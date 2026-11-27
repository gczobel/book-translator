"""Seam 2: the credits page and source branding removal, tested through the codec's interface."""

import posixpath
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

from book_translator.credits import Credits, add_credits_page, remove_branding
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


def dangling(epub: Epub) -> list[str]:
    """Every href, src or content reference to a member the archive no longer holds."""
    missing = []
    for name in epub.names:
        if not name.endswith((".xhtml", ".opf", ".ncx")):
            continue
        for element in etree.fromstring(epub.read(name)).iter():
            if not isinstance(element.tag, str):
                continue
            for attr in ("href", "src"):
                target = element.get(attr)
                if target and "://" not in target:
                    path = posixpath.join(posixpath.dirname(name), unquote(target.split("#")[0]))
                    if target.split("#")[0] and posixpath.normpath(path) not in epub.names:
                        missing.append(f"{name} -> {target}")
    return missing


def test_branding_images_page_and_references_are_removed_without_dangling_references() -> None:
    epub = open_epub(FIXTURES / "epublibre.epub")

    remove_branding(epub)

    assert not [n for n in epub.names if "EPL_logo" in n or "ex_libris" in n or "exlibris" in n]
    assert epub.spine() == [
        "OEBPS/titulo.xhtml",
        "OEBPS/info.xhtml",
        "OEBPS/ch1.xhtml",
        "OEBPS/ch2.xhtml",
    ]
    package = epub.read("OEBPS/content.opf").decode()
    for gone in ["EPL_logo", "ex_libris", "exlibris", "ePubLibre", "EPL"]:
        assert gone not in package
    assert "Ex libris" not in epub.read("OEBPS/toc.ncx").decode()
    info = epub.read("OEBPS/info.xhtml").decode()
    assert "bloque_exlibris" not in info and "<img" not in info
    assert "Titivillus" in info
    assert "tlogo" not in epub.read("OEBPS/titulo.xhtml").decode()
    assert dangling(epub) == []


def test_credits_added_after_branding_removal_leave_a_consistent_book() -> None:
    epub = open_epub(FIXTURES / "epublibre.epub")

    remove_branding(epub)
    add_credits_page(epub, CREDITS)

    assert "OEBPS/credits.xhtml" in epub.spine()
    assert "machine-assisted" in credits_text(epub)
    assert dangling(epub) == []
