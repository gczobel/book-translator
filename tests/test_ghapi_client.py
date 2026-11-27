"""The guard's GitHub client: it holds the token, so its refusals matter."""

import io
import json
import urllib.error
import urllib.request
from types import TracebackType
from typing import Any

import pytest

from ghapi.client import ApiError, HttpApi

API = "https://api.github.com"


class Response:
    def __init__(self, body: Any, link: str = "") -> None:
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = {"Link": link}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "Response":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class Transport:
    """Stands in for urllib: answers from a list, records every request."""

    def __init__(self, answers: list[Response | Exception]) -> None:
        self.answers = answers
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _install(monkeypatch: pytest.MonkeyPatch, *answers: Response | Exception) -> Transport:
    transport = Transport(list(answers))
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    return transport


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(API, code, "x", {}, io.BytesIO(b""))  # type: ignore[arg-type]


def test_get_json_sends_a_bearer_token_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _install(monkeypatch, Response({"ok": True}))
    assert HttpApi("secret").get_json("/repos/o/r") == {"ok": True}
    request = transport.requests[0]
    assert request.full_url == f"{API}/repos/o/r"
    assert request.get_header("Authorization") == "Bearer secret"


def test_pages_are_followed_and_concatenated(monkeypatch: pytest.MonkeyPatch) -> None:
    next_url = f'<{API}/repos/o/r/pulls/1/files?per_page=100&page=2>; rel="next"'
    transport = _install(monkeypatch, Response([1, 2], link=next_url), Response([3]))
    assert HttpApi("t").get_pages("/repos/o/r/pulls/1/files") == [1, 2, 3]
    assert transport.requests[0].full_url == f"{API}/repos/o/r/pulls/1/files?per_page=100"
    assert transport.requests[1].full_url.endswith("page=2")


def test_a_next_link_to_another_host_is_refused_without_sending_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evil = '<https://evil.example/steal>; rel="next"'
    transport = _install(monkeypatch, Response([1], link=evil))
    with pytest.raises(ApiError, match="non-GitHub"):
        HttpApi("secret").get_pages("/repos/o/r/pulls/1/files")
    assert len(transport.requests) == 1  # the second request was never made


def test_endless_pagination_is_an_error_not_a_partial_list(monkeypatch: pytest.MonkeyPatch) -> None:
    link = f'<{API}/x?page=2>; rel="next"'
    _install(monkeypatch, *[Response([0], link=link) for _ in range(100)])
    with pytest.raises(ApiError, match="too many pages"):
        HttpApi("t").get_pages("/x")


def test_a_paginated_endpoint_must_return_a_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, Response({"message": "nope"}))
    with pytest.raises(ApiError, match="list"):
        HttpApi("t").get_pages("/x")


def test_a_missing_file_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _http_error(404))
    assert HttpApi("t").get_text("/repos/o/r/contents/x?ref=" + "a" * 40) is None


def test_other_errors_are_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _http_error(500))
    with pytest.raises(urllib.error.HTTPError):
        HttpApi("t").get_text("/repos/o/r/contents/x")


def test_raw_text_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _install(monkeypatch, Response(b"[tool.uv]\n"))
    assert HttpApi("t").get_text("/repos/o/r/contents/pyproject.toml") == "[tool.uv]\n"
    assert "raw" in (transport.requests[0].get_header("Accept") or "")


def test_a_path_that_would_leave_github_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _install(monkeypatch)
    with pytest.raises(ApiError, match="non-GitHub"):
        HttpApi("t").get_json("@evil.example/x")  # api.github.com@evil.example/x
    assert not transport.requests


def test_post_json_sends_the_payload_with_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _install(monkeypatch, Response({"number": 5}))
    assert HttpApi("secret").post_json("/repos/o/r/issues", {"title": "t"}) == {"number": 5}
    request = transport.requests[0]
    assert request.get_method() == "POST"
    assert request.data == b'{"title": "t"}'
    assert request.get_header("Authorization") == "Bearer secret"
