"""Seam 1: the CLI. `status` observed through its output; it changes nothing."""

import json
from pathlib import Path

import pytest

from book_translator import main
from book_translator.budget import Budget
from book_translator.config import STAGE_MODELS
from book_translator.epub import open_epub
from book_translator.llm import LLMRequest, RawAnswer, request_key
from book_translator.replay import ReplayAdapter
from book_translator.stages.extract import extraction_request

PLAIN = Path(__file__).parent / "fixtures" / "epub" / "plain.epub"


BIBLE = json.dumps(
    {
        "profile": {
            "genre": "comedy",
            "period": "1880s",
            "setting": "a house",
            "narrator": "third person",
            "narrator_distance": "close",
            "tense": "past",
            "narrative_register": "wry",
            "foreignness": "light",
        },
        "style": {
            "dialogue": "inline-quotes",
            "thoughts": "italics",
            "numbers": "words",
            "titles": "keep",
        },
        "cast": [{"name": "Hiram", "aliases": [], "gender": "male", "role": "owner"}],
        "voice_cards": [],
    }
)


class CountingAdapter:
    """A replay adapter that can be interrupted after a number of calls."""

    def __init__(self, recordings: dict[str, str], fail_after: int | None = None) -> None:
        self._replay = ReplayAdapter(recordings)
        self._fail_after = fail_after
        self.calls = 0

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage == "enrichment":  # covered in test_cli_enrichment.py
            return RawAnswer("{}")
        if self._fail_after is not None and self.calls >= self._fail_after:
            raise KeyboardInterrupt
        self.calls += 1
        if request.stage == "completion":
            return RawAnswer("{}")
        if request.stage == "consolidation":
            return RawAnswer(BIBLE)
        return self._replay.complete(request, key, attempt)


def recordings(epub: Path) -> dict[str, str]:
    source = open_epub(epub)
    out = {}
    for chapter in source.book().chapters:
        text = "\n".join(source.encode_block(b.id).text for s in chapter.scenes for b in s.blocks)
        request = extraction_request(STAGE_MODELS["analysis"], text)
        out[request_key(request)] = '{"names": [], "places": [], "phrases": []}'
    return out


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    main(["init", str(PLAIN), "--workspace", str(path), "--variety", "neutral", "--cap", "5"])
    return path


def status(workspace: Path, capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    main(["status", str(workspace)])
    return capsys.readouterr().out


def test_status_of_a_fresh_workspace(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = status(workspace, capsys)
    assert "Stage: not started" in out
    assert "Progress: 0 of 2 chapters extracted" in out
    assert "Spent: $0.00 of $5.00 cap" in out
    assert "Review gate: none waiting" in out
    assert f"Next: book-translator run {workspace}" in out


def test_status_of_an_interrupted_run(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    adapter = CountingAdapter(recordings(PLAIN), fail_after=1)
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(workspace)], adapter=adapter)
    out = status(workspace, capsys)
    assert "Stage: extraction (running)" in out
    assert "Progress: 1 of 2 chapters extracted" in out
    assert f"Next: book-translator run {workspace}" in out


def test_status_of_a_finished_run_shows_spend(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["run", str(workspace)], adapter=CountingAdapter(recordings(PLAIN)))
    Budget(workspace / "book.sqlite").record("extraction", 1.25)
    out = status(workspace, capsys)
    assert "Stage: enrichment (done)" in out
    assert "Progress: 2 of 2 chapters extracted" in out
    assert "Spent: $1.25 of $5.00 cap" in out
    assert "Next: nothing left to run" in out


def test_status_changes_nothing(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = (workspace / "book.sqlite").read_bytes()
    files = sorted(p.name for p in workspace.iterdir())
    status(workspace, capsys)
    assert (workspace / "book.sqlite").read_bytes() == before
    assert sorted(p.name for p in workspace.iterdir()) == files


def test_status_of_a_missing_workspace_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not a workspace"):
        main(["status", str(tmp_path / "nope")])
