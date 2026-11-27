"""Parsing the diff output into per-file changes, refusing anything incomplete."""

import pytest

from repair_validate.diff import FileChange, parse_diff
from repair_validate.errors import ValidateError

A = "a" * 40
B = "b" * 40


def raw(*entries: tuple[str, str, str, str]) -> bytes:
    """Entries are (old_mode, new_mode, status, path), as `diff --raw -z` prints them."""
    return b"".join(f":{om} {nm} {A} {B} {st}\0{path}\0".encode() for om, nm, st, path in entries)


def numstat(*entries: tuple[str, str, str]) -> bytes:
    return b"".join(f"{a}\t{r}\t{path}\0".encode() for a, r, path in entries)


def test_modified_file_collects_added_lines() -> None:
    patch = (
        "diff --git a/src/x.py b/src/x.py\n"
        "index 1..2 100644\n"
        "--- a/src/x.py\n"
        "+++ b/src/x.py\n"
        "@@ -3,1 +3,2 @@ def f():\n"
        "-old\n"
        "+new one\n"
        "+new two\n"
    )
    changes = parse_diff(
        raw(("100644", "100644", "M", "src/x.py")), numstat(("2", "1", "src/x.py")), patch
    )
    assert changes == [
        FileChange(
            path="src/x.py",
            status="M",
            old_mode="100644",
            new_mode="100644",
            added=("new one", "new two"),
            binary=False,
        )
    ]


def test_a_plus_plus_plus_line_inside_a_hunk_is_content_not_a_header() -> None:
    patch = (
        "diff --git a/src/x.py b/src/x.py\n"
        "@@ -1,0 +1,1 @@\n"
        "+++ sneaky\n"
        "diff --git a/src/y.py b/src/y.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+y\n"
    )
    changes = parse_diff(
        raw(("100644", "100644", "M", "src/x.py"), ("000000", "100644", "A", "src/y.py")),
        numstat(("1", "0", "src/x.py"), ("1", "0", "src/y.py")),
        patch,
    )
    assert [c.added for c in changes] == [("++ sneaky",), ("y",)]


def test_hunk_header_without_counts_means_one_line() -> None:
    patch = "diff --git a/f b/f\n@@ -1 +1 @@\n-a\n+b\n"
    changes = parse_diff(raw(("100644", "100644", "M", "f")), numstat(("1", "1", "f")), patch)
    assert changes[0].added == ("b",)


def test_no_newline_marker_is_not_counted() -> None:
    patch = "diff --git a/f b/f\n@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n"
    changes = parse_diff(raw(("100644", "100644", "M", "f")), numstat(("1", "1", "f")), patch)
    assert changes[0].added == ("b",)


def test_deletion_and_mode_only_change_have_no_hunks() -> None:
    patch = (
        "diff --git a/gone b/gone\ndeleted file mode 100644\n"
        "diff --git a/run b/run\nold mode 100644\nnew mode 100755\n"
    )
    changes = parse_diff(
        raw(("100644", "000000", "D", "gone"), ("100644", "100755", "M", "run")),
        numstat(("0", "0", "gone"), ("0", "0", "run")),
        patch,
    )
    assert [(c.status, c.new_mode, c.added) for c in changes] == [
        ("D", "000000", ()),
        ("M", "100755", ()),
    ]


def test_binary_file_is_flagged() -> None:
    patch = "diff --git a/x.bin b/x.bin\nBinary files a/x.bin and b/x.bin differ\n"
    changes = parse_diff(
        raw(("100644", "100644", "M", "x.bin")), numstat(("-", "-", "x.bin")), patch
    )
    assert changes[0].binary


def test_paths_with_odd_characters_survive() -> None:
    path = "src/we ird\tname\n.py"
    patch = 'diff --git "a/x" "b/x"\n@@ -0,0 +1 @@\n+z\n'
    changes = parse_diff(raw(("000000", "100644", "A", path)), numstat(("1", "0", path)), patch)
    assert changes[0].path == path


def test_empty_diff_is_no_changes() -> None:
    assert parse_diff(b"", b"", "") == []


@pytest.mark.parametrize(
    "patch",
    [
        # truncated in the middle of a hunk
        "diff --git a/f b/f\n@@ -1,0 +1,3 @@\n+a\n+b\n",
        # fewer blocks than raw entries
        "",
        # more added lines than numstat says
        "diff --git a/f b/f\n@@ -1,0 +1,2 @@\n+a\n+b\n",
        # a line that is neither context, add nor remove inside a hunk
        "diff --git a/f b/f\n@@ -1,0 +1,1 @@\nxa\n",
    ],
)
def test_incomplete_or_inconsistent_patch_fails_closed(patch: str) -> None:
    with pytest.raises(ValidateError):
        parse_diff(raw(("000000", "100644", "A", "f")), numstat(("1", "0", "f")), patch)


def test_extra_block_not_in_raw_fails_closed() -> None:
    patch = "diff --git a/f b/f\n@@ -0,0 +1 @@\n+a\ndiff --git a/g b/g\n@@ -0,0 +1 @@\n+b\n"
    with pytest.raises(ValidateError):
        parse_diff(raw(("000000", "100644", "A", "f")), numstat(("1", "0", "f")), patch)


@pytest.mark.parametrize(
    "bad_raw",
    [
        b":100644 100644 aaa bbb M\0",  # path missing
        b"junk\0f\0",
        raw(("100644", "100644", "R", "f")),  # renames are disabled, so never expected
        raw(("10064", "100644", "M", "f")),
    ],
)
def test_malformed_raw_output_fails_closed(bad_raw: bytes) -> None:
    with pytest.raises(ValidateError):
        parse_diff(bad_raw, numstat(("0", "0", "f")), "diff --git a/f b/f\n")


def test_numstat_must_list_the_same_paths() -> None:
    with pytest.raises(ValidateError):
        parse_diff(
            raw(("100644", "100644", "M", "f")),
            numstat(("0", "0", "other")),
            "diff --git a/f b/f\n",
        )
