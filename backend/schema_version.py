"""Read-only Writer Core schema compatibility verification."""

from __future__ import annotations

from backend.schema_manifest import manifest_hash


EXPECTED_SCHEMA_VERSION = "writer-core-v1.16.0"
_VERSION_QUERY = (
    "SELECT schema_version, manifest_hash FROM schema_metadata WHERE singleton_id=1"
)


class SchemaMismatch(RuntimeError):
    """The connected database is not the exact Writer Core manifest."""


def _is_missing_table_error(exc: Exception) -> bool:
    errno = getattr(exc, "errno", None)
    if errno == 1146:
        return True
    if not exc.args:
        return False
    value = exc.args[0]
    if value == 1146:
        return True
    return isinstance(value, tuple) and bool(value) and value[0] == 1146


def _guidance() -> str:
    return (
        "Run python -m backend.scripts.initialize_database only for a new empty database. "
        "For an existing database use a backed-up incremental upgrade: "
        "v1.15 to v1.16 uses python -m backend.scripts.upgrade_product_database_v116; "
        "v1.14 to v1.15 uses python -m backend.scripts.upgrade_product_database_v115; "
        "earlier versions must first complete their versioned upgrades."
    )


async def verify_schema_version(session) -> None:
    """Verify metadata using one SELECT and never execute schema DDL."""
    try:
        row = await session.fetchone(_VERSION_QUERY)
    except Exception as exc:
        if not _is_missing_table_error(exc):
            raise
        raise SchemaMismatch(
            f"Writer Core schema metadata table is missing. {_guidance()}"
        ) from None

    expected_hash = manifest_hash()
    if row is None:
        raise SchemaMismatch(
            f"Writer Core schema metadata row is missing. Expected "
            f"{EXPECTED_SCHEMA_VERSION}/{expected_hash}. {_guidance()}"
        )
    actual_version = row["schema_version"]
    actual_hash = row["manifest_hash"]
    if actual_version != EXPECTED_SCHEMA_VERSION or actual_hash != expected_hash:
        raise SchemaMismatch(
            f"Writer Core schema mismatch: expected "
            f"{EXPECTED_SCHEMA_VERSION}/{expected_hash}, got "
            f"{actual_version}/{actual_hash}. {_guidance()}"
        )
