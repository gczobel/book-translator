"""Monotonic alignment of two sequences, allowing 1:N and N:1 groups (ADR 0001: a source block may
become several target blocks, and a reference translation may split or join paragraphs on its own).

Chapters are aligned by title and size, blocks by cross-language embeddings. Both go through
the same dynamic programme: it picks the groups, in order and without overlap, that add up to
the best score; anything left over is a gap."""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from book_translator.evaluate.embed import Embedder

# (our items, reference items) per group. A group of one side only is a gap, never listed here.
SHAPES = ((1, 1), (1, 2), (2, 1), (1, 3), (3, 1), (1, 4), (4, 1))
BLOCK_THRESHOLD = 0.3  # cosine below which two groups are not a match
CHAPTER_THRESHOLD = 0.4  # size similarity below which two chapter groups are not a match
TITLE_BONUS = 0.5
BLOCK_WINDOW = 0.25  # how far, as a share of the sequence, a block may stray from the diagonal


@dataclass(frozen=True)
class Group:
    """`ours` and `theirs` are index ranges; one of them is empty for a gap."""

    ours: range
    theirs: range


def align(
    n: int,
    m: int,
    similarity: Callable[[range, range], float],
    threshold: float,
    window: float | None = None,
) -> list[Group]:
    """The best monotonic grouping of n of our items and m of theirs.

    Only groups whose similarity beats `threshold` count, each adding its excess to the total.
    With a `window`, groups stay within that share of the diagonal (long sequences only).
    """
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    slack = int(window * max(n, m)) + 8 if window is not None else None
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            options: list[tuple[float, tuple[int, int]]] = []
            if i:
                options.append((best[i - 1][j], (1, 0)))
            if j:
                options.append((best[i][j - 1], (0, 1)))
            diagonal = j - i * m / n if n else 0
            if slack is None or abs(diagonal) <= slack:
                for k, ell in SHAPES:
                    if i >= k and j >= ell:
                        gain = similarity(range(i - k, i), range(j - ell, j)) - threshold
                        if gain > 0:
                            options.append((best[i - k][j - ell] + gain, (k, ell)))
            best[i][j], back[i][j] = max(options, key=lambda o: o[0])
    groups: list[Group] = []
    i, j = n, m
    while i or j:
        step = back[i][j]
        assert step is not None
        k, ell = step
        groups.append(Group(range(i - k, i), range(j - ell, j)))
        i, j = i - k, j - ell
    groups.reverse()
    return groups


def _title_key(title: str | None) -> str:
    return " ".join((title or "").lower().split())


@dataclass(frozen=True)
class ChapterShape:
    title: str | None
    size: int  # characters


def align_chapters(ours: Sequence[ChapterShape], theirs: Sequence[ChapterShape]) -> list[Group]:
    """Chapters by order, title and size, so a reference with other file splits still lines up."""

    def similarity(a: range, b: range) -> float:
        ours_size = sum(ours[i].size for i in a)
        their_size = sum(theirs[j].size for j in b)
        size = min(ours_size, their_size) / max(ours_size, their_size, 1)
        # A group opens with the chapter that carries the title, so only the first ones compare.
        same_title = bool(ours[a[0]].title) and _title_key(ours[a[0]].title) == _title_key(
            theirs[b[0]].title
        )
        return size + (TITLE_BONUS if same_title else 0.0)

    return align(len(ours), len(theirs), similarity, CHAPTER_THRESHOLD)


def align_blocks(ours: Sequence[str], theirs: Sequence[str], embedder: Embedder) -> list[Group]:
    """Blocks by what they mean: the embedding of a group is its blocks' embeddings, summed."""
    ours_vec = embedder.embed(ours) if ours else []
    their_vec = embedder.embed(theirs) if theirs else []
    cache: dict[tuple[int, int, int], list[float]] = {}

    def group_vector(side: int, vectors: list[list[float]], span: range) -> list[float]:
        key = (side, span.start, span.stop)
        if key not in cache:
            total = [sum(col) for col in zip(*(vectors[i] for i in span), strict=True)]
            norm = math.sqrt(math.sumprod(total, total)) or 1.0
            cache[key] = [x / norm for x in total]
        return cache[key]

    def similarity(a: range, b: range) -> float:
        return math.sumprod(group_vector(0, ours_vec, a), group_vector(1, their_vec, b))

    return align(len(ours), len(theirs), similarity, BLOCK_THRESHOLD, BLOCK_WINDOW)
