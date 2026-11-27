"""Seam 1: the CLI. `evaluate --judge` marks errors per scene, `--diagnose` explains the report,
`--comet` adds a COMET score, and the report says whether the run was an evaluation run. The LLM
is a replay adapter, COMET a fake, embeddings a deterministic fake: nothing paid or downloaded."""

import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from book_translator.llm import LLMRequest, RawAnswer
from test_cli_evaluate import OURS, REPORT, FakeEmbedder, make_epub, set_all_targets
from test_cli_export import fake_epubcheck
from test_cli_qa import CountingAdapter, translate

MARKS = {
    "marks": [
        {"type": "omission", "severity": "major", "note": "dropped a clause"},
        {"type": "register", "severity": "minor", "note": "too formal"},
        {"type": "omission", "severity": "minor", "note": "dropped a word"},
    ]
}


class JudgeAdapter(CountingAdapter):
    """Answers the evaluation-only stages: the judge finds marks in the scene about the tarde."""

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage == "judge":
            self.stages.append("judge")
            marks = MARKS if "tarde" in request.source_text else {"marks": []}
            return RawAnswer(json.dumps(marks), 1000, 500)
        if request.stage == "diagnosis":
            self.stages.append("diagnosis")
            answer = {"diagnosis": [{"cause": "register drift", "fix": "tighten the polish"}]}
            return RawAnswer(json.dumps(answer), 1000, 500)
        return super().complete(request, key, attempt)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_epubcheck(tmp_path, monkeypatch)
    path = translate(tmp_path, CountingAdapter())
    set_all_targets(path)
    main(["run", str(path)], adapter=CountingAdapter())
    main(["export", str(path)])
    return path


@pytest.fixture
def ref(tmp_path: Path) -> Path:
    return make_epub(tmp_path / "ref.epub", [("One", [*OURS[1]]), ("Two", [*OURS[2]])])


def evaluate(path: Path, reference: Path, *flags: str, adapter: JudgeAdapter | None = None) -> Any:
    main(
        ["evaluate", str(path), "--reference", str(reference), *flags],
        embedder=FakeEmbedder(),
        adapter=adapter or JudgeAdapter(),
    )
    return json.loads((path / REPORT).read_text())


def test_the_judge_marks_errors_by_type_and_severity_per_scene(ws: Path, ref: Path) -> None:
    report = evaluate(ws, ref, "--judge")

    judge = report["judge"]
    assert judge["by_type"] == {"omission": 2, "register": 1}
    assert judge["by_severity"] == {"major": 1, "minor": 2}
    marked = [s for s in judge["scenes"] if s["marks"]]
    assert len(marked) == 1
    assert marked[0]["chapter"] == 1
    assert {m["type"] for m in marked[0]["marks"]} == {"omission", "register"}
    assert "omission" in (ws / "quality-report.md").read_text()


def test_a_second_evaluation_repeats_no_judge_call_and_the_spend_is_accounted(
    ws: Path, ref: Path
) -> None:
    first = JudgeAdapter()
    report = evaluate(ws, ref, "--judge", adapter=first)
    assert first.stages.count("judge") == len(report["judge"]["scenes"]) > 0
    assert report["cost"]["by_stage"]["judge"] > 0

    again = JudgeAdapter()
    second = evaluate(ws, ref, "--judge", adapter=again)

    assert again.stages == []
    assert second["judge"] == report["judge"]
    assert second["cost"] == report["cost"]


def test_the_judge_is_refused_once_the_spending_cap_is_reached(ws: Path, ref: Path) -> None:
    with sqlite3.connect(ws / "book.sqlite") as db:
        db.execute("update settings set value = '0.00' where key = 'cap_usd'")
    adapter = JudgeAdapter()

    with pytest.raises(SystemExit) as stop:
        evaluate(ws, ref, "--judge", adapter=adapter)

    assert "cap" in str(stop.value)
    assert "judge" not in adapter.stages


def test_without_the_flag_no_judge_call_is_made(ws: Path, ref: Path) -> None:
    adapter = JudgeAdapter()

    report = evaluate(ws, ref, adapter=adapter)

    assert "judge" not in report
    assert adapter.stages == []


def test_a_workspace_not_initialised_for_evaluation_is_reported_and_warned_about(
    ws: Path, ref: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = evaluate(ws, ref)

    assert report["evaluation_mode"] is False
    assert "--evaluation" in capsys.readouterr().err
    assert "evaluation mode: off" in (ws / "quality-report.md").read_text().lower()


def test_an_evaluation_workspace_is_reported_without_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_epubcheck(tmp_path, monkeypatch)
    path = translate(tmp_path, CountingAdapter(), "--evaluation")
    set_all_targets(path)
    main(["run", str(path)], adapter=CountingAdapter())
    main(["export", str(path)])
    capsys.readouterr()

    report = evaluate(path, ref)

    assert report["evaluation_mode"] is True
    assert "--evaluation" not in capsys.readouterr().err
    assert "evaluation mode: on" in (path / "quality-report.md").read_text().lower()


class FakeComet:
    """Scores a (source, translation, reference) triple by how long the translation is."""

    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str, str]]] = []

    def score(self, triples: Sequence[tuple[str, str, str]]) -> list[float]:
        self.calls.append(list(triples))
        return [len(mt) / 100 for _, mt, _ in triples]


def test_comet_scores_are_added_only_when_the_flag_is_set(ws: Path, ref: Path) -> None:
    comet = FakeComet()
    main(
        ["evaluate", str(ws), "--reference", str(ref)],
        embedder=FakeEmbedder(),
        comet=comet,
    )
    assert comet.calls == []
    assert "comet" not in json.loads((ws / REPORT).read_text())

    main(
        ["evaluate", str(ws), "--reference", str(ref), "--comet"],
        embedder=FakeEmbedder(),
        comet=comet,
    )

    report = json.loads((ws / REPORT).read_text())
    scenes = report["comet"]["scenes"]
    assert len(scenes) == len(comet.calls[0]) > 0
    assert report["comet"]["overall"] == pytest.approx(
        sum(s["score"] for s in scenes) / len(scenes)
    )
    assert "COMET" in (ws / "quality-report.md").read_text()


def test_without_the_comet_package_the_error_names_it(
    ws: Path, ref: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "comet", None)  # the import fails

    with pytest.raises(SystemExit) as stop:
        main(
            ["evaluate", str(ws), "--reference", str(ref), "--comet"],
            embedder=FakeEmbedder(),
        )

    assert "unbabel-comet" in str(stop.value)
    assert not (ws / REPORT).exists()


def test_the_diagnosis_lists_likely_causes_and_suggested_fixes(ws: Path, ref: Path) -> None:
    adapter = JudgeAdapter()

    report = evaluate(ws, ref, "--diagnose", adapter=adapter)

    assert report["diagnosis"] == [{"cause": "register drift", "fix": "tighten the polish"}]
    assert adapter.stages == ["diagnosis"]
    readable = (ws / "quality-report.md").read_text()
    assert "register drift" in readable
    assert "tighten the polish" in readable
    assert report["cost"]["by_stage"]["diagnosis"] > 0
