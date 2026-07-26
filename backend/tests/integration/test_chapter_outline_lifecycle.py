from __future__ import annotations

import importlib

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.services.planning import ConfirmPlanningDraft
from backend.tests.integration.test_planning_aggregate_lifecycle import (
    NOW,
    PROJECT,
    _prepare,
    _save_complete,
)


pytestmark = pytest.mark.mysql


def _repository():
    module = importlib.import_module("backend.repositories.chapter_outlines")
    return module.ChapterOutlineRepository()


async def _clone_row(session, table, where, args, **overrides):
    source = await session.fetchone(
        f"SELECT * FROM {table} WHERE {where}",
        args,
    )
    assert source is not None
    cloned = {**source, **overrides}
    columns = tuple(cloned)
    await session.execute(
        f"""INSERT INTO {table} ({",".join(columns)})
            VALUES ({",".join("%s" for _ in columns)})""",
        tuple(cloned[column] for column in columns),
    )
    return cloned


async def _clone_outline_basis(
    session,
    planning_row,
    binding,
    target_project,
):
    identifiers = {
        "seed": "9b000000-0000-0000-0000-000000000001",
        "seed_revision": "9b000000-0000-0000-0000-000000000002",
        "binding": "9b000000-0000-0000-0000-000000000003",
        "creation": "9b000000-0000-0000-0000-000000000004",
        "style": "9b000000-0000-0000-0000-000000000005",
        "bible": "9b000000-0000-0000-0000-000000000006",
        "planning": "9b000000-0000-0000-0000-000000000007",
    }
    await _clone_row(
        session,
        "projects",
        "id=%s",
        (PROJECT,),
        id=target_project,
        title="Outline isolation project",
    )
    await _clone_row(
        session,
        "creative_seeds",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["seed_id"]),
        id=identifiers["seed"],
        project_id=target_project,
    )
    await _clone_row(
        session,
        "creative_seed_revisions",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["seed_revision_id"]),
        id=identifiers["seed_revision"],
        project_id=target_project,
        seed_id=identifiers["seed"],
    )
    await _clone_row(
        session,
        "project_seed_selection_revisions",
        "project_id=%s AND selection_revision=%s",
        (PROJECT, planning_row["selection_revision"]),
        project_id=target_project,
        seed_id=identifiers["seed"],
        seed_revision_id=identifiers["seed_revision"],
    )
    await _clone_row(
        session,
        "project_model_binding_revisions",
        "project_id=%s AND id=%s",
        (PROJECT, binding["binding_revision_id"]),
        id=identifiers["binding"],
        project_id=target_project,
        source_project_id=None,
    )
    await _clone_row(
        session,
        "creation_contracts",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["creation_contract_id"]),
        id=identifiers["creation"],
        project_id=target_project,
        seed_id=identifiers["seed"],
        seed_revision_id=identifiers["seed_revision"],
        binding_revision_id=identifiers["binding"],
    )
    await _clone_row(
        session,
        "style_contracts",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["style_contract_id"]),
        id=identifiers["style"],
        project_id=target_project,
        creation_contract_id=identifiers["creation"],
    )
    await _clone_row(
        session,
        "creation_bible_revisions",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["bible_revision_id"]),
        id=identifiers["bible"],
        project_id=target_project,
        seed_id=identifiers["seed"],
        seed_revision_id=identifiers["seed_revision"],
        creation_contract_id=identifiers["creation"],
        style_contract_id=identifiers["style"],
        binding_revision_id=identifiers["binding"],
    )
    cloned_planning = await _clone_row(
        session,
        "planning_revisions",
        "project_id=%s AND id=%s",
        (PROJECT, planning_row["id"]),
        id=identifiers["planning"],
        project_id=target_project,
        seed_id=identifiers["seed"],
        seed_revision_id=identifiers["seed_revision"],
        creation_contract_id=identifiers["creation"],
        style_contract_id=identifiers["style"],
        bible_revision_id=identifiers["bible"],
    )
    return cloned_planning, identifiers["binding"]


@pytest.mark.asyncio
async def test_real_mysql_outline_draft_attempt_revision_and_confirmation_lifecycle(
    disposable_mysql,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            "confirm-for-outline-repository",
        )
    )
    repository = _repository()
    session = disposable_mysql.session

    selected = await session.fetchone("SELECT DATABASE() AS database_name")
    assert selected["database_name"] == disposable_mysql.database_name
    assert disposable_mysql.database_name.startswith("novel_creator_test_")

    authorities = await repository.read_current_authorities(session, PROJECT)
    assert authorities["planning_revision_id"] == planning.planning_revision_id
    assert authorities["planning_revision"] == planning.revision
    assert authorities["planning_hash"] == planning.content_hash
    assert isinstance(authorities["planning_content"], dict)
    assert authorities["canon_revision"] == 0
    assert authorities["projection_revision"] == 0

    assert await ChapterSessionRepository().read_active_session(
        session, PROJECT
    ) is None
    assert (
        await ChapterSessionRepository().read_max_final_chapter_number(
            session, PROJECT
        )
        is None
    )

    initial_content = {"z": [], "chapterGoal": "先观察封锁线。"}
    initial_hash = canonical_hash(initial_content)
    draft = {
        "id": "9a000000-0000-0000-0000-000000000001",
        "project_id": PROJECT,
        "chapter_num": 1,
        "base_head_revision": 0,
        "draft_revision": 1,
        "planning_revision_id": planning.planning_revision_id,
        "planning_revision": planning.revision,
        "planning_hash": planning.content_hash,
        "canon_revision": authorities["canon_revision"],
        "projection_revision": authorities["projection_revision"],
        "projection_hash": authorities["projection_hash"],
        "content": initial_content,
        "content_hash": initial_hash,
        "status": "active",
        "created_at": NOW + 10,
        "updated_at": NOW + 10,
    }
    assert await repository.insert_draft(session, draft)
    persisted = await repository.read_active_draft(session, PROJECT, 1)
    assert persisted["content"] == initial_content
    assert "content_json" not in persisted

    saved_content = {"chapterGoal": "确认换岗间隔。", "z": ["later"]}
    saved_hash = canonical_hash(saved_content)
    saved_draft = {
        **draft,
        "draft_revision": 2,
        "content": saved_content,
        "content_hash": saved_hash,
        "updated_at": NOW + 11,
    }
    assert await repository.update_draft_cas(
        session,
        saved_draft,
        expected_revision=1,
        expected_hash=initial_hash,
    )
    assert not await repository.update_draft_cas(
        session,
        {**saved_draft, "draft_revision": 3},
        expected_revision=1,
        expected_hash=initial_hash,
    )

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
    manifest = {"chapterNumber": 1, "safe": True}
    attempt = {
        "id": "9a000000-0000-0000-0000-000000000002",
        "project_id": PROJECT,
        "outline_draft_id": draft["id"],
        "operation_id": "9a000000-0000-0000-0000-000000000003",
        "idempotency_key": "outline-generation-1",
        "request_fingerprint": "d" * 64,
        "binding_revision_id": binding["binding_revision_id"],
        "binding_revision": binding["binding_revision"],
        "binding_hash": binding["binding_hash"],
        "provider_id": binding["provider_id"],
        "model_name_snapshot": binding["model_name_snapshot"],
        "fencing_token": await repository.next_fencing_token(
            session, draft["id"]
        ),
        "lease_expires_at": NOW + 100,
        "input_manifest": manifest,
        "input_manifest_hash": canonical_hash(manifest),
        "created_at": NOW + 12,
        "updated_at": NOW + 12,
    }
    assert await repository.insert_attempt(session, attempt)
    assert (
        await repository.lock_active_attempt(session, draft["id"])
    )["input_manifest"] == manifest

    generated_content = {"chapterGoal": "穿过封锁线。", "z": ["generated"]}
    generated_hash = canonical_hash(generated_content)
    assert await repository.load_result_into_draft(
        session,
        draft["id"],
        2,
        saved_hash,
        attempt["operation_id"],
        attempt["fencing_token"],
        generated_content,
        generated_hash,
        NOW + 13,
    )
    loaded = await repository.read_draft(session, PROJECT, 1, draft["id"])
    completed_attempt = await repository.read_attempt(
        session, PROJECT, attempt["operation_id"]
    )
    assert loaded["draft_revision"] == 3
    assert loaded["content"] == generated_content
    assert loaded["source_attempt_id"] == attempt["id"]
    assert completed_attempt["status"] == "succeeded"
    assert completed_attempt["result_content"] == generated_content
    assert completed_attempt["loaded_outline_draft_revision"] == 3

    revision = {
        "id": "9a000000-0000-0000-0000-000000000004",
        "project_id": PROJECT,
        "chapter_num": 1,
        "revision": 1,
        "parent_revision": 0,
        "planning_revision_id": planning.planning_revision_id,
        "planning_revision": planning.revision,
        "planning_hash": planning.content_hash,
        "canon_revision": authorities["canon_revision"],
        "projection_revision": authorities["projection_revision"],
        "projection_hash": authorities["projection_hash"],
        "content": generated_content,
        "content_hash": generated_hash,
        "created_at": NOW + 14,
    }
    assert await repository.insert_revision(session, revision)
    head = {
        "project_id": PROJECT,
        "chapter_num": 1,
        "revision": 1,
        "outline_revision_id": revision["id"],
        "content_hash": generated_hash,
        "updated_at": NOW + 14,
    }
    assert await repository.advance_head_cas(session, head, 0)
    assert not await repository.advance_head_cas(session, head, 0)
    current = await repository.read_outline_head(session, PROJECT, 1)
    assert current["outline_revision_id"] == revision["id"]
    assert current["content"] == generated_content

    confirmation = {
        "id": "9a000000-0000-0000-0000-000000000005",
        "project_id": PROJECT,
        "chapter_num": 1,
        "chapter_outline_draft_id": draft["id"],
        "draft_revision": 3,
        "draft_hash": generated_hash,
        "expected_head_revision": 0,
        "planning_revision_id": planning.planning_revision_id,
        "planning_revision": planning.revision,
        "planning_hash": planning.content_hash,
        "canon_revision": authorities["canon_revision"],
        "projection_revision": authorities["projection_revision"],
        "projection_hash": authorities["projection_hash"],
        "idempotency_key": "confirm-outline-1",
        "request_fingerprint": "e" * 64,
        "created_at": NOW + 14,
    }
    assert await repository.insert_confirmation_pending(session, confirmation)
    assert await repository.update_draft_cas(
        session,
        {**loaded, "status": "confirmed", "updated_at": NOW + 15},
        expected_revision=3,
        expected_hash=generated_hash,
    )
    assert await repository.finish_confirmation(
        session,
        {
            **confirmation,
            "status": "succeeded",
            "outline_revision_id": revision["id"],
            "result_revision": 1,
            "result_hash": generated_hash,
            "public_error_code": None,
            "completed_at": NOW + 15,
        },
    )
    replay = await repository.find_confirmation(
        session, PROJECT, 1, "confirm-outline-1"
    )
    assert replay["status"] == "succeeded"
    assert replay["outline_revision_id"] == revision["id"]
    history = await repository.list_revisions(session, PROJECT, 1)
    assert tuple(item["revision"] for item in history) == (1,)
    assert history[0]["content"] == generated_content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "extra_args", "terminal_status"),
    (
        ("supersede_attempt", (), "superseded"),
        ("fail_attempt", ("ProviderFailed",), "failed"),
    ),
)
async def test_real_mysql_terminal_attempt_cas_is_project_scoped(
    disposable_mysql,
    method,
    extra_args,
    terminal_status,
):
    planning_service = await _prepare(disposable_mysql)
    saved_planning = await _save_complete(planning_service)
    planning = await planning_service.confirm_draft(
        ConfirmPlanningDraft(
            PROJECT,
            saved_planning.draft_id,
            saved_planning.draft_revision,
            saved_planning.content_hash,
            f"confirm-for-{method}-isolation",
        )
    )
    session = disposable_mysql.session
    repository = _repository()
    authorities = await repository.read_current_authorities(session, PROJECT)
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
    source_planning = await session.fetchone(
        """SELECT * FROM planning_revisions
            WHERE project_id=%s AND id=%s""",
        (PROJECT, planning.planning_revision_id),
    )
    other_project = "9b000000-0000-0000-0000-000000000010"
    other_planning, other_binding = await _clone_outline_basis(
        session,
        source_planning,
        binding,
        other_project,
    )
    shared_operation = "9b000000-0000-0000-0000-000000000011"
    projects = (
        (
            PROJECT,
            "9b000000-0000-0000-0000-000000000012",
            "9b000000-0000-0000-0000-000000000013",
            planning.planning_revision_id,
            planning.revision,
            planning.content_hash,
            binding["binding_revision_id"],
            binding["binding_revision"],
            binding["binding_hash"],
        ),
        (
            other_project,
            "9b000000-0000-0000-0000-000000000014",
            "9b000000-0000-0000-0000-000000000015",
            other_planning["id"],
            other_planning["revision"],
            other_planning["content_hash"],
            other_binding,
            binding["binding_revision"],
            binding["binding_hash"],
        ),
    )
    for index, (
        project_id,
        draft_id,
        attempt_id,
        planning_id,
        planning_revision,
        planning_hash,
        binding_id,
        binding_revision,
        binding_hash,
    ) in enumerate(projects):
        content = {"chapterGoal": f"project-{index}"}
        content_hash = canonical_hash(content)
        assert await repository.insert_draft(
            session,
            {
                "id": draft_id,
                "project_id": project_id,
                "chapter_num": 1,
                "base_head_revision": 0,
                "draft_revision": 1,
                "planning_revision_id": planning_id,
                "planning_revision": planning_revision,
                "planning_hash": planning_hash,
                "canon_revision": authorities["canon_revision"],
                "projection_revision": authorities["projection_revision"],
                "projection_hash": authorities["projection_hash"],
                "content": content,
                "content_hash": content_hash,
                "status": "active",
                "created_at": NOW + 20 + index,
                "updated_at": NOW + 20 + index,
            },
        )
        manifest = {"project": index}
        assert await repository.insert_attempt(
            session,
            {
                "id": attempt_id,
                "project_id": project_id,
                "outline_draft_id": draft_id,
                "operation_id": shared_operation,
                "idempotency_key": f"shared-operation-{index}",
                "request_fingerprint": str(index) * 64,
                "binding_revision_id": binding_id,
                "binding_revision": binding_revision,
                "binding_hash": binding_hash,
                "provider_id": binding["provider_id"],
                "model_name_snapshot": binding["model_name_snapshot"],
                "fencing_token": 1,
                "lease_expires_at": NOW + 100,
                "input_manifest": manifest,
                "input_manifest_hash": canonical_hash(manifest),
                "created_at": NOW + 20 + index,
                "updated_at": NOW + 20 + index,
            },
        )

    terminal = getattr(repository, method)
    changed = await terminal(
        session,
        PROJECT,
        shared_operation,
        1,
        *extra_args,
    )
    rows = await session.fetchall(
        """SELECT project_id,status,active_slot,failure_code
             FROM chapter_outline_generation_attempts
            WHERE operation_id=%s ORDER BY project_id""",
        (shared_operation,),
    )
    by_project = {row["project_id"]: row for row in rows}

    assert by_project[PROJECT]["status"] == terminal_status
    assert by_project[PROJECT]["active_slot"] is None
    assert by_project[other_project] == {
        "project_id": other_project,
        "status": "pending",
        "active_slot": 1,
        "failure_code": None,
    }
    assert changed is True
