"""Seam 1: the CLI. The style sheet's dialogue setting shows in the stored target blocks."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from book_translator import main
from book_translator.epub import open_epub
from book_translator.llm import LLMRequest, RawAnswer
from test_cli_bible_part2 import EPUB, PART1
from test_cli_draft import DraftAdapter, drafted, query, source_ids


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral"])
    return path


Answer = Callable[[LLMRequest, int], str]

TWO_TURNS = "«¿Qué fue eso?», preguntó Hiram. «Nada», respondió Simon."
TARGET = 1  # index of the source block the drafter answers with dialogue


def say(*texts: str, block: str | None = None) -> Answer:
    """A drafter that answers one block (TARGET by default) with `texts`, echoing the rest."""

    def answer(request: LLMRequest, attempt: int) -> str:
        passage = json.loads(request.source_text)["passage"]
        chosen = block or source_ids()[TARGET]
        blocks = [
            {"source": b["id"], "targets": list(texts) if b["id"] == chosen else [b["text"]]}
            for b in passage
        ]
        return json.dumps({"blocks": blocks})

    return answer


class DialogueAdapter(DraftAdapter):
    """A draft adapter whose consolidated style sheet carries the given dialogue setting."""

    def __init__(self, dialogue: str | None, answer: Answer) -> None:
        super().__init__(answer)
        self.dialogue = dialogue

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage == "consolidation" and self.dialogue:
            style = {**PART1["style"], "dialogue": self.dialogue}  # type: ignore[dict-item]
            return RawAnswer(json.dumps({**PART1, "style": style}))
        return super().complete(request, key, attempt)


def targets_of(ws: Path, index: int) -> list[str]:
    rows = query(
        ws, f"select text from targets where source = '{source_ids()[index]}' order by position"
    )
    return [str(r[0]) for r in rows]


def test_raya_split_gives_every_speech_turn_its_own_raya_block(ws: Path) -> None:
    drafted(ws, DialogueAdapter(None, say(TWO_TURNS)))

    assert targets_of(ws, TARGET) == [
        "—¿Qué fue eso? —preguntó Hiram.",
        "—Nada —respondió Simon.",
    ]


def test_inline_quotes_keeps_the_same_block_whole_with_guillemets(ws: Path) -> None:
    drafted(ws, DialogueAdapter("inline-quotes", say(TWO_TURNS)))

    assert targets_of(ws, TARGET) == [TWO_TURNS]


def test_a_block_with_one_speech_turn_is_never_split(ws: Path) -> None:
    one = "Hiram se detuvo. «¿Qué fue eso?», preguntó."
    drafted(ws, DialogueAdapter(None, say(one)))

    assert targets_of(ws, TARGET) == [one]


def test_a_block_without_speech_is_never_split(ws: Path) -> None:
    drafted(ws, DialogueAdapter(None, say("Era una tarde tranquila. Nada se movía.")))

    assert targets_of(ws, TARGET) == ["Era una tarde tranquila. Nada se movía."]


def test_a_turn_interrupted_by_an_inciso_stays_one_turn(ws: Path) -> None:
    text = "«Está bien», dijo Carlos, «lo haré». «Gracias», dijo Ana."
    drafted(ws, DialogueAdapter(None, say(text)))

    assert targets_of(ws, TARGET) == [
        "—Está bien —dijo Carlos—, lo haré.",
        "—Gracias —dijo Ana.",
    ]


def test_narration_before_the_first_turn_is_its_own_block_without_raya(ws: Path) -> None:
    text = "Se miraron. «Hola», dijo Ana. «Hola», dijo Luis."
    drafted(ws, DialogueAdapter(None, say(text)))

    assert targets_of(ws, TARGET) == ["Se miraron.", "—Hola —dijo Ana.", "—Hola —dijo Luis."]


def test_a_non_speech_verb_keeps_the_speech_punctuation_and_a_capital(ws: Path) -> None:
    text = "«No se moleste.» Cerró la puerta. «Adiós», dijo."
    drafted(ws, DialogueAdapter(None, say(text)))

    assert targets_of(ws, TARGET) == ["—No se moleste. —Cerró la puerta.", "—Adiós —dijo."]


def test_split_blocks_keep_the_source_id_and_other_blocks_are_untouched(ws: Path) -> None:
    drafted(ws, DialogueAdapter(None, say(TWO_TURNS)))

    ids = {r[0] for r in query(ws, "select source from targets")}
    assert ids == set(source_ids())
    assert len(targets_of(ws, TARGET)) == 2
    assert all(len(targets_of(ws, i)) == 1 for i in range(len(source_ids())) if i != TARGET)


def test_a_split_that_would_break_an_inline_code_pair_is_not_made(ws: Path) -> None:
    marked = next(i for i in source_ids() if '<pc id="1">' in open_epub(EPUB).encode_block(i).text)
    straddling = '«Hola <pc id="1">uno», dijo Ana. «dos», dijo Luis</pc>.'

    drafted(ws, DialogueAdapter(None, say(straddling, block=marked)))

    rows = query(ws, f"select text from targets where source = '{marked}'")
    assert [r[0] for r in rows] == [straddling]
