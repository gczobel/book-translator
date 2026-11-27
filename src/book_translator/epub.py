"""EPUB codec: open an EPUB and write it back out (ADR 0002, rebuild in place).

zipfile + lxml, no EbookLib. Members the codec has not been asked to change are written
back as the exact bytes read, so an identity round trip reproduces the source member for
member. Zip metadata (member order, compression, timestamps, attributes) is preserved too.
"""

import posixpath
import zipfile
from collections.abc import Sequence
from copy import copy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from lxml import etree

from book_translator.inline import EncodedBlock, InlineCodeError, decode, encode
from book_translator.structure import Book, build_book, find_element

_CONTAINER = "META-INF/container.xml"
_XML_SUFFIXES = (".xhtml", ".html", ".htm", ".opf", ".ncx", ".xml")


__all__ = ["Epub", "EpubError", "InlineCodeError", "TargetBlock", "open_epub"]


class EpubError(Exception):
    """The file is not a readable EPUB."""


@dataclass(frozen=True)
class TargetBlock:
    """A block of the rebuilt book, with the source block it was made from."""

    id: str
    source: str


@dataclass
class _Member:
    info: zipfile.ZipInfo
    data: bytes


class Epub:
    def __init__(self, members: list[_Member]) -> None:
        self._members = members
        self._by_name = {m.info.filename: m for m in members}
        self._opf_path = self._find_opf()
        self._extras: dict[str, dict[int, int]] = {}  # member -> source block index -> clones added

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

    @property
    def opf_path(self) -> str:
        """Member name of the package document."""
        return self._opf_path

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

    def encode_block(self, block_id: str) -> EncodedBlock:
        """The block's text with its inline markup as codes the LLM can carry through."""
        return encode(self._block_element(block_id)[1])

    def replace_block(self, block_id: str, encoded: EncodedBlock, text: str) -> None:
        """Rebuild the block's content from `text`, re-injecting its inline markup.

        Raises InlineCodeError, leaving the document unchanged, if the codes in `text` are not
        a legal rendering of the block's codes.
        """
        encoded.validate(text)
        member, element = self._block_element(block_id)
        decode(element, encoded, text)
        self.store(member, element.getroottree())

    def rebuild_block(self, block_id: str, encoded: EncodedBlock, texts: Sequence[str]) -> None:
        """Replace a source block with one target block per entry of `texts`, in place.

        Each target block is a clone of the source element (same tag, class and attributes;
        the `id` stays on the first). `block_id` is always the id the block had in the source
        book, however many blocks earlier rebuilds added. Raises InlineCodeError, leaving the
        document unchanged, if the codes in `texts` are not a legal rendering of the block's.
        """
        encoded.validate_pieces(texts)
        member, element = self._block_element(block_id)
        parent = element.getparent()
        assert parent is not None
        source_index = int(block_id.rpartition("#")[2])
        for _ in range(self._extras.get(member, {}).get(source_index, 0)):
            sibling = element.getnext()
            assert sibling is not None
            parent.remove(sibling)
        pieces = [element]
        for _ in texts[1:]:
            clone = copy(element)
            clone.attrib.pop("id", "")
            clone.tail = element.tail
            pieces[-1].addnext(clone)
            pieces.append(clone)
        for piece, text in zip(pieces, texts, strict=True):
            decode(piece, encoded, text)
        self._extras.setdefault(member, {})[source_index] = len(texts) - 1
        self.store(member, element.getroottree())

    def target_blocks(self) -> list[TargetBlock]:
        """Every block made by `rebuild_block`, in document order, with its source block id."""
        out: list[TargetBlock] = []
        for member, splits in self._extras.items():
            shift = 0
            for index, extra in sorted(splits.items()):
                out += [
                    TargetBlock(f"{member}#{index + shift + k}", f"{member}#{index}")
                    for k in range(extra + 1)
                ]
                shift += extra
        return out

    def store(self, member: str, tree: etree._ElementTree) -> None:
        """Keep the member's original bytes when the edit changed nothing (an identity rebuild)."""
        member_data = self._by_name[member]
        if etree.tostring(tree, method="c14n") != etree.tostring(
            etree.fromstring(member_data.data), method="c14n"
        ):
            member_data.data = etree.tostring(tree, xml_declaration=True, encoding="utf-8")

    def locate_block(self, block_id: str) -> tuple[str, etree._Element]:
        """The member and element behind a block id, for editing; save it with `store`."""
        return self._block_element(block_id)

    def _block_element(self, block_id: str) -> tuple[str, etree._Element]:
        member, _, number = block_id.rpartition("#")
        shift = sum(n for i, n in self._extras.get(member, {}).items() if i < int(number))
        element = find_element(
            etree.fromstring(self.read(member)), f"{member}#{int(number) + shift}"
        )
        if element is None:
            raise EpubError(f"no such block: {block_id}")
        return member, element

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
