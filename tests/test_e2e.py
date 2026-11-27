"""Seam 1, end to end: `init -> run -> approve -> run -> approve -> run -> export` through `main`.

A small synthetic EPUB, a replay-style adapter (no network, no paid API) and a fake epubcheck.
Select with `pytest -m e2e`.
"""

import json
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from lxml import etree

from book_translator import main
from book_translator.epub import open_epub
from book_translator.llm import LLMRequest, RawAnswer
from book_translator.replay import ReplayAdapter
from test_cli_export import fake_epubcheck
from test_cli_polish import PolishAdapter
from test_cli_run import recordings

pytestmark = pytest.mark.e2e

SOURCE = Path(__file__).parent / "fixtures" / "epub" / "e2e.epub"
BRANDING_IMAGE = "OEBPS/images/EPL_logo.png"
DC = "{http://purl.org/dc/elements/1.1/}"

SPANISH = {
    "One": "Uno",
    "Two": "Dos",
    "It was a quiet evening in the old house.": "Era una tarde tranquila en la vieja casa.",
    '"Who is there?" asked Hiram. "Nobody," said the voice.': (
        "«¿Quién anda ahí?», preguntó Hiram. «Nadie», dijo la voz."
    ),
    'Born in the town.<pc id="1">[1]</pc>': 'Nació en el pueblo.<pc id="1">[1]</pc>',
    "The morning came slowly.": "La mañana llegó despacio.",
    'The next day was <pc id="1">loud</pc>.': 'El día siguiente fue <pc id="1">ruidoso</pc>.',
    "Nobody remembered the voice.": "Nadie recordó la voz.",
}
# Every replayed call costs $0.0105 (1000 input and 500 output tokens at the sonnet price).
TOKENS = (1000, 500)


class E2EAdapter(PolishAdapter):
    """Replays recorded extractions and a recorded translation; counts calls; never networks."""

    def __init__(self, fail_after: int | None = None, tokens: tuple[int, int] = (0, 0)) -> None:
        super().__init__()
        self._extractions = ReplayAdapter(recordings(SOURCE))
        self.made = 0
        self._stop_after = fail_after
        self._tokens = tokens

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if self._stop_after is not None and self.made >= self._stop_after:
            raise KeyboardInterrupt
        self.made += 1
        if request.stage == "extraction":
            answer = self._extractions.complete(request, key, attempt)
        elif request.stage == "draft":
            passage = json.loads(request.source_text)["passage"]
            blocks = [{"source": b["id"], "targets": [SPANISH[b["text"]]]} for b in passage]
            answer = RawAnswer(json.dumps({"blocks": blocks}))
        else:
            answer = super().complete(request, key, attempt)
        return RawAnswer(answer.text, *self._tokens)


def init(tmp_path: Path, *extra: str) -> Path:
    ws = tmp_path / "ws"
    main(["init", str(SOURCE), "--workspace", str(ws), "--variety", "neutral", *extra])
    return ws


def pipeline(ws: Path, adapter: E2EAdapter) -> None:
    """run, approve the analysis gate, run, approve the TK gate, run."""
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=adapter)


def rows(ws: Path, sql: str) -> list[tuple[object, ...]]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        return db.execute(sql).fetchall()


def status(ws: Path, capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    main(["status", str(ws)])
    return capsys.readouterr().out


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A paid or networked call would need a key or a socket; neither is available here."""
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr("socket.socket.connect", refuse)
    yield


@pytest.fixture
def exported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    fake_epubcheck(tmp_path, monkeypatch)
    ws = init(tmp_path)
    pipeline(ws, E2EAdapter())
    main(["export", str(ws)])
    return ws, ws / "ws.es.epub"


def element_attributes(data: bytes) -> list[tuple[str, str | None, str | None]]:
    root = etree.fromstring(data)
    return [
        (etree.QName(e).localname, e.get("id"), e.get("class"))
        for e in root.iter()
        if isinstance(e.tag, str) and (e.get("id") or e.get("class"))
    ]


def test_the_output_passes_epubcheck_and_keeps_files_ids_and_classes(
    exported: tuple[Path, Path],
) -> None:
    ws, out = exported
    with zipfile.ZipFile(SOURCE) as src, zipfile.ZipFile(out) as dst:
        # The only difference in files is the removed branding image.
        assert set(dst.namelist()) == set(src.namelist()) - {BRANDING_IMAGE}
        for name in ("OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml", "OEBPS/notes.xhtml"):
            before = element_attributes(src.read(name))
            after = element_attributes(dst.read(name))
            for pair in before:
                after.remove(pair)  # every source id and class is still there
            # What is left is the block the raya split added: it keeps the class, no id.
            assert after == ([("p", None, "speech")] if name.endswith("ch1.xhtml") else [])
    assert "No errors" in (ws / "epubcheck-report.txt").read_text()


def test_every_block_is_translated_and_the_speech_is_split_by_raya(
    exported: tuple[Path, Path],
) -> None:
    _, out = exported
    source_blocks = [
        b for c in open_epub(SOURCE).book().chapters for s in c.scenes for b in s.blocks
    ]
    translated = [b for c in open_epub(out).book().chapters for s in c.scenes for b in s.blocks]
    texts = {b.text for b in translated}

    assert not texts & {b.text for b in source_blocks}  # no source text is left
    assert len(translated) == len(source_blocks) + 1  # the two-turn speech became two blocks
    assert "—¿Quién anda ahí? —preguntó Hiram." in texts
    assert "—Nadie —dijo la voz." in texts
    assert "La mañana llegó despacio." in texts


def test_the_synchronized_edits_are_applied(exported: tuple[Path, Path]) -> None:
    _, out = exported
    with zipfile.ZipFile(out) as z:
        opf = etree.fromstring(z.read("OEBPS/content.opf"))
        ncx = z.read("OEBPS/toc.ncx").decode()
        chapter = z.read("OEBPS/ch1.xhtml").decode()
        credits = z.read("OEBPS/credits.xhtml").decode()
        everything = "".join(  # the credits page names the source edition, branding included
            z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n != "OEBPS/credits.xhtml"
        )
        names = z.namelist()
    assert opf.findtext(f".//{DC}language") == "es"
    assert 'xml:lang="es"' in chapter and 'xml:lang="en"' not in chapter
    assert "Uno" in ncx and "Dos" in ncx
    assert "<text>One</text>" not in ncx
    assert "Synthetic Tale" in credits and "book-translator" in credits  # the credits page
    assert "Copyright Nobody" not in credits  # replaced, not kept
    assert BRANDING_IMAGE not in names
    assert "ePubLibre" not in everything and "EPL_logo" not in everything


def test_review_files_are_produced_and_a_bad_edit_is_refused(tmp_path: Path) -> None:
    ws = init(tmp_path)
    adapter = E2EAdapter()
    main(["run", str(ws)], adapter=adapter)
    review = ws / "analysis-review.yaml"
    assert (ws / "analysis-review.html").is_file()
    cards = yaml.safe_load(review.read_text())["cards"]
    assert {"variety", "dialogue"} <= {c["id"] for c in cards}

    review.write_text(review.read_text().replace("choice: null", "choice: martian", 1))
    with pytest.raises(SystemExit) as refused:
        main(["approve", str(ws)])
    assert "martian" in str(refused.value) or "line" in str(refused.value)
    assert not (ws / "tk-review.yaml").exists()  # the gate did not pass

    review.write_text(review.read_text().replace("choice: martian", "choice: null", 1))
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=adapter)
    tk_review = yaml.safe_load((ws / "tk-review.yaml").read_text())
    assert tk_review["cards"] == []
    assert (ws / "tk-review.html").is_file()


def test_an_interrupted_run_resumes_without_repeating_calls(tmp_path: Path) -> None:
    whole = E2EAdapter()
    whole_ws = init(tmp_path / "whole")
    pipeline(whole_ws, whole)

    ws = init(tmp_path / "broken")
    first = E2EAdapter(fail_after=3)
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(ws)], adapter=first)
    second = E2EAdapter()
    pipeline(ws, second)

    assert first.made == 3
    assert first.made + second.made == whole.made
    assert rows(ws, "select count(*) from targets") == rows(
        whole_ws, "select count(*) from targets"
    )


def test_the_budget_guard_stops_at_the_cap_and_resumes_when_it_is_raised(tmp_path: Path) -> None:
    whole = E2EAdapter()
    pipeline(init(tmp_path / "whole"), whole)

    ws = init(tmp_path / "capped")
    first = E2EAdapter(tokens=TOKENS)
    with pytest.raises(SystemExit) as stop:
        main(["run", str(ws), "--cap", "0.015"], adapter=first)
    assert "cap" in str(stop.value).lower()
    assert first.made == 1

    blocked = E2EAdapter(tokens=TOKENS)
    with pytest.raises(SystemExit):
        main(["run", str(ws)], adapter=blocked)
    assert blocked.made == 0  # the cap is spent: no call is made

    second = E2EAdapter(tokens=TOKENS)
    main(["run", str(ws), "--cap", "10"], adapter=second)
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=second)
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=second)
    assert first.made + second.made == whole.made
    assert rows(ws, "select count(*) from spend") == [(whole.made,)]  # one row per call, none twice


def test_the_analysis_gate_can_be_skipped_but_the_tk_gate_always_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_epubcheck(tmp_path, monkeypatch)
    ws = init(tmp_path, "--skip-analysis-gate")
    adapter = E2EAdapter()

    main(["run", str(ws)], adapter=adapter)

    assert not (ws / "analysis-review.yaml").exists()
    assert "Review gate: tk is waiting" in status(ws, capsys)
    with pytest.raises(SystemExit):  # nothing is exported past the waiting TK gate
        main(["export", str(ws)])
    assert not list(ws.glob("*.es.epub"))

    main(["run", str(ws)], adapter=adapter)  # running again does not pass the gate
    assert "Review gate: tk is waiting" in status(ws, capsys)

    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=adapter)
    main(["export", str(ws)])
    assert (ws / "ws.es.epub").is_file()


def test_the_long_stages_report_progress_per_passage_and_scene(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = init(tmp_path)
    capsys.readouterr()

    pipeline(ws, E2EAdapter(tokens=TOKENS))

    lines = capsys.readouterr().err.splitlines()
    for stage in ("draft", "fidelity", "polish", "post_polish_fidelity"):
        counted = [x for x in lines if x.startswith(f"[{stage}]") and "/" in x]
        assert counted, stage
        total = counted[-1].split("/")[1].split()[0]
        assert f"{total}/{total}" in counted[-1]
        assert " of $" in counted[-1]  # the spend so far against the cap
    for stage in ("tk_resolution", "typography", "qa"):
        assert any(x.startswith(f"[{stage}]") and "start" in x for x in lines)
        assert any(x.startswith(f"[{stage}]") and "done" in x for x in lines)
