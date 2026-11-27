"""Seam 2: the build step's synchronized edits, tested only through the codec's interface."""

from pathlib import Path

from lxml import etree

from book_translator.build import AddedNote, SyncEdits, apply_synchronized_edits
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


def note_pairs(epub: Epub) -> list[tuple[str, str]]:
    """(reference label, note text) in the order the references are read."""
    out = []
    for note in epub.book().notes:
        _, reference = epub.locate_block(note.reference)
        _, body = epub.locate_block(note.block)
        target = body.get("id")
        label = [
            "".join(a.itertext())
            for a in reference.iter("{http://www.w3.org/1999/xhtml}a")
            if a.get("href", "").endswith(f"#{target}")
        ]
        out.append((label[0], "".join(body.xpath("text()"))))
    return out


def test_notes_are_renumbered_when_a_note_is_added() -> None:
    epub = open_epub(FIXTURES / "notes.epub")
    assert note_pairs(epub) == [("[1]", "1. A small town."), ("[2]", "2. The mayor.")]
    first_block = "OEBPS/ch1.xhtml#1"

    apply_synchronized_edits(
        epub, SyncEdits(added_notes=[AddedNote(first_block, "Translator: a pun.")])
    )

    assert note_pairs(epub) == [
        ("[1]", "1. A small town."),
        ("[2]", "2. Translator: a pun."),
        ("[3]", "3. The mayor."),
    ]
    notes = etree.fromstring(epub.read("OEBPS/notes.xhtml"))
    ids = [p.get("id") for p in notes.iterfind(".//{http://www.w3.org/1999/xhtml}p")]
    assert ids[0] == "nt1" and ids[2] == "nt2" and len(set(ids)) == 3


def test_an_added_note_links_both_ways_with_fresh_ids() -> None:
    epub = open_epub(FIXTURES / "notes.epub")

    apply_synchronized_edits(
        epub, SyncEdits(added_notes=[AddedNote("OEBPS/ch1.xhtml#1", "Translator: a pun.")])
    )

    ns = {"h": "http://www.w3.org/1999/xhtml"}
    chapter = etree.fromstring(epub.read("OEBPS/ch1.xhtml"))
    notes = etree.fromstring(epub.read("OEBPS/notes.xhtml"))
    assert chapter.xpath("//h:a/@href", namespaces=ns) == ["notes.xhtml#nt1", "notes.xhtml#nt3"]
    assert chapter.xpath("//h:a/@id", namespaces=ns) == ["rf1", "rf3"]
    assert notes.xpath("//h:p[@id='nt3']/h:a/@href", namespaces=ns) == ["ch1.xhtml#rf3"]
