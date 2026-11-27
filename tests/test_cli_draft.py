"""Seam 1: the CLI. S3 draft observed in the workspace database, after the analysis gate."""

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from book_translator.epub import open_epub
from book_translator.llm import LLMRequest, RawAnswer
from test_cli_bible_part2 import EPUB, Part2Adapter, echo_draft, part2

Answer = Callable[[LLMRequest, int], str]


def source_ids() -> list[str]:
    book = open_epub(EPUB).book()
    return [b.id for c in book.chapters for s in c.scenes for b in s.blocks]


def scenes() -> list[list[str]]:
    book = open_epub(EPUB).book()
    return [[b.id for b in s.blocks] for c in book.chapters for s in c.scenes]


class DraftAdapter(Part2Adapter):
    """Part 2's adapter whose drafter is `answer(request, attempt)`, echoing by default."""

    def __init__(
        self,
        answer: Answer | None = None,
        fail_after: int | None = None,
        **bible: object,
    ) -> None:
        super().__init__([json.dumps(part2(**bible))])
        self.answer: Answer = answer or (lambda request, attempt: echo_draft(request))
        self.draft_requests: list[LLMRequest] = []
        self.draft_attempts = 0
        self.draft_fail_after = fail_after

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage == "tk_resolution":  # covered in test_cli_resolve.py; here, unsure
            return RawAnswer('{"resolution": "x", "confidence": 0.0}')
        if request.stage != "draft":
            return super().complete(request, key, attempt)
        if self.draft_fail_after is not None and len(self.draft_requests) >= self.draft_fail_after:
            raise KeyboardInterrupt
        self.draft_attempts += 1
        if attempt == 0:
            self.draft_requests.append(request)
        return RawAnswer(self.answer(request, attempt))


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral"])
    return path


def drafted(ws: Path, adapter: Part2Adapter | None = None) -> Part2Adapter:
    adapter = adapter or DraftAdapter()
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=adapter)
    return adapter


def query(ws: Path, sql: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        return db.execute(sql).fetchall()


def test_every_source_block_has_at_least_one_target_block(ws: Path) -> None:
    drafted(ws)

    sources = {r[0] for r in query(ws, "select source from targets")}
    assert sources == set(source_ids())


def test_a_block_may_become_several_target_blocks_in_order(ws: Path) -> None:
    def split(request: LLMRequest, attempt: int) -> str:
        passage = json.loads(request.source_text)["passage"]
        blocks = [{"source": b["id"], "targets": [b["text"], "second", "third"]} for b in passage]
        return json.dumps({"blocks": blocks})

    drafted(ws, DraftAdapter(split))

    first = source_ids()[1]
    rows = query(ws, f"select text from targets where source = '{first}' order by position")
    assert [r[0] for r in rows] == ["It was a quiet evening.", "second", "third"]


def test_a_block_left_out_is_retried(ws: Path) -> None:
    def forgetful(request: LLMRequest, attempt: int) -> str:
        answer = json.loads(echo_draft(request))
        if attempt == 0:
            answer["blocks"].pop()
        return json.dumps(answer)

    adapter = DraftAdapter(forgetful)
    drafted(ws, adapter)

    assert adapter.draft_attempts == 2 * len(adapter.draft_requests)
    assert {r[0] for r in query(ws, "select source from targets")} == set(source_ids())


def tk(**overrides: Any) -> dict[str, Any]:
    base = {
        "block": source_ids()[1],
        "span": "quiet evening",
        "type": "idiom",
        "excerpt": "It was a quiet evening.",
        "provisional": "Era una tarde tranquila.",
        "candidates": [
            {"rendering": "tarde tranquila", "reason": "natural"},
            {"rendering": "noche en calma", "reason": "more literary"},
        ],
        "recommendation": "tarde tranquila",
        "confidence": 0.4,
        "scope": "local",
    }
    return {**base, **overrides}


def with_tks(tks: list[dict[str, Any]]) -> Answer:
    def answer(request: LLMRequest, attempt: int) -> str:
        draft = json.loads(echo_draft(request))
        ids = {b["source"] for b in draft["blocks"]}
        draft["tks"] = [t for t in tks if t["block"] in ids]
        return json.dumps(draft)

    return answer


def test_a_tk_is_stored_with_every_field_of_the_schema(ws: Path) -> None:
    drafted(ws, DraftAdapter(with_tks([tk()])))

    with sqlite3.connect(ws / "book.sqlite") as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute("select * from tks")]
    assert len(rows) == 1
    stored = rows[0]
    assert stored["id"]
    assert stored["block"] == source_ids()[1]
    assert (stored["span"], stored["type"]) == ("quiet evening", "idiom")
    assert stored["excerpt"] == "It was a quiet evening."
    assert stored["provisional"] == "Era una tarde tranquila."
    candidates = json.loads(stored["candidates"])
    assert [c["rendering"] for c in candidates] == ["tarde tranquila", "noche en calma"]
    assert all(c["reason"] for c in candidates)
    assert stored["recommendation"] == "tarde tranquila"
    assert (stored["confidence"], stored["scope"]) == (0.4, "local")
    assert (stored["resolution"], stored["resolver"]) == (None, None)


def stored_tk(ws: Path) -> dict[str, Any]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute("select * from tks")]
    assert len(rows) == 1
    return rows[0]


def test_the_recommendation_is_asked_for_as_a_candidate_number(ws: Path) -> None:
    adapter = DraftAdapter(with_tks([tk(recommendation=2)]))
    drafted(ws, adapter)

    asked = json.loads(adapter.draft_requests[0].output_schema)
    kinds = [
        p["properties"]["recommendation"]["type"]
        for p in asked["$defs"].values()
        if "recommendation" in p.get("properties", {})
    ]
    assert kinds == ["integer"]
    assert stored_tk(ws)["recommendation"] == "noche en calma"
    assert adapter.draft_attempts == len(adapter.draft_requests)


def test_a_tk_needs_two_or_three_candidates_and_retries_are_bounded(ws: Path) -> None:
    one = tk(candidates=[{"rendering": "a", "reason": "b"}], recommendation="a")
    adapter = DraftAdapter(with_tks([one]))

    with pytest.raises(SystemExit):
        drafted(ws, adapter)

    assert adapter.draft_attempts == 3


def test_an_answer_that_stays_invalid_is_saved_and_the_run_stops_with_a_short_message(
    ws: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "sk-ant-should-never-appear"

    def hopeless(request: LLMRequest, attempt: int) -> str:
        return json.dumps({"blocks": [], "note": secret * 5000})

    adapter = DraftAdapter(hopeless)
    with pytest.raises(SystemExit) as stopped:
        drafted(ws, adapter)

    message = str(stopped.value)
    assert "draft" in message and "validation" in message
    assert "Traceback" not in message
    logs = list((ws / "logs").glob("invalid-*.json"))
    assert len(logs) == 1
    assert str(logs[0]) in message
    assert f"book-translator run {ws}" in message
    saved = json.loads(logs[0].read_text())
    assert saved["stage"] == "draft"
    assert logs[0].name == f"invalid-{saved['key']}.json"
    assert "cover exactly the blocks" in saved["error"]
    assert saved["raw"].startswith('{"blocks": []')
    assert logs[0].stat().st_size < 100_000
    assert secret not in logs[0].read_text()
    assert len(message) < 3000


def test_a_tk_of_an_unknown_type_is_retried(ws: Path) -> None:
    adapter = DraftAdapter(with_tks([tk(type="hunch")]))

    with pytest.raises(SystemExit):
        drafted(ws, adapter)


def test_broken_inline_codes_are_retried_and_a_legal_answer_is_kept(ws: Path) -> None:
    marked = next(i for i in source_ids() if '<pc id="1">' in open_epub(EPUB).encode_block(i).text)

    def sloppy(request: LLMRequest, attempt: int) -> str:
        draft = json.loads(echo_draft(request))
        if attempt == 0:
            for block in draft["blocks"]:
                if block["source"] == marked:
                    block["targets"] = ["no codes at all"]
        return json.dumps(draft)

    adapter = DraftAdapter(sloppy)
    drafted(ws, adapter)

    kept = query(ws, f"select text from targets where source = '{marked}'")
    assert '<pc id="1">' in kept[0][0]
    assert adapter.draft_attempts == len(adapter.draft_requests) + 1


def test_inline_codes_that_stay_broken_stop_the_run_after_bounded_attempts(ws: Path) -> None:
    marked = next(i for i in source_ids() if '<pc id="1">' in open_epub(EPUB).encode_block(i).text)

    def hopeless(request: LLMRequest, attempt: int) -> str:
        draft = json.loads(echo_draft(request))
        for block in draft["blocks"]:
            if block["source"] == marked:
                block["targets"] = ["no codes at all"]
        return json.dumps(draft)

    adapter = DraftAdapter(hopeless)
    with pytest.raises(SystemExit):
        drafted(ws, adapter)

    assert adapter.draft_attempts - len(adapter.draft_requests) == 2


def test_a_passage_never_crosses_a_scene(ws: Path) -> None:
    adapter = drafted(ws)
    assert isinstance(adapter, DraftAdapter)

    for request in adapter.draft_requests:
        ids = [b["id"] for b in json.loads(request.source_text)["passage"]]
        assert any(set(ids) <= set(scene) for scene in scenes()), ids
    covered = [
        b["id"] for r in adapter.draft_requests for b in json.loads(r.source_text)["passage"]
    ]
    assert covered == source_ids()


def test_the_model_named_for_the_draft_in_the_config_is_used(ws: Path) -> None:
    adapter = drafted(ws)
    assert isinstance(adapter, DraftAdapter)

    assert {r.model for r in adapter.draft_requests} == {"anthropic:claude-sonnet-5-5"}


@pytest.mark.parametrize(
    "said",
    ["  Tarde   Tranquila ", '"tarde tranquila"', "«tarde tranquila»", "1", "candidate 1"],
)
def test_a_recommendation_that_only_approximately_names_a_candidate_is_matched(
    ws: Path, said: str
) -> None:
    adapter = DraftAdapter(with_tks([tk(recommendation=said)]))
    drafted(ws, adapter)

    assert stored_tk(ws)["recommendation"] == "tarde tranquila"
    assert adapter.draft_attempts == len(adapter.draft_requests)


@pytest.mark.parametrize("said", ["something else entirely", 7, 0, -1, ""])
def test_a_recommendation_matching_nothing_degrades_to_the_first_candidate(
    ws: Path, said: object
) -> None:
    adapter = DraftAdapter(with_tks([tk(recommendation=said, confidence=0.9)]))
    drafted(ws, adapter)

    stored = stored_tk(ws)
    assert stored["recommendation"] == "tarde tranquila"
    assert stored["confidence"] <= 0.2
    assert adapter.draft_attempts == len(adapter.draft_requests)


def test_a_confidence_given_as_a_percentage_is_normalised(ws: Path) -> None:
    drafted(ws, DraftAdapter(with_tks([tk(confidence=85)])))

    assert stored_tk(ws)["confidence"] == pytest.approx(0.85)


def test_a_fourth_candidate_is_dropped_rather_than_failing_the_passage(ws: Path) -> None:
    extra = [
        {"rendering": "tarde tranquila", "reason": "a"},
        {"rendering": "noche en calma", "reason": "b"},
        {"rendering": "velada serena", "reason": "c"},
        {"rendering": "anochecer sereno", "reason": "d"},
    ]
    adapter = DraftAdapter(with_tks([tk(candidates=extra, recommendation=2)]))
    drafted(ws, adapter)

    stored = stored_tk(ws)
    assert len(json.loads(stored["candidates"])) == 3
    assert stored["recommendation"] == "noche en calma"
    assert adapter.draft_attempts == len(adapter.draft_requests)


def test_resume_does_not_repeat_finished_passages(ws: Path) -> None:
    interrupted = DraftAdapter(fail_after=2)
    main(["run", str(ws)], adapter=interrupted)
    main(["approve", str(ws)])
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(ws)], adapter=interrupted)
    finished = {r[0] for r in query(ws, "select first_block from drafted_passages")}
    assert len(finished) == 2

    resumed = DraftAdapter()
    main(["run", str(ws)], adapter=resumed)

    redone = {json.loads(r.source_text)["passage"][0]["id"] for r in resumed.draft_requests}
    assert not redone & finished
    assert {r[0] for r in query(ws, "select source from targets")} == set(source_ids())


def test_a_finished_draft_is_not_run_again(ws: Path) -> None:
    drafted(ws)
    again = DraftAdapter()

    main(["run", str(ws)], adapter=again)

    assert again.draft_requests == []


def test_draft_waits_for_the_analysis_gate(ws: Path) -> None:
    adapter = DraftAdapter()

    main(["run", str(ws)], adapter=adapter)

    assert adapter.draft_requests == []


def test_the_skip_setting_lets_the_draft_follow_without_approval(tmp_path: Path) -> None:
    path = tmp_path / "skip"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral"])
    with sqlite3.connect(path / "book.sqlite") as db:
        db.execute("insert into settings values ('skip_analysis_gate', '1')")

    main(["run", str(path)], adapter=DraftAdapter())

    assert {r[0] for r in query(path, "select source from targets")} == set(source_ids())


def request_for(adapter: DraftAdapter, block: str) -> dict[str, Any]:
    for request in adapter.draft_requests:
        if block in [b["id"] for b in json.loads(request.source_text)["passage"]]:
            return {"slice": request.bible_slice, "source": json.loads(request.source_text)}
    raise AssertionError(block)


def test_the_bible_slice_holds_only_what_the_passage_touches(ws: Path) -> None:
    glossary = [
        {"term": "quiet", "rendering": "tranquila", "origin": "extracted"},
        {"term": "Zeppelin", "rendering": "zepelín", "origin": "extracted"},
    ]
    adapter = DraftAdapter(glossary=glossary)

    drafted(ws, adapter)

    found = request_for(adapter, source_ids()[1])["slice"]
    assert "tranquila" in found
    assert "zepelín" not in found
    assert "gothic comedy" in found  # profile and style always go along


def test_a_concordance_of_earlier_chapters_shows_how_a_term_was_rendered(ws: Path) -> None:
    glossary = [{"term": "was", "rendering": "era", "origin": "extracted"}]
    adapter = DraftAdapter(
        lambda request, attempt: json.dumps(
            {
                "blocks": [
                    {"source": b["id"], "targets": [b["text"].replace("was", "era")]}
                    for b in json.loads(request.source_text)["passage"]
                ]
            }
        ),
        glossary=glossary,
    )

    drafted(ws, adapter)

    second_chapter = next(i for i in source_ids() if i.endswith("ch2.xhtml#1"))
    first_chapter = source_ids()[1]
    concordance = request_for(adapter, second_chapter)["source"]["concordance"]
    assert concordance[0]["term"] == "was"
    assert {"source": first_chapter, "target": "It era a quiet evening."} in concordance[0][
        "earlier"
    ]
    assert (
        "concordance" not in request_for(adapter, first_chapter)["source"]
        or not (request_for(adapter, first_chapter)["source"]["concordance"])
    )


def test_status_reports_the_draft_stage(ws: Path, capsys: pytest.CaptureFixture[str]) -> None:
    drafted(ws)

    capsys.readouterr()
    main(["status", str(ws)])

    out = capsys.readouterr().out
    assert "Stage: tk_resolution (done)" in out
    assert "Review gate: tk is waiting" in out


def test_a_tk_with_an_empty_provisional_rendering_is_retried(ws: Path) -> None:
    adapter = DraftAdapter(with_tks([tk(provisional="")]))

    with pytest.raises(SystemExit):
        drafted(ws, adapter)

    assert adapter.draft_attempts == 3
