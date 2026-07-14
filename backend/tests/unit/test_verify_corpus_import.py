from __future__ import annotations

import json
import re

import pytest

from backend.scripts.verify_corpus_import import build_receipt


class RecordingSession:
    def __init__(self):
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        return {
            "id": "source-1",
            "relative_path": "safe/book.txt",
            "source_hash": "a" * 64,
            "encoding": "utf-8",
            "file_size": 123,
            "parser_version": "parser-v1",
            "normalizer_version": "normalizer-v1",
            "fragmenter_version": "fragmenter-v1",
            "index_version": "index-v1",
            "status": "analyzed",
            "chapter_count": 2,
            "fragment_count": 3,
            "first_byte_start": 0,
            "last_byte_end": 123,
            "first_char_start": 0,
            "last_char_end": 88,
            "normalized_text": "BODY_TEXT_SENTINEL",
            "absolute_path": "C:/private/SECRET_PATH_SENTINEL/book.txt",
            "password": "SECRET_PASSWORD_SENTINEL",
        }


@pytest.mark.asyncio
async def test_verifier_uses_select_only_and_emits_exact_bounded_receipt():
    session = RecordingSession()

    receipt = await build_receipt(session, source_id="source-1")

    assert set(receipt) == {
        "relativePath", "rawHash", "encoding", "size", "chapterCount",
        "fragmentCount", "firstByteStart", "lastByteEnd", "firstCharStart",
        "lastCharEnd", "parserVersion", "normalizerVersion",
        "fragmenterVersion", "indexVersion", "status",
    }
    assert receipt["relativePath"] == "safe/book.txt"
    assert receipt["rawHash"] == "a" * 64
    assert session.calls
    forbidden = re.compile(
        r"\b(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|TRUNCATE)\b",
        re.IGNORECASE,
    )
    for sql, args in session.calls:
        assert sql.lstrip().upper().startswith("SELECT")
        assert forbidden.search(sql) is None
        assert args == ("source-1",)
        assert "ORDER BY s.imported_at DESC,s.id DESC LIMIT 1" in sql
        assert "ORDER BY s.revision DESC" not in sql
    rendered = json.dumps(receipt)
    assert "BODY_TEXT_SENTINEL" not in rendered
    assert "SECRET_" not in rendered
    assert "C:/private" not in rendered


@pytest.mark.asyncio
async def test_verifier_accepts_exactly_one_source_selector():
    session = RecordingSession()
    with pytest.raises(ValueError, match="exactly one"):
        await build_receipt(session)
    with pytest.raises(ValueError, match="exactly one"):
        await build_receipt(session, source_id="id", source_hash="a" * 64)


@pytest.mark.asyncio
async def test_verifier_missing_source_is_stable_and_non_sensitive():
    class MissingSession(RecordingSession):
        async def fetchone(self, sql, args=None):
            self.calls.append((sql, args))
            return None

    with pytest.raises(LookupError, match="corpus source not found"):
        await build_receipt(MissingSession(), source_hash="b" * 64)
