"""Seam 2: the credits page and source branding removal, tested through the codec's interface."""

from pathlib import Path

from lxml import etree

from book_translator.credits import Credits, add_credits_page
from book_translator.epub import Epub, open_epub

FIXTURES = Path(__file__).parent / "fixtures" / "epub"
CREDITS = Credits(
    original_title="Synthetic Tale",
    source_edition="Nobody, first edition 1999",
    tool="book-translator 0.1",
    model="example-model-1",
    date="2026-11-27",
)


def credits_text(epub: Epub) -> str:
    """Text of the book's single credits page, found through the structure model."""
    (part,) = [p for p in epub.book().front if p.kind == "credits"]
    return " ".join(b.text for b in part.blocks)


def test_credits_page_names_original_title_edition_and_machine_assisted_translation() -> None:
    epub = open_epub(FIXTURES / "plain.epub")

    add_credits_page(epub, CREDITS)

    text = credits_text(epub)
    for expected in [
        "Synthetic Tale",
        "Nobody, first edition 1999",
        "machine-assisted",
        "book-translator 0.1",
        "example-model-1",
        "2026-11-27",
    ]:
        assert expected in text
    spine = epub.spine()
    assert spine.index("OEBPS/credits.xhtml") < spine.index("OEBPS/ch1.xhtml")
    etree.fromstring(epub.read("OEBPS/credits.xhtml"))


def test_an_existing_credits_page_is_replaced_not_duplicated() -> None:
    epub = open_epub(FIXTURES / "matter.epub")

    add_credits_page(epub, CREDITS)

    text = credits_text(epub)
    assert "machine-assisted" in text
    assert "First published as Un Cuento" not in text
    assert epub.spine().count("OEBPS/credits.xhtml") == 1
