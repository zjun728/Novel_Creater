from __future__ import annotations

from contextlib import AbstractAsyncContextManager

import pytest
from pydantic import ValidationError

from backend.services.project_lifecycle import (
    CreateProject,
    ProjectLifecycleService,
)
from backend.services.projections import build_projection_bundle


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
    STEPS = ("guard", "project", "revision", "projection", "contract", "binding")

    def __init__(self):
        self.calls = []
        self.sessions = []
        self.fail_at = None
        self.inserted_command = None
        self.revision = None
        self.projection = None
        self.contract = None

    def _record(self, step, session):
        self.calls.append(step)
        self.sessions.append(session)
        if self.fail_at == step:
            raise RuntimeError(f"{step} failed")

    async def insert_project(self, session, command):
        self.inserted_command = command
        self._record("project", session)

    async def insert_bootstrap_revision(
        self, session, project_id, *, content_hash, idempotency_key
    ):
        self.revision = {
            "project_id": project_id,
            "content_hash": content_hash,
            "key": idempotency_key,
        }
        self._record("revision", session)

    async def insert_projection_head(self, session, project_id, *, content_hash):
        self.projection = {
            "project_id": project_id,
            "content_hash": content_hash,
        }
        self._record("projection", session)

    async def insert_contract_head0(self, session, project_id):
        self.contract = {"project_id": project_id, "revision": 0}
        self._record("contract", session)


class FakeBindingService:
    def __init__(self, events):
        self.events = events
        self.calls = []
        self.fail_at = None

    async def lock_project_creation(self, session):
        self.events.append("guard")
        self.calls.append(("guard", session, None))
        if self.fail_at == "guard":
            raise RuntimeError("guard failed")

    async def initialize_project(self, session, project_id):
        self.events.append("binding")
        self.calls.append(("binding", session, project_id))
        if self.fail_at == "binding":
            raise RuntimeError("binding failed")


def test_title_only_create_uses_internal_product_defaults():
    command = CreateProject(id="p1", title="新项目")

    assert command.model_dump() == {
        "id": "p1",
        "title": "新项目",
        "genre": "",
        "description": "",
        "target_words": 100_000,
        "target_chapters": 100,
    }


def test_create_project_is_strict_frozen_and_forbids_extra_fields():
    with pytest.raises(ValidationError):
        CreateProject(id="p1", title="新项目", target_words="100000")
    with pytest.raises(ValidationError):
        CreateProject(id="p1", title="新项目", unexpected=True)

    command = CreateProject(id="p1", title="新项目")
    with pytest.raises(ValidationError):
        command.title = "changed"


@pytest.mark.asyncio
async def test_create_builds_foundations_and_binding_in_one_transaction():
    repository = FakeProjectRepository()
    bindings = FakeBindingService(repository.calls)
    transactions = FakeTransactionFactory()

    result = await ProjectLifecycleService(
        repository,
        transactions,
        model_binding_service=bindings,
    ).create(CreateProject(id="p1", title="新项目"))

    empty_hash = build_projection_bundle(0, ()).content_hash
    assert repository.calls == list(FakeProjectRepository.STEPS)
    assert repository.inserted_command.genre == ""
    assert repository.inserted_command.target_words == 100_000
    assert repository.revision == {
        "project_id": "p1",
        "content_hash": empty_hash,
        "key": ProjectLifecycleService.bootstrap_idempotency_key("p1"),
    }
    assert repository.projection == {
        "project_id": "p1",
        "content_hash": empty_hash,
    }
    assert repository.contract == {"project_id": "p1", "revision": 0}
    assert bindings.calls == [
        ("guard", repository.sessions[0], None),
        ("binding", repository.sessions[0], "p1"),
    ]
    assert len(
        {
            id(session)
            for session in repository.sessions
            + [call[1] for call in bindings.calls]
        }
    ) == 1
    assert result.model_dump() == {
        "id": "p1",
        "title": "新项目",
        "genre": "",
        "description": "",
        "target_words": 100_000,
        "target_chapters": 100,
        "current_chapter": 0,
        "status": "drafting",
        "archived_at": None,
        "lifecycle_revision": 0,
    }
    assert transactions.commit_count == 1
    assert transactions.rollback_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_step", FakeProjectRepository.STEPS)
async def test_create_rolls_back_every_foundation_failure(failed_step):
    repository = FakeProjectRepository()
    bindings = FakeBindingService(repository.calls)
    transactions = FakeTransactionFactory()
    if failed_step in {"guard", "binding"}:
        bindings.fail_at = failed_step
    else:
        repository.fail_at = failed_step

    with pytest.raises(RuntimeError, match=f"{failed_step} failed"):
        await ProjectLifecycleService(
            repository,
            transactions,
            model_binding_service=bindings,
        ).create(CreateProject(id="p1", title="新项目"))

    assert transactions.commit_count == 0
    assert transactions.rollback_count == 1
