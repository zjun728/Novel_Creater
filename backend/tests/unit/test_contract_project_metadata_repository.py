from __future__ import annotations

import pytest

from backend.repositories.contracts import ContractRepository


class RecordingSession:
    def __init__(self, changed: int):
        self.changed = changed
        self.calls = []

    async def execute(self, sql, args=None):
        self.calls.append((" ".join(sql.split()), args))
        return self.changed


@pytest.mark.asyncio
@pytest.mark.parametrize(("changed", "expected"), [(1, True), (0, False), (2, False)])
async def test_contract_target_sync_participates_in_project_metadata_revision(
    changed,
    expected,
):
    session = RecordingSession(changed)

    result = await ContractRepository().sync_project_contract_targets(
        session,
        project_id="p1",
        target_words=2_400_000,
        target_chapters=720,
        updated_at=123,
        expected_lifecycle_revision=4,
    )

    assert result is expected
    assert session.calls == [(
        "UPDATE projects SET target_words=%s,target_chapters=%s, "
        "lifecycle_revision=lifecycle_revision+1,updated_at=%s WHERE id=%s "
        "AND archived_at IS NULL AND lifecycle_revision=%s",
        (2_400_000, 720, 123, "p1", 4),
    )]
