"""book-translator: multi-pass literary book translation pipeline."""

from collections.abc import Sequence

__version__ = "0.1.0"


def main(argv: Sequence[str] | None = None) -> None:
    from book_translator.cli import main as cli_main

    cli_main(argv)
