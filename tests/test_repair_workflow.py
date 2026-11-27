"""Shape checks on the repair workflow: the separations ADR 0005 relies on."""

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "repair.yml"
TEXT = WORKFLOW.read_text()
LOADED: Any = yaml.safe_load(TEXT)
JOBS: dict[str, dict[str, Any]] = LOADED["jobs"]


def _steps(job: str) -> list[dict[str, Any]]:
    return list(JOBS[job].get("steps", []))


def test_it_runs_only_after_ci_from_the_default_branch() -> None:
    triggers = LOADED.get("on", LOADED.get(True))
    assert set(triggers) == {"workflow_run"}
    assert triggers["workflow_run"]["workflows"] == ["ci"]
    assert LOADED["permissions"] == {}
    assert LOADED["concurrency"]["cancel-in-progress"] is False
    assert "workflow_run.head_branch" in LOADED["concurrency"]["group"]


def test_only_the_agent_job_can_see_the_anthropic_key_and_it_is_in_environment_repair() -> None:
    assert JOBS["agent"]["environment"] == "repair"
    for name, job in JOBS.items():
        if name != "agent":
            assert job.get("environment") != "repair"
    holders = {n for n in JOBS if "ANTHROPIC" in yaml.safe_dump(JOBS[n])}
    assert holders == {"agent"}
    assert TEXT.count("secrets.ANTHROPIC_API_KEY") == 1


def test_the_agent_has_a_read_only_token_no_cache_and_no_credentials_on_disk() -> None:
    assert JOBS["agent"]["permissions"] == {"contents": "read"}
    for step in _steps("agent"):
        uses = str(step.get("uses", ""))
        assert "actions/cache" not in uses and "upload-artifact" not in uses
        if uses.startswith("actions/checkout"):
            assert step["with"]["persist-credentials"] is False
        if uses.startswith("astral-sh/setup-uv"):
            assert step["with"]["enable-cache"] is False
    assert "GH_TOKEN" not in yaml.safe_dump(JOBS["agent"])
    assert "create-github-app-token" not in yaml.safe_dump(JOBS["agent"])


def test_the_agent_runs_claude_without_project_settings_and_with_bash_limited() -> None:
    step = next(s for s in _steps("agent") if "claude-code-action" in str(s.get("uses", "")))
    args = step["with"]["claude_args"]
    assert "--setting-sources user" in args
    assert "Bash(uv sync --locked)" in args and "Bash(uv run pytest:*)" in args
    allowed = args.split("--allowed-tools")[1].split("--disallowed-tools")[0]
    assert allowed.count("Bash(") == 2
    assert step["with"]["show_full_output"] == "false"
    assert "gh:*" in args and "git:*" in args
    assert "${{" not in step["with"]["prompt"]  # no PR text reaches the prompt


def test_the_action_is_pinned_to_a_full_commit_hash() -> None:
    for job in JOBS.values():
        for step in job.get("steps", []):
            uses = str(step.get("uses", ""))
            if "@" in uses:
                assert len(uses.split("@")[1]) == 40, uses


def test_the_agent_cannot_run_until_egress_is_limited() -> None:
    steps = _steps("agent")
    names = [s.get("name", "") for s in steps]
    egress = names.index("Limit network egress to PyPI and the Anthropic API")
    claude = next(i for i, s in enumerate(steps) if "claude-code-action" in str(s.get("uses", "")))
    assert egress < claude
    assert steps[egress]["run"].rstrip().endswith("exit 1")


def test_validate_holds_no_secret_and_no_write_token() -> None:
    text = yaml.safe_dump(JOBS["validate"])
    assert "secrets." not in text and "environment" not in JOBS["validate"]
    assert JOBS["validate"]["permissions"] == {"contents": "read"}
    assert "python3 -m repair_validate" in text
    assert "python3 -m repair names" in text
    # scripts come from main: the only checkout has no ref
    for step in _steps("validate"):
        if str(step.get("uses", "")).startswith("actions/checkout"):
            assert "ref" not in step["with"]


def test_push_gets_a_contents_only_token_and_runs_no_pr_code() -> None:
    job = JOBS["push"]
    assert job["environment"] == "maintenance"
    token = next(s for s in _steps("push") if "create-github-app-token" in str(s.get("uses", "")))
    permissions = {k for k in token["with"] if k.startswith("permission-")}
    assert permissions == {"permission-contents"}
    assert token["with"]["permission-contents"] == "write"
    for step in _steps("push"):
        if str(step.get("uses", "")).startswith("actions/checkout"):
            assert "ref" not in step["with"]
    assert "uv run" not in yaml.safe_dump(job) and "pytest" not in yaml.safe_dump(job)


def test_the_jobs_form_the_agent_validate_push_chain() -> None:
    assert "agent" in JOBS["validate"]["needs"]
    assert {"agent", "validate"} <= set(JOBS["push"]["needs"])


def test_giving_up_in_any_job_escalates() -> None:
    escalated = {
        n: str(JOBS[n]["if"])
        for n in JOBS
        if n.startswith("escalate-") and n != "escalate-gate-failed"
    }
    assert "needs.select.outputs.ok != 'true'" in escalated["escalate-select-failed"]
    assert "outputs.action == 'escalate'" in escalated["escalate-exhausted"]
    for job, cause in (
        ("escalate-agent-failed", "agent"),
        ("escalate-rejected", "validate"),
        ("escalate-push-failed", "push"),
    ):
        assert f"needs.{cause}.result != 'success'" in escalated[job]
        assert "always()" in escalated[job]
    assert "escalate-gate-failed" in JOBS
