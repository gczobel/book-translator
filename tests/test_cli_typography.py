"""Seam 1: the CLI. S8 Spanish typography: the normaliser's stored targets and QA's findings."""

from pathlib import Path

import pytest

from test_cli_draft import source_ids
from test_cli_fidelity import query, target_text
from test_cli_qa import CountingAdapter, findings, qa, set_source, set_target, translate

BLOCK = source_ids()[1]


def normalised(
    ws: Path, text: str, adapter: CountingAdapter, out: pytest.CaptureFixture[str]
) -> str:
    """Store `text` as the target of one block, run again and return what is stored."""
    set_target(ws, BLOCK, text)
    qa(ws, adapter, out)
    return target_text(ws, BLOCK)


@pytest.fixture
def book(tmp_path: Path) -> tuple[Path, CountingAdapter]:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter)
    set_source(
        ws, BLOCK, "it was a quiet evening in the old house of the town, said nobody at all."
    )
    return ws, adapter


def test_quotes_nest_as_guillemets_then_double_then_single_curly_and_punctuation_goes_outside(
    book: tuple[Path, CountingAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    ws, adapter = book
    text = 'Antonio dijo: "vaya \'cacharro\' se ha comprado." Pensó en "nada,"'

    stored = normalised(ws, text, adapter, capsys)

    assert stored == "Antonio dijo: «vaya “cacharro” se ha comprado». Pensó en «nada»,"
    assert query(ws, "select rule, old, new from typography_changes") == [("quotes", text, stored)]
    assert findings(ws) == []
    assert normalised(ws, stored, adapter, capsys) == stored  # idempotent
    assert query(ws, "select count(*) from typography_changes") == [(1,)]


def test_unpaired_quotes_are_flagged_unless_the_next_paragraph_continues_them(
    book: tuple[Path, CountingAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    ws, adapter = book

    stored = normalised(ws, 'Dijo "algo y se fue ahora mismo, por la puerta.', adapter, capsys)

    assert stored == 'Dijo "algo y se fue ahora mismo, por la puerta.'
    assert (BLOCK, "quotes") in findings(ws)

    set_target(ws, BLOCK, "Dijo: «Algo largo que sigue en el párrafo siguiente.", 0)
    set_target(ws, source_ids()[2], "»Y así termina lo dicho.")
    qa(ws, adapter, capsys)
    assert (BLOCK, "quotes") not in findings(ws)  # Q6: the next paragraph opens with »


def test_raya_is_set_as_a_dialogue_dash_with_glued_incisos_and_no_closing_raya_at_the_end(
    book: tuple[Path, CountingAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    ws, adapter = book
    cases = [
        ("-¿Qué fue eso? - preguntó Beregond.", "—¿Qué fue eso? —preguntó Beregond."),  # D1, D2
        ("— Está bien, —dijo Carlos—, lo haré.", "—Está bien —dijo Carlos—, lo haré."),  # D4
        ("Era viejo—muy viejo—y estaba cansado.", "Era viejo —muy viejo— y estaba cansado."),  # D8
        ("—¿Qué fue eso? —preguntó Beregond—", "—¿Qué fue eso? —preguntó Beregond."),  # D3
        ("Sus rayas son muy —muy largas.", "Sus rayas son muy —muy largas."),  # unpaired
    ]
    for text, expected in cases:
        assert normalised(ws, text, adapter, capsys) == expected
        assert normalised(ws, expected, adapter, capsys) == expected  # idempotent
    assert (BLOCK, "raya") in findings(ws)  # only the last case cannot be settled
    assert normalised(ws, cases[0][1], adapter, capsys) == cases[0][1]
    assert (BLOCK, "raya") not in findings(ws)


def test_a_question_or_exclamation_lacking_its_opener_gets_one_only_when_unambiguous(
    book: tuple[Path, CountingAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    ws, adapter = book
    cases = [
        ("Qué fue eso? Nada! Se fue ya.", "¿Qué fue eso? ¡Nada! Se fue ya."),
        ("—Qué fue eso? —preguntó Beregond.", "—¿Qué fue eso? —preguntó Beregond."),
        ("Dijo «hola!», y se fue sin más.", "Dijo «¡hola!», y se fue sin más."),
        ("Pero dónde vas? Eso no está bien.", "Pero dónde vas? Eso no está bien."),  # partial
    ]
    for text, expected in cases:
        assert normalised(ws, text, adapter, capsys) == expected
        assert normalised(ws, expected, adapter, capsys) == expected
    assert (BLOCK, "inverted_marks") in findings(ws)  # the partial question needs a person
    assert normalised(ws, cases[0][1], adapter, capsys) == cases[0][1]
    assert (BLOCK, "inverted_marks") not in findings(ws)
