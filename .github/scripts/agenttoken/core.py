"""Mint a one-hour installation token for the Agent App from a LOCAL private key.

The key is only ever handed to `openssl` by path (the standard library has no RSA), so its
contents never pass through this process, a command line, a log or an error message.
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
from pathlib import Path

APP_ID = 5952762  # the Agent App


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
