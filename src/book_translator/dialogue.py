"""Dialogue layout: the style sheet's `dialogue` setting, applied to drafted target blocks.

The drafter renders speech inside « » whatever the setting. This deterministic step then lays
it out, so the result never depends on prompt wording. With `inline-quotes` the blocks stay as
drafted. With `raya-split` a block holding two or more speech turns becomes one block per turn
(a 1:N split under ADR 0001), each opening with the raya, and narrator incisos follow
docs/reference/epublibre.md section 3.2 (D1-D4, D6). Blocks with one or no turn are untouched.
"""

import re
from collections.abc import Callable, Sequence

from book_translator.bible import StyleSheet

_SPEECH = re.compile(r"«([^«»]*)»")


def lay_out(targets: Sequence[str], dialogue: str) -> list[str]:
    """The target blocks of one source block, laid out as `dialogue` asks."""
    if dialogue != "raya-split":
        return list(targets)
    return [piece for target in targets for piece in _split(target)]


def lay_out_legally(
    targets: Sequence[str], style: StyleSheet, is_legal: Callable[[Sequence[str]], bool]
) -> list[str]:
    """`lay_out`, falling back to the drafted blocks if the layout would break inline codes."""
    laid = lay_out(targets, style.dialogue)
    return laid if is_legal(laid) else list(targets)


def _split(text: str) -> list[str]:
    parts = _SPEECH.split(text)  # narration, speech, narration, speech, ..., narration
    narration, speech = parts[0::2], parts[1::2]
    turns: list[list[str]] = []  # each turn: speech, inciso, speech, ..., optional last inciso
    for index, said in enumerate(speech):
        if index == 0 or not narration[index].strip().endswith(","):
            turns.append([])
        turns[-1].append(said)
        if after := narration[index + 1].strip().lstrip(",").strip():
            turns[-1].append(after)
    if len(turns) < 2:
        return [text]
    blocks = [narration[0].strip()] if narration[0].strip() else []
    return blocks + [_render(turn) for turn in turns]


def _render(turn: list[str]) -> str:
    out = "—"
    for index in range(0, len(turn), 2):
        said = turn[index]
        inciso = turn[index + 1] if index + 1 < len(turn) else ""
        if not any(c.isalpha() for c in inciso):  # nothing but closing punctuation
            out += said + inciso
            continue
        if inciso[0].islower():  # a speech verb: the speech's own comma gives way to the raya
            said = said.removesuffix(",")
        out += said + " —" + inciso
        if index + 2 < len(turn):  # speech resumes: close the raya, comma stays outside
            out = out.removesuffix(",") + "—, "
    return out
