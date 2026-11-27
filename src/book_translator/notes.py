"""Adding notes to a book and renumbering them in reading order (part of the build step)."""

import posixpath
import re
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass

from lxml import etree

from book_translator.epub import Epub, EpubError

_NUMBER = re.compile(r"\d+")

__all__ = ["AddedNote", "add_notes"]


@dataclass(frozen=True)
class AddedNote:
    """A note to add, referenced from the end of a source block."""

    reference_block: str  # source block id, as in `Book`
    text: str  # the note's text, without its number


def add_notes(epub: Epub, added: Sequence[AddedNote]) -> None:
    """Add each note after its reference block, then renumber every note in reading order.

    A new note is a clone of the book's last note and reference (same markup, classes and
    link style) with fresh ids, placed among the notes in the order of the references. Block
    ids of the notes document shift when a note lands before another, so run this once the
    book's own blocks have been rebuilt.
    """
    template = next(iter(reversed(epub.book().notes)), None)
    if template is None:
        raise EpubError("cannot add a note to a book without notes")
    for note in added:
        _add_one(epub, template.reference, template.block, note)
    _renumber(epub)


def _container(block: etree._Element) -> etree._Element:
    """The block itself if it has an id, else its nearest ancestor with one."""
    node = block
    while node.get("id") is None and (parent := node.getparent()) is not None:
        node = parent
    return node


def _all_ids(epub: Epub) -> set[str]:
    return {
        str(i)
        for member in epub.spine()
        for e in etree.fromstring(epub.read(member)).iter()
        if (i := e.get("id"))
    }


def _fresh(old_id: str, taken: set[str]) -> str:
    stem = _NUMBER.sub("", old_id)
    count = 1
    while f"{stem}{count}" in taken:
        count += 1
    return f"{stem}{count}"


def _reference_anchor(reference: etree._Element, note_id: str | None = None) -> etree._Element:
    anchors = [
        a
        for a in reference.iter()
        if isinstance(a.tag, str)
        and etree.QName(a).localname == "a"
        and a.get("href")
        and (note_id is None or str(a.get("href")).partition("#")[2] == note_id)
    ]
    return anchors[-1]


def _add_one(epub: Epub, template_ref: str, template_note: str, note: AddedNote) -> None:
    taken = _all_ids(epub)
    _, ref_block = epub.locate_block(template_ref)
    ref_anchor = _reference_anchor(ref_block)
    note_member, note_block = epub.locate_block(template_note)
    container = _container(note_block)
    note_id = _fresh(str(container.get("id")), taken)
    ref_id = _fresh(str(ref_anchor.get("id") or "rf"), taken | {note_id})

    ref_member, target = epub.locate_block(note.reference_block)
    anchor = deepcopy(ref_anchor)
    anchor.tail = None
    anchor.set("id", ref_id)
    href_path = str(anchor.get("href")).partition("#")[0]
    anchor.set("href", f"{href_path}#{note_id}")
    target.append(anchor)
    epub.store(ref_member, target.getroottree())

    _, note_block = epub.locate_block(template_note)
    container = _container(note_block)
    clone = deepcopy(container)
    clone.set("id", note_id)
    steps = []
    node = note_block
    while node is not container:
        parent = node.getparent()
        assert parent is not None
        steps.append(parent.index(node))
        node = parent
    body = clone
    for step in reversed(steps):
        body = body[step]
    back = posixpath.relpath(ref_member, posixpath.dirname(note_member))
    for child in list(body):
        if etree.QName(child).localname == "a" and child.get("href"):
            child.set("href", f"{back}#{ref_id}")
        else:
            body.remove(child)
    body.text = f"0. {note.text}"
    container.addnext(clone)
    epub.store(note_member, container.getroottree())
    _place(epub, note_id)


def _place(epub: Epub, note_id: str) -> None:
    """Move the new note's container to follow the note of the reference before it."""
    notes = epub.book().notes
    containers = []
    for n in notes:
        member, block = epub.locate_block(n.block)
        containers.append((member, _container(block)))
    index = next(i for i, (_, c) in enumerate(containers) if c.get("id") == note_id)
    member, moved = containers[index]
    neighbour = index - 1 if index > 0 else index + 1
    if neighbour >= len(containers) or containers[neighbour][0] != member:
        return
    # Each lookup parses the document afresh; find the neighbour again in the moved note's tree.
    wanted = containers[neighbour][1].get("id")
    other = next(e for e in moved.getroottree().getroot().iter() if e.get("id") == wanted)
    if other.getparent() is not moved.getparent():
        return
    if index > 0:
        other.addnext(moved)
    else:
        other.addprevious(moved)
    epub.store(member, moved.getroottree())


def _renumber(epub: Epub) -> None:
    """Number each reference and note by the reading order of the references."""
    for number, note in enumerate(epub.book().notes, 1):
        member, block = epub.locate_block(note.block)
        nid = _container(block).get("id")
        block.text = _NUMBER.sub(str(number), block.text or "", count=1)
        epub.store(member, block.getroottree())
        ref_member, reference = epub.locate_block(note.reference)
        anchor = _reference_anchor(reference, str(nid))
        anchor.text = _NUMBER.sub(str(number), anchor.text or "", count=1)
        epub.store(ref_member, reference.getroottree())
