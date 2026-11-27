"""The Agent App token helper: a JWT signed with a local key, exchanged for a narrow token.

Tests generate a throwaway RSA key and stub the HTTP layer; nothing touches the network.
"""

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agenttoken.core import APP_ID, make_jwt


def b64d(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    directory = tmp_path_factory.mktemp("keys")
    private = directory / "agent.pem"
    public = directory / "agent.pub"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(private), "2048"], check=True, capture_output=True
    )
    subprocess.run(
        ["openssl", "rsa", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    return private, public


def verify(public: Path, signing_input: str, signature: bytes, tmp: Path) -> bool:
    sig = tmp / "sig.bin"
    sig.write_bytes(signature)
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(public), "-signature", str(sig)],
        input=signing_input.encode(),
        capture_output=True,
    )
    return result.returncode == 0


def test_jwt_is_rs256_for_the_agent_app_and_verifies_with_the_public_key(
    keys: tuple[Path, Path], tmp_path: Path
) -> None:
    private, public = keys
    token = make_jwt(private, now=1_000_000)
    header, payload, signature = token.split(".")
    assert json.loads(b64d(header)) == {"alg": "RS256", "typ": "JWT"}
    claims: dict[str, Any] = json.loads(b64d(payload))
    assert claims == {"iss": str(APP_ID), "iat": 1_000_000 - 60, "exp": 1_000_000 + 540}
    assert verify(public, f"{header}.{payload}", b64d(signature), tmp_path)
    assert not verify(public, f"{header}.{payload}x", b64d(signature), tmp_path)
