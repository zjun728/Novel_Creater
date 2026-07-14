import importlib
import os
from pathlib import Path
import subprocess

import pytest


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


def test_resolve_under_root_returns_an_existing_nested_regular_file(workspace_tmp_path):
    root = workspace_tmp_path / "corpus"
    chapter = root / "nested" / "Chapter.TXT"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("synthetic", encoding="utf-8")

    resolved = paths_module().resolve_under_root(
        root, "nested/Chapter.TXT", suffix=".txt"
    )

    assert resolved == chapter.resolve(strict=True)


@pytest.mark.parametrize(
    "relative",
    (
        "/chapter.txt",
        "\\chapter.txt",
        "C:\\chapter.txt",
        "C:chapter.txt",
        "\\\\server\\share\\chapter.txt",
    ),
)
def test_resolve_under_root_rejects_absolute_or_drive_qualified_input(
    workspace_tmp_path, relative
):
    root = workspace_tmp_path / "corpus"
    root.mkdir()

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_under_root(root, relative)


def test_resolve_under_root_rejects_an_existing_absolute_path(workspace_tmp_path):
    root = workspace_tmp_path / "corpus"
    root.mkdir()
    chapter = root / "chapter.txt"
    chapter.write_text("synthetic", encoding="utf-8")

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_under_root(root, str(chapter))


@pytest.mark.parametrize(
    "relative",
    (
        "../outside.txt",
        "nested/../../outside.txt",
        "nested\\..\\..\\outside.txt",
        "%2e%2e%2foutside.txt",
        "%2E%2E\\outside.txt",
        "%252e%252e%252foutside.txt",
    ),
)
def test_resolve_under_root_rejects_plain_mixed_and_encoded_traversal(
    workspace_tmp_path, relative
):
    root = workspace_tmp_path / "corpus"
    root.mkdir()
    (workspace_tmp_path / "outside.txt").write_text("outside", encoding="utf-8")

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_under_root(root, relative, suffix=".txt")


def test_resolve_under_root_checks_suffix_case_insensitively(workspace_tmp_path):
    root = workspace_tmp_path / "corpus"
    root.mkdir()
    disguised = root / "chapter.txt.exe"
    disguised.write_text("synthetic", encoding="utf-8")

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_under_root(root, disguised.name, suffix=".txt")


def test_resolve_under_root_requires_an_exact_path_suffix(workspace_tmp_path):
    root = workspace_tmp_path / "corpus"
    root.mkdir()
    suffix_shaped_name = root / ".txt"
    suffix_shaped_name.write_text("synthetic", encoding="utf-8")
    assert suffix_shaped_name.suffix == ""

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_under_root(root, suffix_shaped_name.name, suffix=".txt")


@pytest.mark.parametrize("missing", ("root", "file"))
def test_resolve_under_root_requires_root_and_file_to_exist_strictly(
    workspace_tmp_path, missing
):
    root = workspace_tmp_path / "corpus"
    if missing == "file":
        root.mkdir()

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_under_root(root, "missing.txt", suffix=".txt")


def test_resolve_under_root_rejects_a_directory_instead_of_a_regular_file(
    workspace_tmp_path,
):
    root = workspace_tmp_path / "corpus"
    directory = root / "chapter.txt"
    directory.mkdir(parents=True)

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_under_root(root, directory.name, suffix=".txt")


def test_resolve_under_root_rejects_a_symlink_escape(workspace_tmp_path):
    root = workspace_tmp_path / "corpus"
    outside = workspace_tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "chapter.txt").write_text("outside", encoding="utf-8")
    link = root / "linked"
    create_directory_link(link, outside)

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_under_root(root, "linked/chapter.txt", suffix=".txt")


def test_resolve_under_root_rejects_a_symlink_even_when_its_target_is_inside_root(
    workspace_tmp_path,
):
    root = workspace_tmp_path / "corpus"
    root.mkdir()
    target = root / "chapter.txt"
    target.write_text("synthetic", encoding="utf-8")
    alias = root / "alias.txt"
    try:
        alias.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    module = paths_module()
    with pytest.raises(module.UnsafeLocalPath):
        module.resolve_under_root(root, alias.name, suffix=".txt")


@pytest.mark.skipif(os.name != "nt", reason="Windows path comparison semantics")
def test_resolve_under_root_honors_windows_case_insensitive_root_semantics(
    workspace_tmp_path,
):
    root = workspace_tmp_path / "CaseSensitiveSpelling"
    root.mkdir()
    chapter = root / "Chapter.TXT"
    chapter.write_text("synthetic", encoding="utf-8")
    differently_cased_root = Path(str(root).swapcase())

    resolved = paths_module().resolve_under_root(
        differently_cased_root, "chapter.txt", suffix=".TXT"
    )

    assert os.path.normcase(str(resolved)) == os.path.normcase(str(chapter.resolve()))
