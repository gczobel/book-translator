"""S5: compare each scene with its source and apply structured edits to the target blocks.

The reviewer returns edits (target block, old text, new text, reason, category) for omissions,
additions, meaning drift, flattened tense or free indirect speech and wrong forms of address.
An edit that cannot be applied exactly, breaks inline codes, changes a locked motif or a glossary
rendering, or brings in a banned variant is dropped and recorded with its reason; the other edits
of the answer are kept. Edits are applied in one step per scene and recorded for the quality
report.
"""

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, BeforeValidator, Field, PrivateAttr, model_validator

from book_translator.bible import Bible
from book_translator.epub import Epub
from book_translator.inline import EncodedBlock, InlineCodeError
from book_translator.llm import LLM, LLMRequest
from book_translator.progress import Tick, no_tick
from book_translator.stages.context import bible_slice
from book_translator.tk_gate import require_no_open_tks
from book_translator.tolerance import choice

PROMPT_VERSION = "fidelity-v1"
_PROMPT = (
    "Compare the scene's target blocks with their source blocks. Return an edit for each "
    "omission, addition, meaning drift, flattened tense or free indirect speech, and wrong form "
    "of address (check the address grid). Edit only what is wrong: `old` must appear in the "
    "target block (block id and position), keep inline codes, and never change a locked motif or "
    "a glossary rendering."
)

_CATEGORIES = Literal[
    "omission",
    "addition",
    "meaning drift",
    "flattened tense or free indirect speech",
    "wrong form of address",
]


Category = Annotated[_CATEGORIES, BeforeValidator(choice(*get_args(_CATEGORIES)))]

_QUOTES = {"'": "['‘’]", "’": "['‘’]", "‘": "['‘’]", '"': '["“”]', "“": '["“”]', "”": '["“”]'}


def locate(old: str, text: str) -> str:
    """The stretch of `text` that `old` quotes, if it differs only in spacing, case or quote
    marks and there is exactly one; otherwise `old` itself."""
    if old in text:
        return old
    tokens = old.split()
    if not tokens:
        return old
    pattern = r"\s+".join("".join(_QUOTES.get(c) or re.escape(c) for c in t) for t in tokens)
    found = list(re.finditer(pattern, text, re.IGNORECASE))
    return found[0].group(0) if len(found) == 1 else old


class Edit(BaseModel):
    block: str  # id of the source block whose target is edited
    position: int  # which of its target blocks
    old: str = Field(min_length=1)
    new: str
    reason: str
    category: Category


@dataclass(frozen=True)
class Dropped:
    """An edit left out of a review, and why."""

    edit: Edit
    why: str


class Review(BaseModel):
    edits: list[Edit] = []
    _dropped: list[Dropped] = PrivateAttr(default_factory=list)

    @property
    def dropped(self) -> list[Dropped]:
        return self._dropped


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
    db.execute(
        "create table if not exists fidelity_dropped (id integer primary key autoincrement,"
        " block text not null, position integer not null, old text not null, new text not null,"
        " why text not null)"
    )


def _renderings(bible: Bible) -> list[str]:
    return [g.rendering for g in bible.glossary] + [m.locked_rendering for m in bible.motifs]


def _banned(bible: Bible) -> list[str]:
    return [v for g in bible.glossary for v in g.banned_variants]


def check_rewrite(old: str, new: str, bible: Bible, where: str) -> None:
    """Raise ValueError unless rewriting `old` as `new` keeps every locked rendering and brings
    in no banned variant."""
    for rendering in _renderings(bible):
        if rendering and new.count(rendering) < old.count(rendering):
            raise ValueError(f"{where}: it would change the locked rendering {rendering!r}")
    for variant in _banned(bible):
        if variant and variant in new and variant not in old:
            raise ValueError(f"{where}: it brings in the banned variant {variant!r}")


def _apply(edit: Edit, texts: dict[int, str], bible: Bible) -> None:
    """Apply one edit to a block's target texts, or raise ValueError saying why it cannot be."""
    where = f"edit of block {edit.block}, target {edit.position}"
    if edit.position not in texts:
        raise ValueError(f"{where}: there is no such target block")
    text = texts[edit.position]
    if edit.old not in text:
        raise ValueError(f"{where}: the old text {edit.old!r} is not in the target block")
    check_rewrite(edit.old, edit.new, bible, where)
    texts[edit.position] = text.replace(edit.old, edit.new, 1)


def review_schema(
    ids: list[str],
    targets: dict[str, dict[int, str]],
    encoded: dict[str, EncodedBlock],
    bible: Bible,
    strict: bool = False,
) -> type[Review]:
    """The review's schema for this scene: the edits that apply, are legal and stay within the
    bible are kept; the others are listed as dropped. A strict schema rejects the whole answer
    instead, so the call is retried."""

    class SceneReview(Review):
        @model_validator(mode="before")
        @classmethod
        def _find_the_old_text(cls, data: Any) -> Any:
            if not isinstance(data, dict) or not isinstance(data.get("edits"), list):
                return data
            edits = []
            for e in data["edits"]:
                if isinstance(e, dict) and isinstance(e.get("old"), str):
                    block, position = e.get("block"), e.get("position")
                    if isinstance(block, str) and isinstance(position, int):
                        text = targets.get(block, {}).get(position)
                        if text is not None:
                            e = {**e, "old": locate(e["old"], text)}
                edits.append(e)
            return {**data, "edits": edits}

        @model_validator(mode="after")
        def _applicable(self) -> "SceneReview":
            result = {i: dict(t) for i, t in targets.items()}
            kept: list[Edit] = []
            dropped: list[Dropped] = []
            for edit in self.edits:
                try:
                    if edit.block not in ids:
                        raise ValueError(f"edit for a block outside the scene: {edit.block}")
                    texts = dict(result[edit.block])
                    _apply(edit, texts, bible)
                    try:
                        encoded[edit.block].validate_pieces([texts[p] for p in sorted(texts)])
                    except InlineCodeError as exc:
                        raise ValueError(f"block {edit.block}: {exc}") from exc
                except ValueError as exc:
                    dropped.append(Dropped(edit, str(exc)))
                    continue
                result[edit.block] = texts
                kept.append(edit)
            if strict and dropped:
                raise ValueError(dropped[0].why)
            self.edits = kept
            self._dropped = dropped
            return self

    return SceneReview


def scene_targets(db: sqlite3.Connection, scene: Scene) -> dict[str, dict[int, str]]:
    """The scene's target texts by source block id and position."""
    targets: dict[str, dict[int, str]] = defaultdict(dict)
    for block, position, text in db.execute(
        "select source, position, text from targets order by source, position"
    ):
        if block in scene.ids:
            targets[str(block)][int(position)] = str(text)
    return targets


def review_request(
    stage: str,
    prompt_version: str,
    model: str,
    scene: Scene,
    targets: dict[str, dict[int, str]],
    bible: Bible,
    encoded: dict[str, EncodedBlock],
) -> LLMRequest:
    """The request asking a reviewer to compare the scene's targets with its source."""
    shown = " ".join(e.text for e in encoded.values())
    view = [
        {
            "id": i,
            "source": encoded[i].text,
            "targets": [{"position": p, "text": t} for p, t in sorted(targets.get(i, {}).items())],
        }
        for i in scene.ids
    ]
    return LLMRequest(
        stage=stage,
        prompt_version=prompt_version,
        model=model,
        prompt=_PROMPT,
        bible_slice=bible_slice(bible, shown, scene.chapter, scene.ids),
        source_text=json.dumps({"scene": view}),
    )


def review(
    db: sqlite3.Connection,
    llm: LLM,
    source: Epub,
    bible: Bible,
    model: str,
    progress: Tick = no_tick,
) -> None:
    """Review every scene not yet reviewed. A scene's edits are applied in one step."""
    require_no_open_tks(db)
    done = {str(r[0]) for r in db.execute("select first_block from reviewed_scenes")}
    all_scenes = scenes(source)
    for index, scene in enumerate(all_scenes):
        if scene.ids[0] in done:
            continue
        progress.begin(index, len(all_scenes))
        targets = scene_targets(db, scene)
        encoded = {i: source.encode_block(i) for i in scene.ids}
        request = review_request("fidelity", PROMPT_VERSION, model, scene, targets, bible, encoded)
        result = llm.call(request, review_schema(scene.ids, targets, encoded, bible)).output
        with db:
            for dropped in result.dropped:
                db.execute(
                    "insert into fidelity_dropped (block, position, old, new, why)"
                    " values (?, ?, ?, ?, ?)",
                    (
                        dropped.edit.block,
                        dropped.edit.position,
                        dropped.edit.old,
                        dropped.edit.new,
                        dropped.why,
                    ),
                )
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
        progress(index + 1, len(all_scenes))
