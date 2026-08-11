"""Recoverable command persistence for atomic project imports."""

from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Literal
from uuid import UUID, uuid5

from backend.domain.canon import thaw_json
from backend.domain.project_import_plans import ProjectPublicationPlan
from backend.domain.project_import_publication import (
    PUBLICATION_TABLE_ORDER,
    STATIC_TABLE_COLUMNS,
)
from backend.repositories.canon import CanonRepository
from backend.services.projections import build_projection_bundle


_PUBLIC_ERROR_CODE = "PROJECT_IMPORT_FAILED"
MAX_IMPORT_LEASE_MS = 300_000
_PUBLIC_COLUMNS = """id,request_fingerprint,status,phase,owner_token,
lease_expires_at,target_project_id,public_error_code"""
_PUBLICATION_TABLE_POSITION = MappingProxyType({
    table: position for position, table in enumerate(PUBLICATION_TABLE_ORDER)
})
_STATIC_INSERT_SQL = MappingProxyType({
    table: (
        f"INSERT INTO {table} ({','.join(columns)}) "
        f"VALUES ({','.join(('%s',) * len(columns))})"
    )
    for table, columns in STATIC_TABLE_COLUMNS.items()
})


class ProjectImportCommandConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("project import command conflict")


class ProjectImportCommandStateConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("project import command state conflict")


class ProjectImportPersistenceError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("project import persistence failed")


@dataclass(frozen=True, slots=True)
class ProjectImportCommandView:
    command_id: str
    status: Literal["reserved", "running", "succeeded", "failed"]
    phase: Literal[
        "uploaded", "preflighted", "staged", "publishing", "succeeded", "failed"
    ]
    retry_required: bool
    target_project_id: str | None
    public_error_code: str | None


@dataclass(frozen=True, slots=True)
class ProjectImportRecoveryCommand:
    command_id: str
    status: str
    staging_manifest_json: str


def _is_duplicate_key_error(exc: Exception) -> bool:
    errno = getattr(exc, "errno", None)
    if errno == 1062:
        return True
    if not exc.args:
        return False
    first = exc.args[0]
    return first == 1062 or (
        isinstance(first, tuple) and bool(first) and first[0] == 1062
    )


def _view(row, now_ms: int) -> ProjectImportCommandView:
    status = row["status"]
    succeeded = status == "succeeded"
    failed = status == "failed"
    lease_expires_at = row["lease_expires_at"]
    return ProjectImportCommandView(
        command_id=row["id"],
        status=status,
        phase=row["phase"],
        retry_required=(
            status == "running"
            and lease_expires_at is not None
            and lease_expires_at <= now_ms
        ),
        target_project_id=row["target_project_id"] if succeeded else None,
        public_error_code=row["public_error_code"] if failed else None,
    )


async def _execute(session, sql: str, args):
    try:
        return await session.execute(sql, args)
    except (
        ProjectImportCommandConflict,
        ProjectImportCommandStateConflict,
        ProjectImportPersistenceError,
    ):
        raise
    except Exception:
        raise ProjectImportPersistenceError() from None


async def _fetchone(session, sql: str, args):
    try:
        return await session.fetchone(sql, args)
    except (
        ProjectImportCommandConflict,
        ProjectImportCommandStateConflict,
        ProjectImportPersistenceError,
    ):
        raise
    except Exception:
        raise ProjectImportPersistenceError() from None


class ProjectImportRepository:
    async def _publication_checkpoint(self, point: str) -> None:
        """Test seam for proving transaction rollback at publication boundaries."""

    async def persist_staging_manifest(
        self, session, *, command_id: str, request_fingerprint: str,
        owner_token: str, manifest_json: str, now_ms: int,
    ) -> None:
        affected = await _execute(
            session,
            """UPDATE project_package_import_commands
               SET phase='staged',staging_manifest_json=%s,updated_at=%s
               WHERE id=%s AND request_fingerprint=%s AND status='running'
                 AND owner_token=%s AND lease_expires_at>%s""",
            (manifest_json, now_ms, command_id, request_fingerprint,
             owner_token, now_ms),
        )
        if affected != 1:
            raise ProjectImportCommandStateConflict()

    async def list_recovery_commands(
        self, session, *, now_ms: int, limit: int = 32,
    ) -> tuple[ProjectImportRecoveryCommand, ...]:
        if type(now_ms) is not int or type(limit) is not int or not 1 <= limit <= 32:
            raise ProjectImportCommandStateConflict()
        try:
            rows = await session.fetchall(
                """SELECT id,status,staging_manifest_json
                   FROM project_package_import_commands
                   WHERE staging_manifest_json IS NOT NULL
                     AND (status IN ('succeeded','failed')
                          OR (status='running' AND lease_expires_at<=%s))
                   ORDER BY updated_at,id LIMIT %s""",
                (now_ms, limit),
            )
            return tuple(ProjectImportRecoveryCommand(
                row["id"], row["status"],
                row["staging_manifest_json"] if isinstance(row["staging_manifest_json"], str)
                else json.dumps(row["staging_manifest_json"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ) for row in rows)
        except ProjectImportCommandStateConflict:
            raise
        except Exception:
            raise ProjectImportPersistenceError() from None

    async def corpus_blob_is_referenced(self, session, *, content_hash: str) -> bool:
        row = await _fetchone(
            session, "SELECT content_hash FROM corpus_blobs WHERE content_hash=%s",
            (content_hash,),
        )
        return row is not None

    async def fence_recovery_command(
        self, session, *, candidate: ProjectImportRecoveryCommand, now_ms: int,
    ) -> ProjectImportRecoveryCommand | None:
        """Lock and, for an expired runner, CAS it terminal before file recovery."""
        try:
            row = await session.fetchone(
                """SELECT id,status,lease_expires_at,staging_manifest_json
                   FROM project_package_import_commands WHERE id=%s FOR UPDATE""",
                (candidate.command_id,),
            )
            if row is None:
                return None
            manifest = (
                row["staging_manifest_json"]
                if isinstance(row["staging_manifest_json"], str)
                else json.dumps(row["staging_manifest_json"], ensure_ascii=False,
                                sort_keys=True, separators=(",", ":"))
            )
            if manifest != candidate.staging_manifest_json:
                return None
            if row["status"] in {"succeeded", "failed"}:
                return ProjectImportRecoveryCommand(row["id"], row["status"], manifest)
            if (
                row["status"] != "running"
                or type(row["lease_expires_at"]) is not int
                or row["lease_expires_at"] > now_ms
            ):
                return None
            affected = await session.execute(
                """UPDATE project_package_import_commands
                   SET status='failed',phase='failed',owner_token=NULL,
                       lease_expires_at=NULL,public_error_code=%s,
                       updated_at=%s,completed_at=%s
                   WHERE id=%s AND status='running' AND lease_expires_at<=%s
                     AND staging_manifest_json=%s""",
                (_PUBLIC_ERROR_CODE, now_ms, now_ms, candidate.command_id,
                 now_ms, candidate.staging_manifest_json),
            )
            if affected != 1:
                return None
            return ProjectImportRecoveryCommand(
                candidate.command_id, "failed", candidate.staging_manifest_json,
            )
        except Exception:
            raise ProjectImportPersistenceError() from None

    async def _lock_publication_command(
        self, session, plan: ProjectPublicationPlan, now: int,
        request_fingerprint: str, owner_token: str,
    ):
        row = await session.fetchone(
            """SELECT id,target_project_id,status,phase,owner_token,lease_expires_at,
                      request_fingerprint,package_hash,manifest_hash,normalized_title,
                      staging_manifest_json
               FROM project_package_import_commands WHERE id=%s FOR UPDATE""",
            (plan.command_id,),
        )
        project_batches = [batch for batch in plan.batches if batch.table == "projects"]
        if len(project_batches) != 1 or len(project_batches[0].rows) != 1:
            raise ProjectImportCommandStateConflict()
        title_index = project_batches[0].columns.index("title")
        expected_title = project_batches[0].rows[0][title_index]
        try:
            staging = (
                json.loads(row["staging_manifest_json"])
                if row is not None and isinstance(row["staging_manifest_json"], str)
                else row["staging_manifest_json"] if row is not None else None
            )
        except (TypeError, ValueError):
            raise ProjectImportCommandStateConflict() from None
        if (
            row is None
            or row["target_project_id"] != plan.target_project_id
            or row["request_fingerprint"] != request_fingerprint
            or row["package_hash"] != plan.package_hash
            or row["manifest_hash"] != plan.manifest_hash
            or row["normalized_title"] != expected_title
            or not isinstance(staging, dict)
            or staging.get("idMapHash") != plan.id_map_hash
        ):
            raise ProjectImportCommandStateConflict()
        if row["status"] == "succeeded":
            exists = await session.fetchone(
                "SELECT id FROM projects WHERE id=%s", (plan.target_project_id,),
            )
            if exists is None:
                raise ProjectImportCommandStateConflict()
            return "replay"
        if (
            row["status"] != "running"
            or row["phase"] not in {"staged", "publishing"}
            or row["owner_token"] != owner_token
            or type(row["lease_expires_at"]) is not int
            or row["lease_expires_at"] <= now
        ):
            raise ProjectImportCommandStateConflict()
        affected = await session.execute(
            """UPDATE project_package_import_commands
               SET phase='publishing',updated_at=%s
               WHERE id=%s AND request_fingerprint=%s AND status='running'
                 AND phase IN ('staged','publishing') AND owner_token=%s
                 AND lease_expires_at>%s""",
            (now, plan.command_id, request_fingerprint, owner_token, now),
        )
        if affected != 1:
            raise ProjectImportCommandStateConflict()
        return "publish"

    @staticmethod
    async def _insert_publication_batch(session, batch) -> None:
        columns = STATIC_TABLE_COLUMNS.get(batch.table)
        sql = _STATIC_INSERT_SQL.get(batch.table)
        if columns is None or sql is None or batch.columns != columns:
            raise ProjectImportCommandStateConflict()
        for row in batch.rows:
            if batch.table == "corpus_blobs":
                existing = await session.fetchone(
                    """SELECT content_hash,byte_length,storage_key
                       FROM corpus_blobs WHERE content_hash=%s FOR UPDATE""",
                    (row[0],),
                )
                if existing is not None:
                    if (
                        existing["content_hash"], existing["byte_length"],
                        existing["storage_key"],
                    ) != row[:3]:
                        raise ProjectImportCommandStateConflict()
                    continue
            await session.execute(sql, row)

    @staticmethod
    async def _projection_bundle(session, project_id: str):
        revision_row = await session.fetchone(
            """SELECT MAX(revision_number) AS revision_number
               FROM canon_revisions WHERE project_id=%s""",
            (project_id,),
        )
        revision = revision_row["revision_number"] if revision_row is not None else None
        revision = 0 if revision is None else revision
        rows = await session.fetchall(
            """SELECT id,revision_number,event_order,entity_id,fact_kind,
                      field_path,value_json,confirmation_status,evidence_json
               FROM canon_events WHERE project_id=%s
               ORDER BY revision_number,event_order,id""",
            (project_id,),
        )
        events = ({
            "id": row["id"],
            "revision_number": row["revision_number"],
            "event_order": row["event_order"],
            "entity_id": row["entity_id"],
            "fact_kind": row["fact_kind"],
            "field_path": row["field_path"],
            "value": json.loads(row["value_json"]) if isinstance(row["value_json"], str) else row["value_json"],
            "confirmation_status": row["confirmation_status"],
            "evidence": json.loads(row["evidence_json"]) if isinstance(row["evidence_json"], str) else row["evidence_json"],
        } for row in rows)
        return build_projection_bundle(revision, events)

    @staticmethod
    def _projection_value(bundle) -> dict[str, object]:
        return {
            "revision": bundle.revision,
            "currentState": thaw_json(bundle.current_state),
            "memories": thaw_json(bundle.memories),
            "arcs": thaw_json(bundle.arcs),
            "plotThreads": thaw_json(bundle.plot_threads),
            "contentHash": bundle.content_hash,
        }

    async def _rebuild_and_verify_projection(
        self, session, plan: ProjectPublicationPlan, now: int,
    ) -> None:
        bundle = await self._projection_bundle(session, plan.target_project_id)
        await session.execute(
            """INSERT INTO projection_heads
               (project_id,canon_revision_number,projection_revision_number,
                content_hash,updated_at) VALUES (%s,%s,%s,%s,%s)""",
            (
                plan.target_project_id, bundle.revision, bundle.revision,
                bundle.content_hash, now,
            ),
        )
        counter = 0

        def projection_id() -> str:
            nonlocal counter
            counter += 1
            return str(uuid5(UUID(plan.target_project_id), f"projection/{counter}"))

        await CanonRepository(id_factory=projection_id, clock=lambda: now).replace_projections(
            session, plan.target_project_id, bundle,
        )
        await self._publication_checkpoint("before_projection_compare")
        if self._projection_value(bundle) != thaw_json(plan.expected_projection):
            raise ProjectImportCommandStateConflict()

    async def publish_project(
        self, session, plan: ProjectPublicationPlan, *, now: int,
        request_fingerprint: str, owner_token: str,
    ) -> str:
        """Publish a closed plan into its caller-owned transaction."""
        try:
            if (
                type(plan) is not ProjectPublicationPlan or type(now) is not int
                or not isinstance(request_fingerprint, str)
                or not isinstance(owner_token, str)
            ):
                raise ProjectImportCommandStateConflict()
            mode = await self._lock_publication_command(
                session, plan, now, request_fingerprint, owner_token,
            )
            if mode == "replay":
                return plan.target_project_id
            existing = await session.fetchone(
                "SELECT id FROM projects WHERE id=%s", (plan.target_project_id,),
            )
            if existing is not None:
                raise ProjectImportCommandStateConflict()
            positions = tuple(_PUBLICATION_TABLE_POSITION.get(batch.table, -1) for batch in plan.batches)
            if any(position < 0 for position in positions) or positions != tuple(sorted(positions)):
                raise ProjectImportCommandStateConflict()
            for index, batch in enumerate(plan.batches):
                await self._publication_checkpoint(f"before_batch:{index}")
                await self._insert_publication_batch(session, batch)
            await self._publication_checkpoint("before_projection_rebuild")
            await self._rebuild_and_verify_projection(session, plan, now)
            await self._publication_checkpoint("before_command_success")
            affected = await session.execute(
                """UPDATE project_package_import_commands
                   SET status='succeeded',phase='succeeded',owner_token=NULL,
                       lease_expires_at=NULL,public_error_code=NULL,
                       updated_at=%s,completed_at=%s
                   WHERE id=%s AND target_project_id=%s AND status='running'
                     AND phase='publishing' AND request_fingerprint=%s
                     AND owner_token=%s AND lease_expires_at>%s""",
                (
                    now, now, plan.command_id, plan.target_project_id,
                    request_fingerprint, owner_token, now,
                ),
            )
            if affected != 1:
                raise ProjectImportCommandStateConflict()
            return plan.target_project_id
        except (ProjectImportCommandConflict, ProjectImportCommandStateConflict):
            raise
        except Exception:
            raise ProjectImportPersistenceError() from None

    async def _read_exact(self, session, command_id: str):
        return await _fetchone(
            session,
            f"""SELECT {_PUBLIC_COLUMNS}
                FROM project_package_import_commands WHERE id=%s""",
            (command_id,),
        )

    async def read_command(
        self, session, *, command_id: str, now_ms: int
    ) -> ProjectImportCommandView | None:
        row = await self._read_exact(session, command_id)
        return None if row is None else _view(row, now_ms)

    async def reserve_command(
        self,
        session,
        *,
        command_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        package_hash: str,
        manifest_hash: str,
        package_version: int,
        target_project_id: str,
        normalized_title: str,
        now_ms: int,
    ) -> ProjectImportCommandView:
        try:
            await session.execute(
                """INSERT INTO project_package_import_commands
                   (id,idempotency_key,request_fingerprint,package_hash,
                    manifest_hash,package_version,target_project_id,
                    normalized_title,status,phase,owner_token,lease_expires_at,
                    staging_manifest_json,public_error_code,created_at,updated_at,
                    completed_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'reserved','preflighted',
                           NULL,NULL,NULL,NULL,%s,%s,NULL)""",
                (
                    command_id,
                    idempotency_key,
                    request_fingerprint,
                    package_hash,
                    manifest_hash,
                    package_version,
                    target_project_id,
                    normalized_title,
                    now_ms,
                    now_ms,
                ),
            )
        except (
            ProjectImportCommandConflict,
            ProjectImportCommandStateConflict,
            ProjectImportPersistenceError,
        ):
            raise
        except Exception as exc:
            if not _is_duplicate_key_error(exc):
                raise ProjectImportPersistenceError() from None
            replay = await _fetchone(
                session,
                f"""SELECT {_PUBLIC_COLUMNS}
                    FROM project_package_import_commands
                    WHERE idempotency_key=%s FOR UPDATE""",
                (idempotency_key,),
            )
            if replay is not None and replay["request_fingerprint"] == request_fingerprint:
                return _view(replay, now_ms)
            await _fetchone(
                session,
                """SELECT id FROM project_package_import_commands
                   WHERE id=%s FOR UPDATE""",
                (command_id,),
            )
            raise ProjectImportCommandConflict() from None

        row = await self._read_exact(session, command_id)
        if row is None:
            raise ProjectImportCommandStateConflict() from None
        return _view(row, now_ms)

    async def acquire_lease(
        self,
        session,
        *,
        command_id: str,
        request_fingerprint: str,
        owner_token: str,
        now_ms: int,
        lease_expires_at: int,
    ) -> ProjectImportCommandView:
        if not now_ms < lease_expires_at <= now_ms + MAX_IMPORT_LEASE_MS:
            raise ProjectImportCommandStateConflict() from None
        affected = await _execute(
            session,
            """UPDATE project_package_import_commands
               SET status='running',owner_token=%s,lease_expires_at=%s,updated_at=%s
               WHERE id=%s AND request_fingerprint=%s
                 AND status IN ('reserved','running')
                 AND (status='reserved' OR owner_token=%s OR lease_expires_at<=%s)""",
            (
                owner_token,
                lease_expires_at,
                now_ms,
                command_id,
                request_fingerprint,
                owner_token,
                now_ms,
            ),
        )
        row = await self._read_exact(session, command_id)
        if (
            affected not in (0, 1)
            or row is None
            or row["request_fingerprint"] != request_fingerprint
            or row["status"] != "running"
            or row["owner_token"] != owner_token
            or row["lease_expires_at"] != lease_expires_at
        ):
            raise ProjectImportCommandStateConflict() from None
        return _view(row, now_ms)

    async def mark_failed(
        self,
        session,
        *,
        command_id: str,
        request_fingerprint: str,
        owner_token: str,
        now_ms: int,
    ) -> ProjectImportCommandView:
        affected = await _execute(
            session,
            """UPDATE project_package_import_commands
               SET status='failed',phase='failed',owner_token=NULL,
                   lease_expires_at=NULL,public_error_code=%s,
                   updated_at=%s,completed_at=%s
               WHERE id=%s AND request_fingerprint=%s AND owner_token=%s
                 AND status='running' AND lease_expires_at>%s""",
            (
                _PUBLIC_ERROR_CODE,
                now_ms,
                now_ms,
                command_id,
                request_fingerprint,
                owner_token,
                now_ms,
            ),
        )
        row = await self._read_exact(session, command_id)
        if affected != 1 or row is None:
            raise ProjectImportCommandStateConflict() from None
        return _view(row, now_ms)

    async def mark_succeeded(
        self,
        session,
        *,
        command_id: str,
        request_fingerprint: str,
        owner_token: str,
        target_project_id: str,
        now_ms: int,
    ) -> ProjectImportCommandView:
        affected = await _execute(
            session,
            """UPDATE project_package_import_commands
               SET status='succeeded',phase='succeeded',owner_token=NULL,
                   lease_expires_at=NULL,public_error_code=NULL,
                   updated_at=%s,completed_at=%s
               WHERE id=%s AND request_fingerprint=%s AND owner_token=%s
                 AND target_project_id=%s AND status='running'
                 AND lease_expires_at>%s""",
            (
                now_ms,
                now_ms,
                command_id,
                request_fingerprint,
                owner_token,
                target_project_id,
                now_ms,
            ),
        )
        row = await self._read_exact(session, command_id)
        if affected != 1 or row is None:
            raise ProjectImportCommandStateConflict() from None
        return _view(row, now_ms)
