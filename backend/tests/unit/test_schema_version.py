from __future__ import annotations

import traceback

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
V1_4_MANIFEST_HASH = "d4ca983a7748cdf1e05867a2ab4ccb958e76bf82a59aab8e56398693af4dc428"


def test_expected_schema_version_is_writer_core_v1_5():
    assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.5.0"


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


class DriverError(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_missing_table_is_rejected_with_initializer_guidance_and_no_ddl():
    raw_driver_message = "Table schema_metadata missing; host=DRIVER_SENTINEL"
    session = FakeVersionSession(error=DriverError(1146, raw_driver_message))

    with pytest.raises(SchemaMismatch, match="backend.scripts.initialize_database") as raised:
        await verify_schema_version(session)

    assert raw_driver_message not in str(raised.value)
    assert "DRIVER_SENTINEL" not in str(raised.value)
    assert "DRIVER_SENTINEL" not in "".join(
        traceback.format_exception(raised.value)
    )
    assert raised.value.__cause__ is None
    assert session.executed == [(EXPECTED_QUERY, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        DriverError(1045, "Access denied; password=DRIVER_SENTINEL"),
        DriverError(2003, "Connection timed out to DRIVER_SENTINEL"),
        RuntimeError("unclassified operational failure DRIVER_SENTINEL"),
    ],
)
async def test_non_missing_table_errors_are_reraised_unchanged(error):
    session = FakeVersionSession(error=error)

    with pytest.raises(type(error)) as raised:
        await verify_schema_version(session)

    assert raised.value is error
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
async def test_v1_4_database_is_rejected_read_only():
    session = FakeVersionSession(
        row={
            "schema_version": "writer-core-v1.4.0",
            "manifest_hash": V1_4_MANIFEST_HASH,
        }
    )

    with pytest.raises(SchemaMismatch) as raised:
        await verify_schema_version(session)

    assert "writer-core-v1.5.0" in str(raised.value)
    assert "writer-core-v1.4.0" in str(raised.value)
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
