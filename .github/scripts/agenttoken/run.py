"""Command line: print a fresh Agent App token to a pipe, for `GH_TOKEN=$(...) gh pr create`.

The key path comes only from AGENT_APP_KEY_PATH. There is no fallback to GH_TOKEN, GITHUB_TOKEN
or the owner's `gh` login. The token goes to stdout only when stdout is not a terminal, and is
never written anywhere else.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from agenttoken.core import TokenError, mint_token

KEY_ENV = "AGENT_APP_KEY_PATH"


def _inside_checkout(key: Path) -> bool:
    """True if the key, once symlinks are resolved, sits in a repository or a worktree."""
    return any((parent / ".git").exists() for parent in key.resolve().parents)


class _Stream(Protocol):
    def write(self, data: str, /) -> int: ...
    def isatty(self) -> bool: ...


def run(
    env: Mapping[str, str],
    out: _Stream,
    err: _Stream,
    mint: Callable[[Path], str] = mint_token,
) -> int:
    path = env.get(KEY_ENV)
    if not path:
        err.write(f"agenttoken: set {KEY_ENV} to the path of the Agent App private key\n")
        return 1
    key = Path(path)
    if not key.is_file():
        err.write(f"agenttoken: no key file at the path in {KEY_ENV}\n")
        return 1
    if _inside_checkout(key):
        err.write(f"agenttoken: the key in {KEY_ENV} is inside a checkout; move it out\n")
        return 1
    if out.isatty():
        err.write("agenttoken: refusing to print a token on a terminal; capture it with $(...)\n")
        return 1
    try:
        token = mint(key)
    except TokenError as error:
        err.write(f"agenttoken: {error}\n")
        return 1
    out.write(token + "\n")
    return 0
