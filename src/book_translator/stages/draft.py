"""S3: translate each scene passage by passage, never leaving a gap, recording TKs.

A passage is a run of consecutive blocks inside one scene, short enough for one request. The
model sees the passage with the blocks around it as read-only context, the part of the bible
that concerns it and how earlier chapters rendered the same terms. Each source block gets one or
more target blocks, stored against its id (ADR 0001); the codec rebuild happens at build time.
"""

import json
import sqlite3
from dataclasses import dataclass

from pydantic import BaseModel, Field, model_validator

from book_translator import tk
from book_translator.bible import Bible
from book_translator.epub import Epub
from book_translator.inline import EncodedBlock, InlineCodeError
from book_translator.llm import LLM, LLMRequest
from book_translator.stages.context import SourceBlock, bible_slice, concordance
from book_translator.tk import DraftedTK

PROMPT_VERSION = "draft-v1"
MAX_PASSAGE_WORDS = 400
CONTEXT_BLOCKS = 3
_PROMPT = (
    "Translate the passage block by block. Give every block of the passage one or more target "
    "blocks, keep inline codes, use the bible and the concordance, and where unsure give a "
    "provisional rendering plus a TK. The context blocks are read-only."
)


class DraftedBlock(BaseModel):
    source: str  # id of the source block
    targets: list[str] = Field(min_length=1)


class Draft(BaseModel):
    blocks: list[DraftedBlock]
    tks: list[DraftedTK] = []


@dataclass(frozen=True)
class Passage:
    chapter: int  # 0-based
    ids: list[str]
    before: list[str]  # ids of the blocks read before it in the same scene
    after: list[str]


def passages(source: Epub) -> list[Passage]:
    out: list[Passage] = []
    for chapter, ch in enumerate(source.book().chapters):
        for scene in ch.scenes:
            ids = [b.id for b in scene.blocks]
            start = 0
            while start < len(ids):
                end, words = start, 0
                while end < len(ids) and (end == start or words < MAX_PASSAGE_WORDS):
                    words += len(scene.blocks[end].text.split())
                    end += 1
                out.append(
                    Passage(
                        chapter,
                        ids[start:end],
                        ids[max(0, start - CONTEXT_BLOCKS) : start],
                        ids[end : end + CONTEXT_BLOCKS],
                    )
                )
                start = end
    return out


def draft_schema(passage: Passage, encoded: dict[str, EncodedBlock]) -> type[Draft]:
    """The draft's schema for this passage: every block answered, in order, with legal codes."""

    class PassageDraft(Draft):
        @model_validator(mode="after")
        def _complete_and_legal(self) -> "PassageDraft":
            if [b.source for b in self.blocks] != passage.ids:
                raise ValueError(
                    f"the answer must cover exactly the blocks {passage.ids}, in order"
                )
            for block in self.blocks:
                try:
                    encoded[block.source].validate_pieces(block.targets)
                except InlineCodeError as exc:
                    raise ValueError(f"block {block.source}: {exc}") from exc
            unknown = [t.block for t in self.tks if t.block not in passage.ids]
            if unknown:
                raise ValueError(f"TKs for blocks outside the passage: {unknown}")
            return self

    return PassageDraft


def create_tables(db: sqlite3.Connection) -> None:
    db.execute(
        "create table if not exists targets (source text not null, position integer not null,"
        " text text not null, primary key (source, position))"
    )
    db.execute("create table if not exists drafted_passages (first_block text primary key)")
    tk.create_tables(db)


def draft(db: sqlite3.Connection, llm: LLM, source: Epub, bible: Bible, model: str) -> None:
    """Draft every passage not yet drafted. A passage's results are stored in one step."""
    done = {str(r[0]) for r in db.execute("select first_block from drafted_passages")}
    blocks = [
        SourceBlock(b.id, chapter, source.encode_block(b.id).text)
        for chapter, ch in enumerate(source.book().chapters)
        for scene in ch.scenes
        for b in scene.blocks
    ]
    text_of = {b.id: b.text for b in blocks}
    for passage in passages(source):
        if passage.ids[0] in done:
            continue
        encoded = {i: source.encode_block(i) for i in passage.ids}
        shown = " ".join(text_of[i] for i in (*passage.before, *passage.ids, *passage.after))
        targets = {
            str(s): str(t)
            for s, t in db.execute(
                "select source, group_concat(text, char(10)) from"
                " (select * from targets order by source, position) group by source"
            )
        }
        earlier = [
            (b, targets[b.id]) for b in blocks if b.chapter < passage.chapter and b.id in targets
        ]

        def view(ids: list[str]) -> list[dict[str, str]]:
            return [{"id": i, "text": text_of[i]} for i in ids]

        request = LLMRequest(
            stage="draft",
            prompt_version=PROMPT_VERSION,
            model=model,
            prompt=_PROMPT,
            bible_slice=bible_slice(
                bible, shown, passage.chapter, [*passage.before, *passage.ids, *passage.after]
            ),
            source_text=json.dumps(
                {
                    "before": view(passage.before),
                    "passage": view(passage.ids),
                    "after": view(passage.after),
                    "concordance": concordance(bible, shown, passage.chapter, earlier),
                }
            ),
        )
        result = llm.call(request, draft_schema(passage, encoded)).output
        with db:
            for block in result.blocks:
                db.executemany(
                    "insert into targets values (?, ?, ?)",
                    [(block.source, n, t) for n, t in enumerate(block.targets)],
                )
            tk.store(db, result.tks)
            db.execute("insert into drafted_passages values (?)", (passage.ids[0],))
