"""The daily OSV scan decision: what escalates and what stays quiet.

The OSV documents below follow the shape of `osv-scanner scan source --format json`
(results -> packages -> vulnerabilities and groups). They are hand-trimmed to the fields the
decision reads, not captured from a live run.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ghapi.client import ApiError
from ghapi.identities import DEPENDABOT_ID
from osvscan.core import Verdict, decide
from osvscan.run import run

REPO = "o/r"
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
OLD = "2026-11-20T00:00:00Z"
FRESH = "2026-11-27T00:00:00Z"


def vuln(
    vid: str = "GHSA-aaaa-bbbb-cccc",
    published: str = FRESH,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return {"id": vid, "aliases": aliases or [], "published": published}


def osv(
    name: str = "requests",
    vulns: list[dict[str, Any]] | None = None,
    max_severity: str = "5.3",
) -> str:
    vulns = vulns if vulns is not None else [vuln()]
    ids = [v["id"] for v in vulns]
    pkg = {
        "package": {"name": name, "version": "1.0.0", "ecosystem": "PyPI"},
        "vulnerabilities": vulns,
        "groups": [{"ids": ids, "aliases": ids, "max_severity": max_severity}] if vulns else [],
    }
    return json.dumps({"results": [{"source": {"path": "uv.lock"}, "packages": [pkg]}]})


def pr(ref: str = "dependabot/uv/requests-2.0", body: str = "", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "author_id": DEPENDABOT_ID,
        "head_repo": REPO,
        "ref": ref,
        "title": "bump",
        "body": body,
    }
    base.update(over)
    return base


def run_decide(
    stdout: str, exit_code: int = 1, pulls: list[dict[str, Any]] | None = None
) -> Verdict:
    return decide(exit_code, stdout, pulls or [], REPO, NOW)


def test_clean_scan_escalates_nothing() -> None:
    v = run_decide(json.dumps({"results": []}), exit_code=0)
    assert not v.vulnerable and not v.scan_failed


def test_low_severity_fresh_alert_waits() -> None:
    v = run_decide(osv(max_severity="5.3"))
    assert not v.vulnerable and not v.scan_failed


def test_high_severity_escalates() -> None:
    assert run_decide(osv(max_severity="7.0")).vulnerable


def test_critical_severity_escalates() -> None:
    assert run_decide(osv(max_severity="9.8")).vulnerable


def test_unknown_severity_escalates() -> None:
    assert run_decide(osv(max_severity="")).vulnerable


def test_unparseable_severity_escalates() -> None:
    assert run_decide(osv(max_severity="HIGH?")).vulnerable


def test_vuln_missing_from_every_group_is_unknown() -> None:
    doc = json.loads(osv())
    doc["results"][0]["packages"][0]["groups"] = []
    assert run_decide(json.dumps(doc)).vulnerable


def test_mal_entry_escalates_even_when_low() -> None:
    assert run_decide(osv(vulns=[vuln("MAL-2026-1")], max_severity="1.0")).vulnerable


def test_mal_alias_escalates() -> None:
    v = vuln("GHSA-xxxx-yyyy-zzzz", aliases=["MAL-2026-9"])
    assert run_decide(osv(vulns=[v], max_severity="1.0")).vulnerable


def test_old_alert_without_pr_escalates() -> None:
    assert run_decide(osv(vulns=[vuln(published=OLD)])).vulnerable


def test_missing_published_date_counts_as_old() -> None:
    assert run_decide(osv(vulns=[{"id": "GHSA-aaaa-bbbb-cccc"}])).vulnerable


def test_exactly_48_hours_is_not_yet_old() -> None:
    assert not run_decide(osv(vulns=[vuln(published="2026-11-25T12:00:00Z")])).vulnerable


def test_old_alert_with_open_dependabot_pr_waits() -> None:
    assert not run_decide(osv(vulns=[vuln(published=OLD)]), pulls=[pr()]).vulnerable


def test_pr_found_through_grouped_pr_body() -> None:
    grouped = pr(ref="dependabot/uv/uv-minor-abc123", body="Bumps requests from 1.0 to 2.0")
    assert not run_decide(osv(vulns=[vuln(published=OLD)]), pulls=[grouped]).vulnerable


def test_package_name_is_matched_whole_not_as_substring() -> None:
    other = pr(ref="dependabot/uv/requests-toolbelt-1.0")
    assert run_decide(osv(vulns=[vuln(published=OLD)]), pulls=[other]).vulnerable


def test_name_normalisation_dots_and_underscores() -> None:
    other = pr(ref="dependabot/uv/typing-extensions-4.0")
    v = run_decide(osv(name="typing_extensions", vulns=[vuln(published=OLD)]), pulls=[other])
    assert not v.vulnerable


def test_pr_from_stranger_does_not_count() -> None:
    assert run_decide(osv(vulns=[vuln(published=OLD)]), pulls=[pr(author_id=1234)]).vulnerable


def test_pr_from_fork_does_not_count() -> None:
    assert run_decide(osv(vulns=[vuln(published=OLD)]), pulls=[pr(head_repo="evil/r")]).vulnerable


def test_non_dependabot_branch_does_not_count() -> None:
    fake = pr(ref="feature/requests")
    assert run_decide(osv(vulns=[vuln(published=OLD)]), pulls=[fake]).vulnerable


def test_scanner_error_exit_code_is_a_scan_failure() -> None:
    for code in (127, 128, 2, -9):
        assert run_decide("", exit_code=code).scan_failed


def test_unparseable_output_is_a_scan_failure() -> None:
    assert run_decide("not json", exit_code=1).scan_failed


def test_wrong_shape_is_a_scan_failure() -> None:
    shapes = ["[]", "{}", '{"results": {}}', '{"results": [1]}', '{"results": [{"packages": [1]}]}']
    for text in shapes:
        assert run_decide(text, exit_code=0).scan_failed, text


def test_findings_exit_without_findings_is_a_scan_failure() -> None:
    assert run_decide(json.dumps({"results": []}), exit_code=1).scan_failed


def test_scan_failure_and_vulnerability_are_reported_separately() -> None:
    v = run_decide(osv(max_severity="9.8"), exit_code=127)
    assert v.scan_failed and not v.vulnerable


def test_report_lines_are_log_safe() -> None:
    v = run_decide(osv(name="x::y", vulns=[vuln("MAL-1\n::error::boom")]))
    assert v.lines
    assert all("\n" not in line and "::" not in line for line in v.lines)


def test_both_escalation_reasons_exist() -> None:
    from escalate.core import REASONS

    assert {"vulnerability-found", "vulnerability-scan-failed"} <= set(REASONS)


# The entry point: files and environment in, step outputs out.


class FakePulls:
    def __init__(self, pulls: list[Any] | None = None, error: bool = False) -> None:
        self.pulls = pulls or []
        self.error = error

    def get_pages(self, path: str) -> list[Any]:
        assert path == f"/repos/{REPO}/pulls?state=open"
        if self.error:
            raise ApiError("boom")
        return self.pulls


def github_pr(ref: str, author: int = DEPENDABOT_ID, repo: str | None = REPO) -> dict[str, Any]:
    return {
        "user": {"id": author},
        "head": {"ref": ref, "repo": {"full_name": repo} if repo else None},
        "title": "t",
        "body": None,
    }


def env_for(tmp_path: Path, stdout: str, exit_code: str = "1") -> dict[str, str]:
    scan = tmp_path / "osv.json"
    scan.write_text(stdout)
    return {
        "OSV_OUTPUT_FILE": str(scan),
        "OSV_EXIT_CODE": exit_code,
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_OUTPUT": str(tmp_path / "out"),
        "GH_TOKEN": "x",
    }


def outputs(env: dict[str, str]) -> dict[str, str]:
    lines = Path(env["GITHUB_OUTPUT"]).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_run_publishes_the_verdict(tmp_path: Path) -> None:
    env = env_for(tmp_path, osv(max_severity="9.8"))
    assert run(env, FakePulls(), NOW) == 0
    assert outputs(env) == {"vulnerable": "true", "scan_failed": "false", "scan_ok": "true"}


def test_run_uses_open_dependabot_prs(tmp_path: Path) -> None:
    env = env_for(tmp_path, osv(vulns=[vuln(published=OLD)]))
    api = FakePulls([github_pr("dependabot/uv/requests-2.0")])
    assert run(env, api, NOW) == 0
    assert outputs(env) == {"vulnerable": "false", "scan_failed": "false", "scan_ok": "true"}


def test_run_tolerates_prs_from_deleted_forks(tmp_path: Path) -> None:
    env = env_for(tmp_path, osv(vulns=[vuln(published=OLD)]))
    assert run(env, FakePulls([github_pr("x", repo=None)]), NOW) == 0
    assert outputs(env)["vulnerable"] == "true"


def test_run_escalates_when_pull_requests_cannot_be_listed(tmp_path: Path) -> None:
    env = env_for(tmp_path, osv(vulns=[vuln(published=OLD)]))
    assert run(env, FakePulls(error=True), NOW) == 0
    assert outputs(env)["vulnerable"] == "true"


def test_run_reports_a_missing_scan_file_as_a_failed_scan(tmp_path: Path) -> None:
    env = env_for(tmp_path, "", exit_code="127")
    Path(env["OSV_OUTPUT_FILE"]).unlink()
    assert run(env, FakePulls(), NOW) == 0
    assert outputs(env) == {"vulnerable": "false", "scan_failed": "true", "scan_ok": "false"}


def test_run_fails_loudly_without_an_exit_code(tmp_path: Path) -> None:
    env = env_for(tmp_path, "{}")
    del env["OSV_EXIT_CODE"]
    assert run(env, FakePulls(), NOW) == 1


def test_run_fails_loudly_when_outputs_cannot_be_written(tmp_path: Path) -> None:
    env = env_for(tmp_path, osv())
    del env["GITHUB_OUTPUT"]
    assert run(env, FakePulls(), NOW) == 1

