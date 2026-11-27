"""The test-ID ratchet: a repair may add tests but never remove or silence one.

Collecting tests normally means running pytest, which imports the PR's code. This validator
must not run PR code, so it reads the test files as data: it parses them with `ast` and applies
the collection rules from the *base* tree's pytest configuration (testpaths, python_files,
python_classes, python_functions, and pytest's default ignored directories). The same rules,
from the same base configuration, are applied to the head tree, so a repair cannot narrow what
counts as a test by editing the config.

A test's ID is its path, its class chain and its name. A parametrized test also gets one ID per
literal case (`#0`, `#1`, ...), so dropping a case is a lost ID; a non-literal case list counts
as a single unknown ID. A test's skip signature is every skip, skipif, xfail or importorskip use
that can affect it: on the test, on its classes, at module level, or inside its body.

Anything this reader cannot model faithfully (a pytest.ini, a norecursedirs setting, an addopts
that deselects, a syntax error) raises ValidateError, so the check fails closed.
"""

from __future__ import annotations

import ast
import fnmatch
import itertools
import shlex
import tomllib
from dataclasses import dataclass
from typing import Any, Protocol

from repair_validate.errors import ValidateError

_DEFAULT_NORECURSE = (
    "*.egg",
    ".*",
    "_darcs",
    "build",
    "CVS",
    "dist",
    "node_modules",
    "venv",
    "{arch}",
)
_SKIP_NAMES = {"skip", "skipif", "xfail", "importorskip"}
_DESELECTING_OPTIONS = ("--ignore", "--deselect", "--confcutdir", "--rootdir", "-k")
_REPORTED = 10


class Tree(Protocol):
    def paths(self) -> list[str]:
        """Every file path in the tree."""
        ...

    def read(self, path: str) -> str:
        """A file's text; raises ValidateError if it can't be read."""
        ...


@dataclass(frozen=True)
class PytestConfig:
    testpaths: tuple[str, ...] = ()
    python_files: tuple[str, ...] = ("test_*.py", "*_test.py")
    python_classes: tuple[str, ...] = ("Test",)
    python_functions: tuple[str, ...] = ("test",)


def _words(value: Any, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        return tuple(value.split())
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    raise ValidateError(f"pytest setting {key} has an unsupported value")


def load_config(tree: Tree) -> PytestConfig:
    """The pytest collection settings of a tree, or ValidateError if they can't be modeled."""
    paths = set(tree.paths())
    if paths & {"pytest.ini", ".pytest.ini"}:
        raise ValidateError("pytest.ini is not supported by the ratchet")
    section: dict[str, Any] | None = None
    if "pyproject.toml" in paths:
        try:
            doc = tomllib.loads(tree.read("pyproject.toml"))
        except tomllib.TOMLDecodeError as error:
            raise ValidateError(f"pyproject.toml is not valid TOML: {error}") from error
        tool = doc.get("tool", {})
        pytest_table = tool.get("pytest") if isinstance(tool, dict) else None
        if isinstance(pytest_table, dict):
            if "ini_options" in pytest_table:
                if len(pytest_table) > 1:
                    raise ValidateError("pyproject.toml has both [tool.pytest] and ini_options")
                pytest_table = pytest_table["ini_options"]
            if not isinstance(pytest_table, dict):
                raise ValidateError("pytest configuration is not a table")
            section = pytest_table
    if section is None:
        if paths & {"tox.ini", "setup.cfg"}:
            raise ValidateError("tox.ini or setup.cfg may configure pytest; not supported")
        return PytestConfig()
    if "norecursedirs" in section:
        raise ValidateError("pytest norecursedirs is not supported by the ratchet")
    addopts = section.get("addopts", "")
    tokens = shlex.split(addopts) if isinstance(addopts, str) else list(addopts)
    if any(str(t).startswith(_DESELECTING_OPTIONS) for t in tokens):
        raise ValidateError("pytest addopts deselect tests; not supported by the ratchet")
    defaults = PytestConfig()
    return PytestConfig(
        testpaths=_words(section.get("testpaths"), "testpaths", ()),
        python_files=_words(section.get("python_files"), "python_files", defaults.python_files),
        python_classes=_words(
            section.get("python_classes"), "python_classes", defaults.python_classes
        ),
        python_functions=_words(
            section.get("python_functions"), "python_functions", defaults.python_functions
        ),
    )


def _is_collected_file(path: str, config: PytestConfig) -> bool:
    parts = path.split("/")
    if not path.endswith(".py"):
        return False
    for root in config.testpaths or ("",):
        root = root.rstrip("/")
        if root and fnmatch.fnmatchcase(path, root):
            return True  # a file named directly is collected whatever its name
        for depth in range(len(parts)):
            if root and not fnmatch.fnmatchcase("/".join(parts[:depth]), root):
                continue
            if not root and depth:
                break
            below = parts[depth:]
            if any(
                fnmatch.fnmatchcase(d, pattern)
                for d in below[:-1]
                for pattern in _DEFAULT_NORECURSE
            ):
                continue
            if any(fnmatch.fnmatchcase(below[-1], p) for p in config.python_files):
                return True
    return False


def _name_matches(name: str, patterns: tuple[str, ...]) -> bool:
    return any(name.startswith(p) or fnmatch.fnmatchcase(name, p) for p in patterns)


def _skip_uses(nodes: list[ast.AST]) -> list[str]:
    """Source text of every skip-like use inside the given nodes."""
    called: set[int] = set()
    found: list[str] = []
    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in _SKIP_NAMES:
                    called.add(id(func))
                    found.append(ast.unparse(node))
    for root in nodes:
        for node in ast.walk(root):
            if id(node) in called:
                continue
            if (isinstance(node, ast.Attribute) and node.attr in _SKIP_NAMES) or (
                isinstance(node, ast.Name) and node.id in _SKIP_NAMES
            ):
                found.append(ast.unparse(node))
    return found


def _is_def(node: ast.AST) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)


def _opts_out(body: list[ast.stmt]) -> bool:
    """`__test__ = False` in a module or class body."""
    for stmt in body:
        if (
            isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__test__" for t in stmt.targets)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is False
        ):
            return True
    return False


def _param_options(decorators: list[ast.expr]) -> list[list[str]]:
    options: list[list[str]] = []
    for deco in decorators:
        if not isinstance(deco, ast.Call):
            continue
        name = ast.unparse(deco.func)
        if name != "parametrize" and not name.endswith(".parametrize"):
            continue
        values = deco.args[1] if len(deco.args) > 1 else None
        if values is None:
            values = next((k.value for k in deco.keywords if k.arg == "argvalues"), None)
        if isinstance(values, ast.List | ast.Tuple | ast.Set):
            options.append([f"#{i}" for i in range(len(values.elts))])
        else:
            options.append(["?"])
    return options


def _is_testcase(cls: ast.ClassDef) -> bool:
    return any(ast.unparse(b).endswith("TestCase") for b in cls.bases)


def _collect_body(
    body: list[ast.stmt],
    prefix: str,
    config: PytestConfig,
    inherited_skips: list[str],
    inherited_decorators: list[ast.expr],
    out: dict[str, tuple[str, ...]],
    *,
    in_testcase: bool = False,
) -> None:
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if not (in_testcase and node.name.startswith("test")) and not _name_matches(
                node.name, config.python_functions
            ):
                continue
            own = [*node.decorator_list, *node.body]
            skips = tuple(sorted([*inherited_skips, *_skip_uses(list(own))]))
            decorators = [*inherited_decorators, *node.decorator_list]
            suffixes = [""]
            options = _param_options(decorators)
            if options:
                suffixes = ["[" + "-".join(c) + "]" for c in itertools.product(*options)]
            for suffix in suffixes:
                out[f"{prefix}{node.name}{suffix}"] = skips
        elif isinstance(node, ast.ClassDef):
            testcase = _is_testcase(node)
            if not (testcase or _name_matches(node.name, config.python_classes)):
                continue
            if _opts_out(node.body) or any(
                isinstance(s, ast.FunctionDef) and s.name == "__init__" for s in node.body
            ):
                continue
            class_nodes: list[ast.AST] = [
                *node.decorator_list,
                *(s for s in node.body if not _is_def(s)),
            ]
            _collect_body(
                node.body,
                f"{prefix}{node.name}::",
                config,
                [*inherited_skips, *_skip_uses(class_nodes)],
                [*inherited_decorators, *node.decorator_list],
                out,
                in_testcase=testcase,
            )


def collect_tests(tree: Tree, config: PytestConfig) -> dict[str, tuple[str, ...]]:
    """Every collectable test ID in the tree, with its skip signature."""
    tests: dict[str, tuple[str, ...]] = {}
    for path in sorted(tree.paths()):
        if not _is_collected_file(path, config):
            continue
        try:
            module = ast.parse(tree.read(path), filename=path)
        except (SyntaxError, ValueError, RecursionError) as error:
            raise ValidateError(f"{path} cannot be parsed: {error}") from error
        if _opts_out(module.body):
            continue
        module_skips = _skip_uses([s for s in module.body if not _is_def(s)])
        _collect_body(module.body, f"{path}::", config, module_skips, [], tests)
    return tests


def _sample(ids: list[str]) -> str:
    shown = ", ".join(sorted(ids)[:_REPORTED])
    return shown + (f", and {len(ids) - _REPORTED} more" if len(ids) > _REPORTED else "")


def check(base: Tree, head: Tree) -> list[str]:
    """Reasons the head's tests are weaker than the base's, using the base's pytest config."""
    config = load_config(base)
    before, after = collect_tests(base, config), collect_tests(head, config)
    reasons: list[str] = []
    missing = [i for i in before if i not in after]
    if missing:
        reasons.append(f"{len(missing)} test IDs missing from head: {_sample(missing)}")
    changed = [i for i in before if i in after and before[i] != after[i]]
    changed += [i for i in after if i not in before and after[i]]
    if changed:
        reasons.append(f"skip/xfail changed on {len(changed)} tests: {_sample(changed)}")
    return reasons
