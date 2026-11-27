"""Seam 1: the CLI. S1 completion (book bible, part 2) observed in the workspace database."""

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

CAST = [
    {"name": "Hiram", "aliases": [], "gender": "male", "role": "the new owner"},
    {"name": "Sir Simon", "aliases": [], "gender": "male", "role": "the haunter"},
]
PART1 = {
    "profile": {
        "genre": "gothic comedy",
        "period": "1880s",
        "setting": "an English house",
        "narrator": "third person",
        "narrator_distance": "ironic",
        "tense": "past",
        "narrative_register": "wry",
        "foreignness": "light",
    },
    "style": {"thoughts": "italics", "numbers": "words", "titles": "keep"},
    "cast": CAST,
}
GRID = [
    {"speaker": "Hiram", "addressee": "Sir Simon", "form": "usted"},
    {
        "speaker": "Sir Simon",
        "addressee": "Hiram",
        "form": "tú",
        "from_chapter": 1,
        "to_chapter": 2,
    },
    {"speaker": "Sir Simon", "addressee": "Hiram", "form": "usted", "from_chapter": 3},
]


def part2(**overrides: object) -> dict[str, object]:
    out: dict[str, object] = {"address_grid": GRID}
    out.update(overrides)
    return out


class Part2Adapter:
    """Replay for extraction, a fixed part-1 bible, and recorded completions (one per attempt)."""

    def __init__(self, completions: list[str], fail_after: int | None = None) -> None:
        source = open_epub(EPUB)
        recorded = {}
        for chapter in source.book().chapters:
            text = "\n".join(
                source.encode_block(b.id).text for s in chapter.scenes for b in s.blocks
            )
            key = request_key(extraction_request(STAGE_MODELS["analysis"], text))
            recorded[key] = json.dumps({"names": ["Hiram"], "places": [], "phrases": []})
        self._replay = ReplayAdapter(recorded)
        self._completions = completions
        self._fail_after = fail_after
        self.calls = 0
        self.completion_requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if self._fail_after is not None and self.calls >= self._fail_after:
            raise KeyboardInterrupt
        self.calls += 1
        if request.stage == "consolidation":
            return RawAnswer(json.dumps(PART1))
        if request.stage == "completion":
            self.completion_requests.append(request)
            return RawAnswer(self._completions[min(attempt, len(self._completions) - 1)])
        return self._replay.complete(request, key, attempt)


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


def test_glossary_entries_have_rendering_banned_variants_context_rule_and_origin(
    ws: Path,
) -> None:
    entries: list[dict[str, Any]] = [
        {
            "term": "Canterville Chase",
            "rendering": "Canterville Chase",
            "banned_variants": ["La Caza de Canterville"],
            "context_rule": "keep in English unless the narrator is being ironic",
            "origin": "extracted",
        },
        {"term": "the Chase", "rendering": "la mansión", "origin": "researched"},
    ]

    main(["run", str(ws)], adapter=Part2Adapter([json.dumps(part2(glossary=entries))]))

    glossary = stored(ws)["glossary"]
    assert glossary[0] == entries[0]
    assert glossary[1] == {**entries[1], "banned_variants": [], "context_rule": ""}


def test_an_unknown_glossary_origin_is_retried(ws: Path) -> None:
    bad = part2(glossary=[{"term": "a", "rendering": "b", "origin": "guessed"}])
    adapter = Part2Adapter([json.dumps(bad), json.dumps(part2())])

    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.completion_requests) == 2


def test_established_terms_from_research_join_the_glossary_without_duplicates(ws: Path) -> None:
    found = Finding("Canterville Ghost", "A tale.", "https://example.org/t", "El fantasma")
    model_entry = {
        "term": "canterville ghost",
        "rendering": "El espectro",
        "banned_variants": ["El espectro de Canterville"],
        "origin": "extracted",
    }
    other = {"term": "Otis", "rendering": "Otis", "origin": "extracted"}
    adapter = Part2Adapter([json.dumps(part2(glossary=[model_entry, other]))])

    main(["run", str(ws)], adapter=adapter, search=FixtureSearch([found]))

    glossary = stored(ws)["glossary"]
    assert [g["term"] for g in glossary] == ["Canterville Ghost", "Otis"]
    assert glossary[0]["rendering"] == "El fantasma"
    assert glossary[0]["origin"] == "established"
    assert glossary[0]["banned_variants"] == ["El espectro de Canterville"]


def test_motifs_are_listed_with_their_locked_rendering(ws: Path) -> None:
    motifs = [
        {"name": "the bloodstain", "locked_rendering": "la mancha de sangre"},
        {"name": "Washington's tea", "locked_rendering": "el té", "description": "recurs"},
    ]

    main(["run", str(ws)], adapter=Part2Adapter([json.dumps(part2(motifs=motifs))]))

    assert stored(ws)["motifs"] == [
        {"name": "the bloodstain", "locked_rendering": "la mancha de sangre", "description": ""},
        motifs[1],
    ]


def test_a_motif_without_a_locked_rendering_is_retried(ws: Path) -> None:
    bad = part2(motifs=[{"name": "the bloodstain"}])
    adapter = Part2Adapter([json.dumps(bad), json.dumps(part2())])

    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.completion_requests) == 2


def test_chapter_summaries_and_a_timeline_are_stored_as_drafting_context(ws: Path) -> None:
    summaries = [{"chapter": 1, "summary": "The Otises arrive."}]
    timeline = [{"when": "1887, spring", "event": "the sale of the Chase", "chapter": 1}]

    main(
        ["run", str(ws)],
        adapter=Part2Adapter([json.dumps(part2(summaries=summaries, timeline=timeline))]),
    )

    result = stored(ws)
    assert result["summaries"] == summaries
    assert result["timeline"] == timeline


def test_predicted_cruxes_are_listed_with_type_and_location(ws: Path) -> None:
    cruxes = [
        {"type": "pun", "location": "chapter 1, the ghost's chains"},
        {"type": "lyrics", "location": "chapter 2, the nursery rhyme", "note": "rhymes"},
        {"type": "dialect", "location": "chapter 2, the housekeeper"},
        {"type": "quotation", "location": "chapter 1, the epigraph"},
    ]

    main(["run", str(ws)], adapter=Part2Adapter([json.dumps(part2(cruxes=cruxes))]))

    got = stored(ws)["cruxes"]
    assert [(c["type"], c["location"]) for c in got] == [(c["type"], c["location"]) for c in cruxes]


def test_an_unknown_crux_type_is_retried(ws: Path) -> None:
    bad = part2(cruxes=[{"type": "riddle", "location": "chapter 1"}])
    adapter = Part2Adapter([json.dumps(bad), json.dumps(part2())])

    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.completion_requests) == 2


def test_an_interrupted_completion_resumes_without_repeating_calls(ws: Path) -> None:
    first = Part2Adapter([json.dumps(part2())], fail_after=3)  # 2 extractions + consolidation
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(ws)], adapter=first)
    assert stored(ws)["address_grid"] == []

    second = Part2Adapter([json.dumps(part2())])
    main(["run", str(ws)], adapter=second)
    assert second.calls == 1
    assert len(stored(ws)["address_grid"]) == 3

    third = Part2Adapter([])
    main(["run", str(ws)], adapter=third)
    assert third.calls == 0


def test_a_part_one_bible_stored_by_an_earlier_run_is_completed_on_the_next_run(ws: Path) -> None:
    main(["run", str(ws)], adapter=Part2Adapter([json.dumps(part2())]))
    with sqlite3.connect(ws / "book.sqlite") as db:
        part1 = {"profile", "style", "cast", "voice_cards"}
        old = {k: v for k, v in stored(ws).items() if k in part1}
        db.execute("delete from bible")
        db.execute("insert into bible values (?)", (json.dumps(old),))
        db.execute("delete from stages where stage = 'completion'")

    adapter = Part2Adapter([json.dumps(part2())])
    main(["run", str(ws)], adapter=adapter)

    assert adapter.calls == 0  # the answer was already recorded in the call cache
    assert stored(ws)["cast"] == CAST
    assert len(stored(ws)["address_grid"]) == 3


def test_an_address_rule_for_someone_outside_the_cast_is_retried(ws: Path) -> None:
    stray = part2(address_grid=[{"speaker": "Nobody", "addressee": "Hiram", "form": "tú"}])
    adapter = Part2Adapter([json.dumps(stray), json.dumps(part2())])

    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.completion_requests) == 2
    assert len(stored(ws)["address_grid"]) == 3


def test_a_backwards_chapter_range_is_retried(ws: Path) -> None:
    rule = {"speaker": "Hiram", "addressee": "Sir Simon", "form": "tú"}
    backwards = part2(address_grid=[{**rule, "from_chapter": 3, "to_chapter": 1}])
    adapter = Part2Adapter([json.dumps(backwards), json.dumps(part2())])

    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.completion_requests) == 2


def test_an_unknown_form_of_address_is_never_stored(ws: Path) -> None:
    bad = part2(address_grid=[{"speaker": "Hiram", "addressee": "Sir Simon", "form": "vos"}])

    with pytest.raises(InvalidOutputError):
        main(["run", str(ws)], adapter=Part2Adapter([json.dumps(bad)]))

    assert stored(ws)["address_grid"] == []
