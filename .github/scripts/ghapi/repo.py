"""The one validator for `owner/name` repository names taken from the environment or the API."""

import re

_REPO = re.compile(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def split_repo(value: object) -> tuple[str, str] | None:
    """`(owner, name)` for a well-formed `owner/name`, else None."""
    match = _REPO.fullmatch(value) if isinstance(value, str) else None
    return (match.group(1), match.group(2)) if match else None
