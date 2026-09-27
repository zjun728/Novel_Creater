"""Shared mapping from review-local IDs to globally scoped Canon identities."""
from uuid import NAMESPACE_URL, uuid5
from backend.domain.json_contracts import canonical_json


def finalization_storage_id(project_id: str, attempt_id: str, kind: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, canonical_json([
        "finalization-storage-id-v1", project_id, attempt_id, kind, value,
    ])))
