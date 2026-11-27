"""`evaluate`: compare the exported EPUB with a reference translation and write a quality report.

The reference text is read only here and never feeds a translation stage (ADR 0004): no stage
module imports this package.
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from book_translator.epub import open_epub
from book_translator.evaluate import chrf
from book_translator.evaluate.align import ChapterShape, align_blocks, align_chapters
from book_translator.evaluate.embed import Embedder
from book_translator.evaluate.report import render_markdown, workspace_facts
from book_translator.qa import setting
from book_translator.workspace import DB_NAME

REPORT_JSON = "quality-report.json"
REPORT_MD = "quality-report.md"


class EvaluateError(Exception):
    pass


@dataclass(frozen=True)
class _Chapter:
    title: str | None
    blocks: list[str]

    @property
    def size(self) -> int:
        """Characters of body text: a chapter's own heading says nothing about its length."""
        body = self.blocks[1:] if self.blocks and self.blocks[0] == self.title else self.blocks
        return sum(len(b) for b in body)


def _chapters(path: Path) -> list[_Chapter]:
    try:
        book = open_epub(path).book()
    except Exception as exc:  # any unreadable or malformed file
        raise EvaluateError(f"cannot read {path} as an EPUB: {exc}") from exc
    return [
        _Chapter(c.title, [b.text.strip() for s in c.scenes for b in s.blocks if b.text.strip()])
        for c in book.chapters
    ]


def evaluate(workspace: Path, reference: Path, embedder: Embedder) -> Path:
    """Write the report next to the workspace's database; returns the JSON file."""
    db = sqlite3.connect(f"file:{workspace / DB_NAME}?mode=ro", uri=True)
    try:
        target = setting(db, "target") or "es"
        output = workspace / f"{workspace.resolve().name}.{target}.epub"
        if not output.is_file():
            raise EvaluateError("no output to evaluate: run `book-translator export` first")
        facts = workspace_facts(db)
    finally:
        db.close()
    ours, theirs = _chapters(output), _chapters(reference)
    scores = _score(ours, theirs, embedder)
    report: dict[str, Any] = {
        "output": output.name,
        "reference": reference.name,
        **scores,
        **facts,
    }
    (workspace / REPORT_JSON).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (workspace / REPORT_MD).write_text(render_markdown(report), encoding="utf-8")
    return workspace / REPORT_JSON


def _score(ours: list[_Chapter], theirs: list[_Chapter], embedder: Embedder) -> dict[str, Any]:
    stats: list[list[tuple[int, int, int]]] = [chrf.add_stats([]) for _ in ours]
    ref_titles: list[list[str]] = [[] for _ in ours]
    blocks = [0] * len(ours)
    unaligned: list[str] = []
    extra = chrf.add_stats([])
    shapes_ours = [ChapterShape(c.title, c.size) for c in ours]
    shapes_theirs = [ChapterShape(c.title, c.size) for c in theirs]
    for group in align_chapters(shapes_ours, shapes_theirs):
        if not group.ours:
            for j in group.theirs:
                unaligned.append(theirs[j].title or "(untitled)")
                extra = chrf.add_stats([extra, chrf.segment_stats("", " ".join(theirs[j].blocks))])
            continue
        our_blocks = [(i, b) for i in group.ours for b in ours[i].blocks]
        their_blocks = [b for j in group.theirs for b in theirs[j].blocks]
        for i in group.ours:
            ref_titles[i] = [theirs[j].title or "(untitled)" for j in group.theirs]
        owner = group.ours[0]
        for span in align_blocks([b for _, b in our_blocks], their_blocks, embedder):
            if span.ours:
                owner = our_blocks[span.ours[0]][0]
            hyp = " ".join(our_blocks[i][1] for i in span.ours)
            ref = " ".join(their_blocks[j] for j in span.theirs)
            stats[owner] = chrf.add_stats([stats[owner], chrf.segment_stats(hyp, ref)])
            blocks[owner] += len(span.ours) if span.theirs else 0
    chapters = [
        {
            "index": n,
            "title": ours[n - 1].title,
            "chrf": chrf.score(stats[n - 1]),
            "reference_titles": ref_titles[n - 1],
            "aligned_blocks": blocks[n - 1],
        }
        for n in range(1, len(ours) + 1)
    ]
    return {
        "chrf_overall": chrf.score(chrf.add_stats([*stats, extra])),
        "chapters": chapters,
        "unaligned_reference_chapters": unaligned,
    }
