"""Seam 1: the CLI. S8 deterministic QA checks, reported through `run` and `status`."""

import sqlite3
from pathlib import Path

import pytest

from book_translator import main
from book_translator.llm import LLMRequest, RawAnswer
from test_cli_bible_part2 import EPUB
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
    try:
        main(["run", str(ws)], adapter=adapter)
    except SystemExit:
        pass
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
