"""Small repairs for model output that is right in substance and wrong in form.

A real model writes "Usted" for "usted", "tu" for "tú" or "Mr Otis" for "Mr. Otis". Rejecting
such an answer costs a paid retry (or the whole stage after three), so the validators settle
these slips first and keep rejecting what is wrong in substance.
"""

import unicodedata
from collections.abc import Callable
from typing import Any


def plain(text: str) -> str:
    """Case, accents, punctuation and spacing removed: what two spellings of a name share."""
    folded = unicodedata.normalize("NFKD", text)
    kept = "".join(
        c if c.isalnum() else " " for c in folded if not unicodedata.combining(c)
    ).casefold()
    return " ".join(kept.split())


def choice(*values: str) -> Callable[[Any], Any]:
    """A before-validator mapping a value to the allowed one it spells differently."""
    by_plain = {plain(v): v for v in values}

    def settle(value: Any) -> Any:
        if isinstance(value, str):
            return by_plain.get(plain(value), value)
        return value

    return settle


def percentage(value: Any) -> Any:
    """A confidence written as a percentage (85) is read as a fraction (0.85)."""
    if isinstance(value, int | float) and not isinstance(value, bool) and 1 < value <= 100:
        return value / 100
    return value


def in_order(entries: Any, ids: list[str], key: str) -> Any:
    """Entries answering each of `ids` exactly once come back in the order of `ids`, strays
    dropped. Anything else (a gap, a duplicate) is returned as given, for the validators."""
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return entries
    wanted = set(ids)
    kept = [
        {**e, key: e[key].strip()}
        for e in entries
        if isinstance(e.get(key), str) and e[key].strip() in wanted
    ]
    if sorted(e[key] for e in kept) != sorted(ids):
        return entries
    by_id = {e[key]: e for e in kept}
    return [by_id[i] for i in ids]
