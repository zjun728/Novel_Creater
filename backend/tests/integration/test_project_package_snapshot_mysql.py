from __future__ import annotations

import asyncio

import aiomysql
import pytest

from backend.database import DatabaseSession
from backend.domain.project_packages import ProjectPackageBusy, ProjectPackageConflict
from backend.repositories.project_packages import PROJECT_OWNED_QUERY_PLANS, ProjectPackageRepository


pytestmark = pytest.mark.mysql

PROJECT_ID = "6b000000-0000-0000-0000-000000000001"


async def _insert_project(session, *, title: str = "snapshot-before", lifecycle_revision: int = 7) -> None:
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,current_chapter,
            lifecycle_revision,created_at,updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (PROJECT_ID, title, "history", "fixture", 1000, 10, "active", 0, lifecycle_revision, 1, 1),
    )


async def _pool(database):
    return await aiomysql.create_pool(**{**database.connection_config, "autocommit": True}, minsize=1, maxsize=2)


@pytest.mark.asyncio
async def test_repository_keeps_every_authority_read_in_one_repeatable_read_snapshot(disposable_mysql) -> None:
    await _insert_project(disposable_mysql.session)
    pool = await _pool(disposable_mysql)
    first_authority_read = asyncio.Event()
    resume = asyncio.Event()

    class PausingSession(DatabaseSession):
        async def fetchall(self, sql, args=None):
            rows = await super().fetchall(sql, args)
            if sql == PROJECT_OWNED_QUERY_PLANS["projects"].sql:
                first_authority_read.set()
                await resume.wait()
            return rows

    try:
        task = asyncio.create_task(ProjectPackageRepository(
            pool=pool, session_factory=PausingSession,
        ).read_snapshot(PROJECT_ID, 7))
        await asyncio.wait_for(first_authority_read.wait(), timeout=5)
        await disposable_mysql.session.execute(
            "UPDATE projects SET title=%s,updated_at=%s WHERE id=%s",
            ("snapshot-after", 2, PROJECT_ID),
        )
        resume.set()
        snapshot = await asyncio.wait_for(task, timeout=10)
    finally:
        pool.close()
        await pool.wait_closed()

    project = next(record for record in snapshot.graph_records if record.entity_type == "project")
    assert project.data["title"] == "snapshot-before"
    current = await disposable_mysql.session.fetchone("SELECT title FROM projects WHERE id=%s", (PROJECT_ID,))
    assert current == {"title": "snapshot-after"}


@pytest.mark.asyncio
async def test_repository_rejects_real_mysql_lifecycle_conflict_and_starting_busy_state(disposable_mysql) -> None:
    await _insert_project(disposable_mysql.session)
    pool = await _pool(disposable_mysql)
    repository = ProjectPackageRepository(pool=pool)
    try:
        with pytest.raises(ProjectPackageConflict, match="project package conflict"):
            await repository.read_snapshot(PROJECT_ID, 6)

        await disposable_mysql.session.execute("SET FOREIGN_KEY_CHECKS=0")
        try:
            await disposable_mysql.session.execute(
                """INSERT INTO draft_operation_attempts
                   (id,project_id,chapter_session_id,operation_type,idempotency_key,request_fingerprint,
                    active_slot,fencing_token,lease_expires_at,base_working_draft_revision,
                    base_working_draft_hash,input_manifest_json,input_manifest_hash,provider_id,
                    model_name_snapshot,last_event_sequence,partial_output_text,partial_output_hash,
                    partial_output_scalars,heartbeat_at,status,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,1,1,2,1,%s,%s,%s,%s,%s,0,%s,%s,0,1,'starting',1,1)""",
                (
                    "6b000000-0000-0000-0000-000000000002", PROJECT_ID,
                    "6b000000-0000-0000-0000-000000000003", "generate_new", "i" * 64, "r" * 64,
                    "b" * 64, "{}", "m" * 64, "6b000000-0000-0000-0000-000000000004",
                    "fixture-model", "", "0" * 64,
                ),
            )
        finally:
            await disposable_mysql.session.execute("SET FOREIGN_KEY_CHECKS=1")

        with pytest.raises(ProjectPackageBusy, match="project package busy"):
            await repository.read_snapshot(PROJECT_ID, 7)
    finally:
        pool.close()
        await pool.wait_closed()
