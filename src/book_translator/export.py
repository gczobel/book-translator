"""`export`: rebuild the source EPUB in place from the stored targets and validate it.

Order (ADR 0002): rebuild each block, apply the synchronized edits, add the credits page and
remove the source's branding, check the fonts, then run epubcheck on the written file.
"""

import re
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from book_translator import __version__
from book_translator.build import SyncEdits, apply_synchronized_edits
from book_translator.config import STAGE_MODELS
from book_translator.credits import EPUBLIBRE, Credits, add_credits_page, remove_branding
from book_translator.epub import Epub, open_epub
from book_translator.epubcheck import Validator, locate
from book_translator.qa import QAFailedError, require_qa_clean, setting
from book_translator.structure import Book
from book_translator.tk_gate import OpenTKError, require_no_open_tks
from book_translator.workspace import DB_NAME, SOURCE_NAME
from book_translator.xmlparse import fromstring

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
        titles = _chapter_titles(db, source)  # before the rebuild replaces the source headings
        titles |= _section_titles(source.book(), target)
        description = _description(db, source, _metadata(source, "description"))
        _rebuild(db, source)
        _synchronize(db, source, target, titles, description)
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
    root = fromstring(source.read(source.opf_path))
    return " ".join((root.findtext(f".//{_DC}{tag}") or "").split())


_CODE = re.compile(r'<pc id="\d+">|</pc>|<ph id="\d+"/>')


def _squeezed(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _label(text: str) -> str:
    """The text of a heading as a label: its inline codes stand for a space, so that
    `Capítulo<span>I</span>` reads `Capítulo I`."""
    return " ".join(_CODE.sub(" ", text).split())


def _chapter_titles(db: sqlite3.Connection, source: Epub) -> dict[str, str]:
    """Each source chapter title (and its heading's text, which can differ by a space when the
    number sits in a span of its own) -> the translated heading as a label."""
    targets = _targets(db)
    titles: dict[str, str] = {}
    for chapter in source.book().chapters:
        for scene in chapter.scenes:
            for block in scene.blocks:
                if (
                    block.kind == "heading"
                    and chapter.title
                    and _squeezed(chapter.title) == _squeezed(block.text)
                    and block.id in targets
                ):
                    label = _label(" ".join(targets[block.id]))
                    titles[chapter.title] = titles[block.text] = label
    return titles


def _description(db: sqlite3.Connection, source: Epub, description: str) -> str | None:
    """The package description in the target language: the translation of the block of the book
    that carries the same text (a synopsis page), or None if no block does."""
    if not description.strip():
        return None
    targets = _targets(db)
    book = source.book()
    parts = [*(p.blocks for p in (*book.front, *book.back))]
    parts += [[b for s in c.scenes for b in s.blocks] for c in book.chapters]
    for blocks in parts:
        for block in blocks:
            if block.id in targets and _squeezed(block.text) == _squeezed(description):
                return _label(" ".join(targets[block.id]))
    return None


_SPANISH_SECTIONS = {  # the labels of an ePubLibre base's fixed sections
    "cover": "Cubierta",
    "title": "Título",
    "synopsis": "Sinopsis",
    "author": "Autor",
    "about the author": "Sobre el autor",
    "dedication": "Dedicatoria",
    "notes": "Notas",
    "credits": "Créditos",
}


def _section_titles(book: Book, target: str) -> dict[str, str]:
    """The fixed sections of a Spanish book (cover, synopsis, author...) labelled in Spanish.
    A label that is not one of the familiar English ones is left alone."""
    if target != "es":
        return {}
    labels = [part.title for part in (*book.front, *book.back)]
    labels += [chapter.title for chapter in book.chapters]
    return {
        label: _SPANISH_SECTIONS[label.strip().casefold()]
        for label in labels
        if label and label.strip().casefold() in _SPANISH_SECTIONS
    }


def _synchronize(
    db: sqlite3.Connection,
    source: Epub,
    target: str,
    titles: dict[str, str],
    description: str | None,
) -> None:
    row = db.execute(
        "select rendering from glossary where term = ?", (_metadata(source, "title"),)
    ).fetchone()
    apply_synchronized_edits(
        source,
        SyncEdits(
            title=str(row[0]) if row and row[0] else None,  # the book's established title
            description=description,
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
