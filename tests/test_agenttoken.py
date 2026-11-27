"""The Agent App token helper: a JWT signed with a local key, exchanged for a narrow token.

Tests generate a throwaway RSA key and stub the HTTP layer; nothing touches the network.
"""

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agenttoken.core import APP_ID, PERMISSIONS, TokenError, make_jwt, mint_token
from agenttoken.run import run


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


class Sink:
    def __init__(self, tty: bool = False, fd: int | None = None) -> None:
        self.text = ""
        self._tty = tty
        self._fd = fd

    def fileno(self) -> int:
        if self._fd is None:
            raise OSError("no file descriptor")
        return self._fd

    def write(self, data: str) -> int:
        self.text += data
        return len(data)

    def isatty(self) -> bool:
        return self._tty


def fake_mint(key_path: Path) -> str:
    return "ghs_secret_token"


def test_run_writes_only_the_token_to_a_pipe(tmp_path: Path) -> None:
    key = tmp_path / "k.pem"
    key.write_text("not a real key")
    out, err = Sink(), Sink()
    code = run({"AGENT_APP_KEY_PATH": str(key)}, out, err, mint=fake_mint)
    assert (code, out.text, err.text) == (0, "ghs_secret_token\n", "")


def test_run_refuses_to_write_the_token_to_a_regular_file(tmp_path: Path) -> None:
    key = tmp_path / "k.pem"
    key.write_text("x")
    with (tmp_path / "out.txt").open("w") as target:
        out, err = Sink(fd=target.fileno()), Sink()
        assert run({"AGENT_APP_KEY_PATH": str(key)}, out, err, mint=fake_mint) == 1
    assert "ghs_" not in out.text + err.text
    assert (tmp_path / "out.txt").read_text() == ""


def test_run_refuses_to_print_the_token_on_a_terminal(tmp_path: Path) -> None:
    key = tmp_path / "k.pem"
    key.write_text("x")
    out, err = Sink(tty=True), Sink()
    assert run({"AGENT_APP_KEY_PATH": str(key)}, out, err, mint=fake_mint) == 1
    assert "ghs_" not in out.text + err.text


def test_run_without_a_key_path_fails_and_ignores_owner_credentials() -> None:
    out, err = Sink(), Sink()

    def never(key_path: Path) -> str:
        raise AssertionError("must not mint")

    env = {"GH_TOKEN": "owner", "GITHUB_TOKEN": "owner"}
    assert run(env, out, err, mint=never) == 1
    assert out.text == ""
    assert "AGENT_APP_KEY_PATH" in err.text and "owner" not in err.text


def test_run_reports_a_missing_key_file_without_leaking_anything(tmp_path: Path) -> None:
    out, err = Sink(), Sink()
    code = run({"AGENT_APP_KEY_PATH": str(tmp_path / "nope.pem")}, out, err, mint=fake_mint)
    assert code == 1 and out.text == ""


def test_run_reports_mint_failures_with_the_error_message_only(tmp_path: Path) -> None:
    key = tmp_path / "k.pem"
    key.write_text("x")

    def boom(key_path: Path) -> str:
        raise TokenError("GitHub refused the request (HTTP 401)")

    out, err = Sink(), Sink()
    assert run({"AGENT_APP_KEY_PATH": str(key)}, out, err, mint=boom) == 1
    assert out.text == "" and "HTTP 401" in err.text


@pytest.mark.parametrize("marker", ["dir", "file"])  # a repository has a dir, a worktree a file
def test_run_refuses_a_key_inside_a_checkout(tmp_path: Path, marker: str) -> None:
    repo = tmp_path / "checkout"
    (repo / "deep").mkdir(parents=True)
    if marker == "dir":
        (repo / ".git").mkdir()
    else:
        (repo / ".git").write_text("gitdir: elsewhere\n")
    key = repo / "deep" / "k.pem"
    key.write_text("x")
    out, err = Sink(), Sink()
    assert run({"AGENT_APP_KEY_PATH": str(key)}, out, err, mint=fake_mint) == 1
    assert out.text == "" and "checkout" in err.text


def test_run_refuses_a_symlink_that_points_into_a_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "checkout"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "k.pem").write_text("x")
    link = tmp_path / "link.pem"
    link.symlink_to(repo / "k.pem")
    out, err = Sink(), Sink()
    assert run({"AGENT_APP_KEY_PATH": str(link)}, out, err, mint=fake_mint) == 1
    assert out.text == ""


def test_requested_permissions_never_include_workflows_or_administration() -> None:
    assert set(PERMISSIONS) <= {"contents", "pull_requests", "metadata"}
    assert "workflows" not in PERMISSIONS and "administration" not in PERMISSIONS
