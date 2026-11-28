"""Running epubcheck, the EPUB validator, as a subprocess behind a small interface."""

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

ENV_VAR = "EPUBCHECK"
INSTALL_HINT = (
    "epubcheck was not found. Install the pinned version with `scripts/install-epubcheck` "
    "(from the repository root; it needs curl, unzip and java and installs under ~/.local), "
    f"or put your own `epubcheck` on PATH, or set {ENV_VAR} to its command or its .jar file."
)


class EpubcheckNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    report: str


class Validator(Protocol):
    def validate(self, epub: Path) -> CheckResult: ...


@dataclass(frozen=True)
class Epubcheck:
    command: tuple[str, ...]

    def validate(self, epub: Path) -> CheckResult:
        done = subprocess.run(
            [*self.command, str(epub)], capture_output=True, text=True, check=False
        )
        return CheckResult(done.returncode == 0, (done.stdout + done.stderr).strip() + "\n")


def locate() -> Epubcheck:
    """The epubcheck named by $EPUBCHECK (a command or a .jar), else `epubcheck` on PATH."""
    configured = os.environ.get(ENV_VAR, "").strip()
    if configured:
        if configured.lower().endswith(".jar"):
            if not Path(configured).is_file():
                raise EpubcheckNotFoundError(f"{ENV_VAR} points at {configured}, which is missing")
            return Epubcheck(("java", "-jar", configured))
        parts = tuple(shlex.split(configured))
        if not shutil.which(parts[0]):
            raise EpubcheckNotFoundError(f"{ENV_VAR} names {parts[0]}, which cannot be run")
        return Epubcheck(parts)
    found = shutil.which("epubcheck")
    if found is None:
        raise EpubcheckNotFoundError(INSTALL_HINT)
    return Epubcheck((found,))
