"""The status report: a read-only look at a workspace. It calls no LLM and writes nothing."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from book_translator.budget import CAP_SETTING
from book_translator.epub import open_epub
from book_translator.workspace import DB_NAME, SOURCE_NAME

# Pipeline order of the stages that exist so far; later stages are appended here.
STAGES = (
    "research",
    "extraction",
    "consolidation",
    "completion",
    "enrichment",
    "draft",
    "tk_resolution",
    "fidelity",
    "polish",
)
FINISHED = ("done", "nothing found")


@dataclass(frozen=True)
class Gate:
    """A review gate waiting for the reader: what it is and the command that clears it."""

    name: str
    command: str


@dataclass(frozen=True)
class Status:
    stage: str | None
    stage_state: str | None
    chapters_done: int
    chapters_total: int
    spent_usd: float
    cap_usd: float
    gate: Gate | None


def waiting_gate(db: sqlite3.Connection, workspace: Path) -> Gate | None:
    """The review gate waiting for approval, if any."""
    row = db.execute("select stage from stages where status = 'waiting'").fetchone()
    if row is None:
        return None
    return Gate(
        name=str(row[0]).removesuffix(" gate"), command=f"book-translator approve {workspace}"
    )


def read_status(workspace: Path) -> Status:
    db = sqlite3.connect(f"file:{workspace / DB_NAME}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in db.execute("select name from sqlite_master where type = 'table'")}
        states: dict[str, str | None] = {}
        if "stages" in tables:
            states = {r[0]: r[1] for r in db.execute("select stage, status from stages")}
        # Research is optional (it needs a search), so only stages that have started count.
        started = [s for s in STAGES if s in states]
        current = next((s for s in started if states[s] not in FINISHED), None)
        current = current or (started[-1] if started else None)
        done = 0
        if "extractions" in tables:
            done = db.execute("select count(*) from extractions").fetchone()[0]
        spent = 0.0
        if "spend" in tables:
            spent = float(db.execute("select coalesce(sum(cost_usd), 0) from spend").fetchone()[0])
        row = db.execute("select value from settings where key = ?", (CAP_SETTING,)).fetchone()
        gate = waiting_gate(db, workspace) if "stages" in tables else None
    finally:
        db.close()
    total = len(open_epub(workspace / SOURCE_NAME).book().chapters)
    return Status(
        stage=current,
        stage_state=states.get(current) if current else None,
        chapters_done=done,
        chapters_total=total,
        spent_usd=spent,
        cap_usd=float(row[0]),
        gate=gate,
    )


def render(status: Status, workspace: Path) -> str:
    if status.stage is None:
        stage = "not started"
    else:
        stage = f"{status.stage} ({status.stage_state})"
    lines = [
        f"Stage: {stage}",
        f"Progress: {status.chapters_done} of {status.chapters_total} chapters extracted",
        f"Spent: ${status.spent_usd:.2f} of ${status.cap_usd:.2f} cap",
    ]
    if status.gate is None:
        lines.append("Review gate: none waiting")
        finished = status.stage == STAGES[-1] and status.stage_state in FINISHED
        lines.append(
            "Next: nothing left to run" if finished else f"Next: book-translator run {workspace}"
        )
    else:
        lines.append(f"Review gate: {status.gate.name} is waiting")
        lines.append(f"Next: {status.gate.command}")
    return "\n".join(lines)
