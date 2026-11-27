"""EPUB codec: open an EPUB and write it back out (ADR 0002, rebuild in place).

zipfile + lxml, no EbookLib. Members the codec has not been asked to change are written
back as the exact bytes read, so an identity round trip reproduces the source member for
member. Zip metadata (member order, compression, timestamps, attributes) is preserved too.
"""

import zipfile
from copy import copy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from lxml import etree

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
