"""Read-only, deterministic preflight for Phase 6 project packages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType
import zipfile

from backend.domain.project_imports import ProjectImportInvalid, ProjectImportSensitiveData, ProjectImportTooLarge
from backend.domain.project_packages import (
    HASH_ALGORITHM, MANIFEST_HASH_PATH, MANIFEST_PATH, MAX_ARCHIVE_BYTES, MAX_CORPUS_BLOB_BYTES,
    MAX_ENTRY_COUNT, MAX_STRUCTURED_ENTRY_BYTES, PACKAGE_FORMAT, PACKAGE_VERSION, PAYLOAD_PATHS,
    RECORD_FIELD_ALLOWLISTS, ManifestEntry, PackageRecord,
    ProjectPackageManifest, ProjectPackageSensitiveData, canonical_line, freeze_json_value, record_sort_key, validate_json_depth,
)
from backend.security.project_import_archives import VerifiedArchiveEntry, verify_raw_zip_envelope
from backend.security.project_package_paths import CORPUS_BLOB_RE


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
    "project-chapter-outline-head", "chapter-outline-confirmation", "chapter", "working-draft", "draft-candidate", "candidate-freeze",
    "finalization-change-set", "finalization-change-set-revision", "finalization-record", "final-chapter",
    "canon-entity", "entity-alias", "canon-revision", "canon-event",
})
RECONSTRUCTED_ENTITY_TYPES = frozenset({"project-model-binding-revision", "project-model-binding-item", "project-model-binding-head", "asset", "corpus-revision"})
PROVENANCE_ENTITY_TYPES = frozenset({
    "market-analysis", "seed-inspiration-history", "asset-recommendation-history", "style-trial-history",
    "story-engine-batch", "bible-generation-history", "planning-generation-history",
    "chapter-outline-generation-history", "operation", "operation-event", "working-draft-revision", "candidate-quality",
    "provider-history",
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
    "project-contract-head": {"creationContractLogicalId": frozenset({"creation-contract"}), "styleContractLogicalId": frozenset({"style-contract"})},
    "creation-contract-engine-ref": {"creationContractLogicalId": frozenset({"creation-contract"}), "storyEngineLogicalId": frozenset({"story-engine-option"})},
    "creation-contract-corpus-ref": {"creationContractLogicalId": frozenset({"creation-contract"}), "corpusRevisionLogicalId": frozenset({"corpus-revision"})},
    "creation-contract-corpus-fragment-ref": {"creationContractLogicalId": frozenset({"creation-contract"}), "corpusRevisionLogicalId": frozenset({"corpus-revision"})},
    "project-bible-head": {"bibleRevisionLogicalId": frozenset({"creation-bible-revision"})},
    "planning-revision": {"seedLogicalId": frozenset({"creative-seed"}), "seedRevisionLogicalId": frozenset({"creative-seed-revision"}), "creationContractLogicalId": frozenset({"creation-contract"}), "styleContractLogicalId": frozenset({"style-contract"}), "bibleRevisionLogicalId": frozenset({"creation-bible-revision"})},
    "project-planning-head": {"planningRevisionLogicalId": frozenset({"planning-revision"})},
    "chapter-outline-revision": {"planningRevisionLogicalId": frozenset({"planning-revision"})},
    "project-chapter-outline-head": {"outlineRevisionLogicalId": frozenset({"chapter-outline-revision"})},
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
    "reference-use": {"chapterLogicalId": frozenset({"chapter"}), "candidateLogicalId": frozenset({"draft-candidate"}), "corpusRevisionLogicalId": frozenset({"corpus-revision"})},
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
    "chapter": (("planningRevisionLogicalId", "planning-revision", "planningRevision", "planningHash"), ("outlineRevisionLogicalId", "chapter-outline-revision", "chapterOutlineRevision", "chapterOutlineHash")),
    "final-chapter": (("planningRevisionLogicalId", "planning-revision", "planningRevision", "planningHash"), ("outlineRevisionLogicalId", "chapter-outline-revision", "chapterOutlineRevision", "chapterOutlineHash")),
}

_REQUIRED_CLOSURE_FIELDS: Mapping[str, frozenset[str]] = {
    "planning-revision": frozenset({"revision", "contentHash", "seedLogicalId", "seedRevisionLogicalId", "seedHash", "creationContractLogicalId", "creationHash", "styleContractLogicalId", "styleHash", "bibleRevisionLogicalId", "bibleHash"}),
    "chapter": frozenset({"planningRevisionLogicalId", "planningRevision", "planningHash", "outlineRevisionLogicalId", "chapterOutlineRevision", "chapterOutlineHash", "storyBlockLogicalId", "storyBlockRevision", "storyBlockHash"}),
    "final-chapter": frozenset({"finalizationRecordLogicalId", "planningRevisionLogicalId", "planningRevision", "planningHash", "outlineRevisionLogicalId", "chapterOutlineRevision", "chapterOutlineHash", "candidateLogicalId", "contentHash", "canonRevision"}),
    "corpus-revision": frozenset({"contentHash", "byteLength", "chapters", "fragments"}),
}

_OPTIONAL_REF_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType({
    "project-model-binding-revision": frozenset({"sourceProjectLogicalId"}),
    "working-draft-revision": frozenset({"candidateLogicalId", "operationLogicalId"}),
    "canon-revision": frozenset({"sourceLogicalId"}),
    "provider-history": frozenset({"operationLogicalId"}),
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
            if identity in index or identity in embedded:
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
        if record.entity_type == "final-chapter" and record.data.get("canonRevision") is not None and not isinstance(record.data["canonRevision"], int):
            raise _invalid()
        if record.entity_type == "planning-revision":
            for logical_field, target_type, hash_field in (("seedRevisionLogicalId", "creative-seed-revision", "seedHash"), ("creationContractLogicalId", "creation-contract", "creationHash"), ("styleContractLogicalId", "style-contract", "styleHash"), ("bibleRevisionLogicalId", "creation-bible-revision", "bibleHash")):
                target = index.get((target_type, record.data[logical_field]))
                if target is None or record.data[hash_field] != target.data.get("contentHash"):
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
        keys = tuple(item.data.get("taskKey") for item in sorted(items, key=lambda item: item.order))
        if keys != TASK_KEYS or len({item.logical_id for item in items}) != len(TASK_KEYS):
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
