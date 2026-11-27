"""Book model and structure detection (chapters, scenes, scene breaks, blocks).

Detection works from signals in the markup (an `<hr>` of any class, scene-break paragraph
classes, asterism paragraphs, empty spacer paragraphs) and never from EPUB 3 semantics or
template versions. Chapters come from the NCX table of contents, falling back to headings,
and are not tied to the files that hold them.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

from lxml import etree

BlockKind = Literal["paragraph", "heading", "verse", "list_item"]

_HEADINGS = {f"h{n}" for n in range(1, 7)}
_CONTAINERS = {"div", "section", "blockquote", "article", "body", "aside", "main"}
_VERSE_CLASS = re.compile(r"verse|poem|stanza", re.I)
_BREAK_CLASS = re.compile(r"scene|break|ornament|asterism|dinkus|spacer|separator", re.I)
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
class Book:
    chapters: list[Chapter]


@dataclass
class _Item:
    member: str
    id: str
    anchors: set[str]
    kind: BlockKind | None  # None: a scene break
    text: str = ""
    level: int = 0


def build_book(
    spine: list[str],
    read: Callable[[str], bytes],
    nav: dict[tuple[str, str | None], str],
) -> Book:
    items = [i for member in spine for i in _items(member, read(member))]
    starts = _chapter_starts(items, nav)
    groups: list[tuple[str | None, list[_Item]]] = []
    for n, item in enumerate(items):
        if n == 0 or n in starts:
            groups.append((starts.get(n), []))
        groups[-1][1].append(item)
    position = 0
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
            current.append(Block(item.id, item.kind, item.text, position))
            position += 1
        if current:
            scenes.append(Scene(current))
        chapters.append(Chapter(title, scenes, breaks))
    return Book(chapters)


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
        if _is_break(el, name):
            yield _Item(member, item_id, anchors, None)
        elif name in _HEADINGS:
            yield _Item(member, item_id, anchors, "heading", _text(el), int(name[1]))
        elif name == "li":
            yield _Item(member, item_id, anchors, "list_item", _text(el))
        elif _is_verse(el):
            yield _Item(member, item_id, anchors, "verse", _verse_text(el))
        else:
            yield _Item(member, item_id, anchors, "paragraph", _text(el))
        count += 1


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
