"""Per-stage model names and the rough price table behind the cost estimate.

Prices are USD per million tokens (input, output) and are approximate list prices; they only
feed the pre-run estimate. The budget guard accounts real usage later.
"""

from dataclasses import dataclass

VARIETIES = ("peninsular", "rioplatense", "neutral")
DEFAULT_CAP_USD = 10.00

# Model string per stage (pydantic-ai style "provider:model"). Opus for whole-book consolidation
# and TK resolution, Sonnet elsewhere.
STAGE_MODELS: dict[str, str] = {
    "analysis": "anthropic:claude-sonnet-5-5",
    "consolidation": "anthropic:claude-opus-4-5",
    "enrichment": "anthropic:claude-sonnet-5-5",
    "draft": "anthropic:claude-sonnet-5-5",
    "tk_resolution": "anthropic:claude-opus-4-5",
    "fidelity": "anthropic:claude-sonnet-5-5",
    "polish": "anthropic:claude-sonnet-5-5",
    "post_polish_fidelity": "anthropic:claude-sonnet-5-5",
}


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float


PRICES: dict[str, Price] = {
    "anthropic:claude-sonnet-5-5": Price(3.0, 15.0),
    "anthropic:claude-opus-4-5": Price(5.0, 25.0),
}
