"""What the workspace says about itself: QA failures, cost and what each stage changed."""

import sqlite3
from typing import Any

from book_translator.qa import stored_findings


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("select name from sqlite_master where type = 'table'")}


def _count(db: sqlite3.Connection, tables: set[str], table: str, by: str | None = None) -> Any:
    if table not in tables:
        return {} if by else 0
    if by:
        rows = db.execute(f"select {by}, count(*) from {table} group by {by} order by {by}")
        return {str(k): int(n) for k, n in rows}
    return int(db.execute(f"select count(*) from {table}").fetchone()[0])


def workspace_facts(db: sqlite3.Connection) -> dict[str, Any]:
    tables = _tables(db)
    findings = stored_findings(db)
    by_stage: dict[str, float] = {}
    if "spend" in tables:
        by_stage = {
            str(stage): round(float(cost), 6)
            for stage, cost in db.execute(
                "select stage, sum(cost_usd) from spend group by stage order by stage"
            )
        }
    changes: dict[str, int] = {"fidelity": _count(db, tables, "fidelity_edits")}
    changes.update(_count(db, tables, "polish_edits", "stage"))
    changes["typography"] = _count(db, tables, "typography_changes")
    unresolved = _count(db, tables, "unresolved_findings")
    return {
        "qa": {
            "passed": not findings and not unresolved,
            "findings": [
                {"check": f.check, "block": f.block, "message": f.message} for f in findings
            ],
            "unresolved_fidelity_findings": unresolved,
        },
        "cost": {"total_usd": round(sum(by_stage.values()), 6), "by_stage": by_stage},
        "stage_changes": changes,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Quality report",
        "",
        f"Output: {report['output']}  ",
        f"Reference: {report['reference']}  ",
        f"chrF overall: {report['chrf_overall']}",
        "",
        "## Per chapter (chrF)",
        "",
    ]
    for chapter in report["chapters"]:
        refs = ", ".join(chapter["reference_titles"]) or "no counterpart"
        lines.append(
            f"- {chapter['index']}. {chapter['title'] or '(untitled)'}: "
            f"{chapter['chrf']} (reference: {refs})"
        )
    for title in report["unaligned_reference_chapters"]:
        lines.append(f"- reference chapter without a counterpart: {title}")
    if "judge" in report:
        judge = report["judge"]
        lines += ["", "## Judge: errors", ""]
        lines += [f"- {t}: {n}" for t, n in judge["by_type"].items()] or ["- none"]
        lines += [
            "",
            "By severity: "
            + (", ".join(f"{s} {n}" for s, n in judge["by_severity"].items()) or "none"),
        ]
        lines += ["", "### Marks per scene", ""]
        for scene in judge["scenes"]:
            marks = "; ".join(f"{m['type']}/{m['severity']}: {m['note']}" for m in scene["marks"])
            lines.append(
                f"- chapter {scene['chapter']}, scene {scene['scene']}: {marks or 'no errors'}"
            )
    if report.get("diagnosis"):
        lines += ["", "## Diagnosis", ""]
        lines += [f"- {d['cause']} (fix: {d['fix']})" for d in report["diagnosis"]]
    qa = report["qa"]
    lines += ["", "## QA", ""]
    lines.append("passed" if qa["passed"] else f"{len(qa['findings'])} finding(s):")
    lines += [f"- [{f['check']}] {f['block']}: {f['message']}" for f in qa["findings"]]
    if qa["unresolved_fidelity_findings"]:
        lines.append(f"- {qa['unresolved_fidelity_findings']} unresolved fidelity finding(s)")
    lines += ["", "## Cost", "", f"Total: ${report['cost']['total_usd']:.2f}"]
    lines += [f"- {s}: ${c:.4f}" for s, c in report["cost"]["by_stage"].items()]
    lines += ["", "## Changes per stage", ""]
    lines += [f"- {stage}: {n}" for stage, n in report["stage_changes"].items()]
    return "\n".join(lines) + "\n"
