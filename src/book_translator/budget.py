"""The budget guard: every paid call is accounted in the workspace database, and a call that
would cross the per-book cap is refused before it is made."""

import sqlite3
from pathlib import Path

CAP_SETTING = "cap_usd"


class CapReachedError(Exception):
    """The next call would take the book past its spending cap."""


def set_cap(database: Path, cap_usd: float) -> None:
    db = sqlite3.connect(database)
    try:
        with db:
            db.execute(
                "insert or replace into settings values (?, ?)", (CAP_SETTING, f"{cap_usd:.2f}")
            )
    finally:
        db.close()


class Budget:
    def __init__(self, database: Path) -> None:
        self._database = database
        db = self._connect()
        try:
            with db:
                db.execute(
                    "create table if not exists spend"
                    " (id integer primary key autoincrement, stage text not null,"
                    " cost_usd real not null)"
                )
        finally:
            db.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database)

    def cap(self) -> float:
        db = self._connect()
        try:
            row = db.execute("select value from settings where key = ?", (CAP_SETTING,)).fetchone()
        finally:
            db.close()
        return float(row[0])

    def spent(self) -> float:
        db = self._connect()
        try:
            return float(db.execute("select coalesce(sum(cost_usd), 0) from spend").fetchone()[0])
        finally:
            db.close()

    def check(self, projected_usd: float) -> None:
        """Refuse a call whose projected cost would cross the cap.

        The projection is the dearest call accounted so far (a call is rarely dearer than the
        dearest one before it) or the caller's own estimate, whichever is higher.
        """
        db = self._connect()
        try:
            dearest = float(
                db.execute("select coalesce(max(cost_usd), 0) from spend").fetchone()[0]
            )
        finally:
            db.close()
        spent, cap = self.spent(), self.cap()
        if spent + max(dearest, projected_usd) > cap:
            raise CapReachedError(
                f"spending cap reached: ${spent:.2f} spent of ${cap:.2f};"
                " raise it with `run --cap` to continue"
            )

    def record(self, stage: str, cost_usd: float) -> None:
        db = self._connect()
        try:
            with db:
                db.execute("insert into spend (stage, cost_usd) values (?, ?)", (stage, cost_usd))
        finally:
            db.close()
