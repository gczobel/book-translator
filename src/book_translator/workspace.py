"""The workspace: one directory per book holding the frozen source and the SQLite state."""

import shutil
import sqlite3
from pathlib import Path

SOURCE_NAME = "source.epub"
DB_NAME = "book.sqlite"


class WorkspaceError(Exception):
    pass


def create(path: Path, source: Path, settings: dict[str, str]) -> Path:
    """Create the workspace, freeze a copy of the source EPUB and record the settings."""
    if path.exists():
        raise WorkspaceError(f"workspace already exists: {path}")
    path.mkdir(parents=True)
    shutil.copyfile(source, path / SOURCE_NAME)
    db = sqlite3.connect(path / DB_NAME)
    try:
        with db:
            db.execute("create table settings (key text primary key, value text not null)")
            db.executemany("insert into settings values (?, ?)", settings.items())
    finally:
        db.close()
    return path
