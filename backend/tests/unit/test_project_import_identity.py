from __future__ import annotations

from uuid import UUID, uuid5

import pytest

from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_import_plans import build_import_identity_map
from backend.domain.json_contracts import canonical_hash


COMMAND_ID = "38ca226b-7199-4cc4-a3e9-98c6993b17c3"


def test_identity_map_uses_command_scoped_uuid5_and_canonical_hash() -> None:
    identities = (("creative-seed", "creative-seed:1"), ("project", "project:1"))

    result = build_import_identity_map(COMMAND_ID, identities)

    expected = {
        identity: str(uuid5(UUID(COMMAND_ID), "/".join(identity)))
        for identity in identities
    }
    canonical_entries = [
        {"entityType": kind, "id": expected[(kind, logical_id)], "logicalId": logical_id}
        for kind, logical_id in sorted(identities)
    ]
    assert dict(result.ids) == expected
    assert result.target_project_id == expected[("project", "project:1")]
    assert result.id_map_hash == canonical_hash({"identities": canonical_entries})
    assert build_import_identity_map(COMMAND_ID, reversed(identities)) == result
    assert build_import_identity_map("d2ca456b-e9b9-40f4-975c-c1ec0b929cba", identities) != result


@pytest.mark.parametrize(
    "identities",
    [
        (("project", "project:1"), ("project", "project:1")),
        (("unknown", "unknown:1"), ("project", "project:1")),
        (("project", "58aa4448-7002-4827-a096-b17d2993fd9d"),),
    ],
)
def test_identity_map_fails_closed_without_echoing_identity(identities) -> None:
    with pytest.raises(ProjectImportInvalid, match="^invalid project import archive$") as raised:
        build_import_identity_map(COMMAND_ID, identities)

    assert raised.value.__cause__ is None
    assert all(logical_id not in str(raised.value) for _, logical_id in identities)
