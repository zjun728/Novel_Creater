import ast
import re
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LEGACY_ROUTER_ROOT = REPOSITORY_ROOT / "backend" / "routers"
DOMAIN_ROUTER_ROOT = REPOSITORY_ROOT / "backend" / "domain" / "routers"
SCAN_ROOTS = (
    REPOSITORY_ROOT / "backend",
    REPOSITORY_ROOT / "frontend" / "e2e",
    REPOSITORY_ROOT / "scripts",
)
SOURCE_SUFFIXES = {".py", ".mjs"}
LEGACY_NAMESPACE = "backend.routers"
EMBEDDED_LEGACY_IMPORT_PATTERN = re.compile(
    r"(?:^|;)[^\S\r\n]*(?:"
    r"(?:from|import)\s+backend\.routers(?:\b|\.)"
    r"|from\s+backend\s+import\s+routers\b"
    r")",
    re.MULTILINE,
)
EXPECTED_ROUTER_FILES = {
    "__init__.py",
    "application_settings.py",
    "assets.py",
    "bibles.py",
    "canon.py",
    "chapter_outlines.py",
    "chapter_sessions.py",
    "contracts.py",
    "corpus.py",
    "finalization.py",
    "helpers.py",
    "market_sources.py",
    "manuscripts.py",
    "model_bindings.py",
    "novel_downloads.py",
    "planning.py",
    "project_imports.py",
    "project_overview.py",
    "project_packages.py",
    "projects.py",
    "providers.py",
    "seeds.py",
    "story_engines.py",
    "style_trials.py",
}


def _is_legacy_namespace(value: object) -> bool:
    return isinstance(value, str) and (
        value == LEGACY_NAMESPACE or value.startswith(f"{LEGACY_NAMESPACE}.")
    )


def _is_dynamic_legacy_import(node: ast.Call) -> bool:
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return False
    if not _is_legacy_namespace(node.args[0].value):
        return False
    function = node.func
    return (
        isinstance(function, ast.Name)
        and function.id == "__import__"
        or isinstance(function, ast.Attribute)
        and function.attr == "import_module"
        and isinstance(function.value, ast.Name)
        and function.value.id == "importlib"
    )


def _is_legacy_sys_modules_target(node: ast.expr) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    container = node.value
    return (
        isinstance(container, ast.Attribute)
        and container.attr == "modules"
        and isinstance(container.value, ast.Name)
        and container.value.id == "sys"
        and isinstance(node.slice, ast.Constant)
        and _is_legacy_namespace(node.slice.value)
    )


def _python_legacy_import_lines(text: str) -> list[int]:
    lines: set[int] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import) and any(
            _is_legacy_namespace(alias.name) for alias in node.names
        ):
            lines.add(node.lineno)
        elif isinstance(node, ast.ImportFrom) and (
            _is_legacy_namespace(node.module)
            or node.module == "backend"
            and any(alias.name == "routers" for alias in node.names)
        ):
            lines.add(node.lineno)
        elif isinstance(node, ast.Call) and _is_dynamic_legacy_import(node):
            lines.add(node.lineno)
        elif isinstance(node, ast.Assign) and any(
            _is_legacy_sys_modules_target(target) for target in node.targets
        ):
            lines.add(node.lineno)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and (
            _is_legacy_sys_modules_target(node.target)
        ):
            lines.add(node.lineno)
    return sorted(lines)


def _legacy_import_lines(path: Path) -> list[int]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return _python_legacy_import_lines(text)
    return [
        text.count("\n", 0, match.start()) + 1
        for match in EMBEDDED_LEGACY_IMPORT_PATTERN.finditer(text)
    ]


def _legacy_namespace_literal_lines(path: Path) -> list[int]:
    if path.resolve() == Path(__file__).resolve():
        return []
    return [
        line_number
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if LEGACY_NAMESPACE in line
    ]


@pytest.mark.parametrize(
    "suffix, source, expected",
    [
        (
            ".py",
            "from importlib import import_module as load_module\n"
            "load_module('backend.routers.projects')\n",
            [2],
        ),
        (
            ".py",
            "import importlib as il\n"
            "il.import_module('backend.routers.projects')\n",
            [2],
        ),
        (
            ".py",
            "import importlib\n"
            "importlib.import_module(name='backend.routers.projects')\n",
            [2],
        ),
        (
            ".py",
            "sys.modules.__setitem__('backend.routers.projects', alias)\n",
            [1],
        ),
        (
            ".py",
            "monkeypatch.setitem(sys.modules, 'backend.routers.projects', alias)\n",
            [1],
        ),
        (
            ".py",
            "from sys import modules\n"
            "modules['backend.routers.projects'] = alias\n",
            [2],
        ),
        (".mjs", "await import('backend.routers.projects');\n", [1]),
        (".py", "safe = True\n# backend.routers is retired\n", [2]),
        (".py", "message = 'backend.routers is retired'\n", [1]),
    ],
    ids=[
        "import-module-alias",
        "importlib-alias",
        "keyword-argument",
        "sys-modules-setitem",
        "monkeypatch-setitem",
        "imported-modules-assignment",
        "mjs-dynamic-import",
        "comment",
        "string",
    ],
)
def test_literal_scanner_detects_retired_namespace_anywhere(
    tmp_path: Path, suffix: str, source: str, expected: list[int]
) -> None:
    path = tmp_path / f"source{suffix}"
    path.write_text(source, encoding="utf-8")

    assert _legacy_namespace_literal_lines(path) == expected


@pytest.mark.parametrize(
    "suffix, source",
    [
        (".py", "value = 'backend.domain.routers.projects'\n"),
        (".mjs", "await import('backend.domain.routers.projects');\n"),
    ],
)
def test_literal_scanner_ignores_canonical_namespace(
    tmp_path: Path, suffix: str, source: str
) -> None:
    path = tmp_path / f"source{suffix}"
    path.write_text(source, encoding="utf-8")

    assert _legacy_namespace_literal_lines(path) == []


def test_literal_scanner_exempts_only_this_resolved_test_file(
    tmp_path: Path,
) -> None:
    lookalike = tmp_path / Path(__file__).name
    lookalike.write_text("# backend.routers\n", encoding="utf-8")

    assert _legacy_namespace_literal_lines(Path(__file__)) == []
    assert _legacy_namespace_literal_lines(lookalike) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "import backend.routers\n",
        "import backend.routers.projects as projects\n",
        "from backend.routers import projects\n",
        "from backend.routers.projects import router\n",
        "from backend import routers as legacy_routers\n",
        "importlib.import_module('backend.routers.projects')\n",
        "__import__('backend.routers.projects')\n",
        "configure(); import backend.routers.projects\n",
        "sys.modules['backend.routers'] = legacy_routers\n",
        "sys.modules['backend.routers.projects']: object = projects\n",
        "sys.modules['backend.routers'] += legacy_routers\n",
    ],
    ids=[
        "import-package",
        "import-child",
        "from-package",
        "from-child",
        "from-backend-import-routers",
        "importlib-import-module",
        "builtin-import",
        "semicolon-import",
        "sys-modules-assign",
        "sys-modules-annassign",
        "sys-modules-augassign",
    ],
)
def test_python_scanner_detects_legacy_router_forms(
    tmp_path: Path, source: str
) -> None:
    path = tmp_path / "source.py"
    path.write_text(source, encoding="utf-8")

    assert _legacy_import_lines(path) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "import backend.domain.routers\n",
        "from backend.domain.routers import projects\n",
        "from backend.domain import routers\n",
        "importlib.import_module('backend.domain.routers.projects')\n",
        "__import__('backend.domain.routers.projects')\n",
        "sys.modules['backend.domain.routers'] = routers\n",
        "value = 'backend.routers.projects'\n",
    ],
)
def test_python_scanner_ignores_canonical_and_non_import_references(
    tmp_path: Path, source: str
) -> None:
    path = tmp_path / "source.py"
    path.write_text(source, encoding="utf-8")

    assert _legacy_import_lines(path) == []


@pytest.mark.parametrize(
    "source, expected",
    [
        ("from backend.routers.projects import router\n", [1]),
        ("bootstrap(); from backend.routers import projects\n", [1]),
        ("from backend.domain.routers import projects\n", []),
    ],
    ids=["line-leading", "semicolon", "canonical"],
)
def test_mjs_scanner_handles_embedded_python_imports(
    tmp_path: Path, source: str, expected: list[int]
) -> None:
    path = tmp_path / "source.mjs"
    path.write_text(source, encoding="utf-8")

    assert _legacy_import_lines(path) == expected


def test_domain_router_inventory_is_exact() -> None:
    actual = {
        path.relative_to(DOMAIN_ROUTER_ROOT).as_posix()
        for path in DOMAIN_ROUTER_ROOT.rglob("*.py")
        if path.is_file()
    }

    assert actual == EXPECTED_ROUTER_FILES


def test_legacy_router_package_is_physically_absent() -> None:
    assert not LEGACY_ROUTER_ROOT.exists()


def test_no_legacy_router_imports_remain() -> None:
    locations: list[str] = []

    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            lines = set(_legacy_import_lines(path))
            lines.update(_legacy_namespace_literal_lines(path))
            for line in sorted(lines):
                locations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{line}")

    assert locations == [], "Legacy router imports remain:\n" + "\n".join(locations)
