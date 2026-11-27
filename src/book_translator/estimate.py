"""Rough cost estimate shown at `init`, before any LLM call.

Heuristic: prose is about TOKENS_PER_WORD tokens per word. Each stage sends the book text in
`read` times (bible slice and read-only context ride along) and writes `write` of its size back.
It is deliberately coarse and errs high.
"""

from dataclasses import dataclass

from book_translator.config import PRICES, STAGE_MODELS
from book_translator.structure import Book

TOKENS_PER_WORD = 1.5
# stage -> (times the book text is sent in, fraction of the book text produced)
STAGE_LOAD: dict[str, tuple[float, float]] = {
    "analysis": (1.2, 0.15),
    "consolidation": (0.3, 0.10),
    "enrichment": (0.2, 0.03),
    "draft": (2.5, 1.2),
    "tk_resolution": (0.1, 0.05),
    "fidelity": (2.5, 0.1),
    "polish": (1.8, 1.2),
    "post_polish_fidelity": (2.5, 0.1),
}


@dataclass(frozen=True)
class Estimate:
    words: int
    cost_usd: float


def count_words(book: Book) -> int:
    texts = [b.text for p in (*book.front, *book.back) for b in p.blocks]
    texts += [b.text for c in book.chapters for s in c.scenes for b in s.blocks]
    return sum(len(t.split()) for t in texts)


def estimate(book: Book) -> Estimate:
    words = count_words(book)
    tokens = words * TOKENS_PER_WORD
    cost = 0.0
    for stage, (read, write) in STAGE_LOAD.items():
        price = PRICES[STAGE_MODELS[stage]]
        cost += tokens * read * price.input_per_mtok / 1e6
        cost += tokens * write * price.output_per_mtok / 1e6
    return Estimate(words=words, cost_usd=cost)
