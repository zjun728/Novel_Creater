"""Pinned Writer Core v1.1 schema fixture for disposable reset tests only.

The payload is the normalized concatenation of the nine ``backend/schema``
fragments at commit ``2bded23e691e3ee8c9c2b488029968c5121c29c5``, immediately
before the v1.2 ownership schema was introduced.
"""

from __future__ import annotations

import base64
import gzip
from hashlib import sha256
from pathlib import Path
import re

from backend.tests.support.disposable_mysql import assert_disposable_name


FROZEN_V11_SCHEMA_VERSION = "writer-core-v1.1.0"
FROZEN_V11_MANIFEST_HASH = (
    "cf993ccf7f000935aaa5777bfb9adda4cd6cbd47cb4f83be5d073d7d3e6b30c5"
)
FROZEN_V11_SQL_SHA256 = (
    "38a4d358e72298f564ee0ebaf4a0e4e5ef68ca50e25abab7713f9fc31c333434"
)
FROZEN_V11_GZIP_SHA256 = (
    "3060719e9e800feedf313aa6b8cdfe8577f8c2e7703eccfd5ce7522db9fca5d0"
)
FROZEN_V11_TABLE_NAMES = (
    "schema_metadata",
    "projects",
    "creative_seeds",
    "creative_seed_revisions",
    "creative_seed_heads",
    "project_selected_seeds",
    "provider_profiles",
    "project_model_binding_revisions",
    "project_model_binding_items",
    "project_model_binding_heads",
    "style_templates",
    "style_template_heads",
    "experience_cards",
    "experience_card_heads",
    "corpus_sources",
    "corpus_chapters",
    "corpus_fragments",
    "corpus_import_runs",
    "story_engine_batches",
    "story_engine_options",
    "project_contract_drafts",
    "creation_contracts",
    "style_contracts",
    "project_contract_heads",
    "contract_confirmation_requests",
    "creation_contract_engine_refs",
    "style_contract_template_refs",
    "creation_contract_experience_refs",
    "creation_contract_corpus_refs",
    "volume_plans",
    "story_blocks",
    "story_stages",
    "scene_tasks",
    "chapter_sessions",
    "working_drafts",
    "draft_candidates",
    "finalization_change_sets",
    "finalization_records",
    "final_chapters",
    "canon_entities",
    "entity_aliases",
    "canon_revisions",
    "canon_events",
    "current_state_projections",
    "memory_views",
    "arc_projections",
    "plot_thread_projections",
    "projection_heads",
    "reference_uses",
)

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "writer_core_v11_schema.sql.gz.b64"
)
_STATEMENT_DELIMITER = ";-- statement"
_STATEMENT_SPLIT = re.compile(
    rf"^[ \t]*{re.escape(_STATEMENT_DELIMITER)}[ \t]*$",
    re.MULTILINE,
)
_CREATE_TABLE = re.compile(r"\bCREATE\s+TABLE\s+([A-Za-z0-9_]+)\s*\(", re.IGNORECASE)


class FrozenV11FixtureError(RuntimeError):
    """The checked-in v1.1 fixture no longer matches its frozen contract."""


def _require_hash(payload: bytes, expected: str, label: str) -> None:
    actual = sha256(payload).hexdigest()
    if actual != expected:
        raise FrozenV11FixtureError(
            f"Frozen v1.1 {label} hash drifted: expected {expected}, got {actual}"
        )


def read_frozen_v11_statements() -> tuple[str, ...]:
    """Decode and verify the exact schema manifest committed before v1.2."""
    try:
        encoded = "".join(_FIXTURE_PATH.read_text(encoding="ascii").split())
        compressed = base64.b64decode(encoded, validate=True)
    except (OSError, ValueError) as exc:
        raise FrozenV11FixtureError("Frozen v1.1 schema fixture is unreadable") from exc
    _require_hash(compressed, FROZEN_V11_GZIP_SHA256, "gzip")
    try:
        raw_sql = gzip.decompress(compressed)
    except gzip.BadGzipFile as exc:
        raise FrozenV11FixtureError("Frozen v1.1 schema fixture is not gzip") from exc
    _require_hash(raw_sql, FROZEN_V11_SQL_SHA256, "SQL")
    text = re.sub(
        r"^-- frozen fragment: [A-Za-z0-9_.-]+\n",
        "",
        raw_sql.decode("utf-8"),
        flags=re.MULTILINE,
    )
    statements = tuple(
        part.strip() for part in _STATEMENT_SPLIT.split(text) if part.strip()
    )
    manifest_payload = f"\n{_STATEMENT_DELIMITER}\n".join(statements).encode("utf-8")
    _require_hash(manifest_payload, FROZEN_V11_MANIFEST_HASH, "manifest")
    table_names = tuple(
        match.group(1)
        for statement in statements
        if (match := _CREATE_TABLE.search(statement)) is not None
    )
    if table_names != FROZEN_V11_TABLE_NAMES:
        raise FrozenV11FixtureError("Frozen v1.1 table inventory drifted")
    return statements


async def initialize_frozen_writer_core_v11(admin_session, database_name: str) -> None:
    """Apply only the frozen v1.1 fixture to an existing disposable database."""
    assert_disposable_name(database_name)
    await admin_session.execute(f"USE `{database_name}`")
    for statement in read_frozen_v11_statements():
        await admin_session.execute(statement)
    await admin_session.execute(
        """INSERT INTO schema_metadata
           (singleton_id,schema_version,manifest_hash,initialized_at)
           VALUES (1,%s,%s,1)""",
        (FROZEN_V11_SCHEMA_VERSION, FROZEN_V11_MANIFEST_HASH),
    )
