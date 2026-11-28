"""Checks on a rendering that is about to be pasted into a sentence."""

import re

_PARENTHETICAL = re.compile(r"\([^)]*\)")


def has_note(rendering: str, source_text: str) -> bool:
    """True when the rendering carries a note: a parenthetical that is not in `source_text`.

    A parenthetical that the source text itself has is part of the text; any other is an
    explanation, which belongs in the reason, not in the sentence.
    """
    return any(p not in source_text for p in _PARENTHETICAL.findall(rendering))
