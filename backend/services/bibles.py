"""Generation-fenced manual creation-Bible draft and confirmation service."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Literal, Mapping
from uuid import uuid4

from pydantic import ValidationError

from backend.domain.bibles import (
    BiblePayload,
    canonical_bible_hash,
)
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.http_errors import PublicDomainError


BIBLE_POLICY_VERSION = "creation-bible-v1"
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_LIST_FIELDS = (
    "worldRules",
    "coreCast",
    "factions",
    "longTermConflicts",
    "relationshipDynamics",
    "continuityGuardrails",
    "openDesignQuestions",
)


class BibleNotFound(PublicDomainError):
    status_code = 404
    code = "BibleNotFound"
    message = "Creation Bible or project not found"


class BibleConflict(PublicDomainError):
    status_code = 409
    code = "BibleConflict"
    message = "Creation Bible state changed; refresh and retry"


class BibleAlreadyConfirmed(PublicDomainError):
    status_code = 409
    code = "bible_already_confirmed"
    message = "Creation Bible is already confirmed"


class BiblePreconditionFailed(PublicDomainError):
    status_code = 422
    code = "BiblePreconditionFailed"
    message = "Creation Bible prerequisites are unavailable"


class BibleConfirmationFailed(PublicDomainError):
    status_code = 422
    code = "BibleConfirmationFailed"
    message = "Creation Bible confirmation previously failed"


class BibleConfirmationRetryable(PublicDomainError):
    status_code = 503
    code = "BibleConfirmationRetryable"
    message = "Creation Bible confirmation was not recorded; retry safely"
    retryable = True


@dataclass(frozen=True)
class BibleBasis:
    selection_revision: int
    seed_id: str
    seed_revision_id: str
    seed_hash: str
    contract_revision: int
    creation_contract_id: str
    creation_hash: str
    style_contract_id: str
    style_hash: str
    binding_revision_id: str | None
    binding_hash: str | None
    policy_version: str


@dataclass(frozen=True)
class SaveBibleDraft:
    project_id: str
    expected_draft_version: int
    payload: BiblePayload


@dataclass(frozen=True)
class CloneBibleDraft:
    project_id: str
    source_draft_id: str | None = None
    source_revision: int | None = None


@dataclass(frozen=True)
class ConfirmBible:
    project_id: str
    idempotency_key: str
    expected_draft_version: int
    expected_head_revision: int


@dataclass(frozen=True)
class _ConfirmationFailureContext:
    command: ConfirmBible
    current_basis: BibleBasis
    draft_basis: BibleBasis
    request_row: Mapping[str, object]


@dataclass(frozen=True)
class BibleDraftResult:
    project_id: str
    lifecycle: Literal["active", "archived"]
    status: Literal["missing", "current", "superseded"]
    draft_id: str | None
    draft_version: int | None
    base_head_revision: int | None
    content_hash: str | None
    payload: BiblePayload | None
    basis: BibleBasis | None
    can_edit: bool
    can_confirm: bool
    can_clone: bool
    reasons: tuple[str, ...]
    created_at: int | None
    updated_at: int | None


@dataclass(frozen=True)
class BibleRevisionResult:
    project_id: str
    lifecycle: Literal["active", "archived"]
    status: Literal["current", "superseded"]
    bible_revision_id: str
    revision: int
    content_hash: str
    payload: BiblePayload
    basis: BibleBasis
    can_edit: bool
    can_clone: bool
    reasons: tuple[str, ...]
    confirmed_at: int


@dataclass(frozen=True)
class BibleHeadResult:
    project_id: str
    lifecycle: Literal["active", "archived"]
    status: Literal["missing", "current", "superseded"]
    bible_revision_id: str | None
    revision: int
    content_hash: str | None
    payload: BiblePayload | None
    basis: BibleBasis | None
    can_edit: bool
    can_clone: bool
    reasons: tuple[str, ...]
    confirmed_at: int | None


@dataclass(frozen=True)
class BibleHistoryPage:
    items: tuple[BibleRevisionResult, ...]
    next_before_revision: int | None


def _value(source, name, default=None):
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _unique_reasons(*groups) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(reason for group in groups for reason in group)
    )


class BibleService:
    def __init__(
        self,
        repository,
        *,
        contract_service,
        transaction_factory,
        id_factory=lambda: str(uuid4()),
        clock=lambda: int(time.time() * 1000),
        failpoint=lambda _stage: None,
    ):
        self.repository = repository
        self.contract_service = contract_service
        self.transaction_factory = transaction_factory
        self.id_factory = id_factory
        self.clock = clock
        self.failpoint = failpoint

    @staticmethod
    def _lifecycle(project) -> Literal["active", "archived"]:
        return (
            "archived"
            if project.get("archived_at") is not None
            or project.get("status") == "archived"
            else "active"
        )

    @staticmethod
    def _contract_basis(result) -> tuple[BibleBasis | None, tuple[str, ...]]:
        if _value(result, "contract_ready") is not True:
            reasons = tuple(_value(result, "reasons", ()) or ())
            return None, reasons or ("contract_not_ready",)
        try:
            seed = _value(result, "seed_ref")
            basis = BibleBasis(
                selection_revision=int(_value(result, "selection_revision")),
                seed_id=_value(seed, "id"),
                seed_revision_id=_value(seed, "revision_id"),
                seed_hash=_value(seed, "content_hash"),
                contract_revision=int(_value(result, "revision")),
                creation_contract_id=_value(result, "creation_contract_id"),
                creation_hash=_value(result, "creation_hash"),
                style_contract_id=_value(result, "style_contract_id"),
                style_hash=_value(result, "style_hash"),
                binding_revision_id=None,
                binding_hash=None,
                policy_version=BIBLE_POLICY_VERSION,
            )
            if (
                basis.selection_revision <= 0
                or basis.contract_revision <= 0
                or not all(
                    isinstance(value, str) and value
                    for value in (
                        basis.seed_id,
                        basis.seed_revision_id,
                        basis.seed_hash,
                        basis.creation_contract_id,
                        basis.creation_hash,
                        basis.style_contract_id,
                        basis.style_hash,
                    )
                )
            ):
                raise ValueError("incomplete canonical contract basis")
            return basis, ()
        except (AttributeError, TypeError, ValueError):
            return None, ("contract_basis_invalid",)

    async def _basis_for_read(
        self,
        project_id: str,
        *,
        session,
    ) -> tuple[BibleBasis | None, tuple[str, ...]]:
        try:
            result = await self.contract_service.get_head(
                project_id,
                session=session,
                for_update=False,
            )
        except PublicDomainError:
            return None, ("contract_unavailable",)
        return self._contract_basis(result)

    async def _locked_current_basis(
        self,
        session,
        project_id: str,
        *,
        required: bool,
    ) -> tuple[BibleBasis | None, tuple[str, ...]]:
        try:
            result = await self.contract_service.get_head(
                project_id,
                session=session,
                for_update=True,
            )
        except PublicDomainError:
            if required:
                raise BiblePreconditionFailed() from None
            return None, ("contract_unavailable",)
        basis, reasons = self._contract_basis(result)
        if basis is None:
            if required:
                raise BiblePreconditionFailed()
            return None, reasons
        return basis, ()

    @staticmethod
    def _row_basis(row) -> BibleBasis:
        binding_id = row.get("binding_revision_id")
        binding_hash = row.get("binding_hash")
        if (binding_id is None) != (binding_hash is None):
            raise BiblePreconditionFailed()
        try:
            return BibleBasis(
                selection_revision=int(row["selection_revision"]),
                seed_id=row["seed_id"],
                seed_revision_id=row["seed_revision_id"],
                seed_hash=row["seed_hash"],
                contract_revision=int(row["contract_revision"]),
                creation_contract_id=row["creation_contract_id"],
                creation_hash=row["creation_hash"],
                style_contract_id=row["style_contract_id"],
                style_hash=row["style_hash"],
                binding_revision_id=binding_id,
                binding_hash=binding_hash,
                policy_version=row["policy_version"],
            )
        except (KeyError, TypeError, ValueError):
            raise BiblePreconditionFailed() from None

    @staticmethod
    def _payload_from_row(row, json_field: str) -> BiblePayload:
        try:
            raw = row[json_field]
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            if isinstance(raw, str):
                raw = json.loads(raw)
            if not isinstance(raw, dict):
                raise TypeError("stored Bible payload must be an object")
            normalized = dict(raw)
            for field_name in _LIST_FIELDS:
                if isinstance(normalized.get(field_name), list):
                    normalized[field_name] = tuple(normalized[field_name])
            payload = BiblePayload(**normalized)
            if canonical_bible_hash(payload) != row["content_hash"]:
                raise ValueError("stored Bible hash mismatch")
            return payload
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
            json.JSONDecodeError,
        ):
            raise BiblePreconditionFailed() from None

    @classmethod
    def _stored_draft(cls, row) -> tuple[BiblePayload, BibleBasis]:
        payload = cls._payload_from_row(row, "draft_json")
        basis = cls._row_basis(row)
        if int(row.get("draft_version") or 0) <= 0:
            raise BiblePreconditionFailed()
        return payload, basis

    @classmethod
    def _stored_revision(cls, row) -> tuple[BiblePayload, BibleBasis]:
        payload = cls._payload_from_row(row, "content_json")
        basis = cls._row_basis(row)
        if int(row.get("revision") or 0) <= 0:
            raise BiblePreconditionFailed()
        return payload, basis

    @staticmethod
    def _basis_reasons(
        stored: BibleBasis,
        current: BibleBasis | None,
    ) -> tuple[str, ...]:
        if current is None:
            return ("contract_not_ready",)
        reasons = []
        if stored.selection_revision != current.selection_revision:
            reasons.append("selection_revision_changed")
        if (
            stored.seed_id != current.seed_id
            or stored.seed_revision_id != current.seed_revision_id
            or stored.seed_hash != current.seed_hash
        ):
            reasons.append("seed_generation_changed")
        if stored.contract_revision != current.contract_revision:
            reasons.append("contract_revision_changed")
        if (
            stored.creation_contract_id != current.creation_contract_id
            or stored.creation_hash != current.creation_hash
        ):
            reasons.append("creation_contract_changed")
        if (
            stored.style_contract_id != current.style_contract_id
            or stored.style_hash != current.style_hash
        ):
            reasons.append("style_contract_changed")
        if stored.policy_version != BIBLE_POLICY_VERSION:
            reasons.append("bible_policy_changed")
        return tuple(reasons)

    @staticmethod
    def _draft_row(
        *,
        project_id: str,
        draft_id: str,
        payload: BiblePayload,
        basis: BibleBasis,
        base_head_revision: int,
        draft_version: int,
        binding_revision_id: str | None,
        binding_hash: str | None,
        created_at: int,
        updated_at: int,
    ) -> dict:
        return {
            "id": draft_id,
            "project_id": project_id,
            "active_slot": 1,
            "base_head_revision": base_head_revision,
            "selection_revision": basis.selection_revision,
            "seed_id": basis.seed_id,
            "seed_revision_id": basis.seed_revision_id,
            "seed_hash": basis.seed_hash,
            "contract_revision": basis.contract_revision,
            "creation_contract_id": basis.creation_contract_id,
            "creation_hash": basis.creation_hash,
            "style_contract_id": basis.style_contract_id,
            "style_hash": basis.style_hash,
            "binding_revision_id": binding_revision_id,
            "binding_hash": binding_hash,
            "policy_version": BIBLE_POLICY_VERSION,
            "draft_json": canonical_json(payload),
            "content_hash": canonical_bible_hash(payload),
            "draft_version": draft_version,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def _draft_view(
        self,
        *,
        project,
        row,
        head,
        current_basis,
        current_basis_reasons=(),
    ) -> BibleDraftResult:
        lifecycle = self._lifecycle(project)
        lifecycle_reasons = (
            ("project_archived",) if lifecycle == "archived" else ()
        )
        if head is not None and int(head.get("revision") or 0) > 0:
            return BibleDraftResult(
                project_id=project["id"],
                lifecycle=lifecycle,
                status="missing",
                draft_id=None,
                draft_version=None,
                base_head_revision=None,
                content_hash=None,
                payload=None,
                basis=current_basis,
                can_edit=False,
                can_confirm=False,
                can_clone=False,
                reasons=_unique_reasons(
                    current_basis_reasons, ("bible_confirmed",), lifecycle_reasons,
                ),
                created_at=None,
                updated_at=None,
            )
        if row is None:
            reasons = _unique_reasons(
                current_basis_reasons,
                lifecycle_reasons,
            )
            can_edit = lifecycle == "active" and current_basis is not None
            can_clone = (
                can_edit
                and head is not None
                and int(head.get("revision") or 0) > 0
            )
            return BibleDraftResult(
                project_id=project["id"],
                lifecycle=lifecycle,
                status="missing",
                draft_id=None,
                draft_version=None,
                base_head_revision=None,
                content_hash=None,
                payload=None,
                basis=current_basis,
                can_edit=can_edit,
                can_confirm=False,
                can_clone=can_clone,
                reasons=reasons,
                created_at=None,
                updated_at=None,
            )
        payload, stored_basis = self._stored_draft(row)
        state_reasons = list(self._basis_reasons(stored_basis, current_basis))
        if (
            head is None
            or int(head.get("revision", -1))
            != int(row["base_head_revision"])
        ):
            state_reasons.append("bible_head_changed")
        status = "current" if not state_reasons else "superseded"
        reasons = _unique_reasons(
            current_basis_reasons,
            tuple(state_reasons),
            lifecycle_reasons,
        )
        editable = lifecycle == "active" and status == "current"
        return BibleDraftResult(
            project_id=project["id"],
            lifecycle=lifecycle,
            status=status,
            draft_id=row["id"],
            draft_version=int(row["draft_version"]),
            base_head_revision=int(row["base_head_revision"]),
            content_hash=row["content_hash"],
            payload=payload,
            basis=stored_basis,
            can_edit=editable,
            can_confirm=editable,
            can_clone=(
                lifecycle == "active"
                and current_basis is not None
                and status == "superseded"
            ),
            reasons=reasons,
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    def _revision_view(
        self,
        *,
        project,
        row,
        head,
        current_basis,
        current_basis_reasons=(),
    ) -> BibleRevisionResult:
        lifecycle = self._lifecycle(project)
        payload, stored_basis = self._stored_revision(row)
        state_reasons = list(self._basis_reasons(stored_basis, current_basis))
        if (
            head is None
            or int(head.get("revision") or 0) != int(row["revision"])
            or head.get("bible_revision_id") != row["id"]
            or head.get("content_hash") != row["content_hash"]
        ):
            state_reasons.append("bible_revision_replaced")
        status = "current" if not state_reasons else "superseded"
        reasons = _unique_reasons(
            current_basis_reasons,
            tuple(state_reasons),
            ("project_archived",) if lifecycle == "archived" else (),
        )
        return BibleRevisionResult(
            project_id=project["id"],
            lifecycle=lifecycle,
            status=status,
            bible_revision_id=row["id"],
            revision=int(row["revision"]),
            content_hash=row["content_hash"],
            payload=payload,
            basis=stored_basis,
            can_edit=False,
            can_clone=False,
            reasons=_unique_reasons(reasons, ("bible_confirmed",)),
            confirmed_at=int(row["confirmed_at"]),
        )

    async def get_draft(self, project_id: str) -> BibleDraftResult:
        async with self.transaction_factory() as session:
            project = await self.repository.read_project(session, project_id)
            if project is None:
                raise BibleNotFound()
            row = await self.repository.read_active_draft(session, project_id)
            head = await self.repository.read_bible_head(session, project_id)
            if head is None:
                raise BiblePreconditionFailed()
            basis, basis_reasons = await self._basis_for_read(
                project_id,
                session=session,
            )
        return self._draft_view(
            project=project,
            row=row,
            head=head,
            current_basis=basis,
            current_basis_reasons=basis_reasons,
        )

    async def save_draft(self, command: SaveBibleDraft) -> BibleDraftResult:
        if (
            type(command.expected_draft_version) is not int
            or command.expected_draft_version < 0
            or not isinstance(command.payload, BiblePayload)
        ):
            raise BiblePreconditionFailed()
        async with self.transaction_factory() as session:
            project = await self.repository.lock_project(
                session, command.project_id
            )
            if project is None:
                raise BibleNotFound()
            head = await self.repository.lock_bible_head(
                session, command.project_id
            )
            if head is None:
                raise BiblePreconditionFailed()
            if int(head["revision"]) > 0:
                raise BibleAlreadyConfirmed()
            basis, _ = await self._locked_current_basis(
                session, command.project_id, required=True
            )
            assert basis is not None
            current = await self.repository.lock_active_draft(
                session, command.project_id
            )
            if command.expected_draft_version == 0:
                if current is not None:
                    _, current_stored_basis = self._stored_draft(current)
                    reasons = list(
                        self._basis_reasons(current_stored_basis, basis)
                    )
                    if int(current["base_head_revision"]) != int(
                        head["revision"]
                    ):
                        reasons.append("bible_head_changed")
                    if not reasons:
                        raise BibleConflict()
                    # Explicit replacement retires the superseded product slot;
                    # the immutable source row remains stored for audit/FK use.
                    if not await self.repository.deactivate_active_draft(
                        session,
                        command.project_id,
                        current["id"],
                        int(current["draft_version"]),
                        current["content_hash"],
                    ):
                        raise BibleConflict()
                now = self.clock()
                row = self._draft_row(
                    project_id=command.project_id,
                    draft_id=self.id_factory(),
                    payload=command.payload,
                    basis=basis,
                    base_head_revision=int(head["revision"]),
                    draft_version=1,
                    binding_revision_id=None,
                    binding_hash=None,
                    created_at=now,
                    updated_at=now,
                )
                if not await self.repository.insert_draft(session, row):
                    raise BibleConflict()
            else:
                if current is None:
                    raise BibleConflict()
                _, stored_basis = self._stored_draft(current)
                if (
                    self._basis_reasons(stored_basis, basis)
                    or int(current["base_head_revision"])
                    != int(head["revision"])
                    or int(current["draft_version"])
                    != command.expected_draft_version
                ):
                    raise BibleConflict()
                row = self._draft_row(
                    project_id=command.project_id,
                    draft_id=current["id"],
                    payload=command.payload,
                    basis=basis,
                    base_head_revision=int(current["base_head_revision"]),
                    draft_version=command.expected_draft_version + 1,
                    binding_revision_id=current.get("binding_revision_id"),
                    binding_hash=current.get("binding_hash"),
                    created_at=int(current["created_at"]),
                    updated_at=self.clock(),
                )
                if not await self.repository.cas_update_draft(
                    session,
                    row,
                    command.expected_draft_version,
                ):
                    raise BibleConflict()
            return self._draft_view(
                project=project,
                row=row,
                head=head,
                current_basis=basis,
            )

    @staticmethod
    def _validate_clone(command: CloneBibleDraft) -> None:
        has_draft = command.source_draft_id is not None
        has_revision = command.source_revision is not None
        if has_draft == has_revision:
            raise BiblePreconditionFailed()
        if has_draft and (
            not isinstance(command.source_draft_id, str)
            or not 1 <= len(command.source_draft_id) <= 36
        ):
            raise BiblePreconditionFailed()
        if has_revision and (
            type(command.source_revision) is not int
            or command.source_revision <= 0
        ):
            raise BiblePreconditionFailed()

    async def clone_draft(
        self,
        command: CloneBibleDraft,
    ) -> BibleDraftResult:
        self._validate_clone(command)
        async with self.transaction_factory() as session:
            project = await self.repository.lock_project(
                session, command.project_id
            )
            if project is None:
                raise BibleNotFound()
            head = await self.repository.lock_bible_head(
                session, command.project_id
            )
            if head is None:
                raise BiblePreconditionFailed()
            if int(head["revision"]) > 0:
                raise BibleAlreadyConfirmed()
            basis, _ = await self._locked_current_basis(
                session, command.project_id, required=True
            )
            assert basis is not None
            current = await self.repository.lock_active_draft(
                session, command.project_id
            )
            current_reasons = []
            if current is not None:
                _, active_basis = self._stored_draft(current)
                current_reasons.extend(
                    self._basis_reasons(active_basis, basis)
                )
                if int(current["base_head_revision"]) != int(head["revision"]):
                    current_reasons.append("bible_head_changed")
            if command.source_draft_id is not None:
                if (
                    current is None
                    or current["id"] != command.source_draft_id
                ):
                    raise BibleNotFound()
                if not current_reasons:
                    raise BibleConflict()
                source_payload, _ = self._stored_draft(current)
            else:
                source = await self.repository.read_revision(
                    session,
                    command.project_id,
                    command.source_revision,
                )
                if source is None:
                    raise BibleNotFound()
                source_payload, _ = self._stored_revision(source)
            if current is not None:
                if not current_reasons:
                    raise BibleConflict()
                # Clone copies the visible superseded source into the current
                # basis, then retires only its product slot, never its row.
                if not await self.repository.deactivate_active_draft(
                    session,
                    command.project_id,
                    current["id"],
                    int(current["draft_version"]),
                    current["content_hash"],
                ):
                    raise BibleConflict()
            now = self.clock()
            row = self._draft_row(
                project_id=command.project_id,
                draft_id=self.id_factory(),
                payload=source_payload,
                basis=basis,
                base_head_revision=int(head["revision"]),
                draft_version=1,
                binding_revision_id=None,
                binding_hash=None,
                created_at=now,
                updated_at=now,
            )
            if not await self.repository.insert_draft(session, row):
                raise BibleConflict()
            return self._draft_view(
                project=project,
                row=row,
                head=head,
                current_basis=basis,
            )

    @staticmethod
    def _validate_confirmation(command: ConfirmBible) -> None:
        if (
            not isinstance(command.idempotency_key, str)
            or not 1 <= len(command.idempotency_key) <= 64
            or _IDEMPOTENCY_KEY.fullmatch(command.idempotency_key) is None
            or type(command.expected_draft_version) is not int
            or command.expected_draft_version <= 0
            or type(command.expected_head_revision) is not int
            or command.expected_head_revision < 0
        ):
            raise BiblePreconditionFailed()

    @staticmethod
    def _confirmation_request_hash(
        *,
        project_id: str,
        draft_id: str,
        draft_version: int,
        draft_hash: str,
        expected_head_revision: int,
    ) -> str:
        return canonical_hash(
            {
                "projectId": project_id,
                "draftId": draft_id,
                "draftVersion": draft_version,
                "draftHash": draft_hash,
                "expectedHeadRevision": expected_head_revision,
            }
        )

    @classmethod
    def _request_matches_command(cls, existing, command: ConfirmBible) -> bool:
        request_hash = cls._confirmation_request_hash(
            project_id=command.project_id,
            draft_id=existing["draft_id"],
            draft_version=command.expected_draft_version,
            draft_hash=existing["draft_hash"],
            expected_head_revision=command.expected_head_revision,
        )
        return (
            int(existing["draft_version"])
            == command.expected_draft_version
            and existing["request_hash"] == request_hash
        )

    @staticmethod
    def _request_matches_source(existing, source) -> bool:
        return (
            source is not None
            and source.get("id") == existing.get("draft_id")
            and int(source.get("selection_revision") or 0)
            == int(existing.get("selection_revision") or -1)
            and int(source.get("contract_revision") or 0)
            == int(existing.get("contract_revision") or -1)
            and source.get("creation_contract_id")
            == existing.get("creation_contract_id")
            and source.get("creation_hash") == existing.get("creation_hash")
            and source.get("style_contract_id")
            == existing.get("style_contract_id")
            and source.get("style_hash") == existing.get("style_hash")
        )

    async def _replay_confirmation(
        self,
        session,
        project,
        existing,
        command: ConfirmBible,
    ) -> BibleRevisionResult:
        source = await self.repository.read_draft(
            session,
            command.project_id,
            existing["draft_id"],
        )
        if (
            not self._request_matches_command(existing, command)
            or not self._request_matches_source(existing, source)
        ):
            raise BibleConflict()
        status = existing.get("status")
        if status == "failed":
            raise BibleConfirmationFailed()
        if status != "succeeded":
            raise BibleConflict()
        head = await self.repository.lock_bible_head(
            session, command.project_id
        )
        row = await self.repository.read_revision(
            session,
            command.project_id,
            int(existing["result_revision"]),
        )
        if (
            head is None
            or row is None
            or row.get("id") != existing.get("bible_revision_id")
            or row.get("content_hash") != existing.get("result_hash")
        ):
            raise BiblePreconditionFailed()
        payload, basis = self._stored_revision(row)
        return BibleRevisionResult(
            project_id=project["id"],
            lifecycle="active",
            status="current",
            bible_revision_id=row["id"],
            revision=int(row["revision"]),
            content_hash=row["content_hash"],
            payload=payload,
            basis=basis,
            can_edit=False,
            can_clone=False,
            reasons=("bible_confirmed",),
            confirmed_at=int(row["confirmed_at"]),
        )

    async def _confirm_once(
        self,
        command: ConfirmBible,
        reserved: list[_ConfirmationFailureContext],
    ) -> BibleRevisionResult:
        async with self.transaction_factory() as session:
            project = await self.repository.lock_project(
                session, command.project_id
            )
            if project is None:
                raise BibleNotFound()
            existing = await self.repository.read_confirmation_request(
                session,
                command.project_id,
                command.idempotency_key,
            )
            if existing is not None:
                return await self._replay_confirmation(
                    session,
                    project,
                    existing,
                    command,
                )
            head = await self.repository.lock_bible_head(
                session, command.project_id
            )
            if head is not None and int(head["revision"]) > 0:
                raise BibleAlreadyConfirmed()
            basis, _ = await self._locked_current_basis(
                session, command.project_id, required=True
            )
            assert basis is not None
            draft = await self.repository.lock_active_draft(
                session, command.project_id
            )
            if draft is None or head is None:
                raise BibleConflict()
            payload, stored_basis = self._stored_draft(draft)
            if (
                self._basis_reasons(stored_basis, basis)
                or int(draft["draft_version"])
                != command.expected_draft_version
                or int(draft["base_head_revision"])
                != command.expected_head_revision
                or int(head["revision"])
                != command.expected_head_revision
            ):
                raise BibleConflict()
            request_hash = self._confirmation_request_hash(
                project_id=command.project_id,
                draft_id=draft["id"],
                draft_version=command.expected_draft_version,
                draft_hash=draft["content_hash"],
                expected_head_revision=command.expected_head_revision,
            )
            now = self.clock()
            request_id = self.id_factory()
            revision_id = self.id_factory()
            result_revision = command.expected_head_revision + 1
            request_row = {
                "id": request_id,
                "project_id": command.project_id,
                "selection_revision": basis.selection_revision,
                "contract_revision": basis.contract_revision,
                "creation_contract_id": basis.creation_contract_id,
                "creation_hash": basis.creation_hash,
                "style_contract_id": basis.style_contract_id,
                "style_hash": basis.style_hash,
                "draft_id": draft["id"],
                "draft_version": int(draft["draft_version"]),
                "draft_hash": draft["content_hash"],
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "created_at": now,
            }
            if not await self.repository.insert_confirmation_request(
                session, request_row
            ):
                raise BibleConflict()
            reserved.append(
                _ConfirmationFailureContext(
                    command=command,
                    current_basis=basis,
                    draft_basis=stored_basis,
                    request_row=request_row,
                )
            )
            self.failpoint("after_request_reserve")
            revision_row = {
                "id": revision_id,
                "project_id": command.project_id,
                "revision": result_revision,
                "selection_revision": stored_basis.selection_revision,
                "seed_id": stored_basis.seed_id,
                "seed_revision_id": stored_basis.seed_revision_id,
                "seed_hash": stored_basis.seed_hash,
                "contract_revision": stored_basis.contract_revision,
                "creation_contract_id": stored_basis.creation_contract_id,
                "creation_hash": stored_basis.creation_hash,
                "style_contract_id": stored_basis.style_contract_id,
                "style_hash": stored_basis.style_hash,
                "binding_revision_id": stored_basis.binding_revision_id,
                "binding_hash": stored_basis.binding_hash,
                "policy_version": stored_basis.policy_version,
                "content_json": canonical_json(payload),
                "content_hash": draft["content_hash"],
                "confirmed_at": now,
            }
            if not await self.repository.insert_revision(
                session, revision_row
            ):
                raise BibleConflict()
            self.failpoint("after_revision_insert")
            if not await self.repository.cas_bible_head(
                session,
                {
                    "project_id": command.project_id,
                    "base_revision": command.expected_head_revision,
                    "revision": result_revision,
                    "bible_revision_id": revision_id,
                    "content_hash": draft["content_hash"],
                    "updated_at": now,
                },
            ):
                raise BibleConflict()
            self.failpoint("after_head_advance")
            if not await self.repository.deactivate_active_draft(
                session,
                command.project_id,
                draft["id"],
                int(draft["draft_version"]),
                draft["content_hash"],
            ):
                raise BibleConflict()
            self.failpoint("after_draft_clear")
            self.failpoint("before_request_success")
            if not await self.repository.succeed_confirmation_request(
                session,
                {
                    "project_id": command.project_id,
                    "idempotency_key": command.idempotency_key,
                    "request_hash": request_hash,
                    "bible_revision_id": revision_id,
                    "result_revision": result_revision,
                    "result_hash": draft["content_hash"],
                    "completed_at": now,
                },
            ):
                raise BibleConflict()
            committed_head = {
                "project_id": command.project_id,
                "revision": result_revision,
                "bible_revision_id": revision_id,
                "content_hash": draft["content_hash"],
                "updated_at": now,
            }
            return self._revision_view(
                project=project,
            row=revision_row,
            head=committed_head,
            current_basis=basis,
        )

    async def _settle_confirmation_failure(
        self,
        context: _ConfirmationFailureContext,
    ) -> BibleRevisionResult:
        try:
            async with self.transaction_factory() as session:
                command = context.command
                project = await self.repository.lock_project(
                    session, command.project_id
                )
                if project is None:
                    raise BibleConfirmationFailed()
                existing = await self.repository.read_confirmation_request(
                    session,
                    command.project_id,
                    command.idempotency_key,
                )
                if existing is not None:
                    return await self._replay_confirmation(
                        session,
                        project,
                        existing,
                        command,
                    )

                basis, _ = await self._locked_current_basis(
                    session,
                    command.project_id,
                    required=True,
                )
                draft = await self.repository.lock_active_draft(
                    session, command.project_id
                )
                head = await self.repository.lock_bible_head(
                    session, command.project_id
                )
                request_row = context.request_row
                expected_request_hash = self._confirmation_request_hash(
                    project_id=command.project_id,
                    draft_id=str(request_row["draft_id"]),
                    draft_version=int(request_row["draft_version"]),
                    draft_hash=str(request_row["draft_hash"]),
                    expected_head_revision=command.expected_head_revision,
                )
                matches = (
                    basis == context.current_basis
                    and draft is not None
                    and head is not None
                    and draft.get("id") == request_row["draft_id"]
                    and int(draft.get("draft_version") or 0)
                    == int(request_row["draft_version"])
                    and draft.get("content_hash") == request_row["draft_hash"]
                    and int(draft.get("base_head_revision", -1))
                    == command.expected_head_revision
                    and int(head.get("revision", -1))
                    == command.expected_head_revision
                    and request_row["request_hash"]
                    == expected_request_hash
                )
                if matches:
                    _, stored_basis = self._stored_draft(draft)
                    matches = stored_basis == context.draft_basis
                if not matches:
                    raise BibleConfirmationRetryable()
                failed_row = dict(request_row)
                failed_row["completed_at"] = self.clock()
                inserted = (
                    await self.repository.insert_failed_confirmation_request(
                        session,
                        failed_row,
                    )
                )
                if not inserted:
                    raise BibleConfirmationRetryable()
            raise BibleConfirmationFailed()
        except (
            BibleConflict,
            BibleConfirmationFailed,
            BibleConfirmationRetryable,
        ):
            raise
        except Exception:
            raise BibleConfirmationRetryable() from None

    async def confirm(
        self,
        command: ConfirmBible,
    ) -> BibleRevisionResult:
        self._validate_confirmation(command)
        reserved: list[_ConfirmationFailureContext] = []
        try:
            return await self._confirm_once(command, reserved)
        except PublicDomainError:
            raise
        except Exception:
            if reserved:
                return await self._settle_confirmation_failure(reserved[0])
            raise BibleConfirmationRetryable() from None

    async def get_head(self, project_id: str) -> BibleHeadResult:
        async with self.transaction_factory() as session:
            project = await self.repository.read_project(session, project_id)
            if project is None:
                raise BibleNotFound()
            head = await self.repository.read_bible_head(session, project_id)
            if head is None:
                raise BiblePreconditionFailed()
            row = (
                await self.repository.read_revision(
                    session, project_id, int(head["revision"])
                )
                if int(head["revision"]) > 0
                else None
            )
            basis, basis_reasons = await self._basis_for_read(
                project_id,
                session=session,
            )
        lifecycle = self._lifecycle(project)
        if int(head["revision"]) == 0:
            reasons = _unique_reasons(
                basis_reasons,
                ("project_archived",) if lifecycle == "archived" else (),
            )
            return BibleHeadResult(
                project_id=project_id,
                lifecycle=lifecycle,
                status="missing",
                bible_revision_id=None,
                revision=0,
                content_hash=None,
                payload=None,
                basis=basis,
                can_edit=False,
                can_clone=False,
                reasons=reasons,
                confirmed_at=None,
            )
        if (
            row is None
            or row.get("id") != head.get("bible_revision_id")
            or row.get("content_hash") != head.get("content_hash")
        ):
            raise BiblePreconditionFailed()
        revision = self._revision_view(
            project=project,
            row=row,
            head=head,
            current_basis=basis,
            current_basis_reasons=basis_reasons,
        )
        return BibleHeadResult(
            project_id=revision.project_id,
            lifecycle=revision.lifecycle,
            status=revision.status,
            bible_revision_id=revision.bible_revision_id,
            revision=revision.revision,
            content_hash=revision.content_hash,
            payload=revision.payload,
            basis=revision.basis,
            can_edit=False,
            can_clone=revision.can_clone,
            reasons=revision.reasons,
            confirmed_at=revision.confirmed_at,
        )

    @staticmethod
    def _validate_history_args(limit, before_revision=None) -> None:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or (
                before_revision is not None
                and (
                    type(before_revision) is not int
                    or before_revision <= 0
                )
            )
        ):
            raise BiblePreconditionFailed()

    async def history(
        self,
        project_id: str,
        *,
        limit: int = 20,
        before_revision: int | None = None,
    ) -> BibleHistoryPage:
        self._validate_history_args(limit, before_revision)
        async with self.transaction_factory() as session:
            project = await self.repository.read_project(session, project_id)
            if project is None:
                raise BibleNotFound()
            head = await self.repository.read_bible_head(session, project_id)
            if head is None:
                raise BiblePreconditionFailed()
            revision_refs = await self.repository.list_revisions(
                session,
                project_id,
                before_revision=before_revision,
                limit=limit,
            )
            page = revision_refs[:limit]
            rows = []
            for item in page:
                row = await self.repository.read_revision(
                    session,
                    project_id,
                    int(item["revision"]),
                )
                if row is None:
                    raise BiblePreconditionFailed()
                rows.append(row)
            basis, basis_reasons = await self._basis_for_read(
                project_id,
                session=session,
            )
        return BibleHistoryPage(
            items=tuple(
                self._revision_view(
                    project=project,
                    row=row,
                    head=head,
                    current_basis=basis,
                    current_basis_reasons=basis_reasons,
                )
                for row in rows
            ),
            next_before_revision=(
                int(page[-1]["revision"])
                if len(revision_refs) > limit
                else None
            ),
        )

    async def get_history_revision(
        self,
        project_id: str,
        revision: int,
    ) -> BibleRevisionResult:
        if type(revision) is not int or revision <= 0:
            raise BiblePreconditionFailed()
        async with self.transaction_factory() as session:
            project = await self.repository.read_project(session, project_id)
            if project is None:
                raise BibleNotFound()
            head = await self.repository.read_bible_head(session, project_id)
            row = await self.repository.read_revision(
                session, project_id, revision
            )
            if head is None:
                raise BiblePreconditionFailed()
            if row is None:
                raise BibleNotFound()
            basis, basis_reasons = await self._basis_for_read(
                project_id,
                session=session,
            )
        return self._revision_view(
            project=project,
            row=row,
            head=head,
            current_basis=basis,
            current_basis_reasons=basis_reasons,
        )


__all__ = (
    "BIBLE_POLICY_VERSION",
    "BibleAlreadyConfirmed",
    "BibleBasis",
    "BibleConfirmationFailed",
    "BibleConfirmationRetryable",
    "BibleConflict",
    "BibleDraftResult",
    "BibleHeadResult",
    "BibleHistoryPage",
    "BibleNotFound",
    "BiblePreconditionFailed",
    "BibleRevisionResult",
    "BibleService",
    "CloneBibleDraft",
    "ConfirmBible",
    "SaveBibleDraft",
)
