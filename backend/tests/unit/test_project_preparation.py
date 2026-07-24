from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace

import pytest

from backend import http_errors
from backend.domain.model_bindings import TASK_KEYS
from backend.repositories.projects import ProjectRepository
from backend.services.bibles import BIBLE_POLICY_VERSION
from backend.services.project_lifecycle import ProjectLifecycleService


def _project(*, archived=False):
    return {
        "id": "project / 一",
        "title": "Preparation",
        "genre": "",
        "description": "",
        "target_words": 100_000,
        "target_chapters": 100,
        "current_chapter": 0,
        "status": "drafting",
        "archived_at": 123 if archived else None,
        "lifecycle_revision": 1 if archived else 0,
    }


def _selection(revision=7):
    return {
        "selection_revision": revision,
        "seed_id": "seed-a",
        "seed_revision_id": "seed-a-r1",
        "seed_hash": "a" * 64,
    }


def _contract(*, ready=True, revision=5, selection_revision=7):
    return SimpleNamespace(
        revision=revision,
        selection_revision=selection_revision,
        creation_contract_id="creation-5",
        creation_hash="b" * 64,
        style_contract_id="style-5",
        style_hash="c" * 64,
        contract_ready=ready,
        seed_ref=SimpleNamespace(
            id="seed-a",
            revision_id="seed-a-r1",
            content_hash="a" * 64,
        ),
        reasons=() if ready else ("selection_drift",),
    )


def _ready_model_tasks():
    return tuple(
        {
            "task_key": task_key,
            "resolution_status": "bound",
            "provider_ready": 1,
            "model_snapshot_matches": 1,
        }
        for task_key in TASK_KEYS
    )


def _bible_basis(*, selection_revision=7):
    return {
        "selection_revision": selection_revision,
        "seed_id": "seed-a",
        "seed_revision_id": "seed-a-r1",
        "seed_hash": "a" * 64,
        "contract_revision": 5,
        "creation_contract_id": "creation-5",
        "creation_hash": "b" * 64,
        "style_contract_id": "style-5",
        "style_hash": "c" * 64,
        "policy_version": BIBLE_POLICY_VERSION,
    }


def _snapshot(
    *,
    archived=False,
    selection=None,
    contract_draft=None,
    bible_head=None,
    bible_draft=None,
    planning_head=None,
    planning_draft=None,
    planning_operation=None,
    chapter_session=None,
    model_tasks=None,
):
    return {
        "project": _project(archived=archived),
        "selection": selection,
        "contract_draft": contract_draft,
        "bible_head": bible_head,
        "bible_draft": bible_draft,
        "planning_head": planning_head,
        "planning_draft": planning_draft,
        "planning_operation": planning_operation,
        "chapter_session": chapter_session,
        "model_tasks": (
            _ready_model_tasks() if model_tasks is None else tuple(model_tasks)
        ),
    }


class _Context(AbstractAsyncContextManager):
    def __init__(self):
        self.session = object()

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return None


class _Repository:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    async def read_preparation_snapshot(self, session, project_id):
        self.calls.append((session, project_id))
        return self.snapshot


class _SqlRecordingSession:
    def __init__(self):
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        return {"id": "project-1"}

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        return []


class _ContractService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def get_head(self, project_id, *, session=None, for_update=False):
        self.calls.append((project_id, session, for_update))
        return self.result


def _service(snapshot, contract):
    repository = _Repository(snapshot)
    contract_service = _ContractService(contract)
    transaction = _Context()
    service = ProjectLifecycleService(
        repository,
        lambda: transaction,
        lambda: _Context(),
        contract_service=contract_service,
    )
    return service, repository, contract_service, transaction


@pytest.mark.asyncio
async def test_preparation_operation_query_is_scoped_to_current_active_draft():
    session = _SqlRecordingSession()

    await ProjectRepository().read_preparation_snapshot(session, "project-1")

    operation_queries = [
        (sql, args)
        for method, sql, args in session.calls
        if method == "fetchone"
        and "JOIN planning_generation_attempts attempt" in sql
    ]
    assert operation_queries == [
        (
            "SELECT attempt.operation_id,attempt.status "
            "FROM planning_drafts draft "
            "JOIN planning_generation_attempts attempt "
            "ON attempt.project_id=draft.project_id "
            "AND attempt.draft_id=draft.id "
            "WHERE draft.project_id=%s "
            "AND draft.active_slot=1 AND draft.status='active' "
            "AND attempt.active_slot=1 AND attempt.status='pending' "
            "ORDER BY attempt.created_at DESC,attempt.operation_id DESC "
            "LIMIT 1",
            ("project-1",),
        )
    ]


@pytest.mark.asyncio
async def test_preparation_uses_one_transaction_and_returns_closed_fields():
    service, repository, contract_service, transaction = _service(
        _snapshot(selection=None),
        {
            "revision": 0,
            "has_contract": False,
            "contract_ready": False,
            "reasons": ("contract_missing",),
        },
    )

    result = await service.preparation("project / 一")

    assert result.model_dump(mode="json", by_alias=True) == {
        "lifecycle": "active",
        "activeSelection": "missing",
        "contract": "missing",
        "bible": "missing",
        "planning": "missing",
        "planningOperation": None,
        "modelTasks": [
            {"taskKey": task_key, "readiness": "ready", "reasons": []}
            for task_key in TASK_KEYS
        ],
        "capabilities": {
            "viewPreparation": True,
            "editContract": False,
            "editBible": False,
            "generateBible": False,
        },
        "nextAction": "select_seed",
        "targetPath": "/projects/project%20%2F%20%E4%B8%80/seeds",
        "reasons": ["selection_missing"],
    }
    assert repository.calls == [(transaction.session, "project / 一")]
    assert contract_service.calls == [
        ("project / 一", transaction.session, False)
    ]


@pytest.mark.asyncio
async def test_preparation_priority_is_operation_session_then_foundation_and_planning():
    planning_path = (
        "/projects/project%20%2F%20%E4%B8%80/planning/volumes"
    )
    cases = (
        (
            _snapshot(
                archived=True,
                planning_head={
                    "head_revision": 2,
                    "planning_revision_id": "planning-2",
                    "head_content_hash": "e" * 64,
                    "revision_id": "planning-2",
                    "revision": 2,
                    "content_hash": "e" * 64,
                    **_bible_basis(),
                    "bible_revision_id": "bible-3",
                    "bible_revision": 3,
                    "bible_hash": "d" * 64,
                },
            ),
            _contract(),
            ("archived_read_only", planning_path, "project_archived"),
        ),
        (
            _snapshot(
                planning_operation={
                    "operation_id": "operation-1",
                    "status": "pending",
                },
            ),
            {"revision": 0, "has_contract": False, "contract_ready": False},
            (
                "recover_planning_operation",
                planning_path,
                "planning_operation_pending",
            ),
        ),
        (
            _snapshot(
                chapter_session={
                    "chapter_session_id": "session-7",
                    "chapter_num": 7,
                    "working_draft_id": "draft-7",
                },
            ),
            {"revision": 0, "has_contract": False, "contract_ready": False},
            (
                "continue_writing",
                "/projects/project%20%2F%20%E4%B8%80/write/chapters/7",
                "chapter_session_active",
            ),
        ),
        (
            _snapshot(selection=None),
            {"revision": 0, "has_contract": False, "contract_ready": False},
            (
                "select_seed",
                "/projects/project%20%2F%20%E4%B8%80/seeds",
                "selection_missing",
            ),
        ),
        (
            _snapshot(
                selection=_selection(),
                contract_draft={
                    **_selection(),
                    "base_head_revision": 0,
                },
            ),
            {"revision": 0, "has_contract": False, "contract_ready": False},
            (
                "continue_contract",
                "/projects/project%20%2F%20%E4%B8%80/contract",
                "contract_draft",
            ),
        ),
        (
            _snapshot(selection=_selection()),
            _contract(ready=False),
            (
                "continue_contract",
                "/projects/project%20%2F%20%E4%B8%80/contract",
                "contract_superseded",
            ),
        ),
        (
            _snapshot(selection=_selection()),
            _contract(),
            (
                "continue_bible",
                "/projects/project%20%2F%20%E4%B8%80/bible",
                "bible_missing",
            ),
        ),
        (
            _snapshot(
                selection=_selection(),
                bible_head={
                    "head_revision": 3,
                    "head_bible_revision_id": "bible-3",
                    "head_content_hash": "d" * 64,
                    "revision_id": "bible-3",
                    "revision": 3,
                    "content_hash": "d" * 64,
                    **_bible_basis(),
                },
            ),
            _contract(),
            ("establish_planning", planning_path, "planning_missing"),
        ),
        (
            _snapshot(
                selection=_selection(),
                bible_head={
                    "head_revision": 3,
                    "head_bible_revision_id": "bible-3",
                    "head_content_hash": "d" * 64,
                    "revision_id": "bible-3",
                    "revision": 3,
                    "content_hash": "d" * 64,
                    **_bible_basis(),
                },
                planning_draft={
                    "draft_id": "planning-draft",
                    "base_head_revision": 0,
                    "status": "active",
                    **_bible_basis(),
                    "bible_revision_id": "bible-3",
                    "bible_revision": 3,
                    "bible_hash": "d" * 64,
                },
            ),
            _contract(),
            ("continue_planning", planning_path, "planning_draft"),
        ),
        (
            _snapshot(
                selection=_selection(),
                bible_head={
                    "head_revision": 3,
                    "head_bible_revision_id": "bible-3",
                    "head_content_hash": "d" * 64,
                    "revision_id": "bible-3",
                    "revision": 3,
                    "content_hash": "d" * 64,
                    **_bible_basis(),
                },
                planning_head={
                    "head_revision": 2,
                    "planning_revision_id": "planning-2",
                    "head_content_hash": "e" * 64,
                    "revision_id": "planning-2",
                    "revision": 2,
                    "content_hash": "e" * 64,
                    **_bible_basis(),
                    "bible_revision_id": "bible-3",
                    "bible_revision": 3,
                    "bible_hash": "d" * 64,
                },
            ),
            _contract(),
            ("phase_boundary_outline", None, "phase_3c_outline"),
        ),
    )

    for snapshot, contract, expected in cases:
        service, *_ = _service(snapshot, contract)
        result = await service.preparation("project / 一")
        assert (result.next_action, result.target_path, result.reasons[0]) == expected


@pytest.mark.asyncio
async def test_pending_planning_operation_is_closed_safe_and_preempts_session():
    sentinel = "must-never-leave-preparation"
    service, *_ = _service(
        _snapshot(
            planning_operation={
                "operation_id": "operation / 一",
                "status": "pending",
                "input_manifest_json": sentinel,
                "model_name_snapshot": sentinel,
                "provider_id": sentinel,
            },
            chapter_session={
                "chapter_session_id": "session-7",
                "chapter_num": 7,
                "working_draft_id": "draft-7",
            },
        ),
        {"revision": 0, "has_contract": False, "contract_ready": False},
    )

    result = await service.preparation("project / 一")
    public = result.model_dump(mode="json", by_alias=True)

    assert result.next_action == "recover_planning_operation"
    assert public["planningOperation"] == {
        "operationId": "operation / 一",
        "status": "pending",
    }
    assert sentinel not in str(public)


@pytest.mark.asyncio
async def test_current_drafts_require_current_selection_and_base_head_revision():
    current_contract_draft = {
        **_selection(),
        "base_head_revision": 5,
    }
    current_bible_draft = {
        "draft_id": "draft-current",
        "base_head_revision": 3,
        **_bible_basis(),
    }
    old_bible_head = {
        "head_revision": 3,
        "head_bible_revision_id": "bible-old-a",
        "head_content_hash": "d" * 64,
        "revision_id": "bible-old-a",
        "revision": 3,
        "content_hash": "d" * 64,
        **_bible_basis(selection_revision=4),
    }
    service, *_ = _service(
        _snapshot(
            selection=_selection(),
            contract_draft=current_contract_draft,
            bible_head=old_bible_head,
            bible_draft=current_bible_draft,
        ),
        _contract(ready=False),
    )

    preparation = await service.preparation("project / 一")

    assert preparation.contract == "draft"
    assert preparation.bible == "superseded"
    assert preparation.next_action == "continue_contract"

    service, *_ = _service(
        _snapshot(
            selection=_selection(),
            bible_head=old_bible_head,
            bible_draft=current_bible_draft,
        ),
        _contract(),
    )
    preparation = await service.preparation("project / 一")
    assert preparation.contract == "current"
    assert preparation.bible == "draft"
    assert preparation.next_action == "continue_bible"


@pytest.mark.asyncio
async def test_contract_draft_requires_the_exact_selected_seed_identity():
    service, *_ = _service(
        _snapshot(
            selection=_selection(),
            contract_draft={
                **_selection(),
                "seed_id": "seed-b",
                "base_head_revision": 0,
            },
        ),
        {"revision": 0, "has_contract": False, "contract_ready": False},
    )

    preparation = await service.preparation("project / 一")

    assert preparation.contract == "missing"
    assert preparation.next_action == "continue_contract"
    assert preparation.reasons[0] == "contract_missing"


@pytest.mark.asyncio
async def test_active_adjustment_drafts_take_priority_over_confirmed_heads():
    current_head = {
        "head_revision": 3,
        "head_bible_revision_id": "bible-3",
        "head_content_hash": "d" * 64,
        "revision_id": "bible-3",
        "revision": 3,
        "content_hash": "d" * 64,
        **_bible_basis(),
    }
    service, *_ = _service(
        _snapshot(
            selection=_selection(),
            contract_draft={
                **_selection(),
                "base_head_revision": 5,
            },
            bible_head=current_head,
        ),
        _contract(),
    )
    preparation = await service.preparation("project / 一")
    assert preparation.contract == "draft"
    assert preparation.next_action == "continue_contract"

    service, *_ = _service(
        _snapshot(
            selection=_selection(),
            bible_head=current_head,
            bible_draft={
                "draft_id": "bible-adjustment",
                "base_head_revision": 3,
                **_bible_basis(),
            },
        ),
        _contract(),
    )
    preparation = await service.preparation("project / 一")
    assert preparation.contract == "current"
    assert preparation.bible == "draft"
    assert preparation.next_action == "continue_bible"


@pytest.mark.asyncio
async def test_a_to_b_to_a_never_reactivates_old_contract_or_bible_generation():
    old_a_head = {
        "head_revision": 2,
        "head_bible_revision_id": "bible-old-a",
        "head_content_hash": "d" * 64,
        "revision_id": "bible-old-a",
        "revision": 2,
        "content_hash": "d" * 64,
        **_bible_basis(selection_revision=1),
    }
    service, *_ = _service(
        _snapshot(selection=_selection(revision=3), bible_head=old_a_head),
        _contract(ready=False, selection_revision=1),
    )

    preparation = await service.preparation("project / 一")

    assert preparation.active_selection == "current"
    assert preparation.contract == "superseded"
    assert preparation.bible == "superseded"
    assert preparation.next_action == "continue_contract"


@pytest.mark.asyncio
async def test_bible_current_requires_exact_head_identity_hash_and_full_contract_basis():
    base = {
        "head_revision": 3,
        "head_bible_revision_id": "bible-3",
        "head_content_hash": "d" * 64,
        "revision_id": "bible-3",
        "revision": 3,
        "content_hash": "d" * 64,
        **_bible_basis(),
    }
    mutations = (
        {"head_bible_revision_id": "bible-other"},
        {"head_content_hash": "e" * 64},
        {"revision_id": "bible-other"},
        {"selection_revision": 8},
        {"seed_hash": "f" * 64},
        {"contract_revision": 6},
        {"creation_contract_id": "creation-other"},
        {"creation_hash": "1" * 64},
        {"style_contract_id": "style-other"},
        {"style_hash": "2" * 64},
        {"policy_version": "old-policy"},
    )
    for mutation in mutations:
        service, *_ = _service(
            _snapshot(
                selection=_selection(),
                bible_head={**base, **mutation},
            ),
            _contract(),
        )
        result = await service.preparation("project / 一")
        assert result.bible == "superseded", mutation


@pytest.mark.asyncio
async def test_only_planning_model_loss_changes_bible_generation_capability():
    rows = list(_ready_model_tasks())
    rows[1] = {
        **rows[1],
        "provider_ready": 0,
    }
    service, *_ = _service(
        _snapshot(selection=_selection(), model_tasks=rows),
        _contract(),
    )
    result = await service.preparation("project / 一")
    assert result.capabilities.edit_contract is True
    assert result.capabilities.edit_bible is True
    assert result.capabilities.generate_bible is False
    assert result.reasons == ("bible_missing", "planning_model_not_ready")
    assert result.model_tasks[1].reasons == ("provider_unavailable",)

    rows = list(_ready_model_tasks())
    rows[0] = {
        **rows[0],
        "resolution_status": "unbound",
        "provider_ready": 0,
        "model_snapshot_matches": 0,
    }
    service, *_ = _service(
        _snapshot(selection=_selection(), model_tasks=rows),
        _contract(),
    )
    result = await service.preparation("project / 一")
    assert result.capabilities.generate_bible is True
    assert "planning_model_not_ready" not in result.reasons
    assert result.model_tasks[0].readiness == "not_ready"


@pytest.mark.asyncio
async def test_public_preparation_drops_provider_identity_and_secret_snapshot_fields():
    sentinel = "must-never-leave-the-server"
    rows = tuple(
        {
            **row,
            "provider_id": f"provider-{index}",
            "provider_name": f"Provider {index}",
            "base_url": "https://provider.invalid/v1",
            "api_key": sentinel,
        }
        for index, row in enumerate(_ready_model_tasks())
    )
    service, *_ = _service(
        _snapshot(selection=_selection(), model_tasks=rows),
        _contract(),
    )

    public_json = (
        await service.preparation("project / 一")
    ).model_dump_json(by_alias=True)

    assert sentinel not in public_json
    assert "provider" not in public_json.lower()
    assert "baseUrl" not in public_json
    assert "apiKey" not in public_json


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        _ready_model_tasks()[:-1],
        _ready_model_tasks() + (_ready_model_tasks()[0],),
        tuple(reversed(_ready_model_tasks())),
    ],
)
async def test_malformed_model_task_snapshot_fails_closed_to_eight_safe_values(rows):
    service, *_ = _service(
        _snapshot(selection=_selection(), model_tasks=rows),
        _contract(),
    )

    result = await service.preparation("project / 一")

    assert tuple(item.task_key for item in result.model_tasks) == TASK_KEYS
    assert all(item.readiness == "not_ready" for item in result.model_tasks)
    assert all(item.reasons == ("binding_incomplete",) for item in result.model_tasks)
    assert result.capabilities.edit_contract is True
    assert result.capabilities.edit_bible is True
    assert result.capabilities.generate_bible is False


@pytest.mark.asyncio
async def test_missing_project_fails_before_contract_read():
    service, repository, contract_service, _ = _service(
        None,
        _contract(),
    )

    with pytest.raises(http_errors.ProjectNotFound):
        await service.preparation("missing")

    assert len(repository.calls) == 1
    assert contract_service.calls == []
