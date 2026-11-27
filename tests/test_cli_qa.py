"""Seam 1: the CLI. S8 deterministic QA checks, reported through `run` and `status`."""

import sqlite3
from pathlib import Path

import pytest

from book_translator import main
from book_translator.epub import open_epub
from book_translator.llm import LLMRequest, RawAnswer
from book_translator.qa import QAFailedError, require_qa_clean
from test_cli_bible_part2 import EPUB
from test_cli_draft import source_ids
from test_cli_fidelity import query
from test_cli_polish import PolishAdapter, unchanged


class CountingAdapter(PolishAdapter):
    """The polish adapter, counting every LLM call and noting the stages that made them."""

    def __init__(self, **bible: object) -> None:
        super().__init__(unchanged, **bible)
        self.stages: list[str] = []

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        self.stages.append(request.stage)
        return super().complete(request, key, attempt)


def translate(tmp_path: Path, adapter: CountingAdapter, *extra: str) -> Path:
    """Run a book up to the last LLM stage (S7), leaving the QA stage run once."""
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral", *extra])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])  # analysis gate
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])  # TK gate
    main(["run", str(ws)], adapter=adapter)
    return ws


def tamper(ws: Path, sql: str, *args: object) -> None:
    with sqlite3.connect(ws / "book.sqlite") as db:
        db.execute(sql, args)


def set_target(ws: Path, block: str, text: str, position: int = 0) -> None:
    tamper(
        ws, "update targets set text = ? where source = ? and position = ?", text, block, position
    )


def qa(ws: Path, adapter: CountingAdapter, capsys: pytest.CaptureFixture[str]) -> str:
    """Run again (the QA stage re-runs on the stored targets) and return what was printed."""
    capsys.readouterr()
    main(["run", str(ws)], adapter=adapter)
    return capsys.readouterr().out


def findings(ws: Path) -> list[tuple[str, str]]:
    return query(ws, "select block, check_name from qa_findings order by id")


def test_a_clean_book_passes_qa_with_a_report_and_no_llm_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter)
    calls = len(adapter.stages)

    out = qa(ws, adapter, capsys)

    assert "QA: passed" in out
    assert findings(ws) == []
    assert query(ws, "select status from stages where stage = 'qa'") == [("done",)]
    assert len(adapter.stages) == calls  # QA makes no LLM call
    assert "qa" not in adapter.stages
    main(["status", str(ws)])
    assert "Stage: qa (done)" in capsys.readouterr().out


GLOSSARY = [
    {"term": "evening", "rendering": "evening", "banned_variants": ["dusk"], "origin": "extracted"}
]


def test_glossary_use_passes_when_followed_and_fails_on_a_banned_variant_or_a_lost_term(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter(glossary=GLOSSARY)
    ws = translate(tmp_path, adapter)
    block = source_ids()[1]
    assert qa(ws, adapter, capsys).startswith("QA: passed")

    set_target(ws, block, "It was a quiet dusk.")
    out = qa(ws, adapter, capsys)

    assert (block, "banned_variant") in findings(ws)
    assert (block, "glossary") in findings(ws)  # the term is also gone
    assert f"[banned_variant] {block}" in out
    assert query(ws, "select status from stages where stage = 'qa'") == [("failed",)]


def test_a_blank_target_is_an_omission_and_a_lopsided_one_breaks_the_length_band(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter)
    long_block, blank_block = source_ids()[1], source_ids()[2]
    set_target(ws, long_block, "It was a quiet evening. " * 8)
    set_target(ws, blank_block, "  ")

    qa(ws, adapter, capsys)

    assert (blank_block, "omission") in findings(ws)
    assert (long_block, "length_ratio") in findings(ws)
    assert (long_block, "omission") not in findings(ws)


def set_source(ws: Path, block: str, text: str) -> None:
    """Change a source block's text, as a book with numbers and names would have it."""
    source = open_epub(ws / "source.epub")
    source.replace_block(block, source.encode_block(block), text)
    source.write(ws / "source.epub")


def test_numbers_and_names_of_the_source_must_reach_the_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    glossary = [{"term": "Hiram", "rendering": "Hiram el Viejo", "origin": "established"}]
    adapter = CountingAdapter(glossary=glossary)
    ws = translate(tmp_path, adapter)
    block, other = source_ids()[1], source_ids()[2]
    set_source(ws, block, "It was 1,200 quiet evenings in Hiram's town. Then Simon left.")
    set_target(ws, block, "Fueron 1.200 tardes en el pueblo de Hiram el Viejo. Simon se fue.")
    qa(ws, adapter, capsys)
    assert findings(ws) == []  # separators, glossary renderings and names are allowed

    set_target(ws, block, "Fueron muchas tardes tranquilas en el pueblo. Entonces se fue.")
    out = qa(ws, adapter, capsys)

    assert "'Simon'" in out  # a cast name with no glossary entry must be there itself
    assert (block, "numbers") in findings(ws)
    assert (block, "names") in findings(ws)
    assert [f for f in findings(ws) if f[0] == other] == []


def test_a_locked_motif_must_be_rendered_the_same_every_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    motifs = [{"name": "quiet evening", "locked_rendering": "tarde en calma"}]
    adapter = CountingAdapter(motifs=motifs)
    ws = translate(tmp_path, adapter)
    first, second = source_ids()[1], source_ids()[2]
    set_source(ws, second, "Another quiet evening came.")
    set_target(ws, first, "Era una tarde en calma.")
    set_target(ws, second, "Llegó otra tarde en calma.")
    qa(ws, adapter, capsys)
    assert findings(ws) == []

    set_target(ws, second, "Llegó otra noche tranquila.")
    qa(ws, adapter, capsys)

    assert findings(ws) == [(second, "motif")]


def test_inline_markup_must_stay_intact_in_every_target_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter)
    block = "OEBPS/ch2.xhtml#1"
    set_target(ws, block, 'La mañana siguiente fue <pc id="1">ruidosa</pc>.')
    qa(ws, adapter, capsys)
    assert findings(ws) == []

    set_target(ws, block, 'La mañana siguiente fue <pc id="1">ruidosa.')
    out = qa(ws, adapter, capsys)

    assert findings(ws) == [(block, "inline_markup")]
    assert "must open and close" in out


def test_an_open_tk_and_an_unresolved_fidelity_finding_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter)
    block = source_ids()[1]
    tamper(
        ws,
        "insert into tks values ('TK-9', ?, 'quiet', 'idiom', 'x', 'y', '[]', 'y', 0.5, 'local',"
        " null, null)",
        block,
    )
    tamper(
        ws,
        "insert into unresolved_findings (stage, block, position, old, new, reason, category)"
        " values ('post_polish_fidelity', ?, 0, 'quiet', 'calm', 'drift', 'meaning drift')",
        block,
    )

    out = qa(ws, adapter, capsys)

    assert findings(ws) == [(block, "open_tk"), (block, "unresolved_finding")]
    assert "TK-9" in out
    assert "meaning drift" in out


def test_failed_qa_blocks_the_build_and_status_names_the_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter)
    block = source_ids()[1]
    with sqlite3.connect(ws / "book.sqlite") as db:
        require_qa_clean(db)  # a clean book may be built
    set_target(ws, block, "")
    qa(ws, adapter, capsys)

    with sqlite3.connect(ws / "book.sqlite") as db, pytest.raises(QAFailedError, match="QA"):
        require_qa_clean(db)
    main(["status", str(ws)])
    out = capsys.readouterr().out
    assert "Stage: qa (failed)" in out
    assert f"[omission] {block}" in out
    assert "Next: fix the QA findings" in out

    set_target(ws, block, "It was a quiet evening.")
    qa(ws, adapter, capsys)
    with sqlite3.connect(ws / "book.sqlite") as db:
        require_qa_clean(db)  # fixed text passes again


def test_the_length_band_is_configurable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter, "--qa-length-band", "0.1", "9")
    set_target(ws, source_ids()[1], "It was a quiet evening. " * 8)

    qa(ws, adapter, capsys)

    assert findings(ws) == []


def test_a_waived_finding_no_longer_blocks_the_build_and_is_still_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter)
    block = source_ids()[1]
    set_target(ws, block, "")
    qa(ws, adapter, capsys)

    main(["waive", str(ws), "omission", block, "--reason", "left empty on purpose"])
    waived = capsys.readouterr().out
    out = qa(ws, adapter, capsys)  # QA runs again and keeps honouring the waiver

    with sqlite3.connect(ws / "book.sqlite") as db:
        require_qa_clean(db)
    assert "1 finding(s) accepted" in waived
    assert "QA: passed" in out and "1 accepted" in out
    assert f"[omission] {block}" in out and "left empty on purpose" in out
    assert findings(ws) == []
    main(["status", str(ws)])
    assert "Stage: qa (done)" in capsys.readouterr().out


def test_a_waiver_only_covers_the_text_that_was_looked_at(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter, "--qa-length-band", "0.1", "2")
    block = source_ids()[1]
    set_target(ws, block, "It was a quiet evening. " * 8)
    qa(ws, adapter, capsys)
    main(["waive", str(ws), "length_ratio", block])
    qa(ws, adapter, capsys)
    assert findings(ws) == []

    set_target(ws, block, "It was a quiet evening, again. " * 8)  # changed after the waiver
    qa(ws, adapter, capsys)

    assert findings(ws) == [(block, "length_ratio")]


def test_only_an_open_finding_can_be_waived(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = CountingAdapter()
    ws = translate(tmp_path, adapter)

    with pytest.raises(SystemExit) as stopped:
        main(["waive", str(ws), "omission", source_ids()[1]])

    message = str(stopped.value)
    assert "no open omission finding" in message and source_ids()[1] in message
