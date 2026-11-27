"""A minimal PyPI JSON API client over the standard library.

Only ever talks to pypi.org, and sends no credentials. Every failure is a LockError so the
caller fails closed.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from lockage.core import Entry, LockError

_BASE = "https://pypi.org/pypi/"
_NAME = re.compile(r"[a-z0-9]([a-z0-9._-]*[a-z0-9])?")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!-]*")
_ISO_UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Only the first URL is checked against _BASE, so a redirect would escape that check."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise LockError("refusing to follow a redirect")


def _fetch(url: str) -> bytes:
    if not url.startswith(_BASE):
        raise LockError("refusing to contact a non-PyPI URL")
    request = urllib.request.Request(url, headers={"User-Agent": "book-translator-automation"})
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=30) as response:
        body: bytes = response.read()
    return body


class PyPiClient:
    def __init__(self, opener: Callable[[str], bytes] = _fetch) -> None:
        self._opener = opener

    def upload_time(self, entry: Entry) -> datetime:
        """When the release was uploaded: its youngest file, the safe reading of "how old"."""
        name, version = entry
        if not _NAME.fullmatch(name) or not _VERSION.fullmatch(version):
            raise LockError("malformed name or version")
        try:
            body = self._opener(f"{_BASE}{name}/{version}/json")
        except Exception as error:
            raise LockError(f"PyPI lookup failed ({type(error).__name__})") from error
        return _youngest_upload(body, version)


def _youngest_upload(body: bytes, version: str) -> datetime:
    try:
        data: Any = json.loads(body)
    except ValueError as error:
        raise LockError("PyPI answered with something that is not JSON") from error
    if not isinstance(data, dict):
        raise LockError("unexpected PyPI answer")
    info, files = data.get("info"), data.get("urls")
    if not isinstance(info, dict) or info.get("version") != version:
        raise LockError("PyPI answered for a different version")
    if not isinstance(files, list) or not files:
        raise LockError("PyPI lists no files for this release")
    times: list[datetime] = []
    for item in files:
        stamp = item.get("upload_time_iso_8601") if isinstance(item, dict) else None
        if not isinstance(stamp, str) or not _ISO_UTC.fullmatch(stamp):
            raise LockError("a file has no usable upload time")
        try:
            times.append(datetime.fromisoformat(stamp).astimezone(UTC))
        except ValueError as error:
            raise LockError("a file has an unreadable upload time") from error
    return max(times)
