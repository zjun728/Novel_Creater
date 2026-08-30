"""Atomic immutable seed CRUD, selection CAS, and backend readiness facts."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import (
    SeedAnalysisProvenance,
    SeedInspirationProvenance,
    SeedMutationCapabilities,
    SeedPayload,
    SeedProvenance,
    SeedProvenanceSelection,
    SeedSnapshotProvenance,
    build_seed_provenance,
    decode_seed_revision,
    seed_payload_hash,
    seed_revision_document,
)
from backend.http_errors import (
    ProjectBusy,
    SeedAlreadyConfirmed,
    SeedConflict,
    SeedLocked,
    SeedNotFound,
)


_STRICT = ConfigDict(strict=True, frozen=True, extra="forbid")


class CreateSeed(BaseModel):
    model_config = _STRICT
    project_id: str = Field(min_length=1)
    payload: SeedPayload
    provenance: SeedProvenanceSelection | None = None
    idempotency_key: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )


class EditSeed(BaseModel):
    model_config = _STRICT
    project_id: str = Field(min_length=1)
    seed_id: str = Field(min_length=1)
    payload: SeedPayload
    expected_seed_revision: int = Field(gt=0)
    expected_selection_revision: int = Field(ge=0)


class SelectSeed(BaseModel):
    model_config = _STRICT
    project_id: str = Field(min_length=1)
    seed_id: str = Field(min_length=1)
    expected_seed_revision: int = Field(gt=0)
    expected_selection_revision: int = Field(ge=0)


class DeleteSeed(BaseModel):
    model_config = _STRICT
    project_id: str = Field(min_length=1)
    seed_id: str = Field(min_length=1)
    expected_seed_revision: int = Field(gt=0)
    expected_selection_revision: int = Field(ge=0)


class ArchiveSeed(DeleteSeed):
    pass


class RestoreSeed(DeleteSeed):
    pass


class SeedResult(BaseModel):
    model_config = _STRICT
    id: str
    project_id: str
    status: str
    revision: int = Field(gt=0)
    revision_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: SeedPayload
    provenance: SeedProvenance | None = None
    is_selected: bool
    selection_revision: int = Field(ge=0)
    capabilities: SeedMutationCapabilities


class ActiveSeedSelection(BaseModel):
    model_config = _STRICT
    project_id: str
    selection_revision: int = Field(gt=0)
    seed_id: str
    seed_revision_id: str
    seed_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_at: int = Field(ge=0)
    updated_at: int = Field(ge=0)
    seed: SeedResult


class SelectedSeedResult(BaseModel):
    model_config = _STRICT
    active_selection: ActiveSeedSelection | None
    seed_ready: bool
    contract_ready: bool
    reasons: tuple[str, ...]


def _decode_payload(value: object) -> SeedPayload:
    return decode_seed_revision(value)[0]


def _selection_revision(selection: Mapping | None) -> int:
    return int(selection["selection_revision"]) if selection else 0


class SeedService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory=None,
        id_factory=None,
        clock=None,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))

    async def _lock_project_for_mutation(
        self, session, project_id: str
    ) -> bool:
        try:
            project = await self.repository.lock_project(session, project_id)
        except BaseException as error:
            if self._mysql_error_number(error) in {1205, 1213, 3572}:
                raise ProjectBusy() from None
            raise
        if project is None:
            raise SeedNotFound()
        return bool(
            await self.repository.count_final_chapters(session, project_id)
        )

    @staticmethod
    def _mysql_error_number(error: BaseException) -> int | None:
        seen: set[int] = set()
        current: BaseException | None = error
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if current.args and type(current.args[0]) is int:
                return current.args[0]
            current = current.__cause__ or current.__context__
        return None

    @staticmethod
    def _capabilities(
        *,
        status: str,
        selected: bool,
        referenced: bool,
        has_final_chapters: bool,
        selection_confirmed: bool = False,
        project_archived: bool = False,
    ) -> SeedMutationCapabilities:
        candidate = status == "candidate"
        archived = status == "archived"
        history_locked = has_final_chapters and referenced
        capabilities = SeedMutationCapabilities(
            referenced=referenced,
            hasFinalChapters=has_final_chapters,
            canEdit=candidate and not history_locked and not selection_confirmed,
            canSelect=(
                candidate and not has_final_chapters and not selection_confirmed
            ),
            canArchive=candidate and not selected and not referenced,
            canRestore=archived and not selected and not selection_confirmed,
            canPermanentlyDelete=not selected and not referenced,
        )
        if not project_archived:
            return capabilities
        return capabilities.model_copy(
            update={
                "canEdit": False,
                "canSelect": False,
                "canArchive": False,
                "canRestore": False,
                "canPermanentlyDelete": False,
            }
        )

    @staticmethod
    def _result(
        row: Mapping,
        *,
        is_selected: bool | None = None,
        selection_revision: int | None = None,
        referenced: bool = False,
        has_final_chapters: bool = False,
        selection_confirmed: bool = False,
        project_archived: bool = False,
    ) -> SeedResult:
        selected = (
            bool(row.get("is_selected"))
            if is_selected is None else is_selected
        )
        payload, provenance = decode_seed_revision(row["payload_json"])
        return SeedResult(
            id=row["id"],
            project_id=row["project_id"],
            status=row["status"],
            revision=int(row["revision"]),
            revision_id=row.get("revision_id", row.get("id")),
            content_hash=row["content_hash"],
            payload=payload,
            provenance=provenance,
            is_selected=selected,
            selection_revision=(
                int(row.get("selection_revision") or 0)
                if selection_revision is None else selection_revision
            ),
            capabilities=SeedService._capabilities(
                status=row["status"],
                selected=selected,
                referenced=referenced,
                has_final_chapters=has_final_chapters,
                selection_confirmed=selection_confirmed,
                project_archived=project_archived,
            ),
        )

    @staticmethod
    def _idempotent_seed_id(project_id: str, key: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"novel-creator/seed/{project_id}/{key}"))

    async def _resolve_provenance(
        self,
        session,
        project_id: str,
        selection: SeedProvenanceSelection | None,
    ) -> SeedProvenance | None:
        if selection is None:
            return None
        if selection.kind == "manual":
            return build_seed_provenance(
                kind=selection.kind,
                snapshots=(),
                analysis=None,
                inspiration_attempt=None,
                public_notes=selection.public_notes,
            )
        inputs = await self.repository.lock_seed_provenance_inputs(
            session,
            project_id,
            selection,
        )
        rows = tuple(inputs.get("snapshots") or ())
        if tuple(item.get("id") for item in rows) != selection.snapshot_ids:
            raise SeedConflict()
        try:
            snapshots = tuple(
                SeedSnapshotProvenance(
                    id=item["id"],
                    hash=item["content_hash"],
                    sourceId=item["source_id"],
                    sourceURL=item["source_url"],
                    capturedAt=int(item["captured_at"]),
                )
                for item in rows
            )
        except (KeyError, TypeError, ValueError):
            raise SeedConflict() from None
        analysis = None
        if selection.analysis_id is not None:
            row = inputs.get("analysis")
            if (
                not isinstance(row, Mapping)
                or row.get("id") != selection.analysis_id
                or row.get("status", "succeeded") != "succeeded"
            ):
                raise SeedConflict()
            try:
                analysis = SeedAnalysisProvenance(
                    id=row["id"],
                    hash=row["result_hash"],
                )
            except (KeyError, TypeError, ValueError):
                raise SeedConflict() from None
            analysis_manifest = row.get("input_manifest_json")
            if isinstance(analysis_manifest, str):
                try:
                    analysis_manifest = json.loads(analysis_manifest)
                except ValueError:
                    raise SeedConflict() from None
            frozen = (
                analysis_manifest.get("snapshots")
                if isinstance(analysis_manifest, Mapping)
                else None
            )
            expected_analysis_facts = tuple(
                (
                    item["id"],
                    item["content_hash"],
                    item["manifest_hash"],
                    item["source_id"],
                )
                for item in rows
            )
            actual_analysis_facts = (
                tuple(
                    (
                        item.get("id"),
                        item.get("hash"),
                        item.get("manifestHash"),
                        item.get("sourceId"),
                    )
                    for item in frozen
                    if isinstance(item, Mapping)
                )
                if isinstance(frozen, list)
                else ()
            )
            if actual_analysis_facts != expected_analysis_facts:
                raise SeedConflict()
        inspiration = None
        if selection.inspiration_attempt_id is not None:
            row = inputs.get("attempt")
            if (
                not isinstance(row, Mapping)
                or row.get("id") != selection.inspiration_attempt_id
                or row.get("status") != "succeeded"
                or row.get("market_analysis_id") != selection.analysis_id
                or row.get("market_analysis_hash") != analysis.hash
                or row.get("market_snapshot_id") != snapshots[0].id
                or row.get("market_snapshot_hash") != snapshots[0].hash
            ):
                raise SeedConflict()
            manifest = row.get("input_manifest_json")
            if isinstance(manifest, str):
                try:
                    manifest = json.loads(manifest)
                except ValueError:
                    raise SeedConflict() from None
            manifest_snapshots = (
                manifest.get("snapshots")
                if isinstance(manifest, Mapping)
                else None
            )
            if manifest_snapshots is None and isinstance(manifest, Mapping):
                primary = manifest.get("snapshot")
                manifest_snapshots = [primary] if primary is not None else None
            expected = tuple(
                (item.id, item.hash) for item in snapshots
            )
            actual = (
                tuple(
                    (item.get("id"), item.get("hash"))
                    for item in manifest_snapshots
                    if isinstance(item, Mapping)
                )
                if isinstance(manifest_snapshots, list)
                else ()
            )
            if actual != expected:
                raise SeedConflict()
            try:
                inspiration = SeedInspirationProvenance(
                    id=row["id"],
                    resultHash=row["result_hash"],
                )
            except (KeyError, TypeError, ValueError):
                raise SeedConflict() from None
        return build_seed_provenance(
            kind=selection.kind,
            snapshots=snapshots,
            analysis=analysis,
            inspiration_attempt=inspiration,
            public_notes=selection.public_notes,
        )

    async def _create_once(self, command: CreateSeed) -> SeedResult:
        async with self.transaction_factory() as session:
            has_final_chapters = await self._lock_project_for_mutation(
                session, command.project_id
            )
            selection = await self.repository.lock_selection(
                session, command.project_id
            )
            selection_revision = _selection_revision(selection)
            if selection is not None:
                raise SeedAlreadyConfirmed()
            provenance = await self._resolve_provenance(
                session,
                command.project_id,
                command.provenance,
            )
            seed_id = (
                self._idempotent_seed_id(
                    command.project_id,
                    command.idempotency_key,
                )
                if command.idempotency_key is not None
                else self.id_factory()
            )
            if command.idempotency_key is not None:
                existing = await self.repository.lock_seed_head(
                    session,
                    command.project_id,
                    seed_id,
                )
                if existing is not None:
                    existing_payload, existing_provenance = decode_seed_revision(
                        existing["payload_json"]
                    )
                    if (
                        existing_payload != command.payload
                        or existing_provenance != provenance
                    ):
                        raise SeedConflict()
                    referenced = bool(
                        await self.repository.dependency_count(
                            session,
                            command.project_id,
                            seed_id,
                        )
                    )
                    return self._result(
                        existing,
                        is_selected=bool(
                            selection and selection["seed_id"] == seed_id
                        ),
                        selection_revision=selection_revision,
                        referenced=referenced,
                        has_final_chapters=has_final_chapters,
                        selection_confirmed=False,
                    )
            result = await self.create_in_session(
                session,
                project_id=command.project_id,
                seed_id=seed_id,
                revision_id=self.id_factory(),
                payload=command.payload,
                provenance=provenance,
                now=self.clock(),
                selection_revision=selection_revision,
                has_final_chapters=has_final_chapters,
            )
        return result

    async def create_in_session(
        self,
        session,
        *,
        project_id: str,
        seed_id: str,
        revision_id: str,
        payload: SeedPayload,
        provenance: SeedProvenance | None,
        now: int,
        selection_revision: int = 0,
        has_final_chapters: bool = False,
    ) -> SeedResult:
        """Insert one candidate Seed in a caller-owned transaction."""

        if not isinstance(payload, SeedPayload) or (
            provenance is not None and not isinstance(provenance, SeedProvenance)
        ):
            raise TypeError("validated seed values are required")
        payload_json = canonical_json(seed_revision_document(
            payload,
            provenance,
            materialize_defaults=True,
        ))
        content_hash = seed_payload_hash(payload)
        await self.repository.insert_identity(
            session,
            {
                "id": seed_id,
                "project_id": project_id,
                "status": "candidate",
                "created_at": now,
                "updated_at": now,
            },
        )
        await self.repository.insert_revision(
            session,
            {
                "id": revision_id,
                "project_id": project_id,
                "seed_id": seed_id,
                "revision": 1,
                "payload_json": payload_json,
                "content_hash": content_hash,
                "created_at": now,
            },
        )
        await self.repository.insert_head(
            session,
            {
                "seed_id": seed_id,
                "revision_id": revision_id,
                "revision": 1,
                "content_hash": content_hash,
                "updated_at": now,
            },
        )
        return SeedResult(
            id=seed_id,
            project_id=project_id,
            status="candidate",
            revision=1,
            revision_id=revision_id,
            content_hash=content_hash,
            payload=payload,
            is_selected=False,
            provenance=provenance,
            selection_revision=selection_revision,
            capabilities=self._capabilities(
                status="candidate",
                selected=False,
                referenced=False,
                has_final_chapters=has_final_chapters,
                selection_confirmed=False,
            ),
        )

    async def create(self, command: CreateSeed) -> SeedResult:
        try:
            return await self._create_once(command)
        except Exception as error:
            if self._mysql_error_number(error) in {1205, 1213, 3572}:
                raise ProjectBusy() from None
            raise

    async def edit(self, command: EditSeed) -> SeedResult:
        async with self.transaction_factory() as session:
            has_final_chapters = await self._lock_project_for_mutation(
                session, command.project_id
            )
            selection = await self.repository.lock_selection(
                session, command.project_id
            )
            if selection is not None:
                raise SeedAlreadyConfirmed()
            head = await self.repository.lock_seed_head(
                session, command.project_id, command.seed_id
            )
            if head is None:
                raise SeedNotFound()
            if int(head["revision"]) != command.expected_seed_revision:
                raise SeedConflict()
            if _selection_revision(selection) != command.expected_selection_revision:
                raise SeedConflict()
            is_selected = bool(
                selection and selection["seed_id"] == command.seed_id
            )
            referenced = bool(
                await self.repository.dependency_count(
                    session, command.project_id, command.seed_id
                )
            )
            capabilities = self._capabilities(
                status=head["status"],
                selected=is_selected,
                referenced=referenced,
                has_final_chapters=has_final_chapters,
            )
            if not capabilities.canEdit:
                raise SeedLocked()

            revision_number = int(head["revision"]) + 1
            revision_id = self.id_factory()
            now = self.clock()
            _, provenance = decode_seed_revision(head["payload_json"])
            payload_json = canonical_json(
                seed_revision_document(
                    command.payload,
                    provenance,
                    materialize_defaults=True,
                )
            )
            content_hash = seed_payload_hash(command.payload)
            revision = {
                "id": revision_id, "project_id": command.project_id,
                "seed_id": command.seed_id, "revision": revision_number,
                "payload_json": payload_json, "content_hash": content_hash,
                "created_at": now,
            }
            await self.repository.insert_revision(session, revision)
            await self.repository.update_head(
                session,
                {
                    "seed_id": command.seed_id, "revision_id": revision_id,
                    "revision": revision_number, "content_hash": content_hash,
                    "updated_at": now,
                },
            )
            selection_revision = _selection_revision(selection)
        return SeedResult(
            id=command.seed_id, project_id=command.project_id,
            status=head["status"], revision=revision_number,
            revision_id=revision_id, content_hash=content_hash,
            payload=command.payload, is_selected=is_selected,
            provenance=provenance,
            selection_revision=selection_revision,
            capabilities=self._capabilities(
                status=head["status"],
                selected=is_selected,
                referenced=True if is_selected else referenced,
                has_final_chapters=has_final_chapters,
                selection_confirmed=False,
            ),
        )

    async def select(self, command: SelectSeed) -> SeedResult:
        async with self.transaction_factory() as session:
            has_final_chapters = await self._lock_project_for_mutation(
                session, command.project_id
            )
            selection = await self.repository.lock_selection(
                session, command.project_id
            )
            if selection is not None:
                raise SeedAlreadyConfirmed()
            head = await self.repository.lock_seed_head(
                session, command.project_id, command.seed_id
            )
            if head is None:
                raise SeedNotFound()
            if int(head["revision"]) != command.expected_seed_revision:
                raise SeedConflict()
            current_revision = _selection_revision(selection)
            if current_revision != command.expected_selection_revision:
                raise SeedConflict()
            referenced = bool(
                await self.repository.dependency_count(
                    session, command.project_id, command.seed_id
                )
            )
            capabilities = self._capabilities(
                status=head["status"],
                selected=bool(
                    selection and selection["seed_id"] == command.seed_id
                ),
                referenced=referenced,
                has_final_chapters=has_final_chapters,
                selection_confirmed=False,
            )
            if not capabilities.canSelect:
                raise SeedLocked()
            now = self.clock()
            new_revision = current_revision + 1
            row = {
                "project_id": command.project_id,
                "seed_id": command.seed_id,
                "seed_revision_id": head["revision_id"],
                "seed_hash": head["content_hash"],
                "selection_revision": new_revision,
                "selected_at": now,
                "updated_at": now,
                "expected_selection_revision": current_revision,
            }
            await self.repository.insert_selection_revision(session, row)
            await self.repository.insert_selection(session, row)
        return self._result(
            head,
            is_selected=True,
            selection_revision=new_revision,
            referenced=True,
            has_final_chapters=has_final_chapters,
            selection_confirmed=True,
        )

    async def delete(self, command: DeleteSeed) -> None:
        async with self.transaction_factory() as session:
            has_final_chapters = await self._lock_project_for_mutation(
                session, command.project_id
            )
            selection = await self.repository.lock_selection(
                session, command.project_id
            )
            head = await self.repository.lock_seed_head(
                session, command.project_id, command.seed_id
            )
            if head is None:
                raise SeedNotFound()
            if int(head["revision"]) != command.expected_seed_revision:
                raise SeedConflict()
            if _selection_revision(selection) != command.expected_selection_revision:
                raise SeedConflict()
            selected = bool(
                selection and selection["seed_id"] == command.seed_id
            )
            dependencies = await self.repository.dependency_count(
                session, command.project_id, command.seed_id
            )
            capabilities = self._capabilities(
                status=head["status"],
                selected=selected,
                referenced=bool(dependencies),
                has_final_chapters=has_final_chapters,
                selection_confirmed=selection is not None,
            )
            if not capabilities.canPermanentlyDelete:
                raise SeedLocked()
            await self.repository.physical_delete(
                session, command.project_id, command.seed_id
            )

    async def archive(self, command: ArchiveSeed) -> SeedResult:
        return await self._change_status(command, expected="candidate", target="archived")

    async def restore(self, command: RestoreSeed) -> SeedResult:
        return await self._change_status(command, expected="archived", target="candidate")

    async def _change_status(
        self,
        command: ArchiveSeed | RestoreSeed,
        *,
        expected: str,
        target: str,
    ) -> SeedResult:
        async with self.transaction_factory() as session:
            has_final_chapters = await self._lock_project_for_mutation(
                session, command.project_id
            )
            selection = await self.repository.lock_selection(
                session, command.project_id
            )
            if target == "candidate" and selection is not None:
                raise SeedAlreadyConfirmed()
            head = await self.repository.lock_seed_head(
                session, command.project_id, command.seed_id
            )
            if head is None:
                raise SeedNotFound()
            if int(head["revision"]) != command.expected_seed_revision:
                raise SeedConflict()
            selection_revision = _selection_revision(selection)
            if selection_revision != command.expected_selection_revision:
                raise SeedConflict()
            selected = bool(
                selection and selection["seed_id"] == command.seed_id
            )
            referenced = bool(
                await self.repository.dependency_count(
                    session, command.project_id, command.seed_id
                )
            )
            capabilities = self._capabilities(
                status=head["status"],
                selected=selected,
                referenced=referenced,
                has_final_chapters=has_final_chapters,
                selection_confirmed=selection is not None,
            )
            permitted = (
                capabilities.canArchive
                if target == "archived"
                else capabilities.canRestore
            )
            if head["status"] != expected or not permitted:
                raise SeedLocked()
            now = self.clock()
            if target == "archived":
                await self.repository.archive(
                    session, command.project_id, command.seed_id, now
                )
            else:
                await self.repository.restore(
                    session, command.project_id, command.seed_id, now
                )
            changed = {**head, "status": target}
        return self._result(
            changed,
            is_selected=False,
            selection_revision=selection_revision,
            referenced=referenced,
            has_final_chapters=has_final_chapters,
            selection_confirmed=selection is not None,
        )

    def _connection(self):
        if self.connection_factory is None:
            raise RuntimeError("read connection factory is not configured")
        return self.connection_factory()

    async def list(self, project_id: str) -> tuple[SeedResult, ...]:
        async with self._connection() as session:
            if hasattr(self.repository, "read_project"):
                project = await self.repository.read_project(session, project_id)
                if project is None:
                    raise SeedNotFound()
                project_archived = project.get("archived_at") is not None
            else:
                project_archived = False
            rows = await self.repository.list_heads(session, project_id)
            selection_confirmed = (
                await self.repository.read_selection(session, project_id)
            ) is not None
            has_final_chapters = bool(
                await self.repository.count_final_chapters(session, project_id)
            )
            results = []
            for row in rows:
                referenced = bool(
                    await self.repository.dependency_count(
                        session, project_id, row["id"]
                    )
                )
                results.append(
                    self._result(
                        row,
                        referenced=referenced,
                        has_final_chapters=has_final_chapters,
                        selection_confirmed=selection_confirmed,
                        project_archived=project_archived,
                    )
                )
        return tuple(results)

    async def get_selected(self, project_id: str) -> SelectedSeedResult:
        async with self._connection() as session:
            project = await self.repository.read_project(session, project_id)
            if project is None:
                raise SeedNotFound()
            project_archived = project.get("archived_at") is not None
            selected = await self.repository.read_selection(session, project_id)
            contract = await self.repository.read_contract_facts(
                session, project_id
            )
            has_final_chapters = bool(
                await self.repository.count_final_chapters(session, project_id)
            )
            referenced = (
                bool(
                    await self.repository.dependency_count(
                        session, project_id, selected["seed_id"]
                    )
                )
                if selected is not None
                else False
            )
        if selected is None:
            return SelectedSeedResult(
                active_selection=None, seed_ready=False, contract_ready=False,
                reasons=("seed_not_selected",),
            )
        result = self._result(
            selected,
            is_selected=True,
            referenced=referenced,
            has_final_chapters=has_final_chapters,
            selection_confirmed=True,
            project_archived=project_archived,
        )
        selection_updated_at = selected.get("selection_updated_at")
        if selection_updated_at is None:
            selection_updated_at = selected.get("updated_at")
        if selection_updated_at is None:
            selection_updated_at = selected["selected_at"]
        active_selection = ActiveSeedSelection(
            project_id=selected["project_id"],
            selection_revision=int(selected["selection_revision"]),
            seed_id=selected["seed_id"],
            seed_revision_id=selected["seed_revision_id"],
            seed_hash=selected["seed_hash"],
            selected_at=int(selected["selected_at"]),
            updated_at=int(selection_updated_at),
            seed=result,
        )
        has_contract = bool(contract and int(contract.get("revision") or 0) > 0)
        if not has_contract:
            return SelectedSeedResult(
                active_selection=active_selection,
                seed_ready=False, contract_ready=False,
                reasons=("creation_contract_missing",),
            )
        matches = (
            int(contract.get("selection_revision") or 0)
            == result.selection_revision
            and contract.get("seed_id") == result.id
            and contract.get("seed_revision_id") == result.revision_id
            and contract.get("seed_hash") == result.content_hash
        )
        if not matches:
            return SelectedSeedResult(
                active_selection=active_selection,
                seed_ready=False, contract_ready=False,
                reasons=("selected_seed_drift",),
            )
        return SelectedSeedResult(
            active_selection=active_selection,
            seed_ready=True, contract_ready=False,
            reasons=("binding_not_verified",),
        )
