"""Check that an automation workflow stops when automation is paused.

A workflow passes if every job is the pause gate, or runs only when the gate's `paused`
output is exactly 'false', or runs only after such a job and cannot run when that job was
skipped. The checks are deliberately strict: a condition we can't prove safe is rejected,
so the only way to pass is the documented pattern. Used by a unit test over
`.github/workflows`, so a new unattended workflow can't be added without deciding how it
pauses.
"""

from __future__ import annotations

import re
from typing import Any

GATE_WORKFLOW = "./.github/workflows/pause.yml"

# Workflows that are not unattended automation: PR checks, the pause switch itself, and the
# escalation job, which only runs on behalf of an automation workflow that already paused.
# A test also requires that none of them is scheduled or triggered by another workflow.
EXEMPT_WORKFLOWS = frozenset({"ci", "workflow-security", "guard", "hold", "escalate", "pause"})

# Downstream conditions that are false when the upstream job was skipped. Anything else
# (always(), !cancelled(), result checks, ...) might run while paused and is rejected.
_SKIP_SAFE_CONDITIONS = frozenset({"failure()", "cancelled()", "failure() || cancelled()"})


def _condition(job: dict[str, Any]) -> str:
    """The job's `if`, without `${{ }}` and with whitespace collapsed ('' if absent)."""
    text = str(job.get("if", "")).strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2]
    return re.sub(r"\s+", " ", text).strip()


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _tests_gate(job: dict[str, Any], gates: set[str]) -> bool:
    """True if the job runs only when a gate's output is 'false'.

    The condition must have no `||` and one of its `&&`-separated terms must be exactly the
    comparison, so the job cannot run unless the comparison is true.
    """
    condition = _condition(job)
    if "||" in condition:
        return False
    terms = [term.strip() for term in condition.split("&&")]
    needed = set(_needs(job))
    return any(
        g in needed and re.fullmatch(rf"needs\.{re.escape(g)}\.outputs\.paused == 'false'", t)
        for g in gates
        for t in terms
    )


def ungated_jobs(workflow: dict[str, Any]) -> list[str]:
    """Ids of jobs that could still run while automation is paused."""
    jobs: dict[str, dict[str, Any]] = (workflow or {}).get("jobs", {}) or {}
    gates = {name for name, job in jobs.items() if job.get("uses") == GATE_WORKFLOW}
    gated: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, job in jobs.items():
            if name in gates or name in gated:
                continue
            downstream = any(n in gated for n in _needs(job)) and (
                _condition(job) in _SKIP_SAFE_CONDITIONS or not job.get("if")
            )
            if _tests_gate(job, gates) or downstream:
                gated.add(name)
                changed = True
    return [name for name in jobs if name not in gates and name not in gated]
