"""Seam 2: rebuilding blocks with 1:N splits, tested only through the EPUB codec's interface."""

import inspect
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from book_translator.epub import Epub, InlineCodeError, open_epub

FIXTURES = Path(__file__).parent / "fixtures" / "epub"


def source_blocks(epub: Epub) -> list[str]:
    return [b.id for c in epub.book().chapters for s in c.scenes for b in s.blocks]


def members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def test_identity_translation_reproduces_the_source(tmp_path: Path) -> None:
    source = FIXTURES / "inline-markup.epub"
    epub = open_epub(source)
    for bid in source_blocks(epub):
        encoded = epub.encode_block(bid)
        epub.rebuild_block(bid, encoded, [encoded.text])
    out = tmp_path / "out.epub"

    epub.write(out)

    before, after = members(source), members(out)
    assert after == before


def paragraphs(epub: Epub, member: str = "OEBPS/ch1.xhtml") -> list[tuple[str | None, str]]:
    root = etree.fromstring(epub.read(member))
    return [
        (p.get("class"), str(etree.tostring(p, method="text", encoding="unicode", with_tail=False)))
        for p in root.iterfind(".//{http://www.w3.org/1999/xhtml}p")
    ]


def test_a_block_replaced_by_three_blocks_gives_three_clones_in_place() -> None:
    epub = open_epub(FIXTURES / "dialogue.epub")
    first = source_blocks(epub)[1]
    encoded = epub.encode_block(first)

    epub.rebuild_block(first, encoded, ["— Ve —dijo ella.", "— Ahora —dijo él.", "Fin."])

    assert paragraphs(epub) == [
        ("first", "— Ve —dijo ella."),
        ("first", "— Ahora —dijo él."),
        ("first", "Fin."),
        ("body", "He saw her leave."),
        ("last", "The end."),
    ]


def test_later_blocks_stay_addressed_by_their_source_id_after_an_earlier_split() -> None:
    epub = open_epub(FIXTURES / "dialogue.epub")
    ids = source_blocks(epub)
    first = epub.encode_block(ids[1])
    epub.rebuild_block(ids[1], first, ["Uno.", "Dos."])
    last = epub.encode_block(ids[3])

    epub.rebuild_block(ids[3], last, ["Fin."])

    assert [text for _, text in paragraphs(epub)] == [
        "Uno.",
        "Dos.",
        "He saw her leave.",
        "Fin.",
    ]


def test_a_block_can_be_rebuilt_again_with_a_different_number_of_pieces() -> None:
    epub = open_epub(FIXTURES / "dialogue.epub")
    ids = source_blocks(epub)
    encoded = epub.encode_block(ids[1])
    epub.rebuild_block(ids[1], encoded, ["Uno.", "Dos.", "Tres."])

    epub.rebuild_block(ids[1], encoded, ["Uno.", "Dos."])

    assert [text for _, text in paragraphs(epub)] == [
        "Uno.",
        "Dos.",
        "He saw her leave.",
        "The end.",
    ]


def test_only_the_first_target_block_keeps_the_source_element_id() -> None:
    epub = open_epub(FIXTURES / "dialogue.epub")
    ids = source_blocks(epub)
    encoded = epub.encode_block(ids[2])

    epub.rebuild_block(ids[2], encoded, ['Vio <pc id="1">su</pc>', "partida."])

    root = etree.fromstring(epub.read("OEBPS/ch1.xhtml"))
    assert [p.get("id") for p in root.iterfind(".//{*}p[@class='body']")] == ["mid", None]


def test_every_target_block_carries_its_source_block_id() -> None:
    epub = open_epub(FIXTURES / "dialogue.epub")
    ids = source_blocks(epub)
    epub.rebuild_block(ids[1], epub.encode_block(ids[1]), ["Uno.", "Dos.", "Tres."])

    assert [(t.id, t.source) for t in epub.target_blocks()] == [
        ("OEBPS/ch1.xhtml#1", ids[1]),
        ("OEBPS/ch1.xhtml#2", ids[1]),
        ("OEBPS/ch1.xhtml#3", ids[1]),
    ]


def test_inline_codes_are_reinjected_into_the_target_block_that_carries_them() -> None:
    epub = open_epub(FIXTURES / "dialogue.epub")
    ids = source_blocks(epub)
    encoded = epub.encode_block(ids[2])

    epub.rebuild_block(ids[2], encoded, ["Vio.", 'Ella <pc id="1">se</pc> fue.'])

    root = etree.fromstring(epub.read("OEBPS/ch1.xhtml"))
    first, second = root.iterfind(".//{*}p[@class='body']")
    assert first.find("{*}i") is None
    italic = second.find("{*}i")
    assert italic is not None and italic.text == "se"
    assert [
        etree.tostring(p, method="text", encoding="unicode", with_tail=False)
        for p in (first, second)
    ] == [
        "Vio.",
        "Ella se fue.",
    ]


@pytest.mark.parametrize(
    "texts",
    [
        [],
        ['Vio <pc id="1">su', "partida</pc>."],
        ["Vio.", "Ella se fue."],
    ],
    ids=["no pieces", "pair straddling two pieces", "code lost"],
)
def test_an_illegal_split_is_rejected_and_leaves_the_document_unchanged(texts: list[str]) -> None:
    epub = open_epub(FIXTURES / "dialogue.epub")
    before = epub.read("OEBPS/ch1.xhtml")
    ids = source_blocks(epub)
    encoded = epub.encode_block(ids[2])

    with pytest.raises(InlineCodeError):
        epub.rebuild_block(ids[2], encoded, texts)

    assert epub.read("OEBPS/ch1.xhtml") == before
    assert epub.target_blocks() == []


def test_the_codec_offers_no_way_to_merge_blocks_or_move_text_between_them() -> None:
    public = {n for n in dir(Epub) if not n.startswith("_")}
    assert public == {
        "book",
        "encode_block",
        "locate_block",
        "names",
        "opf_path",
        "read",
        "rebuild_block",
        "replace_block",
        "spine",
        "store",
        "target_blocks",
        "write",
    }
    assert list(inspect.signature(Epub.rebuild_block).parameters) == [
        "self",
        "block_id",
        "encoded",
        "texts",
    ]
