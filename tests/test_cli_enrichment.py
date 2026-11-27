"""Seam 1: the CLI. S2 enrichment (real-world names, quoted songs, poems and scripture)
observed in the workspace database."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from book_translator.llm import LLMRequest, RawAnswer
from book_translator.search import Finding
from test_cli_bible_part2 import EPUB, Part2Adapter, part2

NAMES = [
    {"term": "London", "kind": "place"},
    {"term": "Queen Victoria", "kind": "person"},
    {"term": "Canterville", "kind": "place"},
]
QUOTATIONS = [
    {
        "kind": "song",
        "location": "chapter 2, the nursery rhyme",
        "note": "Greensleeves",
        "recommendation": "existing",
        "source": "https://example.org/greensleeves-es",
    },
    {
        "kind": "scripture",
        "location": "chapter 1, the epigraph",
        "recommendation": "own",
    },
    {"kind": "poem", "location": "chapter 3, the epitaph", "recommendation": "own"},
]


class EnrichAdapter(Part2Adapter):
    def __init__(self, enrichment: dict[str, object] | None = None, **kw: Any) -> None:
        super().__init__([json.dumps(part2())], **kw)
        self._enrichment = enrichment if enrichment is not None else {}
        self.enrichment_requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage == "enrichment":
            self.calls += 1
            self.enrichment_requests.append(request)
            return RawAnswer(json.dumps(self._enrichment))
        return super().complete(request, key, attempt)


class FixtureSearch:
    """Answers each query from a table; records what it was asked."""

    def __init__(self, table: dict[str, Finding | None]) -> None:
        self._table = table
        self.asked: list[tuple[str, bool]] = []

    def lookup(self, query: str, language: str, *, established: bool) -> list[Finding]:
        self.asked.append((query, established))
        found = self._table.get(query)
        return [found] if found is not None and established else []


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral"])
    return path


def bible(ws: Path) -> dict[str, Any]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        rows = db.execute("select result from bible").fetchall()
    assert len(rows) == 1
    result: dict[str, Any] = json.loads(rows[0][0])
    return result


TABLE: dict[str, Finding | None] = {
    "London": Finding("London", "A city.", "https://example.org/london", "Londres"),
    "Queen Victoria": Finding(
        "Queen Victoria", "A queen.", "https://example.org/qv", "la reina Victoria"
    ),
    "Canterville": None,
}


def test_famous_real_world_names_get_their_usual_spanish_form_with_a_source(ws: Path) -> None:
    adapter = EnrichAdapter({"names": NAMES})

    main(["run", str(ws)], adapter=adapter, search=FixtureSearch(TABLE))

    glossary = {g["term"]: g for g in bible(ws)["glossary"]}
    assert glossary["London"]["rendering"] == "Londres"
    assert glossary["London"]["origin"] == "established"
    assert glossary["London"]["source"] == "https://example.org/london"
    assert glossary["Queen Victoria"]["rendering"] == "la reina Victoria"
    assert "Canterville" not in glossary  # nothing established, so nothing invented


def test_quoted_songs_poems_and_scripture_are_flagged_in_the_crux_list(ws: Path) -> None:
    adapter = EnrichAdapter({"quotations": QUOTATIONS})

    main(["run", str(ws)], adapter=adapter)

    flags = {c["location"]: c for c in bible(ws)["cruxes"]}
    song = flags["chapter 2, the nursery rhyme"]
    assert song["type"] == "lyrics"
    assert song["recommendation"] == "existing translation"
    assert song["source"] == "https://example.org/greensleeves-es"
    assert flags["chapter 1, the epigraph"]["type"] == "quotation"
    assert flags["chapter 1, the epigraph"]["recommendation"] == "our own"
    assert flags["chapter 1, the epigraph"]["source"] == ""
    assert flags["chapter 3, the epitaph"]["type"] == "quotation"


def test_our_own_rendering_of_a_quotation_is_marked_as_ours(ws: Path) -> None:
    own = {"kind": "poem", "location": "chapter 3, the epitaph", "recommendation": "own"}

    main(["run", str(ws)], adapter=EnrichAdapter({"quotations": [own]}))

    (crux,) = [c for c in bible(ws)["cruxes"] if c["location"] == own["location"]]
    assert crux["recommendation"] == "our own"
    assert crux["note"].startswith("poem")


def test_recommending_an_existing_translation_without_a_source_is_retried(ws: Path) -> None:
    bad = {"kind": "scripture", "location": "chapter 1", "recommendation": "existing"}
    answers = [{"quotations": [bad]}, {"quotations": [{**bad, "source": "https://e.org/b"}]}]

    class Retrying(EnrichAdapter):
        def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
            if request.stage == "enrichment":
                self.enrichment_requests.append(request)
                return RawAnswer(json.dumps(answers[min(attempt, 1)]))
            return super().complete(request, key, attempt)

    adapter = Retrying()
    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.enrichment_requests) == 2
    assert bible(ws)["cruxes"][0]["source"] == "https://e.org/b"


def test_flags_join_the_cruxes_the_bible_already_predicted(ws: Path) -> None:
    predicted = {"type": "lyrics", "location": "chapter 2, the nursery rhyme", "note": "rhymes"}
    adapter = EnrichAdapter({"quotations": QUOTATIONS})
    adapter._completions = [json.dumps(part2(cruxes=[predicted]))]

    main(["run", str(ws)], adapter=adapter)

    cruxes = bible(ws)["cruxes"]
    assert len(cruxes) == 3  # the predicted lyrics crux is enriched, not duplicated
    rhyme = next(c for c in cruxes if c["location"] == predicted["location"])
    assert rhyme["note"].startswith("rhymes")
    assert rhyme["recommendation"] == "existing translation"


def test_evaluation_mode_looks_nothing_up(tmp_path: Path) -> None:
    path = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral", "--evaluation"])
    search = FixtureSearch(TABLE)

    main(["run", str(path)], adapter=EnrichAdapter({"names": NAMES}), search=search)

    assert [g for g in bible(path)["glossary"] if g["origin"] == "established"] == []
    assert [q for q, _ in search.asked if q in {n["term"] for n in NAMES}] == []


def test_an_interrupted_lookup_resumes_without_asking_again(ws: Path) -> None:
    class Interrupted(FixtureSearch):
        def lookup(self, query: str, language: str, *, established: bool) -> list[Finding]:
            if query == "Queen Victoria":
                raise KeyboardInterrupt
            return super().lookup(query, language, established=established)

    with pytest.raises(KeyboardInterrupt):
        main(["run", str(ws)], adapter=EnrichAdapter({"names": NAMES}), search=Interrupted(TABLE))

    second = FixtureSearch(TABLE)
    adapter = EnrichAdapter({"names": NAMES})
    main(["run", str(ws)], adapter=adapter, search=second)

    assert [q for q, _ in second.asked] == ["Queen Victoria", "Canterville"]
    assert adapter.enrichment_requests == []  # the model's answer was already recorded
    assert {g["term"] for g in bible(ws)["glossary"]} == {"London", "Queen Victoria"}

    third = FixtureSearch(TABLE)
    main(["run", str(ws)], adapter=EnrichAdapter({}), search=third)
    assert third.asked == []
