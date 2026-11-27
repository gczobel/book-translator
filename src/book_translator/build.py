"""The build step's synchronized edits, applied in place (ADR 0002).

Translated text goes in through `Epub.rebuild_block`; this module makes the rest of the book
agree with it: package metadata, `xml:lang`, chapter titles and notes. Nothing is added or
renamed except what is asked for, and an empty `SyncEdits` changes nothing.
"""

from dataclasses import dataclass

from lxml import etree

from book_translator.epub import Epub

_DC = "http://purl.org/dc/elements/1.1/"
_OPF = "http://www.idpf.org/2007/opf"
_NCX = "http://www.daisy.org/z3986/2005/ncx/"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

__all__ = ["SyncEdits", "apply_synchronized_edits"]


@dataclass(frozen=True)
class SyncEdits:
    """What to synchronize across the book. A field left as None is left alone."""

    title: str | None = None
    description: str | None = None
    language: str | None = None
    translator: str | None = None


def apply_synchronized_edits(epub: Epub, edits: SyncEdits) -> None:
    """Apply `edits` to the package, the table of contents and every content document."""
    _edit_package(epub, edits)
    if edits.title is not None:
        _edit_ncx_title(epub, edits.title)
    if edits.language is not None:
        for member in epub.spine():
            tree = etree.ElementTree(etree.fromstring(epub.read(member)))
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
    tree = etree.ElementTree(etree.fromstring(epub.read(epub.opf_path)))
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
            tree = etree.ElementTree(etree.fromstring(epub.read(member)))
            for text in tree.getroot().iterfind(f"{{{_NCX}}}docTitle/{{{_NCX}}}text"):
                text.text = title
            epub.store(member, tree)
