"""S5: compare each scene with its source and apply structured edits to the target blocks.

The reviewer returns edits (target block, old text, new text, reason, category) for omissions,
additions, meaning drift, flattened tense or free indirect speech and wrong forms of address.
An edit that cannot be applied exactly, breaks inline codes, changes a locked motif or a glossary
rendering, or brings in a banned variant makes the whole answer invalid, so the call is retried.
Edits are applied in one step per scene and recorded for the quality report.
"""

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from book_translator.bible import Bible
from book_translator.epub import Epub
from book_translator.inline import EncodedBlock, InlineCodeError
from book_translator.llm import LLM, LLMRequest
from book_translator.stages.context import bible_slice
from book_translator.tk_gate import require_no_open_tks

PROMPT_VERSION = "fidelity-v1"
_PROMPT = (
    "Compare the scene's target blocks with their source blocks. Return an edit for each "
    "omission, addition, meaning drift, flattened tense or free indirect speech, and wrong form "
    "of address (check the address grid). Edit only what is wrong: `old` must appear in the "
    "target block (block id and position), keep inline codes, and never change a locked motif or "
    "a glossary rendering."
)

Category = Literal[
    "omission",
    "addition",
    "meaning drift",
    "flattened tense or free indirect speech",
    "wrong form of address",
]


class Edit(BaseModel):
    block: str  # id of the source block whose target is edited
    position: int  # which of its target blocks
    old: str = Field(min_length=1)
    new: str
    reason: str
    category: Category


class Review(BaseModel):
    edits: list[Edit] = []


@dataclass(frozen=True)
class Scene:
    chapter: int  # 0-based
    ids: list[str]


def scenes(source: Epub) -> list[Scene]:
    return [
        Scene(chapter, [b.id for b in scene.blocks])
        for chapter, ch in enumerate(source.book().chapters)
        for scene in ch.scenes
    ]


def create_tables(db: sqlite3.Connection) -> None:
    db.execute("create table if not exists reviewed_scenes (first_block text primary key)")
    db.execute(
        "create table if not exists fidelity_edits (id integer primary key autoincrement,"
        " block text not null, position integer not null, old text not null, new text not null,"
        " reason text not null, category text not null)"
    )


def _renderings(bible: Bible) -> list[str]:
    return [g.rendering for g in bible.glossary] + [m.locked_rendering for m in bible.motifs]


def _banned(bible: Bible) -> list[str]:
    return [v for g in bible.glossary for v in g.banned_variants]


def _apply(edit: Edit, texts: dict[int, str], bible: Bible) -> None:
    """Apply one edit to a block's target texts, or raise ValueError saying why it cannot be."""
    where = f"edit of block {edit.block}, target {edit.position}"
    if edit.position not in texts:
        raise ValueError(f"{where}: there is no such target block")
    text = texts[edit.position]
    if edit.old not in text:
        raise ValueError(f"{where}: the old text {edit.old!r} is not in the target block")
    for rendering in _renderings(bible):
        if rendering and edit.new.count(rendering) < edit.old.count(rendering):
            raise ValueError(f"{where}: it would change the locked rendering {rendering!r}")
    for variant in _banned(bible):
        if variant and variant in edit.new and variant not in edit.old:
            raise ValueError(f"{where}: it brings in the banned variant {variant!r}")
    texts[edit.position] = text.replace(edit.old, edit.new, 1)


def review_schema(
    ids: list[str],
    targets: dict[str, dict[int, str]],
    encoded: dict[str, EncodedBlock],
    bible: Bible,
) -> type[Review]:
    """The review's schema for this scene: every edit applicable, legal and within the bible."""

    class SceneReview(Review):
        @model_validator(mode="after")
        def _applicable(self) -> "SceneReview":
            result = {i: dict(t) for i, t in targets.items()}
            for edit in self.edits:
                if edit.block not in ids:
                    raise ValueError(f"edit for a block outside the scene: {edit.block}")
                _apply(edit, result[edit.block], bible)
            for edit in self.edits:
                pieces = [result[edit.block][p] for p in sorted(result[edit.block])]
                try:
                    encoded[edit.block].validate_pieces(pieces)
                except InlineCodeError as exc:
                    raise ValueError(f"block {edit.block}: {exc}") from exc
            return self

    return SceneReview


def review(db: sqlite3.Connection, llm: LLM, source: Epub, bible: Bible, model: str) -> None:
    """Review every scene not yet reviewed. A scene's edits are applied in one step."""
    require_no_open_tks(db)
    done = {str(r[0]) for r in db.execute("select first_block from reviewed_scenes")}
    for scene in scenes(source):
        if scene.ids[0] in done:
            continue
        targets: dict[str, dict[int, str]] = defaultdict(dict)
        for block, position, text in db.execute(
            "select source, position, text from targets order by source, position"
        ):
            if block in scene.ids:
                targets[str(block)][int(position)] = str(text)
        encoded = {i: source.encode_block(i) for i in scene.ids}
        shown = " ".join(e.text for e in encoded.values())
        view = [
            {
                "id": i,
                "source": encoded[i].text,
                "targets": [
                    {"position": p, "text": t} for p, t in sorted(targets.get(i, {}).items())
                ],
            }
            for i in scene.ids
        ]
        request = LLMRequest(
            stage="fidelity",
            prompt_version=PROMPT_VERSION,
            model=model,
            prompt=_PROMPT,
            bible_slice=bible_slice(bible, shown, scene.chapter, scene.ids),
            source_text=json.dumps({"scene": view}),
        )
        result = llm.call(request, review_schema(scene.ids, targets, encoded, bible)).output
        with db:
            for edit in result.edits:
                text = str(
                    db.execute(
                        "select text from targets where source = ? and position = ?",
                        (edit.block, edit.position),
                    ).fetchone()[0]
                )
                db.execute(
                    "update targets set text = ? where source = ? and position = ?",
                    (text.replace(edit.old, edit.new, 1), edit.block, edit.position),
                )
                db.execute(
                    "insert into fidelity_edits (block, position, old, new, reason, category)"
                    " values (?, ?, ?, ?, ?, ?)",
                    (edit.block, edit.position, edit.old, edit.new, edit.reason, edit.category),
                )
            db.execute("insert into reviewed_scenes values (?)", (scene.ids[0],))
