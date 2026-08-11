"""Prepare and verify the disposable Phase 6C atomic-import authority."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path

from starlette.datastructures import UploadFile

from backend.database import close_pool, connection, get_pool
from backend.domain.project_import_plans import (
    build_publication_plan,
    read_verified_project_package,
)
from backend.repositories.project_imports import ProjectImportRepository
from backend.repositories.project_packages import ProjectPackageRepository
from backend.scripts.prepare_phase4b2_browser_db import assert_database_name
from backend.scripts.prepare_phase6a_browser_db import (
    CANDIDATE_SENTINEL,
    FINAL_ONE,
    FINAL_TWO,
    WORKING_SENTINEL,
)
from backend.scripts.prepare_phase6b_browser_db import (
    BASE_URL_SENTINEL,
    CORPUS_HASH,
    PROJECT,
    PROVIDER,
    ProviderMustNotRun,
    SECRET_SENTINEL,
    prepare as prepare_phase6b_browser_db,
)
from backend.security.paths import managed_corpus_storage_key
from backend.services.project_imports import ProjectImportService
from backend.services.project_packages import ProjectPackageService


IMPORTED_TITLE = "Phase6C imported authority"
_PROVIDER_GUARD = ProviderMustNotRun


def _owned_path(environment_name: str, parent_name: str | None = None) -> Path:
    raw = os.environ.get(environment_name, "")
    if not raw:
        raise RuntimeError(f"Phase6C {environment_name} is required")
    target = Path(raw)
    if not target.is_absolute():
        raise RuntimeError(f"Phase6C {environment_name} must be absolute")
    if parent_name:
        parent = _owned_path(parent_name)
        try:
            target.resolve(strict=False).relative_to(parent.resolve(strict=True))
        except (OSError, RuntimeError, ValueError):
            raise RuntimeError(f"Phase6C {environment_name} is outside its owned root") from None
    return target


def _authority(database_name: str) -> tuple[str, Path, Path]:
    database = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database:
        raise RuntimeError("Phase6C fixture database authority mismatch")
    corpus_root = _owned_path("MANAGED_CORPUS_ROOT")
    baseline_path = _owned_path("PHASE6C_BASELINE_PATH", "BROWSER_OWNED_ROOT")
    if not corpus_root.is_dir():
        raise RuntimeError("Phase6C managed corpus root is invalid")
    return database, corpus_root, baseline_path


async def _source_snapshot(session) -> dict[str, object]:
    project = await session.fetchone(
        "SELECT title,archived_at,lifecycle_revision FROM projects WHERE id=%s",
        (PROJECT,),
    )
    finals = await session.fetchall(
        "SELECT chapter_num,content FROM final_chapters WHERE project_id=%s ORDER BY chapter_num",
        (PROJECT,),
    )
    head_tables = (
        "project_contract_heads", "project_bible_heads", "project_planning_heads",
        "project_chapter_outline_heads", "projection_heads",
    )
    heads: dict[str, list[dict[str, object]]] = {}
    for table in head_tables:
        rows = await session.fetchall(
            f"SELECT * FROM {table} WHERE project_id=%s", (PROJECT,)
        )
        heads[table] = sorted(
            rows,
            key=lambda row: json.dumps(row, sort_keys=True, default=str),
        )
    return {
        "project": project,
        "finals": finals,
        "headHashes": {
            table: sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
            for table, rows in heads.items()
        },
    }


async def _assert_service_preflight(corpus_root: Path) -> None:
    package_temp = _owned_path("PHASE6C_PACKAGE_TEMP_ROOT", "BROWSER_OWNED_ROOT")
    quarantine = _owned_path("PHASE6C_IMPORT_QUARANTINE_ROOT", "BROWSER_OWNED_ROOT")
    package = await ProjectPackageService(
        repository=ProjectPackageRepository(pool=await get_pool()),
        managed_corpus_root=corpus_root,
        temp_parent=package_temp,
    ).create_backup(PROJECT, 0)
    try:
        with package.path.open("rb") as source:
            try:
                summary = await ProjectImportService(
                    repository=ProjectImportRepository(),
                    managed_corpus_root=corpus_root,
                    temp_parent=quarantine,
                ).preflight(UploadFile(source, filename="project-import.zip"))
            except Exception as exc:
                cause = getattr(exc, "code", type(exc).__name__)
                trace = exc.__traceback__
                graph_line = None
                while trace is not None:
                    if trace.tb_frame.f_code.co_name == "_validate_graph":
                        graph_line = trace.tb_lineno
                        record = trace.tb_frame.f_locals.get("record")
                        entity_type = getattr(record, "entity_type", None)
                        pin_field = trace.tb_frame.f_locals.get("revision_field")
                    trace = trace.tb_next
                if graph_line is not None:
                    cause = f"{cause}-graph-{graph_line}"
                    if isinstance(entity_type, str) and isinstance(pin_field, str):
                        cause = f"{cause}-{entity_type}-{pin_field}"
                Path(os.environ["BROWSER_RESULT_PATH"]).write_text(
                    json.dumps({"fixtureCause": f"preflight-{cause}"}),
                    encoding="utf-8",
                )
                raise
        if summary.package_hash != package.package_sha256:
            raise RuntimeError("Phase6C service preflight hash mismatch")
        verified = read_verified_project_package(package.path)
        try:
            plan = build_publication_plan(
                verified,
                "00000000-0000-4000-8000-00000000006c",
                IMPORTED_TITLE,
            )
        except Exception as exc:
            cause = getattr(exc, "code", type(exc).__name__)
            Path(os.environ["BROWSER_RESULT_PATH"]).write_text(
                json.dumps({"fixtureCause": f"publication-plan-{cause}"}),
                encoding="utf-8",
            )
            raise
        if plan.package_hash != summary.package_hash:
            raise RuntimeError("Phase6C publication plan hash mismatch")
    finally:
        package.cleanup()


async def prepare(database_name: str) -> None:
    database, corpus_root, baseline_path = _authority(database_name)
    await prepare_phase6b_browser_db(database)
    await _assert_service_preflight(corpus_root)
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        if selected != {"database_name": database}:
            raise RuntimeError("Phase6C fixture selected a non-owned database")
        baseline = await _source_snapshot(session)
    baseline_path.write_text(
        json.dumps(baseline, sort_keys=True, separators=(",", ":"), default=str),
        encoding="utf-8",
    )


async def verify_postconditions(database_name: str) -> None:
    database, corpus_root, baseline_path = _authority(database_name)
    backup_path = _owned_path("PHASE6C_BACKUP_PATH", "BROWSER_DOWNLOAD_ROOT")
    final_path = _owned_path("PHASE6C_FINAL_PATH", "BROWSER_DOWNLOAD_ROOT")
    verified = read_verified_project_package(backup_path)
    if not verified.summary.has_finalized_chapters or verified.summary.package_version != 1:
        raise RuntimeError("Phase6C exact package verifier rejected source authority")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        source = await _source_snapshot(session)
        projects = await session.fetchall(
            "SELECT id,title,archived_at,lifecycle_revision FROM projects ORDER BY id"
        )
        imported = [row for row in projects if row["title"] == IMPORTED_TITLE]
        if len(imported) != 1:
            raise RuntimeError("Phase6C imported project cardinality is invalid")
        target = imported[0]["id"]
        command = await session.fetchone(
            """SELECT id,status,phase,target_project_id,package_hash,manifest_hash,
                      public_error_code,owner_token,lease_expires_at
                 FROM project_package_import_commands WHERE target_project_id=%s""",
            (target,),
        )
        authority_counts = {}
        for table in (
            "creation_contracts", "creation_bible_revisions", "planning_revisions",
            "chapter_outline_revisions", "working_drafts", "draft_candidates",
            "final_chapters", "canon_revisions", "projection_heads",
        ):
            authority_counts[table] = await session.fetchone(
                f"SELECT COUNT(*) AS count FROM {table} WHERE project_id=%s", (target,)
            )
        target_finals = await session.fetchall(
            "SELECT chapter_num,content FROM final_chapters WHERE project_id=%s ORDER BY chapter_num",
            (target,),
        )
        bindings = await session.fetchall(
            """SELECT item.task_key,item.resolution_status,item.provider_id,
                      item.provider_name_snapshot,item.model_name_snapshot
                 FROM project_model_binding_heads head
                 JOIN project_model_binding_items item
                   ON item.binding_revision_id=head.binding_revision_id
                WHERE head.project_id=%s ORDER BY item.task_key""",
            (target,),
        )
        provenance = await session.fetchone(
            "SELECT COUNT(*) AS count FROM project_import_provenance WHERE project_id=%s",
            (target,),
        )
        provider = await session.fetchone(
            "SELECT api_key,base_url FROM provider_profiles WHERE id=%s", (PROVIDER,)
        )
        blob = await session.fetchone(
            "SELECT byte_length,storage_key FROM corpus_blobs WHERE content_hash=%s",
            (CORPUS_HASH,),
        )

    if selected != {"database_name": database}:
        raise RuntimeError("Phase6C verifier selected a non-owned database")
    normalized_source = json.loads(json.dumps(source, sort_keys=True, default=str))
    if normalized_source != baseline:
        raise RuntimeError("Phase6C source project authority changed")
    if len(projects) != 2 or imported[0]["archived_at"] is not None:
        raise RuntimeError("Phase6C atomic project visibility is invalid")
    if command is None or command != {
        **command,
        "status": "succeeded",
        "phase": "succeeded",
        "target_project_id": target,
        "package_hash": verified.package_hash,
        "manifest_hash": verified.manifest_hash,
        "public_error_code": None,
        "owner_token": None,
        "lease_expires_at": None,
    }:
        raise RuntimeError("Phase6C command recovery authority is invalid")
    if any(int(value["count"] or 0) < 1 for value in authority_counts.values()):
        raise RuntimeError("Phase6C imported formal authority is incomplete")
    if target_finals != [
        {"chapter_num": 1, "content": FINAL_ONE},
        {"chapter_num": 2, "content": FINAL_TWO},
    ]:
        raise RuntimeError("Phase6C imported final chapter bytes changed")
    if len(bindings) != 8 or any(
        row["resolution_status"] != "unbound"
        or any(row[field] is not None for field in (
            "provider_id", "provider_name_snapshot", "model_name_snapshot",
        ))
        for row in bindings
    ):
        raise RuntimeError("Phase6C imported Provider state is not Not Ready")
    if int(provenance["count"] or 0) < 1:
        raise RuntimeError("Phase6C inert import provenance is absent")
    if provider != {"api_key": SECRET_SENTINEL, "base_url": BASE_URL_SENTINEL}:
        raise RuntimeError("Phase6C source Provider authority changed")
    if blob != {
        "byte_length": (corpus_root / managed_corpus_storage_key(CORPUS_HASH)).stat().st_size,
        "storage_key": managed_corpus_storage_key(CORPUS_HASH),
    }:
        raise RuntimeError("Phase6C canonical corpus blob authority changed")
    final_text = final_path.read_text(encoding="utf-8")
    if not (FINAL_ONE in final_text and FINAL_TWO in final_text):
        raise RuntimeError("Phase6C imported TXT is incomplete")
    if WORKING_SENTINEL in final_text or CANDIDATE_SENTINEL in final_text:
        raise RuntimeError("Phase6C imported TXT leaked non-final prose")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--verify-postconditions", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_postconditions:
            await verify_postconditions(args.database)
        else:
            try:
                await prepare(args.database)
            except Exception as exc:
                result_path = os.environ.get("BROWSER_RESULT_PATH")
                if result_path and not Path(result_path).exists():
                    cause = getattr(exc, "code", type(exc).__name__)
                    Path(result_path).write_text(
                        json.dumps({"fixtureCause": f"fixture-{cause}"}),
                        encoding="utf-8",
                    )
                raise
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
