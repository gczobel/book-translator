"""An HTML view of a review file, so reading the cards is pleasant.

The page is regenerated from the YAML whenever it changes. Scripts on, it is one card at a time
and produces the choices file for `approve --choices`; scripts off, it is this plain listing.
Self-contained: inline CSS, no network assets, every value HTML-escaped.
"""

from html import escape
from pathlib import Path
from typing import Any

import yaml

from book_translator.review_page import interactive


def html_path(review: Path) -> Path:
    return review.with_suffix(".html")


def write_html(review: Path) -> None:
    """Render the review file next to itself, showing every card."""
    document = yaml.safe_load(review.read_text())
    gate = escape(str(document.get("gate", "")))
    body = "".join(_card(c) for c in document.get("cards", []))
    for name, value in document.items():
        if name not in ("gate", "cards"):
            title = escape(name.replace("_", " ").title())
            body += f"<section><h2>{title}</h2>{_value(value)}</section>"
    static = f"<p>Read-only view. Edit the YAML file to choose.</p>{body}"
    html_path(review).write_text(interactive(gate, document, static))


def _value(value: Any) -> str:
    """Any YAML value as nested lists, so extra sections and card details show in full."""
    if isinstance(value, dict):
        items = "".join(f"<li>{escape(str(k))}: {_value(v)}</li>" for k, v in value.items())
        return f"<ul>{items}</ul>"
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_value(v)}</li>" for v in value) + "</ul>"
    return escape(str(value))


_KNOWN = ("id", "question", "context", "options", "recommended", "why", "choice", "free_text")


def _card(card: dict[str, Any]) -> str:
    recommended = escape(str(card.get("recommended", "")))
    options = "".join(
        f"<li{' class="rec"' if str(o) == str(card.get('recommended')) else ''}>"
        f"{escape(str(o))}</li>"
        for o in card.get("options") or []
    )
    choice = card.get("choice")
    chosen = f"<p>Your choice: {escape(str(choice))}</p>" if choice else ""
    details = "".join(
        f"<p>{escape(k.replace('_', ' ').title())}: {_value(v)}</p>"
        for k, v in card.items()
        if k not in _KNOWN
    )
    return (
        f"<article><h2>{escape(str(card.get('question', '')))}</h2>"
        f"{details}"
        f"<p>{escape(str(card.get('context') or ''))}</p>"
        f"<ul>{options}</ul>"
        f'<p>Recommended: <span class="rec">{recommended}</span></p>'
        f"<p>Why: {escape(str(card.get('why') or ''))}</p>"
        f"{chosen}"
        "</article>"
    )
