from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType

import pytest

from backend.domain.project_import_plans import (
    ImportInsertBatch, ProjectImportSummary, ProjectPublicationPlan,
    VerifiedProjectPackage, build_publication_plan,
)
from backend.domain.project_packages import (
    ManifestEntry, PAYLOAD_PATHS, PackageRecord, ProjectPackageManifest,
)
from backend.repositories.project_imports import (
    ProjectImportPersistenceError,
    ProjectImportRepository,
)
from backend.services.projections import build_projection_bundle
from backend.security.paths import managed_corpus_storage_key
from backend.tests.support.disposable_mysql import transaction_factory_for


COMMAND_ID = "10000000-0000-4000-8000-000000000005"
TARGET_ID = "20000000-0000-4000-8000-000000000005"
OWNER_ID = "30000000-0000-4000-8000-000000000005"
ENTITY_ID = "40000000-0000-4000-8000-000000000005"
REVISION_ID = "50000000-0000-4000-8000-000000000005"
EVENT_ID = "60000000-0000-4000-8000-000000000005"


def _plan() -> ProjectPublicationPlan:
    empty = build_projection_bundle(0, ())
    return ProjectPublicationPlan(
        command_id=COMMAND_ID,
        target_project_id=TARGET_ID,
        id_map_hash="a" * 64,
        batches=(
            ImportInsertBatch(
                "projects",
                (
                    "id", "title", "genre", "description", "target_words",
                    "target_chapters", "status", "current_chapter", "archived_at",
                    "lifecycle_revision", "created_at", "updated_at",
                ),
                ((TARGET_ID, "Imported", "test", "test", 1000, 10, "drafting", 0, None, 0, 10, 10),),
            ),
            ImportInsertBatch(
                "project_import_provenance",
                (
                    "project_id", "command_id", "record_order", "category",
                    "source_entity_type", "source_logical_id", "payload_json",
                    "content_hash", "created_at",
                ),
                ((TARGET_ID, COMMAND_ID, 1, "provider-history", "provider-history", "provider-history:1", '{"safe":true}', "b" * 64, 10),),
            ),
        ),
        provenance=("provider-history:1",),
        blobs=(),
        expected_projection={
            "revision": empty.revision,
            "currentState": {},
            "memories": {},
            "arcs": {},
            "plotThreads": {},
            "contentHash": empty.content_hash,
        },
        package_hash="3" * 64,
        manifest_hash="4" * 64,
    )


def _canon_plan() -> ProjectPublicationPlan:
    base = _plan()
    event = {
        "id": EVENT_ID,
        "revision_number": 1,
        "event_order": 1,
        "entity_id": ENTITY_ID,
        "fact_kind": "stable_definition",
        "field_path": "state.role",
        "value": "guardian",
        "confirmation_status": "confirmed",
        "evidence": {"source": "import"},
    }
    expected = build_projection_bundle(1, (event,))
    return ProjectPublicationPlan(
        command_id=base.command_id,
        target_project_id=base.target_project_id,
        id_map_hash=base.id_map_hash,
        batches=(
            base.batches[0],
            ImportInsertBatch(
                "canon_entities",
                ("id", "project_id", "entity_type", "canonical_name", "normalized_name", "created_revision", "created_at"),
                ((ENTITY_ID, TARGET_ID, "person", "Guardian", "guardian", 1, 10),),
            ),
            ImportInsertBatch(
                "canon_revisions",
                ("id", "project_id", "revision_number", "parent_revision_number", "idempotency_key", "source_type", "source_id", "content_hash", "created_at"),
                ((REVISION_ID, TARGET_ID, 1, 0, "5" * 64, "manual_test", None, "6" * 64, 10),),
            ),
            ImportInsertBatch(
                "canon_events",
                ("id", "project_id", "revision_id", "revision_number", "event_order", "entity_id", "fact_kind", "field_path", "value_json", "evidence_json", "effective_start_chapter", "effective_end_chapter", "assertion_operator", "value_cardinality", "confirmation_status", "created_at"),
                ((EVENT_ID, TARGET_ID, REVISION_ID, 1, 1, ENTITY_ID, "stable_definition", "state.role", '"guardian"', '{"source":"import"}', 1, None, "equals", "single", "confirmed", 10),),
            ),
        ),
        provenance=(),
        blobs=(),
        expected_projection={
            "revision": expected.revision,
            "currentState": {ENTITY_ID: {"state.role": "guardian"}},
            "memories": {
                ENTITY_ID: [{
                    "eventId": EVENT_ID,
                    "revisionNumber": 1,
                    "eventOrder": 1,
                    "factKind": "stable_definition",
                    "fieldPath": "state.role",
                    "value": "guardian",
                    "evidence": {"source": "import"},
                }],
            },
            "arcs": {},
            "plotThreads": {},
            "contentHash": expected.content_hash,
        },
        package_hash=base.package_hash,
        manifest_hash=base.manifest_hash,
    )


def _corpus_plan() -> ProjectPublicationPlan:
    content_hash = "7" * 64
    records = (
        PackageRecord("project", "project:1", data={
            "title": "Source", "genre": "test", "description": "safe",
            "targetWords": 1000, "targetChapters": 10, "status": "drafting",
            "currentChapter": 0, "archivedAt": None, "lifecycleRevision": 1,
            "createdAt": 1, "updatedAt": 2,
        }),
        PackageRecord("corpus-revision", "corpus-revision:1", revision=1, data={
            "sourceKey": "shared-source", "revision": 1,
            "relativePath": "source.txt", "displayName": "Source", "author": "Author",
            "referenceTags": [], "notes": "", "provenance": {},
            "contentHash": content_hash, "byteLength": 7, "encoding": "utf-8",
            "parserVersion": "v1", "normalizerVersion": "v1",
            "fragmenterVersion": "v1", "indexVersion": "v1", "status": "imported",
            "importedAt": 1, "analyzedAt": None, "createdAt": 1,
            "chapters": [], "fragments": [],
        }),
    )
    entries = tuple(ManifestEntry(path, 0, "0" * 64) for path in sorted(PAYLOAD_PATHS))
    package = VerifiedProjectPackage(
        Path("unused.zip"), "3" * 64, "4" * 64,
        ProjectPackageManifest("project:1", entries, {"project": 1, "corpus-revision": 1}),
        MappingProxyType({(record.entity_type, record.logical_id): record for record in records}),
        MappingProxyType({}),
        ProjectImportSummary(
            "3" * 64, "4" * 64, 1, "Source", "Imported",
            MappingProxyType({"project": 1, "corpus-revision": 1}), False, 0,
        ),
    )
    return build_publication_plan(package, COMMAND_ID, "Imported")


async def _running_command(repository, transaction_factory, *, staged=True, plan=None):
    publication = plan or _plan()
    project_batch = next(batch for batch in publication.batches if batch.table == "projects")
    title = project_batch.rows[0][project_batch.columns.index("title")]
    async with transaction_factory() as session:
        await repository.reserve_command(
            session,
            command_id=COMMAND_ID,
            idempotency_key="1" * 64,
            request_fingerprint="2" * 64,
            package_hash=publication.package_hash,
            manifest_hash=publication.manifest_hash,
            package_version=1,
            target_project_id=publication.target_project_id,
            normalized_title=title,
            now_ms=10,
        )
        await repository.acquire_lease(
            session,
            command_id=COMMAND_ID,
            request_fingerprint="2" * 64,
            owner_token=OWNER_ID,
            now_ms=10,
            lease_expires_at=1000,
        )
        if staged:
            await session.execute(
                """UPDATE project_package_import_commands
                   SET phase='staged',staging_manifest_json=%s WHERE id=%s""",
                ('{"idMapHash":"' + publication.id_map_hash + '"}', COMMAND_ID),
            )


class _FaultRepository(ProjectImportRepository):
    def __init__(self, fail_at: str):
        self.fail_at = fail_at

    async def _publication_checkpoint(self, point: str) -> None:
        if point == self.fail_at:
            raise RuntimeError("injected publication failure")


@pytest.mark.mysql
@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", (
    "before_batch:0",
    "before_batch:1",
    "before_projection_rebuild",
    "before_projection_compare",
    "before_command_success",
))
async def test_failure_at_each_publication_stage_rolls_back_target_and_keeps_fixed_command(
    disposable_mysql, fail_at,
):
    assert disposable_mysql.database_name.startswith("novel_creator_test_")
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    repository = _FaultRepository(fail_at)
    await _running_command(repository, transaction_factory)

    with pytest.raises(ProjectImportPersistenceError):
        async with transaction_factory() as session:
            await repository.publish_project(
                session, _plan(), now=20,
                request_fingerprint="2" * 64, owner_token=OWNER_ID,
            )

    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM projects WHERE id=%s", (TARGET_ID,),
    ) is None
    command = await repository.read_command(
        disposable_mysql.session, command_id=COMMAND_ID, now_ms=20,
    )
    assert command is not None
    assert (command.status, command.phase, command.target_project_id, command.public_error_code) == (
            "running", "staged", None, None,
    )


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_success_publishes_projection_and_command_once_and_replay_is_a_noop(disposable_mysql):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    repository = ProjectImportRepository()
    await _running_command(repository, transaction_factory)

    async with transaction_factory() as session:
        assert await repository.publish_project(
            session, _plan(), now=20,
            request_fingerprint="2" * 64, owner_token=OWNER_ID,
        ) == TARGET_ID
    async with transaction_factory() as session:
        assert await repository.publish_project(
            session, _plan(), now=30,
            request_fingerprint="2" * 64, owner_token=OWNER_ID,
        ) == TARGET_ID

    project_count = await disposable_mysql.session.fetchone(
        "SELECT COUNT(id) AS count FROM projects WHERE id=%s", (TARGET_ID,),
    )
    provenance_count = await disposable_mysql.session.fetchone(
        "SELECT COUNT(project_id) AS count FROM project_import_provenance WHERE project_id=%s",
        (TARGET_ID,),
    )
    head = await disposable_mysql.session.fetchone(
        "SELECT canon_revision_number,projection_revision_number,content_hash FROM projection_heads WHERE project_id=%s",
        (TARGET_ID,),
    )
    command = await repository.read_command(
        disposable_mysql.session, command_id=COMMAND_ID, now_ms=30,
    )
    assert project_count == {"count": 1}
    assert provenance_count == {"count": 1}
    assert head == {
        "canon_revision_number": 0,
        "projection_revision_number": 0,
        "content_hash": _plan().expected_projection["contentHash"],
    }
    assert command is not None
    assert (command.status, command.phase, command.target_project_id) == (
        "succeeded", "succeeded", TARGET_ID,
    )


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_failure_immediately_before_commit_rolls_back_every_publication_row(disposable_mysql):
    base_factory = transaction_factory_for(disposable_mysql.connection_config)
    repository = ProjectImportRepository()
    await _running_command(repository, base_factory)

    @asynccontextmanager
    async def fail_before_commit():
        async with base_factory() as session:
            yield session
            raise RuntimeError("injected commit failure")

    with pytest.raises(RuntimeError, match="injected commit failure"):
        async with fail_before_commit() as session:
            await repository.publish_project(
                session, _plan(), now=20,
                request_fingerprint="2" * 64, owner_token=OWNER_ID,
            )

    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM projects WHERE id=%s", (TARGET_ID,),
    ) is None
    command = await repository.read_command(
        disposable_mysql.session, command_id=COMMAND_ID, now_ms=20,
    )
    assert command is not None
    assert (command.status, command.phase, command.target_project_id) == (
        "running", "staged", None,
    )


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_publication_rebuilds_nonempty_projection_from_persisted_canon(disposable_mysql):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    repository = ProjectImportRepository()
    await _running_command(repository, transaction_factory)

    async with transaction_factory() as session:
        await repository.publish_project(
            session, _canon_plan(), now=20,
            request_fingerprint="2" * 64, owner_token=OWNER_ID,
        )

    current = await disposable_mysql.session.fetchone(
        """SELECT field_path,payload_json,revision_number,content_hash
           FROM current_state_projections WHERE project_id=%s""",
        (TARGET_ID,),
    )
    memory = await disposable_mysql.session.fetchone(
        """SELECT subject_key,payload_json,revision_number,content_hash
           FROM memory_views WHERE project_id=%s""",
        (TARGET_ID,),
    )
    expected_hash = _canon_plan().expected_projection["contentHash"]
    assert current == {
        "field_path": "state.role",
        "payload_json": '"guardian"',
        "revision_number": 1,
        "content_hash": expected_hash,
    }
    assert memory is not None
    assert memory["subject_key"] == ENTITY_ID
    assert memory["revision_number"] == 1
    assert memory["content_hash"] == expected_hash
    assert EVENT_ID in memory["payload_json"]


@pytest.mark.mysql
@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ("phase", "fingerprint", "owner"))
async def test_publication_requires_staged_matching_command_fence(disposable_mysql, mismatch):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    repository = ProjectImportRepository()
    await _running_command(repository, transaction_factory, staged=mismatch != "phase")

    with pytest.raises(Exception, match="^project import command state conflict$"):
        async with transaction_factory() as session:
            await repository.publish_project(
                session, _plan(), now=20,
                request_fingerprint=("9" * 64 if mismatch == "fingerprint" else "2" * 64),
                owner_token=("90000000-0000-4000-8000-000000000009" if mismatch == "owner" else OWNER_ID),
            )

    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM projects WHERE id=%s", (TARGET_ID,),
    ) is None


@pytest.mark.mysql
@pytest.mark.asyncio
@pytest.mark.parametrize(("existing_byte_length", "canonical_key"), (
    (7, True),
    (8, True),
    (7, False),
))
async def test_real_plan_reuses_only_matching_blob_and_scopes_colliding_corpus_source_key(
    disposable_mysql, existing_byte_length, canonical_key,
):
    plan = _corpus_plan()
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    repository = ProjectImportRepository()
    await _running_command(repository, transaction_factory, plan=plan)
    async with transaction_factory() as session:
        await session.execute(
            """INSERT INTO corpus_blobs
               (content_hash,byte_length,storage_key,created_at) VALUES (%s,%s,%s,%s)""",
            (
                "7" * 64,
                existing_byte_length,
                managed_corpus_storage_key("7" * 64) if canonical_key else "sha256/wrong-key",
                1,
            ),
        )
        await session.execute(
            """INSERT INTO corpus_sources
               (id,source_key,archived_at,created_at,updated_at)
               VALUES (%s,%s,NULL,1,1)""",
            ("70000000-0000-4000-8000-000000000005", "shared-source"),
        )

    blob_batch = next(batch for batch in plan.batches if batch.table == "corpus_blobs")
    storage_index = blob_batch.columns.index("storage_key")
    assert blob_batch.rows[0][storage_index] == managed_corpus_storage_key("7" * 64)

    if existing_byte_length == 7 and canonical_key:
        async with transaction_factory() as session:
            await repository.publish_project(
                session, plan, now=20,
                request_fingerprint="2" * 64, owner_token=OWNER_ID,
            )
    else:
        with pytest.raises(Exception, match="^project import command state conflict$"):
            async with transaction_factory() as session:
                await repository.publish_project(
                    session, plan, now=20,
                    request_fingerprint="2" * 64, owner_token=OWNER_ID,
                )
        assert await disposable_mysql.session.fetchone(
            "SELECT id FROM projects WHERE id=%s", (plan.target_project_id,),
        ) is None
        return

    blobs = await disposable_mysql.session.fetchone(
        "SELECT COUNT(content_hash) AS count FROM corpus_blobs WHERE content_hash=%s",
        ("7" * 64,),
    )
    sources = await disposable_mysql.session.fetchall(
        "SELECT source_key FROM corpus_sources ORDER BY source_key",
    )
    assert blobs == {"count": 1}
    assert len(sources) == 2
    assert {row["source_key"] for row in sources} != {"shared-source"}
    assert any(row["source_key"].startswith("import:") for row in sources)
