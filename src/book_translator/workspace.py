"""The workspace: one directory per book holding the frozen source and the SQLite state."""

import os
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SOURCE_NAME = "source.epub"
DB_NAME = "book.sqlite"
LOCK_NAME = "run.lock"


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


class WorkspaceBusyError(WorkspaceError):
    def __init__(self, pid: int) -> None:
        super().__init__(f"another run (process {pid}) is working on this workspace")
        self.pid = pid


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, owned by someone else
    return True


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold the workspace for one run. A lock left by a process that is gone is taken over."""
    lock = path / LOCK_NAME
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and _alive(pid):
                raise WorkspaceBusyError(pid) from None
            lock.unlink(missing_ok=True)  # stale: its owner is gone
            continue
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        break
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)
