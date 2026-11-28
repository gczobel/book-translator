"""Progress lines for `run`, on stderr so stdout stays clean. Nothing here touches stored data."""

import sys
from collections.abc import Callable
from typing import Protocol

from book_translator.budget import Budget


class Tick(Protocol):
    """What a stage reports to. `begin` is called before each unit it is about to work on, with
    its place (0-based) and the number of units in all; the first call of a run says where the
    work starts. The call itself comes after each finished unit: (units done so far, in all)."""

    def __call__(self, done: int, total: int) -> None: ...

    def begin(self, index: int, total: int) -> None: ...


class _NoTick:
    """The tick of a stage run without a reporter."""

    def __call__(self, done: int, total: int) -> None:
        pass

    def begin(self, index: int, total: int) -> None:
        pass


no_tick: Tick = _NoTick()


class _Unit:
    def __init__(self, say: Callable[[str], None], stage: str, kind: str, spend: Callable[[], str]):
        self._say = say
        self._stage = stage
        self._kind = kind
        self._spend = spend
        self._begun = False

    def begin(self, index: int, total: int) -> None:
        if self._begun:
            return
        self._begun = True
        where = f"{self._kind} {index + 1}/{total}"
        verb = "starting" if index == 0 else "resuming at"
        self._say(f"[{self._stage}] {verb} {where}")

    def __call__(self, done: int, total: int) -> None:
        self._say(f"[{self._stage}] {self._kind} {done}/{total} done{self._spend()}")


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
        """A tick that prints `[stage] resuming at kind 3/10` before the first unit of the run
        and `[stage] kind 3/10 done  ($0.12 of $3.00)` after each one."""
        return _Unit(self._say, stage, kind, self._spend)

    def _spend(self) -> str:
        if self._budget is None or self._quiet:
            return ""
        return f"  (${self._budget.spent():.2f} of ${self._budget.cap():.2f})"
