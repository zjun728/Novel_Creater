import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LEGACY_ROUTER_ROOT = REPOSITORY_ROOT / "backend" / "routers"
DOMAIN_ROUTER_ROOT = REPOSITORY_ROOT / "backend" / "domain" / "routers"
SCAN_ROOTS = (
    REPOSITORY_ROOT / "backend",
    REPOSITORY_ROOT / "frontend" / "e2e",
    REPOSITORY_ROOT / "scripts",
)
SOURCE_SUFFIXES = {".py", ".mjs"}
LEGACY_IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+backend\.routers(?:\b|\.)",
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
    "model_bindings.py",
    "novel_downloads.py",
    "planning.py",
    "project_imports.py",
    "project_packages.py",
    "projects.py",
    "providers.py",
    "seeds.py",
    "story_engines.py",
    "style_trials.py",
}


def test_domain_router_inventory_is_exact() -> None:
    actual = {
        path.name
        for path in DOMAIN_ROUTER_ROOT.iterdir()
        if path.is_file() and path.suffix == ".py"
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
            text = path.read_text(encoding="utf-8")
            for match in LEGACY_IMPORT_PATTERN.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                locations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{line}")

    assert locations == [], "Legacy router imports remain:\n" + "\n".join(locations)
