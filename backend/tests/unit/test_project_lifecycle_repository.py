from __future__ import annotations

import importlib
import importlib.util

import pytest

from backend.repositories import model_bindings, projects, seeds


class RecordingSession:
    def __init__(self, row=None):
        self.row = row or {"id": "p1", "status": "drafting"}
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append((" ".join(sql.split()), args))
        return self.row


@pytest.mark.asyncio
async def test_shared_project_lifecycle_reads_and_locks_only_active_projects():
    spec = importlib.util.find_spec("backend.repositories.project_lifecycle")
    assert spec is not None, "shared project lifecycle repository is missing"
    lifecycle = importlib.import_module("backend.repositories.project_lifecycle")
    session = RecordingSession()

    assert await lifecycle.read_active_project(session, "p1") == session.row
    assert await lifecycle.lock_active_project(session, "p1") == session.row

    assert session.calls == [
        (
            "SELECT * FROM projects WHERE id=%s AND status<>'archived'",
            ("p1",),
        ),
        (
            "SELECT * FROM projects WHERE id=%s AND status<>'archived' FOR UPDATE",
            ("p1",),
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "repository", "method", "guard_name"),
    [
        (projects, projects.ProjectRepository(), "get", "read_active_project"),
        (
            projects,
            projects.ProjectRepository(),
            "lock_active_project",
            "lock_active_project",
        ),
        (seeds, seeds.SeedRepository(), "read_project", "read_active_project"),
        (seeds, seeds.SeedRepository(), "lock_project", "lock_active_project"),
        (
            model_bindings,
            model_bindings.ModelBindingRepository(),
            "read_project",
            "read_active_project",
        ),
        (
            model_bindings,
            model_bindings.ModelBindingRepository(),
            "lock_project",
            "lock_active_project",
        ),
    ],
)
async def test_project_repositories_delegate_active_boundary(
    monkeypatch, module, repository, method, guard_name
):
    calls = []

    async def guard(session, project_id):
        calls.append((session, project_id))
        return {"id": project_id}

    monkeypatch.setattr(module, guard_name, guard, raising=False)
    session = object()

    assert await getattr(repository, method)(session, "p1") == {"id": "p1"}
    assert calls == [(session, "p1")]


@pytest.mark.asyncio
async def test_previous_binding_source_excludes_archived_projects():
    session = RecordingSession()

    await model_bindings.ModelBindingRepository().lock_previous_project(
        session, "p1"
    )

    assert session.calls == [
        (
            "SELECT id FROM projects WHERE id<>%s AND status<>'archived' ORDER BY created_at DESC, id DESC LIMIT 1 FOR UPDATE",
            ("p1",),
        )
    ]
