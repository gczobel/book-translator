"""A minimal GitHub REST client over the standard library.

The token is only ever sent to api.github.com: pagination links that point anywhere
else are refused.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from guard.collect import GuardError

_API = "https://api.github.com"
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')
_MAX_PAGES = 40  # 4000 items at 100 per page; more than any real PR here


class HttpApi:
    def __init__(self, token: str) -> None:
        self._token = token

    def _open(self, url: str, accept: str) -> tuple[bytes, str]:
        if not url.startswith(_API + "/"):
            raise GuardError("refusing to send the token to a non-GitHub URL")
        request = urllib.request.Request(  # noqa: S310 - scheme and host checked above
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": accept,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "book-translator-guard",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read(), response.headers.get("Link", "")

    def get_json(self, path: str) -> Any:
        body, _ = self._open(_API + path, "application/vnd.github+json")
        return json.loads(body)

    def get_pages(self, path: str) -> list[Any]:
        items: list[Any] = []
        separator = "&" if "?" in path else "?"
        url: str | None = f"{_API}{path}{separator}per_page=100"
        for _ in range(_MAX_PAGES):
            if url is None:
                return items
            body, link = self._open(url, "application/vnd.github+json")
            page = json.loads(body)
            if not isinstance(page, list):
                raise GuardError("expected a list from a paginated endpoint")
            items += page
            match = _NEXT.search(link)
            url = match.group(1) if match else None
        if url is not None:
            raise GuardError("too many pages to read them all")
        return items

    def get_text(self, path: str) -> str | None:
        try:
            body, _ = self._open(_API + path, "application/vnd.github.raw+json")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        return body.decode("utf-8")
