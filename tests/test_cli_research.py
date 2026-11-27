"""Seam 1: the CLI. S1 web research observed through the workspace database and search calls."""

import json
import sqlite3
from pathlib import Path

from book_translator import main
from book_translator.config import STAGE_MODELS
from book_translator.epub import open_epub
from book_translator.llm import request_key
from book_translator.replay import ReplayAdapter
from book_translator.search import Finding
from book_translator.stages.extract import extraction_request

FIXTURES = Path(__file__).parent / "fixtures" / "epub"
EPUB = FIXTURES / "plain.epub"


class FixtureSearch:
    """A fixture-backed search adapter: canned findings, and a record of how it was asked."""

    def __init__(self, findings: list[Finding]) -> None:
        self._findings = findings
        self.calls: list[tuple[str, str, bool]] = []

    def lookup(self, query: str, language: str, *, established: bool) -> list[Finding]:
        self.calls.append((query, language, established))
        return [f for f in self._findings if established or f.rendering is None]


def adapter() -> ReplayAdapter:
    source = open_epub(EPUB)
    out = {}
    for chapter in source.book().chapters:
        text = "\n".join(source.encode_block(b.id).text for s in chapter.scenes for b in s.blocks)
        key = request_key(extraction_request(STAGE_MODELS["analysis"], text))
        out[key] = json.dumps({"names": [], "places": [], "phrases": []})
    return ReplayAdapter(out)


def init(tmp_path: Path, *flags: str) -> Path:
    path = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral", *flags])
    return path


def rows(workspace: Path, sql: str) -> list[tuple[object, ...]]:
    with sqlite3.connect(workspace / "book.sqlite") as db:
        return db.execute(sql).fetchall()


PLACE = Finding("Synthetic Tale", "A tale about a place.", "https://en.wikipedia.org/wiki/X")
TERM = Finding("Wand", "A magic stick.", "https://www.wikidata.org/wiki/Q1", rendering="Varita")


def test_research_is_stored_with_a_source_url_per_entry(tmp_path: Path) -> None:
    ws = init(tmp_path)

    main(["run", str(ws)], adapter=adapter(), search=FixtureSearch([PLACE]))

    assert rows(ws, "select term, summary, url from research") == [
        ("Synthetic Tale", "A tale about a place.", "https://en.wikipedia.org/wiki/X")
    ]
    assert rows(ws, "select status from stages where stage = 'research'") == [("done",)]


def test_established_terms_are_marked_with_their_source(tmp_path: Path) -> None:
    ws = init(tmp_path)

    main(["run", str(ws)], adapter=adapter(), search=FixtureSearch([TERM]))

    assert rows(ws, "select term, rendering, origin, source from glossary") == [
        ("Wand", "Varita", "established", "https://www.wikidata.org/wiki/Q1")
    ]


def test_research_that_finds_nothing_is_recorded_and_the_run_proceeds(tmp_path: Path) -> None:
    ws = init(tmp_path)

    main(["run", str(ws)], adapter=adapter(), search=FixtureSearch([]))

    assert rows(ws, "select status from stages where stage = 'research'") == [("nothing found",)]
    assert rows(ws, "select status from stages where stage = 'extraction'") == [("done",)]


def test_evaluation_mode_disables_established_terminology(tmp_path: Path) -> None:
    ws = init(tmp_path, "--evaluation")
    search = FixtureSearch([PLACE, TERM])

    main(["run", str(ws)], adapter=adapter(), search=search)

    assert search.calls
    assert all(not established for _, _, established in search.calls)
    assert rows(ws, "select count(*) from glossary") == [(0,)]
    assert rows(ws, "select term from research") == [("Synthetic Tale",)]


def test_research_is_not_repeated_on_a_second_run(tmp_path: Path) -> None:
    ws = init(tmp_path)
    main(["run", str(ws)], adapter=adapter(), search=FixtureSearch([PLACE]))

    again = FixtureSearch([PLACE])
    main(["run", str(ws)], adapter=adapter(), search=again)

    assert again.calls == []
