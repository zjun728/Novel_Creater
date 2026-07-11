from __future__ import annotations

from contextlib import AbstractAsyncContextManager

import pytest
from pydantic import ValidationError

from backend.repositories.projects import ProjectRepository
from backend.services.projections import build_projection_bundle
from backend.services.projects import CreateProject, ProjectService


class FakeTransaction(AbstractAsyncContextManager):
    def __init__(self, factory):
        self.factory = factory
        self.session = object()

    async def __aenter__(self):
        self.factory.enter_count += 1
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.factory.commit_count += 1
        else:
            self.factory.rollback_count += 1


class FakeTransactionFactory:
    def __init__(self):
        self.enter_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def __call__(self):
        return FakeTransaction(self)


class FakeProjectRepository:
    STEPS = ("project", "revision", "projection", "contract")

    def __init__(self):
        self.calls = []
        self.sessions = []
        self.fail_at = None
        self.revision = None
        self.projection = None
        self.contract = None

    def _record(self, step, session, value=None):
        self.calls.append(step)
        self.sessions.append(session)
        if self.fail_at == step:
            raise RuntimeError(f"{step} failed")
        return value

    async def insert_project(self, session, command):
        self._record("project", session)

    async def insert_bootstrap_revision(
        self, session, project_id, *, content_hash, idempotency_key
    ):
        self.revision = {"content_hash": content_hash, "key": idempotency_key}
        self._record("revision", session)

    async def insert_projection_head(self, session, project_id, *, content_hash):
        self.projection = {"content_hash": content_hash}
        self._record("projection", session)

    async def insert_contract_head0(self, session, project_id):
        self.contract = {"project_id": project_id, "revision": 0}
        self._record("contract", session)


class FakeBindingService:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def initialize_project(self, session, project_id):
        self.calls.append((session, project_id))
        if self.fail:
            raise RuntimeError("binding failed")


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
async def test_create_builds_all_foundations_and_delegates_binding_on_one_session():
    repository = FakeProjectRepository()
    bindings = FakeBindingService()
    transactions = FakeTransactionFactory()

    result = await ProjectService(
        repository,
        transactions,
        model_binding_service=bindings,
    ).create(command())

    empty_hash = build_projection_bundle(0, ()).content_hash
    assert result.id == "p1"
    assert repository.calls == list(FakeProjectRepository.STEPS)
    assert repository.revision["content_hash"] == empty_hash
    assert repository.projection["content_hash"] == empty_hash
    assert repository.contract == {"project_id": "p1", "revision": 0}
    assert repository.revision["key"] == ProjectService.bootstrap_idempotency_key("p1")
    assert bindings.calls == [(repository.sessions[0], "p1")]
    assert len({id(session) for session in repository.sessions}) == 1
    assert transactions.commit_count == 1
    assert transactions.rollback_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_step", (*FakeProjectRepository.STEPS, "binding"))
async def test_create_rolls_back_when_any_foundation_step_fails(failed_step):
    repository = FakeProjectRepository()
    bindings = FakeBindingService()
    transactions = FakeTransactionFactory()
    if failed_step == "binding":
        bindings.fail = True
    else:
        repository.fail_at = failed_step

    with pytest.raises(RuntimeError, match=f"{failed_step} failed"):
        await ProjectService(
            repository,
            transactions,
            model_binding_service=bindings,
        ).create(command())

    assert transactions.commit_count == 0
    assert transactions.rollback_count == 1


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

    async def execute(self, sql, args=None):
        self.calls.append(("execute", " ".join(sql.split()), args))
        return 1

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        return self.fetchone_result


@pytest.mark.asyncio
async def test_repository_inserts_contract_head_zero_on_explicit_session():
    session = RecordingSession()

    await ProjectRepository(clock=lambda: 123).insert_contract_head0(session, "p1")

    assert session.calls == [
        (
            "execute",
            "INSERT INTO project_contract_heads (project_id, revision, creation_contract_id, style_contract_id, creation_hash, style_hash, updated_at) VALUES (%s,0,NULL,NULL,NULL,NULL,%s)",
            ("p1", 123),
        )
    ]


@pytest.mark.asyncio
async def test_delete_is_one_project_statement_on_explicit_session():
    session = RecordingSession()
    await ProjectRepository().delete(session, "p1")
    assert session.calls == [("execute", "DELETE FROM projects WHERE id=%s", ("p1",))]


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
