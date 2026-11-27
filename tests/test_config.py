"""Seam: per-stage model strings and the price table in config."""

import pytest

from book_translator.config import PRICES, STAGE_MODELS

SONNET = "anthropic:claude-sonnet-5-5"
OPUS = "anthropic:claude-opus-5-5"


def test_opus_is_used_for_consolidation_and_tk_resolution() -> None:
    assert STAGE_MODELS["consolidation"] == OPUS
    assert STAGE_MODELS["tk_resolution"] == OPUS


def test_every_other_stage_defaults_to_sonnet() -> None:
    others = set(STAGE_MODELS) - {"consolidation", "tk_resolution"}

    assert others
    assert {STAGE_MODELS[stage] for stage in others} == {SONNET}


@pytest.mark.parametrize("model", sorted({*STAGE_MODELS.values(), "anthropic:claude-haiku-5-5"}))
def test_every_configured_model_has_a_price(model: str) -> None:
    assert PRICES[model].input_per_mtok > 0
    assert PRICES[model].output_per_mtok > 0
