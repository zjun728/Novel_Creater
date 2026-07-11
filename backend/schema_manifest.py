"""Immutable, ordered Writer Core V1 database bootstrap manifest."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re


SCHEMA_DIR = Path(__file__).with_name("schema")
FRAGMENTS = (
    "00_metadata.sql",
    "10_core.sql",
    "20_contracts.sql",
    "30_planning.sql",
    "40_drafts.sql",
    "50_canon.sql",
    "60_projections.sql",
    "70_corpus.sql",
)
STATEMENT_DELIMITER = ";-- statement"
_STATEMENT_SPLIT = re.compile(
    rf"^[ \t]*{re.escape(STATEMENT_DELIMITER)}[ \t]*$",
    re.MULTILINE,
)
_LEADING_SQL_COMMENTS = re.compile(
    r"\A(?:\s+|--[^\n]*(?:\n|\Z)|/\*.*?\*/)*",
    re.DOTALL,
)
_CREATE_TABLE = re.compile(r"^CREATE\s+TABLE\s+([A-Za-z0-9_]+)\s*\(", re.IGNORECASE)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_statements() -> list[str]:
    """Return normalized bootstrap statements in their immutable manifest order."""
    statements: list[str] = []
    for fragment_name in FRAGMENTS:
        fragment = (SCHEMA_DIR / fragment_name).read_text(encoding="utf-8")
        normalized = _normalize_newlines(fragment)
        statements.extend(
            part.strip()
            for part in _STATEMENT_SPLIT.split(normalized)
            if part.strip()
        )
    return statements


def manifest_hash() -> str:
    """Return the SHA-256 of the normalized statement stream."""
    payload = f"\n{STATEMENT_DELIMITER}\n".join(read_statements()).encode("utf-8")
    return sha256(payload).hexdigest()


def created_table_names() -> tuple[str, ...]:
    """Return created table names in manifest order."""
    names: list[str] = []
    for statement in read_statements():
        content_start = _LEADING_SQL_COMMENTS.match(statement).end()
        match = _CREATE_TABLE.match(statement[content_start:])
        if match is not None:
            names.append(match.group(1))
    return tuple(names)
