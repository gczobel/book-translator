"""Seam 1: the CLI. S4 TK resolution observed in the workspace database."""

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from book_translator.llm import LLMRequest, RawAnswer
from test_cli_bible_part2 import EPUB, echo_draft
from test_cli_draft import DraftAdapter, source_ids, tk

Decide = Callable[[dict[str, Any]], dict[str, Any]]


def confident(card: dict[str, Any]) -> dict[str, Any]:
    return {"resolution": card["recommendation"], "confidence": 0.9}


class ResolveAdapter(DraftAdapter):
    """The draft adapter whose drafter reports `tks` and whose resolver answers `decide(card)`.

    The drafter writes each TK's provisional rendering into its block, so the text can change.
    """

    def __init__(self, tks: list[dict[str, Any]], decide: Decide = confident) -> None:
        super().__init__(self._draft)
        self.tks = tks
        self.decide = decide
        self.resolve_requests: list[LLMRequest] = []

    def _draft(self, request: LLMRequest, attempt: int) -> str:
        draft = json.loads(echo_draft(request))
        ids = {b["source"] for b in draft["blocks"]}
        draft["tks"] = [t for t in self.tks if t["block"] in ids]
        for block in draft["blocks"]:
            for t in draft["tks"]:
                if t["block"] == block["source"]:
                    block["targets"] = [f"{t['provisional']} Fin."]
        return json.dumps(draft)

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage != "tk_resolution":
            return super().complete(request, key, attempt)
        if attempt == 0:
            self.resolve_requests.append(request)
        card = json.loads(request.source_text)["tk"]
        return RawAnswer(json.dumps(self.decide(card)))


def run_all(tmp_path: Path, adapter: ResolveAdapter) -> Path:
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=adapter)
    return ws


def tks_of(ws: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("select * from tks order by rowid")]


def target_text(ws: Path, block: str) -> str:
    with sqlite3.connect(ws / "book.sqlite") as db:
        rows = db.execute(
            "select text from targets where source = ? order by position", (block,)
        ).fetchall()
    return "\n".join(r[0] for r in rows)


def test_a_confident_local_tk_is_resolved_automatically_and_updates_the_text(
    tmp_path: Path,
) -> None:
    block = source_ids()[1]
    adapter = ResolveAdapter(
        [tk(confidence=0.9)], lambda card: {"resolution": "noche en calma", "confidence": 0.9}
    )

    ws = run_all(tmp_path, adapter)

    (row,) = tks_of(ws)
    assert (row["resolution"], row["resolver"]) == ("noche en calma", "auto")
    assert target_text(ws, block) == "noche en calma Fin."


def test_a_resolver_confidence_written_as_a_percentage_counts_as_that_fraction(
    tmp_path: Path,
) -> None:
    adapter = ResolveAdapter(
        [tk()], lambda card: {"resolution": "noche en calma", "confidence": 90}
    )

    ws = run_all(tmp_path, adapter)

    (row,) = tks_of(ws)
    assert (row["resolution"], row["resolver"]) == ("noche en calma", "auto")


def second_block() -> str:
    return source_ids()[2]


def test_a_low_confidence_resolution_is_escalated_and_the_tk_stays_open(tmp_path: Path) -> None:
    block = source_ids()[1]
    adapter = ResolveAdapter(
        [tk()], lambda card: {"resolution": "tarde en calma", "confidence": 0.3}
    )

    ws = run_all(tmp_path, adapter)

    (row,) = tks_of(ws)
    assert (row["resolution"], row["resolver"]) == (None, None)
    assert target_text(ws, block) == "Era una tarde tranquila. Fin."


def test_a_recurring_tk_is_escalated_even_when_the_resolver_would_be_sure(tmp_path: Path) -> None:
    adapter = ResolveAdapter([tk(scope="recurring", type="new recurring term")])

    ws = run_all(tmp_path, adapter)

    (row,) = tks_of(ws)
    assert (row["resolution"], row["resolver"]) == (None, None)
    assert target_text(ws, source_ids()[1]) == "Era una tarde tranquila. Fin."


def test_most_tks_are_resolved_automatically_and_only_the_hard_ones_stay_open(
    tmp_path: Path,
) -> None:
    easy = tk(confidence=0.9)
    hard = tk(block=second_block(), provisional="Algo.", scope="recurring")
    other = tk(block=source_ids()[6], provisional="Otra cosa.")
    adapter = ResolveAdapter([easy, hard, other])

    ws = run_all(tmp_path, adapter)

    assert [r["resolver"] for r in tks_of(ws)] == ["auto", None, "auto"]


def test_a_finished_resolution_is_not_run_again_and_calls_are_not_repeated(
    tmp_path: Path,
) -> None:
    adapter = ResolveAdapter([tk(), tk(block=source_ids()[6], provisional="Otra cosa.")])
    ws = run_all(tmp_path, adapter)
    calls = len(adapter.resolve_requests)
    assert calls == 2

    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.resolve_requests) == calls


def test_resolution_resumes_without_repeating_examined_tks(tmp_path: Path) -> None:
    seen: list[str] = []

    def interrupt_on_second(card: dict[str, Any]) -> dict[str, Any]:
        seen.append(card["id"])
        if len(seen) == 2:
            raise KeyboardInterrupt
        return confident(card)

    tks = [tk(), tk(block=source_ids()[6], provisional="Otra cosa.")]
    adapter = ResolveAdapter(tks, interrupt_on_second)
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(ws)], adapter=adapter)
    assert [r["resolver"] for r in tks_of(ws)] == ["auto", None]

    resumed = ResolveAdapter(tks)
    main(["run", str(ws)], adapter=resumed)

    assert [json.loads(r.source_text)["tk"]["id"] for r in resumed.resolve_requests] == ["TK-2"]
    assert [r["resolver"] for r in tks_of(ws)] == ["auto", "auto"]


def test_resolution_uses_the_model_configured_for_it(tmp_path: Path) -> None:
    adapter = ResolveAdapter([tk()])

    run_all(tmp_path, adapter)

    assert {r.model for r in adapter.resolve_requests} == {"anthropic:claude-opus-5-5"}


def test_tk_resolution_waits_for_the_draft(tmp_path: Path) -> None:
    adapter = ResolveAdapter([tk()])
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])

    main(["run", str(ws)], adapter=adapter)

    assert adapter.resolve_requests == []
