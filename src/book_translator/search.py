"""The search component behind our own interface (web research, spec #6).

Tests use a fixture-backed adapter; `WikiSearch` is the production one for English Wikipedia and
Wikidata, using only the stdlib. Established terms come from Wikidata's cross-language labels,
never from the book's own translated text (ADR 0004).
"""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Finding:
    """One researched entry, always with its source URL. `rendering` is set for an established
    term: the name a published source already uses in the target language."""

    term: str
    summary: str
    url: str
    rendering: str | None = None


class Search(Protocol):
    def lookup(self, query: str, language: str, *, established: bool) -> list[Finding]:
        """Findings for the query; established terms are included only when asked for."""
        ...


class WikiSearch:
    """English Wikipedia for background, Wikidata for established names in the target language."""

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    def lookup(self, query: str, language: str, *, established: bool) -> list[Finding]:
        found = self._wikipedia(query)
        if established:
            found += self._wikidata(query, language)
        return found

    def _get(self, base: str, **params: str) -> Any:
        url = f"{base}?{urllib.parse.urlencode({**params, 'format': 'json'})}"
        request = urllib.request.Request(url, headers={"User-Agent": "book-translator/0"})
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.load(response)

    def _wikipedia(self, query: str) -> list[Finding]:
        api = "https://en.wikipedia.org/w/api.php"
        data = self._get(api, action="query", list="search", srsearch=query, srlimit="1")
        hits = data["query"]["search"]
        if not hits:
            return []
        title = hits[0]["title"]
        pages = self._get(
            api, action="query", prop="extracts", exintro="1", explaintext="1", titles=title
        )["query"]["pages"]
        summary = next(iter(pages.values())).get("extract", "")
        url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        return [Finding(title, summary, url)]

    def _wikidata(self, query: str, language: str) -> list[Finding]:
        api = "https://www.wikidata.org/w/api.php"
        hits = self._get(
            api, action="wbsearchentities", search=query, language="en", limit="1"
        ).get("search", [])
        if not hits:
            return []
        entity = hits[0]["id"]
        labels = self._get(
            api, action="wbgetentities", ids=entity, props="labels", languages=language
        )["entities"][entity].get("labels", {})
        if language not in labels:
            return []
        return [
            Finding(
                hits[0]["label"],
                hits[0].get("description", ""),
                f"https://www.wikidata.org/wiki/{entity}",
                rendering=labels[language]["value"],
            )
        ]
