"""book-translator: multi-pass literary book translation pipeline."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from book_translator.evaluate.embed import Embedder
    from book_translator.llm import Adapter
    from book_translator.search import Search

__version__ = "0.1.0"


def main(
    argv: Sequence[str] | None = None,
    *,
    adapter: "Adapter | None" = None,
    search: "Search | None" = None,
    embedder: "Embedder | None" = None,
) -> None:
    from book_translator.cli import main as cli_main

    cli_main(argv, adapter=adapter, search=search, embedder=embedder)
