"""Seam 1: the CLI. S5 fidelity check observed in the workspace database."""

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from book_translator import main
from book_translator.epub import open_epub
from book_translator.llm import LLMRequest, RawAnswer
from test_cli_bible_part2 import EPUB, part2
from test_cli_draft import scenes, source_ids
from test_cli_resolve import ResolveAdapter

Reviewer = Callable[[dict[str, Any], int], dict[str, Any]]


def no_edits(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
    return {"edits": []}


def edit(block: str, old: str, new: str, category: str = "meaning drift") -> dict[str, Any]:
    return {
        "block": block,
        "position": 0,
        "old": old,
        "new": new,
        "reason": "the source says otherwise",
        "category": category,
    }


def in_scene(scene: dict[str, Any], block: str) -> bool:
    return block in [b["id"] for b in scene["scene"]]


class FidelityAdapter(ResolveAdapter):
    """The resolve adapter plus a reviewer answering `review(scene, attempt)` per scene."""

    def __init__(self, review: Reviewer = no_edits, **bible: object) -> None:
        super().__init__([])
        self._completions = [json.dumps(part2(**bible))]
        self.review = review
        self.fidelity_requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if request.stage == "polish":  # covered in test_cli_polish.py; here, leave as it is
            scene = json.loads(request.source_text)["scene"]
            blocks = [{"id": b["id"], "texts": [t["text"] for t in b["targets"]]} for b in scene]
            return RawAnswer(json.dumps({"blocks": blocks}))
        if request.stage == "post_polish_fidelity":  # covered in test_cli_refidelity.py
            return RawAnswer(json.dumps({"edits": []}))
        if request.stage != "fidelity":
            return super().complete(request, key, attempt)
        if attempt == 0:
            self.fidelity_requests.append(request)
        scene = json.loads(request.source_text)
        return RawAnswer(json.dumps(self.review(scene, attempt)))


def run_to_the_end(tmp_path: Path, adapter: FidelityAdapter) -> Path:
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])  # analysis gate
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])  # TK gate
    main(["run", str(ws)], adapter=adapter)
    return ws


def query(ws: Path, sql: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(ws / "book.sqlite") as db:
        return db.execute(sql).fetchall()


def target_text(ws: Path, block: str) -> str:
    rows = query(ws, f"select text from targets where source = '{block}' order by position")
    return "\n".join(r[0] for r in rows)


def test_an_edit_is_applied_to_its_target_block_and_recorded(tmp_path: Path) -> None:
    block = source_ids()[1]

    def review(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
        return {"edits": [edit(block, "quiet", "calm")] if in_scene(scene, block) else []}

    ws = run_to_the_end(tmp_path, FidelityAdapter(review))

    assert target_text(ws, block) == "It was a calm evening."
    assert query(ws, "select block, position, old, new, category from fidelity_edits") == [
        (block, 0, "quiet", "calm", "meaning drift")
    ]


def answering(block: str, answers: list[dict[str, Any]]) -> Reviewer:
    """For the scene holding `block`, the edit `answers[attempt]`; other scenes need none."""

    def review(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
        return {"edits": [answers[attempt]] if in_scene(scene, block) else []}

    return review


def answering_all(block: str, answers: list[dict[str, Any]]) -> Reviewer:
    """For the scene holding `block`, all of `answers` in one answer; other scenes need none."""

    def review(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
        return {"edits": answers if in_scene(scene, block) else []}

    return review


def test_a_bad_edit_is_dropped_and_the_good_ones_of_the_same_answer_are_kept(
    tmp_path: Path,
) -> None:
    block = source_ids()[1]

    def review(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
        if not in_scene(scene, block):
            return {"edits": []}
        return {"edits": [edit(block, "not there", "x"), edit(block, "quiet", "calm")]}

    adapter = FidelityAdapter(review)
    ws = run_to_the_end(tmp_path, adapter)

    assert target_text(ws, block) == "It was a calm evening."
    assert query(ws, "select old, new from fidelity_edits") == [("quiet", "calm")]
    assert query(ws, "select block, position, old, new from fidelity_dropped") == [
        (block, 0, "not there", "x")
    ]
    why = query(ws, "select why from fidelity_dropped")[0][0]
    assert "is not in the target block" in why
    assert len(adapter.fidelity_requests) == len(scenes())  # one call per scene, no retry


def test_an_answer_with_only_bad_edits_changes_nothing_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    block = source_ids()[1]
    answers = [edit(block, "not there", "x"), edit(block, "nor here", "y")]
    adapter = FidelityAdapter(answering_all(block, answers))

    ws = run_to_the_end(tmp_path, adapter)

    assert target_text(ws, block) == "It was a quiet evening."
    assert query(ws, "select id from fidelity_edits") == []
    assert len(query(ws, "select old from fidelity_dropped")) == 2
    assert len(query(ws, "select first_block from reviewed_scenes")) == len(scenes())


def test_an_edit_that_would_change_a_locked_motif_is_dropped(tmp_path: Path) -> None:
    block = source_ids()[1]
    answers = [
        edit(block, "quiet evening", "calm night"),
        edit(block, "evening", "night", "omission"),
    ]
    motifs = [{"name": "quiet evening", "locked_rendering": "quiet evening"}]

    ws = run_to_the_end(tmp_path, FidelityAdapter(answering_all(block, answers), motifs=motifs))

    assert target_text(ws, block) == "It was a quiet night."
    assert [r[0] for r in query(ws, "select category from fidelity_edits")] == ["omission"]
    assert [r[0] for r in query(ws, "select old from fidelity_dropped")] == ["quiet evening"]
    assert "locked rendering" in query(ws, "select why from fidelity_dropped")[0][0]


def test_an_edit_that_changes_a_glossary_rendering_or_brings_a_banned_variant_is_dropped(
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
    answers = [
        edit(block, "evening", "night"),  # changes the rendering
        edit(block, "quiet", "dusk"),  # a banned variant
        edit(block, "quiet", "calm"),
    ]

    ws = run_to_the_end(tmp_path, FidelityAdapter(answering_all(block, answers), glossary=glossary))

    assert target_text(ws, block) == "It was a calm evening."
    assert [r[0] for r in query(ws, "select new from fidelity_dropped order by id")] == [
        "night",
        "dusk",
    ]


def test_an_edit_whose_old_text_is_not_in_the_target_is_dropped(tmp_path: Path) -> None:
    block = source_ids()[1]
    answers = [
        edit(block, "not there", "x"),
        edit(block, "was", "seemed", "flattened tense or free indirect speech"),
    ]

    ws = run_to_the_end(tmp_path, FidelityAdapter(answering_all(block, answers)))

    assert target_text(ws, block) == "It seemed a quiet evening."


def test_an_old_text_quoted_with_different_spacing_is_found_in_the_target(tmp_path: Path) -> None:
    block = source_ids()[1]
    answers = [edit(block, "was  a\n quiet", "seemed a quiet", "Meaning Drift")]
    adapter = FidelityAdapter(answering(block, answers))

    ws = run_to_the_end(tmp_path, adapter)

    assert target_text(ws, block) == "It seemed a quiet evening."
    assert [r[0] for r in query(ws, "select category from fidelity_edits")] == ["meaning drift"]
    assert query(ws, "select old from fidelity_edits") == [("was a quiet",)]


def test_an_edit_that_breaks_inline_codes_is_dropped(tmp_path: Path) -> None:
    source = open_epub(EPUB)
    marked = next(i for i in source_ids() if '<pc id="1">' in source.encode_block(i).text)
    text = source.encode_block(marked).text
    answers = [
        edit(marked, text, text.replace('<pc id="1">', "")),
        edit(marked, text, text + " Mas.", "omission"),
    ]

    ws = run_to_the_end(tmp_path, FidelityAdapter(answering_all(marked, answers)))

    assert target_text(ws, marked) == text + " Mas."
    assert len(query(ws, "select id from fidelity_dropped")) == 1


def test_a_wrong_form_of_address_is_fixed_in_the_right_target_block(tmp_path: Path) -> None:
    block = source_ids()[1]
    answers = [edit(block, "quiet", "calm", "wrong form of address")]

    ws = run_to_the_end(tmp_path, FidelityAdapter(answering(block, answers)))

    assert query(ws, "select block, category from fidelity_edits") == [
        (block, "wrong form of address")
    ]
    assert all(target_text(ws, b) == source_text(b) for b in source_ids() if b != block)


def source_text(block: str) -> str:
    return open_epub(EPUB).encode_block(block).text


def test_a_finished_review_is_not_run_again_and_calls_are_not_repeated(tmp_path: Path) -> None:
    adapter = FidelityAdapter()
    ws = run_to_the_end(tmp_path, adapter)
    calls = len(adapter.fidelity_requests)
    assert calls > 0

    main(["run", str(ws)], adapter=adapter)

    assert len(adapter.fidelity_requests) == calls


def test_the_review_resumes_without_repeating_finished_scenes(tmp_path: Path) -> None:
    seen: list[str] = []

    def interrupt_on_second(scene: dict[str, Any], attempt: int) -> dict[str, Any]:
        seen.append(scene["scene"][0]["id"])
        if len(seen) == 2:
            raise KeyboardInterrupt
        return {"edits": []}

    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    adapter = FidelityAdapter(interrupt_on_second)
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])
    with pytest.raises(KeyboardInterrupt):
        main(["run", str(ws)], adapter=adapter)
    assert len(query(ws, "select * from reviewed_scenes")) == 1

    resumed = FidelityAdapter()
    main(["run", str(ws)], adapter=resumed)

    starts = [s[0] for s in scenes()]
    asked = [json.loads(r.source_text)["scene"][0]["id"] for r in resumed.fidelity_requests]
    assert asked == [s for s in starts if s != seen[0]]


def test_the_review_waits_for_the_tk_gate(tmp_path: Path) -> None:
    adapter = FidelityAdapter()
    ws = tmp_path / "ws"
    main(["init", str(EPUB), "--workspace", str(ws), "--variety", "neutral"])
    main(["run", str(ws)], adapter=adapter)
    main(["approve", str(ws)])

    main(["run", str(ws)], adapter=adapter)

    assert adapter.fidelity_requests == []


def test_the_review_uses_the_model_configured_for_it(tmp_path: Path) -> None:
    adapter = FidelityAdapter()

    run_to_the_end(tmp_path, adapter)

    assert {r.model for r in adapter.fidelity_requests} == {"anthropic:claude-sonnet-5-5"}
