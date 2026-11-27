"""The Agent App token helper: a JWT signed with a local key, exchanged for a narrow token.

Tests generate a throwaway RSA key and stub the HTTP layer; nothing touches the network.
"""

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agenttoken.core import APP_ID, PERMISSIONS, make_jwt, mint_token


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


class StubApi:
    """Stands in for HttpApi: records calls, answers from canned responses."""

    def __init__(self, token: str, calls: list[tuple[str, str, Any]]) -> None:
        self.auth = token
        self.calls = calls

    def get_json(self, path: str) -> Any:
        self.calls.append(("GET", path, None))
        return {"id": 777}

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        self.calls.append(("POST", path, payload))
        return {"token": "ghs_fake", "expires_at": "2030-01-01T01:00:00Z"}


def test_mints_an_installation_token_with_only_the_pr_permissions(
    keys: tuple[Path, Path],
) -> None:
    calls: list[tuple[str, str, Any]] = []
    auths: list[str] = []

    def factory(jwt: str) -> StubApi:
        auths.append(jwt)
        return StubApi(jwt, calls)

    token = mint_token(keys[0], api_factory=factory)

    assert token == "ghs_fake"
    assert calls == [
        ("GET", "/repos/gczobel/book-translator/installation", None),
        (
            "POST",
            "/app/installations/777/access_tokens",
            {
                "repositories": ["book-translator"],
                "permissions": {"contents": "write", "pull_requests": "write"},
            },
        ),
    ]
    assert auths[0].count(".") == 2  # the App JWT, not any ambient credential


def test_requested_permissions_never_include_workflows_or_administration() -> None:
    assert set(PERMISSIONS) <= {"contents", "pull_requests", "metadata"}
    assert "workflows" not in PERMISSIONS and "administration" not in PERMISSIONS
