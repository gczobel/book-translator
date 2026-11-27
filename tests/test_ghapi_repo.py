import pytest

from ghapi.repo import split_repo


def test_splits_a_well_formed_name() -> None:
    assert split_repo("gczobel/book-translator") == ("gczobel", "book-translator")


@pytest.mark.parametrize(
    "value",
    ["", "a", "a/b/c", "a/b\n", "a b/c", "a/b?x=1", "a/", "/b", None, 5],
)
def test_rejects_anything_else(value: object) -> None:
    assert split_repo(value) is None
