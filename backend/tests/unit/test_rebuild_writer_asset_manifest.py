from __future__ import annotations

import ast
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil

import pytest

from backend.domain.assets import AssetPackageError, load_asset_package
from backend.domain.json_contracts import canonical_hash
from backend.scripts import rebuild_writer_asset_manifest as builder


PRODUCTION_PACKAGE_ROOT = (
    Path(__file__).resolve().parents[2] / "assets" / "writer-core-v1.1.0"
)
PACKAGE_FILENAMES = (
    "style_templates.json",
    "experience_cards.json",
    "manifest.json",
)


def _copy_production_package(tmp_path: Path) -> Path:
    package_root = tmp_path / "writer-core-v1.1.0"
    package_root.mkdir()
    for filename in PACKAGE_FILENAMES:
        shutil.copy2(PRODUCTION_PACKAGE_ROOT / filename, package_root / filename)
    return package_root


def _json_bytes(value: object, *, indent: int | None = 2) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=indent).encode("utf-8") + b"\n"
    )


def _read_values(package_root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    styles = json.loads((package_root / "style_templates.json").read_bytes())
    cards = json.loads((package_root / "experience_cards.json").read_bytes())
    manifest = json.loads((package_root / "manifest.json").read_bytes())
    return styles, cards, manifest


def _write_values(
    package_root: Path,
    styles: list[dict[str, object]],
    cards: list[dict[str, object]],
    manifest: dict[str, object],
) -> None:
    (package_root / "style_templates.json").write_bytes(_json_bytes(styles))
    (package_root / "experience_cards.json").write_bytes(_json_bytes(cards))
    (package_root / "manifest.json").write_bytes(_json_bytes(manifest))


def _snapshot(package_root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        filename: (
            (package_root / filename).read_bytes(),
            (package_root / filename).stat().st_mtime_ns,
        )
        for filename in PACKAGE_FILENAMES
    }


def test_render_asset_json_is_utf8_pretty_and_has_exactly_one_trailing_newline():
    rendered = builder.render_asset_json({"text": "中文", "count": 2})

    assert rendered == '{\n  "text": "中文",\n  "count": 2\n}\n'.encode("utf-8")
    assert rendered.endswith(b"\n")
    assert not rendered.endswith(b"\n\n")


def test_rebuild_values_is_pure_and_recalculates_payload_and_child_hashes():
    styles = [{"stable_key": "style.one", "payload": {"text": "新内容"}, "content_hash": "0" * 64}]
    cards = [{"stable_key": "card.one", "payload": {"method": "method"}, "content_hash": "1" * 64}]
    manifest = {
        "package_version": "writer-core-v1.1.0",
        "styles_file": {"path": "style_templates.json", "sha256": "2" * 64},
        "experience_cards_file": {
            "path": "experience_cards.json",
            "sha256": "3" * 64,
        },
    }
    original = deepcopy((styles, cards, manifest))

    rebuilt_styles, rebuilt_cards, rebuilt_manifest = builder.rebuild_values(
        styles, cards, manifest
    )

    assert (styles, cards, manifest) == original
    assert rebuilt_styles is not styles
    assert rebuilt_cards is not cards
    assert rebuilt_manifest is not manifest
    assert rebuilt_styles[0]["content_hash"] == canonical_hash(styles[0]["payload"])
    assert rebuilt_cards[0]["content_hash"] == canonical_hash(cards[0]["payload"])
    style_bytes = builder.render_asset_json(rebuilt_styles)
    card_bytes = builder.render_asset_json(rebuilt_cards)
    assert rebuilt_manifest["styles_file"]["sha256"] == sha256(style_bytes).hexdigest()
    assert rebuilt_manifest["experience_cards_file"]["sha256"] == sha256(card_bytes).hexdigest()


@pytest.mark.parametrize("drift_kind", ["content_hash", "child_hash", "formatting"])
def test_check_detects_every_drift_without_changing_bytes_or_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift_kind: str,
):
    package_root = _copy_production_package(tmp_path)
    styles, cards, manifest = _read_values(package_root)

    if drift_kind == "content_hash":
        styles[0]["content_hash"] = "0" * 64
        style_bytes = _json_bytes(styles)
        (package_root / "style_templates.json").write_bytes(style_bytes)
        manifest["styles_file"]["sha256"] = sha256(style_bytes).hexdigest()
        (package_root / "manifest.json").write_bytes(_json_bytes(manifest))
    elif drift_kind == "child_hash":
        manifest["experience_cards_file"]["sha256"] = "0" * 64
        (package_root / "manifest.json").write_bytes(_json_bytes(manifest))
    else:
        compact_style_bytes = _json_bytes(styles, indent=None)
        (package_root / "style_templates.json").write_bytes(compact_style_bytes)
        manifest["styles_file"]["sha256"] = sha256(compact_style_bytes).hexdigest()
        (package_root / "manifest.json").write_bytes(_json_bytes(manifest))

    for offset, filename in enumerate(PACKAGE_FILENAMES):
        timestamp_ns = 1_700_000_000_000_000_000 + offset * 1_000_000_000
        os.utime(package_root / filename, ns=(timestamp_ns, timestamp_ns))
    before = _snapshot(package_root)
    monkeypatch.setattr(builder, "PACKAGE_ROOT", package_root)

    assert builder.main(["--check"]) == 1
    assert _snapshot(package_root) == before


def test_write_rebuilds_fixed_package_and_second_check_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    package_root = _copy_production_package(tmp_path)
    styles, cards, manifest = _read_values(package_root)
    styles[0]["content_hash"] = "0" * 64
    cards[0]["content_hash"] = "1" * 64
    manifest["styles_file"]["sha256"] = "2" * 64
    manifest["experience_cards_file"]["sha256"] = "3" * 64
    _write_values(package_root, styles, cards, manifest)
    monkeypatch.setattr(builder, "PACKAGE_ROOT", package_root)

    assert builder.main(["--write"]) == 0
    assert builder.main(["--check"]) == 0
    package = load_asset_package(package_root / "manifest.json", mode="structural")
    assert (len(package.styles), len(package.experience_cards)) == (10, 64)


def test_cli_requires_exactly_one_mode_and_rejects_all_path_arguments():
    with pytest.raises(SystemExit):
        builder.main([])
    with pytest.raises(SystemExit):
        builder.main(["--check", "--write"])
    with pytest.raises(SystemExit):
        builder.main(["--check", "--package-root", "elsewhere"])
    with pytest.raises(SystemExit):
        builder.main(["--check", "elsewhere"])


def test_interrupted_replace_leaves_hash_mismatch_and_cleans_remaining_temps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    package_root = _copy_production_package(tmp_path)
    styles, cards, manifest = _read_values(package_root)
    styles[0]["content_hash"] = "0" * 64
    corrupt_style_bytes = _json_bytes(styles)
    (package_root / "style_templates.json").write_bytes(corrupt_style_bytes)
    manifest["styles_file"]["sha256"] = sha256(corrupt_style_bytes).hexdigest()
    (package_root / "manifest.json").write_bytes(_json_bytes(manifest))
    monkeypatch.setattr(builder, "PACKAGE_ROOT", package_root)

    real_replace = os.replace
    replace_count = 0

    def fail_second_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("injected replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(builder.os, "replace", fail_second_replace)

    assert builder.main(["--write"]) == 1
    assert replace_count == 2
    assert not list(package_root.glob(".*.tmp"))
    with pytest.raises(AssetPackageError, match="styles_file sha256 mismatch"):
        load_asset_package(package_root / "manifest.json", mode="structural")


def test_builder_has_no_database_imports():
    source_path = Path(builder.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert not {
        name
        for name in imported_modules
        if name.startswith(("backend.database", "backend.db", "sqlalchemy"))
    }
