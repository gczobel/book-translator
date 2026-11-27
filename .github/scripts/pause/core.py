"""The pause switch: only an explicit `false` lets automation run (ADR 0005).

`PAUSE` is a repository variable. "false" means run, "true" means the owner paused
everything on purpose. Anything else, including a missing or mistyped variable, means
the switch can't be read: automation stops and the owner is told.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

State = Literal["run", "paused", "unreadable"]  # unreadable: stop and escalate


@dataclass(frozen=True)
class Decision:
    state: State

    @property
    def paused(self) -> bool:
        return self.state != "run"


def decide(value: str | None) -> Decision:
    if value == "false":
        return Decision("run")
    if value == "true":
        return Decision("paused")
    return Decision("unreadable")
