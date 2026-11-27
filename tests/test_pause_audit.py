"""Every automation workflow must stop when paused, and a new workflow must opt out loudly."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from pause.audit import EXEMPT_WORKFLOWS, GATE_WORKFLOW, ungated_jobs

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
RUN = "${{ needs.gate.outputs.paused == 'false' }}"


def _gate() -> dict[str, Any]:
    return {"uses": GATE_WORKFLOW}


def test_a_workflow_without_the_gate_is_ungated() -> None:
    wf = {"jobs": {"work": {"runs-on": "x"}}}
    assert ungated_jobs(wf) == ["work"]


def test_a_job_that_tests_the_gate_output_is_gated() -> None:
    wf = {"jobs": {"gate": _gate(), "work": {"needs": ["gate"], "if": RUN}}}
    assert ungated_jobs(wf) == []


def test_a_job_that_needs_the_gate_but_ignores_its_output_is_ungated() -> None:
    wf = {"jobs": {"gate": _gate(), "work": {"needs": ["gate"]}}}
    assert ungated_jobs(wf) == ["work"]


@pytest.mark.parametrize(
    "condition",
    [
        "${{ needs.gate.outputs.paused == 'true' }}",
        "${{ needs.gate.outputs.paused != 'true' }}",
        "${{ always() }}",
        "${{ needs.other.outputs.paused == 'false' }}",
    ],
)
def test_only_an_explicit_false_check_counts(condition: str) -> None:
    wf = {"jobs": {"gate": _gate(), "work": {"needs": ["gate"], "if": condition}}}
    assert ungated_jobs(wf) == ["work"]


def test_a_job_downstream_of_a_gated_job_is_skipped_with_it() -> None:
    wf = {
        "jobs": {
            "gate": _gate(),
            "a": {"needs": ["gate"], "if": RUN},
            "b": {"needs": ["a"]},
            "c": {"needs": ["b"], "if": "${{ failure() || cancelled() }}"},
        }
    }
    assert ungated_jobs(wf) == []


def test_always_runs_even_when_upstream_was_skipped() -> None:
    wf = {
        "jobs": {
            "gate": _gate(),
            "a": {"needs": ["gate"], "if": RUN},
            "b": {"needs": ["a"], "if": "${{ always() }}"},
        }
    }
    assert ungated_jobs(wf) == ["b"]


def test_a_workflow_with_no_jobs_is_fine() -> None:
    assert ungated_jobs({"jobs": {}}) == []
    assert ungated_jobs({}) == []


def test_every_automation_workflow_reads_the_pause_switch() -> None:
    problems: dict[str, list[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.stem in EXEMPT_WORKFLOWS:
            continue
        loaded = yaml.safe_load(path.read_text())
        jobs = ungated_jobs(loaded)
        if jobs:
            problems[path.name] = jobs
    assert not problems, (
        "These workflows run unattended but do not stop when PAUSE is set. Call "
        f"{GATE_WORKFLOW} as a job and gate every job on needs.<gate>.outputs.paused == 'false', "
        f"or add the workflow to EXEMPT_WORKFLOWS if it is a PR check: {problems}"
    )


def test_exempt_workflows_all_exist() -> None:
    names = {p.stem for p in WORKFLOWS.glob("*.yml")}
    assert EXEMPT_WORKFLOWS <= names
