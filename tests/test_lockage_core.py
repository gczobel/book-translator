"""The lock-entry age gate: which entries changed, how old they must be, and what fails closed."""

from datetime import UTC, datetime, timedelta

import pytest

from lockage.core import (
    LockError,
    Policy,
    changed_entries,
    check,
    minimum_age,
    parse_lock,
)

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
REGISTRY = '{ registry = "https://pypi.org/simple" }'


def _lock(*packages: str) -> str:
    return "version = 1\nrevision = 3\n\n" + "\n".join(packages)


def _pkg(name: str, version: str, source: str = REGISTRY) -> str:
    return f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {source}\n'


PROJECT = '[[package]]\nname = "book-translator"\nversion = "0.1.0"\nsource = { editable = "." }\n'


def test_parse_lock_lists_registry_entries_and_skips_the_project() -> None:
    entries = parse_lock(_lock(PROJECT, _pkg("Packaging", "26.4")))
    assert entries == {("packaging", "26.4")}


def test_changed_entries_are_new_or_bumped_ones_only() -> None:
    base = parse_lock(_lock(_pkg("a", "1.0"), _pkg("b", "1.0"), _pkg("gone", "1.0")))
    head = parse_lock(_lock(_pkg("a", "1.0"), _pkg("b", "1.1"), _pkg("c", "2.0")))
    assert changed_entries(base, head) == {("b", "1.1"), ("c", "2.0")}


def test_a_second_version_of_an_existing_package_counts_as_changed() -> None:
    base = parse_lock(_lock(_pkg("a", "1.0")))
    head = parse_lock(_lock(_pkg("a", "1.0"), _pkg("a", "2.0")))
    assert changed_entries(base, head) == {("a", "2.0")}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not [valid toml",
        "version = 1\n",  # no packages at all
        _lock('[[package]]\nname = "a"\nsource = { registry = "https://pypi.org/simple" }\n'),
        _lock('[[package]]\nversion = "1"\nsource = { registry = "https://pypi.org/simple" }\n'),
        _lock('[[package]]\nname = "a"\nversion = "1"\n'),  # no source
        _lock(_pkg("a", "1", '{ git = "https://example.com/a.git" }')),
        _lock(_pkg("a", "1", '{ url = "https://example.com/a.whl" }')),
        _lock(_pkg("a", "1", '{ registry = "https://evil.example/simple" }')),
        _lock(_pkg("../x", "1")),
        _lock(_pkg("a", "1/../../x")),
    ],
)
def test_an_unparseable_or_unverifiable_lock_is_an_error(text: str) -> None:
    with pytest.raises(LockError):
        parse_lock(text)


@pytest.mark.parametrize(
    "security,urgent,hours",
    [
        (False, False, 7 * 24),
        (False, True, 7 * 24),  # urgent never shortens a plain version update
        (True, False, 72),
        (True, True, 0),
    ],
)
def test_minimum_age(security: bool, urgent: bool, hours: int) -> None:
    assert minimum_age(Policy(security=security, urgent=urgent)) == timedelta(hours=hours)


def test_check_passes_entries_old_enough() -> None:
    uploads = {("a", "1"): NOW - timedelta(days=7), ("b", "2"): NOW - timedelta(days=30)}
    assert check(set(uploads), timedelta(days=7), NOW, uploads.__getitem__) == []


def test_check_reports_entries_that_are_too_young() -> None:
    uploads = {("a", "1"): NOW - timedelta(days=6, hours=23), ("b", "2"): NOW - timedelta(days=9)}
    problems = check(set(uploads), timedelta(days=7), NOW, uploads.__getitem__)
    assert len(problems) == 1
    assert "a 1" in problems[0]


def test_check_treats_an_upload_time_in_the_future_as_too_young() -> None:
    uploads = {("a", "1"): NOW + timedelta(days=1)}
    assert check(set(uploads), timedelta(days=7), NOW, uploads.__getitem__)


def test_a_failed_lookup_is_a_problem_not_a_pass() -> None:
    def boom(entry: tuple[str, str]) -> datetime:
        raise LockError("no such release")

    problems = check({("a", "1")}, timedelta(days=7), NOW, boom)
    assert len(problems) == 1
    assert "a 1" in problems[0]


def test_an_unexpected_lookup_crash_is_a_problem_too() -> None:
    def boom(entry: tuple[str, str]) -> datetime:
        raise RuntimeError("secret detail")

    problems = check({("a", "1")}, timedelta(days=7), NOW, boom)
    assert len(problems) == 1
    assert "secret detail" not in problems[0]
