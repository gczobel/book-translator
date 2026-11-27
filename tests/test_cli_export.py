"""Seam 1: the CLI. `export` builds the translated EPUB, runs epubcheck and writes both."""

import stat
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from book_translator import main
from test_cli_draft import source_ids
from test_cli_qa import CountingAdapter, set_target, tamper, translate

DC = "{http://purl.org/dc/elements/1.1/}"


def fake_epubcheck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, passes: bool = True) -> Path:
    """An executable standing in for epubcheck, pointed at through EPUBCHECK."""
    script = tmp_path / "fake-epubcheck"
    if passes:
        body = 'echo "Validating $1"; echo "No errors or warnings detected."; exit 0'
    else:
        body = 'echo "ERROR(RSC-005): $1: invalid markup"; exit 1'
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("EPUBCHECK", str(script))
    return script


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return translate(tmp_path, CountingAdapter())


def test_export_refuses_while_qa_has_findings(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_epubcheck(tmp_path, monkeypatch)
    block = source_ids()[1]
    set_target(ws, block, "x" * 400)
    main(["run", str(ws)], adapter=CountingAdapter())

    with pytest.raises(SystemExit) as stop:
        main(["export", str(ws)])

    assert stop.value.code not in (0, None)
    assert [p.name for p in ws.glob("*.epub")] == ["source.epub"]


def test_export_refuses_while_a_tk_is_open(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_epubcheck(tmp_path, monkeypatch)
    tamper(
        ws,
        "insert into tks values ('TK-1', ?, 'x', 'pun', 'x', 'x', '[]', 'x', 0.1, 'book',"
        " null, null)",
        source_ids()[1],
    )

    with pytest.raises(SystemExit):
        main(["export", str(ws)])

    assert [p.name for p in ws.glob("*.epub")] == ["source.epub"]


def test_export_writes_the_translated_epub_and_the_report(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_epubcheck(tmp_path, monkeypatch)
    set_target(ws, source_ids()[1], "Era una tarde tranquila.")
    main(["run", str(ws)], adapter=CountingAdapter())

    main(["export", str(ws)])

    out = ws / "ws.es.epub"
    assert "No errors" in (ws / "epubcheck-report.txt").read_text()
    with zipfile.ZipFile(out) as z:
        chapter = z.read("OEBPS/ch1.xhtml").decode()
        opf = etree.fromstring(z.read("OEBPS/content.opf"))
        assert "OEBPS/credits.xhtml" in z.namelist()
        assert "Synthetic Tale" in z.read("OEBPS/credits.xhtml").decode()
    assert "Era una tarde tranquila." in chapter
    assert 'xml:lang="es"' in chapter
    assert opf.findtext(f".//{DC}language") == "es"


def test_a_failing_epubcheck_fails_the_command_and_prints_the_report(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_epubcheck(tmp_path, monkeypatch, passes=False)

    with pytest.raises(SystemExit) as stop:
        main(["export", str(ws)])

    assert stop.value.code not in (0, None)
    assert "RSC-005" in capsys.readouterr().out
    assert "RSC-005" in (ws / "epubcheck-report.txt").read_text()


def test_export_without_epubcheck_says_how_to_get_it(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EPUBCHECK", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")

    with pytest.raises(SystemExit) as stop:
        main(["export", str(ws)])

    assert "EPUBCHECK" in str(stop.value)
    assert [p.name for p in ws.glob("*.epub")] == ["source.epub"]


def test_the_target_language_setting_names_the_output_file(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_epubcheck(tmp_path, monkeypatch)
    tamper(ws, "update settings set value = 'ja' where key = 'target'")
    main(["export", str(ws)])
    assert (ws / "ws.ja.epub").is_file()


def test_the_translated_chapter_titles_reach_the_table_of_contents(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_epubcheck(tmp_path, monkeypatch)
    set_target(ws, source_ids()[0], "Uno")

    main(["export", str(ws)])

    with zipfile.ZipFile(ws / "ws.es.epub") as z:
        ncx = z.read("OEBPS/toc.ncx").decode()
    assert "<text>Uno</text>" in ncx
    assert "<text>One</text>" not in ncx


def test_export_with_a_jar_but_no_java_is_a_clear_error_not_a_traceback(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"")
    monkeypatch.setenv("EPUBCHECK", str(jar))
    monkeypatch.setenv("PATH", "/nonexistent")

    with pytest.raises(SystemExit) as stop:
        main(["export", str(ws)])

    assert str(stop.value).startswith("error:")
