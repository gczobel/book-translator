"""Seam 1: the CLI. S6 blind polish observed in the workspace database and the LLM requests."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from book_translator.epub import open_epub
from book_translator.llm import LLMRequest, RawAnswer
from test_cli_bible_part2 import EPUB
from test_cli_draft import scenes, source_ids
from test_cli_fidelity import FidelityAdapter, no_edits, query, target_text

Polisher = Callable[[dict[str, Any], int], dict[str, Any]]


def unchanged(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
    return {
        "blocks": [
            {"id": b["id"], "texts": [t["text"] for t in b["targets"]]} for b in scene["scene"]
        ]
    }


def rewriting(block: str, answers: list[list[str]]) -> Polisher:
    """For the scene holding `block`, its texts `answers[attempt]`; other scenes are unchanged."""

    def polish(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
        answer = unchanged(scene, attempt)
        for entry in answer["blocks"]:
            if entry["id"] == block:
                entry["texts"] = answers[attempt]
        return answer

    return polish


class PolishAdapter(FidelityAdapter):
    """The fidelity adapter plus a polisher answering `polish(scene, attempt)` per scene."""

    def __init__(self, polish: Polisher = unchanged, **bible: object) -> None:
        super().__init__(no_edits, **bible)
        self.polish = polish
        self.polish_requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage != "polish":
            return super().complete(request, key, attempt)
        if attempt == 0:
            self.polish_requests.append(request)
        return RawAnswer(json.dumps(self.polish(json.loads(request.source_text), attempt)))


def run_to_the_end(tmp_path: Path, adapter: PolishAdapter) -> Path:
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])  # analysis gate
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])  # TK gate
    main(["run", str(ws)], adapter=adapter)
    return ws


def test_a_polished_block_replaces_its_target_and_is_recorded(tmp_path: Path) -> None:
    block = source_ids()[1]
    adapter = PolishAdapter(rewriting(block, [["It was a quiet, still evening."]]))

    ws = run_to_the_end(tmp_path, adapter)

    assert target_text(ws, block) == "It was a quiet, still evening."
    assert query(ws, "select stage, block, position, old, new from polish_edits") == [
        ("polish", block, 0, "It was a quiet evening.", "It was a quiet, still evening.")
    ]


def test_the_polisher_is_given_target_text_only(tmp_path: Path) -> None:
    adapter = PolishAdapter()

    run_to_the_end(tmp_path, adapter)

    assert adapter.polish_requests
    for request in adapter.polish_requests:
        scene = json.loads(request.source_text)
        assert set(scene) == {"scene"}
        for entry in scene["scene"]:
            assert set(entry) == {"id", "targets"}
            assert all(set(t) == {"position", "text"} for t in entry["targets"])


def test_a_polish_that_varies_a_locked_motif_is_retried(tmp_path: Path) -> None:
    block = source_ids()[1]
    answers = [["It was a calm night."], ["It was a quiet evening, still."]]
    motifs = [{"name": "quiet evening", "locked_rendering": "quiet evening"}]

    ws = run_to_the_end(tmp_path, PolishAdapter(rewriting(block, answers), motifs=motifs))

    assert target_text(ws, block) == "It was a quiet evening, still."


def test_a_polish_that_changes_a_glossary_rendering_or_adds_a_banned_variant_is_retried(
    tmp_path: Path,
) -> None:
    block = source_ids()[1]
    glossary = [
        {
            "term": "evening",
            "rendering": "evening",
            "banned_variants": ["dusk"],
            "origin": "extracted",
        }
    ]
    answers = [["It was a quiet night."], ["It was a quiet dusk."], ["It was a calm evening."]]

    ws = run_to_the_end(tmp_path, PolishAdapter(rewriting(block, answers), glossary=glossary))

    assert target_text(ws, block) == "It was a calm evening."


def test_a_polish_that_breaks_inline_codes_is_retried(tmp_path: Path) -> None:
    source = open_epub(EPUB)
    marked = next(i for i in source_ids() if '<pc id="1">' in source.encode_block(i).text)
    text = source.encode_block(marked).text
    answers = [[text.replace('<pc id="1">', "")], [text + " Mas."]]

    ws = run_to_the_end(tmp_path, PolishAdapter(rewriting(marked, answers)))

    assert target_text(ws, marked) == text + " Mas."


def test_a_polish_that_splits_a_block_or_drops_one_is_retried(tmp_path: Path) -> None:
    block = source_ids()[1]
    answers = [["It was a quiet", "evening."], ["It was a quiet evening, truly."]]

    ws = run_to_the_end(tmp_path, PolishAdapter(rewriting(block, answers)))

    assert target_text(ws, block) == "It was a quiet evening, truly."
    assert query(ws, f"select count(*) from targets where source = '{block}'") == [(1,)]


def test_a_polish_that_drops_a_block_of_the_scene_is_retried(tmp_path: Path) -> None:
    def polish(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
        answer = unchanged(scene, attempt)
        if attempt == 0:
            answer["blocks"] = answer["blocks"][1:]
        return answer

    ws = run_to_the_end(tmp_path, PolishAdapter(polish))

    assert query(ws, "select count(*) from polish_edits") == [(0,)]
    assert query(ws, "select count(*) from polished_scenes") == [(len(scenes()),)]


def test_a_finished_polish_is_not_run_again_and_calls_are_not_repeated(tmp_path: Path) -> None:
    adapter = PolishAdapter()
    ws = run_to_the_end(tmp_path, adapter)
    calls = len(adapter.polish_requests)
    assert calls > 0

    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.polish_requests) == calls


def test_polish_resumes_without_repeating_finished_scenes(tmp_path: Path) -> None:
    seen: list[str] = []

    def interrupt_on_second(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
        seen.append(scene["scene"][0]["id"])
        if len(seen) == 2:
            raise KeyboardInterrupt
        return unchanged(scene, attempt)

    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    adapter = PolishAdapter(interrupt_on_second)
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(ws)], adapter=adapter)
    assert len(query(ws, "select * from polished_scenes")) == 1

    resumed = PolishAdapter()
    main(["run", str(ws)], adapter=resumed)

    starts = [s[0] for s in scenes()]
    asked = [json.loads(r.source_text)["scene"][0]["id"] for r in resumed.polish_requests]
    assert asked == [s for s in starts if s != seen[0]]


def test_polish_uses_the_model_configured_for_it(tmp_path: Path) -> None:
    adapter = PolishAdapter()

    run_to_the_end(tmp_path, adapter)

    assert {r.model for r in adapter.polish_requests} == {"anthropic:claude-sonnet-5-5"}
