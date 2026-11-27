"""Mint a one-hour installation token for the Agent App from a LOCAL private key.

The key is only ever handed to `openssl` by path (the standard library has no RSA), so its
contents never pass through this process, a command line, a log or an error message.
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ghapi.client import ApiError, HttpApi

APP_ID = 5952762  # the Agent App
REPO = "gczobel/book-translator"
# What opening a code PR needs. Never Workflows or administration (ADR 0005, Identities).
PERMISSIONS = {"contents": "write", "pull_requests": "write"}


class TokenError(Exception):
    """A token can't be minted safely. Messages never contain key material or tokens."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign(key_path: Path, signing_input: bytes) -> bytes:
    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(key_path)],
            input=signing_input,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TokenError(f"could not run openssl to sign ({type(error).__name__})") from None
    if result.returncode != 0 or not result.stdout:
        raise TokenError("openssl could not sign with the Agent App key")
    return result.stdout


def make_jwt(key_path: Path, now: int | None = None) -> str:
    """A short-lived RS256 JWT identifying the Agent App to GitHub."""
    issued = int(time.time()) if now is None else now
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {"iss": str(APP_ID), "iat": issued - 60, "exp": issued + 540}
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_b64(_sign(key_path, signing_input.encode()))}"


class _Api(Protocol):
    def get_json(self, path: str) -> Any: ...
    def post_json(self, path: str, payload: dict[str, Any]) -> Any: ...


def mint_token(
    key_path: Path,
    api_factory: Callable[[str], _Api] = HttpApi,
    now: int | None = None,
) -> str:
    """Exchange the App JWT for a one-hour installation token limited to PERMISSIONS."""
    api = api_factory(make_jwt(key_path, now))
    try:
        installation = api.get_json(f"/repos/{REPO}/installation")
        response = api.post_json(
            f"/app/installations/{installation['id']}/access_tokens",
            {"repositories": [REPO.split("/")[1]], "permissions": dict(PERMISSIONS)},
        )
        token = response["token"]
    except urllib.error.HTTPError as error:
        raise TokenError(f"GitHub refused the request (HTTP {error.code})") from None
    except (ApiError, OSError, KeyError, TypeError):
        raise TokenError("GitHub did not return an installation token") from None
    if not isinstance(token, str) or not token:
        raise TokenError("GitHub did not return an installation token")
    return token
