"""Prepare and verify the disposable Phase 6B project-backup authority."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import os
from pathlib import Path

from backend.database import close_pool, connection, get_pool, transaction
from backend.domain.contracts import FrozenCorpusFragment
from backend.routers.projects import _service as project_lifecycle_service
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.corpus import CorpusRepository
from backend.repositories.project_packages import ProjectPackageRepository
from backend.scripts.prepare_phase4b2_browser_db import assert_database_name
from backend.scripts.prepare_phase6a_browser_db import (
    CANDIDATE_SENTINEL,
    PROJECT,
    WORKING_SENTINEL,
    prepare as prepare_finalized_project,
)
from backend.security.paths import (
    ensure_managed_corpus_blob_parent,
    managed_corpus_storage_key,
)
from backend.services.draft_operations import DraftOperationService, StartDraftOperation
from backend.services.corpus_import import CorpusImportService
from backend.services.contracts import CorpusSourceRef


SECRET_SENTINEL = "phase6b-private-api-key-sentinel"
BASE_URL_SENTINEL = "https://phase6b-private.invalid/v1"
CORPUS_UNIT = b"PHASE6B_OWNED_CORPUS_BYTES\n"
CORPUS_BYTES = (CORPUS_UNIT * ((8 * 1024 * 1024 // len(CORPUS_UNIT)) + 1))[: 8 * 1024 * 1024]
CORPUS_HASH = sha256(CORPUS_BYTES).hexdigest()
CORPUS_SOURCE_BYTES = "第一章 受控语料\n这段语料只用于备份闭包验证。".encode("utf-8")
PROVIDER_NAME = "Phase6A local deny"


class PreparationSnapshotTimeout(RuntimeError):
    pass


class ContractHeadTimeout(RuntimeError):
    pass


class PreparationServiceTimeout(RuntimeError):
    pass


class ProviderMustNotRun:
    async def generate(self, **_kwargs):
        raise RuntimeError("Phase6B terminal operation must not invoke Provider")

    def stream(self, **_kwargs):
        raise RuntimeError("Phase6B terminal operation must not invoke Provider")


def _record_state(value: int) -> None:
    target = os.environ.get("PHASE6B_FIXTURE_STATE_PATH", "")
    if target:
        Path(target).write_text(str(value), encoding="ascii")


def _authority(database_name: str) -> tuple[str, Path]:
    database = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database:
        raise RuntimeError("Phase6B fixture database authority mismatch")
    raw_root = os.environ.get("MANAGED_CORPUS_ROOT", "")
    if not raw_root:
        raise RuntimeError("Phase6B managed corpus root is required")
    root = Path(raw_root)
    if not root.is_absolute() or not root.is_dir():
        raise RuntimeError("Phase6B managed corpus root is invalid")
    return database, root


async def _prepare_corpus_ref(corpus_root: Path) -> CorpusSourceRef:
    source_name = "phase6b-owned-source.txt"
    source_path = corpus_root / source_name
    source_path.write_bytes(CORPUS_SOURCE_BYTES)
    initial_hash = sha256(CORPUS_SOURCE_BYTES).hexdigest()
    service = CorpusImportService(
        CorpusRepository(),
        corpus_root=corpus_root,
        managed_root=corpus_root,
        transaction_factory=transaction,
        connection_factory=connection,
    )
    try:
        imported = await service.import_source(
            source_name,
            "phase6b-corpus-import-authority",
            display_name="Phase6B owned corpus",
        )
        source_id = str(imported["corpus_source_id"])
        revision_id = str(imported["source_revision_id"])
        revision = int(imported["source_revision"])
        chapters = await service.list_chapters(source_id)
        if len(chapters) != 1:
            raise RuntimeError("Phase6B corpus chapter authority is invalid")
        fragment_page = await service.list_fragments(chapters[0]["id"], 0, 10)
        fragments = tuple(fragment_page["items"])
        if len(fragments) != 1:
            raise RuntimeError("Phase6B corpus fragment authority is invalid")
        fragment = fragments[0]
        async with transaction() as session:
            await session.execute("SET FOREIGN_KEY_CHECKS=0")
            try:
                await session.execute(
                    """UPDATE corpus_blobs
                       SET content_hash=%s,byte_length=%s,storage_key=%s
                       WHERE content_hash=%s""",
                    (
                        CORPUS_HASH,
                        len(CORPUS_BYTES),
                        managed_corpus_storage_key(CORPUS_HASH),
                        initial_hash,
                    ),
                )
                await session.execute(
                    """UPDATE corpus_source_revisions
                       SET content_hash=%s,byte_length=%s WHERE id=%s""",
                    (CORPUS_HASH, len(CORPUS_BYTES), revision_id),
                )
                await session.execute(
                    "UPDATE corpus_source_heads SET content_hash=%s WHERE source_id=%s",
                    (CORPUS_HASH, source_id),
                )
                await session.execute(
                    "UPDATE corpus_chapters SET source_hash=%s WHERE source_revision_id=%s",
                    (CORPUS_HASH, revision_id),
                )
            finally:
                await session.execute("SET FOREIGN_KEY_CHECKS=1")
        initial_blob = corpus_root / managed_corpus_storage_key(initial_hash)
        target = ensure_managed_corpus_blob_parent(corpus_root, CORPUS_HASH)
        target.write_bytes(CORPUS_BYTES)
        initial_blob.unlink()
        return CorpusSourceRef(
            id=source_id,
            revisionId=revision_id,
            revision=revision,
            contentHash=CORPUS_HASH,
            selectionMode="author",
            fragments=(FrozenCorpusFragment(
                chapterId=str(chapters[0]["id"]),
                fragmentId=str(fragment["id"]),
                fragmentHash=str(fragment["content_hash"]),
                chapterCharStart=int(fragment["chapter_char_start"]),
                chapterCharEnd=int(fragment["chapter_char_end"]),
                referenceUse="structure",
            ),),
            pinnedHistoricalRevision=False,
        )
    finally:
        source_path.unlink(missing_ok=True)


async def prepare(database_name: str) -> None:
    database, corpus_root = _authority(database_name)
    corpus_ref = await _prepare_corpus_ref(corpus_root)
    await prepare_finalized_project(database, corpus_source_refs=(corpus_ref,))
    # The Phase 6A fixture normally runs as its own process and closes its pool
    # in main().  Preserve that lifecycle boundary before Phase 6B mutates the
    # canonical fixture through a fresh pool.
    await close_pool()

    async with connection() as session:
        workspace = await session.fetchone(
            """SELECT chapter.id AS chapter_session_id,
                      draft.revision,draft.content_hash
                 FROM chapter_sessions chapter
                 JOIN working_drafts draft
                   ON draft.project_id=chapter.project_id
                  AND draft.chapter_session_id=chapter.id
                WHERE chapter.project_id=%s AND chapter.status='drafting'
                  AND draft.content=%s""",
            (PROJECT, WORKING_SENTINEL),
        )
    if workspace is None:
        raise RuntimeError("Phase6B terminal operation workspace is unavailable")
    operation_service = DraftOperationService(
        ChapterSessionRepository(),
        provider_gateway=ProviderMustNotRun(),
        transaction_factory=transaction,
    )
    operation_command = operation_service.validate(StartDraftOperation(
        project_id=PROJECT,
        chapter_session_id=workspace["chapter_session_id"],
        operation_type="generate_new",
        expected_working_draft_revision=int(workspace["revision"]),
        expected_content_hash=workspace["content_hash"],
        idempotency_key="62000000-0000-4000-8000-000000000001",
    ))
    replay, operation_context = await operation_service._reserve(operation_command)
    if replay is not None or operation_context is None:
        raise RuntimeError("Phase6B terminal operation reservation is invalid")
    terminal_operation = await operation_service.cancel(
        PROJECT,
        workspace["chapter_session_id"],
        operation_context["attempt"]["id"],
    )
    if terminal_operation.status != "cancelled":
        raise RuntimeError("Phase6B terminal operation did not settle")

    async with transaction() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        if selected != {"database_name": database}:
            raise RuntimeError("Phase6B fixture selected a non-owned database")
        provider = await session.fetchone(
            "SELECT id FROM provider_profiles WHERE name=%s", (PROVIDER_NAME,)
        )
        if provider is None:
            raise RuntimeError("Phase6B provider authority is unavailable")
        await session.execute(
            "UPDATE provider_profiles SET api_key=%s,base_url=%s WHERE id=%s",
            (SECRET_SENTINEL, BASE_URL_SENTINEL, provider["id"]),
        )
    _record_state(10)
    async with transaction() as session:
        try:
            await asyncio.wait_for(
                project_lifecycle_service.repository.read_preparation_snapshot(
                    session, PROJECT
                ),
                timeout=5,
            )
        except TimeoutError:
            raise PreparationSnapshotTimeout from None
        _record_state(11)
        try:
            await asyncio.wait_for(
                project_lifecycle_service.contract_service.get_head(
                    PROJECT, session=session, for_update=False
                ),
                timeout=30,
            )
        except TimeoutError:
            raise ContractHeadTimeout from None
        _record_state(12)
    _record_state(20)
    try:
        authority = await asyncio.wait_for(
            project_lifecycle_service.preparation(PROJECT), timeout=30
        )
    except TimeoutError:
        raise PreparationServiceTimeout from None
    _record_state(21)
    if authority.lifecycle != "active":
        raise RuntimeError("Phase6B active preparation authority is invalid")
    snapshot = await asyncio.wait_for(
        ProjectPackageRepository(pool=await get_pool()).read_snapshot(PROJECT, 0),
        timeout=30,
    )
    if snapshot.lifecycle_revision != 0:
        raise RuntimeError("Phase6B active package snapshot authority is invalid")


async def verify_postconditions(database_name: str) -> None:
    database, corpus_root = _authority(database_name)
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        project = await session.fetchone(
            "SELECT archived_at,lifecycle_revision FROM projects WHERE id=%s", (PROJECT,)
        )
        finals = await session.fetchone(
            "SELECT COUNT(*) AS count FROM final_chapters WHERE project_id=%s", (PROJECT,)
        )
        working = await session.fetchone(
            "SELECT COUNT(*) AS count FROM working_drafts WHERE project_id=%s AND content=%s",
            (PROJECT, WORKING_SENTINEL),
        )
        candidates = await session.fetchone(
            "SELECT COUNT(*) AS count FROM draft_candidates WHERE project_id=%s AND content=%s",
            (PROJECT, CANDIDATE_SENTINEL),
        )
        frozen_assets = await session.fetchone(
            """SELECT
                   (SELECT COUNT(*) FROM style_contract_template_refs r
                    JOIN style_contracts s ON s.id=r.style_contract_id WHERE s.project_id=%s) AS styles,
                   (SELECT COUNT(*) FROM creation_contract_experience_refs r
                    JOIN creation_contracts c ON c.id=r.creation_contract_id WHERE c.project_id=%s) AS experiences,
                   (SELECT COUNT(*) FROM creation_contract_corpus_refs r
                    JOIN creation_contracts c ON c.id=r.creation_contract_id
                    WHERE c.project_id=%s AND r.source_hash=%s) AS corpus""",
            (PROJECT, PROJECT, PROJECT, CORPUS_HASH),
        )
        provider = await session.fetchone(
            "SELECT api_key,base_url FROM provider_profiles WHERE name=%s",
            (PROVIDER_NAME,),
        )
        operations = await session.fetchone(
            """SELECT COUNT(*) AS count FROM draft_operation_attempts
                WHERE project_id=%s AND status='cancelled' AND active_slot IS NULL""",
            (PROJECT,),
        )
    if selected != {"database_name": database}:
        raise RuntimeError("Phase6B verifier selected a non-owned database")
    if (
        project is None
        or project.get("archived_at") is None
        or project.get("lifecycle_revision") != 1
    ):
        raise RuntimeError("Phase6B project did not reach the archived authority")
    if int(finals.get("count") or 0) < 1:
        raise RuntimeError("Phase6B fixture has no finalized chapter")
    if int(working.get("count") or 0) != 1 or int(candidates.get("count") or 0) != 1:
        raise RuntimeError("Phase6B draft sentinel authority is invalid")
    if frozen_assets != {"styles": 1, "experiences": 1, "corpus": 1}:
        raise RuntimeError("Phase6B frozen asset authority is invalid")
    if provider != {"api_key": SECRET_SENTINEL, "base_url": BASE_URL_SENTINEL}:
        raise RuntimeError("Phase6B referenced provider authority is invalid")
    if int(operations.get("count") or 0) != 1:
        raise RuntimeError("Phase6B terminal operation authority is invalid")
    blob = corpus_root / managed_corpus_storage_key(CORPUS_HASH)
    if not blob.is_file() or sha256(blob.read_bytes()).hexdigest() != CORPUS_HASH:
        raise RuntimeError("Phase6B owned corpus blob is invalid")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--verify-postconditions", action="store_true")
    args = parser.parse_args()
    exit_code = 0
    try:
        if args.verify_postconditions:
            await verify_postconditions(args.database)
        else:
            await prepare(args.database)
    except PreparationSnapshotTimeout:
        exit_code = 61
    except ContractHeadTimeout:
        exit_code = 62
    except PreparationServiceTimeout:
        exit_code = 63
    finally:
        await close_pool()
    if exit_code:
        diagnostic = os.environ.get("PHASE6B_FIXTURE_STATE_PATH", "")
        if diagnostic:
            Path(diagnostic).write_text(str(exit_code), encoding="ascii")
        raise SystemExit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
