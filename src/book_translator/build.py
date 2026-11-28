"""The build step's synchronized edits, applied in place (ADR 0002).

Translated text goes in through `Epub.rebuild_block`; this module makes the rest of the book
agree with it: package metadata, `xml:lang`, chapter titles and notes. Nothing is added or
renamed except what is asked for, and an empty `SyncEdits` changes nothing.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from lxml import etree

from book_translator.epub import Epub
from book_translator.fonts import check_font_coverage
from book_translator.notes import AddedNote, add_notes
from book_translator.xmlparse import fromstring

_DC = "http://purl.org/dc/elements/1.1/"
_OPF = "http://www.idpf.org/2007/opf"
_NCX = "http://www.daisy.org/z3986/2005/ncx/"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

__all__ = ["AddedNote", "SyncEdits", "apply_synchronized_edits"]


@dataclass(frozen=True)
class SyncEdits:
    """What to synchronize across the book. A field left as None is left alone."""

    title: str | None = None
    description: str | None = None
    language: str | None = None
    translator: str | None = None
    chapter_titles: Mapping[str, str] = field(default_factory=dict)  # source label -> target
    added_notes: Sequence[AddedNote] = ()


def apply_synchronized_edits(epub: Epub, edits: SyncEdits) -> None:
    """Apply `edits` to the package, the table of contents and every content document."""
    _edit_package(epub, edits)
    if edits.title is not None:
        _edit_ncx_title(epub, edits.title)
    if edits.chapter_titles:
        _edit_titles(epub, edits.chapter_titles)
    if edits.added_notes:
        add_notes(epub, edits.added_notes)
    if edits.language is not None:
        check_font_coverage(epub, edits.language)
        for member in epub.spine():
            tree = etree.ElementTree(fromstring(epub.read(member)))
            tree.getroot().set(_XML_LANG, edits.language)
            epub.store(member, tree)


def _set_text(metadata: etree._Element, tag: str, text: str, **attrs: str) -> None:
    found = [
        e for e in metadata.iter(f"{{{_DC}}}{tag}") if all(e.get(k) == v for k, v in attrs.items())
    ]
    element = found[0] if found else etree.SubElement(metadata, f"{{{_DC}}}{tag}")
    for key, value in attrs.items():
        element.set(key, value)
    element.text = text


def _edit_package(epub: Epub, edits: SyncEdits) -> None:
    tree = etree.ElementTree(fromstring(epub.read(epub.opf_path)))
    metadata = tree.getroot().find(f"{{{_OPF}}}metadata")
    if metadata is None:
        return
    if edits.title is not None:
        _set_text(metadata, "title", edits.title)
    if edits.description is not None:
        _set_text(metadata, "description", edits.description)
    if edits.language is not None:
        _set_text(metadata, "language", edits.language)
    if edits.translator is not None:
        _set_text(metadata, "contributor", edits.translator, **{f"{{{_OPF}}}role": "trl"})
    epub.store(epub.opf_path, tree)


def _edit_ncx_title(epub: Epub, title: str) -> None:
    for member in epub.names:
        if member.lower().endswith(".ncx"):
            tree = etree.ElementTree(fromstring(epub.read(member)))
            for text in tree.getroot().iterfind(f"{{{_NCX}}}docTitle/{{{_NCX}}}text"):
                text.text = title
            epub.store(member, tree)


_LABELLED = {"h1", "h2", "h3", "h4", "h5", "h6", "a", "title", "text"}


def _edit_titles(epub: Epub, titles: Mapping[str, str]) -> None:
    """Rewrite each source chapter title wherever it stands as a label, heading or `title`."""
    for member in epub.names:
        if not member.lower().endswith((".xhtml", ".html", ".htm", ".ncx")):
            continue
        tree = etree.ElementTree(fromstring(epub.read(member)))
        for element in tree.getroot().iter():
            if not isinstance(element.tag, str):
                continue
            if element.get("title") in titles:
                element.set("title", titles[str(element.get("title"))])
            label = " ".join(_text(element).split())
            if (
                etree.QName(element).localname in _LABELLED
                and len(element) == 0
                and label in titles
            ):
                element.text = titles[label]
        epub.store(member, tree)


def _text(element: etree._Element) -> str:
    return etree.tostring(element, method="text", encoding="unicode", with_tail=False)
