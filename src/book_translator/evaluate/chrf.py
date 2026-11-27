"""chrF (Popovic 2015): a character n-gram F-score, 0 to 100, with recall weighted twice as much
as precision (beta = 2), over character n-grams of length 1 to 6 with the spaces left out.
Statistics add up over segments, so a chapter scores as one corpus."""

from collections import Counter
from collections.abc import Iterable

MAX_ORDER = 6
BETA = 2.0

# Per order: (matching n-grams, n-grams in the hypothesis, n-grams in the reference).
Stats = list[tuple[int, int, int]]


def _ngrams(text: str, n: int) -> Counter[str]:
    squeezed = "".join(text.split())
    return Counter(squeezed[i : i + n] for i in range(len(squeezed) - n + 1))


def segment_stats(hypothesis: str, reference: str) -> Stats:
    out: Stats = []
    for n in range(1, MAX_ORDER + 1):
        hyp, ref = _ngrams(hypothesis, n), _ngrams(reference, n)
        out.append((sum((hyp & ref).values()), sum(hyp.values()), sum(ref.values())))
    return out


def add_stats(parts: Iterable[Stats]) -> Stats:
    total: Stats = [(0, 0, 0)] * MAX_ORDER
    for part in parts:
        total = [(a + x, b + y, c + z) for (a, b, c), (x, y, z) in zip(total, part, strict=True)]
    return total


def score(stats: Stats) -> float:
    """The chrF of summed statistics; the precision and recall are averaged over the orders."""
    usable = [(m, h, r) for m, h, r in stats if h and r]
    if not usable:
        return 0.0
    precision = sum(m / h for m, h, _ in usable) / len(usable)
    recall = sum(m / r for m, _, r in usable) / len(usable)
    if precision + recall == 0:
        return 0.0
    beta2 = BETA**2
    return round(100 * (1 + beta2) * precision * recall / (beta2 * precision + recall), 2)
