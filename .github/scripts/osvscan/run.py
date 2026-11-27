"""Entry point: read the scan, list open PRs, publish the verdict as step outputs.

The scan step never fails the job on findings; it publishes `vulnerable` and `scan_failed`
and the workflow's escalation jobs act on them. A crash here fails the job, which the
workflow also escalates.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ghapi.client import HttpApi
from ghapi.repo import split_repo
from osvscan.core import decide


class Api(Protocol):
    def get_pages(self, path: str) -> list[Any]: ...


def _open_pulls(api: Api, repo: str) -> list[dict[str, Any]]:
    pulls = []
    for item in api.get_pages(f"/repos/{repo}/pulls?state=open"):
        head = item.get("head") or {}
        head_repo = head.get("repo") or {}
        pulls.append(
            {
                "author_id": (item.get("user") or {}).get("id"),
                "head_repo": head_repo.get("full_name"),
                "ref": head.get("ref"),
                "title": item.get("title"),
                "body": item.get("body"),
            }
        )
    return pulls


def run(env: Mapping[str, str], api: Api | None = None, now: datetime | None = None) -> int:
    try:
        exit_code = int(env["OSV_EXIT_CODE"])
        output_file = env["OSV_OUTPUT_FILE"]
        repo = env["GITHUB_REPOSITORY"]
        out_path = env["GITHUB_OUTPUT"]
    except (KeyError, ValueError):
        print("osvscan: OSV_EXIT_CODE, OSV_OUTPUT_FILE, GITHUB_REPOSITORY or GITHUB_OUTPUT is bad")
        return 1
    if split_repo(repo) is None:
        print("osvscan: GITHUB_REPOSITORY is not owner/name")
        return 1
    try:
        stdout = Path(output_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        stdout = ""
        exit_code = 127  # no readable output is a failed scan, whatever the exit code said
    try:
        if api is None:
            api = HttpApi(env.get("GH_TOKEN", ""))
        pulls = _open_pulls(api, repo)
    except Exception as error:
        # Without the PR list every old alert looks unhandled, so we escalate more, not less.
        print(f"osvscan: cannot list open PRs ({type(error).__name__}); treating as none")
        pulls = []
    verdict = decide(exit_code, stdout, pulls, repo, now or datetime.now(UTC))
    for line in verdict.lines:
        print(f"osvscan: {line}")
    try:
        with open(out_path, "a", encoding="utf-8") as out:
            out.write(
                f"vulnerable={str(verdict.vulnerable).lower()}\n"
                f"scan_failed={str(verdict.scan_failed).lower()}\n"
                # Positive form for the workflow: empty (job crashed or cancelled) is not 'true'.
                f"scan_ok={str(not verdict.scan_failed).lower()}\n"
            )
    except OSError:
        print("osvscan: cannot write the step outputs")
        return 1
    return 0
