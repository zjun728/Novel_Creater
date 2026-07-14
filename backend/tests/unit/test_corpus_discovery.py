from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services import corpus_import


def _assert_public_discovery(value: object, root: Path) -> None:
    rendered = json.dumps(value, ensure_ascii=False)
    assert str(root) not in rendered
    assert "absolute" not in rendered.casefold()
    for item in value["items"]:
        assert set(item) == {"relativePath", "byteSize", "preflightStatus"}
        assert not Path(item["relativePath"]).is_absolute()


def test_discovery_recurses_safely_sorts_and_uses_bounded_cursor_pages(tmp_path):
    root = tmp_path / "private-corpus-root"
    root.mkdir()
    (root / "zeta.txt").write_bytes("尾页".encode())
    (root / "Alpha.TXT").write_bytes(b"alpha")
    nested = root / "nested"
    nested.mkdir()
    (nested / "beta.txt").write_bytes(b"beta")
    (root / "cover.jpg").write_bytes(b"not text")

    first = corpus_import.discover_corpus(root, limit=2)
    second = corpus_import.discover_corpus(
        root, cursor=first["nextCursor"], limit=200
    )

    assert [item["relativePath"] for item in first["items"]] == [
        "Alpha.TXT", "nested/beta.txt"
    ]
    assert [item["relativePath"] for item in second["items"]] == ["zeta.txt"]
    assert first["scanStrategy"] == "recursive"
    assert first["reasonCounts"] == {"nonTxt": 1}
    assert first["nextCursor"] and second["nextCursor"] is None
    _assert_public_discovery(first, root)
    _assert_public_discovery(second, root)


@pytest.mark.parametrize("limit", (0, 201, True, "20"))
def test_discovery_rejects_limits_outside_fixed_one_to_200(tmp_path, limit):
    with pytest.raises(ValueError, match="limit"):
        corpus_import.discover_corpus(tmp_path, limit=limit)


def test_discovery_rejects_forged_cursor_without_echoing_root(tmp_path):
    with pytest.raises(corpus_import.CorpusDiscoveryCursorError) as raised:
        corpus_import.discover_corpus(tmp_path, cursor="../private", limit=10)

    assert str(tmp_path) not in str(raised.value)


def test_discovery_counts_unreadable_and_reparse_without_returning_them(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    good = root / "good.txt"
    denied = root / "denied.txt"
    good.write_bytes(b"good")
    denied.write_bytes(b"denied")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    linked = root / "linked.txt"
    try:
        linked.symlink_to(outside)
    except OSError:
        linked = None

    original = corpus_import._is_readable_file
    monkeypatch.setattr(
        corpus_import,
        "_is_readable_file",
        lambda path: False if path.name == "denied.txt" else original(path),
    )

    result = corpus_import.discover_corpus(root, limit=200)

    assert [item["relativePath"] for item in result["items"]] == ["good.txt"]
    assert result["reasonCounts"]["unreadable"] == 1
    if linked is not None:
        assert result["reasonCounts"]["reparse"] == 1
    _assert_public_discovery(result, root)
