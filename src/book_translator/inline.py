"""Inline markup codes: encode a block's inline tags for the LLM and re-inject them after.

The LLM sees a block's text with XLIFF-style codes: `<pc id="n">...</pc>` for a paired inline
element (italics, links, spans) and `<ph id="n"/>` for a standalone one (`<br/>`, note
reference anchors, empty elements, comments). The block's original markup (tag names,
attributes, namespaces) stays on our side in a map keyed by code id, so the model can never
alter a class, id or href. After a response the codes are validated and the text is rebuilt
into the DOM from the map.
"""

import copy
import re
from dataclasses import dataclass
from typing import Literal

from lxml import etree

_EPUB_NS = "http://www.idpf.org/2007/ops"
_TOKEN = re.compile(r"<pc id=\"(\d+)\">|</pc>|<ph id=\"(\d+)\"/>|([^<]+)|(<)")
_OPEN = re.compile(r"<pc id=\"(\d+)\">")


class InlineCodeError(ValueError):
    """A translated block's inline codes are not acceptable. The message says why."""


@dataclass(frozen=True)
class _Code:
    kind: Literal["pc", "ph"]
    original: etree._Element  # a pc keeps the element without children; a ph the whole element


@dataclass(frozen=True)
class EncodedBlock:
    """A block's text with inline codes, plus the original-data map that backs them."""

    text: str
    _codes: dict[int, _Code]


def encode(element: etree._Element) -> EncodedBlock:
    codes: dict[int, _Code] = {}
    return EncodedBlock(_encode_children(element, codes), codes)


def decode(element: etree._Element, encoded: EncodedBlock, text: str) -> None:
    """Replace the children of `element` with `text`, rebuilt from its codes."""
    for child in list(element):
        element.remove(child)
    element.text = None
    stack = [element]
    for match in _TOKEN.finditer(text):
        opened, standalone, plain, _ = match.groups()
        if plain is not None:
            _add_text(stack[-1], _unescape(plain))
        elif opened is not None:
            shell = copy.deepcopy(encoded._codes[int(opened)].original)
            stack[-1].append(shell)
            stack.append(shell)
        elif standalone is not None:
            stack[-1].append(copy.deepcopy(encoded._codes[int(standalone)].original))
        else:
            stack.pop()


def _encode_children(parent: etree._Element, codes: dict[int, _Code]) -> str:
    parts = [_escape(parent.text or "")]
    for child in parent:
        number = len(codes) + 1
        if _is_standalone(child):
            codes[number] = _Code("ph", _detached(child, deep=True))
            parts.append(f'<ph id="{number}"/>')
        else:
            codes[number] = _Code("pc", _detached(child, deep=False))
            inner = _encode_children(child, codes)
            parts.append(f'<pc id="{number}">{inner}</pc>')
        parts.append(_escape(child.tail or ""))
    return "".join(parts)


def _is_standalone(el: etree._Element) -> bool:
    if not isinstance(el.tag, str):  # a comment or processing instruction
        return True
    if not len(el) and not el.text:
        return True
    types = (el.get(f"{{{_EPUB_NS}}}type", "") + " " + el.get("role", "")).split()
    return "noteref" in types or "doc-noteref" in types


def _detached(el: etree._Element, *, deep: bool) -> etree._Element:
    clone = copy.deepcopy(el)
    clone.tail = None
    if not deep:
        clone.text = None
        for child in list(clone):
            clone.remove(child)
    return clone


def _add_text(parent: etree._Element, text: str) -> None:
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _unescape(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
