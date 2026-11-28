"""The pinned epubcheck install: the pin file, the script, and the hint `export` prints."""

import re
import subprocess
from pathlib import Path

import pytest

from book_translator.epubcheck import EpubcheckNotFoundError, locate

ROOT = Path(__file__).parent.parent
PIN = ROOT / "scripts" / "epubcheck.pin"
SCRIPT = ROOT / "scripts" / "install-epubcheck"


def test_the_pin_names_a_version_and_a_sha256() -> None:
    pin = dict(
        line.split("=", 1)
        for line in PIN.read_text().splitlines()
        if "=" in line and line[0] != "#"
    )
    assert re.fullmatch(r"\d+\.\d+\.\d+", pin["EPUBCHECK_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", pin["EPUBCHECK_SHA256"])


def test_the_script_is_executable_and_valid_shell() -> None:
    assert SCRIPT.stat().st_mode & 0o111
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True)


def test_a_missing_epubcheck_tells_how_to_install_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EPUBCHECK", raising=False)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(EpubcheckNotFoundError) as missing:
        locate()
    assert "scripts/install-epubcheck" in str(missing.value)
