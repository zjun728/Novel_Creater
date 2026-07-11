"""Optional state provenance persistence helpers.

Phase 1.2 does not run migrations automatically. These helpers write provenance
only when the target table already has the provenance columns, so older local
databases remain readable while migrated databases become auditable.
"""
import json
from backend.database import execute, fetchall

PROVENANCE_COLUMNS = {
    "provenance": "json",
    "source_chapter_num": "number",
    "source_version_id": "text",
    "run_id": "text",
    "finalization_id": "text",
    "commit_status": "text",
}

_column_cache: dict[str, set[str]] = {}


async def persist_provenance_if_columns(table: str, record_id: str, data, fallback: dict | None = None):
    if not record_id:
        return
    payload = _as_dict(data)
    fallback_payload = _as_dict(fallback)
    if not _has_meaningful_provenance(payload) and not _has_meaningful_provenance(fallback_payload):
        return

    columns = await _table_columns(table)
    supported = set(PROVENANCE_COLUMNS.keys()).intersection(columns)
    if not supported:
        return

    provenance = normalize_state_provenance(payload, fallback_payload)
    values = {}
    if "provenance" in supported:
        values["provenance"] = json.dumps(provenance, ensure_ascii=False)
    if "source_chapter_num" in supported:
        values["source_chapter_num"] = provenance.get("sourceChapterNum")
    if "source_version_id" in supported:
        values["source_version_id"] = provenance.get("sourceVersionId") or ""
    if "run_id" in supported:
        values["run_id"] = provenance.get("runId") or ""
    if "finalization_id" in supported:
        values["finalization_id"] = provenance.get("finalizationId") or ""
    if "commit_status" in supported:
        values["commit_status"] = provenance.get("commitStatus") or "unknown"
    if not values:
        return

    sets = [f"{key}=%s" for key in values.keys()]
    await execute(
        f"UPDATE {table} SET {', '.join(sets)} WHERE id=%s",
        list(values.values()) + [record_id],
    )


def normalize_state_provenance(data, fallback: dict | None = None):
    payload = _as_dict(data)
    nested = _as_dict(payload.get("provenance") or payload.get("sourceProvenance") or payload.get("snapshotProvenance") or {})
    fallback_payload = _as_dict(fallback)
    return {
        "sourceChapterNum": _number_or_none(
            _pick_non_empty(
                payload.get("sourceChapterNum"),
                payload.get("source_chapter_num"),
                nested.get("sourceChapterNum"),
                nested.get("source_chapter_num"),
                fallback_payload.get("sourceChapterNum"),
                fallback_payload.get("source_chapter_num"),
                payload.get("chapterNum"),
                payload.get("chapter_num"),
            )
        ),
        "sourceVersionId": str(
            _pick_non_empty(
                payload.get("sourceVersionId"),
                payload.get("source_version_id"),
                nested.get("sourceVersionId"),
                nested.get("source_version_id"),
                fallback_payload.get("sourceVersionId"),
                fallback_payload.get("source_version_id"),
                payload.get("versionId"),
                payload.get("version_id"),
                "",
            )
        ),
        "runId": str(_pick_non_empty(
            payload.get("runId"),
            payload.get("run_id"),
            nested.get("runId"),
            nested.get("run_id"),
            fallback_payload.get("runId"),
            fallback_payload.get("run_id"),
            "",
        )),
        "finalizationId": str(_pick_non_empty(
            payload.get("finalizationId"),
            payload.get("finalization_id"),
            nested.get("finalizationId"),
            nested.get("finalization_id"),
            fallback_payload.get("finalizationId"),
            fallback_payload.get("finalization_id"),
            "",
        )),
        "commitStatus": _normalize_commit_status(
            _pick_non_empty(
                payload.get("commitStatus"),
                payload.get("commit_status"),
                nested.get("commitStatus"),
                nested.get("commit_status"),
                fallback_payload.get("commitStatus"),
                fallback_payload.get("commit_status"),
            )
        ),
    }


async def _table_columns(table: str) -> set[str]:
    if table in _column_cache:
        return _column_cache[table]
    rows = await fetchall(f"SHOW COLUMNS FROM {table}")
    columns = {row.get("Field") for row in rows if row.get("Field")}
    _column_cache[table] = columns
    return columns


def _as_dict(data):
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    if hasattr(data, "dict"):
        return data.dict(exclude_none=True)
    if hasattr(data, "model_dump"):
        return data.model_dump(exclude_none=True)
    return {}


def _has_meaningful_provenance(payload: dict) -> bool:
    if not payload:
        return False
    nested = payload.get("provenance") or payload.get("sourceProvenance") or payload.get("snapshotProvenance")
    if isinstance(nested, dict) and any(_is_present(value) for value in nested.values()):
        return True
    for key in (
        "sourceChapterNum",
        "source_chapter_num",
        "sourceVersionId",
        "source_version_id",
        "runId",
        "run_id",
        "finalizationId",
        "finalization_id",
        "commitStatus",
        "commit_status",
    ):
        if _is_present(payload.get(key)):
            return True
    return False


def _pick_non_empty(*values):
    for value in values:
        if _is_present(value):
            return value
    return None


def _is_present(value):
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _number_or_none(value):
    if value in ("", None):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_commit_status(value):
    status = str(value or "unknown").strip().lower()
    if status == "finalized":
        return "final"
    if status == "committed":
        return "committed"
    return status or "unknown"
