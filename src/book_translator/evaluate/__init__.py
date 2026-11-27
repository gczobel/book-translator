"""`evaluate`: compare the exported EPUB with a reference translation and write a quality report.

The reference text is read only here and never feeds a translation stage (ADR 0004): no stage
module imports this package.
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from book_translator.budget import Budget
from book_translator.config import STAGE_MODELS
from book_translator.epub import open_epub
from book_translator.evaluate import chrf
from book_translator.evaluate.align import ChapterShape, align_blocks, align_chapters
from book_translator.evaluate.comet import CometScorer, comet_scores
from book_translator.evaluate.embed import Embedder
from book_translator.evaluate.judge import SceneView, judge_scenes
from book_translator.evaluate.judge import diagnose as diagnose_report
from book_translator.evaluate.report import render_markdown, workspace_facts
from book_translator.llm import LLM, Adapter
from book_translator.qa import setting
from book_translator.workspace import DB_NAME, SOURCE_NAME

REPORT_JSON = "quality-report.json"
REPORT_MD = "quality-report.md"


class EvaluateError(Exception):
    pass


@dataclass(frozen=True)
class _Chapter:
    title: str | None
    scenes: list[list[str]]

    @property
    def blocks(self) -> list[str]:
        return [b for scene in self.scenes for b in scene]

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
        _Chapter(c.title, [[b.text.strip() for b in s.blocks if b.text.strip()] for s in c.scenes])
        for c in book.chapters
    ]


def _facts(workspace: Path) -> dict[str, Any]:
    db = sqlite3.connect(f"file:{workspace / DB_NAME}?mode=ro", uri=True)
    try:
        return workspace_facts(db)
    finally:
        db.close()


def _scene_views(
    source: Path, ours: list[_Chapter], refs: dict[tuple[int, int], list[str]]
) -> list[SceneView]:
    """Each of our scenes with the source scene at the same place and its aligned reference."""
    chapters = open_epub(source).book().chapters
    views: list[SceneView] = []
    for c, chapter in enumerate(ours):
        src = chapters[c].scenes if c < len(chapters) else []
        for s, scene in enumerate(chapter.scenes):
            text = " ".join(b.text for b in src[s].blocks) if s < len(src) else ""
            views.append(
                SceneView(c + 1, s + 1, text, " ".join(scene), " ".join(refs.get((c, s), [])))
            )
    return views


def evaluate(
    workspace: Path,
    reference: Path,
    embedder: Embedder,
    *,
    adapter: Adapter | None = None,
    judge: bool = False,
    diagnose: bool = False,
    comet: CometScorer | None = None,
) -> Path:
    """Write the report next to the workspace's database; returns the JSON file.

    `judge` and `diagnose` are the optional LLM parts and need `adapter`; `comet` is an optional
    COMET scorer.
    """
    database = workspace / DB_NAME
    db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        target = setting(db, "target") or "es"
        evaluation_mode = setting(db, "evaluation") != ""
        output = workspace / f"{workspace.resolve().name}.{target}.epub"
        if not output.is_file():
            raise EvaluateError("no output to evaluate: run `book-translator export` first")
    finally:
        db.close()
    ours, theirs = _chapters(output), _chapters(reference)
    refs: dict[tuple[int, int], list[str]] = {}
    scores = _score(ours, theirs, embedder, refs)
    report: dict[str, Any] = {
        "output": output.name,
        "reference": reference.name,
        "evaluation_mode": evaluation_mode,
        **scores,
    }
    views = _scene_views(workspace / SOURCE_NAME, ours, refs) if judge or comet is not None else []
    if comet is not None:
        report["comet"] = comet_scores(comet, views)
    if (judge or diagnose) and adapter is None:
        raise EvaluateError("the judge and the diagnosis need an LLM adapter")
    llm = LLM(adapter, database, budget=Budget(database)) if adapter is not None else None
    if judge and llm is not None:
        report["judge"] = judge_scenes(llm, STAGE_MODELS["judge"], views)
    report.update(_facts(workspace))
    if diagnose and llm is not None:
        # Cost varies run to run (it includes earlier diagnoses), so it stays out of the request
        # and a rerun hits the cache.
        facts = {k: v for k, v in report.items() if k != "cost"}
        report["diagnosis"] = diagnose_report(llm, STAGE_MODELS["diagnosis"], facts)
        report["cost"] = _facts(workspace)["cost"]
    (workspace / REPORT_JSON).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (workspace / REPORT_MD).write_text(render_markdown(report), encoding="utf-8")
    return workspace / REPORT_JSON


def _score(
    ours: list[_Chapter],
    theirs: list[_Chapter],
    embedder: Embedder,
    scene_refs: dict[tuple[int, int], list[str]],
) -> dict[str, Any]:
    """chrF per chapter; fills `scene_refs` with the reference blocks aligned to each of our
    scenes, keyed by (0-based chapter, 0-based scene)."""
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
        our_blocks = [
            (i, n, b) for i in group.ours for n, scene in enumerate(ours[i].scenes) for b in scene
        ]
        their_blocks = [b for j in group.theirs for b in theirs[j].blocks]
        for i in group.ours:
            ref_titles[i] = [theirs[j].title or "(untitled)" for j in group.theirs]
        owner = group.ours[0]
        for span in align_blocks([b for _, _, b in our_blocks], their_blocks, embedder):
            if span.ours:
                owner = our_blocks[span.ours[0]][0]
            hyp = " ".join(our_blocks[i][2] for i in span.ours)
            ref = " ".join(their_blocks[j] for j in span.theirs)
            if span.ours:
                key = our_blocks[span.ours[0]][:2]
                scene_refs[key] = [
                    *scene_refs.get(key, []),
                    *(their_blocks[j] for j in span.theirs),
                ]
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
