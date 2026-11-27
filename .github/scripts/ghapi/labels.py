"""The `hold` kill switch, one rule for every workflow that honours it (ADR 0005, "Kill switches").

GitHub treats label names case-insensitively, so `Hold` and `HOLD` hold too.
"""

from __future__ import annotations

from collections.abc import Iterable

HOLD = "hold"


def is_on_hold(labels: Iterable[str]) -> bool:
    """True if any label is `hold`, whatever its case."""
    return any(label.casefold() == HOLD for label in labels)
