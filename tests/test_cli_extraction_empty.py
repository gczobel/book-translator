"""Seam 1: the CLI. S0 extraction skips a chapter that holds no text."""

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from book_translator import main
from book_translator.llm import LLMRequest, RawAnswer
from test_cli_evaluate import make_epub

COVER = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Cover</title></head>'
    b'<body><h1 class="oculto" title="Cover"></h1><div><img src="cover.jpg" alt=""/></div>'
    b"</body></html>"
)


def epub_with_a_cover(tmp_path: Path) -> Path:
    """Chapter 1 is a cover: an empty hidden heading and an image, no text at all."""
    plain = make_epub(
        tmp_path / "plain.epub", [("Cover", []), ("One", ["It was a quiet evening."])]
    )
    covered = tmp_path / "covered.epub"
    with zipfile.ZipFile(plain) as src, zipfile.ZipFile(covered, "w") as out:
        for item in src.infolist():
            out.writestr(item, COVER if item.filename.endswith("c0.xhtml") else src.read(item))
    return covered


class ExtractionOnly:
    """Answers extraction and records its requests; any later stage ends the run."""

    def __init__(self) -> None:
        self.extractions: list[LLMRequest] = []

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage != "extraction":
            raise KeyboardInterrupt
        self.extractions.append(request)
        return RawAnswer(json.dumps({"names": ["Ann"], "places": [], "phrases": []}))


def test_a_chapter_with_no_text_is_not_sent_to_the_model(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    main(["init", str(epub_with_a_cover(tmp_path)), "--workspace", str(ws), "--variety", "neutral"])
    adapter = ExtractionOnly()

    with pytest.raises((KeyboardInterrupt, SystemExit)):
        main(["run", str(ws)], adapter=adapter)

    assert len(adapter.extractions) == 1  # the real chapter only
    assert "quiet evening" in adapter.extractions[0].source_text
    with sqlite3.connect(ws / "book.sqlite") as db:
        rows = db.execute("select chapter from extractions order by chapter").fetchall()
    assert rows == [(0,), (1,)]  # the cover has a result too, an empty one
