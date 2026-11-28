"""Dialogue layout: the style sheet's `dialogue` setting, applied to drafted target blocks.

The drafter renders speech inside « » whatever the setting. This deterministic step then lays
it out, so the result never depends on prompt wording. With `inline-quotes` the blocks stay as
drafted. With `raya-split` a block holding two or more speech turns becomes one block per turn
(a 1:N split under ADR 0001), each opening with the raya, and narrator incisos follow
docs/reference/epublibre.md section 3.2 (D1-D4, D6). Blocks with one or no turn are untouched.
"""

import re
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Sequence

from book_translator.bible import StyleSheet
from book_translator.epub import Epub
from book_translator.inline import InlineCodeError

_SPEECH = re.compile(r"«([^«»]*)»")


def lay_out(targets: Sequence[str], dialogue: str) -> list[str]:
    """The target blocks of one source block, laid out as `dialogue` asks."""
    if dialogue != "raya-split":
        return list(targets)
    return [
        paragraph
        for target in targets
        for piece in _split(target)
        for paragraph in break_paragraphs(piece)
    ]


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


_NARRATION_ENDS = re.compile(r"\n+|(?<=[.!?\u2026:])[ \t]+(?=\u2014[^\s\u2014])")


def break_paragraphs(text: str) -> list[str]:
    """Narration and speech never share a paragraph: a raya that opens speech after narration
    (after a full stop or a colon, or on a new line) starts a paragraph of its own. A paragraph
    that already opens with a raya is left whole, and so is a raya inside an open « »: both
    are incisos."""
    if text.lstrip().startswith("\u2014"):
        return [text]
    for end in _NARRATION_ENDS.finditer(text):
        if text[: end.start()].count("\u00ab") == text[: end.start()].count("\u00bb"):
            return [text[: end.start()].strip(), text[end.end() :].strip()]
    return [text]


def relayout(db: sqlite3.Connection, source: Epub, style: StyleSheet) -> int:
    """Break narration from speech in the stored target blocks, renumbering their positions.
    Deterministic and idempotent. A block whose new layout would break its inline codes is left
    as it is. Returns how many source blocks changed."""
    if style.dialogue != "raya-split":
        return 0
    pieces: dict[str, list[str]] = defaultdict(list)
    for block, text in db.execute("select source, text from targets order by source, position"):
        pieces[str(block)].append(str(text))
    changed = 0
    with db:
        for block, texts in pieces.items():
            laid = [paragraph for text in texts for paragraph in break_paragraphs(text)]
            if laid == texts:
                continue
            try:
                source.encode_block(block).validate_pieces(laid)
            except (InlineCodeError, KeyError):
                continue
            db.execute("delete from targets where source = ?", (block,))
            db.executemany(
                "insert into targets values (?, ?, ?)",
                [(block, n, text) for n, text in enumerate(laid)],
            )
            changed += 1
    return changed
