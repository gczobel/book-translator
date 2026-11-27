"""The PyPI lookup, run against recorded JSON API responses (tests/fixtures/pypi), no network."""

import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lockage.core import LockError
from lockage.pypi import PyPiClient

FIXTURES = Path(__file__).parent / "fixtures" / "pypi"


def _recorded(name: str, version: str) -> bytes:
    return (FIXTURES / f"{name}-{version}.json").read_bytes()


def _body(version: str, stamp: str) -> bytes:
    files = [{"upload_time_iso_8601": stamp}]
    return json.dumps({"info": {"version": version}, "urls": files}).encode()


def _client(body: bytes, urls: list[str] | None = None) -> PyPiClient:
    def opener(url: str) -> bytes:
        if urls is not None:
            urls.append(url)
        return body

    return PyPiClient(opener)


def test_the_upload_time_is_the_youngest_file_of_the_release() -> None:
    # packaging 26.4: wheel 21:44:09, sdist 21:44:11 on 2026-11-23
    got = _client(_recorded("packaging", "26.4")).upload_time(("packaging", "26.4"))
    assert got == datetime(2026, 11, 23, 21, 44, 11, 152574, tzinfo=UTC)


def test_the_youngest_of_many_files_wins() -> None:
    got = _client(_recorded("ruff", "0.17.6")).upload_time(("ruff", "0.17.6"))
    assert got == datetime(2026, 11, 19, 15, 56, 27, 106209, tzinfo=UTC)


def test_it_asks_the_release_json_endpoint_on_pypi() -> None:
    urls: list[str] = []
    _client(_recorded("pytest", "9.2.0"), urls).upload_time(("pytest", "9.2.0"))
    assert urls == ["https://pypi.org/pypi/pytest/9.2.0/json"]


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b"{}",
        b'{"info": {"version": "9.2.0"}, "urls": []}',  # a release with no files
        _body("9.2.1", "2026-01-01T00:00:00Z"),  # a different version
        _body("9.2.0", "yesterday"),
        _body("9.2.0", "2026-01-01T00:00:00"),  # no timezone
        b'{"info": {"version": "9.2.0"}, "urls": [{}]}',
        b'{"info": {"version": "9.2.0"}, "urls": "x"}',
    ],
)
def test_an_answer_that_cannot_be_trusted_is_an_error(body: bytes) -> None:
    with pytest.raises(LockError):
        _client(body).upload_time(("pytest", "9.2.0"))


def test_a_missing_release_is_an_error() -> None:
    def opener(url: str) -> bytes:
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]

    with pytest.raises(LockError):
        PyPiClient(opener).upload_time(("nope", "1"))


def test_a_network_failure_is_an_error() -> None:
    def opener(url: str) -> bytes:
        raise TimeoutError

    with pytest.raises(LockError):
        PyPiClient(opener).upload_time(("pytest", "9.2.0"))


def test_a_malformed_entry_never_reaches_the_url() -> None:
    urls: list[str] = []
    with pytest.raises(LockError):
        _client(json.dumps({}).encode(), urls).upload_time(("../etc", "1"))
    assert urls == []
