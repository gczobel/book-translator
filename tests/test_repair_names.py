"""A repair may not introduce a dependency name the PR did not already have. Seam: `new_names`."""

from repair.names import new_names

PYPROJECT = '[project]\nname = "x"\ndependencies = ["httpx>=0.27", "Typing_Extensions"]\n'
LOCK = '[[package]]\nname = "httpx"\nversion = "1"\n\n[[package]]\nname = "typing-extensions"\n'


def test_the_same_names_add_nothing() -> None:
    assert new_names(PYPROJECT, PYPROJECT, LOCK, LOCK) == []


def test_a_version_change_is_not_a_new_name() -> None:
    head = PYPROJECT.replace(">=0.27", ">=0.28")
    assert new_names(PYPROJECT, head, LOCK, LOCK.replace('"1"', '"2"')) == []


def test_a_new_requirement_name_is_reported() -> None:
    head = PYPROJECT.replace('"httpx>=0.27"', '"httpx>=0.27", "requestz>=1"')
    assert new_names(PYPROJECT, head, LOCK, LOCK) == ["requestz"]


def test_a_new_lock_entry_is_reported() -> None:
    head_lock = LOCK + '\n[[package]]\nname = "Evil.Pkg"\n'
    assert new_names(PYPROJECT, PYPROJECT, LOCK, head_lock) == ["evil-pkg"]


def test_names_are_compared_the_way_pypi_does() -> None:
    head = PYPROJECT.replace("Typing_Extensions", "typing.extensions")
    assert new_names(PYPROJECT, head, LOCK, LOCK) == []


def test_dependency_groups_and_optional_dependencies_count() -> None:
    head = PYPROJECT + '[dependency-groups]\ndev = ["pytestt>=1", {include-group = "x"}]\n'
    assert new_names(PYPROJECT, head, LOCK, LOCK) == ["pytestt"]
    head = PYPROJECT + '[project.optional-dependencies]\nextra = ["foo[bar]>=1; python_version>\'3\'"]\n'
    assert new_names(PYPROJECT, head, LOCK, LOCK) == ["foo"]


def test_a_missing_file_is_read_as_no_names() -> None:
    assert new_names('[project]\nname = "x"\n', '[project]\nname = "x"\n', "", LOCK) == [
        "httpx",
        "typing-extensions",
    ]
