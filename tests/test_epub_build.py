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
