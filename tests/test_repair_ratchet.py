"""The test-ID ratchet: head keeps every base test, and skip/xfail sets don't change."""

import pytest

from repair_validate.errors import ValidateError
from repair_validate.ratchet import check

PYPROJECT = '[tool.pytest.ini_options]\ntestpaths = ["tests"]\npythonpath = ["x"]\n'

BASE_TESTS = """\
import pytest

def test_a(): pass

@pytest.mark.parametrize("n", [1, 2, 3])
def test_b(n): pass

class TestC:
    def test_d(self): pass
    def helper(self): pass

class Plain:
    def test_not_collected(self): pass

def helper(): pass
"""


class DictTree:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def paths(self) -> list[str]:
        return list(self.files)

    def read(self, path: str) -> str:
        return self.files[path]


def tree(tests: str = BASE_TESTS, pyproject: str | None = PYPROJECT, **extra: str) -> DictTree:
    files = {"tests/test_x.py": tests, "src/pkg/__init__.py": "x = 1\n"}
    if pyproject is not None:
        files["pyproject.toml"] = pyproject
    files.update({k.replace("__", "/"): v for k, v in extra.items()})
    return DictTree(files)


def test_identical_trees_pass() -> None:
    assert check(tree(), tree()) == []


def test_new_tests_are_fine() -> None:
    assert check(tree(), tree(BASE_TESTS + "def test_new(): pass\n")) == []


@pytest.mark.parametrize(
    "mutated",
    [
        BASE_TESTS.replace("def test_a(): pass\n", ""),
        BASE_TESTS.replace("def test_a(", "def not_a_test_a("),
        BASE_TESTS.replace("class TestC:", "class Gone:"),
        BASE_TESTS.replace("[1, 2, 3]", "[1, 2]"),
        BASE_TESTS.replace("[1, 2, 3]", "make_params()"),
        BASE_TESTS.replace("class TestC:", "class TestC:\n    __test__ = False"),
        "",
    ],
)
def test_a_missing_test_id_fails(mutated: str) -> None:
    found = check(tree(), tree(mutated))
    assert found and "missing" in found[0]


def test_deleting_the_test_file_fails() -> None:
    head = tree()
    del head.files["tests/test_x.py"]
    assert check(tree(), head)


def test_moving_tests_to_a_path_pytest_no_longer_collects_fails() -> None:
    head = tree()
    head.files["tests/helpers.py"] = head.files.pop("tests/test_x.py")
    assert check(tree(), head)


@pytest.mark.parametrize(
    "mutated",
    [
        BASE_TESTS.replace("def test_a()", "@pytest.mark.skip\ndef test_a()"),
        BASE_TESTS.replace("def test_a()", "@pytest.mark.skipif(True, reason='x')\ndef test_a()"),
        BASE_TESTS.replace("def test_a()", "@pytest.mark.xfail\ndef test_a()"),
        BASE_TESTS.replace("def test_a(): pass", "def test_a():\n    pytest.skip('no')"),
        BASE_TESTS.replace("def test_a(): pass", "def test_a():\n    pytest.xfail('no')"),
        BASE_TESTS.replace("class TestC:", "@pytest.mark.skip\nclass TestC:"),
        BASE_TESTS.replace("class TestC:", "class TestC:\n    pytestmark = pytest.mark.skip"),
        "pytestmark = pytest.mark.skip\n" + BASE_TESTS,
        "pytest.skip('all', allow_module_level=True)\n" + BASE_TESTS,
        BASE_TESTS.replace("[1, 2, 3]", "[1, pytest.param(2, marks=pytest.mark.xfail), 3]"),
    ],
)
def test_added_skip_or_xfail_fails(mutated: str) -> None:
    found = check(tree(), tree(mutated))
    assert found and "skip" in found[0]


def test_removing_a_skip_also_fails() -> None:
    skipped = BASE_TESTS.replace("def test_a()", "@pytest.mark.skip\ndef test_a()")
    assert check(tree(skipped), tree())


def test_a_new_skipped_test_fails() -> None:
    head = BASE_TESTS + "@pytest.mark.skip\ndef test_new(): pass\n"
    assert check(tree(), tree(head))


def test_skip_that_already_exists_in_base_is_unchanged() -> None:
    skipped = BASE_TESTS.replace("def test_a()", "@pytest.mark.skip\ndef test_a()")
    assert check(tree(skipped), tree(skipped + "def test_new(): pass\n")) == []


def test_default_collection_rules_without_a_pytest_section() -> None:
    files = {
        "pkg/test_a.py": "def test_a(): pass\n",
        "pkg/b_test.py": "def test_b(): pass\n",
        "pkg/helpers.py": "def test_c(): pass\n",
        ".venv/test_z.py": "def test_z(): pass\n",
        "node_modules/test_y.py": "def test_y(): pass\n",
    }
    base = DictTree({**files, "pyproject.toml": "[project]\nname = 'x'\n"})
    head = DictTree({**files, "pyproject.toml": "[project]\nname = 'x'\n"})
    assert check(base, head) == []
    del head.files["pkg/b_test.py"]
    assert check(base, head)
    # files pytest ignores by default may change freely
    head = DictTree({**base.files, ".venv/test_z.py": ""})
    assert check(base, head) == []


def test_uses_the_bases_config_not_the_heads() -> None:
    # Head's config narrows testpaths so its tests vanish; the ratchet must still use base's.
    head = tree(pyproject='[tool.pytest.ini_options]\ntestpaths = ["nowhere"]\n')
    assert check(tree(), head) == []  # same files, base's config: nothing is lost


def test_custom_patterns_from_the_base_config() -> None:
    config = (
        "[tool.pytest.ini_options]\ntestpaths = ['spec']\n"
        "python_files = ['check_*.py']\npython_classes = ['Describe']\n"
        "python_functions = ['it_']\n"
    )
    files = {
        "spec/check_a.py": "def it_works(): pass\nclass DescribeX:\n    def it_too(self): pass\n",
        "spec/test_b.py": "def test_x(): pass\n",
        "pyproject.toml": config,
    }
    base = DictTree(files)
    head = DictTree({**files, "spec/check_a.py": "def it_works(): pass\n"})
    found = check(base, head)
    assert found and "check_a.py::DescribeX::it_too" in found[0]
    # test_b.py is not collected under these patterns, so deleting it is fine
    head = DictTree({k: v for k, v in files.items() if k != "spec/test_b.py"})
    assert check(base, head) == []


def test_testpaths_may_name_a_file_and_globs() -> None:
    config = "[tool.pytest.ini_options]\ntestpaths = ['one.py', 'many/*']\n"
    files = {
        "pyproject.toml": config,
        "one.py": "def test_one(): pass\n",
        "many/a/test_a.py": "def test_a(): pass\n",
        "other/test_o.py": "def test_o(): pass\n",
    }
    head = DictTree({**files})
    del head.files["one.py"]
    assert check(DictTree(files), head)
    head = DictTree({**files})
    del head.files["many/a/test_a.py"]
    assert check(DictTree(files), head)
    head = DictTree({**files})
    del head.files["other/test_o.py"]
    assert check(DictTree(files), head) == []


def test_unittest_testcase_classes_are_collected() -> None:
    src = "import unittest\nclass Thing(unittest.TestCase):\n    def test_x(self): pass\n"
    assert check(tree(src), tree("import unittest\n"))


def test_native_toml_pytest_section_is_read() -> None:
    config = "[tool.pytest]\ntestpaths = ['spec']\n"
    files = {"pyproject.toml": config, "spec/test_a.py": "def test_a(): pass\n"}
    head = DictTree({"pyproject.toml": config})
    assert check(DictTree(files), head)


@pytest.mark.parametrize(
    "extra",
    [
        {"pytest.ini": "[pytest]\n"},
        {".pytest.ini": "[pytest]\n"},
    ],
)
def test_other_config_files_fail_closed(extra: dict[str, str]) -> None:
    base = tree()
    base.files.update(extra)
    with pytest.raises(ValidateError):
        check(base, tree())


def test_tox_or_setup_cfg_without_a_pyproject_section_fails_closed() -> None:
    base = tree(pyproject="[project]\nname='x'\n")
    base.files["tox.ini"] = "[pytest]\n"
    with pytest.raises(ValidateError):
        check(base, base)


@pytest.mark.parametrize(
    "config",
    [
        "[tool.pytest.ini_options]\nnorecursedirs = ['tests']\n",
        "[tool.pytest.ini_options]\naddopts = '--ignore=tests/test_x.py'\n",
        "[tool.pytest.ini_options]\ntestpaths = 5\n",
        "[tool.pytest]\ntestpaths = ['a']\n[tool.pytest.ini_options]\ntestpaths = ['b']\n",
        "[tool.pytest.ini_options",
    ],
)
def test_config_we_cannot_model_fails_closed(config: str) -> None:
    with pytest.raises(ValidateError):
        check(tree(pyproject=config), tree())


def test_a_syntax_error_in_either_tree_fails_closed() -> None:
    with pytest.raises(ValidateError):
        check(tree(), tree("def test_a(:\n"))
    with pytest.raises(ValidateError):
        check(tree("def test_a(:\n"), tree())
