"""Deterministically rebuild the fixed Writer Core asset package."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Sequence

from backend.domain.assets import PACKAGE_VERSION
from backend.domain.json_contracts import canonical_hash


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "assets" / PACKAGE_VERSION
STYLE_FILENAME = "style_templates.json"
CARD_FILENAME = "experience_cards.json"
MANIFEST_FILENAME = "manifest.json"


def render_asset_json(value: object) -> bytes:
    """Render one asset document in the package's canonical file format."""

    return (
        json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )


def rebuild_values(
    styles: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return rebuilt values without mutating any caller-owned input."""

    rebuilt_styles = deepcopy(styles)
    rebuilt_cards = deepcopy(cards)
    rebuilt_manifest = deepcopy(manifest)

    for row in rebuilt_styles:
        row["content_hash"] = canonical_hash(row["payload"])
    for row in rebuilt_cards:
        row["content_hash"] = canonical_hash(row["payload"])

    style_bytes = render_asset_json(rebuilt_styles)
    card_bytes = render_asset_json(rebuilt_cards)
    rebuilt_manifest["styles_file"]["sha256"] = sha256(style_bytes).hexdigest()
    rebuilt_manifest["experience_cards_file"]["sha256"] = sha256(
        card_bytes
    ).hexdigest()
    return rebuilt_styles, rebuilt_cards, rebuilt_manifest


def _package_paths() -> tuple[Path, Path, Path]:
    return (
        PACKAGE_ROOT / STYLE_FILENAME,
        PACKAGE_ROOT / CARD_FILENAME,
        PACKAGE_ROOT / MANIFEST_FILENAME,
    )


def _read_values() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    style_path, card_path, manifest_path = _package_paths()
    styles = json.loads(style_path.read_bytes())
    cards = json.loads(card_path.read_bytes())
    manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(styles, list) or not isinstance(cards, list):
        raise ValueError("asset children must be arrays")
    if not isinstance(manifest, dict):
        raise ValueError("asset manifest must be an object")
    return styles, cards, manifest


def _rebuilt_documents() -> tuple[bytes, bytes, bytes]:
    styles, cards, manifest = _read_values()
    rebuilt_styles, rebuilt_cards, rebuilt_manifest = rebuild_values(
        styles,
        cards,
        manifest,
    )
    return (
        render_asset_json(rebuilt_styles),
        render_asset_json(rebuilt_cards),
        render_asset_json(rebuilt_manifest),
    )


def _check() -> bool:
    expected_documents = _rebuilt_documents()
    return all(
        path.read_bytes() == expected
        for path, expected in zip(_package_paths(), expected_documents, strict=True)
    )


def _write_temp_sibling(target: Path, content: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temp_path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _write() -> None:
    documents = _rebuilt_documents()
    targets = _package_paths()
    remaining_temps: set[Path] = set()
    replacements: list[tuple[Path, Path]] = []
    try:
        for target, content in zip(targets, documents, strict=True):
            temp_path = _write_temp_sibling(target, content)
            remaining_temps.add(temp_path)
            replacements.append((temp_path, target))

        for temp_path, target in replacements:
            os.replace(temp_path, target)
            remaining_temps.remove(temp_path)
    finally:
        for temp_path in remaining_temps:
            temp_path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild the fixed Writer Core asset package hashes."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.check:
            return 0 if _check() else 1
        _write()
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
