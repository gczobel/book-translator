"""The repair allowlist and rejections: what a repair patch may touch and may not add."""

import random
import string
from collections.abc import Callable

import pytest

from repair_validate.diff import FileChange
from repair_validate.rules import evaluate

PYPROJECT = """\
[project]
name = "x"
requires-python = ">=3.13"
dependencies = ["httpx>=0.27"]

[dependency-groups]
dev = ["pytest>=9.0", {include-group = "lint"}]
lint = ["ruff>=0.17"]

[tool.pytest.ini_options]
testpaths = ["tests"]
"""

HASH = "a1" * 32
LOCK_LINES = (
    "[[package]]",
    'name = "httpx"',
    'version = "0.28.1"',
    'source = { registry = "https://pypi.org/simple" }',
    "sdist = { url = "
    f'"https://files.pythonhosted.org/packages/ab/cd/{"e" * 60}/httpx-0.28.1.tar.gz", '
    f'hash = "sha256:{HASH}", size = 123, upload-time = "2026-10-17T00:04:17.183Z" }}',
    "wheels = [",
    "    { url = "
    f'"https://files.pythonhosted.org/packages/ab/cd/{"f" * 60}/httpx-0.28.1-py3-none-any.whl", '
    f'hash = "sha256:{HASH}", size = 12 }},',
    "]",
    "dependencies = [",
    '    { name = "anyio", marker = "python_full_version < \'3.15\'" },',
    '    { name = "httpx", extra = ["http2"] },',
    "]",
)


def change(
    path: str,
    added: tuple[str, ...] = ("x = 1",),
    *,
    status: str = "M",
    old_mode: str = "100644",
    new_mode: str = "100644",
    binary: bool = False,
) -> FileChange:
    return FileChange(path, status, old_mode, new_mode, added, binary)


def reasons(
    *changes: FileChange, base: str | None = PYPROJECT, head: str | None = PYPROJECT
) -> list[str]:
    return evaluate(list(changes), base, head)


def test_source_edit_is_accepted() -> None:
    assert reasons(change("src/book_translator/core.py", ("def f() -> int:", "    return 1"))) == []


def test_new_and_deleted_source_files_are_accepted() -> None:
    assert (
        reasons(
            change("src/pkg/new.py", status="A", old_mode="000000"),
            change("src/pkg/old.py", (), status="D", new_mode="000000"),
        )
        == []
    )


def test_empty_patch_is_rejected() -> None:
    assert reasons() == ["the patch changes nothing"]


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_x.py",
        "conftest.py",
        "docs/adr/0005-x.md",
        ".github/workflows/ci.yml",
        ".github/scripts/repair_validate/rules.py",
        ".claude/settings.json",
        "AGENTS.md",
        "README.md",
        "pyproject.toml.bak",
        "Src/x.py",
        "srcx/x.py",
        "../src/x.py",
        "src/../tests/x.py",
        "/src/x.py",
        "src\\x.py",
    ],
)
def test_paths_outside_the_allowlist_are_rejected(path: str) -> None:
    assert reasons(change(path))


@pytest.mark.parametrize(
    "path",
    [
        "src/pkg/conftest.py",
        "src/pkg/test_x.py",
        "src/pkg/x_test.py",
        "src/pkg/tests/helper.py",
        "src/pkg/test/helper.py",
        "src/pkg/fixtures/book.epub",
        "src/pkg/Fixture/a.json",
        "src/pkg/cassettes/run.yaml",
        "src/pkg/recorded/answers.json",
        "src/pkg/recordings/a.json",
        "src/pkg/snapshots/a.txt",
        "src/pkg/__snapshots__/a.ambr",
        "src/pkg/golden/a.txt",
        "src/pkg/.claude/commands/x.md",
        "src/pkg/.CLAUDE/x.md",
        "src/pkg/.git/hooks/pre-commit",
        "src/.github/workflows/x.yml",
    ],
)
def test_test_support_and_agent_config_inside_src_are_rejected(path: str) -> None:
    assert reasons(change(path))


@pytest.mark.parametrize(
    ("old_mode", "new_mode", "status"),
    [
        ("000000", "120000", "A"),  # new symlink
        ("120000", "120000", "M"),  # edited symlink
        ("100644", "120000", "T"),  # file turned into a symlink
        ("120000", "100644", "T"),
        ("000000", "160000", "A"),  # submodule
        ("100644", "100755", "M"),  # becomes executable
        ("000000", "100755", "A"),
    ],
)
def test_links_and_mode_changes_are_rejected(old_mode: str, new_mode: str, status: str) -> None:
    assert reasons(change("src/pkg/x.py", (), status=status, old_mode=old_mode, new_mode=new_mode))


def test_deleting_a_symlink_is_rejected_too() -> None:
    assert reasons(change("src/pkg/x", (), status="D", old_mode="120000", new_mode="000000"))


def test_binary_changes_are_rejected() -> None:
    assert reasons(change("src/pkg/data.bin", (), binary=True))


@pytest.mark.parametrize(
    "line",
    [
        "import os  # noqa",
        "import os  # noqa: F401",
        "import os  #noqa",
        "import os  # NOQA",
        "x: int = 'a'  # type: ignore",
        "x: int = 'a'  # type:ignore[assignment]",
        "x = f()  # pyright: ignore",
        "# ruff: noqa",
        "def f():  # pragma: no cover",
        "# fmt: off",
    ],
)
def test_new_suppressions_are_rejected(line: str) -> None:
    assert reasons(change("src/pkg/x.py", (line,)))


def test_removing_a_suppression_is_fine() -> None:
    # Only added lines are scanned, so a patch that deletes a noqa passes.
    assert reasons(change("src/pkg/x.py", ("import os",))) == []


@pytest.mark.parametrize(
    "line",
    [
        'KEY = "ghp_' + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8" + '"',
        'KEY = "AKIAIOSFODNN7EXAMPLE"',
        'TOKEN = "sk-ant-api03-Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0Lz"',
        "-----BEGIN RSA PRIVATE KEY-----",
        'BLOB = "' + "0123456789abcdef" * 4 + '"',
        'BLOB = "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MEFCQ0RFRg=="',
        'BLOB = "'
        + "".join(random.Random(7).choices(string.ascii_letters + string.digits, k=40))
        + '"',
    ],
)
def test_high_entropy_strings_are_rejected(line: str) -> None:
    assert reasons(change("src/pkg/x.py", (line,)))


@pytest.mark.parametrize(
    "line",
    [
        "def a_rather_long_but_ordinary_function_name(argument_one, argument_two):",
        "from book_translator.pipeline.stages import SomeVeryLongClassNameThatIsFine",
        "https://example.com/some/long/path/segment/that/is/readable",
        "x = 'the quick brown fox jumps over the lazy dog'",
        "VERSION = '1.2.3'",
        "# abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_ordinary_code_is_not_flagged_as_high_entropy(line: str) -> None:
    assert reasons(change("src/pkg/x.py", (line,))) == []


def test_dependency_edit_in_pyproject_is_accepted() -> None:
    head = PYPROJECT.replace("httpx>=0.27", "httpx>=0.28").replace("ruff>=0.17", "ruff>=0.18")
    head = head.replace(
        '"pytest>=9.0",', '"pytest>=9.0", "newpkg[extra]>=1; python_version>\'3.9\'",'
    )
    assert reasons(change("pyproject.toml", ('dependencies = ["httpx>=0.28"]',)), head=head) == []


def test_tool_config_change_in_pyproject_is_rejected() -> None:
    head = PYPROJECT.replace('testpaths = ["tests"]', "testpaths = []")
    found = reasons(change("pyproject.toml", ("testpaths = []",)), head=head)
    assert any("tool" in r for r in found)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.replace('requires-python = ">=3.13"', 'requires-python = ">=3.9"'),
        lambda t: t + '\n[tool.uv]\nexclude-newer = "1 day"\n',
        lambda t: t + '\n[tool.ruff.lint]\nignore = ["E"]\n',
        lambda t: t + '\n[project.scripts]\nx = "evil:main"\n',
        lambda t: t.replace('name = "x"', 'name = "y"'),
        lambda t: t.replace(
            "[dependency-groups]", "[build-system]\nrequires = []\n[dependency-groups]"
        ),
    ],
)
def test_any_non_dependency_change_in_pyproject_is_rejected(mutate: Callable[[str], str]) -> None:
    assert reasons(change("pyproject.toml", ("x",)), head=mutate(PYPROJECT))


@pytest.mark.parametrize(
    "dep",
    [
        "evil @ https://evil.example/x.whl",
        "evil @ git+https://github.com/a/b",
        "evil[extra] @ file:///tmp/x",
        "git+https://github.com/a/b#egg=evil",
        "../local",
        "not a requirement!!",
    ],
)
def test_direct_references_and_odd_requirements_are_rejected(dep: str) -> None:
    head = PYPROJECT.replace('"httpx>=0.27"', f'"httpx>=0.27", "{dep}"')
    assert reasons(change("pyproject.toml", (dep,)), head=head)


def test_unparsable_or_missing_pyproject_is_rejected() -> None:
    assert reasons(change("pyproject.toml"), head="[project")
    assert reasons(change("pyproject.toml", (), status="D", new_mode="000000"), head=None)
    assert reasons(change("pyproject.toml", status="A", old_mode="000000"), base=None)


def test_lock_dependency_lines_are_accepted() -> None:
    assert reasons(change("uv.lock", LOCK_LINES + ("",))) == []


@pytest.mark.parametrize(
    "line",
    [
        'source = { git = "https://github.com/evil/x" }',
        'source = { url = "https://evil.example/x.whl" }',
        'source = { path = "../x" }',
        'source = { registry = "https://evil.example/simple" }',
        'sdist = { url = "https://evil.example/x.tar.gz", hash = "sha256:' + HASH + '" }',
        'exclude-newer = "2000-01-01T00:00:00Z"',
        "[options]",
        'name = "ok"  # smuggled comment with payload=curl evil.example',
        'name = "' + "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0Lz" + '"',
        '    { url = "https://files.pythonhosted.org/packages/ab/cd/' + "z" * 60 + '/x.whl",'
        ' hash = "sha256:123", size = 1 },',
    ],
)
def test_foreign_lock_lines_are_rejected(line: str) -> None:
    assert reasons(change("uv.lock", (line,)))


def test_lock_deletion_is_rejected() -> None:
    assert reasons(change("uv.lock", (), status="D", new_mode="000000"))


def test_every_violation_is_reported_not_just_the_first() -> None:
    found = reasons(change("tests/a.py"), change("src/b.py", ("x  # noqa",)), change(".claude/c"))
    assert len(found) >= 3
