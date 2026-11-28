"""Rough cost estimate shown at `init`, before any LLM call.

Heuristic: prose is about TOKENS_PER_WORD tokens per word. Each stage sends the book text in
`read` times (bible slice and read-only context ride along) and writes `write` of its size back.
It covers every stage that calls the model, and a margin for retries on top. It errs high.
"""

from dataclasses import dataclass

from book_translator.config import PRICES, STAGE_MODELS
from book_translator.structure import Book

TOKENS_PER_WORD = 1.5
# Extra spend on top of one clean pass: fidelity retries, re-runs and billed refusals.
RETRY_MARGIN = 0.75
# stage -> (times the book text is sent in, fraction of the book text produced). Calibrated
# against a real 6,000-word chapter: stages run per scene with the bible and read-only context
# riding along, and the writing stages emit far more than the text itself (reasoning, retries
# inside a call), so these are well above the bare token counts. Re-tune after a real run.
STAGE_LOAD: dict[str, tuple[float, float]] = {
    "analysis": (1.2, 0.15),
    "consolidation": (2.0, 0.8),  # includes the bible completion pass
    "enrichment": (0.6, 0.15),
    "draft": (50.0, 12.0),
    "tk_resolution": (2.0, 0.5),
    "fidelity": (8.0, 0.5),
    "polish": (20.0, 8.0),
    "post_polish_fidelity": (40.0, 3.5),
}


@dataclass(frozen=True)
class Estimate:
    words: int
    by_stage: dict[str, float]
    margin: float = RETRY_MARGIN

    @property
    def base_usd(self) -> float:
        return sum(self.by_stage.values())

    @property
    def cost_usd(self) -> float:
        """The figure to compare with the cap: one clean pass plus the retry margin."""
        return self.base_usd * (1 + self.margin)


def count_words(book: Book) -> int:
    texts = [b.text for p in (*book.front, *book.back) for b in p.blocks]
    texts += [b.text for c in book.chapters for s in c.scenes for b in s.blocks]
    return sum(len(t.split()) for t in texts)


def estimate(book: Book) -> Estimate:
    words = count_words(book)
    tokens = words * TOKENS_PER_WORD
    by_stage: dict[str, float] = {}
    for stage, (read, write) in STAGE_LOAD.items():
        price = PRICES[STAGE_MODELS[stage]]
        by_stage[stage] = (
            tokens * read * price.input_per_mtok + tokens * write * price.output_per_mtok
        ) / 1e6
    return Estimate(words=words, by_stage=by_stage)
