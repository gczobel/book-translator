"""Seam: WikiSearch, the production search, with the network replaced by failures."""

import io
import urllib.error
import urllib.request
from typing import Any

import pytest

from book_translator.search import WikiSearch


def failing(error: BaseException) -> Any:
    def urlopen(*args: object, **kwargs: object) -> Any:
        raise error

    return urlopen


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("no network"),
        TimeoutError("timed out"),
        urllib.error.HTTPError("https://x", 503, "unavailable", None, None),  # type: ignore[arg-type]
    ],
)
def test_a_network_failure_means_nothing_found_not_an_aborted_run(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", failing(error))

    assert WikiSearch().lookup("Gondor", "es", established=True) == []


def test_an_answer_that_is_not_json_means_nothing_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"<html>oops"))

    assert WikiSearch().lookup("Gondor", "es", established=False) == []
