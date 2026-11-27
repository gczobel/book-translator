"""S6: polish the Spanish scene by scene with the source withheld.

The polisher sees only the target blocks (ids and texts, never the source), so the prose is
judged as Spanish. Its answer must give back every block of the scene, in order, with the same
number of target blocks each (ADR 0001: no merging, no new splits), keep locked motifs and
glossary renderings, bring in no banned variant and keep inline codes balanced; otherwise the
call is retried. Each changed target block is recorded for the quality report.
"""

import json
import sqlite3
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, model_validator

from book_translator.bible import Bible
from book_translator.epub import Epub
from book_translator.inline import EncodedBlock, InlineCodeError
from book_translator.llm import LLM, LLMRequest
from book_translator.progress import Tick, no_tick
from book_translator.stages.context import bible_slice
from book_translator.stages.fidelity import check_rewrite, scenes
from book_translator.tolerance import in_order

PROMPT_VERSION = "polish-v1"
_PROMPT = (
    "Polish the Spanish prose of this scene so that it reads as if it had been written in "
    "Spanish: natural rhythm, idiom and flow. You are not given the original; do not add or "
    "drop content. Return every block id in the same order with the same number of texts. Keep "
    "inline codes, locked motifs and glossary renderings exactly as they are."
)


class PolishedBlock(BaseModel):
    id: str
    texts: list[str]


class Polished(BaseModel):
    blocks: list[PolishedBlock]


def create_tables(db: sqlite3.Connection) -> None:
    db.execute("create table if not exists polished_scenes (first_block text primary key)")
    db.execute(
        "create table if not exists polish_edits (id integer primary key autoincrement,"
        " stage text not null, block text not null, position integer not null,"
        " old text not null, new text not null)"
    )


def polish_schema(
    ids: list[str],
    targets: dict[str, dict[int, str]],
    encoded: dict[str, EncodedBlock],
    bible: Bible,
) -> type[Polished]:
    """The polish's schema for this scene: the same blocks, legal, and within the bible."""

    class ScenePolished(Polished):
        @model_validator(mode="before")
        @classmethod
        def _settle_order(cls, data: Any) -> Any:
            if not isinstance(data, dict):
                return data
            return {**data, "blocks": in_order(data.get("blocks"), ids, "id")}

        @model_validator(mode="after")
        def _faithful_to_the_scene(self) -> "ScenePolished":
            if [b.id for b in self.blocks] != ids:
                raise ValueError(f"the blocks must be exactly {ids} in this order")
            for block in self.blocks:
                old = [targets[block.id][p] for p in sorted(targets[block.id])]
                if len(block.texts) != len(old):
                    raise ValueError(
                        f"block {block.id} has {len(old)} target blocks, not {len(block.texts)}"
                    )
                check_rewrite("\n".join(old), "\n".join(block.texts), bible, f"block {block.id}")
                try:
                    encoded[block.id].validate_pieces(block.texts)
                except InlineCodeError as exc:
                    raise ValueError(f"block {block.id}: {exc}") from exc
            return self

    return ScenePolished


def polish(
    db: sqlite3.Connection,
    llm: LLM,
    source: Epub,
    bible: Bible,
    model: str,
    progress: Tick = no_tick,
) -> None:
    """Polish every scene not yet polished. A scene's changes are applied in one step."""
    done = {str(r[0]) for r in db.execute("select first_block from polished_scenes")}
    all_scenes = scenes(source)
    for index, scene in enumerate(all_scenes):
        if scene.ids[0] in done:
            continue
        targets: dict[str, dict[int, str]] = defaultdict(dict)
        for block, position, text in db.execute(
            "select source, position, text from targets order by source, position"
        ):
            if block in scene.ids:
                targets[str(block)][int(position)] = str(text)
        encoded = {i: source.encode_block(i) for i in scene.ids}
        shown = " ".join(e.text for e in encoded.values())  # picks the bible slice; never sent
        view = [
            {
                "id": i,
                "targets": [{"position": p, "text": t} for p, t in sorted(targets[i].items())],
            }
            for i in scene.ids
        ]
        request = LLMRequest(
            stage="polish",
            prompt_version=PROMPT_VERSION,
            model=model,
            prompt=_PROMPT,
            bible_slice=bible_slice(bible, shown, scene.chapter, scene.ids),
            source_text=json.dumps({"scene": view}),
        )
        result = llm.call(request, polish_schema(scene.ids, targets, encoded, bible)).output
        with db:
            for block in result.blocks:
                for position, new in zip(sorted(targets[block.id]), block.texts, strict=True):
                    old = targets[block.id][position]
                    if new == old:
                        continue
                    db.execute(
                        "update targets set text = ? where source = ? and position = ?",
                        (new, block.id, position),
                    )
                    db.execute(
                        "insert into polish_edits (stage, block, position, old, new)"
                        " values ('polish', ?, ?, ?, ?)",
                        (block.id, position, old, new),
                    )
            db.execute("insert into polished_scenes values (?)", (scene.ids[0],))
        progress(index + 1, len(all_scenes))
