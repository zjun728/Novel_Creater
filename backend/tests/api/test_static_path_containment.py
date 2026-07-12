import importlib
import os
from pathlib import Path
import subprocess
import tempfile

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def workspace_tmp_path():
    root = REPOSITORY_ROOT / "output" / "pytest-api"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        yield Path(directory)


def paths_module():
    return importlib.import_module("backend.security.paths")


def create_directory_link(link: Path, target: Path):
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"symlink creation is unavailable: {symlink_error}")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("symlink and junction creation are unavailable")


def make_frontend_dist(tmp_path):
    frontend_dist = tmp_path / "frontend" / "dist"
    frontend_dist.mkdir(parents=True)
    index = frontend_dist / "index.html"
    index.write_text("spa-index", encoding="utf-8")
    return frontend_dist, index


def test_spa_file_resolution_returns_a_regular_file_inside_frontend_dist(
    workspace_tmp_path,
):
    frontend_dist, _ = make_frontend_dist(workspace_tmp_path)
    asset = frontend_dist / "assets" / "app.js"
    asset.parent.mkdir()
    asset.write_text("synthetic-app", encoding="utf-8")

    resolved = paths_module().resolve_spa_file(frontend_dist, "assets/app.js")

    assert resolved == asset.resolve(strict=True)


def test_spa_file_resolution_falls_back_to_contained_index_for_a_client_route(
    workspace_tmp_path,
):
    frontend_dist, index = make_frontend_dist(workspace_tmp_path)

    resolved = paths_module().resolve_spa_file(frontend_dist, "projects/synthetic")

    assert resolved == index.resolve(strict=True)


@pytest.mark.parametrize(
    "decoded_path",
    (
        "../outside.txt",
        "..\\outside.txt",
        "%2e%2e%2foutside.txt",
        "%252e%252e%252foutside.txt",
    ),
)
def test_spa_fallback_never_reads_outside_frontend_dist(
    workspace_tmp_path, decoded_path
):
    frontend_dist, index = make_frontend_dist(workspace_tmp_path)
    (workspace_tmp_path / "frontend" / "outside.txt").write_text(
        "outside-secret", encoding="utf-8"
    )

    resolved = paths_module().resolve_spa_file(frontend_dist, decoded_path)

    assert resolved == index.resolve(strict=True)
    assert resolved.read_text(encoding="utf-8") == "spa-index"


def test_spa_fallback_never_follows_an_external_directory_symlink(
    workspace_tmp_path,
):
    frontend_dist, index = make_frontend_dist(workspace_tmp_path)
    outside = workspace_tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside-secret", encoding="utf-8")
    link = frontend_dist / "linked"
    create_directory_link(link, outside)

    resolved = paths_module().resolve_spa_file(frontend_dist, "linked/secret.txt")

    assert resolved == index.resolve(strict=True)
    assert resolved.read_text(encoding="utf-8") == "spa-index"


def test_spa_fallback_requires_the_index_to_be_a_contained_regular_file(
    workspace_tmp_path,
):
    frontend_dist = workspace_tmp_path / "frontend" / "dist"
    frontend_dist.mkdir(parents=True)
    outside_index = workspace_tmp_path / "outside-index.html"
    outside_index.write_text("outside-secret", encoding="utf-8")
    try:
        (frontend_dist / "index.html").symlink_to(outside_index)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_spa_file(frontend_dist, "missing-route")
