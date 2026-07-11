from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from backend.repositories.projects import ProjectRepository
from backend.services.projections import build_projection_bundle
from backend.services.projects import CreateProject, ProjectService, TASK_KEYS


@dataclass
class PreviousSnapshot:
    source_project_id: str
    provider_ids: dict[str, str]


class FakeTransaction(AbstractAsyncContextManager):
    def __init__(self, factory: "FakeTransactionFactory"):
        self.factory = factory
        self.session = object()

    async def __aenter__(self):
        self.factory.enter_count += 1
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.factory.commit_count += 1
            self.factory.repository.committed_rows.extend(
                self.factory.repository.pending_rows
            )
        else:
            self.factory.rollback_count += 1
        self.factory.repository.pending_rows.clear()


class FakeTransactionFactory:
    def __init__(self, repository):
        self.repository = repository
        self.enter_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def __call__(self):
        return FakeTransaction(self)


class FakeProjectRepository:
    STEPS = (
        "project",
        "revision",
        "head",
        "providers",
        "previous",
        "binding",
        "items",
    )

    def __init__(self):
        self.enabled_providers = []
        self.previous_snapshot = None
        self.fail_at = None
        self.calls = []
        self.seen_sessions = []
        self.pending_rows = []
        self.committed_rows = []
        self.inserted_revision = None
        self.inserted_head = None
        self.binding_items = {}
        self.binding_source = None

    def _record(self, step, session, row=None):
        self.calls.append(step)
        self.seen_sessions.append(session)
        if self.fail_at == step:
            raise RuntimeError(f"{step} failed")
        if row is not None:
            self.pending_rows.append((step, row))

    async def insert_project(self, session, command):
        self._record("project", session, command)

    async def insert_bootstrap_revision(
        self, session, project_id, *, content_hash, idempotency_key
    ):
        row = {
            "project_id": project_id,
            "revision_number": 0,
            "parent_revision_number": 0,
            "source_type": "bootstrap",
            "content_hash": content_hash,
            "idempotency_key": idempotency_key,
        }
        self._record("revision", session, row)
        self.inserted_revision = row

    async def insert_projection_head(self, session, project_id, *, content_hash):
        row = {
            "project_id": project_id,
            "canon_revision_number": 0,
            "projection_revision_number": 0,
            "content_hash": content_hash,
        }
        self._record("head", session, row)
        self.inserted_head = row

    async def list_enabled_providers(self, session):
        self._record("providers", session)
        return self.enabled_providers

    async def find_previous_binding_snapshot(self, session, project_id):
        self._record("previous", session)
        return self.previous_snapshot

    async def insert_binding_snapshot(
        self, session, project_id, *, source_project_id
    ):
        self._record("binding", session, project_id)
        self.binding_source = source_project_id
        return "binding-1"

    async def insert_binding_items(self, session, project_id, binding_id, items):
        self._record("items", session, dict(items))
        self.binding_items = {
            task: item["provider_id"] for task, item in items.items()
        }


def command(**overrides):
    values = {
        "id": "p1",
        "title": "新项目",
        "genre": "穿越",
        "description": "",
        "target_words": 100_000,
        "target_chapters": 100,
    }
    values.update(overrides)
    return CreateProject(**values)


@pytest.mark.asyncio
async def test_create_builds_revision_head_and_per_task_binding_on_one_session():
    repository = FakeProjectRepository()
    repository.previous_snapshot = PreviousSnapshot(
        "previous-project", {"writing": "enabled-previous", "seed": "disabled"}
    )
    repository.enabled_providers = [
        {"id": "fallback", "model_name": "fallback-model"},
        {"id": "enabled-previous", "model_name": "previous-model"},
    ]
    transactions = FakeTransactionFactory(repository)

    result = await ProjectService(repository, transactions).create(command())

    empty_hash = build_projection_bundle(0, ()).content_hash
    assert result.id == "p1"
    assert repository.calls == list(FakeProjectRepository.STEPS)
    assert repository.inserted_revision["content_hash"] == empty_hash
    assert repository.inserted_head["content_hash"] == empty_hash
    assert repository.inserted_revision["idempotency_key"] == (
        ProjectService.bootstrap_idempotency_key("p1")
    )
    assert repository.binding_items["writing"] == "enabled-previous"
    assert repository.binding_items["seed"] == "fallback"
    assert set(repository.binding_items) == set(TASK_KEYS)
    assert repository.binding_source == "previous-project"
    assert len({id(session) for session in repository.seen_sessions}) == 1
    assert transactions.commit_count == 1
    assert transactions.rollback_count == 0


@pytest.mark.asyncio
async def test_create_falls_back_each_disabled_or_missing_previous_task():
    repository = FakeProjectRepository()
    repository.previous_snapshot = PreviousSnapshot(
        "previous-project", {"writing": "disabled", "audit": "enabled"}
    )
    repository.enabled_providers = [
        {"id": "fallback", "model_name": "fallback-model"},
        {"id": "enabled", "model_name": "enabled-model"},
    ]
    transactions = FakeTransactionFactory(repository)

    await ProjectService(repository, transactions).create(command())

    assert repository.binding_items["audit"] == "enabled"
    assert repository.binding_items["writing"] == "fallback"
    assert repository.binding_items["planning"] == "fallback"


@pytest.mark.asyncio
async def test_create_without_enabled_provider_keeps_empty_binding_snapshot():
    repository = FakeProjectRepository()
    repository.previous_snapshot = PreviousSnapshot(
        "previous-project", {"writing": "disabled"}
    )
    transactions = FakeTransactionFactory(repository)

    await ProjectService(repository, transactions).create(command())

    assert repository.binding_items == {}
    assert "binding" in repository.calls
    assert repository.binding_source == "previous-project"


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_step", FakeProjectRepository.STEPS)
async def test_create_rolls_back_when_any_foundation_step_fails(failed_step):
    repository = FakeProjectRepository()
    repository.enabled_providers = [
        {"id": "provider", "model_name": "model"}
    ]
    repository.fail_at = failed_step
    transactions = FakeTransactionFactory(repository)

    with pytest.raises(RuntimeError, match=f"{failed_step} failed"):
        await ProjectService(repository, transactions).create(command())

    assert transactions.commit_count == 0
    assert transactions.rollback_count == 1
    assert repository.committed_rows == []


def test_create_project_is_strict_frozen_and_rejects_extra_fields():
    with pytest.raises(ValidationError):
        command(target_words="100000")
    with pytest.raises(ValidationError):
        CreateProject(**command().model_dump(), unexpected=True)
    value = command()
    with pytest.raises(ValidationError):
        value.title = "changed"


class RecordingSession:
    def __init__(self):
        self.calls = []
        self.fetchone_result = None
        self.fetchall_result = []

    async def execute(self, sql, args=None):
        self.calls.append(("execute", " ".join(sql.split()), args))
        return 1

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        return self.fetchone_result

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        return self.fetchall_result


@pytest.mark.asyncio
async def test_repository_orders_enabled_providers_stably():
    session = RecordingSession()
    await ProjectRepository().list_enabled_providers(session)
    assert "ORDER BY sort_order ASC, created_at ASC, id ASC" in session.calls[0][1]


@pytest.mark.asyncio
async def test_repository_finds_previous_project_by_created_at_then_id():
    session = RecordingSession()
    await ProjectRepository().find_previous_binding_snapshot(session, "p1")
    sql = session.calls[0][1]
    assert "p.id<>%s" in sql
    assert "ORDER BY p.created_at DESC, p.id DESC" in sql


@pytest.mark.asyncio
async def test_delete_is_one_project_statement_on_explicit_session():
    session = RecordingSession()
    repository = ProjectRepository()

    await repository.delete(session, "p1")

    assert session.calls == [
        ("execute", "DELETE FROM projects WHERE id=%s", ("p1",))
    ]


@pytest.mark.asyncio
async def test_delete_uses_one_transaction_and_rolls_back_repository_failure():
    class DeleteRepository(FakeProjectRepository):
        async def delete(self, session, project_id):
            self._record("delete", session, project_id)

    repository = DeleteRepository()
    transactions = FakeTransactionFactory(repository)
    service = ProjectService(repository, transactions)

    await service.delete("p1")

    assert transactions.commit_count == 1
    assert repository.committed_rows == [("delete", "p1")]

    repository.fail_at = "delete"
    with pytest.raises(RuntimeError, match="delete failed"):
        await service.delete("p1")
    assert transactions.rollback_count == 1


@pytest.mark.asyncio
async def test_content_state_reads_only_new_seed_head_and_final_chapter_tables():
    class ContentStateSession(RecordingSession):
        async def fetchone(self, sql, args=None):
            self.calls.append(("fetchone", " ".join(sql.split()), args))
            return {
                "seeds_count": 3,
                "canon_head_revision": 2,
                "final_chapters_count": 1,
            }

    session = ContentStateSession()
    state = await ProjectRepository().content_state(session, "p1")

    assert state == {
        "seeds_count": 3,
        "canon_head_revision": 2,
        "has_final_chapters": True,
    }
    sql = session.calls[0][1].lower()
    assert "creative_seeds" in sql
    assert "projection_heads" in sql
    assert "final_chapters" in sql
    for legacy in (
        " chapters ",
        "chapter_versions",
        "temp_drafts",
        "creative_bible",
        "setting_entities",
    ):
        assert legacy not in f" {sql} "
