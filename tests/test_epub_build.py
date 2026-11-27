"""Seam 2: the build step's synchronized edits, tested only through the codec's interface."""

from pathlib import Path

from lxml import etree

from book_translator.build import SyncEdits, apply_synchronized_edits
from book_translator.epub import Epub, open_epub

FIXTURES = Path(__file__).parent / "fixtures" / "epub"
DC = "{http://purl.org/dc/elements/1.1/}"
OPF = "{http://www.idpf.org/2007/opf}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def opf(epub: Epub) -> etree._Element:
    return etree.fromstring(epub.read("OEBPS/content.opf"))


def test_opf_metadata_and_xml_lang_are_updated() -> None:
    epub = open_epub(FIXTURES / "plain.epub")

    apply_synchronized_edits(
        epub,
        SyncEdits(
            title="Un Cuento Sintetico",
            description="Una tarde tranquila.",
            language="es",
            translator="Machine Assist",
        ),
    )

    meta = opf(epub)
    assert [e.text for e in meta.iter(f"{DC}title")] == ["Un Cuento Sintetico"]
    assert [e.text for e in meta.iter(f"{DC}description")] == ["Una tarde tranquila."]
    assert [e.text for e in meta.iter(f"{DC}language")] == ["es"]
    trl = [e for e in meta.iter(f"{DC}contributor") if e.get(f"{OPF}role") == "trl"]
    assert [e.text for e in trl] == ["Machine Assist"]
    for member in epub.spine():
        assert etree.fromstring(epub.read(member)).get(XML_LANG) == "es"
    ncx = etree.fromstring(epub.read("OEBPS/toc.ncx"))
    assert ncx.findtext(".//{http://www.daisy.org/z3986/2005/ncx/}docTitle/*") == (
        "Un Cuento Sintetico"
    )


def heading_texts(epub: Epub, member: str) -> list[str]:
    root = etree.fromstring(epub.read(member))
    return ["".join(h.itertext()) for h in root.iterfind(".//{http://www.w3.org/1999/xhtml}h1")]


def test_chapter_titles_agree_across_ncx_headings_and_head_title() -> None:
    epub = open_epub(FIXTURES / "plain.epub")

    apply_synchronized_edits(epub, SyncEdits(chapter_titles={"One": "Uno", "Two": "Dos"}))

    ncx = etree.fromstring(epub.read("OEBPS/toc.ncx"))
    labels = [t.text for t in ncx.iterfind(".//{http://www.daisy.org/z3986/2005/ncx/}text")][1:]
    assert labels == ["Uno", "Dos"]
    assert heading_texts(epub, "OEBPS/ch1.xhtml") == ["Uno"]
    assert heading_texts(epub, "OEBPS/ch2.xhtml") == ["Dos"]
    head = etree.fromstring(epub.read("OEBPS/ch1.xhtml")).find(
        "{http://www.w3.org/1999/xhtml}head/{http://www.w3.org/1999/xhtml}title"
    )
    assert head is not None and head.text == "Uno"


def test_chapter_titles_reach_the_toc_page_links_and_title_attributes() -> None:
    epub = open_epub(FIXTURES / "toc-page.epub")

    apply_synchronized_edits(epub, SyncEdits(chapter_titles={"One": "Uno", "Two": "Dos"}))

    root = etree.fromstring(epub.read("OEBPS/contents.xhtml"))
    links = root.findall(".//{http://www.w3.org/1999/xhtml}a")
    assert [("".join(a.itertext()), a.get("title")) for a in links] == [
        ("Uno", "Uno"),
        ("Dos", "Dos"),
    ]
    assert [a.get("href") for a in links] == ["ch1.xhtml", "ch2.xhtml"]


def test_chapter_titles_reach_the_epub3_nav() -> None:
    epub = open_epub(FIXTURES / "epub3.epub")

    apply_synchronized_edits(epub, SyncEdits(chapter_titles={"Chapter One": "Capitulo Uno"}))

    nav = etree.fromstring(epub.read("OEBPS/nav.xhtml"))
    links = ["".join(a.itertext()) for a in nav.iterfind(".//{http://www.w3.org/1999/xhtml}a")]
    assert links == ["Capitulo Uno", "Chapter Two"]
