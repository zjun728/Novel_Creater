"""Prepare one frozen Candidate for author-reviewed atomic finalization."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from backend.domain.finalization import (
    ChangeSetSource,
    DeterministicBlock,
    FinalizationAuthority,
    FinalizationChangeSet,
    QualityFinding,
    QualityReportPayload,
    QualityReportStatus,
    change_set_hash,
)
from backend.domain.json_contracts import canonical_hash
from backend.prompts.finalization import (
    FinalizationBinding,
    FinalizationProviderManifest,
)
from backend.repositories.finalization import FinalizationRepository
from backend.services.finalization_checks import (
    run_finalization_prechecks,
    validate_change_set_context,
)


_HASH_LENGTH = 64
_POLICY_VERSION_MAX_LENGTH = 32


class FinalizationConflict(RuntimeError):
    """Stable public preparation conflict without persisted content."""


@dataclass(frozen=True, slots=True)
class PrepareFinalization:
    project_id: str
    chapter_session_id: str
    candidate_id: str
    candidate_hash: str
    expected_canon_revision: int
    expected_planning_hash: str
    expected_outline_hash: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.project_id,
                self.chapter_session_id,
                self.candidate_id,
            )
        ):
            raise ValueError("finalization identity is invalid")
        for value in (
            self.candidate_hash,
            self.expected_planning_hash,
            self.expected_outline_hash,
            self.idempotency_key,
        ):
            if (
                not isinstance(value, str)
                or len(value) != _HASH_LENGTH
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError("finalization hash is invalid")
        if type(self.expected_canon_revision) is not int or self.expected_canon_revision < 0:
            raise ValueError("expected Canon revision is invalid")


def _validate_review_identity(
    project_id: str,
    chapter_session_id: str,
    expected_revision: int,
    expected_revision_hash: str,
) -> None:
    if not all(
        isinstance(value, str) and value.strip()
        for value in (project_id, chapter_session_id)
    ):
        raise ValueError("finalization identity is invalid")
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError("finalization revision is invalid")
    if (
        not isinstance(expected_revision_hash, str)
        or len(expected_revision_hash) != _HASH_LENGTH
        or any(
            character not in "0123456789abcdef"
            for character in expected_revision_hash
        )
    ):
        raise ValueError("finalization hash is invalid")


@dataclass(frozen=True, slots=True)
class CorrectFinalization:
    project_id: str
    chapter_session_id: str
    expected_revision: int
    expected_revision_hash: str
    change_set: FinalizationChangeSet

    def __post_init__(self) -> None:
        _validate_review_identity(
            self.project_id,
            self.chapter_session_id,
            self.expected_revision,
            self.expected_revision_hash,
        )
        if type(self.change_set) is not FinalizationChangeSet:
            raise ValueError("Finalization ChangeSet is invalid")


@dataclass(frozen=True, slots=True)
class ConfirmFinalization:
    project_id: str
    chapter_session_id: str
    expected_revision: int
    expected_revision_hash: str

    def __post_init__(self) -> None:
        _validate_review_identity(
            self.project_id,
            self.chapter_session_id,
            self.expected_revision,
            self.expected_revision_hash,
        )


@dataclass(frozen=True, slots=True)
class CancelFinalization:
    project_id: str
    chapter_session_id: str
    expected_revision: int
    expected_revision_hash: str

    def __post_init__(self) -> None:
        _validate_review_identity(
            self.project_id,
            self.chapter_session_id,
            self.expected_revision,
            self.expected_revision_hash,
        )


@dataclass(frozen=True, slots=True)
class PreparedFinalization:
    attempt_id: str
    status: str
    quality_status: str | None = None
    current_revision: int | None = None
    current_revision_hash: str | None = None
    hard_blocks: tuple[DeterministicBlock, ...] = ()
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ReviewedFinalization:
    attempt_id: str
    status: str
    current_revision: int
    current_revision_hash: str
    confirmed_revision: int | None = None
    confirmed_revision_hash: str | None = None


def _public_values(values) -> list[dict[str, object]]:
    return [
        value.model_dump(by_alias=True, mode="json")
        for value in values
    ]


class FinalizationService:
    def __init__(
        self,
        *,
        transaction_factory,
        quality_provider,
        extraction_provider,
        repository: FinalizationRepository | None = None,
        clock: Callable[[], int],
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.transaction_factory = transaction_factory
        self.quality_provider = quality_provider
        self.extraction_provider = extraction_provider
        self.repository = repository or FinalizationRepository()
        self._clock = clock
        self._id = id_factory or (lambda: str(uuid4()))

    @staticmethod
    def _binding_identity(binding: object) -> dict[str, object] | None:
        if not isinstance(binding, dict):
            return None
        provider_id = binding.get("id")
        model_name = binding.get("model_name")
        revision = binding.get("revision")
        if (
            not isinstance(provider_id, str)
            or not provider_id.strip()
            or not isinstance(model_name, str)
            or not model_name.strip()
            or type(revision) is not int
            or revision < 0
        ):
            return None
        return {
            "provider_id": provider_id,
            "model_name": model_name,
            "provider_profile_revision": revision,
        }

    @classmethod
    def _context_manifest(
        cls,
        command: PrepareFinalization,
        chapter_number: int,
        snapshot: dict[str, object],
    ) -> dict[str, object]:
        policy_version = snapshot.get("policy_version")
        if (
            not isinstance(policy_version, str)
            or not policy_version.strip()
            or len(policy_version) > _POLICY_VERSION_MAX_LENGTH
        ):
            raise FinalizationConflict("FINALIZATION_CONTEXT_INVALID")
        contexts = {}
        for name in ("canon", "planning", "outline", "contract", "bible"):
            value = snapshot.get(f"{name}_context")
            if type(value) is not dict:
                raise FinalizationConflict("FINALIZATION_CONTEXT_INVALID")
            try:
                contexts[f"{name}Hash"] = canonical_hash(value)
            except (TypeError, ValueError, UnicodeError, RecursionError):
                raise FinalizationConflict("FINALIZATION_CONTEXT_INVALID") from None
        references = snapshot.get("reference_sources")
        if type(references) not in (list, tuple):
            raise FinalizationConflict("FINALIZATION_CONTEXT_INVALID")
        reference_manifest = []
        for item in references:
            if not isinstance(item, dict):
                raise FinalizationConflict("FINALIZATION_CONTEXT_INVALID")
            reference_id = item.get("id")
            reference_hash = item.get("content_hash")
            if not isinstance(reference_id, str) or not isinstance(reference_hash, str):
                raise FinalizationConflict("FINALIZATION_CONTEXT_INVALID")
            reference_manifest.append({"id": reference_id, "contentHash": reference_hash})
        return {
            "schemaVersion": "finalization-context-v1",
            "projectId": command.project_id,
            "chapterSessionId": command.chapter_session_id,
            "candidateId": command.candidate_id,
            "candidateHash": command.candidate_hash,
            "chapterNumber": chapter_number,
            "expectedCanonRevision": command.expected_canon_revision,
            "expectedPlanningHash": command.expected_planning_hash,
            "expectedOutlineHash": command.expected_outline_hash,
            "policyVersion": policy_version,
            "contexts": contexts,
            "bindings": {
                "audit": cls._binding_identity(snapshot.get("audit_binding")),
                "extraction": cls._binding_identity(snapshot.get("extraction_binding")),
            },
            "references": reference_manifest,
        }

    @classmethod
    def request_fingerprint(
        cls,
        command: PrepareFinalization,
        snapshot: dict[str, object],
        chapter_number: int = 1,
    ) -> str:
        context_manifest = cls._context_manifest(command, chapter_number, snapshot)
        return canonical_hash({
            "schemaVersion": "finalization-prepare-request-v1",
            "contextManifestHash": canonical_hash(context_manifest),
            "idempotencyKey": command.idempotency_key,
        })

    @staticmethod
    def _authority(
        command: PrepareFinalization,
        context_manifest_hash: str,
        request_fingerprint: str,
    ) -> FinalizationAuthority:
        return FinalizationAuthority.model_validate({
            "projectId": command.project_id,
            "chapterSessionId": command.chapter_session_id,
            "candidateId": command.candidate_id,
            "candidateHash": command.candidate_hash,
            "expectedCanonRevision": command.expected_canon_revision,
            "expectedPlanningHash": command.expected_planning_hash,
            "expectedOutlineHash": command.expected_outline_hash,
            "contextManifestHash": context_manifest_hash,
            "idempotencyKey": command.idempotency_key,
            "requestFingerprint": request_fingerprint,
        })

    async def _lock_inputs(self, session, command: PrepareFinalization):
        project = await self.repository.lock_project(session, command.project_id)
        chapter_session = await self.repository.lock_session(
            session, command.project_id, command.chapter_session_id,
        )
        candidate = await self.repository.lock_candidate(
            session,
            command.project_id,
            command.chapter_session_id,
            command.candidate_id,
        )
        if project is None or chapter_session is None or candidate is None:
            raise FinalizationConflict("FINALIZATION_NOT_FOUND")
        chapter_number = chapter_session.get("chapter_num")
        if type(chapter_number) is not int or chapter_number < 1:
            raise FinalizationConflict("FINALIZATION_CONTEXT_INVALID")
        current = await self.repository.lock_current_authority(
            session, command.project_id, chapter_number,
        )
        snapshot = await self.repository.load_preparation_context(
            session, command.project_id, chapter_number,
        )
        if current is None or not isinstance(snapshot, dict):
            raise FinalizationConflict("FINALIZATION_CONTEXT_INVALID")
        return chapter_session, candidate, current, snapshot, chapter_number

    @staticmethod
    def _manifest(
        *,
        command: PrepareFinalization,
        candidate: dict[str, object],
        snapshot: dict[str, object],
        chapter_number: int,
        binding_key: str,
    ) -> FinalizationProviderManifest:
        identity = FinalizationService._binding_identity(snapshot.get(binding_key))
        if identity is None:
            raise FinalizationConflict("FINALIZATION_PROVIDER_UNAVAILABLE")
        contract_context = snapshot["contract_context"]
        provider_contract_context = dict(contract_context)
        contract_content = contract_context.get("content")
        if type(contract_content) is dict:
            provider_contract_context["content"] = {
                key: value
                for key, value in contract_content.items()
                if key != "corpusSourceRefs"
            }
        return FinalizationProviderManifest.model_validate({
            "chapter_number": chapter_number,
            "candidate_hash": command.candidate_hash,
            "candidate_prose": candidate["content"],
            "canon_context": snapshot["canon_context"],
            "planning_context": snapshot["planning_context"],
            "outline_context": snapshot["outline_context"],
            "contract_context": provider_contract_context,
            "bible_context": snapshot["bible_context"],
            "policy_version": snapshot["policy_version"],
            "binding": FinalizationBinding.model_validate(identity),
        })

    @staticmethod
    def _report(
        *,
        status: QualityReportStatus,
        blocks: tuple[DeterministicBlock, ...],
        findings: tuple[QualityFinding, ...],
    ) -> QualityReportPayload:
        return QualityReportPayload.model_validate({
            "status": status,
            "deterministicBlocks": blocks,
            "findings": findings,
        })

    def _report_row(
        self,
        *,
        report_id: str,
        command: PrepareFinalization,
        context_manifest_hash: str,
        snapshot: dict[str, object],
        report: QualityReportPayload,
    ) -> dict[str, object]:
        binding = self._binding_identity(snapshot.get("audit_binding"))
        payload = report.model_dump(by_alias=True, mode="json")
        return {
            "id": report_id,
            "project_id": command.project_id,
            "chapter_session_id": command.chapter_session_id,
            "draft_candidate_id": command.candidate_id,
            "candidate_hash": command.candidate_hash,
            "expected_canon_revision": command.expected_canon_revision,
            "expected_planning_hash": command.expected_planning_hash,
            "expected_outline_hash": command.expected_outline_hash,
            "policy_version": snapshot["policy_version"],
            "context_manifest_hash": context_manifest_hash,
            "provider_id": None if binding is None else binding["provider_id"],
            "provider_profile_revision": (
                None if binding is None else binding["provider_profile_revision"]
            ),
            "model_name_snapshot": None if binding is None else binding["model_name"],
            "status": report.status.value,
            "deterministic_blocks": _public_values(report.deterministic_blocks),
            "findings": _public_values(report.findings),
            "content_hash": canonical_hash(payload),
            "created_at": self._clock(),
        }

    async def _terminalize(
        self,
        *,
        command: PrepareFinalization,
        attempt_id: str,
        status: str,
        context_manifest_hash: str,
        snapshot: dict[str, object],
        report: QualityReportPayload | None,
    ) -> None:
        async with self.transaction_factory() as session:
            report_id = None
            if report is not None:
                report_id = self._id()
                await self.repository.insert_quality_report(
                    session,
                    self._report_row(
                        report_id=report_id,
                        command=command,
                        context_manifest_hash=context_manifest_hash,
                        snapshot=snapshot,
                        report=report,
                    ),
                )
            changed = await self.repository.mark_terminal(
                session,
                project_id=command.project_id,
                session_id=command.chapter_session_id,
                change_set_id=attempt_id,
                status=status,
                report_id=report_id,
                updated_at=self._clock(),
            )
            if not changed:
                raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")

    @staticmethod
    def _require_review_state(attempt, *, revision: int, revision_hash: str):
        if (
            not isinstance(attempt, dict)
            or attempt.get("status") != "awaiting_author"
            or attempt.get("current_revision") != revision
            or attempt.get("current_revision_hash") != revision_hash
            or attempt.get("confirmed_revision") is not None
            or attempt.get("confirmed_revision_hash") is not None
        ):
            raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")

    async def _lock_review_inputs(self, session, command):
        if await self.repository.lock_project(session, command.project_id) is None:
            raise FinalizationConflict("FINALIZATION_NOT_FOUND")
        attempt = await self.repository.lock_current_attempt(
            session, command.project_id, command.chapter_session_id,
        )
        self._require_review_state(
            attempt,
            revision=command.expected_revision,
            revision_hash=command.expected_revision_hash,
        )
        candidate_id = attempt.get("draft_candidate_id")
        if not isinstance(candidate_id, str):
            raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
        chapter_session = await self.repository.lock_session(
            session, command.project_id, command.chapter_session_id,
        )
        candidate = await self.repository.lock_candidate(
            session, command.project_id, command.chapter_session_id, candidate_id,
        )
        if chapter_session is None or candidate is None:
            raise FinalizationConflict("FINALIZATION_NOT_FOUND")
        chapter_number = chapter_session.get("chapter_num")
        if type(chapter_number) is not int or chapter_number < 1:
            raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
        current = await self.repository.lock_current_authority(
            session, command.project_id, chapter_number,
        )
        snapshot = await self.repository.load_preparation_context(
            session, command.project_id, chapter_number,
        )
        if current is None or not isinstance(snapshot, dict):
            raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
        try:
            frozen_command = PrepareFinalization(
                project_id=command.project_id,
                chapter_session_id=command.chapter_session_id,
                candidate_id=candidate_id,
                candidate_hash=attempt.get("candidate_hash"),
                expected_canon_revision=attempt.get("expected_canon_revision"),
                expected_planning_hash=attempt.get("expected_planning_hash"),
                expected_outline_hash=attempt.get("expected_outline_hash"),
                idempotency_key=attempt.get("idempotency_key"),
            )
            current_manifest_hash = canonical_hash(self._context_manifest(
                frozen_command, chapter_number, snapshot,
            ))
        except (TypeError, ValueError, FinalizationConflict):
            raise FinalizationConflict("FINALIZATION_STATE_CONFLICT") from None
        if current_manifest_hash != attempt.get("context_manifest_hash"):
            raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
        authority = FinalizationAuthority.model_validate({
            "projectId": command.project_id,
            "chapterSessionId": command.chapter_session_id,
            "candidateId": candidate_id,
            "candidateHash": attempt.get("candidate_hash"),
            "expectedCanonRevision": attempt.get("expected_canon_revision"),
            "expectedPlanningHash": attempt.get("expected_planning_hash"),
            "expectedOutlineHash": attempt.get("expected_outline_hash"),
            "contextManifestHash": attempt.get("context_manifest_hash", "0" * 64),
            "idempotencyKey": attempt.get("idempotency_key", "0" * 64),
            "requestFingerprint": attempt.get("request_fingerprint", "0" * 64),
        })
        blocks = run_finalization_prechecks(
            authority,
            session=chapter_session,
            candidate=candidate,
            current_authority=current,
            reference_sources=snapshot["reference_sources"],
            copy_check_completed=True,
        )
        if blocks:
            raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
        return attempt, candidate, snapshot

    async def get_review(self, project_id: str, chapter_session_id: str):
        if not all(
            isinstance(value, str) and value.strip()
            for value in (project_id, chapter_session_id)
        ):
            raise ValueError("finalization identity is invalid")
        async with self.transaction_factory() as session:
            value = await self.repository.read_current_view(
                session, project_id, chapter_session_id,
            )
            if value is None:
                chapter_session = await self.repository.lock_session(
                    session, project_id, chapter_session_id,
                )
                if chapter_session is None:
                    raise FinalizationConflict("FINALIZATION_NOT_FOUND")
                return {"state": "empty"}
        return value

    async def correct(self, command: CorrectFinalization) -> ReviewedFinalization:
        if type(command) is not CorrectFinalization:
            raise TypeError("command must be CorrectFinalization")
        async with self.transaction_factory() as session:
            attempt, candidate, snapshot = await self._lock_review_inputs(
                session, command,
            )
            validate_change_set_context(
                command.change_set,
                candidate_content=candidate["content"],
                canon_context=snapshot["canon_context"],
                planning_context=snapshot["planning_context"],
            )
            next_revision = command.expected_revision + 1
            next_hash = change_set_hash(command.change_set)
            await self.repository.insert_change_set_revision(session, {
                "id": self._id(),
                "project_id": command.project_id,
                "change_set_id": attempt["id"],
                "revision": next_revision,
                "change_set": command.change_set,
                "content_hash": next_hash,
                "source": ChangeSetSource.AUTHOR_CORRECTION.value,
                "created_at": self._clock(),
            })
            advanced = await self.repository.advance_current_revision(
                session,
                project_id=command.project_id,
                session_id=command.chapter_session_id,
                change_set_id=attempt["id"],
                expected_revision=command.expected_revision,
                expected_revision_hash=command.expected_revision_hash,
                next_revision=next_revision,
                next_revision_hash=next_hash,
                updated_at=self._clock(),
            )
            if not advanced:
                raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
        return ReviewedFinalization(
            attempt_id=attempt["id"],
            status="awaiting_author",
            current_revision=next_revision,
            current_revision_hash=next_hash,
        )

    async def confirm(self, command: ConfirmFinalization) -> ReviewedFinalization:
        if type(command) is not ConfirmFinalization:
            raise TypeError("command must be ConfirmFinalization")
        async with self.transaction_factory() as session:
            attempt, _, _ = await self._lock_review_inputs(session, command)
            revision = await self.repository.lock_change_set_revision(
                session,
                command.project_id,
                attempt["id"],
                command.expected_revision,
                command.expected_revision_hash,
            )
            if revision is None:
                raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
            confirmed = await self.repository.confirm_current_revision(
                session,
                project_id=command.project_id,
                session_id=command.chapter_session_id,
                change_set_id=attempt["id"],
                revision=command.expected_revision,
                revision_hash=command.expected_revision_hash,
                confirmed_at=self._clock(),
            )
            if not confirmed:
                raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
        return ReviewedFinalization(
            attempt_id=attempt["id"],
            status="awaiting_author",
            current_revision=command.expected_revision,
            current_revision_hash=command.expected_revision_hash,
            confirmed_revision=command.expected_revision,
            confirmed_revision_hash=command.expected_revision_hash,
        )

    async def cancel(self, command: CancelFinalization) -> ReviewedFinalization:
        if type(command) is not CancelFinalization:
            raise TypeError("command must be CancelFinalization")
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(
                session, command.project_id,
            ) is None:
                raise FinalizationConflict("FINALIZATION_NOT_FOUND")
            attempt = await self.repository.lock_current_attempt(
                session, command.project_id, command.chapter_session_id,
            )
            self._require_review_state(
                attempt,
                revision=command.expected_revision,
                revision_hash=command.expected_revision_hash,
            )
            cancelled = await self.repository.cancel_awaiting_author(
                session,
                project_id=command.project_id,
                session_id=command.chapter_session_id,
                change_set_id=attempt["id"],
                expected_revision=command.expected_revision,
                expected_revision_hash=command.expected_revision_hash,
                updated_at=self._clock(),
            )
            if not cancelled:
                raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
        return ReviewedFinalization(
            attempt_id=attempt["id"],
            status="cancelled",
            current_revision=command.expected_revision,
            current_revision_hash=command.expected_revision_hash,
        )

    async def prepare(self, command: PrepareFinalization) -> PreparedFinalization:
        if type(command) is not PrepareFinalization:
            raise TypeError("command must be PrepareFinalization")

        async with self.transaction_factory() as session:
            chapter_session, candidate, current, snapshot, chapter_number = (
                await self._lock_inputs(session, command)
            )
            context_manifest = self._context_manifest(
                command, chapter_number, snapshot,
            )
            context_manifest_hash = canonical_hash(context_manifest)
            fingerprint = self.request_fingerprint(
                command, snapshot, chapter_number,
            )
            authority = self._authority(
                command, context_manifest_hash, fingerprint,
            )
            blocks = run_finalization_prechecks(
                authority,
                session=chapter_session,
                candidate=candidate,
                current_authority=current,
                reference_sources=snapshot["reference_sources"],
                copy_check_completed=True,
            )
            existing = await self.repository.find_by_idempotency(
                session,
                command.project_id,
                command.chapter_session_id,
                command.idempotency_key,
            )
            if existing is not None:
                if existing.get("request_fingerprint") != fingerprint:
                    raise FinalizationConflict("FINALIZATION_IDEMPOTENCY_CONFLICT")
                return PreparedFinalization(
                    attempt_id=existing["id"],
                    status=existing.get("status", "preparing"),
                    current_revision=existing.get("current_revision"),
                    current_revision_hash=existing.get("current_revision_hash"),
                    replayed=True,
                )
            active = await self.repository.find_active(
                session, command.project_id, command.chapter_session_id,
            )
            if active is not None:
                raise FinalizationConflict("FINALIZATION_ACTIVE_CONFLICT")
            attempt_id = self._id()
            now = self._clock()
            await self.repository.insert_preparing_attempt(session, {
                "id": attempt_id,
                "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "draft_candidate_id": command.candidate_id,
                "idempotency_key": command.idempotency_key,
                "request_fingerprint": fingerprint,
                "candidate_hash": command.candidate_hash,
                "expected_canon_revision": command.expected_canon_revision,
                "expected_planning_hash": command.expected_planning_hash,
                "expected_outline_hash": command.expected_outline_hash,
                "context_manifest": context_manifest,
                "context_manifest_hash": context_manifest_hash,
                "created_at": now,
                "updated_at": now,
            })

        quality_status = QualityReportStatus.COMPLETED
        findings: tuple[QualityFinding, ...] = ()
        audit_binding = snapshot.get("audit_binding")
        if self._binding_identity(audit_binding) is None:
            quality_status = QualityReportStatus.QUALITY_NOT_COMPLETED
        else:
            try:
                audit_manifest = self._manifest(
                    command=command,
                    candidate=candidate,
                    snapshot=snapshot,
                    chapter_number=chapter_number,
                    binding_key="audit_binding",
                )
                findings = await self.quality_provider.audit(
                    provider=audit_binding,
                    model_name=audit_binding["model_name"],
                    manifest=audit_manifest,
                )
            except asyncio.CancelledError:
                await self._terminalize(
                    command=command,
                    attempt_id=attempt_id,
                    status="cancelled",
                    context_manifest_hash=context_manifest_hash,
                    snapshot=snapshot,
                    report=None,
                )
                raise
            except Exception:
                quality_status = QualityReportStatus.QUALITY_NOT_COMPLETED
                findings = ()

        report = self._report(
            status=quality_status,
            blocks=blocks,
            findings=findings,
        )
        if blocks:
            await self._terminalize(
                command=command,
                attempt_id=attempt_id,
                status="failed",
                context_manifest_hash=context_manifest_hash,
                snapshot=snapshot,
                report=report,
            )
            return PreparedFinalization(
                attempt_id=attempt_id,
                status="failed",
                quality_status=quality_status.value,
                hard_blocks=blocks,
            )

        extraction_binding = snapshot.get("extraction_binding")
        try:
            extraction_manifest = self._manifest(
                command=command,
                candidate=candidate,
                snapshot=snapshot,
                chapter_number=chapter_number,
                binding_key="extraction_binding",
            )
            change_set = await self.extraction_provider.extract(
                provider=extraction_binding,
                model_name=extraction_binding["model_name"],
                manifest=extraction_manifest,
            )
            if type(change_set) is not FinalizationChangeSet:
                raise ValueError("invalid extraction")
            validate_change_set_context(
                change_set,
                candidate_content=candidate["content"],
                canon_context=snapshot["canon_context"],
                planning_context=snapshot["planning_context"],
            )
        except asyncio.CancelledError:
            await self._terminalize(
                command=command,
                attempt_id=attempt_id,
                status="cancelled",
                context_manifest_hash=context_manifest_hash,
                snapshot=snapshot,
                report=None,
            )
            raise
        except Exception:
            await self._terminalize(
                command=command,
                attempt_id=attempt_id,
                status="failed",
                context_manifest_hash=context_manifest_hash,
                snapshot=snapshot,
                report=report,
            )
            return PreparedFinalization(
                attempt_id=attempt_id,
                status="failed",
                quality_status=quality_status.value,
            )

        async with self.transaction_factory() as session:
            second_session, second_candidate, second_current, second_snapshot, _ = (
                await self._lock_inputs(session, command)
            )
            second_manifest = self._context_manifest(
                command, chapter_number, second_snapshot,
            )
            second_authority = self._authority(
                command,
                canonical_hash(second_manifest),
                self.request_fingerprint(command, second_snapshot, chapter_number),
            )
            second_blocks = run_finalization_prechecks(
                second_authority,
                session=second_session,
                candidate=second_candidate,
                current_authority=second_current,
                reference_sources=second_snapshot["reference_sources"],
                copy_check_completed=True,
            )
            if (
                canonical_hash(second_manifest) != context_manifest_hash
                or second_blocks
            ):
                changed = await self.repository.mark_terminal(
                    session,
                    project_id=command.project_id,
                    session_id=command.chapter_session_id,
                    change_set_id=attempt_id,
                    status="invalidated",
                    report_id=None,
                    updated_at=self._clock(),
                )
                if not changed:
                    raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
                return PreparedFinalization(
                    attempt_id=attempt_id,
                    status="invalidated",
                    quality_status=quality_status.value,
                    hard_blocks=second_blocks,
                )

            report_id = self._id()
            extraction_id = self._id()
            revision_row_id = self._id()
            revision_hash = change_set_hash(change_set)
            await self.repository.insert_quality_report(
                session,
                self._report_row(
                    report_id=report_id,
                    command=command,
                    context_manifest_hash=context_manifest_hash,
                    snapshot=snapshot,
                    report=report,
                ),
            )
            await self.repository.insert_change_set_revision(session, {
                "id": revision_row_id,
                "project_id": command.project_id,
                "change_set_id": attempt_id,
                "revision": 1,
                "change_set": change_set,
                "content_hash": revision_hash,
                "source": ChangeSetSource.EXTRACTION.value,
                "created_at": self._clock(),
            })
            published = await self.repository.publish_awaiting_author(
                session,
                project_id=command.project_id,
                session_id=command.chapter_session_id,
                change_set_id=attempt_id,
                report_id=report_id,
                extraction_id=extraction_id,
                revision=1,
                revision_hash=revision_hash,
                updated_at=self._clock(),
            )
            if not published:
                raise FinalizationConflict("FINALIZATION_STATE_CONFLICT")
        return PreparedFinalization(
            attempt_id=attempt_id,
            status="awaiting_author",
            quality_status=quality_status.value,
            current_revision=1,
            current_revision_hash=revision_hash,
        )


__all__ = [
    "CancelFinalization",
    "ConfirmFinalization",
    "CorrectFinalization",
    "FinalizationConflict",
    "FinalizationService",
    "PrepareFinalization",
    "PreparedFinalization",
    "ReviewedFinalization",
]
