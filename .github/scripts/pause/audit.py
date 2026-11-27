"""Check that an automation workflow stops when automation is paused.

A workflow passes if every job is either the pause gate, tests the gate's `paused` output
for exactly `'false'`, or runs only after a job that does (so it is skipped with it).
Used by a unit test over `.github/workflows`, so a new unattended workflow can't be added
without deciding how it pauses.
"""

from __future__ import annotations

import re
from typing import Any

GATE_WORKFLOW = "./.github/workflows/pause.yml"

# Workflows that are not unattended automation: PR checks, the pause switch itself, and the
# escalation job, which only runs on behalf of an automation workflow that already paused.
EXEMPT_WORKFLOWS = frozenset({"ci", "workflow-security", "guard", "hold", "escalate", "pause"})

_ALWAYS = re.compile(r"\balways\s*\(")


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _tests_gate(job: dict[str, Any], gates: set[str]) -> bool:
    condition = re.sub(r"\s+", " ", str(job.get("if", "")))
    needed = set(_needs(job))
    return any(g in needed and f"needs.{g}.outputs.paused == 'false'" in condition for g in gates)


def ungated_jobs(workflow: dict[str, Any]) -> list[str]:
    """Ids of jobs that would still run while automation is paused."""
    jobs: dict[str, dict[str, Any]] = (workflow or {}).get("jobs", {}) or {}
    gates = {name for name, job in jobs.items() if job.get("uses") == GATE_WORKFLOW}
    ok = set(gates)
    changed = True
    while changed:
        changed = False
        for name, job in jobs.items():
            if name in ok:
                continue
            direct = _tests_gate(job, gates)
            # Downstream of a stopped job, a job is skipped too unless its `if` says always().
            downstream = any(n in ok - gates for n in _needs(job)) and not _ALWAYS.search(
                str(job.get("if", ""))
            )
            if direct or downstream:
                ok.add(name)
                changed = True
    return [name for name in jobs if name not in ok]
