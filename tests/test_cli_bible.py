"""Seam 1: the CLI. S1 consolidation (book bible, part 1) observed in the workspace database."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from book_translator.config import STAGE_MODELS
from book_translator.epub import open_epub
from book_translator.llm import InvalidOutputError, LLMRequest, RawAnswer, request_key
from book_translator.replay import ReplayAdapter
from book_translator.search import Finding
from book_translator.stages.extract import extraction_request

EPUB = Path(__file__).parent / "fixtures" / "epub" / "plain.epub"

PROFILE = {
    "genre": "gothic comedy",
    "period": "late nineteenth century",
    "setting": "an English country house",
    "narrator": "third person",
    "narrator_distance": "ironic, close to the family",
    "tense": "past",
    "narrative_register": "refined, wry",
    "foreignness": "keep the English manners visible",
}
STYLE = {
    "dialogue": "inline-quotes",
    "thoughts": "italics",
    "numbers": "words",
    "titles": "keep the honorific",
}
CAST = [
    {"name": "Hiram", "aliases": ["Mr. Otis"], "gender": "male", "role": "the new owner"},
    {"name": "Sir Simon", "aliases": ["the ghost"], "gender": "male", "role": "the haunter"},
]
VOICE = {
    "character": "Sir Simon",
    "speech_register": "archaic, theatrical",
    "tics": ["sighs before speaking"],
    "never_says": ["okay"],
    "sample_lines": ["Woe betide the house!"],
}


def bible(**overrides: object) -> dict[str, object]:
    out: dict[str, object] = {
        "profile": PROFILE,
        "style": STYLE,
        "cast": CAST,
        "voice_cards": [VOICE],
    }
    out.update(overrides)
    return out


class BibleAdapter:
    """Replay for extraction; recorded answers (one per attempt) for the consolidation call."""

    def __init__(self, answers: list[str], fail_after: int | None = None) -> None:
        source = open_epub(EPUB)
        recorded = {}
        for chapter in source.book().chapters:
            text = "\n".join(
                source.encode_block(b.id).text for s in chapter.scenes for b in s.blocks
            )
            key = request_key(extraction_request(STAGE_MODELS["analysis"], text))
            recorded[key] = json.dumps({"names": ["Hiram"], "places": ["Kent"], "phrases": []})
        self._replay = ReplayAdapter(recorded)
        self._answers = answers
        self._fail_after = fail_after
        self.requests: list[LLMRequest] = []
        self.calls = 0

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage == "enrichment":  # covered in test_cli_enrichment.py
            return RawAnswer("{}")
        if self._fail_after is not None and self.calls >= self._fail_after:
            raise KeyboardInterrupt
        self.calls += 1
        if request.stage == "completion":
            return RawAnswer("{}")  # part 2 is covered in test_cli_bible_part2.py
        if request.stage != "consolidation":
            return self._replay.complete(request, key, attempt)
        self.requests.append(request)
        return RawAnswer(self._answers[min(attempt, len(self._answers) - 1)])


class FixtureSearch:
    def lookup(self, query: str, language: str, *, established: bool) -> list[Finding]:
        return [Finding("Canterville", "A haunted chase in Kent.", "https://example.org/c")]


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


def status(ws: Path, stage: str) -> list[tuple[object, ...]]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        return db.execute("select status from stages where stage = ?", (stage,)).fetchall()


def test_consolidation_stores_profile_style_cast_and_voice_cards(ws: Path) -> None:
    main(["run", str(ws)], adapter=BibleAdapter([json.dumps(bible())]))

    result = stored(ws)
    assert result["profile"] == PROFILE
    assert result["style"] == STYLE
    assert result["cast"] == CAST
    assert result["voice_cards"] == [VOICE]
    assert status(ws, "consolidation") == [("done",)]


def test_dialogue_defaults_to_raya_split(ws: Path) -> None:
    style = {"thoughts": "italics", "numbers": "words", "titles": "keep"}

    main(["run", str(ws)], adapter=BibleAdapter([json.dumps(bible(style=style))]))

    assert stored(ws)["style"]["dialogue"] == "raya-split"


def test_an_unknown_dialogue_setting_is_never_stored(ws: Path) -> None:
    style = {**STYLE, "dialogue": "guillemets"}

    with pytest.raises(InvalidOutputError):
        main(["run", str(ws)], adapter=BibleAdapter([json.dumps(bible(style=style))]))

    with sqlite3.connect(ws / "book.sqlite") as db:
        assert db.execute("select count(*) from bible").fetchone() == (0,)
    assert status(ws, "consolidation") != [("done",)]


def test_a_voice_card_for_someone_outside_the_cast_is_retried(ws: Path) -> None:
    stray = bible(voice_cards=[{**VOICE, "character": "Nobody"}])
    adapter = BibleAdapter([json.dumps(stray), json.dumps(bible())])

    main(["run", str(ws)], adapter=adapter)

    assert stored(ws)["voice_cards"] == [VOICE]
    assert len(adapter.requests) == 2


def test_consolidation_reads_the_extractions_and_the_research(ws: Path) -> None:
    adapter = BibleAdapter([json.dumps(bible())])

    main(["run", str(ws)], adapter=adapter, search=FixtureSearch())

    (request,) = adapter.requests
    assert request.model == STAGE_MODELS["consolidation"]
    assert "Hiram" in request.source_text
    assert "A haunted chase in Kent." in request.source_text


def test_an_interrupted_consolidation_resumes_without_repeating_calls(ws: Path) -> None:
    first = BibleAdapter([json.dumps(bible())], fail_after=2)
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(ws)], adapter=first)
    assert status(ws, "extraction") == [("done",)]

    second = BibleAdapter([json.dumps(bible())])
    main(["run", str(ws)], adapter=second)
    assert second.calls == 2  # consolidation, then completion

    third = BibleAdapter([])
    main(["run", str(ws)], adapter=third)
    assert third.calls == 0
    assert stored(ws)["cast"] == CAST
