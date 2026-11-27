"""Book model and structure detection (chapters, scenes, scene breaks, blocks).

Detection works from signals in the markup (an `<hr>` of any class, scene-break paragraph
classes, asterism paragraphs, empty spacer paragraphs) and never from EPUB 3 semantics or
template versions. Chapters come from the NCX table of contents, falling back to headings,
and are not tied to the files that hold them.
"""

import posixpath
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote

from lxml import etree

BlockKind = Literal["paragraph", "heading", "verse", "list_item"]
MatterKind = Literal[
    "cover", "synopsis", "title_page", "credits", "dedication", "about_author", "notes"
]

_HEADINGS = {f"h{n}" for n in range(1, 7)}
_CONTAINERS = {"div", "section", "blockquote", "article", "body", "aside", "main"}
_VERSE_CLASS = re.compile(r"verse|poem|stanza", re.I)
_BREAK_CLASS = re.compile(r"scene|break|ornament|asterism|dinkus|spacer|separator", re.I)
_MATTER_NAMES: list[tuple[MatterKind, re.Pattern[str]]] = [
    ("cover", re.compile(r"cover")),
    ("synopsis", re.compile(r"synopsis|blurb|summary|description")),
    ("title_page", re.compile(r"title(page)?")),
    ("credits", re.compile(r"credits?|copyright|colophon|imprint|legal")),
    ("dedication", re.compile(r"dedication")),
    ("about_author", re.compile(r"(about(the)?)?authors?|aboutauthor")),
    ("notes", re.compile(r"(end|foot)?notes")),
]
_EPUB_TYPES: dict[str, MatterKind] = {
    "cover": "cover",
    "titlepage": "title_page",
    "halftitlepage": "title_page",
    "dedication": "dedication",
    "abstract": "synopsis",
    "colophon": "credits",
    "copyright-page": "credits",
    "endnotes": "notes",
    "footnotes": "notes",
    "rearnotes": "notes",
}
_EPUB_NS = "http://www.idpf.org/2007/ops"
_ASTERISM_CHARS = set("*⁂✻✽❖◆◇•·~#-—–_")


@dataclass(frozen=True)
class Block:
    """One paragraph-level unit of text."""

    id: str  # "<member>#<n>", n counting the document's blocks and scene breaks from 0
    kind: BlockKind
    text: str
    position: int  # 0-based order among all blocks of the book


@dataclass(frozen=True)
class SceneBreak:
    """A marker between two scenes. It is preserved as it is, never translated."""

    id: str
    translatable: bool = False


@dataclass(frozen=True)
class Scene:
    blocks: list[Block]


@dataclass(frozen=True)
class Chapter:
    title: str | None
    scenes: list[Scene]
    breaks: list[SceneBreak]  # breaks[i] sits between scenes[i] and scenes[i + 1]


@dataclass(frozen=True)
class Note:
    """A note and the block that refers to it."""

    block: str  # id of the note's first block
    reference: str  # id of the block holding the reference


@dataclass(frozen=True)
class Part:
    """A front- or back-matter file. Later stages translate, rewrite or keep it by its kind."""

    kind: MatterKind
    title: str | None  # None for an untitled section
    blocks: list[Block]


@dataclass(frozen=True)
class Book:
    chapters: list[Chapter]
    notes: list[Note]
    front: list[Part]
    back: list[Part]


@dataclass
class _Item:
    member: str
    id: str
    anchors: set[str]
    kind: BlockKind | None  # None: a scene break
    text: str = ""
    level: int = 0
    links: tuple[tuple[str, str], ...] = ()  # (member, fragment) of each link in the block


def build_book(
    spine: list[str],
    read: Callable[[str], bytes],
    nav: dict[tuple[str, str | None], str],
) -> Book:
    data = {member: read(member) for member in spine}
    kinds = {member: _semantic_kind(data[member]) or _matter_kind(member) for member in spine}
    every = [i for member in spine for i in _items(member, data[member])]
    position: dict[str, int] = {}
    for item in every:
        if item.kind is not None:
            position[item.id] = len(position)
    items = [i for i in every if kinds[i.member] is None]
    front: list[Part] = []
    back: list[Part] = []
    body_seen = False
    for member in spine:
        kind = kinds[member]
        if kind is None:
            body_seen = True
            continue
        part_items = [i for i in every if i.member == member]
        heading = next((i.text for i in part_items if i.kind == "heading"), None)
        blocks = [
            Block(i.id, i.kind, i.text, position[i.id]) for i in part_items if i.kind is not None
        ]
        (back if body_seen else front).append(Part(kind, heading, blocks))
    starts = _chapter_starts(items, nav)
    groups: list[tuple[str | None, list[_Item]]] = []
    for n, item in enumerate(items):
        if n == 0 or n in starts:
            groups.append((starts.get(n), []))
        groups[-1][1].append(item)
    chapters: list[Chapter] = []
    for title, group in groups:
        scenes: list[Scene] = []
        breaks: list[SceneBreak] = []
        current: list[Block] = []
        pending: SceneBreak | None = None
        for item in group:
            if item.kind is None:
                pending = pending or SceneBreak(item.id)
                continue
            if pending and current:
                scenes.append(Scene(current))
                breaks.append(pending)
                current = []
            pending = None
            current.append(Block(item.id, item.kind, item.text, position[item.id]))
        if current:
            scenes.append(Scene(current))
        chapters.append(Chapter(title, scenes, breaks))
    return Book(chapters, _notes(every), front, back)


def matter_kind(member: str, data: bytes) -> MatterKind | None:
    """Kind of front or back matter a spine document is, or None for a body document."""
    return _semantic_kind(data) or _matter_kind(member)


def _semantic_kind(data: bytes) -> MatterKind | None:
    """Kind of matter declared by `epub:type` on the body or its top-level sections."""
    body = next((e for e in etree.fromstring(data).iter() if _name(e) == "body"), None)
    if body is None:
        return None
    for el in [body, *body]:
        for token in str(el.get(f"{{{_EPUB_NS}}}type", "")).split():
            if token in _EPUB_TYPES:
                return _EPUB_TYPES[token]
    return None


def _matter_kind(member: str) -> MatterKind | None:
    """Kind of front or back matter named by the file name, or None for a body file."""
    stem = re.sub(r"[\W_\d]+", "", member.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower())
    return next((kind for kind, name in _MATTER_NAMES if name.fullmatch(stem)), None)


def _notes(items: list[_Item]) -> list[Note]:
    """Notes in reading order of their references: a reference links to the note's anchor.

    A note's back-link to its reference is not a reference itself, so of two blocks that
    link to each other the earlier one is the reference.
    """
    first: dict[tuple[str, str], int] = {}
    for n, item in enumerate(items):
        for anchor in item.anchors:
            first.setdefault((item.member, anchor), n)
    notes: list[Note] = []
    for n, item in enumerate(items):
        if item.kind is None:
            continue
        for link in item.links:
            t = first.get(link)
            if t is None or t == n:
                continue
            target = items[t]
            if t < n and any(first.get(back) == n for back in target.links):
                continue
            notes.append(Note(target.id, item.id))
    return notes


def _chapter_starts(
    items: list[_Item], nav: dict[tuple[str, str | None], str]
) -> dict[int, str | None]:
    """Item index -> chapter title, for each item that opens a chapter."""
    starts: dict[int, str | None] = {}
    seen: set[str] = set()
    for n, item in enumerate(items):
        label = None if item.member in seen else nav.get((item.member, None))
        seen.add(item.member)
        for anchor in sorted(item.anchors):
            label = nav.get((item.member, anchor), label)
        if label is not None:
            starts[n] = label
    if starts:
        return starts
    levels = [i.level for i in items if i.kind == "heading"]
    top = min(levels, default=0)
    return {n: i.text for n, i in enumerate(items) if i.kind == "heading" and i.level == top}


def _items(member: str, data: bytes) -> Iterator[_Item]:
    root = etree.fromstring(data)
    body = next((e for e in root.iter() if _name(e) == "body"), None)
    if body is None:
        return
    count = 0
    for el, ids in _walk(body, set()):
        name = _name(el)
        anchors = ids | {str(i) for e in el.iter() if (i := e.get("id"))}
        item_id = f"{member}#{count}"
        links = _links(member, el)
        if _is_break(el, name):
            yield _Item(member, item_id, anchors, None)
        elif name in _HEADINGS:
            yield _Item(member, item_id, anchors, "heading", _text(el), int(name[1]), links)
        elif name == "li":
            yield _Item(member, item_id, anchors, "list_item", _text(el), 0, links)
        elif _is_verse(el):
            yield _Item(member, item_id, anchors, "verse", _verse_text(el), 0, links)
        else:
            yield _Item(member, item_id, anchors, "paragraph", _text(el), 0, links)
        count += 1


def find_element(root: etree._Element, block_id: str) -> etree._Element | None:
    """The element behind a block id ("<member>#<n>"), or None if the document has no such n."""
    body = next((e for e in root.iter() if _name(e) == "body"), None)
    n = int(block_id.rpartition("#")[2])
    found = list(_walk(body, set())) if body is not None else []
    return found[n][0] if n < len(found) else None


def _links(member: str, el: etree._Element) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for a in el.iter():
        href = a.get("href") if _name(a) == "a" else None
        if href and "#" in href:
            path, _, fragment = unquote(str(href)).partition("#")
            target = posixpath.normpath(posixpath.join(posixpath.dirname(member), path or member))
            out.append((target if path else member, fragment))
    return tuple(out)


def _walk(parent: etree._Element, ids: set[str]) -> Iterator[tuple[etree._Element, set[str]]]:
    for el in parent:
        name = _name(el)
        if name is None:
            continue
        own = ids | ({str(i)} if (i := el.get("id")) else set())
        if name in {"p", "hr", "li", *_HEADINGS} or _is_verse(el):
            yield el, own
        elif name in {"ul", "ol", *_CONTAINERS}:
            yield from _walk(el, own)


def _name(el: etree._Element) -> str | None:
    tag = el.tag
    return etree.QName(tag).localname if isinstance(tag, str) else None


def _is_verse(el: etree._Element) -> bool:
    return _name(el) in {"p", "div", "blockquote"} and bool(
        _VERSE_CLASS.search(el.get("class", ""))
    )


def _is_break(el: etree._Element, name: str | None) -> bool:
    if name == "hr":
        return True
    if name != "p" or _is_verse(el):
        return False
    text = _plain(el).replace(" ", " ").strip()
    if any(c.isalnum() for c in text):
        return False
    if text:
        return set(text.replace(" ", "")) <= _ASTERISM_CHARS or bool(
            _BREAK_CLASS.search(el.get("class", ""))
        )
    has_picture = any(_name(e) == "img" for e in el.iter())
    return not has_picture or bool(_BREAK_CLASS.search(el.get("class", "")))


def _plain(el: etree._Element) -> str:
    return str(etree.tostring(el, method="text", encoding="unicode", with_tail=False))


def _text(el: etree._Element) -> str:
    return re.sub(r"\s+", " ", _raw(el)).strip()


def _verse_text(el: etree._Element) -> str:
    lines = [re.sub(r"[ \t\r\f]+", " ", ln).strip() for ln in _raw(el).split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _raw(el: etree._Element) -> str:
    """Text of `el` with `<br/>` as a newline and block children on their own lines."""
    parts: list[str] = [el.text or ""]
    for child in el:
        name = _name(child)
        if name == "br":
            parts.append("\n")
        elif name in {"p", "div"}:
            parts.append("\n" + _raw(child) + "\n")
        elif name is not None:
            parts.append(_raw(child))
        parts.append(child.tail or "")
    return "".join(parts)
