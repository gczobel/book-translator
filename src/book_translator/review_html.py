"""A read-only HTML view of a review file, so reading the cards is pleasant.

The YAML stays the thing that is edited; this page is regenerated from it whenever it changes.
Self-contained: inline CSS, no network assets, every value HTML-escaped.
"""

from html import escape
from pathlib import Path
from typing import Any

import yaml

_CSS = (
    "body{font-family:sans-serif;max-width:48rem;margin:2rem auto;padding:0 1rem;line-height:1.5}"
    "article{border:1px solid #ccc;border-radius:.5rem;padding:1rem;margin:1rem 0}"
    "h2{font-size:1.1rem;margin:0 0 .5rem}"
    ".rec{font-weight:bold}"
)


def html_path(review: Path) -> Path:
    return review.with_suffix(".html")


def write_html(review: Path) -> None:
    """Render the review file next to itself, showing every card."""
    document = yaml.safe_load(review.read_text())
    gate = escape(str(document.get("gate", "")))
    body = "".join(_card(c) for c in document.get("cards", []))
    page = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>Review: {gate}</title><style>{_CSS}</style></head><body>"
        f"<h1>Review: {gate}</h1><p>Read-only view. Edit the YAML file to choose.</p>"
        f"{body}</body></html>"
    )
    html_path(review).write_text(page)


def _card(card: dict[str, Any]) -> str:
    recommended = escape(str(card.get("recommended", "")))
    options = "".join(
        f"<li{' class="rec"' if str(o) == str(card.get('recommended')) else ''}>"
        f"{escape(str(o))}</li>"
        for o in card.get("options") or []
    )
    choice = card.get("choice")
    chosen = f"<p>Your choice: {escape(str(choice))}</p>" if choice else ""
    return (
        f"<article><h2>{escape(str(card.get('question', '')))}</h2>"
        f"<p>{escape(str(card.get('context') or ''))}</p>"
        f"<ul>{options}</ul>"
        f'<p>Recommended: <span class="rec">{recommended}</span></p>'
        f"<p>Why: {escape(str(card.get('why') or ''))}</p>"
        f"{chosen}"
        "</article>"
    )
