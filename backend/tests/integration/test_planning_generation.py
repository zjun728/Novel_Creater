from __future__ import annotations

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.repositories.planning import PlanningRepository
from backend.services.planning import CreatePlanningDraft
from backend.tests.integration.test_contract_drafts import PROJECT
from backend.tests.integration.test_planning_aggregate_lifecycle import _prepare


pytestmark = pytest.mark.mysql

NOW = 1_940_000_000_000


async def _attempt_row(session, draft_id, *, number: int):
    binding = await session.fetchone(
        """SELECT head.binding_revision_id,head.revision AS binding_revision,
                  head.content_hash AS binding_hash,item.provider_id,
                  item.model_name_snapshot
             FROM project_model_binding_heads head
             JOIN project_model_binding_items item
               ON item.binding_revision_id=head.binding_revision_id
              AND item.task_key='planning'
            WHERE head.project_id=%s""",
        (PROJECT,),
    )
    return {
        "id": f"96000000-0000-0000-0000-{number:012d}",
        "project_id": PROJECT,
        "draft_id": draft_id,
        "operation_id": f"operation-{number}",
        "idempotency_key": f"planning-generation-{number}",
        "request_fingerprint": f"{number:x}".rjust(64, "0"),
        "binding_revision_id": binding["binding_revision_id"],
        "binding_revision": binding["binding_revision"],
        "binding_hash": binding["binding_hash"],
        "provider_id": binding["provider_id"],
        "model_name_snapshot": binding["model_name_snapshot"],
        "fencing_token": number,
        "lease_expires_at": NOW + 60_000,
        "input_manifest_json": canonical_json({"draftId": draft_id}),
        "input_manifest_hash": canonical_hash({"draftId": draft_id}),
        "created_at": NOW + number,
        "updated_at": NOW + number,
    }


@pytest.mark.asyncio
async def test_real_mysql_generation_fences_terminal_writes_and_loads_exact_draft(
    disposable_mysql,
):
    service = await _prepare(disposable_mysql)
    draft = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-generation-draft")
    )
    repository = PlanningRepository()
    first = await _attempt_row(
        disposable_mysql.session,
        draft.draft_id,
        number=1,
    )

    assert await repository.next_fencing_token(
        disposable_mysql.session,
        draft.draft_id,
    ) == 1
    assert await repository.insert_generation_attempt(
        disposable_mysql.session,
        first,
    )
    assert (
        await repository.lock_generation_attempt_by_key(
            disposable_mysql.session,
            PROJECT,
            first["idempotency_key"],
        )
    )["operation_id"] == first["operation_id"]
    assert (
        await repository.lock_generation_attempt(
            disposable_mysql.session,
            PROJECT,
            first["operation_id"],
        )
    )["id"] == first["id"]
    assert (
        await repository.lock_active_generation_attempt(
            disposable_mysql.session,
            draft.draft_id,
        )
    )["id"] == first["id"]
    assert await repository.next_fencing_token(
        disposable_mysql.session,
        draft.draft_id,
    ) == 2
    assert await repository.supersede_generation_attempt(
        disposable_mysql.session,
        project_id=PROJECT,
        operation_id=first["operation_id"],
        fencing_token=1,
        updated_at=NOW + 10,
    )

    first_terminal = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (first["id"],),
    )
    assert first_terminal["status"] == "superseded"
    assert first_terminal["active_slot"] is None

    second = await _attempt_row(
        disposable_mysql.session,
        draft.draft_id,
        number=2,
    )
    assert await repository.insert_generation_attempt(
        disposable_mysql.session,
        second,
    )
    result = {"generated": True, "operation": second["operation_id"]}
    result_json = canonical_json(result)
    result_hash = canonical_hash(result)
    draft_before_stale = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_drafts WHERE id=%s",
        (draft.draft_id,),
    )
    attempt_before_stale = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (second["id"],),
    )
    assert not await repository.load_generation_result_into_draft(
        disposable_mysql.session,
        project_id=PROJECT,
        draft_id=draft.draft_id,
        expected_revision=draft.draft_revision,
        expected_hash=draft.content_hash,
        operation_id=second["operation_id"],
        fencing_token=1,
        content_json=result_json,
        content_hash=result_hash,
        loaded_at=NOW + 20,
    )
    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_drafts WHERE id=%s",
        (draft.draft_id,),
    ) == draft_before_stale
    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (second["id"],),
    ) == attempt_before_stale
    assert await repository.load_generation_result_into_draft(
        disposable_mysql.session,
        project_id=PROJECT,
        draft_id=draft.draft_id,
        expected_revision=draft.draft_revision,
        expected_hash=draft.content_hash,
        operation_id=second["operation_id"],
        fencing_token=2,
        content_json=result_json,
        content_hash=result_hash,
        loaded_at=NOW + 21,
    )

    loaded_draft = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_drafts WHERE id=%s",
        (draft.draft_id,),
    )
    loaded_attempt = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (second["id"],),
    )
    assert loaded_draft["draft_revision"] == draft.draft_revision + 1
    assert loaded_draft["content_hash"] == result_hash
    assert loaded_draft["source_attempt_id"] == second["id"]
    assert loaded_attempt["status"] == "succeeded"
    assert loaded_attempt["active_slot"] is None
    assert loaded_attempt["loaded_draft_revision"] == draft.draft_revision + 1
    assert loaded_attempt["loaded_at"] == NOW + 21
    assert loaded_attempt["updated_at"] == NOW + 21


@pytest.mark.asyncio
async def test_real_mysql_failed_attempt_releases_active_slot_for_next_token(
    disposable_mysql,
):
    service = await _prepare(disposable_mysql)
    draft = await service.create_draft(
        CreatePlanningDraft(PROJECT, "create-failure-draft")
    )
    repository = PlanningRepository()
    attempt = await _attempt_row(
        disposable_mysql.session,
        draft.draft_id,
        number=1,
    )
    assert await repository.insert_generation_attempt(
        disposable_mysql.session,
        attempt,
    )
    assert await repository.fail_generation_attempt(
        disposable_mysql.session,
        project_id=PROJECT,
        operation_id=attempt["operation_id"],
        fencing_token=1,
        failure_code="PlanningProviderFailed",
        updated_at=NOW + 30,
    )
    persisted = await disposable_mysql.session.fetchone(
        "SELECT * FROM planning_generation_attempts WHERE id=%s",
        (attempt["id"],),
    )
    assert persisted["status"] == "failed"
    assert persisted["active_slot"] is None
    assert persisted["failure_code"] == "PlanningProviderFailed"
    assert await repository.next_fencing_token(
        disposable_mysql.session,
        draft.draft_id,
    ) == 2
