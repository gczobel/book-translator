"""The credits page and source branding removal (ADR 0002).

The credits page names the original title, the source edition and that the translation is
machine-assisted (tool, model, date, all passed in as data). Source branding is removed so the
output never passes itself off as a release of the group that made the source.
"""

import posixpath
from dataclasses import dataclass
from html import escape

from lxml import etree

from book_translator.epub import Epub
from book_translator.structure import matter_kind

_OPF = "http://www.idpf.org/2007/opf"
_PAGE = "credits.xhtml"

__all__ = ["Credits", "add_credits_page"]


@dataclass(frozen=True)
class Credits:
    original_title: str
    source_edition: str
    tool: str
    model: str
    date: str


def add_credits_page(epub: Epub, credits: Credits) -> None:
    """Put the credits page in the book: replace the existing one, else add it before the body."""
    existing = next((m for m in epub.spine() if matter_kind(m, epub.read(m)) == "credits"), None)
    if existing is not None:
        epub.store(existing, etree.ElementTree(etree.fromstring(_page(credits).encode("utf-8"))))
        return
    base = posixpath.dirname(epub.opf_path)
    epub.add(posixpath.join(base, _PAGE), _page(credits).encode("utf-8"))
    tree = etree.ElementTree(etree.fromstring(epub.read(epub.opf_path)))
    root = tree.getroot()
    manifest = root.find(f"{{{_OPF}}}manifest")
    spine = root.find(f"{{{_OPF}}}spine")
    assert manifest is not None and spine is not None
    etree.SubElement(
        manifest,
        f"{{{_OPF}}}item",
        {"id": "credits", "href": _PAGE, "media-type": "application/xhtml+xml"},
    )
    hrefs = {str(i.get("id")): str(i.get("href")) for i in manifest}
    ref = etree.Element(f"{{{_OPF}}}itemref", idref="credits")
    for itemref in spine:
        name = posixpath.join(base, hrefs[str(itemref.get("idref"))])
        if matter_kind(name, epub.read(name)) is None:
            itemref.addprevious(ref)
            break
    else:
        spine.append(ref)
    epub.store(epub.opf_path, tree)


def _page(c: Credits) -> str:
    lines = [
        f"Original title: <cite>{escape(c.original_title)}</cite>",
        f"Source edition: {escape(c.source_edition)}",
        "This translation is machine-assisted.",
        f"Tool: {escape(c.tool)}",
        f"Model: {escape(c.model)}",
        f"Date: {escape(c.date)}",
    ]
    body = "".join(f"<p>{line}</p>\n" for line in lines)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<head><title>Credits</title></head>\n"
        f'<body>\n<div class="credits">\n{body}</div>\n</body>\n</html>\n'
    )
