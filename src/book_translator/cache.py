"""The call cache: validated LLM answers stored in the workspace database, by request key."""

import sqlite3
from pathlib import Path


class CallCache:
    def __init__(self, database: Path) -> None:
        self._database = database
        db = self._connect()
        try:
            with db:
                db.execute(
                    "create table if not exists llm_cache"
                    " (key text primary key, answer text not null)"
                )
        finally:
            db.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database)

    def get(self, key: str) -> str | None:
        db = self._connect()
        try:
            row = db.execute("select answer from llm_cache where key = ?", (key,)).fetchone()
        finally:
            db.close()
        return None if row is None else str(row[0])

    def put(self, key: str, answer: str) -> None:
        db = self._connect()
        try:
            with db:
                db.execute("insert or replace into llm_cache values (?, ?)", (key, answer))
        finally:
            db.close()
