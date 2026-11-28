"""Seam 1: the CLI. The review page is interactive, self-contained and safe with book text."""

import json
import re
from pathlib import Path
from typing import Any

from book_translator import main
from test_cli_bible_part2 import EPUB, Part2Adapter, part2
from test_cli_draft import tk
from test_cli_resolve import ResolveAdapter
from test_cli_tk_gate import stopped_at_gate, unsure


def embedded(page: str) -> dict[str, Any]:
    match = re.search(r'<script type="application/json" id="review-data">(.*?)</script>', page)
    assert match
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def test_the_tk_page_embeds_its_cards_and_the_controls_of_the_interactive_page(
    tmp_path: Path,
) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))

    page = (ws / "tk-review.html").read_text()

    (card,) = embedded(page)["cards"]
    assert card["id"] == "TK-1"
    assert card["free_text"] is True
    assert card["recommended"] == "tarde tranquila"
    for control in ('id="prev"', 'id="next"', 'id="copy"', 'id="download"', "choices.json"):
        assert control in page
    assert 'name="viewport"' in page
    assert "prefers-color-scheme:dark" in page


def test_the_page_makes_no_external_request(tmp_path: Path) -> None:
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk()], unsure))

    page = (ws / "tk-review.html").read_text()

    assert not re.search(r"https?://", page)
    assert not re.search(r"<(link|img|iframe)\b|src=|@import", page)


def test_card_text_cannot_break_out_of_the_embedded_data(tmp_path: Path) -> None:
    hostile = '</script><img src=x onerror=alert(1)> & "q"'
    ws = stopped_at_gate(tmp_path, ResolveAdapter([tk(excerpt=hostile)], unsure))

    page = (ws / "tk-review.html").read_text()

    assert "<img" not in page
    assert page.count("</script>") == 2
    (card,) = embedded(page)["cards"]
    assert card["excerpt"] == hostile


def test_the_analysis_page_marks_which_cards_take_free_text(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    main(["run", str(ws)], adapter=Part2Adapter([json.dumps(part2())]))

    cards = embedded((ws / "analysis-review.html").read_text())["cards"]

    free = {c["id"].split("-")[0] for c in cards if c["free_text"]}
    fixed = {c["id"].split("-")[0] for c in cards if not c["free_text"]}
    assert free <= {"name", "glossary", "motif"}
    assert {"variety", "dialogue", "thoughts"} <= fixed


def test_the_page_has_no_innerhtml_so_card_text_is_never_parsed_as_markup() -> None:
    from book_translator.review_page import SCRIPT

    assert "innerHTML" not in SCRIPT
    assert "outerHTML" not in SCRIPT
    assert "insertAdjacentHTML" not in SCRIPT


def test_the_page_builder_escapes_its_title_itself() -> None:
    from book_translator.review_page import interactive

    page = interactive("<img src=x>", {"cards": []}, "")

    assert "<img" not in page


def test_a_hostile_gate_name_is_escaped_in_the_page_title_and_heading(tmp_path: Path) -> None:
    from book_translator.review_html import write_html

    review = tmp_path / "x-review.yaml"
    review.write_text('gate: "<img src=x onerror=alert(1)>"\ncards: []\n')

    write_html(review)

    page = review.with_suffix(".html").read_text()
    assert "<img" not in page
    assert "&lt;img" in page
    assert "&amp;lt;" not in page  # escaped once, not twice
