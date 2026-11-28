"""Local-only check of the codec on real books; skipped when the fixtures folder is absent.

The books are copyrighted: they live in a gitignored folder (`BOOK_FIXTURES`, default
`<main checkout>/.work/fixtures`), and are never committed or used in CI.
"""

import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from book_translator.epub import open_epub


def _fixtures_dir() -> Path:
    if env := os.environ.get("BOOK_FIXTURES"):
        return Path(env)
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return Path(".work/fixtures")
    return Path(common).parent / ".work" / "fixtures"


BOOKS = sorted(_fixtures_dir().glob("*.epub")) if _fixtures_dir().is_dir() else []

pytestmark = pytest.mark.skipif(not BOOKS, reason="no real books in the fixtures folder")


def members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


@pytest.mark.parametrize("book", BOOKS, ids=lambda p: p.stem)
def test_real_book_opens_has_structure_and_round_trips(book: Path, tmp_path: Path) -> None:
    epub = open_epub(book)
    structure = epub.book()
    out = tmp_path / "out.epub"
    epub.write(out)

    assert structure.chapters
    assert members(out) == members(book)
