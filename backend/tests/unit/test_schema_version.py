from __future__ import annotations

import pytest

from backend.schema_manifest import manifest_hash
from backend.schema_version import (
    EXPECTED_SCHEMA_VERSION,
    SchemaMismatch,
    verify_schema_version,
)


EXPECTED_QUERY = (
    "SELECT schema_version, manifest_hash FROM schema_metadata WHERE singleton_id=1"
)


class FakeVersionSession:
    def __init__(self, row=None, error: Exception | None = None):
        self.row = row
        self.error = error
        self.executed = []

    async def fetchone(self, sql, parameters=None):
        self.executed.append((sql, parameters))
        if self.error is not None:
            raise self.error
        return self.row


@pytest.mark.asyncio
async def test_missing_table_is_rejected_with_initializer_guidance_and_no_ddl():
    session = FakeVersionSession(error=RuntimeError("schema_metadata does not exist"))

    with pytest.raises(SchemaMismatch, match="backend.scripts.initialize_database") as raised:
        await verify_schema_version(session)

    assert "schema_metadata does not exist" in str(raised.value)
    assert session.executed == [(EXPECTED_QUERY, None)]


@pytest.mark.asyncio
async def test_missing_metadata_row_is_rejected_with_reinitialize_guidance():
    session = FakeVersionSession(row=None)

    with pytest.raises(SchemaMismatch, match="reinitialize"):
        await verify_schema_version(session)

    assert session.executed == [(EXPECTED_QUERY, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        {"schema_version": "writer-core-v0", "manifest_hash": "x" * 64},
        {"schema_version": EXPECTED_SCHEMA_VERSION, "manifest_hash": "0" * 64},
    ],
)
async def test_wrong_version_or_hash_is_rejected_with_expected_values(row):
    session = FakeVersionSession(row=row)

    with pytest.raises(SchemaMismatch) as raised:
        await verify_schema_version(session)

    message = str(raised.value)
    assert EXPECTED_SCHEMA_VERSION in message
    assert manifest_hash() in message
    assert "backend.scripts.initialize_database" in message
    assert "reinitialize" in message
    assert session.executed == [(EXPECTED_QUERY, None)]


@pytest.mark.asyncio
async def test_matching_version_and_hash_returns_none_after_one_read():
    session = FakeVersionSession(
        row={
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "manifest_hash": manifest_hash(),
        }
    )

    assert await verify_schema_version(session) is None
    assert session.executed == [(EXPECTED_QUERY, None)]
