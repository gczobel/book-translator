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
        # can still run while paused
        "${{ always() || needs.gate.outputs.paused == 'false' }}",
        "${{ needs.gate.outputs.paused == 'false' || true }}",
        "${{ needs.gate.outputs.paused == 'false' || always() }}",
        "${{ !(needs.gate.outputs.paused == 'false') }}",
        "${{ (needs.gate.outputs.paused == 'false') }}",
        "always() && true # needs.gate.outputs.paused == 'false'",
        "${{ needs.gate.outputs.paused == 'false2' }}",
        True,
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


def test_a_conjunction_that_still_requires_the_gate_is_gated() -> None:
    cond = "${{ needs.gate.outputs.paused == 'false' && github.event_name == 'push' }}"
    wf = {"jobs": {"gate": _gate(), "work": {"needs": ["gate"], "if": cond}}}
    assert ungated_jobs(wf) == []


@pytest.mark.parametrize(
    "condition",
    [
        "${{ always() }}",
        "${{ !cancelled() }}",
        "${{ !failure() }}",
        "${{ success() || failure() }}",
        "${{ needs.a.result == 'skipped' }}",
        "${{ always() && github.event_name == 'push' }}",
    ],
)
def test_downstream_jobs_that_can_run_when_upstream_was_skipped_are_ungated(
    condition: str,
) -> None:
    wf = {
        "jobs": {
            "gate": _gate(),
            "a": {"needs": ["gate"], "if": RUN},
            "b": {"needs": ["a"], "if": condition},
        }
    }
    assert ungated_jobs(wf) == ["b"]


def test_the_gate_itself_is_never_reported() -> None:
    assert ungated_jobs({"jobs": {"gate": _gate()}}) == []


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


UNATTENDED_TRIGGERS = {"schedule", "workflow_run", "repository_dispatch"}


def test_exempt_workflows_are_not_triggered_without_a_human_or_a_pull_request() -> None:
    for name in sorted(EXEMPT_WORKFLOWS):
        loaded = yaml.safe_load((WORKFLOWS / f"{name}.yml").read_text())
        triggers = loaded.get("on", loaded.get(True))  # YAML 1.1 reads `on:` as True
        names = set(triggers) if isinstance(triggers, dict) else {triggers}
        assert not names & UNATTENDED_TRIGGERS, f"{name}.yml runs unattended: gate it instead"
