"""Seam 2: structure detection, observed through the codec's Book model only."""

from pathlib import Path

from book_translator.epub import open_epub

FIXTURES = Path(__file__).parent / "fixtures" / "epub"


def test_chapters_take_their_titles_from_the_ncx_and_hold_the_blocks_in_order() -> None:
    book = open_epub(FIXTURES / "plain.epub").book()

    assert [c.title for c in book.chapters] == ["One", "Two"]
    first = book.chapters[0]
    texts = [b.text for s in first.scenes for b in s.blocks]
    assert texts[:3] == ["One", "It was a quiet evening.", "She said nothing."]
    assert first.scenes[0].blocks[0].kind == "heading"
    assert first.scenes[0].blocks[1].kind == "paragraph"


def scene_texts(name: str, chapter: int = 0) -> list[list[str]]:
    book = open_epub(FIXTURES / name).book()
    return [[b.text for b in s.blocks] for s in book.chapters[chapter].scenes]


def test_hr_scene_breaks_of_any_class_split_scenes() -> None:
    assert scene_texts("hr-breaks.epub") == [["One", "A1.", "A2."], ["B1."], ["C1."]]


def test_asterism_spacer_and_classed_paragraphs_split_scenes() -> None:
    assert scene_texts("asterism-breaks.epub") == [
        ["One", "A1."],
        ["B1."],
        ["C1."],
        ["D1."],
        ["E1."],
        ["F1."],
    ]


def test_scene_breaks_are_preserved_not_translatable() -> None:
    chapter = open_epub(FIXTURES / "hr-breaks.epub").book().chapters[0]

    assert len(chapter.breaks) == len(chapter.scenes) - 1 == 2
    assert not any(b.translatable for b in chapter.breaks)
    block_ids = {b.id for s in chapter.scenes for b in s.blocks}
    assert block_ids.isdisjoint(b.id for b in chapter.breaks)


def test_a_chapter_spanning_two_files_is_one_chapter() -> None:
    book = open_epub(FIXTURES / "split-chapter.epub").book()

    assert [c.title for c in book.chapters] == ["One"]
    assert [[b.text for b in s.blocks] for s in book.chapters[0].scenes] == [
        ["One", "A1.", "A2.", "A3."],
        ["B1."],
    ]


def test_ncx_fragment_links_split_chapters_inside_one_file() -> None:
    book = open_epub(FIXTURES / "fragment-chapters.epub").book()

    assert [c.title for c in book.chapters] == ["One", "Two"]
    assert [b.text for s in book.chapters[1].scenes for b in s.blocks] == [
        "Two",
        "Line a\nLine b",
        "More of two.",
    ]


def test_without_a_table_of_contents_chapters_come_from_headings() -> None:
    book = open_epub(FIXTURES / "no-toc.epub").book()

    assert [c.title for c in book.chapters] == ["One", "Two"]


def test_verse_groups_and_list_items_are_blocks_of_their_own_kind() -> None:
    chapter = open_epub(FIXTURES / "fragment-chapters.epub").book().chapters[0]

    blocks = [(b.kind, b.text) for s in chapter.scenes for b in s.blocks]
    assert blocks == [
        ("heading", "One"),
        ("paragraph", "A1."),
        ("verse", "Roses are red\nViolets are blue"),
        ("list_item", "first"),
        ("list_item", "second"),
    ]


def test_blocks_keep_a_stable_id_and_their_position() -> None:
    first = open_epub(FIXTURES / "hr-breaks.epub").book()
    again = open_epub(FIXTURES / "hr-breaks.epub").book()

    blocks = [b for c in first.chapters for s in c.scenes for b in s.blocks]
    assert [b.position for b in blocks] == list(range(len(blocks)))
    assert len({b.id for b in blocks}) == len(blocks)
    assert blocks == [b for c in again.chapters for s in c.scenes for b in s.blocks]
    assert blocks[0].id == "OEBPS/ch1.xhtml#0"


def test_notes_are_linked_to_their_references_by_rf_nt_ids() -> None:
    book = open_epub(FIXTURES / "notes.epub").book()

    by_id = {b.id: b for c in book.chapters for s in c.scenes for b in s.blocks}
    linked = [(by_id[n.reference].text, by_id[n.block].text) for n in book.notes]
    assert linked == [
        ("Born in the town.[1]", "1. A small town.back"),
        ("Said the maire.[2] Then left.", "2. The mayor.back"),
    ]
