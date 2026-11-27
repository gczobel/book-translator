"""Shape checks on the agent-PR workflows: what they must never do."""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _text(name: str) -> str:
    return (WORKFLOWS / f"{name}.yml").read_text()


def test_the_merge_workflow_never_arms_auto_merge_or_reads_pr_text() -> None:
    text = _text("agent-pr")
    for forbidden in ("--auto", "github.event.pull_request", "head_ref", "head.ref", "actor"):
        assert forbidden not in text
    for stale in ("--admin", "enable-auto-merge", "enableAutoMerge"):
        assert stale not in text


def test_the_merge_workflow_rebases_and_pins_the_head_commit() -> None:
    text = _text("agent-pr")
    assert "--rebase" in text
    assert "--match-head-commit" in text
    assert "--squash" not in text


def test_the_merge_job_runs_in_the_main_only_environment_from_the_default_branch() -> None:
    loaded = yaml.safe_load(_text("agent-pr"))
    triggers = loaded.get("on", loaded.get(True))
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert loaded["jobs"]["merge"]["environment"] == "maintenance"
    # no step checks out anything but the default ref
    for job in loaded["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("actions/checkout"):
                assert "ref" not in step.get("with", {})


def test_the_workflow_run_list_covers_every_required_check_source() -> None:
    loaded = yaml.safe_load(_text("agent-pr"))
    triggers = loaded.get("on", loaded.get(True))
    watched = set(triggers["workflow_run"]["workflows"])
    assert {"ci", "guard", "hold", "workflow-security", "agent-pr-review"} <= watched


def test_the_review_workflow_is_a_base_branch_check_that_never_posts_reviews() -> None:
    text = _text("agent-pr-review")
    loaded = yaml.safe_load(text)
    assert "pull_request_target" in loaded.get("on", loaded.get(True))
    assert loaded["jobs"]["llm-review"]["name"] == "llm-review"
    assert "pull-requests: write" not in text
    assert "ref:" not in text  # never checks out the PR head
    assert "secrets." not in text  # the placeholder holds no secret


def test_the_merge_sweep_ignores_the_event_commit_and_has_no_schedule() -> None:
    text = _text("agent-pr")
    loaded = yaml.safe_load(text)
    triggers = loaded.get("on", loaded.get(True))
    assert "schedule" not in triggers
    assert "inputs" not in (triggers["workflow_dispatch"] or {})
    for env_name in ("AGENTPR_SHA", "AGENTPR_PR"):
        assert env_name not in text
    assert "${{ github.event.workflow_run.head_sha" not in text
