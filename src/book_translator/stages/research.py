"""S1, first step: web research on the book itself, before any chapter is read."""

import re
import sqlite3

from book_translator.search import Search

_TITLE = re.compile(rb"<dc:title[^>]*>([^<]+)</dc:title>")


def book_title(opf: bytes) -> str | None:
    match = _TITLE.search(opf)
    return match.group(1).decode().strip() if match else None


def research(db: sqlite3.Connection, search: Search, title: str, language: str) -> bool:
    """Look the book up and store what is found; True if anything was. Established terminology
    is looked up only outside evaluation mode (ADR 0004)."""
    evaluation = db.execute("select value from settings where key = 'evaluation'").fetchone()
    findings = search.lookup(title, language, established=evaluation is None)
    with db:
        for f in findings:
            db.execute("insert into research values (?, ?, ?)", (f.term, f.summary, f.url))
            if f.rendering is not None:
                db.execute(
                    "insert into glossary values (?, ?, 'established', ?)",
                    (f.term, f.rendering, f.url),
                )
    return bool(findings)
