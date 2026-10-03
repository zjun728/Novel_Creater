"""Local historical references tied to a saved review; no snapshot/hash replay.

This read does not confer CURRENT-head write eligibility. The immutable saved
manifest and candidate basis bind the revision; individual event reads follow
the existing current-state rule without proving the complete extraction input.
"""

from dataclasses import dataclass
from hashlib import sha256
import re

from backend.domain.finalization import FinalizationChangeSet, change_set_hash
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.repositories.finalization import _decoded_object, _decoded_json_value
from backend.services.finalization import FinalizationConflict
from backend.services.finalization_checks import _BASIS_KEYS


def conflict():
    return FinalizationConflict("FINALIZATION_STATE_CONFLICT")


@dataclass(frozen=True)
class ReadFinalizationHistory:
    project_id: str
    chapter_session_id: str
    attempt_id: str
    candidate_id: str
    candidate_hash: str
    canon_revision: int
    expected_revision: int
    expected_revision_hash: str

    def __post_init__(self):
        if any(type(value) is not str or not value.strip() or len(value) > 100
               for value in (self.project_id, self.chapter_session_id, self.attempt_id, self.candidate_id)):
            raise ValueError("invalid history identity")
        if any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
               for value in (self.candidate_hash, self.expected_revision_hash)):
            raise ValueError("invalid history hash")
        if type(self.canon_revision) is not int or self.canon_revision < 0:
            raise ValueError("invalid frozen revision")
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise ValueError("invalid saved revision")

    def identity(self):
        return {"projectId": self.project_id, "chapterSessionId": self.chapter_session_id,
                "attemptId": self.attempt_id, "candidateId": self.candidate_id,
                "candidateHash": self.candidate_hash, "canonRevision": self.canon_revision,
                "expectedRevision": self.expected_revision, "expectedRevisionHash": self.expected_revision_hash}


class FinalizationHistoryReader:
    def __init__(self, repository, continuity_repository, connection_factory):
        self.repository = repository
        self.continuity_repository = continuity_repository
        self.connection_factory = connection_factory

    @staticmethod
    def _saved(row, command):
        if not isinstance(row, dict) or not row.get("baseline_revision_id"):
            raise conflict()
        expected = {"project_id": command.project_id, "chapter_session_id": command.chapter_session_id,
                    "attempt_id": command.attempt_id, "draft_candidate_id": command.candidate_id,
                    "candidate_id": command.candidate_id, "candidate_project_id": command.project_id,
                    "candidate_session_id": command.chapter_session_id, "candidate_hash": command.candidate_hash,
                    "candidate_content_hash": command.candidate_hash,
                    "expected_canon_revision": command.canon_revision, "current_revision": command.expected_revision,
                    "current_revision_hash": command.expected_revision_hash}
        if any(row.get(key) != value or type(row.get(key)) is not type(value) for key, value in expected.items()):
            raise conflict()
        if type(row.get("content")) is not str or sha256(row["content"].encode()).hexdigest() != command.candidate_hash:
            raise conflict()
        manifest = _decoded_object(row.get("context_manifest_json"), "history manifest")
        provenance = _decoded_object(row.get("provenance_json"), "history candidate basis")
        try:
            basis = {key: provenance[key] for key in _BASIS_KEYS}
            changes = FinalizationChangeSet.model_validate(_decoded_object(row.get("payload_json"), "history changes"))
            if (canonical_hash(manifest) != row.get("context_manifest_hash")
                or canonical_hash(basis) != row.get("basis_hash")
                or change_set_hash(changes) != command.expected_revision_hash):
                raise conflict()
            manifest_identity = {"schemaVersion": "finalization-context-v1", "projectId": command.project_id,
                                 "chapterSessionId": command.chapter_session_id, "candidateId": command.candidate_id,
                                 "candidateHash": command.candidate_hash, "expectedCanonRevision": command.canon_revision,
                                 "expectedPlanningHash": row.get("expected_planning_hash"),
                                 "expectedOutlineHash": row.get("expected_outline_hash")}
            if any(manifest.get(key) != value or type(manifest.get(key)) is not type(value)
                   for key, value in manifest_identity.items()):
                raise conflict()
            if (basis["schemaVersion"] != "draft-candidate-basis-v1"
                or type(basis["canonRevision"]) is not int or basis["canonRevision"] != command.canon_revision
                or type(basis["projectionRevision"]) is not int or basis["projectionRevision"] != command.canon_revision
                or basis["planningHash"] != manifest["expectedPlanningHash"]
                or basis["outlineHash"] != manifest["expectedOutlineHash"]):
                raise conflict()
            if any(type(basis[key]) is not int or basis[key] < 1 for key in ("outlineRevision", "planningRevision")):
                raise conflict()
            if any(type(basis[key]) is not str or not basis[key] for key in ("outlineRevisionId", "planningRevisionId")):
                raise conflict()
            hashes = [basis[key] for key in ("outlineHash", "planningHash", "projectionHash")]
            hashes.append(manifest["contexts"]["canonHash"])
            if any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes):
                raise conflict()
        except (KeyError, TypeError, ValueError):
            raise conflict() from None
        return changes

    @staticmethod
    def _reference(rows, command, entity_id, field_path):
        item = {"entityId": entity_id, "fieldPath": field_path}
        if not isinstance(rows, (list, tuple)) or len(rows) > 2:
            return {**item, "state": "unavailable"}
        if not rows:
            return {**item, "state": "absent"}
        for row in rows:
            if (not isinstance(row, dict) or row.get("project_id") != command.project_id
                or row.get("entity_id") != entity_id or row.get("field_path") != field_path
                or row.get("fact_kind") not in {"dynamic_event", "stable_definition"}
                or row.get("confirmation_status") != "confirmed"
                or type(row.get("revision_number")) is not int or not 0 <= row["revision_number"] <= command.canon_revision
                or type(row.get("event_order")) is not int or row["event_order"] < 1
                or type(row.get("id")) is not str or not row["id"] or "payload_json" not in row):
                return {**item, "state": "unavailable"}
        source = rows[0]
        if len(rows) == 2 and (source["revision_number"], source["event_order"]) <= (rows[1]["revision_number"], rows[1]["event_order"]):
            return {**item, "state": "unavailable"}
        try:
            value = _decoded_json_value(source["payload_json"], "history source value")
            canonical_json(value)  # Validate JSON without coalescing null/empty/false/zero.
        except (TypeError, ValueError, RuntimeError):
            return {**item, "state": "unavailable"}
        return {**item, "state": "present", "value": value,
                "source": {"eventId": source["id"], "revision": source["revision_number"], "eventOrder": source["event_order"]}}

    async def read(self, command):
        if type(command) is not ReadFinalizationHistory:
            raise TypeError("history command required")
        async with self.connection_factory() as session:
            row = await self.repository.read_history_context(session, command.project_id, command.chapter_session_id)
            changes = self._saved(row, command)
            # Closed saved ChangeSet contract bounds this list at 2048 events.
            keys = dict.fromkeys((event.entity_id, event.field_path) for event in changes.canon_events)
            new_entities = {entity.id for entity in changes.entities}
            entities = {}
            items = []
            for entity_id, field_path in keys:
                item = {"entityId": entity_id, "fieldPath": field_path}
                if entity_id is None or entity_id in new_entities:
                    items.append({**item, "state": "not_applicable", "reason": "global" if entity_id is None else "new_entity"})
                    continue
                if entity_id not in entities:
                    entity = await self.continuity_repository.entity(session, command.project_id, entity_id, command.canon_revision)
                    entities[entity_id] = isinstance(entity, dict) and entity.get("id") == entity_id
                if not entities[entity_id]:
                    items.append({**item, "state": "unavailable"})
                    continue
                rows = await self.continuity_repository.state_history_reference(
                    session, command.project_id, entity_id, field_path, command.canon_revision,
                )
                items.append(self._reference(rows, command, entity_id, field_path))
            # Also works under READ COMMITTED: a saved identity change invalidates
            # this response. Canon event history is append-only; never consult head.
            final = await self.repository.read_history_context(session, command.project_id, command.chapter_session_id)
            self._saved(final, command)
            if any(final.get(key) != row.get(key) for key in ("context_manifest_hash", "basis_hash")):
                raise conflict()
            return {**command.identity(), "items": items}
