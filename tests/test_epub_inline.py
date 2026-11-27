"""Seam 2: inline markup codes, tested only through the EPUB codec's public interface."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from lxml import etree

from book_translator.epub import Epub, InlineCodeError, open_epub

FIXTURES = Path(__file__).parent / "fixtures" / "epub"
MEMBER = "OEBPS/ch1.xhtml"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"


def block_id(epub: Epub, starts_with: str) -> str:
    blocks = [b for c in epub.book().chapters for s in c.scenes for b in s.blocks]
    return next(b.id for b in blocks if b.text.startswith(starts_with))


def canonical(data: bytes) -> bytes:
    return etree.tostring(etree.fromstring(data), method="c14n")


def text_of(el: etree._Element) -> str:
    return str(etree.tostring(el, method="text", encoding="unicode", with_tail=False))


def paragraph(epub: Epub, starts_with: str) -> etree._Element:
    root = etree.fromstring(epub.read(MEMBER))
    return next(p for p in root.iterfind(".//{*}p") if text_of(p).startswith(starts_with))


def test_decoding_an_encoded_block_reproduces_the_original_element() -> None:
    epub = open_epub(FIXTURES / "inline-markup.epub")
    original = epub.read(MEMBER)
    bid = block_id(epub, "She said")
    encoded = epub.encode_block(bid)

    epub.replace_block(bid, encoded, encoded.text)

    assert canonical(epub.read(MEMBER)) == canonical(original)


def test_translated_text_keeps_the_original_markup_and_attributes() -> None:
    epub = open_epub(FIXTURES / "inline-markup.epub")
    bid = block_id(epub, "She said")
    encoded = epub.encode_block(bid)

    epub.replace_block(
        bid,
        encoded,
        encoded.text.replace("Tom &amp; Jerry", "Tomás y Jerry").replace("very", "muy"),
    )

    p = paragraph(epub, "She said")
    link = p.find(".//{*}a[@class='ref']")
    assert link is not None
    assert (link.get("href"), link.get("id"), link.text) == ("ch2.xhtml#t", "l1", "Tomás y Jerry")
    assert p.get("id") == "p1" and p.get("class") == "first"
    inner = p.find(".//{*}i")
    assert inner is not None and (inner.get("class"), inner.text) == ("x", "muy")


def test_standalone_codes_survive_being_moved_in_the_translation() -> None:
    epub = open_epub(FIXTURES / "inline-markup.epub")
    bid = block_id(epub, "She said")
    encoded = epub.encode_block(bid)
    # Put the text after the line break first: a legal reordering of standalone codes.
    before, _, after = encoded.text.partition("then left.")
    epub.replace_block(bid, encoded, "then left." + after + before)

    p = paragraph(epub, "then left")
    assert p.find("{*}br") is not None
    note = p.find("{*}a[@id='r1']")
    assert note is not None
    assert note.attrib[EPUB_TYPE] == "noteref"
    assert note.get("href") == "notes.xhtml#n1" and note.text == "1"


def test_text_that_looks_like_markup_round_trips_as_text() -> None:
    epub = open_epub(FIXTURES / "inline-markup.epub")
    bid = block_id(epub, "She said")
    encoded = epub.encode_block(bid)

    epub.replace_block(bid, encoded, encoded.text.replace("then left.", "a &lt; b &amp; c."))

    assert "a < b & c." in text_of(paragraph(epub, "She said"))


def drop_first(text: str, code: str) -> str:
    return text.replace(code, "", 1)


def first_ph(text: str) -> str:
    return re.search(r'<ph id="\d+"/>', text).group(0)  # type: ignore[union-attr]


BAD_RESPONSES = [
    ("a closing code is missing", lambda t: drop_first(t, "</pc>"), "original pair"),
    ("an opening code is missing", lambda t: drop_first(t, '<pc id="2">'), "closing"),
    ("a standalone code is missing", lambda t: drop_first(t, first_ph(t)), "missing"),
    ("a standalone code is duplicated", lambda t: t + first_ph(t), "more than once"),
    ("the response is cut off inside a pair", lambda t: t[: t.index("very")], "not closed"),
    ("a code is unknown", lambda t: t + '<ph id="99"/>', "unknown"),
    ("a stray tag appears", lambda t: t + "<b>", "unexpected"),
    (
        "a nested pair is turned inside out",
        lambda t: (
            t.replace('<pc id="1">', '<pc id="@">')
            .replace('<pc id="2">', '<pc id="1">')
            .replace('<pc id="@">', '<pc id="2">')
        ),
        "original",
    ),
    ("everything is dropped", lambda t: "Dijo eso.", "missing"),
]


@pytest.mark.parametrize(("reason", "damage", "expected"), BAD_RESPONSES)
def test_damaged_codes_are_rejected_with_a_reason_and_the_block_is_left_alone(
    reason: str, damage: Callable[[str], str], expected: str
) -> None:
    epub = open_epub(FIXTURES / "inline-markup.epub")
    original = epub.read(MEMBER)
    bid = block_id(epub, "She said")
    encoded = epub.encode_block(bid)

    with pytest.raises(InlineCodeError, match=expected):
        epub.replace_block(bid, encoded, damage(encoded.text))

    assert epub.read(MEMBER) == original


def test_only_the_member_holding_the_block_changes_when_the_book_is_written(
    tmp_path: Path,
) -> None:
    source = FIXTURES / "inline-markup.epub"
    epub = open_epub(source)
    bid = block_id(epub, "Plain words")
    epub.replace_block(bid, epub.encode_block(bid), "Solo palabras.")
    out = tmp_path / "out.epub"

    epub.write(out)

    before, after = open_epub(source), open_epub(out)
    assert after.names == before.names
    assert [n for n in after.names if after.read(n) != before.read(n)] == [MEMBER]


def test_a_block_without_inline_markup_encodes_to_its_text() -> None:
    epub = open_epub(FIXTURES / "inline-markup.epub")
    bid = block_id(epub, "Plain words")
    encoded = epub.encode_block(bid)

    assert encoded.text == "Plain words only."
    epub.replace_block(bid, encoded, "Solo palabras sencillas.")
    assert text_of(paragraph(epub, "Solo")) == "Solo palabras sencillas."
