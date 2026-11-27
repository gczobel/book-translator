"""Progress lines for `run`, on stderr so stdout stays clean. Nothing here touches stored data."""

import sys
from collections.abc import Callable

from book_translator.budget import Budget

Tick = Callable[[int, int], None]
"""Called by a stage after each finished unit of work: (units done so far, units in all)."""


def no_tick(done: int, total: int) -> None:
    """The tick of a stage run without a reporter."""


class Progress:
    """Writes one line per event. The silent reporter (`Progress(None, quiet=True)`) writes none."""

    def __init__(self, budget: Budget | None, *, quiet: bool = False) -> None:
        self._budget = budget
        self._quiet = quiet

    def with_budget(self, budget: Budget) -> "Progress":
        return Progress(budget, quiet=self._quiet)

    def _say(self, line: str) -> None:
        if not self._quiet:
            print(line, file=sys.stderr, flush=True)

    def start(self, stage: str, note: str = "") -> None:
        self._say(f"[{stage}] start{note}")

    def end(self, stage: str) -> None:
        self._say(f"[{stage}] done{self._spend()}")

    def skipped(self, stage: str) -> None:
        self._say(f"[{stage}] skipped (nothing left to do)")

    def unit(self, stage: str, kind: str) -> Tick:
        """A tick that prints `[stage] kind 3/10 done  ($0.12 of $3.00)`."""

        def tick(done: int, total: int) -> None:
            self._say(f"[{stage}] {kind} {done}/{total} done{self._spend()}")

        return tick

    def _spend(self) -> str:
        if self._budget is None or self._quiet:
            return ""
        return f"  (${self._budget.spent():.2f} of ${self._budget.cap():.2f})"
