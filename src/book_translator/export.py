"""`export`: rebuild the source EPUB in place from the stored targets and validate it.

Order (ADR 0002): rebuild each block, apply the synchronized edits, add the credits page and
remove the source's branding, check the fonts, then run epubcheck on the written file.
"""

import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from lxml import etree

from book_translator import __version__
from book_translator.build import SyncEdits, apply_synchronized_edits
from book_translator.config import STAGE_MODELS
from book_translator.credits import EPUBLIBRE, Credits, add_credits_page, remove_branding
from book_translator.epub import Epub, open_epub
from book_translator.epubcheck import Validator, locate
from book_translator.qa import QAFailedError, plain, require_qa_clean, setting
from book_translator.tk_gate import OpenTKError, require_no_open_tks
from book_translator.workspace import DB_NAME, SOURCE_NAME

_DC = "{http://purl.org/dc/elements/1.1/}"
REPORT_NAME = "epubcheck-report.txt"


class ExportError(Exception):
    pass


class ValidationFailedError(ExportError):
    def __init__(self, report: str) -> None:
        super().__init__("epubcheck failed")
        self.report = report


def export(workspace: Path, validator: Validator | None = None) -> Path:
    """Build and validate the translated EPUB; returns its path in the workspace."""
    db = sqlite3.connect(workspace / DB_NAME)
    try:
        _require_ready(db)
        checker = validator or locate()
        source = open_epub(workspace / SOURCE_NAME)
        target = setting(db, "target") or "es"
        credits = _credits(source)  # before the edits replace the original title
        _rebuild(db, source)
        _synchronize(db, source, target)
        add_credits_page(source, credits)
        remove_branding(source, EPUBLIBRE)
    finally:
        db.close()
    out = workspace / f"{workspace.resolve().name}.{target}.epub"
    source.write(out)
    result = checker.validate(out)
    (workspace / REPORT_NAME).write_text(result.report, encoding="utf-8")
    if not result.passed:
        raise ValidationFailedError(result.report)
    return out


def _require_ready(db: sqlite3.Connection) -> None:
    tables = {r[0] for r in db.execute("select name from sqlite_master where type = 'table'")}
    if not {"stages", "tks", "targets"} <= tables:
        raise ExportError("nothing to export yet: run `book-translator run` first")
    try:
        require_qa_clean(db)
        require_no_open_tks(db)
    except (QAFailedError, OpenTKError) as exc:
        raise ExportError(str(exc)) from exc


def _targets(db: sqlite3.Connection) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for block, text in db.execute("select source, text from targets order by source, position"):
        out[str(block)].append(str(text))
    return out


def _rebuild(db: sqlite3.Connection, source: Epub) -> None:
    for block, texts in _targets(db).items():
        source.rebuild_block(block, source.encode_block(block), texts)


def _metadata(source: Epub, tag: str) -> str:
    root = etree.fromstring(source.read(source.opf_path))
    return " ".join((root.findtext(f".//{_DC}{tag}") or "").split())


def _synchronize(db: sqlite3.Connection, source: Epub, target: str) -> None:
    targets = _targets(db)
    titles: dict[str, str] = {}
    for chapter in source.book().chapters:
        for scene in chapter.scenes:
            for block in scene.blocks:
                if block.kind == "heading" and chapter.title == block.text and block.id in targets:
                    titles[block.text] = plain(" ".join(targets[block.id]))
    row = db.execute(
        "select rendering from glossary where term = ?", (_metadata(source, "title"),)
    ).fetchone()
    apply_synchronized_edits(
        source,
        SyncEdits(
            title=str(row[0]) if row and row[0] else None,  # the book's established title
            language=target,
            translator=f"book-translator {__version__}",
            chapter_titles=titles,
        ),
    )


def _credits(source: Epub) -> Credits:
    edition = ", ".join(
        v for tag in ("creator", "publisher", "date") if (v := _metadata(source, tag))
    )
    return Credits(
        original_title=_metadata(source, "title"),
        source_edition=edition or "unknown edition",
        tool=f"book-translator {__version__}",
        model=", ".join(sorted({m.split(":", 1)[-1] for m in STAGE_MODELS.values()})),
        date=date.today().isoformat(),
    )
