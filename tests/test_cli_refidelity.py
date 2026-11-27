"""Seam 1: the CLI. S7 post-polish fidelity observed in the workspace database."""

import json
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from book_translator.llm import LLMRequest, RawAnswer
from test_cli_bible_part2 import EPUB
from test_cli_draft import scenes, source_ids
from test_cli_fidelity import Reviewer, edit, in_scene, no_edits, query, target_text
from test_cli_polish import PolishAdapter, Polisher, rewriting, unchanged

STAGE = "post_polish_fidelity"


class RecheckAdapter(PolishAdapter):
    """The polish adapter plus a checker answering `check(scene, round)` for every re-check of a
    scene; `round` counts the scene's re-checks from 0."""

    def __init__(self, polish: Polisher, check: Reviewer = no_edits, **bible: object) -> None:
        super().__init__(polish, **bible)
        self.check = check
        self.recheck_requests: list[LLMRequest] = []
        self._rounds: dict[str, int] = {}

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage != STAGE:
            return super().complete(request, key, attempt)
        scene = json.loads(request.source_text)
        first = scene["scene"][0]["id"]
        if attempt == 0:
            self.recheck_requests.append(request)
            self._rounds[first] = self._rounds.get(first, -1) + 1
        return RawAnswer(json.dumps(self.check(scene, self._rounds[first])))


def run_to_the_end(tmp_path: Path, adapter: RecheckAdapter, *extra: str) -> Path:
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral", *extra])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])  # analysis gate
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])  # TK gate
    main(["run", str(ws)], adapter=adapter)
    return ws


def correcting(block: str, answers: list[list[dict[str, Any]]]) -> Reviewer:
    """For the scene holding `block`, the edits `answers[round]` (none past the end)."""

    def check(scene: dict[str, Any], round_: int) -> dict[str, Any]:
        if not in_scene(scene, block) or round_ >= len(answers):
            return {"edits": []}
        return {"edits": answers[round_]}

    return check


def test_meaning_drift_planted_by_the_polish_is_corrected_and_recorded(tmp_path: Path) -> None:
    block = source_ids()[1]
    polish = rewriting(block, [["It was a loud evening."]])
    check = correcting(block, [[edit(block, "loud", "quiet")]])

    ws = run_to_the_end(tmp_path, RecheckAdapter(polish, check))

    assert target_text(ws, block) == "It was a quiet evening."
    assert query(ws, "select stage, block, old, new from polish_edits order by id") == [
        ("polish", block, "It was a quiet evening.", "It was a loud evening."),
        (STAGE, block, "loud", "quiet"),
    ]
    assert query(ws, "select count(*) from unresolved_findings") == [(0,)]


def stubborn(block: str, olds: list[str], news: list[str]) -> Reviewer:
    """For the scene holding `block`, an edit turning `olds[round]` into `news[round]` always."""

    def check(scene: dict[str, Any], round_: int) -> dict[str, Any]:
        if not in_scene(scene, block):
            return {"edits": []}
        return {"edits": [edit(block, olds[round_], news[round_])]}

    return check


def test_drift_still_present_after_the_last_retry_is_recorded_for_qa(tmp_path: Path) -> None:
    block = source_ids()[1]
    polish = rewriting(block, [["It was a loud evening."]])
    # Each check finds new drift in the text as corrected so far; the third is left unapplied.
    check = stubborn(block, ["loud", "noisy", "evening"], ["noisy", "calm", "night"])
    adapter = RecheckAdapter(polish, check)

    ws = run_to_the_end(tmp_path, adapter)

    asked = [r for r in adapter.recheck_requests if block in r.source_text]
    assert len(asked) == 3  # the first check and two retries, then it stops
    assert target_text(ws, block) == "It was a calm evening."
    assert query(ws, "select stage, block, old, new from unresolved_findings") == [
        (STAGE, block, "evening", "night")
    ]
    assert query(ws, "select count(*) from polish_edits where stage = 'post_polish_fidelity'") == [
        (2,)
    ]


def test_the_number_of_retries_is_configurable(tmp_path: Path) -> None:
    block = source_ids()[1]
    polish = rewriting(block, [["It was a loud evening."]])
    check = stubborn(block, ["loud", "quiet", "evening"], ["noisy", "calm", "night"])
    adapter = RecheckAdapter(polish, check)

    ws = run_to_the_end(tmp_path, adapter, "--fidelity-retries", "0")

    assert len([r for r in adapter.recheck_requests if block in r.source_text]) == 1
    assert target_text(ws, block) == "It was a loud evening."
    assert query(ws, "select block, old, new from unresolved_findings") == [
        (block, "loud", "noisy")
    ]


def test_a_scene_without_drift_is_checked_once_and_leaves_no_findings(tmp_path: Path) -> None:
    adapter = RecheckAdapter(rewriting(source_ids()[1], [["It was a quiet, still evening."]]))

    ws = run_to_the_end(tmp_path, adapter)

    assert len(adapter.recheck_requests) == len(query(ws, "select * from rechecked_scenes"))
    assert query(ws, "select count(*) from unresolved_findings") == [(0,)]
    assert query(ws, "select count(*) from polish_edits where stage = 'post_polish_fidelity'") == [
        (0,)
    ]


def test_a_correction_that_cannot_be_applied_is_retried(tmp_path: Path) -> None:
    block = source_ids()[1]
    polish = rewriting(block, [["It was a loud evening."]])

    class Adapter(RecheckAdapter):
        def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
            if request.stage == STAGE and "loud evening" in request.source_text:
                fix = "loud" if attempt else "not there"
                return RawAnswer(json.dumps({"edits": [edit(block, fix, "quiet")]}))
            return super().complete(request, key, attempt)

    ws = run_to_the_end(tmp_path, Adapter(polish))

    assert target_text(ws, block) == "It was a quiet evening."


def test_a_finished_recheck_is_not_run_again_and_calls_are_not_repeated(tmp_path: Path) -> None:
    block = source_ids()[1]
    adapter = RecheckAdapter(
        rewriting(block, [["It was a loud evening."]]),
        correcting(block, [[edit(block, "loud", "quiet")]]),
    )
    ws = run_to_the_end(tmp_path, adapter)
    calls = len(adapter.recheck_requests)

    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.recheck_requests) == calls


def test_the_recheck_resumes_without_repeating_finished_scenes(tmp_path: Path) -> None:
    seen: list[str] = []

    def interrupt_on_second(scene: dict[str, Any], round_: int) -> dict[str, Any]:
        seen.append(scene["scene"][0]["id"])
        if len(seen) == 2:
            raise KeyboardInterrupt
        return {"edits": []}

    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    adapter = RecheckAdapter(unchanged, interrupt_on_second)
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(ws)], adapter=adapter)
    assert len(query(ws, "select * from rechecked_scenes")) == 1

    resumed = RecheckAdapter(unchanged)
    main(["run", str(ws)], adapter=resumed)

    starts = [s[0] for s in scenes()]
    asked = [json.loads(r.source_text)["scene"][0]["id"] for r in resumed.recheck_requests]
    assert asked == [s for s in starts if s != seen[0]]


def test_the_recheck_uses_the_model_configured_for_it(tmp_path: Path) -> None:
    adapter = RecheckAdapter(unchanged)

    run_to_the_end(tmp_path, adapter)

    assert {r.model for r in adapter.recheck_requests} == {"anthropic:claude-sonnet-5-5"}
