"""Atomic one-way handoff from a global topic candidate to a new project."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import time
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.json_contracts import canonical_hash
from backend.domain.seeds import (
    SeedPayload,
    SeedSnapshotProvenance,
    SeedTopicCandidateProvenance,
    build_seed_provenance,
)
from backend.domain.topics import (
    TopicCandidatePayload,
    TopicEvidenceRef,
    TopicFailure,
)
from backend.services.project_lifecycle import CreateProject


def _now_ms() -> int:
    return int(time.time() * 1000)


class HandoffTopicCandidate(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    candidate_id: str = Field(alias="candidateId", min_length=1, max_length=36)
    candidate_version: int = Field(alias="candidateVersion", gt=0)
    candidate_hash: str = Field(
        alias="candidateHash",
        pattern=r"^[0-9a-f]{64}$",
    )
    project_title: str = Field(alias="projectTitle", min_length=1, max_length=200)
    idempotency_key: str = Field(
        alias="idempotencyKey",
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )


class TopicProjectHandoffService:
    def __init__(
        self,
        topic_repository,
        *,
        project_service,
        seed_service,
        transaction_factory,
        clock: Callable[[], int] = _now_ms,
    ) -> None:
        self._topics = topic_repository
        self._projects = project_service
        self._seeds = seed_service
        self._transaction = transaction_factory
        self._clock = clock

    @staticmethod
    def _id(key: str, kind: str) -> str:
        return str(uuid5(
            NAMESPACE_URL,
            f"novel-creator/topic-handoff/{key}/{kind}",
        ))

    @staticmethod
    def _result(row: Mapping) -> dict[str, object]:
        return {
            "handoffId": row["id"],
            "candidateId": row["candidate_id"],
            "candidateVersion": int(row["candidate_version"]),
            "candidateHash": row["candidate_hash"],
            "projectId": row["project_id"],
            "seedId": row["seed_id"],
            "seedRevisionId": row["seed_revision_id"],
            "seedRevision": int(row["seed_revision"]),
            "seedHash": row["seed_hash"],
            "createdAt": int(row["created_at"]),
        }

    @staticmethod
    def _request_hash(command: HandoffTopicCandidate) -> str:
        return canonical_hash(command.model_dump(mode="json", by_alias=True))

    @staticmethod
    def _evidence_refs(version: Mapping) -> tuple[TopicEvidenceRef, ...]:
        basis = version.get("basis")
        values = basis.get("evidence") if isinstance(basis, Mapping) else ()
        if not isinstance(values, list):
            raise TopicFailure("TOPIC_NOT_FOUND")
        try:
            refs = tuple(
                TopicEvidenceRef(
                    snapshotId=item["snapshotId"],
                    contentHash=item["contentHash"],
                )
                for item in values
                if isinstance(item, Mapping)
            )
            if len(refs) != len(values):
                raise ValueError("invalid evidence facts")
            return refs
        except (KeyError, TypeError, ValueError):
            raise TopicFailure("TOPIC_NOT_FOUND") from None

    @staticmethod
    def _seed_payload(candidate: TopicCandidatePayload) -> SeedPayload:
        return SeedPayload(
            title=candidate.title,
            genre=candidate.genre,
            logline=candidate.logline,
            protagonist=candidate.protagonist,
            desire=candidate.desire,
            coreConflict=candidate.core_conflict,
            worldPressure=candidate.world_pressure,
            openingHook=candidate.opening_hook,
            differentiation=candidate.differentiation,
            targetAudience=candidate.target_audience,
            storyPromise=candidate.story_promise,
            longFormPotential=candidate.long_form_potential,
            marketBasis=candidate.market_basis,
        )

    async def create_project(self, command: HandoffTopicCandidate):
        request_hash = self._request_hash(command)
        async with self._transaction() as session:
            existing = await self._topics.lock_handoff_by_key(
                session,
                command.idempotency_key,
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise TopicFailure("TOPIC_REQUEST_CONFLICT")
                return self._result(existing)

            candidate = await self._topics.lock_candidate(
                session,
                command.candidate_id,
            )
            if candidate is None:
                raise TopicFailure("TOPIC_NOT_FOUND")
            if candidate["status"] == "archived":
                raise TopicFailure("TOPIC_CANDIDATE_ARCHIVED")
            version = await self._topics.lock_candidate_version(
                session,
                candidate_id=command.candidate_id,
                version=command.candidate_version,
                content_hash=command.candidate_hash,
            )
            if version is None:
                raise TopicFailure("TOPIC_NOT_FOUND")
            try:
                candidate_payload = TopicCandidatePayload.model_validate(
                    version["payload"],
                    strict=True,
                )
            except (KeyError, TypeError, ValueError):
                raise TopicFailure("TOPIC_NOT_FOUND") from None

            evidence_refs = self._evidence_refs(version)
            snapshots = await self._topics.lock_snapshot_evidence(
                session,
                evidence_refs,
            )
            basis_evidence = version["basis"]["evidence"]
            expected_evidence = tuple(
                (
                    item["snapshotId"],
                    item["contentHash"],
                    item["sourceId"],
                )
                for item in basis_evidence
            )
            actual_evidence = tuple(
                (item["id"], item["content_hash"], item["source_id"])
                for item in snapshots
            )
            if actual_evidence != expected_evidence:
                raise TopicFailure("TOPIC_NOT_FOUND")
            try:
                snapshot_provenance = tuple(
                    SeedSnapshotProvenance(
                        id=item["id"],
                        hash=item["content_hash"],
                        sourceId=item["source_id"],
                        sourceURL=item["source_url"],
                        capturedAt=int(item["captured_at"]),
                    )
                    for item in snapshots
                )
            except (KeyError, TypeError, ValueError):
                raise TopicFailure("TOPIC_NOT_FOUND") from None

            project_id = self._id(command.idempotency_key, "project")
            seed_id = self._id(command.idempotency_key, "seed")
            revision_id = self._id(command.idempotency_key, "seed-revision")
            handoff_id = self._id(command.idempotency_key, "receipt")
            now = self._clock()
            project = CreateProject(
                id=project_id,
                title=command.project_title,
                genre=candidate_payload.genre,
                description=candidate_payload.logline,
            )
            await self._projects.create_in_session(session, project)

            provenance = build_seed_provenance(
                kind="topic_candidate",
                snapshots=snapshot_provenance,
                analysis=None,
                inspiration_attempt=None,
                public_notes=(),
                topic_candidate=SeedTopicCandidateProvenance(
                    id=command.candidate_id,
                    version=command.candidate_version,
                    hash=command.candidate_hash,
                ),
            )
            seed = await self._seeds.create_in_session(
                session,
                project_id=project_id,
                seed_id=seed_id,
                revision_id=revision_id,
                payload=self._seed_payload(candidate_payload),
                provenance=provenance,
                now=now,
            )
            receipt = {
                "id": handoff_id,
                "candidate_id": command.candidate_id,
                "candidate_version": command.candidate_version,
                "candidate_hash": command.candidate_hash,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "project_id": project_id,
                "seed_id": seed.id,
                "seed_revision_id": seed.revision_id,
                "seed_revision": seed.revision,
                "seed_hash": seed.content_hash,
                "created_at": now,
            }
            await self._topics.insert_handoff(session, receipt)
            return self._result(receipt)


__all__ = ("HandoffTopicCandidate", "TopicProjectHandoffService")
