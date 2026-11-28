"""S8a: Spanish typography, applied to the stored targets and checked by QA. No LLM is called.

The normaliser runs after the post-polish fidelity stage and before QA, on every run. It applies
only the mechanical rules of docs/reference/epublibre.md section 3 and section 5.4 that have one
safe reading, and records each change in `typography_changes`. A second run changes nothing
(idempotent). Whatever it cannot fix safely is left as it is and reported by the QA checks
registered below, one per rule family.

Inline codes (`<pc id="n">`, `</pc>`, `<ph id="n"/>`) are lifted out of the text before any rule
runs and put back afterwards, so a rule can never touch them. A rewrite that would break the
block's codes is dropped.
"""

import re
import sqlite3
from collections.abc import Callable

from book_translator.bible import Bible
from book_translator.epub import Epub
from book_translator.inline import InlineCodeError
from book_translator.qa import Finding, QAContext, check, plain

STAGE = "typography"
OPEN_CODE, CLOSE_CODE, STANDALONE_CODE = "", "", ""
_CODE = re.compile(r'<pc id="\d+">|</pc>|<ph id="\d+"/>')
_PLACEHOLDER = re.compile("[-]")


def mask(text: str) -> tuple[str, list[str]]:
    """The text with each inline code replaced by one private character, and the codes."""
    codes: list[str] = []

    def lift(match: re.Match[str]) -> str:
        code = match.group()
        codes.append(code)
        if code == "</pc>":
            return CLOSE_CODE
        return OPEN_CODE if code.startswith("<pc") else STANDALONE_CODE

    return _CODE.sub(lift, text), codes


def unmask(text: str, codes: list[str]) -> str:
    supply = iter(codes)
    return _PLACEHOLDER.sub(lambda _: next(supply), text)


_OPENERS = "  \t\n([{—«“‘" + OPEN_CODE + STANDALONE_CODE
_QUOTE_CHARS = "\"'«»“”‘’"
_LEVELS = (("«", "»"), ("“", "”"), ("‘", "’"))


def _requote(text: str) -> tuple[str, int] | None:
    """The text with its quotes re-set by depth, and the depth left open at its end. None when a
    quote closes what was never opened."""
    out: list[str] = []
    depth = 0
    single: list[bool] = []  # per open quote: opened as a single quote, so ’ may close it
    for index, char in enumerate(text):
        if char not in _QUOTE_CHARS:
            out.append(char)
            continue
        before = text[index - 1] if index else ""
        after = text[index + 1] if index + 1 < len(text) else ""
        if char in "'’" and before.isalnum() and after.isalnum():
            out.append("’")  # an apostrophe
            continue
        if char in "'’" and before.isalpha() and not (single and single[-1]):
            out.append("’")  # an elision at the end of a word (na’, to’), no single quote open
            continue
        if char in "\"'" and before.isdigit():
            out.append(char)  # Q2: a measure (52° 2' 20")
            continue
        if char == "»" and index == 0:
            out.append(char)  # Q6: a continuation paragraph opens with a closing guillemet
            depth = 1
            single = [False]
            continue
        if char in "«“‘" or (char in "\"'" and (not before or before in _OPENERS)):
            depth += 1
            single.append(char in "'‘")
            out.append(_LEVELS[min(depth, 3) - 1][0])
            continue
        if depth == 0:
            return None
        tail = ""
        while out and out[-1] in ".,;:":
            tail = out.pop() + tail
        out.append(_LEVELS[min(depth, 3) - 1][1] + tail)
        depth -= 1
        single.pop()
    return "".join(out), depth


def quotes(text: str, continued: bool = False) -> str:
    """Q1-Q4 (3.1): straight and curly quotes are re-set by depth as « » then “ ” then ‘ ’, and a
    period, comma, semicolon or colon inside a closing quote goes outside it. Text whose quotes
    do not pair up is left alone (the `quotes` check reports it), unless the quote left open
    continues in the next paragraph (`continued`, Q6)."""
    done = _requote(text)
    return text if done is None or (done[1] and not continued) else done[0]


@check("quotes")
def quote_pairing(context: QAContext) -> list[Finding]:
    """Quotes must pair up. Q6: a quote left open may continue in the next paragraph, which then
    opens with »."""
    pieces = [(b, mask(t)[0]) for b, ts in context.targets.items() for t in ts]
    found = []
    for index, (block, text) in enumerate(pieces):
        done = _requote(text)
        continued = index + 1 < len(pieces) and pieces[index + 1][1].startswith("\u00bb")
        if done is None or (done[1] and not continued):
            found.append(Finding("quotes", block, "its quotes do not pair up"))
        elif done[0] != text:
            found.append(Finding("quotes", block, "its quotes are not set as « » “ ” ‘ ’"))
    return found


RAYA = "\u2014"
_DASHES = "\u2013\u2015\u2014-"
_SPEECH_DASH = re.compile(rf"^\s*[{_DASHES}]+\s*(?=[^\s\d{_DASHES}])")
_DASH_AS_RAYA = re.compile(
    # spaced hyphen, --, ―, –; a hyphen or en dash before a number is a label ("Saga - 05")
    r"\s+[-\u2013\u2015]+(?!\s*\d)\s+|--+|\u2015|(?<!\d)\u2013(?!\s*\d)|\u2013(?!\s*\d)"
)
_NEXT_WORD = re.compile(r"[^\W_]|[\u00bf\u00a1\u00ab\u201c\u2018(\ue000\ue002]")
_LOWER = "a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00fc"


def _is_dialogue(text: str) -> bool:
    return _SPEECH_DASH.match(text) is not None


def raya(text: str) -> str:
    """D1-D4, D8 (3.2, 3.3): a leading dash opens the speech with a raya glued to its first word;
    a dash used as a raya (--, –, ―, spaced hyphen) becomes —; incisos are paired, the opening
    raya spaced before and glued after, the closing one glued before. In a speech, a comma before
    an inciso goes (D4) and a closing raya ending the paragraph goes (D3). An odd number of
    rayas outside a speech has no safe reading and is left for the `raya` check."""
    dialogue = _is_dialogue(text)
    body = _SPEECH_DASH.sub("", text, count=1) if dialogue else text
    body = _DASH_AS_RAYA.sub(RAYA, body)
    count = body.count(RAYA)
    if count % 2 and not dialogue:
        return text
    pieces = body.split(RAYA)
    out = pieces[0]
    for index, piece in enumerate(pieces[1:]):
        if index % 2 == 0:  # an opening raya: spaced before, glued after
            out = out.rstrip()
            if dialogue and re.match(rf"[{_LOWER}]", piece.lstrip()):
                out = out.removesuffix(",").removesuffix(";")  # D4
            out += ("" if not out or out[-1] in "([\u00ab\u201c" else " ") + RAYA + piece.lstrip()
        else:  # a closing raya: glued before, a space after unless a sign or the end follows
            rest = piece.lstrip()
            out = out.rstrip() + RAYA + (" " if _NEXT_WORD.match(rest) else "") + rest
    if dialogue and count and count % 2 == 0 and out.endswith(RAYA):  # D3
        out = out.removesuffix(RAYA)
        out += "" if out[-1:] in ".?!\u2026" else "."
    return (RAYA if dialogue else "") + out


_MARK = re.compile(r"[?!]")
_SEGMENT_START = re.compile(
    r"(?:^|(?<=[\u00ab\u201c\u2018\u2014])|(?<=[.!?\u2026]\s)|(?<=[.!?\u2026][\u00bb\u201d\u2019)]\s))"
)
_UNSURE_FIRST_WORDS = frozenset(
    "pero y o u e ni que pues entonces así bueno aunque mas sino si".split()
)
_OPENER = {"?": "\u00bf", "!": "\u00a1"}


def inverted_marks(text: str) -> str:
    """P2 (3.4, 5.4): a sentence that is wholly a question or exclamation, with no opener, gets its
    ¿ or ¡ at its start. Anything else (a partial question after a conjunction, commas inside, a
    mixed ?! ending) has more than one reading and is left for the `inverted_marks` check."""
    for match in reversed(list(_MARK.finditer(text))):
        end = match.start()
        start = max(m.end() for m in _SEGMENT_START.finditer(text, 0, end))
        segment = text[start:end]
        opener = _OPENER[match.group()]
        if text[:start].count(opener) > text[:start].count(match.group()):
            continue  # its opener is already there, before an ellipsis or full stop inside it
        first = segment.split(" ", 1)[0].lower() if segment else ""
        if (
            not segment
            or not segment[0].isalpha()
            or first in _UNSURE_FIRST_WORDS
            or re.search(r"[\u00bf\u00a1?!,;:]", segment)
            or text[end + 1 : end + 2] in ("?", "!")
        ):
            continue
        text = text[:start] + opener + text[start:]
    return text


@check("inverted_marks")
def inverted_mark_pairs(context: QAContext) -> list[Finding]:
    """Every ? and ! needs its ¿ or ¡ (P2): the openers and closers of a block must match."""
    found = []
    for block, texts in context.targets.items():
        text = "".join(plain(t) for t in texts)
        for opener, closer in (("\u00bf", "?"), ("\u00a1", "!")):
            if text.count(opener) != text.count(closer):
                found.append(
                    Finding("inverted_marks", block, f"its {opener} and {closer} do not match (P2)")
                )
    return found


NBSP = " "
_ENGLISH_DECIMAL = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+)\.(\d+)")
_GROUPED = re.compile(r"(?<![\d.,])(\d{1,3}(?:([.,])\d{3}){2,})(?!\d)")
_PERCENT = re.compile(r"(?<=\d) ?%")


def _group(digits: str) -> str:
    """Digits grouped in threes with a no-break space from five digits up (N2)."""
    if len(digits) < 5:
        return digits
    head = len(digits) % 3
    groups = ([digits[:head]] if head else []) + [
        digits[i : i + 3] for i in range(head, len(digits), 3)
    ]
    return NBSP.join(groups)


def numbers(text: str) -> str:
    """N2, N6 (3.7, 5.4): `1,000.5` is `1000,5`, groups of three digits are joined by a no-break
    space (`8.327.451` and `8,327,451` are `8 327 451`), and `%` follows its number after a
    no-break space. A single group (`1.200`) may be a decimal or a thousand: it is left alone."""
    text = _ENGLISH_DECIMAL.sub(
        lambda m: _group(re.sub(r"\D", "", m.group(1))) + "," + m.group(2), text
    )
    text = _GROUPED.sub(lambda m: _group(re.sub(r"\D", "", m.group(1))), text)
    return _PERCENT.sub(NBSP + "%", text)


_MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre"
_DAYS = "lunes martes miércoles jueves viernes sábado domingo"
_CAPITAL = "A-ZÁÉÍÓÚÑ"
_MONTH_AFTER = re.compile(
    rf"\b(de|en|desde|hasta)\s+({'|'.join(w.capitalize() for w in _MONTHS.split())})\b"
    rf"(?!\s+[{_CAPITAL}])"
)
_DAY_AFTER = re.compile(
    r"\b(el|los|este|ese|aquel|del|al|cada|un|próximo|pasado|último)\s+"
    rf"({'|'.join(w.capitalize() for w in _DAYS.split())})\b(?!\s+[{_CAPITAL}])"
)


def months_days(text: str) -> str:
    """3.6, 5.4: months and days are lowercase. Only where a capital cannot be the start of a
    sentence or a name: after `de`, `en`, `el`, `este`... and before no capitalised word."""
    lower = lambda m: f"{m.group(1)} {m.group(2).lower()}"  # noqa: E731
    return _DAY_AFTER.sub(lower, _MONTH_AFTER.sub(lower, text))


@check("number_format")
def number_format(context: QAContext) -> list[Finding]:
    return [
        Finding("number_format", block, "its numbers are not set as N2 and N6 ask")
        for block, texts in context.targets.items()
        if any(numbers(mask(t)[0]) != mask(t)[0] for t in texts)
    ]


@check("raya")
def raya_layout(context: QAContext) -> list[Finding]:
    """What the normaliser could not settle: a dash that is not a raya, rayas that do not pair up
    outside a speech (D8), a paragraph ending in a raya (D3), or a layout still off (D1-D4)."""
    found = []
    for block, texts in context.targets.items():
        for text in (mask(t)[0] for t in texts):
            body = _SPEECH_DASH.sub("", text, count=1) if _is_dialogue(text) else text
            if _DASH_AS_RAYA.search(body) or (body.count(RAYA) % 2 and not _is_dialogue(text)):
                found.append(Finding("raya", block, "its rayas do not pair up as incisos (D8)"))
            elif text.endswith(RAYA):
                found.append(Finding("raya", block, "it ends in a raya (D3)"))
            elif raya(text) != text:
                found.append(Finding("raya", block, "its rayas are not laid out as D1-D4 ask"))
    return found


_THOUGHT_VERB = r"(?:pens\w+|se dijo|se dijeron|me dije|se preguntó|me pregunté)\b"
_QUOTED_THOUGHT = re.compile(rf"«[^«»]+»,?\s+{_THOUGHT_VERB}")
_ITALIC_THOUGHT = re.compile(rf'<pc id="(\d+)">[^<]+</pc>,?\s+{_THOUGHT_VERB}')


@check("thoughts")
def thought_style(context: QAContext) -> list[Finding]:
    """Thoughts are set the one way the style sheet chose, everywhere (Q5, 5.4): in italics or in
    « ». A thought is a quote or an italic span followed by a thinking verb (`pensó`, `se dijo`).
    The normaliser cannot switch between the two (it may not add or drop an inline code), so
    a thought in the other style is reported."""
    choice = context.bible.style.thoughts
    found = []
    for block, texts in context.targets.items():
        for text in texts:
            if choice != "quotation marks" and _QUOTED_THOUGHT.search(text):
                found.append(Finding("thoughts", block, f"a thought is in « », not {choice}"))
            italic = [
                m
                for m in _ITALIC_THOUGHT.finditer(text)
                if context.sources[block].element_name(int(m.group(1))) in ("i", "em")
            ]
            if choice != "italics" and italic:
                found.append(Finding("thoughts", block, f"a thought is in italics, not {choice}"))
    return found


RULES: list[tuple[str, Callable[[str], str]]] = [
    ("quotes", quotes),
    ("raya", raya),
    ("inverted_marks", inverted_marks),
    ("numbers", numbers),
    ("months_days", months_days),
]


def normalise(text: str, continued: bool = False) -> list[tuple[str, str, str]]:
    """Apply every rule in turn: each change as (rule, old, new), the last new being the result.
    `continued` says the next paragraph opens with », continuing a quote left open here."""
    masked, codes = mask(text)
    changes: list[tuple[str, str, str]] = []
    for name, rule in RULES:
        new = quotes(masked, continued) if rule is quotes else rule(masked)
        if new != masked:
            changes.append((name, unmask(masked, codes), unmask(new, codes)))
            masked = new
    return changes


def create_tables(db: sqlite3.Connection) -> None:
    db.execute(
        "create table if not exists typography_changes (id integer primary key autoincrement,"
        " block text not null, position integer not null, rule text not null,"
        " old text not null, new text not null)"
    )


def apply(db: sqlite3.Connection, source: Epub, bible: Bible) -> None:
    """Normalise every stored target block that has a change to make, and record the changes."""
    rows = db.execute("select source, position, text from targets order by source, position")
    stored = [(str(b), int(p), str(t)) for b, p, t in rows]
    pieces: dict[str, list[str]] = {}
    for block, _, text in stored:
        pieces.setdefault(block, []).append(text)
    with db:
        for index, (block, position, text) in enumerate(stored):
            following = stored[index + 1][2] if index + 1 < len(stored) else ""
            changes = normalise(text, mask(following)[0].startswith("\u00bb"))
            if not changes:
                continue
            result = changes[-1][2]
            fixed = [result if p == position else t for p, t in enumerate(pieces[block])]
            if not _legal(source, block, fixed):
                continue
            db.execute(
                "update targets set text = ? where source = ? and position = ?",
                (result, block, position),
            )
            db.executemany(
                "insert into typography_changes (block, position, rule, old, new)"
                " values (?, ?, ?, ?, ?)",
                [(block, position, rule, old, new) for rule, old, new in changes],
            )
            pieces[block][position] = result


def _legal(source: Epub, block: str, pieces: list[str]) -> bool:
    try:
        source.encode_block(block).validate_pieces(pieces)
    except (InlineCodeError, KeyError):
        return False
    return True
