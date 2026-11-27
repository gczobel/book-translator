"""Seam 1: the CLI. S8 Spanish typography: the normaliser's stored targets and QA's findings."""

import json
from pathlib import Path

import pytest

from test_cli_draft import source_ids
from test_cli_fidelity import query, target_text
from test_cli_qa import CountingAdapter, findings, qa, set_source, set_target, tamper, translate

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


def test_numbers_use_a_decimal_comma_and_spaced_thousands_and_percent_signs(
    book: tuple[Path, CountingAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    ws, adapter = book
    nb = " "
    cases = [
        (
            "Eran 1,000.5 y 8,327,451 y 8.327.451 personas.",
            f"Eran 1000,5 y 8{nb}327{nb}451 y 8{nb}327{nb}451 personas.",
        ),
        (
            "El 25% y el 3,1416 en el año 2001 con 1.200 tardes.",
            f"El 25{nb}% y el 3,1416 en el año 2001 con 1.200 tardes.",
        ),
    ]
    for text, expected in cases:
        assert normalised(ws, text, adapter, capsys) == expected  # N2, N3, N6
        assert normalised(ws, expected, adapter, capsys) == expected
    assert findings(ws) == []


def test_inline_codes_are_never_corrupted(
    book: tuple[Path, CountingAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    ws, adapter = book
    block = "OEBPS/ch2.xhtml#1"
    set_target(ws, block, 'Dijo "<pc id="1">alto</pc>" ya, 25% así.')

    qa(ws, adapter, capsys)

    assert target_text(ws, block) == 'Dijo «<pc id="1">alto</pc>» ya, 25 % así.'
    assert [f for f in findings(ws) if f[0] == block] == []
    set_target(ws, block, 'Dijo "<pc id="1">alto" ya</pc> así.')  # a pair straddling a quote
    qa(ws, adapter, capsys)
    assert target_text(ws, block) == 'Dijo «<pc id="1">alto» ya</pc> así.'
    assert [f for f in findings(ws) if f[0] == block] == []  # the codes are still legal


def set_thoughts(ws: Path, setting: str) -> None:
    """Change the style sheet's thoughts choice in the stored bible."""
    (stored,) = query(ws, "select result from bible")[0]
    bible = json.loads(stored)
    bible["style"]["thoughts"] = setting
    tamper(ws, "update bible set result = ?", json.dumps(bible))


def test_thoughts_follow_the_style_sheet_choice_everywhere(
    book: tuple[Path, CountingAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    ws, adapter = book
    italic = "OEBPS/ch2.xhtml#1"  # the block with an italic code
    set_target(ws, italic, '<pc id="1">Qué tarde</pc>, pensó él.')
    set_target(ws, BLOCK, "«Qué bien», se dijo ella en voz baja, sin mirar a nadie.")

    qa(ws, adapter, capsys)
    assert [f for f in findings(ws) if f[1] == "thoughts"] == [(BLOCK, "thoughts")]  # « » is wrong

    set_thoughts(ws, "quotation marks")
    qa(ws, adapter, capsys)
    assert [f for f in findings(ws) if f[1] == "thoughts"] == [(italic, "thoughts")]

    set_thoughts(ws, "plain")
    qa(ws, adapter, capsys)
    wrong = {f for f in findings(ws) if f[1] == "thoughts"}
    assert wrong == {(BLOCK, "thoughts"), (italic, "thoughts")}


def test_words_of_the_wrong_spanish_variety_are_reported_by_the_workspace_variety(
    book: tuple[Path, CountingAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    ws, adapter = book

    def variety_findings(variety: str, text: str) -> list[str]:
        tamper(ws, "insert or replace into settings values ('variety', ?)", variety)
        set_target(ws, BLOCK, text)
        out = qa(ws, adapter, capsys)
        found = [f for f in findings(ws) if f == (BLOCK, "variety")]
        assert bool(found) == ("[variety]" in out)
        return [line for line in out.splitlines() if "[variety]" in line]

    peninsular = "Cogió el ordenador y vosotros lo visteis mucho."
    river_plate = "Agarrá la computadora, che, vos tenés que ir al laburo."
    american = "Tomó la computadora y el celular, platicó con todos ahorita."

    neutral = variety_findings("neutral", peninsular)
    assert all(w in " ".join(neutral) for w in ("cogió", "ordenador", "vosotros"))
    assert variety_findings("peninsular", peninsular) == []
    assert variety_findings("neutral", river_plate) != []
    assert variety_findings("rioplatense", river_plate) == []
    assert variety_findings("rioplatense", peninsular) != []
    assert variety_findings("peninsular", american) != []
    assert variety_findings("neutral", american) == []
    assert variety_findings("rioplatense", american) != []


def test_months_and_days_are_lowercase_inside_a_sentence_but_not_names_or_sentence_starts(
    book: tuple[Path, CountingAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    ws, adapter = book
    cases = [
        (
            "Llegó el Lunes 3 de Mayo y se fue en Diciembre.",
            "Llegó el lunes 3 de mayo y se fue en diciembre.",
        ),
        ("Marzo fue largo. Vio a Domingo Pérez y al Domingo Ramos.", None),  # starts and names
    ]
    for text, expected in cases:
        assert normalised(ws, text, adapter, capsys) == (expected or text)  # 3.6
        assert normalised(ws, expected or text, adapter, capsys) == (expected or text)
    assert query(ws, "select rule from typography_changes") == [("months_days",)]
