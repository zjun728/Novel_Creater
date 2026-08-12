"""Prepare and verify the disposable Phase 6B project-backup authority."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import os
from pathlib import Path

from backend.database import close_pool, connection, get_pool, transaction
from backend.domain.bibles import BiblePayload
from backend.routers.projects import _service as project_lifecycle_service
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.project_packages import ProjectPackageRepository
from backend.scripts.prepare_phase4b2_browser_db import assert_database_name
from backend.scripts.prepare_phase6a_browser_db import (
    CANDIDATE_SENTINEL,
    WORKING_SENTINEL,
    prepare as prepare_finalized_project,
)
from backend.security.paths import (
    ensure_managed_corpus_blob_parent,
    managed_corpus_storage_key,
)
from backend.services.draft_operations import DraftOperationService, StartDraftOperation
from backend.tests.integration.test_contract_drafts import PROJECT, PROVIDER
from backend.tests.integration import test_planning_aggregate_lifecycle as planning_fixture


SECRET_SENTINEL = "phase6b-private-api-key-sentinel"
BASE_URL_SENTINEL = "https://phase6b-private.invalid/v1"
CORPUS_UNIT = b"PHASE6B_OWNED_CORPUS_BYTES\n"
CORPUS_BYTES = (CORPUS_UNIT * ((8 * 1024 * 1024 // len(CORPUS_UNIT)) + 1))[: 8 * 1024 * 1024]
CORPUS_HASH = sha256(CORPUS_BYTES).hexdigest()
LEGACY_CORPUS_HASH = "e" * 64
VALID_BIBLE = BiblePayload.model_validate({
    "premiseAndPromise": "保存真相必须承担关系与行动的代价。",
    "worldRules": ({"id": "world-rule", "text": "所有能力都留下可追踪代价。"},),
    "powerOrProgressionSystem": "成长来自选择、训练与有限资源。",
    "protagonist": "主角谨慎并愿意承担选择后果。",
    "coreCast": ({"id": "core-cast", "text": "同伴拥有独立目标与判断。"},),
    "factions": ({"id": "faction", "text": "守序势力试图封存异常档案。"},),
    "longTermConflicts": ({"id": "conflict", "text": "真相与秩序长期冲突。"},),
    "relationshipDynamics": ({"id": "relationship", "text": "互疑会在共同选择中转为有限信任。"},),
    "toneAndNarrativeBoundaries": "叙事克制具体，以人物选择推动情节。",
    "continuityGuardrails": ({"id": "guardrail", "text": "关键胜利必须伴随损失。"},),
    "openDesignQuestions": ({"id": "question", "text": "幕后人的真实身份仍未确定。"},),
}, strict=True).model_dump(mode="json", by_alias=True)


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


async def prepare(database_name: str) -> None:
    database, corpus_root = _authority(database_name)
    target = ensure_managed_corpus_blob_parent(corpus_root, CORPUS_HASH)
    target.write_bytes(CORPUS_BYTES)
    original_bootstrap = planning_fixture._bootstrap
    original_insert_bible = planning_fixture._insert_confirmed_bible

    async def bootstrap_with_owned_corpus(session):
        facts = await original_bootstrap(session)
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
                    LEGACY_CORPUS_HASH,
                ),
            )
            await session.execute(
                """UPDATE corpus_source_revisions
                   SET content_hash=%s,byte_length=%s WHERE content_hash=%s""",
                (CORPUS_HASH, len(CORPUS_BYTES), LEGACY_CORPUS_HASH),
            )
            await session.execute(
                "UPDATE corpus_source_heads SET content_hash=%s WHERE content_hash=%s",
                (CORPUS_HASH, LEGACY_CORPUS_HASH),
            )
            await session.execute(
                "UPDATE corpus_chapters SET source_hash=%s WHERE source_hash=%s",
                (CORPUS_HASH, LEGACY_CORPUS_HASH),
            )
        finally:
            await session.execute("SET FOREIGN_KEY_CHECKS=1")
        return dict(facts) | {"source_hash": CORPUS_HASH}

    async def insert_valid_bible(*args, **kwargs):
        options = dict(kwargs)
        options.setdefault("content", VALID_BIBLE)
        return await original_insert_bible(*args, **options)

    planning_fixture._bootstrap = bootstrap_with_owned_corpus
    planning_fixture._insert_confirmed_bible = insert_valid_bible
    try:
        await prepare_finalized_project(database)
    finally:
        planning_fixture._bootstrap = original_bootstrap
        planning_fixture._insert_confirmed_bible = original_insert_bible
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
        await session.execute(
            "UPDATE provider_profiles SET api_key=%s,base_url=%s WHERE id=%s",
            (SECRET_SENTINEL, BASE_URL_SENTINEL, PROVIDER),
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
            "SELECT api_key,base_url FROM provider_profiles WHERE id=%s", (PROVIDER,)
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
