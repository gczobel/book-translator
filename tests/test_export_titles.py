"""The table of contents and section labels follow the translation."""

import sqlite3
from dataclasses import dataclass

from book_translator.export import _chapter_titles, _section_titles
from book_translator.structure import Block, Book, Chapter, Part, Scene


@dataclass
class FakeSource:
    book_: Book

    def book(self) -> Book:
        return self.book_


def heading(text: str) -> Block:
    return Block("c#0", "heading", text, 0)


def stored(text: str) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("create table targets (source text, position integer, text text)")
    db.execute("insert into targets values ('c#0', 0, ?)", (text,))
    return db


def one_chapter(title: str, block_text: str) -> FakeSource:
    chapter = Chapter(title, [Scene([heading(block_text)])], [])
    return FakeSource(Book([chapter], [], [], []))


def test_a_heading_whose_number_sits_in_its_own_span_still_labels_its_chapter() -> None:
    source = one_chapter("Chapter I", "ChapterI")  # <h1>Chapter<span>I</span></h1>

    titles = _chapter_titles(stored('Capítulo<pc id="1">I</pc>'), source)  # type: ignore[arg-type]

    assert titles == {"Chapter I": "Capítulo I", "ChapterI": "Capítulo I"}


def test_a_heading_translated_with_its_space_keeps_one_space() -> None:
    source = one_chapter("Chapter II", "ChapterII")

    titles = _chapter_titles(stored('Capítulo <pc id="1">II</pc>'), source)  # type: ignore[arg-type]

    assert titles == {"Chapter II": "Capítulo II", "ChapterII": "Capítulo II"}


def test_the_fixed_sections_of_a_spanish_book_get_their_spanish_labels() -> None:
    book = Book(
        [],
        [],
        [Part("cover", "Cover", []), Part("synopsis", "Synopsis", [])],
        [Part("about_author", "Author", [])],
    )

    assert _section_titles(book, "es") == {
        "Cover": "Cubierta",
        "Synopsis": "Sinopsis",
        "Author": "Autor",
    }
    assert _section_titles(book, "ja") == {}


def test_a_section_with_an_unfamiliar_label_is_left_alone() -> None:
    book = Book([], [], [Part("cover", "Portada original", [])], [])

    assert _section_titles(book, "es") == {}
