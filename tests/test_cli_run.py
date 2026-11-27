"""Seam 1: the CLI. `run` observed through the workspace database and the LLM calls made."""

import json
import sqlite3
from pathlib import Path

import pytest

from book_translator import main
from book_translator.config import STAGE_MODELS
from book_translator.epub import open_epub
from book_translator.llm import LLMRequest, RawAnswer, request_key
from book_translator.replay import ReplayAdapter
from book_translator.stages.extract import extraction_request

FIXTURES = Path(__file__).parent / "fixtures" / "epub"


class CountingAdapter:
    """A replay adapter that counts its calls and can fail after a number of them."""

    def __init__(self, recordings: dict[str, str], fail_after: int | None = None) -> None:
        self._replay = ReplayAdapter(recordings)
        self._fail_after = fail_after
        self.calls = 0

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if self._fail_after is not None and self.calls >= self._fail_after:
            raise KeyboardInterrupt
        self.calls += 1
        return self._replay.complete(request, key, attempt)


def recordings(epub: Path) -> dict[str, str]:
    source = open_epub(epub)
    out = {}
    for i, chapter in enumerate(source.book().chapters, 1):
        text = "\n".join(source.encode_block(b.id).text for s in chapter.scenes for b in s.blocks)
        request = extraction_request(STAGE_MODELS["analysis"], text)
        out[request_key(request)] = json.dumps(
            {"names": [f"Name{i}"], "places": [f"Place{i}"], "phrases": [f"Phrase{i}"]}
        )
    return out


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    main(["init", str(FIXTURES / "plain.epub"), "--workspace", str(path), "--variety", "neutral"])
    return path


def rows(workspace: Path, sql: str) -> list[tuple[object, ...]]:
    with sqlite3.connect(workspace / "book.sqlite") as db:
        return db.execute(sql).fetchall()


def test_run_extracts_names_places_and_phrases_per_chapter(workspace: Path) -> None:
    adapter = CountingAdapter(recordings(FIXTURES / "plain.epub"))

    main(["run", str(workspace)], adapter=adapter)

    stored = rows(workspace, "select chapter, result from extractions order by chapter")
    assert [(c, json.loads(str(r))) for c, r in stored] == [
        (0, {"names": ["Name1"], "places": ["Place1"], "phrases": ["Phrase1"]}),
        (1, {"names": ["Name2"], "places": ["Place2"], "phrases": ["Phrase2"]}),
    ]
    assert rows(workspace, "select stage, status from stages") == [("extraction", "done")]


def test_an_interrupted_run_resumes_without_repeating_calls(workspace: Path) -> None:
    recorded = recordings(FIXTURES / "plain.epub")
    first = CountingAdapter(recorded, fail_after=1)
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(workspace)], adapter=first)
    assert rows(workspace, "select stage, status from stages") == [("extraction", "running")]
    assert rows(workspace, "select count(*) from extractions") == [(1,)]

    second = CountingAdapter(recorded)
    main(["run", str(workspace)], adapter=second)

    assert first.calls + second.calls == 2
    assert rows(workspace, "select stage, status from stages") == [("extraction", "done")]
    assert rows(workspace, "select count(*) from extractions") == [(2,)]


def test_running_a_finished_stage_costs_nothing(workspace: Path) -> None:
    main(["run", str(workspace)], adapter=CountingAdapter(recordings(FIXTURES / "plain.epub")))

    again = CountingAdapter({})
    main(["run", str(workspace)], adapter=again)

    assert again.calls == 0
