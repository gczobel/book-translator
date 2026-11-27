"""Seam 1: the CLI. S1 completion (book bible, part 2) observed in the workspace database."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from book_translator.llm import LLMRequest, RawAnswer
from book_translator.search import Finding
from test_cli_bible import CAST, BibleAdapter, bible

EPUB = Path(__file__).parent / "fixtures" / "epub" / "plain.epub"

GRID = [
    {"speaker": "Hiram", "addressee": "Sir Simon", "form": "usted"},
    {"speaker": "Sir Simon", "addressee": "Hiram", "form": "tú", "from_chapter": 1, "to_chapter": 2},
    {"speaker": "Sir Simon", "addressee": "Hiram", "form": "usted", "from_chapter": 3},
]


def part2(**overrides: object) -> dict[str, object]:
    out: dict[str, object] = {"address_grid": GRID}
    out.update(overrides)
    return out


class Part2Adapter(BibleAdapter):
    def __init__(self, completions: list[str], fail_after: int | None = None) -> None:
        super().__init__([json.dumps(bible())], fail_after)
        self._completions = completions
        self.completion_requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage != "completion":
            return super().complete(request, key, attempt)
        self.calls += 1
        self.completion_requests.append(request)
        return RawAnswer(self._completions[min(attempt, len(self._completions) - 1)])


class FixtureSearch:
    def __init__(self, findings: list[Finding]) -> None:
        self._findings = findings

    def lookup(self, query: str, language: str, *, established: bool) -> list[Finding]:
        return self._findings


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral"])
    return path


def stored(ws: Path) -> dict[str, Any]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        rows = db.execute("select result from bible").fetchall()
    assert len(rows) == 1
    result: dict[str, Any] = json.loads(rows[0][0])
    return result


def test_the_address_grid_holds_directed_pairs_with_chapter_ranges(ws: Path) -> None:
    main(["run", str(ws)], adapter=Part2Adapter([json.dumps(part2())]))

    result = stored(ws)
    assert result["cast"] == CAST  # part 1 is kept
    grid = result["address_grid"]
    assert [(g["speaker"], g["addressee"], g["form"]) for g in grid] == [
        ("Hiram", "Sir Simon", "usted"),
        ("Sir Simon", "Hiram", "tú"),
        ("Sir Simon", "Hiram", "usted"),
    ]
    assert (grid[0]["from_chapter"], grid[0]["to_chapter"]) == (None, None)
    assert (grid[1]["from_chapter"], grid[1]["to_chapter"]) == (1, 2)
    assert (grid[2]["from_chapter"], grid[2]["to_chapter"]) == (3, None)
