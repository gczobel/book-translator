"""Seam 1: the CLI. `evaluate` compares the exported EPUB with a reference translation and
writes a quality report. Embeddings are a deterministic fake; no model is ever loaded."""

import json
import math
import sqlite3
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from test_cli_draft import source_ids
from test_cli_export import fake_epubcheck
from test_cli_qa import CountingAdapter, set_target, translate

REPORT = "quality-report.json"


class FakeEmbedder:
    """A hashed bag of words: texts sharing words are close, whatever the language."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * 64
            for word in text.lower().split():
                vec[sum(ord(c) * 31**i for i, c in enumerate(word)) % 64] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


def make_epub(path: Path, chapters: Sequence[tuple[str, Sequence[str]]]) -> Path:
    """A tiny synthetic EPUB 2: one file per chapter, an h1 title and one <p> per paragraph."""
    items = "".join(
        f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(len(chapters))
    )
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    points = "".join(
        f'<navPoint id="n{i}" playOrder="{i + 1}"><navLabel><text>{title}</text></navLabel>'
        f'<content src="c{i}.xhtml"/></navPoint>'
        for i, (title, _) in enumerate(chapters)
    )
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="b">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Ref</dc:title>'
        '<dc:language>es</dc:language><dc:identifier id="b">urn:uuid:1</dc:identifier>'
        '</metadata><manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        f'{items}</manifest><spine toc="ncx">{spine}</spine></package>'
    )
    ncx = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        '<head><meta name="dtb:uid" content="urn:uuid:1"/></head>'
        f"<docTitle><text>Ref</text></docTitle><navMap>{points}</navMap></ncx>"
    )
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="content.opf"'
        ' media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("content.opf", opf)
        z.writestr("toc.ncx", ncx)
        for i, (title, paragraphs) in enumerate(chapters):
            body = f"<h1>{title}</h1>" + "".join(f"<p>{p}</p>" for p in paragraphs)
            z.writestr(
                f"c{i}.xhtml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head>'
                f"<body>{body}</body></html>",
            )
    return path


OURS = {
    1: ("Era una tarde tranquila en la vieja casa.", "Ella no dijo nada a nadie."),
    2: ("La mañana siguiente fue muy ruidosa.", "Fin."),
}


def set_all_targets(ws: Path) -> None:
    """Chapter 1 holds the plain fixture's blocks #1 and #2, chapter 2 its #1 and #3."""
    ids = source_ids()
    texts = (*OURS[1], OURS[2][0].replace("muy ruidosa", '<pc id="1">muy ruidosa</pc>'), OURS[2][1])
    for block, text in zip((ids[1], ids[2], ids[5], ids[6]), texts, strict=True):
        set_target(ws, block, text)


@pytest.fixture
def exported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_epubcheck(tmp_path, monkeypatch)
    ws = translate(tmp_path, CountingAdapter())
    set_all_targets(ws)
    main(["run", str(ws)], adapter=CountingAdapter())
    main(["export", str(ws)])
    return ws


def evaluate(ws: Path, reference: Path, embedder: FakeEmbedder | None = None) -> dict[str, Any]:
    main(["evaluate", str(ws), "--reference", str(reference)], embedder=embedder or FakeEmbedder())
    report: dict[str, Any] = json.loads((ws / REPORT).read_text())
    return report


def test_a_fixture_pair_gets_a_chrf_score_per_chapter(exported: Path, tmp_path: Path) -> None:
    ref = make_epub(
        tmp_path / "ref.epub",
        [
            ("One", [*OURS[1]]),
            ("Two", ["La mañana siguiente fue muy ruidosa.", "El fin."]),
        ],
    )

    report = evaluate(exported, ref)

    first, second = report["chapters"]
    assert first["chrf"] == 100.0
    assert 40.0 < second["chrf"] < 100.0


def test_a_reference_that_splits_paragraphs_still_scores_full(
    exported: Path, tmp_path: Path
) -> None:
    ref = make_epub(
        tmp_path / "ref.epub",
        [
            (
                "One",
                [
                    "Era una tarde",
                    "tranquila en la vieja casa.",
                    "Ella no dijo",
                    "nada",
                    "a nadie.",
                ],
            ),
            ("Two", ["La mañana siguiente fue muy ruidosa.", "Fin."]),
        ],
    )

    report = evaluate(exported, ref)

    assert [c["chrf"] for c in report["chapters"]] == [100.0, 100.0]
    assert report["chapters"][0]["aligned_blocks"] == 3


def test_a_reference_with_other_chapter_splits_is_aligned_by_order_and_size(
    exported: Path, tmp_path: Path
) -> None:
    ref = make_epub(
        tmp_path / "ref.epub",
        [
            ("One", [*OURS[1]]),
            ("Two", [OURS[2][0]]),
            ("Two, continued", [OURS[2][1]]),
        ],
    )

    report = evaluate(exported, ref)

    first, second = report["chapters"]
    assert first["reference_titles"] == ["One"]
    assert second["reference_titles"] == ["Two", "Two, continued"]
    assert second["chrf"] > 70.0  # only the extra heading is missing from our side
    assert report["unaligned_reference_chapters"] == []


def test_a_worse_translation_scores_lower_than_a_closer_one(exported: Path, tmp_path: Path) -> None:
    close = make_epub(tmp_path / "close.epub", [("One", [*OURS[1]]), ("Two", [*OURS[2]])])
    far = make_epub(
        tmp_path / "far.epub",
        [("One", ["Fue una noche serena.", "Callo ella."]), ("Two", ["Al alba hubo gritos."])],
    )

    assert evaluate(exported, close)["chrf_overall"] == 100.0
    assert evaluate(exported, far)["chrf_overall"] < 50.0


def test_the_report_lists_qa_failures_cost_and_what_each_stage_changed(
    exported: Path, tmp_path: Path
) -> None:
    with sqlite3.connect(exported / "book.sqlite") as db:
        db.execute("delete from spend")
        db.executemany(
            "insert into spend (stage, cost_usd) values (?, ?)",
            [("draft", 0.25), ("draft", 0.5), ("polish", 0.125)],
        )
        db.execute(
            "insert into qa_findings (check_name, block, message) values ('glossary', 'b1', 'x')"
        )
        for _ in range(2):
            db.execute(
                "insert into fidelity_edits (block, position, old, new, reason, category)"
                " values ('b', 0, 'a', 'b', 'r', 'omission')"
            )
        db.execute(
            "insert into polish_edits (stage, block, position, old, new)"
            " values ('polish', 'b', 0, 'a', 'b')"
        )
        db.execute(
            "insert into typography_changes (block, position, rule, old, new)"
            " values ('b', 0, 'quotes', 'a', 'b')"
        )
    ref = make_epub(tmp_path / "ref.epub", [("One", [*OURS[1]]), ("Two", [*OURS[2]])])

    report = evaluate(exported, ref)

    assert report["qa"]["passed"] is False
    assert report["qa"]["findings"] == [{"check": "glossary", "block": "b1", "message": "x"}]
    assert report["cost"] == {"total_usd": 0.875, "by_stage": {"draft": 0.75, "polish": 0.125}}
    assert report["stage_changes"] == {"fidelity": 2, "polish": 1, "typography": 1}
    readable = (exported / "quality-report.md").read_text()
    assert "[glossary] b1: x" in readable
    assert "Total: $0.88" in readable


def test_evaluating_before_export_says_to_export_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_epubcheck(tmp_path, monkeypatch)
    ws = translate(tmp_path, CountingAdapter())
    ref = make_epub(tmp_path / "ref.epub", [("One", [*OURS[1]])])

    with pytest.raises(SystemExit) as stop:
        main(["evaluate", str(ws), "--reference", str(ref)], embedder=FakeEmbedder())

    assert "export" in str(stop.value)
    assert not (ws / REPORT).exists()


def test_a_reference_that_is_not_an_epub_is_refused(exported: Path, tmp_path: Path) -> None:
    junk = tmp_path / "ref.epub"
    junk.write_text("not a zip")

    with pytest.raises(SystemExit) as stop:
        main(["evaluate", str(exported), "--reference", str(junk)], embedder=FakeEmbedder())

    assert "ref.epub" in str(stop.value)


def test_without_the_optional_model_package_the_error_says_how_to_get_it(
    exported: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # the import fails
    ref = make_epub(tmp_path / "ref.epub", [("One", [*OURS[1]])])

    with pytest.raises(SystemExit) as stop:
        main(["evaluate", str(exported), "--reference", str(ref)])

    assert "sentence-transformers" in str(stop.value)
    assert "--extra evaluate" in str(stop.value)


def test_no_translation_stage_can_see_the_reference() -> None:
    """ADR 0004: only the CLI wires `evaluate`; nothing else in the package imports it."""
    src = Path(__file__).parent.parent / "src" / "book_translator"
    wired = {src / "cli.py", src / "__init__.py"}
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if src / "evaluate" not in path.parents
        and path not in wired
        and "book_translator.evaluate" in path.read_text()
    ]
    assert offenders == []


class FakeComet:
    """Scores each segment by how many words ours and the reference share; records what it got."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str, str]] = []

    def score(self, triples: Sequence[tuple[str, str, str]]) -> list[float]:
        self.seen = list(triples)
        return [
            len(set(hyp.split()) & set(ref.split())) / max(len(set(ref.split())), 1)
            for _, hyp, ref in triples
        ]


class GlossEmbedder(FakeEmbedder):
    """The fake embedder with a few Spanish words mapped to their English twins, so a source
    block and its translation are close, as LaBSE makes them."""

    TWINS = {
        "tarde": "evening",
        "tranquila": "quiet",
        "ella": "she",
        "dijo": "said",
        "nada": "nothing",
        "mañana": "morning",
        "siguiente": "next",
        "ruidosa": "loud",
        "fue": "was",
        "era": "was",
        "una": "a",
    }

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        def twin(text: str) -> str:
            words = [w.strip(".,;:!?") for w in text.lower().split()]
            return " ".join(self.TWINS.get(w, w) for w in words)

        return super().embed([twin(t) for t in texts])


def evaluate_with_comet(ws: Path, reference: Path, comet: FakeComet) -> dict[str, Any]:
    main(
        ["evaluate", str(ws), "--reference", str(reference), "--comet"],
        embedder=GlossEmbedder(),
        comet=comet,
    )
    report: dict[str, Any] = json.loads((ws / REPORT).read_text())
    return report


def test_comet_scores_each_aligned_segment_against_its_source_and_reference(
    exported: Path, tmp_path: Path
) -> None:
    ref = make_epub(
        tmp_path / "ref.epub",
        [("One", [*OURS[1]]), ("Two", ["La mañana siguiente fue muy ruidosa.", "El fin."])],
    )
    comet = FakeComet()

    report = evaluate_with_comet(exported, ref, comet)

    assert comet.seen, "COMET was given nothing"
    assert all(src and hyp and reference for src, hyp, reference in comet.seen)
    assert any(src.startswith("It was a quiet evening") for src, _, _ in comet.seen)
    first, second = report["chapters"]
    assert first["comet"] == 1.0 and 0.0 < second["comet"] < 1.0
    assert report["comet_segments"] == len(comet.seen)
    mean = sum(comet.score(comet.seen)) / len(comet.seen)
    assert report["comet_overall"] == pytest.approx(mean, abs=1e-3)
    readable = (exported / "quality-report.md").read_text()
    assert "COMET overall:" in readable and "COMET 1.0" in readable
    assert "not to judge one sentence" in readable


def test_without_the_comet_flag_nothing_is_scored_and_the_report_has_no_comet(
    exported: Path, tmp_path: Path
) -> None:
    ref = make_epub(tmp_path / "ref.epub", [("One", [*OURS[1]]), ("Two", [*OURS[2]])])
    comet = FakeComet()

    main(
        ["evaluate", str(exported), "--reference", str(ref)],
        embedder=FakeEmbedder(),
        comet=comet,
    )

    assert comet.seen == []
    report = json.loads((exported / REPORT).read_text())
    assert "comet_overall" not in report
    assert "comet" not in report["chapters"][0]


def test_a_comet_that_cannot_start_stops_with_a_clear_message(
    exported: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = make_epub(tmp_path / "ref.epub", [("One", [*OURS[1]]), ("Two", [*OURS[2]])])
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))

    with pytest.raises(SystemExit) as stopped:
        main(
            ["evaluate", str(exported), "--reference", str(ref), "--comet"],
            embedder=FakeEmbedder(),
        )

    assert "needs `uv`" in str(stopped.value)
