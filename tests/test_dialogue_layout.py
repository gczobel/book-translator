"""Narration and speech never share a paragraph: a raya opening speech starts its own."""

import sqlite3

from book_translator.bible import StyleSheet
from book_translator.dialogue import break_paragraphs, lay_out, relayout
from book_translator.epub import open_epub
from test_cli_bible_part2 import EPUB
from test_cli_draft import source_ids


def test_narration_followed_by_speech_becomes_two_paragraphs() -> None:
    text = (
        "Salió Mrs. Otis con una bata azul. —Me temo que está muy mal —dijo— y le he traído algo."
    )

    assert break_paragraphs(text) == [
        "Salió Mrs. Otis con una bata azul.",
        "—Me temo que está muy mal —dijo— y le he traído algo.",
    ]


def test_a_colon_and_a_raw_newline_also_end_the_narration() -> None:
    assert break_paragraphs("Se asomó y dijo: —Bueno, Cecil.") == [
        "Se asomó y dijo:",
        "—Bueno, Cecil.",
    ]
    assert break_paragraphs("Se asomó y dijo:\n—Bueno, Cecil.") == [
        "Se asomó y dijo:",
        "—Bueno, Cecil.",
    ]


def test_a_paragraph_that_opens_with_a_raya_is_never_broken() -> None:
    text = "—¿Puedo irme ya? —Se puso en pie—. No hace falta, respondió."

    assert break_paragraphs(text) == [text]


def test_a_raya_inside_an_open_guillemet_quote_is_an_inciso_not_new_speech() -> None:
    text = "«¡Qué horror! —exclamó Mrs. Otis—. No me gustan las manchas. Quítela»."

    assert break_paragraphs(text) == [text]
    assert break_paragraphs("Dijo «no» y salió. —Hola —dijo.") == [
        "Dijo «no» y salió.",
        "—Hola —dijo.",
    ]


def test_an_inciso_inside_narration_is_not_a_speech() -> None:
    text = "Compró varias obras —todas de su primera época— y se fue."

    assert break_paragraphs(text) == [text]


def test_the_layout_of_a_new_draft_also_breaks_narration_from_speech() -> None:
    assert lay_out(["Salió. —Hola —dijo."], "raya-split") == ["Salió.", "—Hola —dijo."]
    assert lay_out(["Salió. —Hola —dijo."], "inline-quotes") == ["Salió. —Hola —dijo."]


def stored(texts: list[str]) -> tuple[sqlite3.Connection, str]:
    block = source_ids()[1]
    db = sqlite3.connect(":memory:")
    db.execute("create table targets (source text, position integer, text text)")
    db.executemany(
        "insert into targets values (?, ?, ?)", [(block, n, t) for n, t in enumerate(texts)]
    )
    return db, block


def rows(db: sqlite3.Connection, block: str) -> list[str]:
    q = "select text from targets where source = ? order by position"
    return [str(r[0]) for r in db.execute(q, (block,))]


def test_relayout_rewrites_stored_targets_and_renumbers_their_positions() -> None:
    db, block = stored(["Salió. —Hola —dijo.", "Otro párrafo."])

    changed = relayout(db, open_epub(EPUB), StyleSheet(thoughts="", numbers="", titles=""))

    assert changed == 1
    assert rows(db, block) == ["Salió.", "—Hola —dijo.", "Otro párrafo."]


def test_relayout_is_idempotent_and_leaves_inline_quotes_alone() -> None:
    db, block = stored(["Salió. —Hola —dijo."])
    raya = StyleSheet(thoughts="", numbers="", titles="")
    relayout(db, open_epub(EPUB), raya)

    assert relayout(db, open_epub(EPUB), raya) == 0

    other, same = stored(["Salió. —Hola —dijo."])
    quotes = StyleSheet(thoughts="", numbers="", titles="", dialogue="inline-quotes")
    assert relayout(other, open_epub(EPUB), quotes) == 0
    assert rows(other, same) == ["Salió. —Hola —dijo."]
