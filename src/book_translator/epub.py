"""EPUB codec: open an EPUB and write it back out (ADR 0002, rebuild in place).

zipfile + lxml, no EbookLib. Members the codec has not been asked to change are written
back as the exact bytes read, so an identity round trip reproduces the source member for
member. Zip metadata (member order, compression, timestamps, attributes) is preserved too.
"""

import posixpath
import zipfile
from copy import copy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from lxml import etree

from book_translator.structure import Book, build_book

_CONTAINER = "META-INF/container.xml"
_XML_SUFFIXES = (".xhtml", ".html", ".htm", ".opf", ".ncx", ".xml")


class EpubError(Exception):
    """The file is not a readable EPUB."""


@dataclass
class _Member:
    info: zipfile.ZipInfo
    data: bytes


class Epub:
    def __init__(self, members: list[_Member]) -> None:
        self._members = members
        self._by_name = {m.info.filename: m for m in members}
        self._opf_path = self._find_opf()

    @property
    def names(self) -> list[str]:
        """Archive member names in archive order."""
        return [m.info.filename for m in self._members]

    def read(self, name: str) -> bytes:
        """Raw bytes of one member."""
        try:
            return self._by_name[name].data
        except KeyError:
            raise EpubError(f"no such member: {name}") from None

    def spine(self) -> list[str]:
        """Member names of the content documents, in reading order."""
        opf = etree.fromstring(self.read(self._opf_path))
        ns = {"o": "http://www.idpf.org/2007/opf"}
        hrefs: dict[str, str] = {}
        for item in opf.iterfind(".//o:manifest/o:item", ns):
            item_id, href = item.get("id"), item.get("href")
            if item_id and href:
                hrefs[str(item_id)] = str(href)
        base = PurePosixPath(self._opf_path).parent
        return [
            str(base / hrefs[str(idref)])
            for ref in opf.iterfind(".//o:spine/o:itemref", ns)
            if (idref := ref.get("idref")) and str(idref) in hrefs
        ]

    def book(self) -> Book:
        """The book's structure: chapters, scenes, scene breaks and blocks."""
        return build_book(self.spine(), self.read, self._nav_labels())

    def _nav_labels(self) -> dict[tuple[str, str | None], str]:
        """NCX and EPUB 3 nav entries as {(member, fragment or None): label}; the NCX wins."""
        labels = self._ncx_labels()
        for key, label in self._nav_document_labels().items():
            labels.setdefault(key, label)
        return labels

    def _nav_document_labels(self) -> dict[tuple[str, str | None], str]:
        """Entries of the EPUB 3 `nav` document's table of contents."""
        opf = etree.fromstring(self.read(self._opf_path))
        ns = {"o": "http://www.idpf.org/2007/opf", "h": "http://www.w3.org/1999/xhtml"}
        base = PurePosixPath(self._opf_path).parent
        nav_path = next(
            (
                str(base / str(i.get("href")))
                for i in opf.iterfind(".//o:manifest/o:item", ns)
                if "nav" in str(i.get("properties", "")).split() and i.get("href")
            ),
            None,
        )
        if nav_path is None or nav_path not in self._by_name:
            return {}
        ops = "{http://www.idpf.org/2007/ops}type"
        labels: dict[tuple[str, str | None], str] = {}
        for nav in etree.fromstring(self.read(nav_path)).iterfind(".//h:nav", ns):
            if "toc" not in str(nav.get(ops, "")).split():
                continue
            for a in nav.iterfind(".//h:a", ns):
                if not a.get("href"):
                    continue
                src, _, fragment = unquote(str(a.get("href"))).partition("#")
                member = posixpath.normpath(posixpath.join(posixpath.dirname(nav_path), src))
                label = " ".join(
                    etree.tostring(a, method="text", encoding="unicode", with_tail=False).split()
                )
                labels.setdefault((member, fragment or None), label)
        return labels

    def _ncx_labels(self) -> dict[tuple[str, str | None], str]:
        """NCX entries as {(member, fragment or None): label}; empty if there is no NCX."""
        opf = etree.fromstring(self.read(self._opf_path))
        ns = {"o": "http://www.idpf.org/2007/opf"}
        spine = opf.find(".//o:spine", ns)
        toc_id = spine.get("toc") if spine is not None else None
        base = PurePosixPath(self._opf_path).parent
        ncx_path = next(
            (
                str(base / str(i.get("href")))
                for i in opf.iterfind(".//o:manifest/o:item", ns)
                if i.get("id") == toc_id and i.get("href")
            ),
            None,
        )
        if ncx_path is None or ncx_path not in self._by_name:
            return {}
        n = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
        labels: dict[tuple[str, str | None], str] = {}
        for point in etree.fromstring(self.read(ncx_path)).iterfind(".//n:navPoint", n):
            text = point.find("n:navLabel/n:text", n)
            content = point.find("n:content", n)
            if text is None or content is None or not content.get("src"):
                continue
            src, _, fragment = unquote(str(content.get("src"))).partition("#")
            member = posixpath.normpath(posixpath.join(posixpath.dirname(ncx_path), src))
            labels.setdefault(
                (member, fragment or None),
                " ".join(
                    etree.tostring(text, method="text", encoding="unicode", with_tail=False).split()
                ),
            )
        return labels

    def write(self, path: Path) -> None:
        """Write the archive to `path`."""
        with zipfile.ZipFile(path, "w") as z:
            for m in self._members:
                z.writestr(copy(m.info), m.data, compress_type=m.info.compress_type)

    def _find_opf(self) -> str:
        if _CONTAINER not in self._by_name:
            raise EpubError(f"missing {_CONTAINER}")
        root = etree.fromstring(self._by_name[_CONTAINER].data)
        ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        rootfile = root.find(".//c:rootfile", ns)
        if rootfile is None or rootfile.get("full-path") not in self._by_name:
            raise EpubError("container.xml does not point at a package document")
        return str(rootfile.get("full-path"))


def open_epub(path: Path) -> Epub:
    """Read an EPUB 2 (or 3) from `path`, checking that its XML members are well formed."""
    try:
        with zipfile.ZipFile(path) as z:
            members = [_Member(info, z.read(info)) for info in z.infolist()]
    except zipfile.BadZipFile as e:
        raise EpubError(f"not a zip archive: {path}") from e
    for m in members:
        if m.info.filename.lower().endswith(_XML_SUFFIXES):
            try:
                etree.fromstring(m.data)
            except etree.XMLSyntaxError as e:
                raise EpubError(f"malformed XML in {m.info.filename}: {e}") from e
    return Epub(members)
