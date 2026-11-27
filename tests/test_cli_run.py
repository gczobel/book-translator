"""Seam 1: the CLI. `run` observed through the workspace database and the LLM calls made."""

import json
import sqlite3
from pathlib import Path

import pytest

from book_translator import main
from book_translator.config import STAGE_MODELS
from book_translator.epub import open_epub
from book_translator.llm import LLMRequest, RawAnswer, request_key
from book_translator.pydantic_ai_adapter import PydanticAIAdapter
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


# Each replayed call costs $0.0105 (1000 input and 500 output tokens at the sonnet price).
def costly(recorded: dict[str, str], **kwargs: int | None) -> CountingAdapter:
    adapter = CountingAdapter(recorded, **kwargs)
    adapter._replay = ReplayAdapter(recorded, input_tokens=1000, output_tokens=500)
    return adapter


def test_the_run_stops_before_the_call_that_would_cross_the_cap(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = costly(recordings(FIXTURES / "plain.epub"))

    with pytest.raises(SystemExit) as stop:
        main(["run", str(workspace), "--cap", "0.015"], adapter=adapter)

    assert adapter.calls == 1
    assert "cap" in str(stop.value).lower()
    assert rows(workspace, "select count(*) from extractions") == [(1,)]
    assert rows(workspace, "select stage, status from stages") == [("extraction", "running")]


def test_raising_the_cap_resumes_without_repeating_or_losing_work(workspace: Path) -> None:
    recorded = recordings(FIXTURES / "plain.epub")
    first = costly(recorded)
    with pytest.raises(SystemExit):
        main(["run", str(workspace), "--cap", "0.015"], adapter=first)

    second = costly(recorded)
    main(["run", str(workspace), "--cap", "1"], adapter=second)

    assert first.calls + second.calls == 2
    assert rows(workspace, "select count(*) from extractions") == [(2,)]
    assert rows(workspace, "select stage, status from stages") == [("extraction", "done")]
    assert rows(workspace, "select round(sum(cost_usd), 4) from spend") == [(0.021,)]


def test_a_run_over_a_tiny_cap_stops_before_any_call_when_the_cap_is_spent(
    workspace: Path,
) -> None:
    recorded = recordings(FIXTURES / "plain.epub")
    with pytest.raises(SystemExit):
        main(["run", str(workspace), "--cap", "0.015"], adapter=costly(recorded))

    again = costly(recorded)
    with pytest.raises(SystemExit):
        main(["run", str(workspace)], adapter=again)

    assert again.calls == 0


def test_run_without_a_provider_key_exits_with_a_clear_message(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(SystemExit) as stop:
        main(["run", str(workspace)])

    assert "ANTHROPIC_API_KEY" in str(stop.value)


def test_run_builds_the_production_adapter_when_the_key_is_set(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    built: list[object] = []

    def fake_run(path: Path, adapter: object) -> None:
        built.append(adapter)

    monkeypatch.setattr("book_translator.cli.run", fake_run)

    main(["run", str(workspace)])

    assert isinstance(built[0], PydanticAIAdapter)
