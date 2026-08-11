"""Read-only, deterministic preflight for Phase 6 project packages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from uuid import UUID, uuid5
import zipfile

from backend.domain.project_imports import ProjectImportInvalid, ProjectImportSensitiveData, ProjectImportTooLarge
from backend.domain.project_packages import (
    HASH_ALGORITHM, MANIFEST_HASH_PATH, MANIFEST_PATH, MAX_ARCHIVE_BYTES, MAX_CORPUS_BLOB_BYTES,
    MAX_ENTRY_COUNT, MAX_STRUCTURED_ENTRY_BYTES, PACKAGE_FORMAT, PACKAGE_VERSION, PAYLOAD_PATHS,
    RECORD_FIELD_ALLOWLISTS, ManifestEntry, PackageRecord,
    ProjectPackageManifest, ProjectPackageSensitiveData, canonical_line, freeze_json_value, record_sort_key, thaw_json_value, validate_json_depth,
)
from backend.security.project_import_archives import VerifiedArchiveEntry, verify_raw_zip_envelope
from backend.security.project_package_paths import CORPUS_BLOB_RE
from backend.domain.project_import_publication import (
    PUBLICATION_TABLE_ORDER as _PUBLICATION_TABLE_ORDER,
    STATIC_TABLE_COLUMNS as _IMPORT_TABLE_COLUMNS,
    _RECORD_ENCODERS, _SPECIAL_RECORD_HANDLERS, encode_provenance_batch, encode_publication_batches,
)


# Every v1 emitted authority is classified exactly once; invalid is intentionally empty in v1.
FORMAL_ENTITY_TYPES = frozenset({
    "project", "creative-seed", "creative-seed-revision", "creative-seed-head",
    "project-seed-selection-revision", "project-selected-seed",
    "story-engine-option", "project-contract-draft", "creation-contract", "style-contract",
    "project-contract-head", "contract-confirmation", "creation-contract-engine-ref", "reference-use",
    "style-contract-template-ref", "creation-contract-experience-ref", "creation-contract-corpus-ref",
    "creation-contract-corpus-fragment-ref", "project-bible-draft", "creation-bible-revision",
    "project-bible-head", "bible-confirmation", "planning-draft", "planning-revision",
    "project-planning-head", "planning-confirmation", "chapter-outline-draft", "chapter-outline-revision",
    "project-chapter-outline-head", "chapter-outline-confirmation", "chapter", "working-draft", "draft-candidate", "candidate-freeze", "candidate-quality",
    "finalization-change-set", "finalization-change-set-revision", "finalization-record", "final-chapter",
    "canon-entity", "entity-alias", "canon-revision", "canon-event",
})
RECONSTRUCTED_ENTITY_TYPES = frozenset({"project-model-binding-revision", "project-model-binding-item", "project-model-binding-head", "asset", "corpus-revision"})
PROVENANCE_ENTITY_TYPES = frozenset({
    "market-analysis", "seed-inspiration-history", "asset-recommendation-history", "style-trial-history",
    "story-engine-batch", "bible-generation-history", "planning-generation-history",
    "chapter-outline-generation-history", "operation", "operation-event", "working-draft-revision",
    "provider-history", "import-provenance",
})
INVALID_ENTITY_TYPES = frozenset()


def all_v1_record_types() -> frozenset[str]:
    return frozenset().union(FORMAL_ENTITY_TYPES, RECONSTRUCTED_ENTITY_TYPES, PROVENANCE_ENTITY_TYPES, INVALID_ENTITY_TYPES)


@dataclass(frozen=True, slots=True)
class RecordValidator:
    entity_type: str
    required_fields: frozenset[str]
    reference_fields: frozenset[str]
    allowed_states: frozenset[str]


@dataclass(frozen=True, slots=True)
class ProjectImportSummary:
    package_hash: str
    manifest_hash: str
    package_version: int
    source_title: str
    proposed_title: str
    counts: Mapping[str, int]
    has_finalized_chapters: bool
    provider_history_count: int


@dataclass(frozen=True, slots=True)
class VerifiedProjectPackage:
    archive_path: Path
    package_hash: str
    manifest_hash: str
    manifest: ProjectPackageManifest
    graph_index: Mapping[tuple[str, str], PackageRecord]
    entry_index: Mapping[str, VerifiedArchiveEntry]
    summary: ProjectImportSummary


@dataclass(frozen=True, slots=True)
class ImportIdentityMap:
    ids: Mapping[tuple[str, str], str]
    target_project_id: str
    id_map_hash: str


@dataclass(frozen=True, slots=True)
class ImportInsertBatch:
    table: str
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]

    def __post_init__(self) -> None:
        allowed = _IMPORT_TABLE_COLUMNS.get(self.table)
        primitive = lambda value: (
            value is None or type(value) in {str, bool, int} or type(value) is float and math.isfinite(value)
        )
        if (
            allowed is None or type(self.columns) is not tuple or self.columns != allowed
            or type(self.rows) is not tuple
            or any(type(row) is not tuple or len(row) != len(allowed) or not all(primitive(value) for value in row) for row in self.rows)
        ):
            raise _invalid()


@dataclass(frozen=True, slots=True)
class ProjectPublicationPlan:
    command_id: str
    target_project_id: str
    id_map_hash: str
    batches: tuple[ImportInsertBatch, ...]
    provenance: tuple[str, ...]
    blobs: tuple[tuple[str, int], ...]
    expected_projection: Mapping[str, object]
    package_hash: str = ""
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        try:
            UUID(self.command_id)
            UUID(self.target_project_id)
        except (TypeError, ValueError, AttributeError):
            raise _invalid() from None
        if (
            re.fullmatch(r"[0-9a-f]{64}", self.id_map_hash) is None
            or type(self.batches) is not tuple or any(type(value) is not ImportInsertBatch for value in self.batches)
            or type(self.provenance) is not tuple or any(type(value) is not str for value in self.provenance)
            or type(self.blobs) is not tuple
            or any(type(value) is not tuple or len(value) != 2 or type(value[0]) is not str or re.fullmatch(r"[0-9a-f]{64}", value[0]) is None or type(value[1]) is not int or value[1] < 0 for value in self.blobs)
            or not isinstance(self.expected_projection, Mapping)
            or (self.package_hash != "" and re.fullmatch(r"[0-9a-f]{64}", self.package_hash) is None)
            or (self.manifest_hash != "" and re.fullmatch(r"[0-9a-f]{64}", self.manifest_hash) is None)
        ):
            raise _invalid()
        object.__setattr__(self, "expected_projection", _freeze_publication_json(self.expected_projection))


def _freeze_publication_json(value: object) -> object:
    """Freeze target-side JSON, whose typed identifiers are UUIDs rather than package logical IDs."""
    from backend.domain.canon import FrozenJsonObject, freeze_json, thaw_json

    return freeze_json(thaw_json(value) if isinstance(value, FrozenJsonObject) else value, field_name="publication")


_EMBEDDED_IDENTITY_TYPES = frozenset({
    "planning-volume", "planning-plot", "plot", "story-block", "planning-stage", "scene-task",
    "corpus-chapter", "corpus-fragment", "bible-world-rule", "bible-core-cast", "bible-faction",
    "bible-long-term-conflict", "bible-relationship-dynamic", "bible-continuity-guardrail",
    "bible-open-design-question", "quality-finding", "finalization-entity", "finalization-alias",
    "finalization-event", "finalization-progress-event", "finalization-planning-patch",
    "finalization-planning-suggestion", "finalization-patch", "finalization-suggestion",
})


_LOGICAL_ID_RE = re.compile(r"^[a-z]+(?:-[a-z]+)*:[1-9][0-9]*$")


def _typed_id(
    value: object,
    target_types: tuple[str, ...],
    ids: Mapping[tuple[str, str], str],
) -> str:
    if not isinstance(value, str) or _LOGICAL_ID_RE.fullmatch(value) is None:
        raise _invalid()
    matches = [ids[(kind, value)] for kind in target_types if (kind, value) in ids]
    if len(matches) != 1:
        raise _invalid()
    return matches[0]


def _slot(
    value: dict[str, object], key: str, target_types: tuple[str, ...],
    ids: Mapping[tuple[str, str], str], *, optional: bool = False,
) -> None:
    if key not in value or value[key] is None:
        if optional:
            return
        raise _invalid()
    value[key] = _typed_id(value[key], target_types, ids)


def _definition(item: object, kind: str, ids: Mapping[tuple[str, str], str]) -> dict[str, object]:
    if not isinstance(item, dict):
        raise _invalid()
    key = next((candidate for candidate in ("logicalId", "id", "clientNodeKey") if candidate in item), None)
    if key is None:
        raise _invalid()
    item[key] = _typed_id(item[key], (kind,), ids)
    return item


def _rewrite_creation_contract(payload: dict[str, object], ids: Mapping[tuple[str, str], str]) -> None:
    _slot(payload, "seedRevisionId", ("creative-seed-revision",), ids)
    _slot(payload, "engineOptionId", ("story-engine-option",), ids)
    for field, optional in (("primaryStyleRef", False), ("secondaryStyleRef", True)):
        ref = payload.get(field)
        if ref is None and optional:
            continue
        if not isinstance(ref, dict):
            raise _invalid()
        _slot(ref, "id", ("asset",), ids)
    for ref in payload.get("experienceCardRefs", []):
        if not isinstance(ref, dict):
            raise _invalid()
        _slot(ref, "id", ("asset",), ids)
    for source in payload.get("corpusSourceRefs", []):
        if not isinstance(source, dict):
            raise _invalid()
        _slot(source, "id", ("corpus-revision",), ids)
        _slot(source, "revisionId", ("corpus-revision",), ids)
        for fragment in source.get("fragments", []):
            if not isinstance(fragment, dict):
                raise _invalid()
            _slot(fragment, "chapterId", ("corpus-chapter",), ids)
            _slot(fragment, "fragmentId", ("corpus-fragment",), ids)
    binding = payload.get("modelBindingRef")
    if binding is not None:
        if not isinstance(binding, dict):
            raise _invalid()
        _slot(binding, "id", ("project-model-binding-revision",), ids)


def _rewrite_contract_draft(payload: dict[str, object], ids: Mapping[tuple[str, str], str]) -> None:
    """Rewrite the frozen authority slots of the persisted ContractDraftPayload."""
    _slot(payload, "seedRevisionId", ("creative-seed-revision",), ids)
    _slot(payload, "engineOptionId", ("story-engine-option",), ids)
    for field in ("primaryStyleRef", "secondaryStyleRef"):
        ref = payload.get(field)
        if ref is not None:
            if not isinstance(ref, dict):
                raise _invalid()
            _slot(ref, "id", ("asset",), ids)
    for ref in payload.get("experienceCardRefs") or []:
        if not isinstance(ref, dict):
            raise _invalid()
        _slot(ref, "id", ("asset",), ids)
    for source in payload.get("corpusSourceRefs") or []:
        if not isinstance(source, dict):
            raise _invalid()
        _slot(source, "id", ("corpus-revision",), ids)
        _slot(source, "revisionId", ("corpus-revision",), ids)
        for fragment in source.get("fragments", []):
            if not isinstance(fragment, dict):
                raise _invalid()
            _slot(fragment, "chapterId", ("corpus-chapter",), ids)
            _slot(fragment, "fragmentId", ("corpus-fragment",), ids)
    binding = payload.get("modelBindingRef")
    if binding is not None:
        if not isinstance(binding, dict):
            raise _invalid()
        _slot(binding, "id", ("project-model-binding-revision",), ids)


def _rewrite_planning_draft(payload: dict[str, object], ids: Mapping[tuple[str, str], str]) -> None:
    """Rewrite formal persisted-node IDs while preserving draft client keys."""
    def node(item: object, kind: str) -> dict[str, object]:
        if not isinstance(item, dict):
            raise _invalid()
        if item.get("id") is not None:
            _slot(item, "id", (kind,), ids)
        return item

    for item in payload.get("volumes", []):
        node(item, "planning-volume")
    for item in payload.get("plots", []):
        node(item, "planning-plot")
    for block_value in payload.get("storyBlocks", []):
        block = node(block_value, "story-block")
        for stage_value in block.get("stages", []):
            stage = node(stage_value, "planning-stage")
            for task_value in stage.get("sceneTasks", []):
                node(task_value, "scene-task")


def _rewrite_planning(payload: dict[str, object], ids: Mapping[tuple[str, str], str]) -> None:
    for item in payload.get("volumes", []):
        _definition(item, "planning-volume", ids)
    for item in payload.get("plots", []):
        _definition(item, "planning-plot", ids)
    for block_value in payload.get("storyBlocks", []):
        block = _definition(block_value, "story-block", ids)
        for field in ("volumeId", "volumeRef"):
            if field in block:
                _slot(block, field, ("planning-volume",), ids)
        for field in ("plotIds", "plotRefs"):
            if field in block:
                values = block[field]
                if not isinstance(values, list):
                    raise _invalid()
                block[field] = [_typed_id(value, ("planning-plot",), ids) for value in values]
        for stage_value in block.get("stages", []):
            stage = _definition(stage_value, "planning-stage", ids)
            if "storyBlockId" in stage:
                _slot(stage, "storyBlockId", ("story-block",), ids)
            for task_value in stage.get("sceneTasks", []):
                task = _definition(task_value, "scene-task", ids)
                if "stageId" in task:
                    _slot(task, "stageId", ("planning-stage",), ids)
    for field in ("activeStoryBlockId", "activeStoryBlockRef"):
        if payload.get(field) is not None:
            _slot(payload, field, ("story-block",), ids)


def _rewrite_bible(payload: dict[str, object], ids: Mapping[tuple[str, str], str]) -> None:
    fields = {
        "worldRules": "bible-world-rule", "coreCast": "bible-core-cast", "factions": "bible-faction",
        "longTermConflicts": "bible-long-term-conflict", "relationshipDynamics": "bible-relationship-dynamic",
        "continuityGuardrails": "bible-continuity-guardrail", "openDesignQuestions": "bible-open-design-question",
    }
    for field, kind in fields.items():
        for item in payload.get(field, []):
            _definition(item, kind, ids)


def _rewrite_outline(payload: dict[str, object], ids: Mapping[tuple[str, str], str]) -> None:
    if "planningRevisionId" in payload:
        _slot(payload, "planningRevisionId", ("planning-revision",), ids)
    for field, kind in (("volumeRef", "planning-volume"), ("storyBlockRef", "story-block")):
        ref = payload.get(field)
        if ref is not None:
            if not isinstance(ref, dict):
                raise _invalid()
            _slot(ref, "id", (kind,), ids)
    for field, kind in (("stageRefs", "planning-stage"), ("sceneTaskRefs", "scene-task")):
        for ref in payload.get(field, []):
            if not isinstance(ref, dict):
                raise _invalid()
            _slot(ref, "id", (kind,), ids)


def _rewrite_corpus(data: dict[str, object], ids: Mapping[tuple[str, str], str]) -> None:
    for item in data.get("chapters", []):
        if not isinstance(item, dict):
            raise _invalid()
        _slot(item, "logicalId", ("corpus-chapter",), ids)
    for item in data.get("fragments", []):
        if not isinstance(item, dict):
            raise _invalid()
        _slot(item, "logicalId", ("corpus-fragment",), ids)


def _rewrite_finalization(payload: dict[str, object], ids: Mapping[tuple[str, str], str]) -> None:
    fields = {
        "entities": "finalization-entity", "aliases": "finalization-alias", "canonEvents": "finalization-event",
        "storyProgressEvents": "finalization-progress-event", "planningPatches": "finalization-planning-patch",
        "planningSuggestions": "finalization-planning-suggestion",
    }
    for field, kind in fields.items():
        for item in payload.get(field, []):
            _definition(item, kind, ids)
    entity_types = ("canon-entity", "finalization-entity")
    if "existingEntityIds" in payload:
        values = payload["existingEntityIds"]
        if not isinstance(values, list):
            raise _invalid()
        payload["existingEntityIds"] = [_typed_id(value, entity_types, ids) for value in values]
    for field in ("aliases", "canonEvents"):
        for item in payload.get(field, []):
            if isinstance(item, dict) and item.get("entityId") is not None:
                _slot(item, "entityId", entity_types, ids)
    planning_types = {
        "volume": ("planning-volume",), "plot": ("planning-plot",), "story_block": ("story-block",),
        "stage": ("planning-stage",), "scene_task": ("scene-task",),
    }
    for field in ("storyProgressEvents", "planningPatches"):
        for item in payload.get(field, []):
            if not isinstance(item, dict) or item.get("targetType") not in planning_types:
                raise _invalid()
            _slot(item, "targetId", planning_types[item["targetType"]], ids)
    for item in payload.get("planningSuggestions", []):
        if isinstance(item, dict) and item.get("targetId") is not None:
            _slot(item, "targetId", tuple(kind for values in planning_types.values() for kind in values), ids)


def _rewrite_record_data(
    record: PackageRecord,
    ids: Mapping[tuple[str, str], str],
) -> dict[str, object]:
    """Rewrite only declared identity slots; prose and byte-backed content are opaque."""
    try:
        data = thaw_json_value(record.data)
        if not isinstance(data, dict):
            raise ValueError
        for field, targets in _REFS.get(record.entity_type, {}).items():
            optional = field in _OPTIONAL_REF_FIELDS.get(record.entity_type, frozenset())
            _slot(data, field, tuple(sorted(targets)), ids, optional=optional)
        payload = data.get("payload")
        if record.entity_type == "project-contract-draft" and isinstance(payload, dict):
            _rewrite_contract_draft(payload, ids)
        elif record.entity_type == "creation-contract" and isinstance(payload, dict):
            _rewrite_creation_contract(payload, ids)
        elif record.entity_type == "planning-draft" and isinstance(payload, dict):
            if payload.get("schemaVersion") == "planning-v1":
                _rewrite_planning(payload, ids)
            else:
                _rewrite_planning_draft(payload, ids)
        elif record.entity_type == "planning-revision" and isinstance(payload, dict):
            _rewrite_planning(payload, ids)
        elif record.entity_type in {"project-bible-draft", "creation-bible-revision"} and isinstance(payload, dict):
            _rewrite_bible(payload, ids)
        elif record.entity_type in {"chapter-outline-draft", "chapter-outline-revision"} and isinstance(payload, dict):
            _rewrite_outline(payload, ids)
        elif record.entity_type == "finalization-change-set-revision" and isinstance(payload, dict):
            _rewrite_finalization(payload, ids)
        elif record.entity_type == "candidate-quality":
            for finding in data.get("findings", []):
                _definition(finding, "quality-finding", ids)
        elif record.entity_type == "corpus-revision":
            _rewrite_corpus(data, ids)
        elif record.entity_type == "finalization-record" and isinstance(data.get("resultPayload"), dict):
            receipt = data["resultPayload"]
            if set(receipt) != {
                "finalChapterId", "canonRevision", "projectionHash", "planningRevisionId",
                "planningRevision", "planningHash",
            }:
                raise _invalid()
            _slot(receipt, "finalChapterId", ("final-chapter",), ids)
            _slot(receipt, "planningRevisionId", ("planning-revision",), ids)
            for field in ("canonRevision", "planningRevision"):
                if type(receipt[field]) is not int or receipt[field] < 0:
                    raise _invalid()
            for field in ("projectionHash", "planningHash"):
                if not isinstance(receipt[field], str) or re.fullmatch(r"[0-9a-f]{64}", receipt[field]) is None:
                    raise _invalid()
        return data
    except ProjectImportInvalid:
        raise
    except Exception:
        raise _invalid() from None


def _rehash_planning_nodes(payload: dict[str, object]) -> None:
    from backend.domain.json_contracts import canonical_hash

    def rehash(node: object, nested: str | None = None) -> None:
        if not isinstance(node, dict):
            raise ValueError
        if nested is not None:
            children = node.get(nested, [])
            if not isinstance(children, list):
                raise ValueError
            for child in children:
                rehash(child, "sceneTasks" if nested == "stages" else None)
        public = {key: value for key, value in node.items() if key not in {"revision", "contentHash", "stages", "sceneTasks"}}
        node["contentHash"] = canonical_hash(public)

    for key in ("volumes", "plots"):
        values = payload.get(key, [])
        if not isinstance(values, list):
            raise ValueError
        for node in values:
            rehash(node)
    blocks = payload.get("storyBlocks", [])
    if not isinstance(blocks, list):
        raise ValueError
    for block in blocks:
        rehash(block, "stages")


def _rewrite_outline_node_hashes(
    record: PackageRecord,
    data: dict[str, object],
    rewritten: Mapping[tuple[str, str], dict[str, object]],
) -> None:
    source = record.data.get("planningRevisionLogicalId")
    planning = rewritten.get(("planning-revision", source)) if isinstance(source, str) else None
    payload = data.get("payload")
    planning_payload = planning.get("payload") if planning is not None else None
    if not isinstance(payload, dict) or not isinstance(planning_payload, dict):
        return
    hashes: dict[str, str] = {}
    for node in (
        *planning_payload.get("volumes", []), *planning_payload.get("plots", []),
        *planning_payload.get("storyBlocks", []),
    ):
        if not isinstance(node, dict):
            raise ValueError
        if isinstance(node.get("id"), str) and isinstance(node.get("contentHash"), str):
            hashes[node["id"]] = node["contentHash"]
        for stage in node.get("stages", []):
            if not isinstance(stage, dict):
                raise ValueError
            if isinstance(stage.get("id"), str) and isinstance(stage.get("contentHash"), str):
                hashes[stage["id"]] = stage["contentHash"]
            for task in stage.get("sceneTasks", []):
                if isinstance(task, dict) and isinstance(task.get("id"), str) and isinstance(task.get("contentHash"), str):
                    hashes[task["id"]] = task["contentHash"]
    for field in ("volumeRef", "storyBlockRef"):
        ref = payload.get(field)
        if isinstance(ref, dict) and ref.get("id") in hashes:
            ref["contentHash"] = hashes[ref["id"]]
    for field in ("stageRefs", "sceneTaskRefs"):
        for ref in payload.get(field, []):
            if isinstance(ref, dict) and ref.get("id") in hashes:
                ref["contentHash"] = hashes[ref["id"]]


def _planning_node_hash(
    rewritten: Mapping[tuple[str, str], Mapping[str, object]], target_id: object,
) -> str:
    for (kind, _), data in rewritten.items():
        if kind != "planning-revision":
            continue
        payload = data.get("payload")
        if not isinstance(payload, Mapping):
            continue
        nodes: list[object] = [*payload.get("volumes", ()), *payload.get("plots", ()), *payload.get("storyBlocks", ())]
        for block in payload.get("storyBlocks", ()):
            if isinstance(block, Mapping):
                nodes.extend(block.get("stages", ()))
                for stage in block.get("stages", ()):
                    if isinstance(stage, Mapping):
                        nodes.extend(stage.get("sceneTasks", ()))
        for node in nodes:
            if isinstance(node, Mapping) and node.get("id") == target_id and isinstance(node.get("contentHash"), str):
                return node["contentHash"]  # type: ignore[return-value]
    raise _invalid()


def _repair_chapter_story_block_pin(
    record: PackageRecord,
    data: dict[str, object],
    package: VerifiedProjectPackage,
    rewritten: Mapping[tuple[str, str], dict[str, object]],
    ids: Mapping[tuple[str, str], str],
) -> None:
    planning_logical_id = record.data.get("planningRevisionLogicalId")
    story_block_logical_id = record.data.get("storyBlockLogicalId")
    if not isinstance(planning_logical_id, str) or not isinstance(story_block_logical_id, str):
        raise _invalid()
    source_planning = package.graph_index.get(("planning-revision", planning_logical_id))
    target_planning = rewritten.get(("planning-revision", planning_logical_id))
    source_payload = source_planning.data.get("payload") if source_planning is not None else None
    target_payload = target_planning.get("payload") if target_planning is not None else None
    if not isinstance(source_payload, Mapping) or not isinstance(target_payload, Mapping):
        raise _invalid()

    source_blocks = source_payload.get("storyBlocks")
    target_blocks = target_payload.get("storyBlocks")
    if not isinstance(source_blocks, (list, tuple)) or not isinstance(target_blocks, (list, tuple)):
        raise _invalid()
    source_matches = [block for block in source_blocks if isinstance(block, Mapping) and block.get("id") == story_block_logical_id]
    target_id = ids.get(("story-block", story_block_logical_id))
    target_matches = [block for block in target_blocks if isinstance(block, Mapping) and block.get("id") == target_id]
    if len(source_matches) != 1 or len(target_matches) != 1:
        raise _invalid()
    source_block, target_block = source_matches[0], target_matches[0]
    if (
        record.data.get("storyBlockRevision") != source_block.get("revision")
        or record.data.get("storyBlockHash") != source_block.get("contentHash")
        or type(target_block.get("revision")) is not int
        or not isinstance(target_block.get("contentHash"), str)
    ):
        raise _invalid()
    data["storyBlockRevision"] = target_block["revision"]
    data["storyBlockHash"] = target_block["contentHash"]


def _authority_hash(entity_type: str, data: dict[str, object]) -> str | None:
    """Validate strict JSON authorities and hash their public canonical payload."""
    from backend.domain.json_contracts import canonical_hash
    if entity_type == "candidate-quality":
        from backend.domain.finalization import QualityReportPayload
        report = QualityReportPayload.model_validate({
            key: data[key] for key in ("status", "deterministicBlocks", "findings")
        }, strict=False)
        return canonical_hash(report.model_dump(mode="json", by_alias=True))
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return None
    if entity_type == "creative-seed-revision":
        from backend.domain.seeds import SeedPayload
        return canonical_hash(SeedPayload.model_validate(payload, strict=False))
    if entity_type == "story-engine-option":
        from backend.domain.story_engines import StoryEngineOption
        return canonical_hash(StoryEngineOption.model_validate(payload, strict=False))
    if entity_type == "creation-contract":
        from backend.domain.contracts import CreationContractPayload
        return canonical_hash(CreationContractPayload.model_validate(payload, strict=False))
    if entity_type == "project-contract-draft":
        from backend.services.contracts.drafts import ContractDraftPayload
        return canonical_hash(ContractDraftPayload.model_validate(payload, strict=False))
    if entity_type == "style-contract":
        if set(payload) != {"mergedStyle", "likes", "dislikes"}:
            raise ValueError
        return canonical_hash(payload)
    if entity_type in {"project-bible-draft", "creation-bible-revision"}:
        from backend.domain.bibles import BiblePayload, canonical_bible_hash
        return canonical_bible_hash(BiblePayload.model_validate(payload, strict=False))
    if entity_type == "planning-draft":
        from backend.domain.planning import DraftPlanningAggregate, PlanningAggregate, planning_content_hash
        if payload.get("schemaVersion") == "planning-v1":
            _rehash_planning_nodes(payload)
            model = PlanningAggregate.model_validate(payload, strict=False)
            return planning_content_hash(model.model_dump(mode="json", by_alias=True, exclude={"content_hash"}))
        return canonical_hash(DraftPlanningAggregate.model_validate(payload, strict=False))
    if entity_type == "planning-revision":
        from backend.domain.planning import PlanningAggregate, planning_content_hash
        _rehash_planning_nodes(payload)
        model = PlanningAggregate.model_validate(payload, strict=False)
        return planning_content_hash(model.model_dump(mode="json", by_alias=True, exclude={"content_hash"}))
    if entity_type == "chapter-outline-draft":
        from backend.domain.chapter_outlines import ChapterOutline, DraftChapterOutline, EditableChapterOutlineContent
        if payload.get("schemaVersion") == "chapter-outline-draft-v1":
            model = EditableChapterOutlineContent.model_validate(payload, strict=False)
        elif "canonRevision" in payload or "projectionRevision" in payload or "contentHash" in payload:
            formal = ChapterOutline.model_validate(payload, strict=False)
            return canonical_hash(formal.model_dump(mode="json", by_alias=True, exclude={"content_hash"}))
        else:
            model = DraftChapterOutline.model_validate(payload, strict=False)
        return canonical_hash(model)
    if entity_type == "chapter-outline-revision":
        from backend.domain.chapter_outlines import ChapterOutline
        model = ChapterOutline.model_validate(payload, strict=False)
        return canonical_hash(model.model_dump(mode="json", by_alias=True, exclude={"content_hash"}))
    if entity_type == "finalization-change-set-revision":
        from backend.domain.finalization import FinalizationChangeSet, change_set_hash
        return change_set_hash(FinalizationChangeSet.model_validate(payload, strict=False))
    return canonical_hash(payload)


def _rewrite_records(
    package: VerifiedProjectPackage,
    identity_map: ImportIdentityMap,
) -> dict[tuple[str, str], dict[str, object]]:
    rewritten: dict[tuple[str, str], dict[str, object]] = {}
    records = tuple(sorted(package.graph_index.values(), key=record_sort_key))
    binding_items = [record for record in records if record.entity_type == "project-model-binding-item"]
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.model_bindings import BindingItem, BindingRevision, TASK_KEYS

    for record in records:
        if record.entity_type in PROVENANCE_ENTITY_TYPES:
            continue
        data = _rewrite_record_data(record, identity_map.ids)
        if record.entity_type == "project-model-binding-item":
            data.update({"resolutionStatus": "unbound", "providerId": None, "providerName": None, "modelName": None})
            item = BindingItem(task_key=data["taskKey"], resolution_status="unbound")
            data["itemHash"] = canonical_hash(item)
        if record.entity_type == "finalization-record" and isinstance(data.get("resultPayload"), dict):
            data["resultHash"] = canonical_hash(data["resultPayload"])
        rewritten[(record.entity_type, record.logical_id)] = data

    for record in records:
        if record.entity_type != "project-model-binding-revision":
            continue
        selected = {
            item.data.get("taskKey"): item
            for item in binding_items
            if item.data.get("bindingRevisionLogicalId") == record.logical_id
        }
        if set(selected) != set(TASK_KEYS) or len(selected) != len(TASK_KEYS):
            raise _invalid()
        project_id = identity_map.target_project_id
        revision = record.data.get("revision", record.revision)
        model = BindingRevision(
            project_id=project_id, revision=revision,
            items=tuple(BindingItem(task_key=key, resolution_status="unbound") for key in TASK_KEYS),
        )
        rewritten[(record.entity_type, record.logical_id)]["contentHash"] = canonical_hash(model)

    # Rewrite embedded binding pins before hashing CreationContract itself.
    for record in records:
        if record.entity_type not in {"project-contract-draft", "creation-contract"}:
            continue
        data = rewritten[(record.entity_type, record.logical_id)]
        payload = data.get("payload")
        original_payload = record.data.get("payload")
        if not isinstance(payload, dict) or not isinstance(original_payload, Mapping):
            continue
        binding = payload.get("modelBindingRef")
        original_binding = original_payload.get("modelBindingRef")
        if isinstance(binding, dict) and isinstance(original_binding, Mapping):
            source_id = original_binding.get("id")
            target = rewritten.get(("project-model-binding-revision", source_id)) if isinstance(source_id, str) else None
            if target is None or not isinstance(target.get("contentHash"), str):
                raise _invalid()
            binding["contentHash"] = target["contentHash"]

    hash_order = (
        "creative-seed-revision", "story-engine-option", "asset", "project-contract-draft", "creation-contract", "style-contract",
        "project-bible-draft", "creation-bible-revision", "planning-draft", "planning-revision",
        "chapter-outline-draft", "chapter-outline-revision", "finalization-change-set-revision",
        "candidate-quality",
    )
    for entity_type in hash_order:
        for record in records:
            if record.entity_type != entity_type:
                continue
            data = rewritten[(record.entity_type, record.logical_id)]
            if record.entity_type == "chapter-outline-revision":
                planning_logical_id = record.data.get("planningRevisionLogicalId")
                planning = rewritten.get(("planning-revision", planning_logical_id)) if isinstance(planning_logical_id, str) else None
                if planning is None or not isinstance(planning.get("contentHash"), str):
                    raise _invalid()
                data["planningHash"] = planning["contentHash"]
                outline_payload = data.get("payload")
                if isinstance(outline_payload, dict) and "planningHash" in outline_payload:
                    outline_payload["planningHash"] = planning["contentHash"]
                _rewrite_outline_node_hashes(record, data, rewritten)
            if record.entity_type == "chapter-outline-draft":
                outline_payload = data.get("payload")
                if not isinstance(outline_payload, dict):
                    raise _invalid()
                if outline_payload.get("schemaVersion") != "chapter-outline-draft-v1":
                    planning_logical_id = record.data.get("planningRevisionLogicalId")
                    planning = rewritten.get(("planning-revision", planning_logical_id)) if isinstance(planning_logical_id, str) else None
                    if planning is None or not isinstance(planning.get("contentHash"), str):
                        raise _invalid()
                    data["planningHash"] = planning["contentHash"]
                    outline_payload["planningHash"] = planning["contentHash"]
                    _rewrite_outline_node_hashes(record, data, rewritten)
            if record.entity_type == "candidate-quality":
                chapter_logical_id = record.data.get("chapterLogicalId")
                chapter = package.graph_index.get(("chapter", chapter_logical_id)) if isinstance(chapter_logical_id, str) else None
                if chapter is None:
                    raise _invalid()
                planning_logical_id = chapter.data.get("planningRevisionLogicalId")
                outline_logical_id = chapter.data.get("outlineRevisionLogicalId")
                planning = rewritten.get(("planning-revision", planning_logical_id)) if isinstance(planning_logical_id, str) else None
                outline = rewritten.get(("chapter-outline-revision", outline_logical_id)) if isinstance(outline_logical_id, str) else None
                if planning is None or outline is None or not isinstance(planning.get("contentHash"), str) or not isinstance(outline.get("contentHash"), str):
                    raise _invalid()
                data["expectedPlanningHash"] = planning["contentHash"]
                data["expectedOutlineHash"] = outline["contentHash"]
            if record.entity_type == "finalization-change-set-revision":
                payload = data.get("payload")
                if not isinstance(payload, dict):
                    raise _invalid()
                for patch in payload.get("planningPatches", ()):
                    if not isinstance(patch, dict):
                        raise _invalid()
                    patch["expectedHash"] = _planning_node_hash(rewritten, patch.get("targetId"))
            own_hash = _authority_hash(record.entity_type, data)
            if own_hash is not None:
                data["contentHash"] = own_hash
                if record.entity_type in {"planning-revision", "chapter-outline-revision"}:
                    payload = data.get("payload")
                    if not isinstance(payload, dict):
                        raise _invalid()
                    payload["contentHash"] = own_hash

    for change_set in (record for record in records if record.entity_type == "finalization-change-set"):
        revisions = [
            record for record in records
            if record.entity_type == "finalization-change-set-revision"
            and record.data.get("changeSetLogicalId") == change_set.logical_id
        ]
        if revisions:
            latest = max(revisions, key=lambda value: value.data.get("revision", value.revision))
            target = rewritten[(latest.entity_type, latest.logical_id)].get("contentHash")
            if not isinstance(target, str):
                raise _invalid()
            rewritten[(change_set.entity_type, change_set.logical_id)]["contentHash"] = target

    # Relational pins are repaired only after every rewritten authority hash exists.
    for record in records:
        data = rewritten.get((record.entity_type, record.logical_id))
        if data is None:
            continue
        for field, targets in _REFS.get(record.entity_type, {}).items():
            source_logical = record.data.get(field)
            if not isinstance(source_logical, str):
                continue
            matches = [rewritten[(kind, source_logical)] for kind in targets if (kind, source_logical) in rewritten]
            target = matches[0] if len(matches) == 1 else None
            if target is None:
                continue
            hash_fields = {
                "seedRevisionLogicalId": "seedHash", "creationContractLogicalId": "creationHash",
                "styleContractLogicalId": "styleHash", "bibleRevisionLogicalId": "bibleHash",
                "planningRevisionLogicalId": "planningHash", "outlineRevisionLogicalId": "chapterOutlineHash",
                "candidateLogicalId": "candidateHash", "bindingRevisionLogicalId": "bindingHash",
                "changeSetLogicalId": "changeSetHash", "draftLogicalId": "draftHash",
            }
            hash_field = hash_fields.get(field)
            if hash_field in data and isinstance(target.get("contentHash"), str):
                data[hash_field] = target["contentHash"]
        result_targets = {
            "bible-confirmation": ("bibleRevisionLogicalId", "creation-bible-revision"),
            "planning-confirmation": ("planningRevisionLogicalId", "planning-revision"),
            "chapter-outline-confirmation": ("outlineRevisionLogicalId", "chapter-outline-revision"),
        }
        result_target = result_targets.get(record.entity_type)
        if result_target is not None:
            field, kind = result_target
            logical_id = record.data.get(field)
            target = rewritten.get((kind, logical_id)) if isinstance(logical_id, str) else None
            if target is None or not isinstance(target.get("contentHash"), str):
                raise _invalid()
            data["contentHash"] = target["contentHash"]
        if record.entity_type == "chapter":
            _repair_chapter_story_block_pin(record, data, package, rewritten, identity_map.ids)
        head = _HEAD_REVISION_TARGETS.get(record.entity_type)
        if head is not None:
            field, kind = head
            source_logical = record.data.get(field)
            target = rewritten.get((kind, source_logical)) if isinstance(source_logical, str) else None
            if target is not None and isinstance(target.get("contentHash"), str):
                data["contentHash"] = target["contentHash"]
        if record.entity_type == "project-contract-head":
            creation_id = record.data.get("creationContractLogicalId")
            style_id = record.data.get("styleContractLogicalId")
            creation = rewritten.get(("creation-contract", creation_id)) if isinstance(creation_id, str) else None
            style = rewritten.get(("style-contract", style_id)) if isinstance(style_id, str) else None
            if creation is None or style is None or not isinstance(creation.get("contentHash"), str) or not isinstance(style.get("contentHash"), str):
                raise _invalid()
            data["creationHash"] = creation["contentHash"]
            data["styleHash"] = style["contentHash"]

    # Canon revision hashes are production projection hashes over the rewritten event stream.
    for record in records:
        if record.entity_type != "canon-revision":
            continue
        data = rewritten[(record.entity_type, record.logical_id)]
        revision_number = data.get("revisionNumber")
        if type(revision_number) is not int:
            raise _invalid()
        data["contentHash"] = _target_projection(rewritten, identity_map.ids, revision=revision_number)["contentHash"]

    # The commit receipt is downstream of both rewritten Planning and rewritten Canon.
    for record in records:
        if record.entity_type != "finalization-record":
            continue
        data = rewritten[(record.entity_type, record.logical_id)]
        receipt = data.get("resultPayload")
        source_receipt = record.data.get("resultPayload")
        if not isinstance(receipt, dict) or not isinstance(source_receipt, Mapping):
            raise _invalid()
        planning_logical_id = source_receipt.get("planningRevisionId")
        planning = rewritten.get(("planning-revision", planning_logical_id)) if isinstance(planning_logical_id, str) else None
        committed_revision = receipt.get("canonRevision")
        if planning is None or not isinstance(planning.get("contentHash"), str) or type(committed_revision) is not int:
            raise _invalid()
        receipt["planningHash"] = planning["contentHash"]
        receipt["projectionHash"] = _target_projection(
            rewritten, identity_map.ids, revision=committed_revision,
        )["contentHash"]
        data["resultHash"] = canonical_hash(receipt)
    return rewritten


def _validate_publication_references(package: VerifiedProjectPackage) -> None:
    records = tuple(package.graph_index.values())
    if len(records) != len(package.graph_index):
        raise _invalid()
    embedded = {
        identity
        for record in records
        for identity in _publication_embedded_identities(record)
    }
    for identity, record in package.graph_index.items():
        if identity != (record.entity_type, record.logical_id) or record.entity_type not in all_v1_record_types():
            raise _invalid()
        for field, target_types in _REFS.get(record.entity_type, {}).items():
            value = record.data.get(field)
            if value is None and field in _OPTIONAL_REF_FIELDS.get(record.entity_type, frozenset()):
                continue
            if not isinstance(value, str) or not any(
                (kind, value) in package.graph_index or (kind, value) in embedded
                for kind in target_types
            ):
                raise _invalid()
        for reference_field, target_type, revision_field, hash_field in _PINNED_REVISIONS.get(record.entity_type, ()):
            reference = record.data.get(reference_field)
            target = package.graph_index.get((target_type, reference)) if isinstance(reference, str) else None
            if target is None:
                raise _invalid()
            if revision_field in record.data and record.data[revision_field] != target.data.get("revision", target.revision):
                raise _invalid()
            if hash_field in record.data and record.data[hash_field] != target.data.get("contentHash"):
                raise _invalid()


def _validate_source_hashes(package: VerifiedProjectPackage) -> None:
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.seeds import SeedPayload, decode_seed_revision
    from backend.domain.story_engines import StoryEngineOption
    try:
        for record in package.graph_index.values():
            if record.entity_type == "creative-seed-revision":
                raw = record.data.get("payload")
                try:
                    payload = SeedPayload.model_validate(thaw_json_value(raw), strict=False)
                except Exception:
                    payload, _provenance = decode_seed_revision(canonical_line(raw).decode("utf-8"))
                if record.data.get("contentHash") != canonical_hash(payload):
                    raise ValueError
            elif record.entity_type == "story-engine-option":
                raw = record.data.get("payload")
                payload = StoryEngineOption.model_validate(thaw_json_value(raw), strict=False)
                if record.data.get("contentHash") != canonical_hash(payload):
                    raise ValueError
            elif record.entity_type in {"working-draft", "working-draft-revision", "draft-candidate", "final-chapter"}:
                content = record.data.get("content")
                if isinstance(content, str) and record.data.get("contentHash") != sha256(content.encode("utf-8")).hexdigest():
                    raise ValueError
    except Exception:
        raise _invalid() from None


def _publication_embedded_identities(record: PackageRecord) -> tuple[tuple[str, str], ...]:
    """Collect definitions from the closed typed payload shapes emitted by package v1."""
    found: list[tuple[str, str]] = []

    def add(kind: str, item: object, *, allow_client_key: bool = False) -> None:
        if not isinstance(item, Mapping):
            raise _invalid()
        logical_id = item.get("logicalId") or item.get("id")
        if logical_id is None and allow_client_key:
            return
        if not isinstance(logical_id, str) or re.fullmatch(rf"{re.escape(kind)}:[1-9][0-9]*", logical_id) is None:
            raise _invalid()
        found.append((kind, logical_id))

    payload = record.data.get("payload")
    if record.entity_type in {"planning-draft", "planning-revision"} and isinstance(payload, Mapping):
        is_draft = record.entity_type == "planning-draft"
        for item in payload.get("volumes", ()):
            add("planning-volume", item, allow_client_key=is_draft)
        for item in payload.get("plots", ()):
            add("planning-plot", item, allow_client_key=is_draft)
        for block in payload.get("storyBlocks", ()):
            add("story-block", block, allow_client_key=is_draft)
            if not isinstance(block, Mapping):
                raise _invalid()
            for stage in block.get("stages", ()):
                add("planning-stage", stage, allow_client_key=is_draft)
                if not isinstance(stage, Mapping):
                    raise _invalid()
                for task in stage.get("sceneTasks", ()):
                    add("scene-task", task, allow_client_key=is_draft)
    elif record.entity_type in {"project-bible-draft", "creation-bible-revision"} and isinstance(payload, Mapping):
        fields = {
            "worldRules": "bible-world-rule", "coreCast": "bible-core-cast", "factions": "bible-faction",
            "longTermConflicts": "bible-long-term-conflict", "relationshipDynamics": "bible-relationship-dynamic",
            "continuityGuardrails": "bible-continuity-guardrail", "openDesignQuestions": "bible-open-design-question",
        }
        for field, kind in fields.items():
            for item in payload.get(field, ()):
                add(kind, item)
    elif record.entity_type == "finalization-change-set-revision" and isinstance(payload, Mapping):
        fields = {
            "entities": "finalization-entity", "aliases": "finalization-alias", "canonEvents": "finalization-event",
            "storyProgressEvents": "finalization-progress-event", "planningPatches": "finalization-planning-patch",
            "planningSuggestions": "finalization-planning-suggestion",
        }
        for field, kind in fields.items():
            for item in payload.get(field, ()):
                add(kind, item)
    elif record.entity_type == "candidate-quality":
        for item in record.data.get("findings", ()):
            add("quality-finding", item)
    elif record.entity_type == "corpus-revision":
        for item in record.data.get("chapters", ()):
            add("corpus-chapter", item)
        for item in record.data.get("fragments", ()):
            add("corpus-fragment", item)
    if len(found) != len(set(found)):
        raise _invalid()
    return tuple(found)


def _expected_projection(package: VerifiedProjectPackage) -> Mapping[str, object]:
    entry = package.entry_index.get("validation/projections.json")
    if entry is None or not package.archive_path.is_file():
        return MappingProxyType({})
    try:
        with zipfile.ZipFile(package.archive_path, "r", allowZip64=False) as archive:
            raw = _member_bytes(archive, entry)
        _projection(raw)
        return freeze_json_value(_json(raw))  # type: ignore[return-value]
    except ProjectImportInvalid:
        raise
    except Exception:
        raise _invalid() from None


def _target_projection(
    rewritten: Mapping[tuple[str, str], Mapping[str, object]],
    ids: Mapping[tuple[str, str], str],
    *,
    revision: int | None = None,
) -> Mapping[str, object]:
    from backend.services.projections import build_projection_bundle

    if revision is None:
        revision = max(
            (int(data["revisionNumber"]) for (kind, _), data in rewritten.items() if kind == "canon-revision"),
            default=0,
        )
    if type(revision) is not int or revision < 0:
        raise _invalid()
    events: list[dict[str, object]] = []
    for key, data in rewritten.items():
        if key[0] != "canon-event":
            continue
        event_revision = data.get("revisionNumber")
        if type(event_revision) is not int or event_revision > revision:
            continue
        events.append({
            "id": ids[key], "revision_number": data.get("revisionNumber"),
            "event_order": data.get("eventOrder"), "entity_id": data.get("entityLogicalId"),
            "fact_kind": data.get("factKind"), "field_path": data.get("fieldPath"),
            "value": data.get("value"), "confirmation_status": data.get("confirmationStatus"),
            "evidence": data.get("evidence"),
        })
    bundle = build_projection_bundle(revision, events)
    return _freeze_publication_json({
        "revision": bundle.revision,
        "currentState": thaw_json_value(bundle.current_state),
        "memories": thaw_json_value(bundle.memories),
        "arcs": thaw_json_value(bundle.arcs),
        "plotThreads": thaw_json_value(bundle.plot_threads),
        "contentHash": bundle.content_hash,
    })  # type: ignore[return-value]


def build_publication_plan(
    package: VerifiedProjectPackage,
    command_id: str,
    new_title: str,
) -> ProjectPublicationPlan:
    """Normalize one verified package into an immutable, SQL-free publication value."""
    try:
        if not isinstance(package, VerifiedProjectPackage) or not isinstance(new_title, str) or not new_title.strip() or len(new_title) > 200:
            raise ValueError
        _validate_publication_references(package)
        _validate_source_hashes(package)
        identities: list[tuple[str, str]] = []
        derived_identities: dict[tuple[str, str], None] = {}
        for record in package.graph_index.values():
            if record.entity_type not in PROVENANCE_ENTITY_TYPES:
                identities.append((record.entity_type, record.logical_id))
                for identity in _publication_embedded_identities(record):
                    derived_identities.setdefault(identity, None)
        for record in package.graph_index.values():
            if record.entity_type == "story-engine-option":
                batch_id = record.data.get("batchLogicalId")
                if isinstance(batch_id, str):
                    derived_identities.setdefault(("story-engine-batch", batch_id), None)
        identities.extend(identity for identity in derived_identities if identity not in set(identities))
        identity_map = build_import_identity_map(command_id, identities)
        rewritten = _rewrite_records(package, identity_map)
        from backend.domain.json_contracts import canonical_json
        from backend.domain.model_bindings import TASK_KEYS

        def publication_order(record: PackageRecord) -> tuple[object, ...]:
            binding_order = TASK_KEYS.index(record.data.get("taskKey")) if record.entity_type == "project-model-binding-item" and record.data.get("taskKey") in TASK_KEYS else record.order
            return record.entity_type, binding_order, record.logical_id

        formal_records = tuple(
            record for record in sorted(package.graph_index.values(), key=publication_order)
            if record.entity_type not in PROVENANCE_ENTITY_TYPES
        )
        encoded = encode_publication_batches(
            formal_records, rewritten, identity_map.ids,
            command_id=command_id, target_project_id=identity_map.target_project_id,
            new_title=new_title.strip(), source_records=tuple(package.graph_index.values()),
        )
        provenance_records = tuple(
            record for record in package.graph_index.values()
            if record.entity_type in PROVENANCE_ENTITY_TYPES
        )
        provenance_batch = encode_provenance_batch(
            provenance_records, command_id=command_id,
            target_project_id=identity_map.target_project_id,
        )
        if provenance_batch is not None:
            encoded = (*encoded, provenance_batch)
        positions = {table: index for index, table in enumerate(_PUBLICATION_TABLE_ORDER)}
        encoded = tuple(sorted(encoded, key=lambda batch: positions[batch.table]))
        batches = tuple(
            ImportInsertBatch(batch.table, batch.columns, batch.rows) for batch in encoded
        )
        provenance = tuple(
            canonical_json(record.to_public_dict())
            for record in sorted(package.graph_index.values(), key=record_sort_key)
            if record.entity_type in PROVENANCE_ENTITY_TYPES
        )
        blobs = tuple(sorted(
            (entry.sha256, entry.byte_length) for path, entry in package.entry_index.items()
            if CORPUS_BLOB_RE.fullmatch(path)
        ))
        _expected_projection(package)  # Validate the source diagnostic artifact when present.
        return ProjectPublicationPlan(
            command_id, identity_map.target_project_id, identity_map.id_map_hash,
            batches, provenance, blobs, _target_projection(rewritten, identity_map.ids),
            package.package_hash, package.manifest_hash,
        )
    except ProjectImportInvalid:
        raise
    except Exception:
        raise _invalid() from None


def _identity_uuid(namespace: UUID, entity_type: str, logical_id: str) -> str:
    return str(uuid5(namespace, f"{entity_type}/{logical_id}"))


def build_import_identity_map(
    command_id: str,
    identities: object,
) -> ImportIdentityMap:
    """Build the closed command-scoped UUID map used by publication."""
    try:
        namespace = UUID(command_id)
        supplied = tuple(identities)  # type: ignore[arg-type]
        allowed = all_v1_record_types() | _EMBEDDED_IDENTITY_TYPES
        if not supplied:
            raise ValueError
        seen: set[tuple[str, str]] = set()
        mapped: dict[tuple[str, str], str] = {}
        outputs: set[str] = set()
        for identity in supplied:
            if not isinstance(identity, tuple) or len(identity) != 2:
                raise ValueError
            entity_type, logical_id = identity
            if (
                not isinstance(entity_type, str)
                or entity_type not in allowed
                or not isinstance(logical_id, str)
                or re.fullmatch(rf"{re.escape(entity_type)}:[1-9][0-9]*", logical_id) is None
                or identity in seen
            ):
                raise ValueError
            seen.add(identity)
            target = _identity_uuid(namespace, entity_type, logical_id)
            if target in outputs:
                raise ValueError
            outputs.add(target)
            mapped[identity] = target
        project = mapped.get(("project", "project:1"))
        if project is None or sum(kind == "project" for kind, _ in mapped) != 1:
            raise ValueError
        from backend.domain.json_contracts import canonical_hash
        entries = [
            {"entityType": kind, "id": mapped[(kind, logical_id)], "logicalId": logical_id}
            for kind, logical_id in sorted(mapped)
        ]
        return ImportIdentityMap(
            MappingProxyType(mapped), project, canonical_hash({"identities": entries}),
        )
    except ProjectImportInvalid:
        raise
    except Exception:
        raise _invalid() from None


def _invalid() -> ProjectImportInvalid:
    return ProjectImportInvalid("invalid project import archive")


def _too_large() -> ProjectImportTooLarge:
    return ProjectImportTooLarge("project import archive exceeds configured limit")


def _reject_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise ValueError


_IMPORT_SENSITIVE_ALIASES = frozenset({"idempotencykey", "providerprofileid", "providerid", "profileid"})
_PATH_ALIASES = frozenset({"localpath", "absolutepath", "filesystempath", "storagepath", "path"})


def _reject_import_sensitive_aliases(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = key.replace("_", "").replace("-", "").casefold() if isinstance(key, str) else ""
            if normalized in _IMPORT_SENSITIVE_ALIASES:
                raise ProjectImportSensitiveData("project import contains sensitive data")
            if normalized in _PATH_ALIASES and isinstance(nested, str) and (nested.startswith("/") or nested.startswith("\\") or re.match(r"^[a-zA-Z]:[/\\]", nested)):
                raise ProjectImportSensitiveData("project import contains sensitive data")
            _reject_import_sensitive_aliases(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_import_sensitive_aliases(nested)


def _json(raw: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_reject_pairs, parse_constant=_reject_constant)
        validate_json_depth(value)
        if not isinstance(value, dict):
            raise ValueError
        _reject_import_sensitive_aliases(value)
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise _invalid() from None


def _exact_keys(value: Mapping[str, object], expected: frozenset[str]) -> None:
    if set(value) != expected:
        raise _invalid()


def _manifest(raw: bytes, raw_hash: bytes) -> ProjectPackageManifest:
    if raw_hash != sha256(raw).hexdigest().encode("ascii") + b"\n":
        raise _invalid()
    value = _json(raw)
    _exact_keys(value, frozenset({"counts", "entries", "format", "hashAlgorithm", "projectLogicalId", "version"}))
    if value["format"] != PACKAGE_FORMAT or value["version"] != PACKAGE_VERSION or value["hashAlgorithm"] != HASH_ALGORITHM:
        raise _invalid()
    entries_value, counts = value["entries"], value["counts"]
    if not isinstance(entries_value, list) or not isinstance(counts, dict):
        raise _invalid()
    try:
        entries = []
        for item in entries_value:
            if not isinstance(item, dict):
                raise ValueError
            _exact_keys(item, frozenset({"path", "byteLength", "sha256"}))
            entries.append(ManifestEntry(item["path"], item["byteLength"], item["sha256"]))
        manifest = ProjectPackageManifest(value["projectLogicalId"], tuple(entries), counts)
        if manifest.to_bytes() != raw:
            raise ValueError
        return manifest
    except Exception:
        raise _invalid() from None


def _record(raw: bytes) -> PackageRecord:
    value = _json(raw)
    _exact_keys(value, frozenset({"data", "entityType", "logicalId", "order", "revision"}))
    if not isinstance(value["data"], dict):
        raise _invalid()
    try:
        record = PackageRecord(value["entityType"], value["logicalId"], value["revision"], value["order"], value["data"])
        if canonical_line(record.to_public_dict()) != raw:
            raise ValueError
        return record
    except ProjectPackageSensitiveData:
        raise ProjectImportSensitiveData("project import contains sensitive data") from None
    except Exception:
        raise _invalid() from None


def _stream_records(archive: zipfile.ZipFile, verified: VerifiedArchiveEntry) -> tuple[PackageRecord, ...]:
    """Parse one JSONL member incrementally, retaining only its validated records."""
    if verified.byte_length > MAX_STRUCTURED_ENTRY_BYTES:
        raise _too_large()
    buffer = bytearray()
    records: list[PackageRecord] = []
    identities: set[tuple[str, str]] = set()
    previous: tuple[str, str, int, int] | None = None
    total = 0
    try:
        with archive.open(verified.path, "r") as source:
            while True:
                chunk = source.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                if type(chunk) is not bytes or len(chunk) > _READ_CHUNK_BYTES:
                    raise _invalid()
                total += len(chunk)
                if total > verified.byte_length:
                    raise _invalid()
                buffer.extend(chunk)
                while True:
                    line_end = buffer.find(b"\n")
                    if line_end < 0:
                        break
                    raw = bytes(buffer[:line_end + 1])
                    del buffer[:line_end + 1]
                    if raw == b"\n":
                        raise _invalid()
                    record = _record(raw)
                    identity = (record.entity_type, record.logical_id)
                    sort_key = record_sort_key(record)
                    if identity in identities or previous is not None and sort_key <= previous or len(records) >= MAX_ENTRY_COUNT:
                        raise _invalid()
                    identities.add(identity)
                    previous = sort_key
                    records.append(record)
                if len(buffer) > MAX_STRUCTURED_ENTRY_BYTES:
                    raise _too_large()
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        raise _invalid() from None
    if total != verified.byte_length or buffer:
        raise _invalid()
    return tuple(records)


_REFS: Mapping[str, Mapping[str, frozenset[str]]] = {
    "creative-seed-revision": {"seedLogicalId": frozenset({"creative-seed"})},
    "creative-seed-head": {"seedLogicalId": frozenset({"creative-seed"}), "revisionLogicalId": frozenset({"creative-seed-revision"})},
    "project-seed-selection-revision": {"seedLogicalId": frozenset({"creative-seed"}), "seedRevisionLogicalId": frozenset({"creative-seed-revision"})},
    "project-selected-seed": {"seedLogicalId": frozenset({"creative-seed"}), "seedRevisionLogicalId": frozenset({"creative-seed-revision"})},
    "project-model-binding-revision": {"sourceProjectLogicalId": frozenset({"project"})},
    "project-model-binding-item": {"bindingRevisionLogicalId": frozenset({"project-model-binding-revision"})},
    "project-model-binding-head": {"bindingRevisionLogicalId": frozenset({"project-model-binding-revision"})},
    "story-engine-option": {"batchLogicalId": frozenset({"story-engine-batch"})},
    "project-contract-draft": {"seedRevisionLogicalId": frozenset({"creative-seed-revision"}), "engineOptionLogicalId": frozenset({"story-engine-option"})},
    "creation-contract": {"seedLogicalId": frozenset({"creative-seed"}), "seedRevisionLogicalId": frozenset({"creative-seed-revision"}), "bindingRevisionLogicalId": frozenset({"project-model-binding-revision"})},
    "style-contract": {"creationContractLogicalId": frozenset({"creation-contract"})},
    "creation-bible-revision": {
        "seedLogicalId": frozenset({"creative-seed"}),
        "seedRevisionLogicalId": frozenset({"creative-seed-revision"}),
        "creationContractLogicalId": frozenset({"creation-contract"}),
        "styleContractLogicalId": frozenset({"style-contract"}),
        "bindingRevisionLogicalId": frozenset({"project-model-binding-revision"}),
    },
    "project-contract-head": {"creationContractLogicalId": frozenset({"creation-contract"}), "styleContractLogicalId": frozenset({"style-contract"})},
    "contract-confirmation": {"creationContractLogicalId": frozenset({"creation-contract"}), "styleContractLogicalId": frozenset({"style-contract"})},
    "creation-contract-engine-ref": {"creationContractLogicalId": frozenset({"creation-contract"}), "storyEngineLogicalId": frozenset({"story-engine-option"})},
    "creation-contract-corpus-ref": {"creationContractLogicalId": frozenset({"creation-contract"}), "corpusRevisionLogicalId": frozenset({"corpus-revision"})},
    "creation-contract-corpus-fragment-ref": {"creationContractLogicalId": frozenset({"creation-contract"}), "corpusRevisionLogicalId": frozenset({"corpus-revision"})},
    "project-bible-head": {"bibleRevisionLogicalId": frozenset({"creation-bible-revision"})},
    "bible-confirmation": {"creationContractLogicalId": frozenset({"creation-contract"}), "styleContractLogicalId": frozenset({"style-contract"}), "draftLogicalId": frozenset({"project-bible-draft"}), "bibleRevisionLogicalId": frozenset({"creation-bible-revision"})},
    "project-bible-draft": {"seedLogicalId": frozenset({"creative-seed"}), "seedRevisionLogicalId": frozenset({"creative-seed-revision"}), "creationContractLogicalId": frozenset({"creation-contract"}), "styleContractLogicalId": frozenset({"style-contract"}), "bindingRevisionLogicalId": frozenset({"project-model-binding-revision"})},
    "planning-draft": {"seedLogicalId": frozenset({"creative-seed"}), "seedRevisionLogicalId": frozenset({"creative-seed-revision"}), "creationContractLogicalId": frozenset({"creation-contract"}), "styleContractLogicalId": frozenset({"style-contract"}), "bibleRevisionLogicalId": frozenset({"creation-bible-revision"})},
    "planning-revision": {"seedLogicalId": frozenset({"creative-seed"}), "seedRevisionLogicalId": frozenset({"creative-seed-revision"}), "creationContractLogicalId": frozenset({"creation-contract"}), "styleContractLogicalId": frozenset({"style-contract"}), "bibleRevisionLogicalId": frozenset({"creation-bible-revision"})},
    "project-planning-head": {"planningRevisionLogicalId": frozenset({"planning-revision"})},
    "planning-confirmation": {"draftLogicalId": frozenset({"planning-draft"}), "planningRevisionLogicalId": frozenset({"planning-revision"})},
    "chapter-outline-revision": {"planningRevisionLogicalId": frozenset({"planning-revision"})},
    "chapter-outline-draft": {"planningRevisionLogicalId": frozenset({"planning-revision"})},
    "project-chapter-outline-head": {"outlineRevisionLogicalId": frozenset({"chapter-outline-revision"})},
    "chapter-outline-confirmation": {"draftLogicalId": frozenset({"chapter-outline-draft"}), "planningRevisionLogicalId": frozenset({"planning-revision"}), "outlineRevisionLogicalId": frozenset({"chapter-outline-revision"})},
    "chapter": {"planningRevisionLogicalId": frozenset({"planning-revision"}), "outlineRevisionLogicalId": frozenset({"chapter-outline-revision"}), "storyBlockLogicalId": frozenset({"story-block"})},
    "working-draft": {"chapterLogicalId": frozenset({"chapter"})}, "operation": {"chapterLogicalId": frozenset({"chapter"})},
    "draft-candidate": {"chapterLogicalId": frozenset({"chapter"})},
    "working-draft-revision": {"workingDraftLogicalId": frozenset({"working-draft"}), "chapterLogicalId": frozenset({"chapter"}), "candidateLogicalId": frozenset({"draft-candidate"}), "operationLogicalId": frozenset({"operation"})},
    "operation-event": {"operationLogicalId": frozenset({"operation"})},
    "candidate-freeze": {"chapterLogicalId": frozenset({"chapter"}), "candidateLogicalId": frozenset({"draft-candidate"})},
    "candidate-quality": {"chapterLogicalId": frozenset({"chapter"}), "candidateLogicalId": frozenset({"draft-candidate"})},
    "finalization-change-set": {"chapterLogicalId": frozenset({"chapter"}), "candidateLogicalId": frozenset({"draft-candidate"})},
    "finalization-change-set-revision": {"changeSetLogicalId": frozenset({"finalization-change-set"})},
    "finalization-record": {"chapterLogicalId": frozenset({"chapter"}), "candidateLogicalId": frozenset({"draft-candidate"}), "changeSetLogicalId": frozenset({"finalization-change-set"})},
    "final-chapter": {"chapterLogicalId": frozenset({"chapter"}), "candidateLogicalId": frozenset({"draft-candidate"}), "finalizationRecordLogicalId": frozenset({"finalization-record"}), "planningRevisionLogicalId": frozenset({"planning-revision"}), "outlineRevisionLogicalId": frozenset({"chapter-outline-revision"})},
    "entity-alias": {"entityLogicalId": frozenset({"canon-entity"})},
    "canon-revision": {"sourceLogicalId": frozenset({"finalization-change-set"})},
    "canon-event": {"canonRevisionLogicalId": frozenset({"canon-revision"}), "entityLogicalId": frozenset({"canon-entity"})},
    "reference-use": {"chapterLogicalId": frozenset({"chapter"}), "candidateLogicalId": frozenset({"draft-candidate"}), "corpusRevisionLogicalId": frozenset({"corpus-revision"}), "corpusChapterLogicalId": frozenset({"corpus-chapter"})},
    "provider-history": {"bindingRevisionLogicalId": frozenset({"project-model-binding-revision"}), "operationLogicalId": frozenset({"operation"})},
}

_EMBEDDED_COLLECTION_TYPES: Mapping[str, str] = {
    "volumes": "planning-volume", "plots": "plot", "storyBlocks": "story-block",
    "stages": "planning-stage", "sceneTasks": "scene-task", "chapters": "corpus-chapter",
    "fragments": "corpus-fragment", "worldRules": "bible-world-rule", "coreCast": "bible-core-cast",
    "factions": "bible-faction", "longTermConflicts": "bible-long-term-conflict",
    "relationshipDynamics": "bible-relationship-dynamic", "continuityGuardrails": "bible-continuity-guardrail",
    "openDesignQuestions": "bible-open-design-question", "entities": "canon-entity",
    "aliases": "entity-alias", "events": "canon-event", "patches": "finalization-patch",
    "suggestions": "finalization-suggestion",
}

_HEAD_REVISION_TARGETS: Mapping[str, tuple[str, str]] = {
    "creative-seed-head": ("revisionLogicalId", "creative-seed-revision"),
    "project-model-binding-head": ("bindingRevisionLogicalId", "project-model-binding-revision"),
    "project-bible-head": ("bibleRevisionLogicalId", "creation-bible-revision"),
    "project-planning-head": ("planningRevisionLogicalId", "planning-revision"),
    "project-chapter-outline-head": ("outlineRevisionLogicalId", "chapter-outline-revision"),
}

_PINNED_REVISIONS: Mapping[str, tuple[tuple[str, str, str, str], ...]] = {
    "creation-contract": (("seedRevisionLogicalId", "creative-seed-revision", "seedRevision", "seedHash"),),
    "project-contract-draft": (("seedRevisionLogicalId", "creative-seed-revision", "seedRevision", "seedHash"),),
    "project-bible-draft": (("seedRevisionLogicalId", "creative-seed-revision", "seedRevision", "seedHash"), ("creationContractLogicalId", "creation-contract", "contractRevision", "creationHash"), ("styleContractLogicalId", "style-contract", "contractRevision", "styleHash")),
    "planning-draft": (("seedRevisionLogicalId", "creative-seed-revision", "seedRevision", "seedHash"), ("creationContractLogicalId", "creation-contract", "contractRevision", "creationHash"), ("styleContractLogicalId", "style-contract", "contractRevision", "styleHash"), ("bibleRevisionLogicalId", "creation-bible-revision", "bibleRevision", "bibleHash")),
    "chapter-outline-draft": (("planningRevisionLogicalId", "planning-revision", "planningRevision", "planningHash"),),
    "bible-confirmation": (("creationContractLogicalId", "creation-contract", "contractRevision", "creationHash"), ("styleContractLogicalId", "style-contract", "contractRevision", "styleHash"), ("draftLogicalId", "project-bible-draft", "draftVersion", "draftHash"), ("bibleRevisionLogicalId", "creation-bible-revision", "resultRevision", "contentHash")),
    "planning-confirmation": (("draftLogicalId", "planning-draft", "draftRevision", "draftHash"), ("planningRevisionLogicalId", "planning-revision", "resultRevision", "contentHash")),
    "chapter-outline-confirmation": (("draftLogicalId", "chapter-outline-draft", "draftRevision", "draftHash"), ("planningRevisionLogicalId", "planning-revision", "planningRevision", "planningHash"), ("outlineRevisionLogicalId", "chapter-outline-revision", "resultRevision", "contentHash")),
    "chapter": (("planningRevisionLogicalId", "planning-revision", "planningRevision", "planningHash"), ("outlineRevisionLogicalId", "chapter-outline-revision", "chapterOutlineRevision", "chapterOutlineHash")),
    "final-chapter": (("planningRevisionLogicalId", "planning-revision", "planningRevision", "planningHash"), ("outlineRevisionLogicalId", "chapter-outline-revision", "chapterOutlineRevision", "chapterOutlineHash")),
}

_REQUIRED_CLOSURE_FIELDS: Mapping[str, frozenset[str]] = {
    "import-provenance": frozenset({
        "category", "sourceEntityType", "sourceLogicalId", "payload",
        "contentHash", "createdAt",
    }),
    "story-engine-option": frozenset({"batchLogicalId", "selectionRevision", "contentHash"}),
    "project-contract-draft": frozenset({"baseHeadRevision", "selectionRevision", "seedRevisionLogicalId", "seedHash", "engineOptionLogicalId", "contentHash"}),
    "creation-contract": frozenset({"revision", "selectionRevision", "seedLogicalId", "seedRevisionLogicalId", "seedHash", "contentHash"}),
    "style-contract": frozenset({"revision", "creationContractLogicalId", "contentHash"}),
    "creation-bible-revision": frozenset({
        "revision", "selectionRevision", "seedLogicalId", "seedRevisionLogicalId", "seedHash",
        "contractRevision", "creationContractLogicalId", "creationHash", "styleContractLogicalId", "styleHash",
        "policyVersion", "contentHash",
    }),
    "project-bible-draft": frozenset({"baseHeadRevision", "selectionRevision", "seedLogicalId", "seedRevisionLogicalId", "seedHash", "contractRevision", "creationContractLogicalId", "creationHash", "styleContractLogicalId", "styleHash", "policyVersion", "contentHash"}),
    "planning-draft": frozenset({"baseHeadRevision", "selectionRevision", "seedLogicalId", "seedRevisionLogicalId", "seedHash", "contractRevision", "creationContractLogicalId", "creationHash", "styleContractLogicalId", "styleHash", "bibleRevision", "bibleRevisionLogicalId", "bibleHash", "contentHash"}),
    "chapter-outline-draft": frozenset({"chapterNumber", "baseHeadRevision", "planningRevisionLogicalId", "planningRevision", "planningHash", "canonRevision", "projectionRevision", "projectionHash", "contentHash"}),
    "contract-confirmation": frozenset({"selectionRevision", "creationContractLogicalId", "styleContractLogicalId", "resultRevision", "contentHash"}),
    "bible-confirmation": frozenset({"selectionRevision", "contractRevision", "creationContractLogicalId", "creationHash", "styleContractLogicalId", "styleHash", "draftLogicalId", "draftVersion", "draftHash", "bibleRevisionLogicalId", "resultRevision", "contentHash"}),
    "planning-confirmation": frozenset({"draftLogicalId", "draftRevision", "draftHash", "expectedHeadRevision", "planningRevisionLogicalId", "resultRevision", "contentHash"}),
    "chapter-outline-confirmation": frozenset({"chapterNumber", "draftLogicalId", "draftRevision", "draftHash", "expectedHeadRevision", "planningRevisionLogicalId", "planningRevision", "planningHash", "canonRevision", "projectionRevision", "projectionHash", "outlineRevisionLogicalId", "resultRevision", "contentHash"}),
    "planning-revision": frozenset({"revision", "contentHash", "seedLogicalId", "seedRevisionLogicalId", "seedHash", "creationContractLogicalId", "creationHash", "styleContractLogicalId", "styleHash", "bibleRevisionLogicalId", "bibleHash"}),
    "chapter": frozenset({"planningRevisionLogicalId", "planningRevision", "planningHash", "outlineRevisionLogicalId", "chapterOutlineRevision", "chapterOutlineHash", "storyBlockLogicalId", "storyBlockRevision", "storyBlockHash"}),
    "final-chapter": frozenset({"finalizationRecordLogicalId", "planningRevisionLogicalId", "planningRevision", "planningHash", "outlineRevisionLogicalId", "chapterOutlineRevision", "chapterOutlineHash", "candidateLogicalId", "contentHash", "canonRevision"}),
    "corpus-revision": frozenset({"contentHash", "byteLength", "chapters", "fragments"}),
    "reference-use": frozenset({"chapterLogicalId", "candidateLogicalId", "corpusRevisionLogicalId", "corpusChapterLogicalId"}),
}

_OPTIONAL_REF_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType({
    "creation-contract": frozenset({"bindingRevisionLogicalId"}),
    "project-bible-draft": frozenset({"bindingRevisionLogicalId"}),
    "project-model-binding-revision": frozenset({"sourceProjectLogicalId"}),
    "working-draft-revision": frozenset({"candidateLogicalId", "operationLogicalId"}),
    "canon-revision": frozenset({"sourceLogicalId"}),
    "provider-history": frozenset({"operationLogicalId"}),
    "creation-bible-revision": frozenset({"bindingRevisionLogicalId"}),
})

VALIDATORS: Mapping[str, RecordValidator] = MappingProxyType({
    entity_type: RecordValidator(
        entity_type=entity_type,
        required_fields=_REQUIRED_CLOSURE_FIELDS.get(entity_type, frozenset()) | (frozenset(_REFS.get(entity_type, {})) - _OPTIONAL_REF_FIELDS.get(entity_type, frozenset())) | (frozenset({"status"}) if entity_type == "operation" else frozenset()),
        reference_fields=frozenset(_REFS.get(entity_type, {})),
        allowed_states=frozenset({"completed", "failed", "cancelled", "succeeded"}) if entity_type == "operation" else frozenset(),
    )
    for entity_type in sorted(all_v1_record_types())
})


def _embedded_identities(record: PackageRecord) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()

    def visit(value: object) -> None:
        if not isinstance(value, Mapping):
            return
        for key, kind in _EMBEDDED_COLLECTION_TYPES.items():
            items = value.get(key)
            if items is None:
                continue
            if not isinstance(items, (list, tuple)):
                raise _invalid()
            for item in items:
                if not isinstance(item, Mapping) or not isinstance(item.get("logicalId"), str):
                    raise _invalid()
                identity = (kind, item["logicalId"])
                if identity in found:
                    raise _invalid()
                found.add(identity)
                visit(item)
        for key in ("payload", "resultPayload", "data"):
            nested = value.get(key)
            if isinstance(nested, Mapping):
                visit(nested)

    visit(record.data)
    return found


def _validate_graph(records: tuple[PackageRecord, ...]) -> dict[tuple[str, str], PackageRecord]:
    index = {(record.entity_type, record.logical_id): record for record in records}
    if len(index) != len(records) or any(record.entity_type not in all_v1_record_types() for record in records):
        raise _invalid()
    embedded: set[tuple[str, str]] = set()
    for record in records:
        for identity in _embedded_identities(record):
            if identity in index:
                raise _invalid()
            embedded.add(identity)
    for record in records:
        declaration = VALIDATORS.get(record.entity_type)
        if declaration is None or not declaration.required_fields.issubset(record.data):
            raise _invalid()
        for field, target_types in _REFS.get(record.entity_type, {}).items():
            value = record.data.get(field)
            if value is not None and (not isinstance(value, str) or not any((kind, value) in index or (kind, value) in embedded for kind in target_types)):
                raise _invalid()
        if record.entity_type == "operation" and "status" in record.data and record.data["status"] not in {"completed", "failed", "cancelled", "succeeded"}:
            raise _invalid()
        if record.entity_type == "import-provenance":
            if (
                record.data.get("category") not in {
                    "provider-history", "market-history",
                    "operation-history", "unsupported-history",
                }
                or not isinstance(record.data.get("sourceEntityType"), str)
                or not record.data["sourceEntityType"]
                or not isinstance(record.data.get("sourceLogicalId"), str)
                or not record.data["sourceLogicalId"]
                or not isinstance(record.data.get("payload"), Mapping)
                or not isinstance(record.data.get("contentHash"), str)
                or re.fullmatch(r"[0-9a-f]{64}", record.data["contentHash"]) is None
                or type(record.data.get("createdAt")) is not int
            ):
                raise _invalid()
        if record.entity_type == "final-chapter" and record.data.get("canonRevision") is not None and not isinstance(record.data["canonRevision"], int):
            raise _invalid()
        if record.entity_type == "planning-revision":
            for logical_field, target_type, hash_field in (("seedRevisionLogicalId", "creative-seed-revision", "seedHash"), ("creationContractLogicalId", "creation-contract", "creationHash"), ("styleContractLogicalId", "style-contract", "styleHash"), ("bibleRevisionLogicalId", "creation-bible-revision", "bibleHash")):
                target = index.get((target_type, record.data[logical_field]))
                if target is None or record.data[hash_field] != target.data.get("contentHash"):
                    raise _invalid()
        if record.entity_type == "creation-bible-revision":
            for logical_field, target_type, revision_field, hash_field in (
                ("seedRevisionLogicalId", "creative-seed-revision", None, "seedHash"),
                ("creationContractLogicalId", "creation-contract", "contractRevision", "creationHash"),
                ("styleContractLogicalId", "style-contract", "contractRevision", "styleHash"),
            ):
                target = index.get((target_type, record.data[logical_field]))
                if target is None or record.data[hash_field] != target.data.get("contentHash"):
                    raise _invalid()
                if revision_field is not None and record.data[revision_field] != target.data.get("revision", target.revision):
                    raise _invalid()
            binding_id = record.data.get("bindingRevisionLogicalId")
            binding_hash = record.data.get("bindingHash")
            if (binding_id is None) != (binding_hash is None):
                raise _invalid()
            if binding_id is not None:
                binding = index.get(("project-model-binding-revision", binding_id))
                if binding is None or binding_hash != binding.data.get("contentHash"):
                    raise _invalid()
        for reference_field, target_type, revision_field, hash_field in _PINNED_REVISIONS.get(record.entity_type, ()):
            reference = record.data.get(reference_field)
            target = index.get((target_type, reference)) if isinstance(reference, str) else None
            if target is None:
                raise _invalid()
            target_revision = target.data.get("revision", target.revision)
            if revision_field in record.data and record.data[revision_field] != target_revision:
                raise _invalid()
            if hash_field in record.data and record.data[hash_field] != target.data.get("contentHash"):
                raise _invalid()
        head_target = _HEAD_REVISION_TARGETS.get(record.entity_type)
        if head_target is not None:
            field, target_type = head_target
            target_id = record.data.get(field)
            target = index.get((target_type, target_id)) if isinstance(target_id, str) else None
            if target is None:
                raise _invalid()
            for key in ("revision", "contentHash"):
                if key in record.data and record.data[key] != target.data.get(key, target.revision if key == "revision" else None):
                    raise _invalid()
    canon_revisions = sorted(
        (record for record in records if record.entity_type == "canon-revision"),
        key=lambda record: record.data.get("revisionNumber", -1),
    )
    for expected, revision in enumerate(canon_revisions, start=1):
        number = revision.data.get("revisionNumber")
        parent = revision.data.get("parentRevisionNumber")
        source_type = revision.data.get("sourceType")
        source_id = revision.data.get("sourceLogicalId")
        if type(number) is not int or number != expected or parent != (expected - 1 if expected > 1 else 0):
            raise _invalid()
        if source_type == "finalization":
            if not isinstance(source_id, str) or ("finalization-change-set", source_id) not in index:
                raise _invalid()
        elif source_type in {"bootstrap", "manual_test"}:
            if source_id is not None:
                raise _invalid()
        else:
            raise _invalid()
    for event in (record for record in records if record.entity_type == "canon-event"):
        revision_id = event.data.get("canonRevisionLogicalId")
        revision = index.get(("canon-revision", revision_id)) if isinstance(revision_id, str) else None
        if revision is None or event.data.get("revisionNumber") != revision.data.get("revisionNumber"):
            raise _invalid()
    from backend.domain.model_bindings import TASK_KEYS
    for binding in (record for record in records if record.entity_type == "project-model-binding-revision"):
        items = [item for item in records if item.entity_type == "project-model-binding-item" and item.data.get("bindingRevisionLogicalId") == binding.logical_id]
        by_task = {item.data.get("taskKey"): item for item in items}
        if set(by_task) != set(TASK_KEYS) or len(by_task) != len(TASK_KEYS) or len({item.logical_id for item in items}) != len(TASK_KEYS):
            raise _invalid()
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.seeds import SeedPayload, decode_seed_revision
    for revision in (record for record in records if record.entity_type == "creative-seed-revision"):
        try:
            raw_payload = revision.data.get("payload")
            try:
                payload = SeedPayload.model_validate(raw_payload, strict=True)
            except Exception:
                payload, _provenance = decode_seed_revision(canonical_line(raw_payload).decode("utf-8"))
        except Exception:
            raise _invalid() from None
        if revision.data.get("contentHash") != canonical_hash(payload):
            raise _invalid()
    for record in records:
        if record.entity_type == "corpus-revision":
            chapters = record.data["chapters"]
            fragments = record.data["fragments"]
            if not isinstance(chapters, tuple) or not isinstance(fragments, tuple):
                raise _invalid()
            chapter_by_order: dict[int, Mapping[str, object]] = {}
            for chapter in chapters:
                if not isinstance(chapter, Mapping) or type(chapter.get("chapterOrder")) is not int or chapter["chapterOrder"] in chapter_by_order:
                    raise _invalid()
                chapter_by_order[chapter["chapterOrder"]] = chapter
            seen_fragments: set[tuple[int, int]] = set()
            for fragment in fragments:
                if not isinstance(fragment, Mapping) or type(fragment.get("chapterOrder")) is not int or type(fragment.get("fragmentOrder")) is not int:
                    raise _invalid()
                chapter = chapter_by_order.get(fragment["chapterOrder"])
                key = (fragment["chapterOrder"], fragment["fragmentOrder"])
                if chapter is None or key in seen_fragments:
                    raise _invalid()
                start, end = fragment.get("chapterCharStart"), fragment.get("chapterCharEnd")
                chapter_start, chapter_end = chapter.get("normalizedCharStart"), chapter.get("normalizedCharEnd")
                if any(type(value) is not int for value in (start, end, chapter_start, chapter_end)) or not chapter_start <= start <= end <= chapter_end:
                    raise _invalid()
                seen_fragments.add(key)
        if record.entity_type == "project-contract-head":
            targets = [index.get((kind, record.data.get(field))) for field, kind in (("creationContractLogicalId", "creation-contract"), ("styleContractLogicalId", "style-contract"))]
            if any(target is None for target in targets):
                raise _invalid()
            if "revision" in record.data and any(record.data["revision"] != target.data.get("revision", target.revision) for target in targets if target is not None):
                raise _invalid()
        if record.entity_type == "finalization-record":
            change_set = index.get(("finalization-change-set", record.data.get("changeSetLogicalId")))
            candidate = index.get(("draft-candidate", record.data.get("candidateLogicalId")))
            revisions = [item for item in records if item.entity_type == "finalization-change-set-revision" and item.data.get("changeSetLogicalId") == record.data.get("changeSetLogicalId") and item.data.get("revision", item.revision) == record.data.get("changeSetRevision")]
            if change_set is None or candidate is None or len(revisions) != 1:
                raise _invalid()
            if "candidateHash" in record.data and record.data["candidateHash"] != candidate.data.get("contentHash"):
                raise _invalid()
            if "changeSetHash" in record.data and record.data["changeSetHash"] != revisions[0].data.get("contentHash"):
                raise _invalid()
        if record.entity_type == "final-chapter":
            candidate = index.get(("draft-candidate", record.data.get("candidateLogicalId")))
            finalization = index.get(("finalization-record", record.data.get("finalizationRecordLogicalId")))
            if candidate is None or finalization is None:
                raise _invalid()
            if "contentHash" in record.data and record.data["contentHash"] != candidate.data.get("contentHash"):
                raise _invalid()
        if record.entity_type == "creation-contract-corpus-fragment-ref":
            corpus_id, order = record.data.get("corpusRevisionLogicalId"), record.data.get("fragmentOrder")
            corpus = index.get(("corpus-revision", corpus_id)) if isinstance(corpus_id, str) else None
            fragments = corpus.data.get("fragments") if corpus is not None else None
            matched = [item for item in fragments if isinstance(item, Mapping) and item.get("fragmentOrder") == order] if isinstance(fragments, tuple) else []
            if len(matched) != 1 or ("contentHash" in record.data and record.data["contentHash"] != matched[0].get("contentHash")):
                raise _invalid()
        if record.entity_type != "creation-contract":
            continue
        payload = record.data.get("payload")
        if not isinstance(payload, Mapping):
            continue
        asset_refs = [payload.get("primaryStyleRef"), payload.get("secondaryStyleRef"), *(payload.get("experienceCardRefs", ()) if isinstance(payload.get("experienceCardRefs", ()), tuple) else ())]
        for ref in asset_refs:
            if ref is None:
                continue
            if not isinstance(ref, Mapping) or not isinstance(ref.get("id"), str):
                raise _invalid()
            target = index.get(("asset", ref["id"]))
            if target is None or any(ref.get(key) != target.data.get(key) for key in ("revision", "contentHash") if key in ref):
                raise _invalid()
        binding = payload.get("modelBindingRef")
        if binding is not None and (not isinstance(binding, Mapping) or not isinstance(binding.get("id"), str) or ("project-model-binding-revision", binding["id"]) not in index):
            raise _invalid()
    return index


def _projection(raw: bytes) -> None:
    value = _json(raw)
    try:
        freeze_json_value(value)
    except ProjectPackageSensitiveData:
        raise ProjectImportSensitiveData("project import contains sensitive data") from None
    except Exception:
        raise _invalid() from None
    expected = frozenset({"arcProjections", "currentStateProjections", "memoryViews", "plotThreadProjections", "projectionHeads"})
    _exact_keys(value, expected)
    for item in value.values():
        if not isinstance(item, dict):
            raise _invalid()
        _exact_keys(item, frozenset({"count", "hashes"}))
        hashes = item["hashes"]
        if type(item["count"]) is not int or not isinstance(hashes, list) or item["count"] != len(hashes) or hashes != sorted(hashes) or len(set(hashes)) != len(hashes) or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes):
            raise _invalid()
    if canonical_line(value) != raw:
        raise _invalid()


_READ_CHUNK_BYTES = 64 * 1024


def _member_bytes(archive: zipfile.ZipFile, verified: VerifiedArchiveEntry) -> bytes:
    """Read one declared member through a bounded stream, never ZipFile.read."""
    maximum = MAX_CORPUS_BLOB_BYTES if CORPUS_BLOB_RE.fullmatch(verified.path) else MAX_STRUCTURED_ENTRY_BYTES
    if verified.byte_length > maximum:
        raise _too_large()
    chunks: list[bytes] = []
    total = 0
    try:
        with archive.open(verified.path, "r") as source:
            while True:
                chunk = source.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                if type(chunk) is not bytes or len(chunk) > _READ_CHUNK_BYTES:
                    raise _invalid()
                total += len(chunk)
                if total > verified.byte_length or total > maximum:
                    raise _invalid()
                chunks.append(chunk)
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        raise _invalid() from None
    if total != verified.byte_length:
        raise _invalid()
    return b"".join(chunks)


def _file_hash(path: Path) -> str:
    digest = sha256()
    total = 0
    try:
        with Path(path).open("rb") as source:
            while True:
                chunk = source.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                if type(chunk) is not bytes or len(chunk) > _READ_CHUNK_BYTES:
                    raise _invalid()
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise _too_large()
                digest.update(chunk)
    except (OSError, RuntimeError, ValueError):
        raise _invalid() from None
    return digest.hexdigest()


def _summary(package_hash: str, manifest_hash: str, manifest: ProjectPackageManifest, records: tuple[PackageRecord, ...]) -> ProjectImportSummary:
    projects = [record for record in records if record.entity_type == "project"]
    if len(projects) != 1 or projects[0].logical_id != manifest.project_logical_id:
        raise _invalid()
    title = projects[0].data.get("title", projects[0].data.get("label"))
    if not isinstance(title, str) or not title:
        raise _invalid()
    source = title
    suffix = "（导入）"
    proposed = source[: 200 - len(suffix)] + suffix
    actual = {kind: sum(record.entity_type == kind for record in records) for kind in sorted({r.entity_type for r in records})}
    if dict(manifest.counts) != actual:
        raise _invalid()
    return ProjectImportSummary(package_hash, manifest_hash, PACKAGE_VERSION, source, proposed, MappingProxyType(actual), any(r.entity_type == "final-chapter" for r in records), actual.get("provider-history", 0))


def read_verified_project_package(path: Path) -> VerifiedProjectPackage:
    """Authenticate and preflight one archive without extraction or side effects."""
    try:
        entries = verify_raw_zip_envelope(Path(path))
        by_path = {entry.path: entry for entry in entries}
        if (
            len(by_path) != len(entries)
            or tuple(entry.path for entry in entries) != tuple(sorted(by_path))
            or MANIFEST_PATH not in by_path
            or MANIFEST_HASH_PATH not in by_path
        ):
            raise _invalid()
        with zipfile.ZipFile(path, "r", allowZip64=False) as archive:
            manifest_raw = _member_bytes(archive, by_path[MANIFEST_PATH])
            manifest_hash_raw = _member_bytes(archive, by_path[MANIFEST_HASH_PATH])
            manifest = _manifest(manifest_raw, manifest_hash_raw)
            declared = {entry.path: entry for entry in manifest.entries}
            fixed_payloads = frozenset(PAYLOAD_PATHS)
            if (
                not fixed_payloads.issubset(declared)
                or any(path not in fixed_payloads and CORPUS_BLOB_RE.fullmatch(path) is None for path in declared)
                or set(by_path) != set(declared) | {MANIFEST_PATH, MANIFEST_HASH_PATH}
            ):
                raise _invalid()
            for item in manifest.entries:
                actual = by_path.get(item.path)
                if actual is None or actual.byte_length != item.byte_length or actual.sha256 != item.sha256:
                    raise _invalid()
                if CORPUS_BLOB_RE.fullmatch(item.path) and item.path.rsplit("/", 1)[-1] != actual.sha256:
                    raise _invalid()
            records: list[PackageRecord] = []
            expected_types = {
                "assets/frozen.jsonl": {"asset"}, "corpus/revisions.jsonl": {"corpus-revision"},
                "history/operations.jsonl": {"operation", "operation-event"}, "history/providers.jsonl": {"provider-history"},
                "project/graph.jsonl": set(all_v1_record_types()) - {"asset", "corpus-revision", "operation", "operation-event", "provider-history"},
            }
            for entry in manifest.entries:
                if entry.path.endswith(".jsonl"):
                    parsed = _stream_records(archive, by_path[entry.path])
                    if entry.path in expected_types and any(record.entity_type not in expected_types[entry.path] for record in parsed):
                        raise _invalid()
                    records.extend(parsed)
                elif entry.path == "validation/projections.json":
                    _projection(_member_bytes(archive, by_path[entry.path]))
                elif not CORPUS_BLOB_RE.fullmatch(entry.path):
                    raise _invalid()
        all_records = tuple(records)
        index = _validate_graph(all_records)
        for record in all_records:
            if record.entity_type != "corpus-revision":
                continue
            content_hash = record.data.get("contentHash")
            byte_length = record.data.get("byteLength")
            blob = by_path.get(f"corpus/blobs/sha256/{content_hash}") if isinstance(content_hash, str) else None
            if re.fullmatch(r"[0-9a-f]{64}", content_hash or "") is None or blob is None or type(byte_length) is not int or byte_length < 0 or blob.byte_length != byte_length or blob.sha256 != content_hash:
                raise _invalid()
        package_hash = _file_hash(Path(path))
        manifest_hash = sha256(manifest_raw).hexdigest()
        return VerifiedProjectPackage(Path(path), package_hash, manifest_hash, manifest, MappingProxyType(index), MappingProxyType(by_path), _summary(package_hash, manifest_hash, manifest, all_records))
    except (ProjectImportInvalid, ProjectImportTooLarge, ProjectImportSensitiveData):
        raise
    except ProjectPackageSensitiveData:
        raise ProjectImportSensitiveData("project import contains sensitive data") from None
    except (OSError, ValueError, zipfile.BadZipFile):
        raise _invalid() from None
