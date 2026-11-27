"""The credits page and source branding removal (ADR 0002).

The credits page names the original title, the source edition and that the translation is
machine-assisted (tool, model, date, all passed in as data). Source branding is removed so the
output never passes itself off as a release of the group that made the source.
"""

import posixpath
import re
from dataclasses import dataclass
from html import escape
from urllib.parse import unquote

from lxml import etree

from book_translator.epub import Epub
from book_translator.structure import matter_kind

_OPF = "http://www.idpf.org/2007/opf"
_DC = "http://purl.org/dc/elements/1.1/"
_NCX = "http://www.daisy.org/z3986/2005/ncx/"
_XHTML = "http://www.w3.org/1999/xhtml"
_XLINK = "{http://www.w3.org/1999/xlink}href"
_PAGE = "credits.xhtml"
_DOCUMENTS = (".xhtml", ".html", ".htm")

__all__ = ["EPUBLIBRE", "Branding", "Credits", "add_credits_page", "remove_branding"]


@dataclass(frozen=True)
class Credits:
    original_title: str
    source_edition: str
    tool: str
    model: str
    date: str


@dataclass(frozen=True)
class Branding:
    """What marks a source as a release of some group: image files, publisher, identifier."""

    images: re.Pattern[str]  # matched against the image's file name
    publishers: frozenset[str] = frozenset()
    identifier_schemes: frozenset[str] = frozenset()


EPUBLIBRE = Branding(
    images=re.compile(r"(epl_logo|ex_?libris)\.\w+", re.IGNORECASE),
    publishers=frozenset({"ePubLibre"}),
    identifier_schemes=frozenset({"EPL"}),
)


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
        f'<html xmlns="{_XHTML}">\n'
        "<head><title>Credits</title></head>\n"
        f'<body>\n<div class="credits">\n{body}</div>\n</body>\n</html>\n'
    )


def remove_branding(epub: Epub, branding: Branding = EPUBLIBRE) -> None:
    """Remove the source's branding images, the pages they leave empty, and every reference."""
    base = posixpath.dirname(epub.opf_path)
    package = etree.ElementTree(etree.fromstring(epub.read(epub.opf_path)))
    root = package.getroot()
    manifest = root.find(f"{{{_OPF}}}manifest")
    assert manifest is not None
    images = {
        posixpath.join(base, str(i.get("href")))
        for i in manifest
        if branding.images.fullmatch(posixpath.basename(str(i.get("href"))))
    }
    spine = set(epub.spine())
    emptied: set[str] = set()
    for member in epub.names:
        if member.lower().endswith(_DOCUMENTS):
            tree = etree.ElementTree(etree.fromstring(epub.read(member)))
            if _strip_images(tree.getroot(), member, images):
                epub.store(member, tree)
                if member in spine and not _has_content(tree.getroot()):
                    emptied.add(member)
    gone = images | emptied
    for member in epub.names:
        if member.lower().endswith(_DOCUMENTS) and member not in emptied:
            _unlink(epub, member, gone)
        elif member.lower().endswith(".ncx"):
            _drop_nav_points(epub, member, gone)
    ids = set()
    for item in list(manifest):
        if posixpath.join(base, str(item.get("href"))) in gone:
            ids.add(item.get("id"))
            manifest.remove(item)
    for ref in list(root.iterfind(f"{{{_OPF}}}spine/{{{_OPF}}}itemref")):
        if ref.get("idref") in ids:
            _detach(ref)
    for ref in list(root.iterfind(f"{{{_OPF}}}guide/{{{_OPF}}}reference")):
        if _resolve(epub.opf_path, str(ref.get("href")).split("#")[0]) in gone:
            _detach(ref)
    for element in list(root.iter(f"{{{_DC}}}publisher", f"{{{_DC}}}identifier")):
        scheme = element.get(f"{{{_OPF}}}scheme")
        if (element.text or "") in branding.publishers or (
            scheme is not None and scheme in branding.identifier_schemes
        ):
            _detach(element)
    epub.store(epub.opf_path, package)
    for member in sorted(gone):
        epub.remove(member)


def _detach(element: etree._Element) -> None:
    parent = element.getparent()
    assert parent is not None
    parent.remove(element)


def _resolve(member: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(member), unquote(href)))


def _local(element: etree._Element) -> str:
    return etree.QName(element).localname if isinstance(element.tag, str) else ""


def _strip_images(root: etree._Element, member: str, images: set[str]) -> bool:
    """Remove branding images, and the wrappers they leave empty. True if any went."""
    changed = False
    for element in list(root.iter()):
        src = element.get("src") or element.get(_XLINK)
        if _local(element) not in {"img", "image"} or not src:
            continue
        if _resolve(member, src.split("#")[0]) not in images:
            continue
        node = element
        parent = node.getparent()
        while parent is not None:
            parent.remove(node)
            changed = True
            if len(parent) or (parent.text or "").strip() or _local(parent) in {"body", "html"}:
                break
            node, parent = parent, parent.getparent()
    return changed


def _has_content(root: etree._Element) -> bool:
    body = next((e for e in root.iter() if _local(e) == "body"), None)
    if body is None:
        return False
    return bool(
        etree.tostring(body, method="text", encoding="unicode", with_tail=False).strip()
    ) or any(_local(e) in {"img", "image", "svg", "object"} for e in body.iter())


def _unlink(epub: Epub, member: str, gone: set[str]) -> None:
    """Turn links to removed members into plain spans, keeping their text."""
    tree = etree.ElementTree(etree.fromstring(epub.read(member)))
    changed = False
    for a in tree.getroot().iter():
        href = a.get("href")
        if _local(a) == "a" and href and "://" not in href:
            target = href.split("#")[0]
            if target and _resolve(member, target) in gone:
                del a.attrib["href"]
                a.tag = f"{{{_XHTML}}}span"
                changed = True
    if changed:
        epub.store(member, tree)


def _drop_nav_points(epub: Epub, member: str, gone: set[str]) -> None:
    tree = etree.ElementTree(etree.fromstring(epub.read(member)))
    for point in list(tree.getroot().iter(f"{{{_NCX}}}navPoint")):
        content = point.find(f"{{{_NCX}}}content")
        src = content.get("src") if content is not None else None
        if src and _resolve(member, src.split("#")[0]) in gone:
            _detach(point)
    epub.store(member, tree)
