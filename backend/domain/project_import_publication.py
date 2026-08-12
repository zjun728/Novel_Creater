"""DDL-precise, side-effect-free publication batch encoders."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias
from uuid import UUID, uuid5

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_packages import PackageRecord, thaw_json_value
from backend.security.paths import managed_corpus_storage_key


JsonPrimitive: TypeAlias = str | int | float | bool | None


def _invalid() -> ProjectImportInvalid:
    return ProjectImportInvalid("invalid project import archive")


def corpus_source_target_id(command_id: str, source_key: str) -> str:
    """Return the target-local identity used by every reconstructed corpus source row."""
    try:
        if not isinstance(source_key, str) or not source_key:
            raise ValueError
        return str(uuid5(UUID(command_id), f"corpus-source/{source_key}"))
    except (TypeError, ValueError, AttributeError):
        raise _invalid() from None


@dataclass(frozen=True, slots=True)
class EncodedBatch:
    table: str
    columns: tuple[str, ...]
    rows: tuple[tuple[JsonPrimitive, ...], ...]


@dataclass(frozen=True, slots=True)
class PublicationEncodingContext:
    command_id: str
    target_project_id: str
    new_title: str
    records: Mapping[tuple[str, str], PackageRecord]
    rewritten: Mapping[tuple[str, str], Mapping[str, object]]
    ids: Mapping[tuple[str, str], str]


def _derived_hash(context: PublicationEncodingContext, purpose: str, authority: object) -> str:
    return canonical_hash({
        "commandId": context.command_id,
        "purpose": purpose,
        "authority": authority,
    })


def _record_by_target_id(
    context: PublicationEncodingContext,
    entity_type: str,
    target_id: object,
) -> tuple[tuple[str, str], Mapping[str, object]]:
    matches = [
        (key, data) for key, data in context.rewritten.items()
        if key[0] == entity_type and context.ids.get(key) == target_id
    ]
    if len(matches) != 1:
        raise _invalid()
    return matches[0]


def _selection_revision(context: PublicationEncodingContext, revision: object) -> Mapping[str, object]:
    historical = [data for (kind, _), data in context.rewritten.items() if kind == "project-seed-selection-revision" and data.get("selectionRevision") == revision]
    if len(historical) == 1:
        return historical[0]
    selected = [data for (kind, _), data in context.rewritten.items() if kind == "project-selected-seed" and data.get("selectionRevision") == revision]
    if len(historical) == 0 and len(selected) == 1:
        return selected[0]
    raise _invalid()


RecordEncoder: TypeAlias = Callable[[PackageRecord, Mapping[str, object], PublicationEncodingContext], tuple[EncodedBatch, ...]]


def _required(data: Mapping[str, object], key: str) -> JsonPrimitive:
    value = data.get(key)
    if value is None or type(value) not in {str, int, float, bool}:
        raise _invalid()
    return value  # type: ignore[return-value]


def _nullable(data: Mapping[str, object], key: str) -> JsonPrimitive:
    value = data.get(key)
    if value is None or type(value) in {str, int, float, bool}:
        return value  # type: ignore[return-value]
    raise _invalid()


def _json_value(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, (Mapping, list, tuple)):
        raise _invalid()
    try:
        return canonical_json(thaw_json_value(value))  # type: ignore[arg-type]
    except Exception:
        raise _invalid() from None


def _json_any(data: Mapping[str, object], key: str) -> str:
    if key not in data:
        raise _invalid()
    try:
        return canonical_json(thaw_json_value(data[key]))  # type: ignore[arg-type]
    except Exception:
        raise _invalid() from None


def _project(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = (
        "id", "title", "genre", "description", "target_words", "target_chapters",
        "status", "current_chapter", "archived_at", "lifecycle_revision", "created_at", "updated_at",
    )
    row = (
        context.target_project_id, context.new_title, _required(data, "genre"), _required(data, "description"),
        _required(data, "targetWords"), _required(data, "targetChapters"), _required(data, "status"),
        _required(data, "currentChapter"), _nullable(data, "archivedAt"), _required(data, "lifecycleRevision"),
        _required(data, "createdAt"), _required(data, "updatedAt"),
    )
    return (EncodedBatch("projects", columns, (row,)),)


def _binding_revision(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "revision", "content_hash", "source_project_id", "created_at")
    row = (
        context.ids[(record.entity_type, record.logical_id)], context.target_project_id,
        _required(data, "revision"), _required(data, "contentHash"),
        _nullable(data, "sourceProjectLogicalId"), _required(data, "createdAt"),
    )
    return (EncodedBatch("project_model_binding_revisions", columns, (row,)),)


def _binding_item(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = (
        "binding_revision_id", "task_key", "resolution_status", "provider_id",
        "provider_name_snapshot", "model_name_snapshot", "item_hash",
    )
    row = (
        _required(data, "bindingRevisionLogicalId"), _required(data, "taskKey"),
        _required(data, "resolutionStatus"), _nullable(data, "providerId"),
        _nullable(data, "providerName"), _nullable(data, "modelName"), _required(data, "itemHash"),
    )
    return (EncodedBatch("project_model_binding_items", columns, (row,)),)


def _binding_head(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("project_id", "revision", "binding_revision_id", "content_hash", "updated_at")
    row = (
        context.target_project_id, _required(data, "revision"), _required(data, "bindingRevisionLogicalId"),
        _required(data, "contentHash"), _required(data, "updatedAt"),
    )
    return (EncodedBatch("project_model_binding_heads", columns, (row,)),)


def _creative_seed(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "status", "created_at", "updated_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "status"), _required(data, "createdAt"), _required(data, "updatedAt"))
    return (EncodedBatch("creative_seeds", columns, (row,)),)


def _creative_seed_revision(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "seed_id", "revision", "payload_json", "content_hash", "created_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "seedLogicalId"), _required(data, "revision"), _json_value(data, "payload"), _required(data, "contentHash"), _required(data, "createdAt"))
    return (EncodedBatch("creative_seed_revisions", columns, (row,)),)


def _creative_seed_head(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("seed_id", "revision_id", "revision", "content_hash", "updated_at")
    row = (_required(data, "seedLogicalId"), _required(data, "revisionLogicalId"), _required(data, "revision"), _required(data, "contentHash"), _required(data, "updatedAt"))
    return (EncodedBatch("creative_seed_heads", columns, (row,)),)


def _seed_selection_revision(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("project_id", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "selected_at")
    row = (context.target_project_id, _required(data, "selectionRevision"), _required(data, "seedLogicalId"), _required(data, "seedRevisionLogicalId"), _required(data, "seedHash"), _required(data, "selectedAt"))
    return (EncodedBatch("project_seed_selection_revisions", columns, (row,)),)


def _selected_seed(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("project_id", "seed_id", "seed_revision_id", "seed_hash", "selection_revision", "selected_at", "updated_at")
    row = (context.target_project_id, _required(data, "seedLogicalId"), _required(data, "seedRevisionLogicalId"), _required(data, "seedHash"), _required(data, "selectionRevision"), _required(data, "selectedAt"), _required(data, "updatedAt"))
    return (EncodedBatch("project_selected_seeds", columns, (row,)),)


def _story_engine_option(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    batch_logical_id = record.data.get("batchLogicalId")
    if not isinstance(batch_logical_id, str):
        raise _invalid()
    batch_id = context.ids.get(("story-engine-batch", batch_logical_id))
    source_batch = context.records.get(("story-engine-batch", batch_logical_id))
    if batch_id is None or source_batch is None:
        raise _invalid()
    peers = [
        item for item in context.records.values()
        if item.entity_type == "story-engine-option" and item.data.get("batchLogicalId") == batch_logical_id
    ]
    selected = _selection_revision(context, data.get("selectionRevision"))
    if not peers or min((item.order, item.logical_id) for item in peers) != (record.order, record.logical_id):
        batch = ()
    else:
        selection_revision = selected.get("selectionRevision")
        created_at = _required(data, "createdAt")
        authority = {
            "batchLogicalId": batch_logical_id,
            "selectionRevision": selection_revision,
            "seedId": selected.get("seedLogicalId"),
            "seedRevisionId": selected.get("seedRevisionLogicalId"),
            "seedHash": selected.get("seedHash"),
        }
        columns = (
            "id", "project_id", "selection_revision", "source_type", "seed_id", "seed_revision_id",
            "seed_hash", "binding_revision_id", "binding_hash", "provider_id", "model_name_snapshot",
            "idempotency_key", "request_json", "request_hash", "status", "attempt_id", "attempt_started_at",
            "lease_expires_at", "raw_response_text", "raw_response_hash", "public_error_code", "created_at", "finished_at",
        )
        batch = (EncodedBatch("story_engine_batches", columns, ((
            batch_id, context.target_project_id, selection_revision, "manual", _required(selected, "seedLogicalId"),
            _required(selected, "seedRevisionLogicalId"), _required(selected, "seedHash"), None, None, None, None,
            _derived_hash(context, "story-engine-batch/idempotency", authority), "{}",
            _derived_hash(context, "story-engine-batch/request", authority), "succeeded", None, None, None,
            None, None, None, created_at, created_at,
        ),)),)
    option_columns = ("id", "project_id", "selection_revision", "batch_id", "option_order", "payload_json", "content_hash", "created_at")
    option_row = (
        context.ids[(record.entity_type, record.logical_id)], context.target_project_id,
        _required(selected, "selectionRevision"), batch_id, _required(data, "optionOrder"),
        _json_value(data, "payload"), _required(data, "contentHash"), _required(data, "createdAt"),
    )
    return batch + (EncodedBatch("story_engine_options", option_columns, (option_row,)),)


def _asset(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    kind = data.get("assetKind")
    target_id = context.ids[(record.entity_type, record.logical_id)]
    stable_key = f"import/{uuid5(UUID(context.command_id), record.entity_type + '/' + record.logical_id)}"
    if kind == "style-template":
        columns = ("id", "stable_key", "revision", "name", "payload_json", "provenance_json", "content_hash", "status", "created_at")
        row = (
            target_id, stable_key, _required(data, "revision"), _required(data, "name"),
            _json_value(data, "payload"), _json_value(data, "provenance"), _required(data, "contentHash"),
            _required(data, "status"), _required(data, "createdAt"),
        )
        return (EncodedBatch("style_templates", columns, (row,)),)
    if kind == "experience-card":
        columns = ("id", "stable_key", "revision", "title", "category", "payload_json", "provenance_json", "content_hash", "status", "created_at")
        row = (
            target_id, stable_key, _required(data, "revision"), _required(data, "name"),
            _required(data, "category"), _json_value(data, "payload"), _json_value(data, "provenance"),
            _required(data, "contentHash"), _required(data, "status"), _required(data, "createdAt"),
        )
        return (EncodedBatch("experience_cards", columns, (row,)),)
    raise _invalid()


def _corpus(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    revision_id = context.ids[(record.entity_type, record.logical_id)]
    raw_source_key = _required(data, "sourceKey")
    source_id = str(uuid5(UUID(context.command_id), f"corpus-source/{raw_source_key}"))
    source_key = f"import:{uuid5(UUID(context.command_id), f'corpus-source-key/{raw_source_key}')}"
    created_at = _required(data, "createdAt")
    content_hash = _required(data, "contentHash")
    revision = _required(data, "revision")
    batches = [
        EncodedBatch("corpus_blobs", ("content_hash", "byte_length", "storage_key", "created_at"), ((content_hash, _required(data, "byteLength"), managed_corpus_storage_key(content_hash), created_at),)),
        EncodedBatch("corpus_sources", ("id", "source_key", "archived_at", "created_at", "updated_at"), ((source_id, source_key, None, created_at, created_at),)),
        EncodedBatch("corpus_source_revisions", (
            "id", "source_id", "revision", "content_hash", "relative_path", "display_name", "author",
            "reference_tags_json", "notes", "provenance_json", "byte_length", "encoding", "parser_version",
            "normalizer_version", "fragmenter_version", "index_version", "status", "public_error_code",
            "imported_at", "analyzed_at", "created_at",
        ), ((
            revision_id, source_id, revision, content_hash, _required(data, "relativePath"), _required(data, "displayName"),
            _required(data, "author"), _json_value(data, "referenceTags"), _required(data, "notes"),
            _json_value(data, "provenance"), _required(data, "byteLength"), _required(data, "encoding"),
            _required(data, "parserVersion"), _required(data, "normalizerVersion"), _required(data, "fragmenterVersion"),
            _required(data, "indexVersion"), _required(data, "status"), None, _required(data, "importedAt"),
            _nullable(data, "analyzedAt"), created_at,
        ),)),
    ]
    chapters = data.get("chapters")
    fragments = data.get("fragments")
    if not isinstance(chapters, list) or not isinstance(fragments, list):
        raise _invalid()
    chapter_ids: dict[int, str] = {}
    chapter_rows: list[tuple[JsonPrimitive, ...]] = []
    for chapter in chapters:
        if not isinstance(chapter, Mapping):
            raise _invalid()
        order = _required(chapter, "chapterOrder")
        if type(order) is not int:
            raise _invalid()
        chapter_id = _required(chapter, "logicalId")
        if type(chapter_id) is not str:
            raise _invalid()
        chapter_ids[order] = chapter_id
        chapter_rows.append((
            chapter_id, source_id, revision_id, revision, content_hash, order, _required(chapter, "title"),
            _required(chapter, "rawByteStart"), _required(chapter, "rawByteEnd"), _required(chapter, "normalizedCharStart"),
            _required(chapter, "normalizedCharEnd"), _required(chapter, "normalizedText"), _required(chapter, "contentHash"),
            _required(chapter, "createdAt"),
        ))
    if chapter_rows:
        batches.append(EncodedBatch("corpus_chapters", (
            "id", "corpus_source_id", "source_revision_id", "source_revision", "source_hash", "chapter_order",
            "title", "raw_byte_start", "raw_byte_end", "normalized_char_start", "normalized_char_end",
            "normalized_text", "content_hash", "created_at",
        ), tuple(chapter_rows)))
    fragment_rows: list[tuple[JsonPrimitive, ...]] = []
    for fragment in fragments:
        if not isinstance(fragment, Mapping):
            raise _invalid()
        order = _required(fragment, "chapterOrder")
        if type(order) is not int or order not in chapter_ids:
            raise _invalid()
        fragment_rows.append((
            _required(fragment, "logicalId"), source_id, chapter_ids[order], _required(fragment, "fragmentOrder"),
            _required(fragment, "chapterCharStart"), _required(fragment, "chapterCharEnd"),
            _required(fragment, "normalizedText"), _required(fragment, "contentHash"), _json_value(fragment, "indexPayload"),
            _required(fragment, "analysisVersion"), _required(fragment, "createdAt"),
        ))
    if fragment_rows:
        batches.append(EncodedBatch("corpus_fragments", (
            "id", "corpus_source_id", "corpus_chapter_id", "fragment_order", "chapter_char_start",
            "chapter_char_end", "normalized_text", "content_hash", "index_payload", "analysis_version", "created_at",
        ), tuple(fragment_rows)))
    return tuple(batches)


def _style_contract(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    payload = data.get("payload")
    if not isinstance(payload, Mapping):
        raise _invalid()
    columns = ("id", "project_id", "creation_contract_id", "revision", "merged_style_json", "likes_json", "dislikes_json", "content_hash", "confirmed_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id,
           _required(data, "creationContractLogicalId"), _required(data, "revision"),
           canonical_json(thaw_json_value(payload.get("mergedStyle"))), canonical_json(thaw_json_value(payload.get("likes"))),
           canonical_json(thaw_json_value(payload.get("dislikes"))), _required(data, "contentHash"), _required(data, "createdAt"))
    return (EncodedBatch("style_contracts", columns, (row,)),)


def _contract_head(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("project_id", "revision", "creation_contract_id", "style_contract_id", "creation_hash", "style_hash", "updated_at")
    row = (context.target_project_id, _required(data, "revision"), _required(data, "creationContractLogicalId"),
           _required(data, "styleContractLogicalId"), _required(data, "creationHash"), _required(data, "styleHash"), _required(data, "updatedAt"))
    return (EncodedBatch("project_contract_heads", columns, (row,)),)


def _bible_revision(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "binding_revision_id", "binding_hash", "policy_version", "content_json", "content_hash", "confirmed_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "revision"),
           _required(data, "selectionRevision"), _required(data, "seedLogicalId"), _required(data, "seedRevisionLogicalId"),
           _required(data, "seedHash"), _required(data, "contractRevision"), _required(data, "creationContractLogicalId"),
           _required(data, "creationHash"), _required(data, "styleContractLogicalId"), _required(data, "styleHash"),
           _nullable(data, "bindingRevisionLogicalId"), _nullable(data, "bindingHash"), _required(data, "policyVersion"), _json_value(data, "payload"),
           _required(data, "contentHash"), _required(data, "createdAt"))
    return (EncodedBatch("creation_bible_revisions", columns, (row,)),)


def _bible_head(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("project_id", "revision", "bible_revision_id", "content_hash", "updated_at")
    return (EncodedBatch("project_bible_heads", columns, ((context.target_project_id, _required(data, "revision"), _required(data, "bibleRevisionLogicalId"), _required(data, "contentHash"), _required(data, "updatedAt")),)),)


def _planning_revision(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "revision", "parent_revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "bible_revision", "bible_revision_id", "bible_hash", "content_json", "content_hash", "created_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "revision"), _required(data, "parentRevision"),
           _required(data, "selectionRevision"), _required(data, "seedLogicalId"), _required(data, "seedRevisionLogicalId"), _required(data, "seedHash"),
           _required(data, "contractRevision"), _required(data, "creationContractLogicalId"), _required(data, "creationHash"), _required(data, "styleContractLogicalId"),
           _required(data, "styleHash"), _required(data, "bibleRevision"), _required(data, "bibleRevisionLogicalId"), _required(data, "bibleHash"),
           _json_value(data, "payload"), _required(data, "contentHash"), _required(data, "createdAt"))
    return (EncodedBatch("planning_revisions", columns, (row,)),)


def _planning_head(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("project_id", "revision", "planning_revision_id", "content_hash", "updated_at")
    return (EncodedBatch("project_planning_heads", columns, ((context.target_project_id, _required(data, "revision"), _required(data, "planningRevisionLogicalId"), _required(data, "contentHash"), _required(data, "updatedAt")),)),)


def _outline_revision(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    payload = data.get("payload")
    if not isinstance(payload, Mapping):
        raise _invalid()
    columns = ("id", "project_id", "chapter_num", "revision", "parent_revision", "planning_revision_id", "planning_revision", "planning_hash", "canon_revision", "projection_revision", "projection_hash", "content_json", "content_hash", "created_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterNumber"), _required(data, "revision"),
           payload.get("parentRevision", 0), _required(data, "planningRevisionLogicalId"), _required(payload, "planningRevision"), _required(payload, "planningHash"),
           _required(payload, "canonRevision"), _required(payload, "projectionRevision"), _required(payload, "projectionHash"), _json_value(data, "payload"),
           _required(data, "contentHash"), _required(data, "createdAt"))
    return (EncodedBatch("chapter_outline_revisions", columns, (row,)),)


def _outline_head(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("project_id", "chapter_num", "revision", "outline_revision_id", "content_hash", "updated_at")
    return (EncodedBatch("project_chapter_outline_heads", columns, ((context.target_project_id, _required(data, "chapterNumber"), _required(data, "revision"), _required(data, "outlineRevisionLogicalId"), _required(data, "contentHash"), _required(data, "updatedAt")),)),)


def _canon_entity(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "entity_type", "canonical_name", "normalized_name", "created_revision", "created_at")
    return (EncodedBatch("canon_entities", columns, ((context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "entityType"), _required(data, "canonicalName"), _required(data, "normalizedName"), _required(data, "createdRevision"), _required(data, "createdAt")),)),)


def _entity_alias(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "entity_id", "alias", "normalized_alias", "created_revision", "created_at")
    return (EncodedBatch("entity_aliases", columns, ((context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "entityLogicalId"), _required(data, "alias"), _required(data, "normalizedAlias"), _required(data, "createdRevision"), _required(data, "createdAt")),)),)


def _canon_revision(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "revision_number", "parent_revision_number", "idempotency_key", "source_type", "source_id", "content_hash", "created_at")
    authority = {"logicalId": record.logical_id, "revisionNumber": data.get("revisionNumber"), "contentHash": data.get("contentHash")}
    return (EncodedBatch("canon_revisions", columns, ((context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "revisionNumber"), _required(data, "parentRevisionNumber"), _derived_hash(context, "canon-revision/idempotency", authority), _required(data, "sourceType"), _nullable(data, "sourceLogicalId"), _required(data, "contentHash"), _required(data, "createdAt")),)),)


def _canon_event(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "revision_id", "revision_number", "event_order", "entity_id", "fact_kind", "field_path", "value_json", "evidence_json", "effective_start_chapter", "effective_end_chapter", "assertion_operator", "value_cardinality", "confirmation_status", "created_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "canonRevisionLogicalId"), _required(data, "revisionNumber"), _required(data, "eventOrder"), _nullable(data, "entityLogicalId"), _required(data, "factKind"), _required(data, "fieldPath"), _json_any(data, "value"), _json_any(data, "evidence"), _nullable(data, "effectiveStartChapter"), _nullable(data, "effectiveEndChapter"), _required(data, "assertionOperator"), _required(data, "valueCardinality"), _required(data, "confirmationStatus"), _required(data, "createdAt"))
    return (EncodedBatch("canon_events", columns, (row,)),)


def _chapter(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "planning_revision_id", "planning_revision", "planning_hash", "story_block_id", "story_block_revision", "story_block_hash", "chapter_outline_revision_id", "chapter_outline_revision", "chapter_outline_hash", "chapter_num", "expected_canon_revision", "status", "draft_operation_fencing_token", "active_draft_operation_id", "created_at", "finalized_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "planningRevisionLogicalId"), _required(data, "planningRevision"), _required(data, "planningHash"), _required(data, "storyBlockLogicalId"), _required(data, "storyBlockRevision"), _required(data, "storyBlockHash"), _required(data, "outlineRevisionLogicalId"), _required(data, "chapterOutlineRevision"), _required(data, "chapterOutlineHash"), _required(data, "chapterNumber"), _required(data, "expectedCanonRevision"), _required(data, "status"), 0, None, _required(data, "createdAt"), _nullable(data, "finalizedAt"))
    return (EncodedBatch("chapter_sessions", columns, (row,)),)


def _working_draft(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "chapter_session_id", "revision", "content", "content_hash", "source_payload_json", "updated_at")
    return (EncodedBatch("working_drafts", columns, ((context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterLogicalId"), _required(data, "revision"), _required(data, "content"), _required(data, "contentHash"), "{}", _required(data, "updatedAt")),)),)


def _draft_candidate(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "chapter_session_id", "working_draft_revision", "content", "content_hash", "basis_hash", "provenance_json", "created_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterLogicalId"), _required(data, "workingDraftRevision"), _required(data, "content"), _required(data, "contentHash"), _required(data, "basisHash"), _json_value(data, "provenance"), _required(data, "createdAt"))
    return (EncodedBatch("draft_candidates", columns, (row,)),)


def _candidate_quality(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "chapter_session_id", "draft_candidate_id", "candidate_hash", "expected_canon_revision", "expected_planning_hash", "expected_outline_hash", "policy_version", "context_manifest_hash", "provider_id", "provider_profile_revision", "model_name_snapshot", "status", "deterministic_blocks_json", "findings_json", "content_hash", "created_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterLogicalId"), _required(data, "candidateLogicalId"), _required(data, "candidateHash"), _required(data, "expectedCanonRevision"), _required(data, "expectedPlanningHash"), _required(data, "expectedOutlineHash"), _required(data, "policyVersion"), _required(data, "contextManifestHash"), None, None, None, _required(data, "status"), _json_value(data, "deterministicBlocks"), _json_value(data, "findings"), _required(data, "contentHash"), _required(data, "createdAt"))
    return (EncodedBatch("candidate_quality_reports", columns, (row,)),)


def _change_set_revision(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "change_set_id", "revision", "payload_json", "content_hash", "source", "created_at")
    return (EncodedBatch("finalization_change_set_revisions", columns, ((context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "changeSetLogicalId"), _required(data, "revision"), _json_value(data, "payload"), _required(data, "contentHash"), _required(data, "source"), _required(data, "createdAt")),)),)


def _change_set(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    quality = [item for (kind, _), item in context.rewritten.items() if kind == "candidate-quality" and item.get("candidateLogicalId") == data.get("candidateLogicalId")]
    revisions = [item for (kind, _), item in context.rewritten.items() if kind == "finalization-change-set-revision" and item.get("changeSetLogicalId") == context.ids[(record.entity_type, record.logical_id)]]
    chapter_matches = [item for key, item in context.rewritten.items() if key[0] == "chapter" and context.ids.get(key) == data.get("chapterLogicalId")]
    if len(quality) != 1 or not revisions or len(chapter_matches) != 1:
        raise _invalid()
    chapter = chapter_matches[0]
    latest = max(revisions, key=lambda item: int(item.get("revision", 0)))
    manifest: dict[str, object] = {}
    authority = {"logicalId": record.logical_id, "candidateHash": data.get("candidateHash"), "contentHash": data.get("contentHash")}
    columns = ("id", "project_id", "chapter_session_id", "draft_candidate_id", "quality_report_id", "extraction_id", "idempotency_key", "request_fingerprint", "active_slot", "candidate_hash", "expected_canon_revision", "expected_planning_hash", "expected_outline_hash", "context_manifest_json", "context_manifest_hash", "status", "current_revision", "current_revision_hash", "confirmed_revision", "confirmed_revision_hash", "created_at", "updated_at", "confirmed_at")
    quality_matches = [context.ids[key] for key, item in context.rewritten.items() if key[0] == "candidate-quality" and item is quality[0]]
    if len(quality_matches) != 1:
        raise _invalid()
    quality_id = quality_matches[0]
    committed = any(
        item.entity_type == "finalization-record" and item.data.get("changeSetLogicalId") == record.logical_id
        for item in context.records.values()
    )
    status = "committed" if committed else "awaiting_author"
    extraction_id = str(uuid5(
        UUID(context.command_id),
        f"finalization-extraction/{record.logical_id}",
    ))
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterLogicalId"), _required(data, "candidateLogicalId"), quality_id, extraction_id, _derived_hash(context, "finalization-change-set/idempotency", authority), _derived_hash(context, "finalization-change-set/request", authority), None, _required(data, "candidateHash"), _required(chapter, "expectedCanonRevision"), _required(quality[0], "expectedPlanningHash"), _required(quality[0], "expectedOutlineHash"), canonical_json(manifest), canonical_hash(manifest), status, _required(latest, "revision"), _required(latest, "contentHash"), _required(latest, "revision") if data.get("confirmedAt") is not None else None, _required(latest, "contentHash") if data.get("confirmedAt") is not None else None, _required(data, "createdAt"), _required(data, "updatedAt"), _nullable(data, "confirmedAt"))
    return (EncodedBatch("finalization_change_sets", columns, (row,)),)


def _finalization_record(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    authority = {"logicalId": record.logical_id, "resultHash": data.get("resultHash")}
    columns = ("id", "project_id", "chapter_session_id", "draft_candidate_id", "change_set_id", "change_set_revision", "idempotency_key", "request_fingerprint", "candidate_hash", "change_set_hash", "expected_canon_revision", "committed_canon_revision", "result_payload_json", "finalized_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterLogicalId"), _required(data, "candidateLogicalId"), _required(data, "changeSetLogicalId"), _required(data, "changeSetRevision"), _derived_hash(context, "finalization-record/idempotency", authority), _derived_hash(context, "finalization-record/request", authority), _required(data, "candidateHash"), _required(data, "changeSetHash"), _required(data, "expectedCanonRevision"), _required(data, "committedCanonRevision"), _json_value(data, "resultPayload"), _required(data, "finalizedAt"))
    return (EncodedBatch("finalization_records", columns, (row,)),)


def _final_chapter(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "chapter_session_id", "draft_candidate_id", "finalization_record_id", "chapter_num", "title", "content", "content_hash", "canon_revision", "planning_revision_id", "planning_revision", "planning_hash", "chapter_outline_revision_id", "chapter_outline_revision", "chapter_outline_hash", "finalized_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterLogicalId"), _required(data, "candidateLogicalId"), _required(data, "finalizationRecordLogicalId"), _required(data, "chapterNumber"), _required(data, "title"), _required(data, "content"), _required(data, "contentHash"), _required(data, "canonRevision"), _required(data, "planningRevisionLogicalId"), _required(data, "planningRevision"), _required(data, "planningHash"), _required(data, "outlineRevisionLogicalId"), _required(data, "chapterOutlineRevision"), _required(data, "chapterOutlineHash"), _required(data, "finalizedAt"))
    return (EncodedBatch("final_chapters", columns, (row,)),)


def _creation_contract(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    payload = data.get("payload")
    if not isinstance(payload, Mapping):
        raise _invalid()
    selected = _selection_revision(context, data.get("selectionRevision"))
    engine_id = _required(payload, "engineOptionId")
    option_key, _option_data = _record_by_target_id(context, "story-engine-option", engine_id)
    option = context.records.get(option_key)
    batch_logical = option.data.get("batchLogicalId") if option is not None else None
    if not isinstance(batch_logical, str):
        raise _invalid()
    binding_ref = payload.get("modelBindingRef")
    style_refs = [("primary", payload.get("primaryStyleRef"))]
    if payload.get("secondaryStyleRef") is not None:
        style_refs.append(("secondary", payload.get("secondaryStyleRef")))
    manifest = {
        "schemaVersion": "contract-reference-manifest-v1",
        "seedRef": {"id": data.get("seedLogicalId"), "revisionId": data.get("seedRevisionLogicalId"), "contentHash": data.get("seedHash")},
        "engineRef": {"id": engine_id, "batchId": context.ids.get(("story-engine-batch", batch_logical)), "contentHash": payload.get("engineHash")},
        "bindingRef": thaw_json_value(binding_ref) if binding_ref is not None else None,
        "styleRefs": [
            {"role": role, **thaw_json_value(item)}
            for role, item in style_refs
            if isinstance(item, Mapping)
        ],
        "experienceCardRefs": thaw_json_value(payload.get("experienceCardRefs")),
        "corpusSourceRefs": thaw_json_value(payload.get("corpusSourceRefs")),
    }
    capacity = {"expectedVolumeCount": payload.get("expectedVolumeCount"), "expectedChapterCount": payload.get("expectedChapterCount"), "chapterWordRangePreference": thaw_json_value(payload.get("chapterWordRangePreference"))}
    binding_id = binding_ref.get("id") if isinstance(binding_ref, Mapping) else None
    binding_hash = binding_ref.get("contentHash") if isinstance(binding_ref, Mapping) else None
    columns = ("id", "project_id", "revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "binding_revision_id", "binding_hash", "channel_profile_key", "genre_profile_key", "quality_charter_version", "total_word_min", "total_word_max", "chapter_capacity_policy", "reference_manifest_json", "reference_manifest_hash", "content_json", "content_hash", "confirmed_at")
    if selected.get("seedLogicalId") != data.get("seedLogicalId") or selected.get("seedRevisionLogicalId") != data.get("seedRevisionLogicalId") or selected.get("seedHash") != data.get("seedHash"):
        raise _invalid()
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "revision"), _required(data, "selectionRevision"), _required(data, "seedLogicalId"), _required(data, "seedRevisionLogicalId"), _required(data, "seedHash"), binding_id, binding_hash, _required(payload, "channelProfileKey"), _required(payload, "genreProfileKey"), _required(payload, "qualityCharterVersion"), _required(payload, "targetTotalWords"), _required(payload, "targetTotalWords"), canonical_json(capacity), canonical_json(manifest), canonical_hash(manifest), _json_value(data, "payload"), _required(data, "contentHash"), _required(data, "createdAt"))
    return (EncodedBatch("creation_contracts", columns, (row,)),)


def _engine_ref(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("creation_contract_id", "project_id", "engine_option_id", "engine_hash")
    return (EncodedBatch("creation_contract_engine_refs", columns, ((_required(data, "creationContractLogicalId"), context.target_project_id, _required(data, "storyEngineLogicalId"), _required(data, "contentHash")),)),)


def _asset_by_name(
    context: PublicationEncodingContext,
    name: object,
    revision: object,
    content_hash: object,
    expected_kind: str,
) -> tuple[str, Mapping[str, object]]:
    found = [
        (context.ids[key], value)
        for key, value in context.rewritten.items()
        if key[0] == "asset"
        and value.get("assetKind") == expected_kind
        and value.get("name") == name
        and value.get("revision") == revision
        and value.get("contentHash") == content_hash
    ]
    if len(found) != 1:
        raise _invalid()
    return found[0]


def _template_ref(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    asset_id, asset = _asset_by_name(
        context, data.get("templateName"), data.get("templateRevision"),
        data.get("contentHash"), "style-template",
    )
    style_key, style = _record_by_target_id(context, "style-contract", data.get("styleContractLogicalId"))
    creation = _record_by_target_id(context, "creation-contract", style.get("creationContractLogicalId"))[1]
    payload = creation.get("payload")
    if not isinstance(payload, Mapping):
        raise _invalid()
    linked = [
        ("primary", payload.get("primaryStyleRef")),
        ("secondary", payload.get("secondaryStyleRef")),
    ]
    linked = [(role, value) for role, value in linked if isinstance(value, Mapping)]
    if record.order < 1 or record.order > len(linked):
        raise _invalid()
    role, expected = linked[record.order - 1]
    if any(expected.get(field) != actual for field, actual in (
        ("id", asset_id), ("revision", data.get("templateRevision")),
        ("contentHash", data.get("contentHash")),
    )):
        raise _invalid()
    columns = ("style_contract_id", "role", "style_template_id", "asset_revision", "asset_hash", "sort_order")
    style_id = context.ids[style_key]
    return (EncodedBatch("style_contract_template_refs", columns, ((style_id, role, asset_id, _required(asset, "revision"), _required(asset, "contentHash"), record.order),)),)


def _experience_ref(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    asset_id, asset = _asset_by_name(
        context, data.get("experienceTitle"), data.get("experienceRevision"),
        data.get("contentHash"), "experience-card",
    )
    creation = _record_by_target_id(
        context, "creation-contract", data.get("creationContractLogicalId"),
    )[1]
    payload = creation.get("payload")
    refs = payload.get("experienceCardRefs") if isinstance(payload, Mapping) else None
    if not isinstance(refs, list) or record.order < 1 or record.order > len(refs):
        raise _invalid()
    expected = refs[record.order - 1]
    if not isinstance(expected, Mapping) or any(expected.get(field) != actual for field, actual in (
        ("id", asset_id), ("revision", data.get("experienceRevision")),
        ("contentHash", data.get("contentHash")),
    )):
        raise _invalid()
    columns = ("creation_contract_id", "experience_card_id", "asset_revision", "asset_hash", "sort_order")
    return (EncodedBatch("creation_contract_experience_refs", columns, ((_required(data, "creationContractLogicalId"), asset_id, _required(asset, "revision"), _required(asset, "contentHash"), record.order),)),)


def _corpus_parts(context: PublicationEncodingContext, revision_id: object) -> tuple[str, Mapping[str, object]]:
    _key, corpus = _record_by_target_id(context, "corpus-revision", revision_id)
    source_id = corpus_source_target_id(context.command_id, _required(corpus, "sourceKey"))
    return source_id, corpus


def _contract_corpus_source(
    context: PublicationEncodingContext,
    data: Mapping[str, object],
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...]]:
    source_id, _corpus = _corpus_parts(context, data.get("corpusRevisionLogicalId"))
    creation = _record_by_target_id(context, "creation-contract", data.get("creationContractLogicalId"))[1]
    payload = creation.get("payload")
    if not isinstance(payload, Mapping):
        raise _invalid()
    sources = payload.get("corpusSourceRefs")
    if not isinstance(sources, list):
        raise _invalid()
    source_matches = [
        source for source in sources
        if isinstance(source, Mapping)
        and source.get("id") == source_id
        and source.get("revisionId") == data.get("corpusRevisionLogicalId")
    ]
    if len(source_matches) != 1:
        raise _invalid()
    ordered: list[Mapping[str, object]] = []
    for source in sources:
        if not isinstance(source, Mapping) or not isinstance(source.get("fragments"), list):
            raise _invalid()
        ordered.extend(fragment for fragment in source["fragments"] if isinstance(fragment, Mapping))
        if len(ordered) != sum(len(item.get("fragments", [])) for item in sources if isinstance(item, Mapping)):
            raise _invalid()
    return source_matches[0], tuple(ordered)


def _corpus_ref(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    source_id, corpus = _corpus_parts(context, data.get("corpusRevisionLogicalId"))
    authority, _fragments = _contract_corpus_source(context, data)
    columns = ("creation_contract_id", "corpus_source_id", "source_revision", "source_hash", "selection_mode", "sort_order")
    return (EncodedBatch("creation_contract_corpus_refs", columns, ((_required(data, "creationContractLogicalId"), source_id, _required(corpus, "revision"), _required(corpus, "contentHash"), _required(authority, "selectionMode"), record.order),)),)


def _corpus_fragment_ref(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    source_id, corpus = _corpus_parts(context, data.get("corpusRevisionLogicalId"))
    authority, ordered = _contract_corpus_source(context, data)
    if record.order < 1 or record.order > len(ordered):
        raise _invalid()
    authority_fragment = ordered[record.order - 1]
    if authority.get("id") != source_id or authority.get("revisionId") != data.get("corpusRevisionLogicalId"):
        raise _invalid()
    fragments = corpus.get("fragments")
    if not isinstance(fragments, list):
        raise _invalid()
    matched = [item for item in fragments if isinstance(item, Mapping) and item.get("logicalId") == authority_fragment.get("fragmentId")]
    if len(matched) != 1:
        raise _invalid()
    fragment = matched[0]
    chapters = corpus.get("chapters")
    chapter_matches = [item for item in chapters if isinstance(item, Mapping) and item.get("logicalId") == authority_fragment.get("chapterId")] if isinstance(chapters, list) else []
    if len(chapter_matches) != 1:
        raise _invalid()
    chapter = chapter_matches[0]
    columns = ("creation_contract_id", "corpus_source_id", "source_revision", "source_hash", "corpus_chapter_id", "corpus_fragment_id", "fragment_hash", "chapter_char_start", "chapter_char_end", "reference_use", "sort_order")
    selected_start = authority_fragment.get("chapterCharStart")
    selected_end = authority_fragment.get("chapterCharEnd")
    fragment_start = fragment.get("chapterCharStart")
    fragment_end = fragment.get("chapterCharEnd")
    if (
        authority_fragment.get("fragmentHash") != fragment.get("contentHash")
        or fragment.get("chapterOrder") != chapter.get("chapterOrder")
        or any(type(value) is not int for value in (
            selected_start, selected_end, fragment_start, fragment_end,
        ))
        or not fragment_start <= selected_start < selected_end <= fragment_end
    ):
        raise _invalid()
    row = (_required(data, "creationContractLogicalId"), source_id, _required(corpus, "revision"), _required(corpus, "contentHash"), _required(chapter, "logicalId"), _required(fragment, "logicalId"), _required(fragment, "contentHash"), _required(authority_fragment, "chapterCharStart"), _required(authority_fragment, "chapterCharEnd"), _required(authority_fragment, "referenceUse"), record.order)
    return (EncodedBatch("creation_contract_corpus_fragment_refs", columns, (row,)),)


def _contract_draft(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    payload = data.get("payload")
    if not isinstance(payload, Mapping):
        raise _invalid()
    columns = ("project_id", "id", "base_head_revision", "selection_revision", "seed_revision_id", "seed_hash", "engine_option_id", "draft_json", "content_hash", "draft_version", "created_at", "updated_at")
    row = (context.target_project_id, context.ids[(record.entity_type, record.logical_id)], _required(data, "baseHeadRevision"), _required(data, "selectionRevision"), _required(data, "seedRevisionLogicalId"), _required(data, "seedHash"), _required(data, "engineOptionLogicalId"), _json_value(data, "payload"), _required(data, "contentHash"), _required(data, "draftVersion") if data.get("draftVersion") is not None else _required(data, "revision"), _required(data, "createdAt") if data.get("createdAt") is not None else _required(data, "updatedAt"), _required(data, "updatedAt"))
    return (EncodedBatch("project_contract_drafts", columns, (row,)),)


def _bible_draft(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "active_slot", "base_head_revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "binding_revision_id", "binding_hash", "policy_version", "draft_json", "content_hash", "draft_version", "created_at", "updated_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, None, _required(data, "baseHeadRevision"), _required(data, "selectionRevision"), _required(data, "seedLogicalId"), _required(data, "seedRevisionLogicalId"), _required(data, "seedHash"), _required(data, "contractRevision"), _required(data, "creationContractLogicalId"), _required(data, "creationHash"), _required(data, "styleContractLogicalId"), _required(data, "styleHash"), _nullable(data, "bindingRevisionLogicalId"), _nullable(data, "bindingHash"), _required(data, "policyVersion"), _json_value(data, "payload"), _required(data, "contentHash"), _required(data, "draftVersion") if data.get("draftVersion") is not None else _required(data, "revision"), _required(data, "createdAt") if data.get("createdAt") is not None else _required(data, "updatedAt"), _required(data, "updatedAt"))
    return (EncodedBatch("project_bible_drafts", columns, (row,)),)


def _planning_draft(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "active_slot", "base_head_revision", "draft_revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "bible_revision", "bible_revision_id", "bible_hash", "content_json", "content_hash", "source_attempt_id", "status", "created_at", "updated_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, None, _required(data, "baseHeadRevision"), _required(data, "draftRevision") if data.get("draftRevision") is not None else _required(data, "revision"), _required(data, "selectionRevision"), _required(data, "seedLogicalId"), _required(data, "seedRevisionLogicalId"), _required(data, "seedHash"), _required(data, "contractRevision"), _required(data, "creationContractLogicalId"), _required(data, "creationHash"), _required(data, "styleContractLogicalId"), _required(data, "styleHash"), _required(data, "bibleRevision"), _required(data, "bibleRevisionLogicalId"), _required(data, "bibleHash"), _json_value(data, "payload"), _required(data, "contentHash"), None, "confirmed", _required(data, "createdAt") if data.get("createdAt") is not None else _required(data, "updatedAt"), _required(data, "updatedAt"))
    return (EncodedBatch("planning_drafts", columns, (row,)),)


def _outline_draft(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    columns = ("id", "project_id", "chapter_num", "active_slot", "base_head_revision", "draft_revision", "planning_revision_id", "planning_revision", "planning_hash", "canon_revision", "projection_revision", "projection_hash", "content_json", "content_hash", "source_attempt_id", "status", "created_at", "updated_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterNumber"), None, _required(data, "baseHeadRevision"), _required(data, "draftRevision") if data.get("draftRevision") is not None else _required(data, "revision"), _required(data, "planningRevisionLogicalId"), _required(data, "planningRevision"), _required(data, "planningHash"), _required(data, "canonRevision"), _required(data, "projectionRevision"), _required(data, "projectionHash"), _json_value(data, "payload"), _required(data, "contentHash"), None, "confirmed", _required(data, "createdAt") if data.get("createdAt") is not None else _required(data, "updatedAt"), _required(data, "updatedAt"))
    return (EncodedBatch("chapter_outline_drafts", columns, (row,)),)


def _candidate_freeze(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    authority = {"candidateId": data.get("candidateLogicalId"), "chapterId": data.get("chapterLogicalId"), "fingerprint": data.get("requestFingerprint")}
    columns = ("id", "project_id", "chapter_session_id", "idempotency_key", "request_hash", "draft_candidate_id", "created_at")
    return (EncodedBatch("candidate_freeze_requests", columns, ((context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterLogicalId"), _derived_hash(context, "candidate-freeze/idempotency", authority), _derived_hash(context, "candidate-freeze/request", authority), _required(data, "candidateLogicalId"), _required(data, "createdAt")),)),)


def _reference_use(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    source_id, corpus = _corpus_parts(context, data.get("corpusRevisionLogicalId"))
    chapters = corpus.get("chapters")
    if not isinstance(chapters, list):
        raise _invalid()
    chapter_matches = [item for item in chapters if isinstance(item, Mapping) and item.get("logicalId") == data.get("corpusChapterLogicalId")]
    if len(chapter_matches) != 1:
        raise _invalid()
    columns = ("id", "project_id", "chapter_session_id", "draft_candidate_id", "corpus_source_id", "corpus_chapter_id", "location_start", "location_end", "reference_purpose", "referenced_text_hash", "created_at")
    return (EncodedBatch("reference_uses", columns, ((context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterLogicalId"), _required(data, "candidateLogicalId"), source_id, _required(chapter_matches[0], "logicalId"), _required(data, "locationStart"), _required(data, "locationEnd"), _required(data, "referencePurpose"), _required(data, "referencedTextHash"), _required(data, "createdAt")),)),)


def _contract_confirmation(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    creation_key, creation = _record_by_target_id(context, "creation-contract", data.get("creationContractLogicalId"))
    style_key, style = _record_by_target_id(context, "style-contract", data.get("styleContractLogicalId"))
    payload = creation.get("payload")
    if not isinstance(payload, Mapping):
        raise _invalid()
    authority = {
        "logicalId": record.logical_id,
        "selectionRevision": data.get("selectionRevision"),
        "resultRevision": data.get("resultRevision"),
        "creationHash": creation.get("contentHash"),
        "styleHash": style.get("contentHash"),
    }
    columns = ("id", "project_id", "selection_revision", "idempotency_key", "request_hash", "status", "creation_contract_id", "style_contract_id", "result_revision", "public_error_code", "created_at", "completed_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "selectionRevision"), _derived_hash(context, "contract-confirmation/idempotency", authority), _derived_hash(context, "contract-confirmation/request", authority), "succeeded", context.ids[creation_key], context.ids[style_key], _required(data, "resultRevision"), None, _required(data, "createdAt"), _required(data, "completedAt"))
    return (EncodedBatch("contract_confirmation_requests", columns, (row,)),)


def _bible_confirmation(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    revision_key, revision = _record_by_target_id(context, "creation-bible-revision", data.get("bibleRevisionLogicalId"))
    draft_key, draft = _record_by_target_id(context, "project-bible-draft", data.get("draftLogicalId"))
    authority = {"logicalId": record.logical_id, "draftHash": draft.get("contentHash")}
    columns = ("id", "project_id", "selection_revision", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "draft_id", "draft_version", "draft_hash", "idempotency_key", "request_hash", "status", "bible_revision_id", "result_revision", "result_hash", "public_error_code", "created_at", "completed_at")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "selectionRevision"), _required(data, "contractRevision"), _required(data, "creationContractLogicalId"), _required(data, "creationHash"), _required(data, "styleContractLogicalId"), _required(data, "styleHash"), context.ids[draft_key], _required(data, "draftVersion"), _required(data, "draftHash"), _derived_hash(context, "bible-confirmation/idempotency", authority), _derived_hash(context, "bible-confirmation/request", authority), "succeeded", context.ids[revision_key], _required(data, "resultRevision"), _required(data, "contentHash"), None, _required(data, "createdAt"), _required(data, "completedAt"))
    return (EncodedBatch("bible_confirmation_requests", columns, (row,)),)


def _planning_confirmation(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    draft_key, draft = _record_by_target_id(context, "planning-draft", data.get("draftLogicalId"))
    revision_key, _revision = _record_by_target_id(context, "planning-revision", data.get("planningRevisionLogicalId"))
    authority = {"logicalId": record.logical_id, "draftHash": draft.get("contentHash")}
    columns = ("id", "project_id", "planning_draft_id", "draft_revision", "draft_hash", "expected_head_revision", "idempotency_key", "request_fingerprint", "status", "planning_revision_id", "result_revision", "result_hash", "public_error_code", "created_at", "completed_at")
    result_revision = _required(data, "resultRevision")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, context.ids[draft_key], _required(data, "draftRevision"), _required(data, "draftHash"), _required(data, "expectedHeadRevision"), _derived_hash(context, "planning-confirmation/idempotency", authority), _derived_hash(context, "planning-confirmation/request", authority), "succeeded", context.ids[revision_key], result_revision, _required(data, "contentHash"), None, _required(data, "createdAt"), _required(data, "completedAt"))
    return (EncodedBatch("planning_confirmation_requests", columns, (row,)),)


def _outline_confirmation(record: PackageRecord, data: Mapping[str, object], context: PublicationEncodingContext) -> tuple[EncodedBatch, ...]:
    draft_key, draft = _record_by_target_id(context, "chapter-outline-draft", data.get("draftLogicalId"))
    revision_key, revision = _record_by_target_id(context, "chapter-outline-revision", data.get("outlineRevisionLogicalId"))
    payload = revision.get("payload")
    if not isinstance(payload, Mapping):
        raise _invalid()
    authority = {"logicalId": record.logical_id, "draftHash": draft.get("contentHash")}
    columns = ("id", "project_id", "chapter_num", "chapter_outline_draft_id", "draft_revision", "draft_hash", "expected_head_revision", "planning_revision_id", "planning_revision", "planning_hash", "canon_revision", "projection_revision", "projection_hash", "idempotency_key", "request_fingerprint", "status", "outline_revision_id", "result_revision", "result_hash", "public_error_code", "created_at", "completed_at")
    result_revision = _required(data, "resultRevision")
    row = (context.ids[(record.entity_type, record.logical_id)], context.target_project_id, _required(data, "chapterNumber"), context.ids[draft_key], _required(data, "draftRevision"), _required(data, "draftHash"), _required(data, "expectedHeadRevision"), _required(data, "planningRevisionLogicalId"), _required(data, "planningRevision"), _required(data, "planningHash"), _required(data, "canonRevision"), _required(data, "projectionRevision"), _required(data, "projectionHash"), _derived_hash(context, "outline-confirmation/idempotency", authority), _derived_hash(context, "outline-confirmation/request", authority), "succeeded", context.ids[revision_key], result_revision, _required(data, "contentHash"), None, _required(data, "createdAt"), _required(data, "completedAt"))
    return (EncodedBatch("chapter_outline_confirmation_requests", columns, (row,)),)


_RECORD_ENCODERS: Mapping[str, RecordEncoder] = MappingProxyType({
    "project": _project,
    "creative-seed": _creative_seed,
    "creative-seed-revision": _creative_seed_revision,
    "creative-seed-head": _creative_seed_head,
    "project-seed-selection-revision": _seed_selection_revision,
    "project-selected-seed": _selected_seed,
    "story-engine-option": _story_engine_option,
    "style-contract": _style_contract,
    "project-contract-head": _contract_head,
    "creation-bible-revision": _bible_revision,
    "project-bible-head": _bible_head,
    "planning-revision": _planning_revision,
    "project-planning-head": _planning_head,
    "chapter-outline-revision": _outline_revision,
    "project-chapter-outline-head": _outline_head,
    "canon-entity": _canon_entity,
    "entity-alias": _entity_alias,
    "canon-revision": _canon_revision,
    "canon-event": _canon_event,
    "chapter": _chapter,
    "working-draft": _working_draft,
    "draft-candidate": _draft_candidate,
    "candidate-quality": _candidate_quality,
    "finalization-change-set": _change_set,
    "finalization-change-set-revision": _change_set_revision,
    "finalization-record": _finalization_record,
    "final-chapter": _final_chapter,
    "creation-contract": _creation_contract,
    "creation-contract-engine-ref": _engine_ref,
    "style-contract-template-ref": _template_ref,
    "creation-contract-experience-ref": _experience_ref,
    "creation-contract-corpus-ref": _corpus_ref,
    "creation-contract-corpus-fragment-ref": _corpus_fragment_ref,
    "project-contract-draft": _contract_draft,
    "project-bible-draft": _bible_draft,
    "planning-draft": _planning_draft,
    "chapter-outline-draft": _outline_draft,
    "candidate-freeze": _candidate_freeze,
    "reference-use": _reference_use,
    "contract-confirmation": _contract_confirmation,
    "bible-confirmation": _bible_confirmation,
    "planning-confirmation": _planning_confirmation,
    "chapter-outline-confirmation": _outline_confirmation,
    "project-model-binding-revision": _binding_revision,
    "project-model-binding-item": _binding_item,
    "project-model-binding-head": _binding_head,
})

_SPECIAL_RECORD_HANDLERS: Mapping[str, RecordEncoder] = MappingProxyType({
    "asset": _asset,
    "corpus-revision": _corpus,
})

STATIC_TABLE_COLUMNS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "projects": ("id", "title", "genre", "description", "target_words", "target_chapters", "status", "current_chapter", "archived_at", "lifecycle_revision", "created_at", "updated_at"),
    "project_model_binding_revisions": ("id", "project_id", "revision", "content_hash", "source_project_id", "created_at"),
    "project_model_binding_items": ("binding_revision_id", "task_key", "resolution_status", "provider_id", "provider_name_snapshot", "model_name_snapshot", "item_hash"),
    "project_model_binding_heads": ("project_id", "revision", "binding_revision_id", "content_hash", "updated_at"),
    "style_templates": ("id", "stable_key", "revision", "name", "payload_json", "provenance_json", "content_hash", "status", "created_at"),
    "experience_cards": ("id", "stable_key", "revision", "title", "category", "payload_json", "provenance_json", "content_hash", "status", "created_at"),
    "creative_seeds": ("id", "project_id", "status", "created_at", "updated_at"),
    "creative_seed_revisions": ("id", "project_id", "seed_id", "revision", "payload_json", "content_hash", "created_at"),
    "creative_seed_heads": ("seed_id", "revision_id", "revision", "content_hash", "updated_at"),
    "project_seed_selection_revisions": ("project_id", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "selected_at"),
    "project_selected_seeds": ("project_id", "seed_id", "seed_revision_id", "seed_hash", "selection_revision", "selected_at", "updated_at"),
    "story_engine_batches": ("id", "project_id", "selection_revision", "source_type", "seed_id", "seed_revision_id", "seed_hash", "binding_revision_id", "binding_hash", "provider_id", "model_name_snapshot", "idempotency_key", "request_json", "request_hash", "status", "attempt_id", "attempt_started_at", "lease_expires_at", "raw_response_text", "raw_response_hash", "public_error_code", "created_at", "finished_at"),
    "story_engine_options": ("id", "project_id", "selection_revision", "batch_id", "option_order", "payload_json", "content_hash", "created_at"),
    "style_contracts": ("id", "project_id", "creation_contract_id", "revision", "merged_style_json", "likes_json", "dislikes_json", "content_hash", "confirmed_at"),
    "project_contract_heads": ("project_id", "revision", "creation_contract_id", "style_contract_id", "creation_hash", "style_hash", "updated_at"),
    "creation_bible_revisions": ("id", "project_id", "revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "binding_revision_id", "binding_hash", "policy_version", "content_json", "content_hash", "confirmed_at"),
    "project_bible_heads": ("project_id", "revision", "bible_revision_id", "content_hash", "updated_at"),
    "planning_revisions": ("id", "project_id", "revision", "parent_revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "bible_revision", "bible_revision_id", "bible_hash", "content_json", "content_hash", "created_at"),
    "project_planning_heads": ("project_id", "revision", "planning_revision_id", "content_hash", "updated_at"),
    "chapter_outline_revisions": ("id", "project_id", "chapter_num", "revision", "parent_revision", "planning_revision_id", "planning_revision", "planning_hash", "canon_revision", "projection_revision", "projection_hash", "content_json", "content_hash", "created_at"),
    "project_chapter_outline_heads": ("project_id", "chapter_num", "revision", "outline_revision_id", "content_hash", "updated_at"),
    "canon_entities": ("id", "project_id", "entity_type", "canonical_name", "normalized_name", "created_revision", "created_at"),
    "entity_aliases": ("id", "project_id", "entity_id", "alias", "normalized_alias", "created_revision", "created_at"),
    "canon_revisions": ("id", "project_id", "revision_number", "parent_revision_number", "idempotency_key", "source_type", "source_id", "content_hash", "created_at"),
    "canon_events": ("id", "project_id", "revision_id", "revision_number", "event_order", "entity_id", "fact_kind", "field_path", "value_json", "evidence_json", "effective_start_chapter", "effective_end_chapter", "assertion_operator", "value_cardinality", "confirmation_status", "created_at"),
    "chapter_sessions": ("id", "project_id", "planning_revision_id", "planning_revision", "planning_hash", "story_block_id", "story_block_revision", "story_block_hash", "chapter_outline_revision_id", "chapter_outline_revision", "chapter_outline_hash", "chapter_num", "expected_canon_revision", "status", "draft_operation_fencing_token", "active_draft_operation_id", "created_at", "finalized_at"),
    "working_drafts": ("id", "project_id", "chapter_session_id", "revision", "content", "content_hash", "source_payload_json", "updated_at"),
    "draft_candidates": ("id", "project_id", "chapter_session_id", "working_draft_revision", "content", "content_hash", "basis_hash", "provenance_json", "created_at"),
    "candidate_quality_reports": ("id", "project_id", "chapter_session_id", "draft_candidate_id", "candidate_hash", "expected_canon_revision", "expected_planning_hash", "expected_outline_hash", "policy_version", "context_manifest_hash", "provider_id", "provider_profile_revision", "model_name_snapshot", "status", "deterministic_blocks_json", "findings_json", "content_hash", "created_at"),
    "finalization_change_sets": ("id", "project_id", "chapter_session_id", "draft_candidate_id", "quality_report_id", "extraction_id", "idempotency_key", "request_fingerprint", "active_slot", "candidate_hash", "expected_canon_revision", "expected_planning_hash", "expected_outline_hash", "context_manifest_json", "context_manifest_hash", "status", "current_revision", "current_revision_hash", "confirmed_revision", "confirmed_revision_hash", "created_at", "updated_at", "confirmed_at"),
    "finalization_change_set_revisions": ("id", "project_id", "change_set_id", "revision", "payload_json", "content_hash", "source", "created_at"),
    "finalization_records": ("id", "project_id", "chapter_session_id", "draft_candidate_id", "change_set_id", "change_set_revision", "idempotency_key", "request_fingerprint", "candidate_hash", "change_set_hash", "expected_canon_revision", "committed_canon_revision", "result_payload_json", "finalized_at"),
    "final_chapters": ("id", "project_id", "chapter_session_id", "draft_candidate_id", "finalization_record_id", "chapter_num", "title", "content", "content_hash", "canon_revision", "planning_revision_id", "planning_revision", "planning_hash", "chapter_outline_revision_id", "chapter_outline_revision", "chapter_outline_hash", "finalized_at"),
    "creation_contracts": ("id", "project_id", "revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "binding_revision_id", "binding_hash", "channel_profile_key", "genre_profile_key", "quality_charter_version", "total_word_min", "total_word_max", "chapter_capacity_policy", "reference_manifest_json", "reference_manifest_hash", "content_json", "content_hash", "confirmed_at"),
    "creation_contract_engine_refs": ("creation_contract_id", "project_id", "engine_option_id", "engine_hash"),
    "style_contract_template_refs": ("style_contract_id", "role", "style_template_id", "asset_revision", "asset_hash", "sort_order"),
    "creation_contract_experience_refs": ("creation_contract_id", "experience_card_id", "asset_revision", "asset_hash", "sort_order"),
    "creation_contract_corpus_refs": ("creation_contract_id", "corpus_source_id", "source_revision", "source_hash", "selection_mode", "sort_order"),
    "creation_contract_corpus_fragment_refs": ("creation_contract_id", "corpus_source_id", "source_revision", "source_hash", "corpus_chapter_id", "corpus_fragment_id", "fragment_hash", "chapter_char_start", "chapter_char_end", "reference_use", "sort_order"),
    "project_contract_drafts": ("project_id", "id", "base_head_revision", "selection_revision", "seed_revision_id", "seed_hash", "engine_option_id", "draft_json", "content_hash", "draft_version", "created_at", "updated_at"),
    "project_bible_drafts": ("id", "project_id", "active_slot", "base_head_revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "binding_revision_id", "binding_hash", "policy_version", "draft_json", "content_hash", "draft_version", "created_at", "updated_at"),
    "planning_drafts": ("id", "project_id", "active_slot", "base_head_revision", "draft_revision", "selection_revision", "seed_id", "seed_revision_id", "seed_hash", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "bible_revision", "bible_revision_id", "bible_hash", "content_json", "content_hash", "source_attempt_id", "status", "created_at", "updated_at"),
    "chapter_outline_drafts": ("id", "project_id", "chapter_num", "active_slot", "base_head_revision", "draft_revision", "planning_revision_id", "planning_revision", "planning_hash", "canon_revision", "projection_revision", "projection_hash", "content_json", "content_hash", "source_attempt_id", "status", "created_at", "updated_at"),
    "candidate_freeze_requests": ("id", "project_id", "chapter_session_id", "idempotency_key", "request_hash", "draft_candidate_id", "created_at"),
    "reference_uses": ("id", "project_id", "chapter_session_id", "draft_candidate_id", "corpus_source_id", "corpus_chapter_id", "location_start", "location_end", "reference_purpose", "referenced_text_hash", "created_at"),
    "contract_confirmation_requests": ("id", "project_id", "selection_revision", "idempotency_key", "request_hash", "status", "creation_contract_id", "style_contract_id", "result_revision", "public_error_code", "created_at", "completed_at"),
    "bible_confirmation_requests": ("id", "project_id", "selection_revision", "contract_revision", "creation_contract_id", "creation_hash", "style_contract_id", "style_hash", "draft_id", "draft_version", "draft_hash", "idempotency_key", "request_hash", "status", "bible_revision_id", "result_revision", "result_hash", "public_error_code", "created_at", "completed_at"),
    "planning_confirmation_requests": ("id", "project_id", "planning_draft_id", "draft_revision", "draft_hash", "expected_head_revision", "idempotency_key", "request_fingerprint", "status", "planning_revision_id", "result_revision", "result_hash", "public_error_code", "created_at", "completed_at"),
    "chapter_outline_confirmation_requests": ("id", "project_id", "chapter_num", "chapter_outline_draft_id", "draft_revision", "draft_hash", "expected_head_revision", "planning_revision_id", "planning_revision", "planning_hash", "canon_revision", "projection_revision", "projection_hash", "idempotency_key", "request_fingerprint", "status", "outline_revision_id", "result_revision", "result_hash", "public_error_code", "created_at", "completed_at"),
    "project_import_provenance": ("project_id", "command_id", "record_order", "category", "source_entity_type", "source_logical_id", "payload_json", "content_hash", "created_at"),
    "corpus_blobs": ("content_hash", "byte_length", "storage_key", "created_at"),
    "corpus_sources": ("id", "source_key", "archived_at", "created_at", "updated_at"),
    "corpus_source_revisions": ("id", "source_id", "revision", "content_hash", "relative_path", "display_name", "author", "reference_tags_json", "notes", "provenance_json", "byte_length", "encoding", "parser_version", "normalizer_version", "fragmenter_version", "index_version", "status", "public_error_code", "imported_at", "analyzed_at", "created_at"),
    "corpus_chapters": ("id", "corpus_source_id", "source_revision_id", "source_revision", "source_hash", "chapter_order", "title", "raw_byte_start", "raw_byte_end", "normalized_char_start", "normalized_char_end", "normalized_text", "content_hash", "created_at"),
    "corpus_fragments": ("id", "corpus_source_id", "corpus_chapter_id", "fragment_order", "chapter_char_start", "chapter_char_end", "normalized_text", "content_hash", "index_payload", "analysis_version", "created_at"),
})


# One closed FK-topological order for every table publication may target.
PUBLICATION_TABLE_ORDER = (
    "corpus_blobs", "corpus_sources", "experience_cards", "projects", "style_templates",
    "canon_entities", "canon_revisions", "corpus_source_revisions", "creative_seeds",
    "project_import_provenance", "project_model_binding_revisions", "canon_events",
    "corpus_chapters", "creative_seed_revisions", "entity_aliases", "project_model_binding_heads",
    "project_model_binding_items", "corpus_fragments", "creative_seed_heads",
    "project_seed_selection_revisions", "creation_contracts", "project_selected_seeds",
    "story_engine_batches", "creation_contract_corpus_fragment_refs", "creation_contract_corpus_refs",
    "creation_contract_experience_refs", "story_engine_options", "style_contracts",
    "contract_confirmation_requests", "creation_bible_revisions", "creation_contract_engine_refs",
    "project_bible_drafts", "project_contract_drafts", "project_contract_heads",
    "style_contract_template_refs", "bible_confirmation_requests", "planning_drafts",
    "planning_revisions", "project_bible_heads", "chapter_outline_drafts",
    "chapter_outline_revisions", "planning_confirmation_requests", "project_planning_heads",
    "chapter_outline_confirmation_requests", "chapter_sessions", "project_chapter_outline_heads",
    "draft_candidates", "working_drafts", "candidate_freeze_requests", "candidate_quality_reports",
    "reference_uses", "finalization_change_sets", "finalization_change_set_revisions",
    "finalization_records", "final_chapters",
)
_PUBLICATION_TABLE_POSITION = MappingProxyType({table: index for index, table in enumerate(PUBLICATION_TABLE_ORDER)})

_PUBLICATION_CLOSED_ENUMS: Mapping[tuple[str, str], frozenset[JsonPrimitive]] = MappingProxyType({
    ("projects", "status"): frozenset({"drafting", "active", "completed"}),
    ("style_templates", "status"): frozenset({"active", "archived"}),
    ("experience_cards", "status"): frozenset({"active", "archived"}),
    ("experience_cards", "category"): frozenset({"plot_organization", "ensemble", "dialogue", "emotion", "interiority", "information_release", "pacing", "suspense", "long_arc_continuity", "progression_economy", "character_arcs", "action_conflict"}),
    ("corpus_source_revisions", "status"): frozenset({"imported", "analyzed", "failed"}),
    ("story_engine_batches", "source_type"): frozenset({"provider", "manual"}),
    ("story_engine_batches", "status"): frozenset({"reserved", "running", "succeeded", "failed", "outcome_unknown"}),
    ("project_model_binding_items", "resolution_status"): frozenset({"bound", "unbound"}),
    ("creation_contract_corpus_refs", "selection_mode"): frozenset({"author", "system"}),
    ("creation_contract_corpus_fragment_refs", "reference_use"): frozenset({"inspiration", "structure", "style", "fact_check"}),
    ("reference_uses", "reference_purpose"): frozenset({"generation", "review", "revision"}),
    ("planning_drafts", "status"): frozenset({"active", "confirmed", "superseded"}),
    ("chapter_outline_drafts", "status"): frozenset({"active", "confirmed", "superseded"}),
    ("chapter_sessions", "status"): frozenset({"drafting", "final"}),
    ("candidate_quality_reports", "status"): frozenset({"completed", "quality_not_completed"}),
    ("finalization_change_sets", "status"): frozenset({"preparing", "awaiting_author", "committing", "committed", "invalidated", "cancelled", "failed"}),
})


def validate_publication_batches(batches: tuple[EncodedBatch, ...]) -> None:
    """Validate the closed DDL checks relied upon by inert import publication."""
    rows: dict[str, list[dict[str, JsonPrimitive]]] = {}
    for batch in batches:
        if len(set(batch.columns)) != len(batch.columns):
            raise _invalid()
        for values in batch.rows:
            if len(values) != len(batch.columns):
                raise _invalid()
            rows.setdefault(batch.table, []).append(dict(zip(batch.columns, values, strict=True)))

    for (table, column), accepted in _PUBLICATION_CLOSED_ENUMS.items():
        if any(column in row and row[column] not in accepted for row in rows.get(table, ())):
            raise _invalid()

    for row in rows.get("project_model_binding_items", ()):
        provider = (row.get("provider_id"), row.get("provider_name_snapshot"), row.get("model_name_snapshot"))
        if row.get("resolution_status") == "unbound" and provider != (None, None, None):
            raise _invalid()
        if row.get("resolution_status") == "bound" and any(value is None for value in provider):
            raise _invalid()
    for row in rows.get("candidate_quality_reports", ()):
        provider = (row.get("provider_id"), row.get("provider_profile_revision"), row.get("model_name_snapshot"))
        if any(value is None for value in provider) and provider != (None, None, None):
            raise _invalid()
    for row in rows.get("story_engine_batches", ()):
        inert = (
            row.get("source_type") == "manual"
            and row.get("status") == "succeeded"
            and row.get("finished_at") is not None
            and all(row.get(column) is None for column in (
                "binding_revision_id", "binding_hash", "provider_id", "model_name_snapshot",
                "attempt_id", "attempt_started_at", "lease_expires_at", "raw_response_text",
                "raw_response_hash", "public_error_code",
            ))
        )
        if not inert:
            raise _invalid()
    for row in rows.get("creation_contract_corpus_refs", ()):
        if type(row.get("source_revision")) is not int or row["source_revision"] <= 0 or type(row.get("sort_order")) is not int or row["sort_order"] <= 0:
            raise _invalid()
    for row in rows.get("creation_contract_corpus_fragment_refs", ()):
        start, end = row.get("chapter_char_start"), row.get("chapter_char_end")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or type(row.get("sort_order")) is not int or row["sort_order"] <= 0:
            raise _invalid()


_PROVENANCE_CATEGORIES: Mapping[str, str] = MappingProxyType({
    "provider-history": "provider-history",
    "market-analysis": "market-history",
    "seed-inspiration-history": "market-history",
    "asset-recommendation-history": "market-history",
    "style-trial-history": "market-history",
    "story-engine-batch": "operation-history",
    "bible-generation-history": "operation-history",
    "planning-generation-history": "operation-history",
    "chapter-outline-generation-history": "operation-history",
    "operation": "operation-history",
    "operation-event": "operation-history",
    "working-draft-revision": "operation-history",
    "import-provenance": "unsupported-history",
})


def encode_provenance_batch(
    records: tuple[PackageRecord, ...], *, command_id: str, target_project_id: str,
) -> EncodedBatch | None:
    rows: list[tuple[JsonPrimitive, ...]] = []
    for record_order, record in enumerate(sorted(records, key=lambda item: (item.entity_type, item.order, item.logical_id)), 1):
        if record.entity_type == "import-provenance":
            category = record.data.get("category")
            source_type = record.data.get("sourceEntityType")
            source_logical_id = record.data.get("sourceLogicalId")
            payload = record.data.get("payload")
            content_hash = record.data.get("contentHash")
            created_at = record.data.get("createdAt")
            if (
                category not in {"provider-history", "market-history", "operation-history", "unsupported-history"}
                or not isinstance(source_type, str) or not source_type
                or not isinstance(source_logical_id, str) or not source_logical_id
                or not isinstance(content_hash, str) or len(content_hash) != 64
                or any(character not in "0123456789abcdef" for character in content_hash)
                or type(created_at) is not int
            ):
                raise _invalid()
            try:
                payload_json = canonical_json(thaw_json_value(payload))
            except Exception:
                raise _invalid() from None
            rows.append((
                target_project_id, command_id, record_order, category,
                source_type, source_logical_id, payload_json, content_hash,
                created_at,
            ))
            continue
        category = _PROVENANCE_CATEGORIES.get(record.entity_type)
        if category is None:
            raise _invalid()
        public = record.to_public_dict()
        created_at = record.data.get("createdAt", record.data.get("completedAt"))
        if type(created_at) is not int:
            created_at = int(_derived_hash(
                PublicationEncodingContext(command_id, target_project_id, "", {}, {}, {}),
                "provenance/created-at", {"entityType": record.entity_type, "logicalId": record.logical_id},
            )[:15], 16)
        source_hash = record.data.get("contentHash")
        content_hash = source_hash if isinstance(source_hash, str) and len(source_hash) == 64 else canonical_hash(public)
        rows.append((target_project_id, command_id, record_order, category, record.entity_type, record.logical_id, canonical_json(public), content_hash, created_at))
    return EncodedBatch("project_import_provenance", STATIC_TABLE_COLUMNS["project_import_provenance"], tuple(rows)) if rows else None


def encode_publication_batches(
    records: tuple[PackageRecord, ...],
    rewritten: Mapping[tuple[str, str], Mapping[str, object]],
    ids: Mapping[tuple[str, str], str],
    *,
    command_id: str,
    target_project_id: str,
    new_title: str,
    source_records: tuple[PackageRecord, ...] | None = None,
) -> tuple[EncodedBatch, ...]:
    context = PublicationEncodingContext(
        command_id, target_project_id, new_title,
        MappingProxyType({(record.entity_type, record.logical_id): record for record in (source_records or records)}),
        rewritten, ids,
    )
    grouped: dict[tuple[str, tuple[str, ...]], list[tuple[JsonPrimitive, ...]]] = {}
    derived_rows: dict[str, set[JsonPrimitive]] = {
        "corpus_blobs": set(), "corpus_sources": set(), "story_engine_batches": set(),
    }
    for record in records:
        encoder = _RECORD_ENCODERS.get(record.entity_type) or _SPECIAL_RECORD_HANDLERS.get(record.entity_type)
        if encoder is None:
            raise _invalid()
        data = rewritten.get((record.entity_type, record.logical_id))
        if data is None:
            raise _invalid()
        for batch in encoder(record, data, context):
            rows = batch.rows
            if batch.table in derived_rows:
                unique: list[tuple[JsonPrimitive, ...]] = []
                for row in rows:
                    identity = row[0]
                    if identity not in derived_rows[batch.table]:
                        derived_rows[batch.table].add(identity)
                        unique.append(row)
                rows = tuple(unique)
            grouped.setdefault((batch.table, batch.columns), []).extend(rows)
    batches = tuple(
        EncodedBatch(table, columns, tuple(rows))
        for (table, columns), rows in sorted(
            grouped.items(), key=lambda item: _PUBLICATION_TABLE_POSITION[item[0][0]],
        )
    )
    validate_publication_batches(batches)
    return batches


__all__ = (
    "EncodedBatch", "PublicationEncodingContext", "encode_publication_batches", "encode_provenance_batch", "validate_publication_batches",
    "_RECORD_ENCODERS", "_SPECIAL_RECORD_HANDLERS", "PUBLICATION_TABLE_ORDER", "STATIC_TABLE_COLUMNS",
)
