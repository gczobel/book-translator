"""Seam 1: the CLI. Each review file has a read-only HTML view next to it."""

import html
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from book_translator import main
from test_cli_bible_part2 import EPUB, Part2Adapter, part2

YAML = "analysis-review.yaml"
HTML = "analysis-review.html"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(path), "--variety", "neutral"])
    main(["run", str(path)], adapter=Part2Adapter([json.dumps(part2())]))
    return path


def cards(ws: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = yaml.safe_load((ws / YAML).read_text())["cards"]
    return result


def test_the_gate_writes_an_html_view_showing_every_card(ws: Path) -> None:
    page = html.unescape((ws / HTML).read_text())

    assert cards(ws)
    for card in cards(ws):
        for field in ("question", "recommended", "why"):
            assert card[field] in page
        assert card["context"] in page
        for option in card["options"]:
            assert option in page
