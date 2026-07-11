"""Read-only Writer Core schema compatibility verification."""

from __future__ import annotations

from backend.schema_manifest import manifest_hash


EXPECTED_SCHEMA_VERSION = "writer-core-v1.0.0"
_VERSION_QUERY = (
    "SELECT schema_version, manifest_hash FROM schema_metadata WHERE singleton_id=1"
)


class SchemaMismatch(RuntimeError):
    """The connected database is not the exact Writer Core manifest."""


def _guidance() -> str:
    return (
        "Run python -m backend.scripts.initialize_database for a new empty database, "
        "or explicitly reinitialize the development database."
    )


async def verify_schema_version(session) -> None:
    """Verify metadata using one SELECT and never execute schema DDL."""
    try:
        row = await session.fetchone(_VERSION_QUERY)
    except Exception as exc:
        raise SchemaMismatch(
            f"Writer Core schema metadata could not be read ({exc}). {_guidance()}"
        ) from exc

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
