"""Decide what a daily OSV scan of uv.lock escalates (ADR 0005, "Vulnerabilities").

The scanner's exit code and JSON output go in; two independent verdicts come out. Everything
fails closed: output that can't be read or doesn't have the expected shape is a scan failure,
a severity that can't be read is "unknown", and an alert with no readable date is old.

Escalate (as `vulnerable`) on any of:
- high or critical severity (CVSS 7.0 and up) or unknown severity,
- any malicious-package entry (`MAL-`), by id or alias,
- an alert published more than 48 hours ago with no open Dependabot PR for the package.

Escalate (as `scan_failed`) when the scanner errors or its output can't be parsed.

Text in the OSV data comes from outside, so report lines keep only a safe character set:
they are printed to the Actions log, where `::` and newlines would be workflow commands.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

DEPENDABOT_ID = 49699333  # dependabot[bot]
HIGH = 7.0  # CVSS v3 "high" starts here
STALE_AFTER = timedelta(hours=48)
# osv-scanner exits 0 when clean and 1 when it found vulnerabilities; 127, 128 and the rest
# are errors (including "no packages found").
_OK_EXITS = (0, 1)
_UNSAFE = re.compile(r"[^A-Za-z0-9._+\- ]")


class ScanOutputError(Exception):
    """The scanner output is not the document we expect."""


@dataclass(frozen=True)
class Verdict:
    vulnerable: bool = False
    scan_failed: bool = False
    lines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Finding:
    package: str
    vuln_id: str
    aliases: tuple[str, ...]
    published: datetime | None
    severity: float | None  # None: unknown


def _safe(text: str) -> str:
    return _UNSAFE.sub("_", text)[:80]


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _score(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        score = float(value)
    except ValueError:
        return None
    return score if 0.0 <= score <= 10.0 else None


def _findings(stdout: str) -> list[_Finding]:
    try:
        doc = json.loads(stdout)
    except ValueError as error:
        raise ScanOutputError("output is not JSON") from error
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
        raise ScanOutputError("no results list")
    found: list[_Finding] = []
    for result in doc["results"]:
        packages = result.get("packages") if isinstance(result, dict) else None
        if not isinstance(packages, list):
            raise ScanOutputError("a result has no packages list")
        for entry in packages:
            found += _package_findings(entry)
    return found


def _package_findings(entry: object) -> list[_Finding]:
    if not isinstance(entry, dict):
        raise ScanOutputError("a package entry is not an object")
    package, vulns = entry.get("package"), entry.get("vulnerabilities", [])
    groups = entry.get("groups", [])
    if not isinstance(package, dict) or not isinstance(package.get("name"), str):
        raise ScanOutputError("a package has no name")
    if not isinstance(vulns, list) or not isinstance(groups, list):
        raise ScanOutputError("vulnerabilities or groups is not a list")
    out = []
    for vuln in vulns:
        if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str):
            raise ScanOutputError("a vulnerability has no id")
        aliases = vuln.get("aliases")
        names = {vuln["id"], *(a for a in aliases or [] if isinstance(a, str))}
        # The group's max_severity is the scanner's own CVSS roll-up; no group, no severity.
        severity = None
        for group in groups:
            if isinstance(group, dict) and names & {
                *group.get("ids", []),
                *group.get("aliases", []),
            }:
                severity = _score(group.get("max_severity"))
                break
        out.append(
            _Finding(
                package=package["name"],
                vuln_id=vuln["id"],
                aliases=tuple(sorted(names - {vuln["id"]})),
                published=_parse_time(vuln.get("published")),
                severity=severity,
            )
        )
    return out


def _has_open_pr(package: str, repo: str, pulls: Sequence[Mapping[str, Any]]) -> bool:
    """A Dependabot PR from this repository whose branch, title or body names the package.

    Grouped PRs carry no package name in the branch, so the title and body count too. Only
    Dependabot's own same-repository PRs are read, so a stranger can't suppress an alert.
    """
    pattern = re.compile(
        r"(?<![a-z0-9-])" + re.escape(_normalise(package)) + r"(?![a-z0-9])(?!-[a-z])"
    )
    for pull in pulls:
        if pull.get("author_id") != DEPENDABOT_ID or pull.get("head_repo") != repo:
            continue
        ref = pull.get("ref")
        if not isinstance(ref, str) or not ref.startswith("dependabot/uv/"):
            continue
        text = " ".join(str(pull.get(k) or "") for k in ("ref", "title", "body"))
        if pattern.search(_normalise(text)):
            return True
    return False


def _reasons(
    finding: _Finding, repo: str, pulls: Sequence[Mapping[str, Any]], now: datetime
) -> list[str]:
    reasons = []
    if any(n.startswith("MAL-") for n in (finding.vuln_id, *finding.aliases)):
        reasons.append("malicious package")
    if finding.severity is None:
        reasons.append("unknown severity")
    elif finding.severity >= HIGH:
        reasons.append(f"severity {finding.severity}")
    old = finding.published is None or now - finding.published > STALE_AFTER
    if old and not _has_open_pr(finding.package, repo, pulls):
        reasons.append("older than 48h with no open PR")
    return reasons


def decide(
    exit_code: int,
    stdout: str,
    pulls: Sequence[Mapping[str, Any]],
    repo: str,
    now: datetime,
) -> Verdict:
    if exit_code not in _OK_EXITS:
        return Verdict(scan_failed=True, lines=[f"scanner exited with {exit_code}"])
    try:
        findings = _findings(stdout)
    except ScanOutputError as error:
        return Verdict(scan_failed=True, lines=[f"cannot read scanner output: {error}"])
    if exit_code == 1 and not findings:
        return Verdict(scan_failed=True, lines=["scanner reported findings but none were parsed"])
    lines = []
    for finding in findings:
        reasons = _reasons(finding, repo, pulls, now)
        if reasons:
            lines.append(f"{_safe(finding.package)} {_safe(finding.vuln_id)}: {', '.join(reasons)}")
    return Verdict(vulnerable=bool(lines), lines=lines)
