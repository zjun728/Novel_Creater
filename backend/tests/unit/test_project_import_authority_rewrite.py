from __future__ import annotations

import json
from dataclasses import replace
import inspect
from hashlib import sha256
from pathlib import Path
import re
from types import MappingProxyType
from uuid import UUID, uuid5

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.project_import_plans import (
    ImportInsertBatch,
    ProjectPublicationPlan,
    ProjectImportSummary,
    VerifiedProjectPackage,
    _validate_graph,
    build_publication_plan,
    _authority_hash,
    _rewrite_record_data,
    _target_projection,
    _publication_embedded_identities,
    _rewrite_records,
    build_import_identity_map,
    _RECORD_ENCODERS,
    _SPECIAL_RECORD_HANDLERS,
    FORMAL_ENTITY_TYPES,
    RECONSTRUCTED_ENTITY_TYPES,
)
from backend.domain.project_packages import thaw_json_value
from backend.domain.project_packages import ManifestEntry, PackageRecord, PAYLOAD_PATHS, ProjectPackageManifest
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_import_publication import PUBLICATION_TABLE_ORDER, STATIC_TABLE_COLUMNS, encode_publication_batches
import backend.domain.project_import_publication as publication_module


COMMAND_ID = "38ca226b-7199-4cc4-a3e9-98c6993b17c3"
SEED_PAYLOAD = {key: "x" for key in (
    "title", "genre", "logline", "protagonist", "desire", "coreConflict",
    "worldPressure", "openingHook", "differentiation",
)}


def test_historical_publication_encoders_have_no_singleton_current_authority_lookup() -> None:
    source = inspect.getsource(publication_module)
    assert "_one_record" not in source
    assert "_current_selected_seed" not in source


def _project_record() -> PackageRecord:
    return PackageRecord("project", "project:1", data={
        "title": "Old", "genre": "fantasy", "description": "project:1",
        "targetWords": 100_000, "targetChapters": 100, "status": "active",
        "currentChapter": 0, "archivedAt": None, "lifecycleRevision": 2,
        "createdAt": 1, "updatedAt": 2,
    })


def _package(records: tuple[PackageRecord, ...]) -> VerifiedProjectPackage:
    index = MappingProxyType({(record.entity_type, record.logical_id): record for record in records})
    entries = tuple(ManifestEntry(path, 0, "0" * 64) for path in sorted(PAYLOAD_PATHS))
    return VerifiedProjectPackage(
        Path("unused.zip"), "a" * 64, "b" * 64,
        ProjectPackageManifest("project:1", entries, {record.entity_type: 1 for record in records}),
        index, MappingProxyType({}),
        ProjectImportSummary("a" * 64, "b" * 64, 1, "Old", "Old（导入）", MappingProxyType({}), False, 0),
    )


def _rows(plan: ProjectPublicationPlan, table: str) -> list[dict[str, object]]:
    batch = next(batch for batch in plan.batches if batch.table == table)
    return [dict(zip(batch.columns, row, strict=True)) for row in batch.rows]


def test_rewrites_typed_seed_authority_and_keeps_corpus_byte_hash_unchanged() -> None:
    records = (
        _project_record(),
        PackageRecord("creative-seed", "creative-seed:1", data={"status": "candidate", "createdAt": 1, "updatedAt": 1}),
        PackageRecord("creative-seed-revision", "creative-seed-revision:1", revision=1, data={
            "seedLogicalId": "creative-seed:1", "revision": 1,
            "payload": SEED_PAYLOAD, "contentHash": canonical_hash(SEED_PAYLOAD), "createdAt": 1,
        }),
        PackageRecord("corpus-revision", "corpus-revision:1", data={
            "sourceKey": "import/source", "revision": 1, "relativePath": "source.txt", "displayName": "Source",
            "author": "Author", "referenceTags": [], "notes": "notes", "provenance": {},
            "contentHash": "c" * 64, "byteLength": 7, "encoding": "utf-8", "parserVersion": "v1",
            "normalizerVersion": "v1", "fragmenterVersion": "v1", "indexVersion": "v1", "status": "imported",
            "importedAt": 1, "analyzedAt": None, "createdAt": 1, "chapters": [], "fragments": [],
        }),
    )

    plan = build_publication_plan(_package(records), COMMAND_ID, "Imported")

    seed = _rows(plan, "creative_seed_revisions")[0]
    corpus = _rows(plan, "corpus_source_revisions")[0]
    assert str(UUID(seed["seed_id"])) == seed["seed_id"]
    assert seed["content_hash"] == canonical_hash(SEED_PAYLOAD)
    assert corpus["byte_length"] == 7
    assert corpus["content_hash"] == "c" * 64


def test_rewrites_corpus_index_identity_slots_to_target_ids() -> None:
    corpus = PackageRecord("corpus-revision", "corpus-revision:1", revision=1, data={
        "sourceKey": "import/source", "revision": 1, "relativePath": "source.txt",
        "displayName": "Source", "author": "Author", "referenceTags": [],
        "notes": "notes", "provenance": {}, "contentHash": "c" * 64,
        "byteLength": 7, "encoding": "utf-8", "parserVersion": "v1",
        "normalizerVersion": "v1", "fragmenterVersion": "v1", "indexVersion": "v1",
        "status": "analyzed", "importedAt": 1, "analyzedAt": 2, "createdAt": 1,
        "chapters": [{
            "logicalId": "corpus-chapter:1", "chapterOrder": 1, "title": "Chapter",
            "rawByteStart": 0, "rawByteEnd": 7, "normalizedCharStart": 0,
            "normalizedCharEnd": 7, "normalizedText": "content", "contentHash": "d" * 64,
            "createdAt": 1,
        }],
        "fragments": [{
            "logicalId": "corpus-fragment:1", "chapterOrder": 1, "fragmentOrder": 1,
            "chapterCharStart": 0, "chapterCharEnd": 7, "normalizedText": "content",
            "contentHash": "e" * 64, "analysisVersion": "v1", "createdAt": 1,
            "indexPayload": {
                "schemaVersion": "corpus-index-v1", "fragmentId": "corpus-fragment:1",
                "chapterId": "corpus-chapter:1", "contentHash": "e" * 64,
                "normalizerVersion": "v1",
            },
        }],
    })

    plan = build_publication_plan(_package((_project_record(), corpus)), COMMAND_ID, "Imported")

    chapter = _rows(plan, "corpus_chapters")[0]
    fragment = _rows(plan, "corpus_fragments")[0]
    index_payload = json.loads(fragment["index_payload"])
    assert index_payload["chapterId"] == chapter["id"]
    assert index_payload["fragmentId"] == fragment["id"]


def test_reconstructs_each_binding_revision_as_exact_unbound_task_set() -> None:
    revision = PackageRecord("project-model-binding-revision", "project-model-binding-revision:1", revision=3, data={
        "revision": 3, "contentHash": "d" * 64, "sourceProjectLogicalId": "project:1", "createdAt": 3,
    })
    alphabetical = tuple(sorted(TASK_KEYS))
    items = tuple(
        PackageRecord("project-model-binding-item", f"project-model-binding-item:{index}", order=index, data={
            "bindingRevisionLogicalId": revision.logical_id, "taskKey": key,
            "resolutionStatus": "bound", "providerName": "remote", "modelName": "secret-model", "itemHash": "e" * 64,
        })
        for index, key in enumerate(alphabetical, 1)
    )
    head = PackageRecord("project-model-binding-head", "project-model-binding-head:1", data={
        "revision": 3, "bindingRevisionLogicalId": revision.logical_id,
        "contentHash": "d" * 64, "updatedAt": 4,
    })
    records = (_project_record(), revision, *items, head)

    plan = build_publication_plan(_package(records), COMMAND_ID, "Imported")

    rewritten = _rows(plan, "project_model_binding_items")
    assert tuple(item["task_key"] for item in rewritten) == TASK_KEYS
    assert all(item["resolution_status"] == "unbound" for item in rewritten)
    assert all(item["provider_id"] is None and item["provider_name_snapshot"] is None and item["model_name_snapshot"] is None for item in rewritten)
    assert len({item["item_hash"] for item in rewritten}) == len(TASK_KEYS)


def test_task2_graph_accepts_exporter_alphabetical_binding_items_by_task_key_map() -> None:
    revision = PackageRecord(
        "project-model-binding-revision", "project-model-binding-revision:1",
        data={"revision": 1, "contentHash": "d" * 64},
    )
    items = tuple(
        PackageRecord(
            "project-model-binding-item", f"project-model-binding-item:{index}", order=index,
            data={
                "bindingRevisionLogicalId": revision.logical_id, "taskKey": key,
                "resolutionStatus": "bound", "providerName": "remote", "modelName": "model",
                "itemHash": "e" * 64,
            },
        )
        for index, key in enumerate(sorted(TASK_KEYS), 1)
    )

    index = _validate_graph((revision, *items))

    assert len(index) == len(TASK_KEYS) + 1


def test_quality_findings_are_typed_and_report_hash_is_recalculated() -> None:
    data = {
        "status": "completed", "deterministicBlocks": [],
        "findings": [{
            "id": "f92dd022-e899-51fc-9af4-e95ae7593034", "dimension": "continuity",
            "reason": "conflict", "suggestedAction": "repair",
            "evidence": {"startScalar": 0, "endScalar": 1, "excerptHash": "a" * 64, "confidence": 1.0, "rationale": "exact"},
        }],
        "contentHash": "b" * 64,
    }

    expected = canonical_hash({key: data[key] for key in ("status", "deterministicBlocks", "findings")})

    assert _authority_hash("candidate-quality", data) == expected


def test_candidate_quality_publication_clears_all_provider_snapshot_fields() -> None:
    record = PackageRecord("candidate-quality", "candidate-quality:1", data={
        "chapterLogicalId": "chapter:1", "candidateLogicalId": "draft-candidate:1",
        "candidateHash": "a" * 64, "expectedCanonRevision": 0,
        "expectedPlanningHash": "b" * 64, "expectedOutlineHash": "c" * 64,
        "policyVersion": "quality-v1", "contextManifestHash": "d" * 64,
        "modelName": "remote-model", "status": "completed", "deterministicBlocks": [],
        "findings": [], "contentHash": "e" * 64, "createdAt": 1,
    })
    ids = {(record.entity_type, record.logical_id): str(UUID(int=51))}
    rewritten = {(record.entity_type, record.logical_id): {
        **dict(record.data), "chapterLogicalId": str(UUID(int=52)),
        "candidateLogicalId": str(UUID(int=53)),
    }}

    batch = encode_publication_batches(
        (record,), rewritten, ids, command_id=COMMAND_ID,
        target_project_id=str(UUID(int=54)), new_title="Imported",
    )[0]
    row = dict(zip(batch.columns, batch.rows[0], strict=True))

    assert (row["provider_id"], row["provider_profile_revision"], row["model_name_snapshot"]) == (None, None, None)


@pytest.mark.parametrize("entity_type", ["working-draft", "draft-candidate", "final-chapter"])
def test_typed_visitors_never_rewrite_logical_looking_prose_or_its_hash(entity_type: str) -> None:
    reference_fields = {
        "working-draft": {"chapterLogicalId": "chapter:1"},
        "draft-candidate": {"chapterLogicalId": "chapter:1"},
        "final-chapter": {
            "chapterLogicalId": "chapter:1", "candidateLogicalId": "draft-candidate:1",
            "finalizationRecordLogicalId": "finalization-record:1",
            "planningRevisionLogicalId": "planning-revision:1",
            "outlineRevisionLogicalId": "chapter-outline-revision:1",
        },
    }[entity_type]
    data = {**reference_fields, "content": "project:1", "contentHash": "a" * 64}
    if entity_type == "draft-candidate":
        data.update({
            "workingDraftRevision": 1, "basisHash": "b" * 64,
            "provenance": {
                "source": "explicit-save-candidate", "workingDraftRevision": 1,
                "schemaVersion": "draft-candidate-basis-v1",
                "outlineRevisionId": "chapter-outline-revision:1", "outlineRevision": 1,
                "outlineHash": "c" * 64,
                "planningRevisionId": "planning-revision:1", "planningRevision": 1,
                "planningHash": "d" * 64, "canonRevision": 0,
                "projectionRevision": 0, "projectionHash": "e" * 64,
            },
        })
    record = PackageRecord(entity_type, f"{entity_type}:1", data=data)
    ids = {
        (kind, logical_id): str(UUID(int=index + 1))
        for index, (kind, logical_id) in enumerate((
            ("chapter", "chapter:1"), ("draft-candidate", "draft-candidate:1"),
            ("finalization-record", "finalization-record:1"), ("planning-revision", "planning-revision:1"),
            ("chapter-outline-revision", "chapter-outline-revision:1"),
        ))
    }

    rewritten = _rewrite_record_data(record, ids, {})

    assert rewritten["content"] == "project:1"
    assert rewritten["contentHash"] == "a" * 64
    assert all(rewritten[field] != logical_id for field, logical_id in reference_fields.items())


def test_typed_visitor_rejects_dangling_and_wrong_typed_slot_without_echo() -> None:
    record = PackageRecord("working-draft", "working-draft:1", data={
        "chapterLogicalId": "chapter:1", "content": "unchanged", "contentHash": "a" * 64,
    })
    for ids in ({}, {("project", "chapter:1"): str(UUID(int=1))}):
        with pytest.raises(Exception, match="^invalid project import archive$") as raised:
            _rewrite_record_data(record, ids, {})
        assert raised.value.__cause__ is None
        assert "chapter:1" not in str(raised.value)


def test_publication_plan_is_deeply_immutable_and_uses_only_static_targets() -> None:
    plan = build_publication_plan(
        _package((_project_record(),)),
        COMMAND_ID,
        "Imported",
    )

    assert isinstance(plan, ProjectPublicationPlan)
    assert all(isinstance(batch, ImportInsertBatch) for batch in plan.batches)
    assert plan.batches[0].table == "projects"
    assert plan.batches[0].columns[:2] == ("id", "title")
    with pytest.raises((AttributeError, TypeError)):
        plan.batches[0].rows[0] += ("mutation",)
    with pytest.raises(Exception, match="^invalid project import archive$"):
        ImportInsertBatch("projects", plan.batches[0].columns, ((*plan.batches[0].rows[0][:-1], {}),))
    with pytest.raises(Exception, match="^invalid project import archive$"):
        ImportInsertBatch("package_supplied_table", ("id",), (("id",),))
    with pytest.raises(Exception, match="^invalid project import archive$"):
        ProjectPublicationPlan(COMMAND_ID, plan.target_project_id, "a" * 64, [], (), (), {})


@pytest.mark.parametrize("case", ["dangling", "wrong_type", "extra", "hash"])
def test_publication_failure_matrix_is_fixed_and_never_echoes_values(case: str) -> None:
    project = _project_record()
    secret = "creative-seed:987654"
    if case == "dangling":
        records = (project, PackageRecord("project-model-binding-revision", "project-model-binding-revision:1", data={
            "sourceProjectLogicalId": secret,
        }))
        package = _package(records)
    elif case == "wrong_type":
        records = (
            project,
            PackageRecord("creative-seed", secret, data={"label": "Seed"}),
            PackageRecord("project-model-binding-revision", "project-model-binding-revision:1", data={"sourceProjectLogicalId": secret}),
        )
        package = _package(records)
    elif case == "extra":
        package = _package((project,))
        package = VerifiedProjectPackage(
            package.archive_path, package.package_hash, package.manifest_hash, package.manifest,
            MappingProxyType({("project", "project:2"): project}), package.entry_index, package.summary,
        )
    else:
        records = (
            project,
            PackageRecord("creative-seed", "creative-seed:1", data={"label": "Seed"}),
            PackageRecord("creative-seed-revision", "creative-seed-revision:1", data={
                "seedLogicalId": "creative-seed:1", "revision": 1, "payload": SEED_PAYLOAD,
                "contentHash": "f" * 64,
            }),
        )
        package = _package(records)

    with pytest.raises(Exception, match="^invalid project import archive$") as raised:
        build_publication_plan(package, COMMAND_ID, "Imported")

    assert raised.value.__cause__ is None
    assert secret not in str(raised.value)


def _ddl_contract() -> dict[str, tuple[set[str], set[str]]]:
    schema_root = Path(__file__).parents[2] / "schema"
    sql = "\n".join(path.read_text(encoding="utf-8") for path in sorted(schema_root.glob("*.sql")))
    result: dict[str, tuple[set[str], set[str]]] = {}
    for match in re.finditer(r"CREATE TABLE ([a-z0-9_]+) \((.*?)\) ENGINE=", sql, re.DOTALL):
        columns: set[str] = set()
        required: set[str] = set()
        for raw in match.group(2).splitlines():
            line = raw.strip().rstrip(",")
            column = re.match(r"^([a-z][a-z0-9_]*)\s+(.+)$", line)
            if column is None or column.group(1).upper() in {"PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT", "KEY"}:
                continue
            name, declaration = column.groups()
            columns.add(name)
            if "NOT NULL" in declaration.upper() and "DEFAULT" not in declaration.upper():
                required.add(name)
        result[match.group(1)] = (columns, required)
    return result


def _assert_plan_foreign_keys_exist(plan: ProjectPublicationPlan) -> None:
    schema_root = Path(__file__).parents[2] / "schema"
    sql = "\n".join(path.read_text(encoding="utf-8") for path in sorted(schema_root.glob("*.sql")))
    bodies = {
        match.group(1): match.group(2)
        for match in re.finditer(r"CREATE TABLE ([a-z0-9_]+) \((.*?)\) ENGINE=", sql, re.DOTALL)
    }
    rows: dict[str, list[dict[str, object]]] = {}
    for batch in plan.batches:
        rows.setdefault(batch.table, []).extend(
            dict(zip(batch.columns, values, strict=True)) for values in batch.rows
        )
    for child, child_rows in rows.items():
        for match in re.finditer(
            r"FOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s+([a-z0-9_]+)\s*\(([^)]+)\)",
            bodies[child], re.IGNORECASE | re.DOTALL,
        ):
            child_columns = tuple(value.strip() for value in match.group(1).split(","))
            parent, parent_text = match.group(2), match.group(3)
            if parent not in rows:
                continue
            parent_columns = tuple(value.strip() for value in parent_text.split(","))
            parent_keys = {
                tuple(parent_row[column] for column in parent_columns)
                for parent_row in rows[parent]
                if all(column in parent_row for column in parent_columns)
            }
            for child_row in child_rows:
                if not all(column in child_row for column in child_columns):
                    continue
                key = tuple(child_row[column] for column in child_columns)
                if any(value is None for value in key):
                    continue
                assert key in parent_keys, f"missing FK {child}{child_columns} -> {parent}{parent_columns}"


def test_publication_batches_match_real_schema_and_closed_record_handlers() -> None:
    revision = PackageRecord("project-model-binding-revision", "project-model-binding-revision:1", revision=1, data={
        "revision": 1, "contentHash": "d" * 64, "sourceProjectLogicalId": "project:1", "createdAt": 3,
    })
    items = tuple(
        PackageRecord("project-model-binding-item", f"project-model-binding-item:{index}", order=index, data={
            "bindingRevisionLogicalId": revision.logical_id, "taskKey": key, "resolutionStatus": "bound",
            "providerName": "remote", "modelName": "model", "itemHash": "e" * 64,
        })
        for index, key in enumerate(sorted(TASK_KEYS), 1)
    )
    head = PackageRecord("project-model-binding-head", "project-model-binding-head:1", data={
        "revision": 1, "bindingRevisionLogicalId": revision.logical_id, "contentHash": "d" * 64, "updatedAt": 4,
    })
    asset = PackageRecord("asset", "asset:1", revision=1, data={
        "assetKind": "style-template", "stableKey": "import/style", "revision": 1,
        "name": "Style", "payload": {"voice": "clean"}, "provenance": {},
        "contentHash": canonical_hash({"voice": "clean"}), "status": "active", "createdAt": 5,
    })
    plan = build_publication_plan(_package((_project_record(), revision, *items, head, asset)), COMMAND_ID, "Imported")
    ddl = _ddl_contract()

    assert set(_RECORD_ENCODERS) | set(_SPECIAL_RECORD_HANDLERS) == FORMAL_ENTITY_TYPES | RECONSTRUCTED_ENTITY_TYPES
    assert set(_RECORD_ENCODERS).isdisjoint(_SPECIAL_RECORD_HANDLERS)
    for table, encoded_columns in STATIC_TABLE_COLUMNS.items():
        assert table in ddl
        columns, required = ddl[table]
        assert set(encoded_columns) <= columns
        assert required <= set(encoded_columns)
    for batch in plan.batches:
        assert batch.table in ddl
        columns, required = ddl[batch.table]
        assert set(batch.columns) <= columns
        assert required <= set(batch.columns)
    assert next(batch for batch in plan.batches if batch.table == "project_model_binding_items").columns == (
        "binding_revision_id", "task_key", "resolution_status", "provider_id",
        "provider_name_snapshot", "model_name_snapshot", "item_hash",
    )
    assert "frozen_import_assets" not in {batch.table for batch in plan.batches}


def test_static_publication_order_places_every_real_fk_parent_before_child() -> None:
    schema_root = Path(__file__).parents[2] / "schema"
    sql = "\n".join(path.read_text(encoding="utf-8") for path in sorted(schema_root.glob("*.sql")))
    bodies = {
        match.group(1): match.group(2)
        for match in re.finditer(r"CREATE TABLE ([a-z0-9_]+) \((.*?)\) ENGINE=", sql, re.DOTALL)
    }
    positions = {table: index for index, table in enumerate(PUBLICATION_TABLE_ORDER)}

    assert tuple(positions) == PUBLICATION_TABLE_ORDER
    assert set(PUBLICATION_TABLE_ORDER) == set(STATIC_TABLE_COLUMNS)
    for child in PUBLICATION_TABLE_ORDER:
        for parent in set(re.findall(r"REFERENCES\s+([a-z0-9_]+)", bodies[child], re.IGNORECASE)) & set(positions):
            assert positions[parent] < positions[child], f"{parent} must precede {child}"


def test_story_engine_option_reconstructs_stable_inert_batch_container() -> None:
    batch = PackageRecord("story-engine-batch", "story-engine-batch:1", data={
        "status": "succeeded", "contentHash": "c" * 64, "createdAt": 9, "completedAt": 9,
    })
    option = PackageRecord("story-engine-option", "story-engine-option:1", data={
        "batchLogicalId": batch.logical_id, "selectionRevision": 1, "optionOrder": 1, "payload": {"title": "Option"},
        "contentHash": "a" * 64, "createdAt": 9,
    })
    selected = PackageRecord("project-selected-seed", "project-selected-seed:1", data={
        "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1",
        "seedHash": "b" * 64, "selectionRevision": 1, "selectedAt": 1, "updatedAt": 1,
    })
    ids = {
        ("story-engine-batch", batch.logical_id): str(UUID(int=1)),
        ("story-engine-option", option.logical_id): str(UUID(int=2)),
    }
    rewritten = {
        (option.entity_type, option.logical_id): dict(option.data),
        (selected.entity_type, selected.logical_id): {
            **dict(selected.data), "seedLogicalId": str(UUID(int=3)),
            "seedRevisionLogicalId": str(UUID(int=4)),
        },
    }

    def row(command_id: str) -> dict[str, object]:
        batches = encode_publication_batches(
            (option,), rewritten, ids, command_id=command_id,
            target_project_id=str(UUID(int=5)), new_title="Imported",
            source_records=(batch, option, selected),
        )
        encoded = next(item for item in batches if item.table == "story_engine_batches")
        return dict(zip(encoded.columns, encoded.rows[0], strict=True))

    first = row(COMMAND_ID)
    assert first == row(COMMAND_ID)
    assert first["idempotency_key"] != row("38ca226b-7199-4cc4-a3e9-98c6993b17c4")["idempotency_key"]
    assert first["source_type"] == "manual" and first["status"] == "succeeded"
    assert first["request_json"] == "{}" and first["created_at"] == first["finished_at"]
    for field in ("binding_revision_id", "binding_hash", "provider_id", "model_name_snapshot", "attempt_id", "attempt_started_at", "lease_expires_at", "raw_response_text", "raw_response_hash", "public_error_code"):
        assert first[field] is None


@pytest.mark.parametrize("option_count", (2, 3))
def test_public_plan_deduplicates_one_derived_story_batch_for_multiple_options(option_count: int) -> None:
    from backend.domain.story_engines import StoryEngineOption

    engine = StoryEngineOption.model_validate({
        "name": "Engine", "storyPromise": "promise", "protagonistDesire": "desire",
        "sustainedPressure": "pressure", "growthDirection": "growth", "conflictLoop": "loop",
        "ensembleRoles": ({"role": "ally", "purpose": "help"},), "advantageAndCost": "cost",
        "satisfactionSources": ("satisfaction",), "longFormVariation": ("variation",),
        "endingAnchor": "ending", "risks": ("risk",), "differentiation": "different",
    })
    seed_hash = canonical_hash(SEED_PAYLOAD)
    records = [
        _project_record(),
        PackageRecord("creative-seed", "creative-seed:1", data={"status": "candidate", "createdAt": 1, "updatedAt": 1}),
        PackageRecord("creative-seed-revision", "creative-seed-revision:1", revision=1, data={"seedLogicalId": "creative-seed:1", "revision": 1, "payload": SEED_PAYLOAD, "contentHash": seed_hash, "createdAt": 1}),
        PackageRecord("project-selected-seed", "project-selected-seed:1", data={"seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": seed_hash, "selectionRevision": 1, "selectedAt": 1, "updatedAt": 1}),
        PackageRecord("story-engine-batch", "story-engine-batch:1", data={"status": "succeeded", "createdAt": 2, "completedAt": 2}),
        *(PackageRecord("story-engine-option", f"story-engine-option:{index}", order=index, data={"batchLogicalId": "story-engine-batch:1", "selectionRevision": 1, "optionOrder": index, "payload": engine.model_dump(mode="json", by_alias=True), "contentHash": canonical_hash(engine), "createdAt": 2}) for index in range(1, option_count + 1)),
    ]

    plan = build_publication_plan(_package(tuple(records)), COMMAND_ID, "Imported")

    assert len(_rows(plan, "story_engine_batches")) == 1
    assert len(_rows(plan, "story_engine_options")) == option_count


def test_public_plan_deduplicates_corpus_source_across_multiple_revisions() -> None:
    def corpus(logical_id: str, revision: int, digest: str) -> PackageRecord:
        return PackageRecord("corpus-revision", logical_id, revision=revision, data={
            "sourceKey": "shared-source", "revision": revision, "relativePath": "source.txt",
            "displayName": "Source", "author": "Author", "referenceTags": [], "notes": "notes",
            "provenance": {}, "contentHash": digest, "byteLength": 7, "encoding": "utf-8",
            "parserVersion": "p1", "normalizerVersion": "n1", "fragmenterVersion": "f1",
            "indexVersion": "i1", "status": "analyzed", "importedAt": revision,
            "analyzedAt": revision, "createdAt": revision, "chapters": [], "fragments": [],
        })

    plan = build_publication_plan(_package((
        _project_record(), corpus("corpus-revision:1", 1, "a" * 64),
        corpus("corpus-revision:2", 2, "b" * 64),
    )), COMMAND_ID, "Imported")

    assert len(_rows(plan, "corpus_sources")) == 1
    assert len(_rows(plan, "corpus_source_revisions")) == 2
    assert len(_rows(plan, "corpus_blobs")) == 2


def test_target_projection_is_rebuilt_from_rewritten_canon_ids() -> None:
    entity_id = str(UUID(int=21))
    revision_id = str(UUID(int=22))
    event_id = str(UUID(int=23))
    rewritten = {
        ("canon-revision", "canon-revision:1"): {"revisionNumber": 1},
        ("canon-event", "canon-event:1"): {
            "canonRevisionLogicalId": revision_id,
            "revisionNumber": 1,
            "eventOrder": 1,
            "entityLogicalId": entity_id,
            "factKind": "stable_definition",
            "fieldPath": "profile.name",
            "value": "Target Name",
            "evidence": {"source": "chapter"},
            "confirmationStatus": "confirmed",
        },
    }

    projection = _target_projection(
        rewritten,
        {
            ("canon-revision", "canon-revision:1"): revision_id,
            ("canon-event", "canon-event:1"): event_id,
        },
    )

    assert projection["revision"] == 1
    assert projection["currentState"] == {entity_id: {"profile.name": "Target Name"}}
    assert projection["memories"][entity_id][0]["eventId"] == event_id
    assert re.fullmatch(r"[0-9a-f]{64}", projection["contentHash"])


def test_finalization_receipt_requires_exact_production_shape_and_rewrites_typed_ids() -> None:
    record = PackageRecord("finalization-record", "finalization-record:1", data={
        "chapterLogicalId": "chapter:1",
        "candidateLogicalId": "draft-candidate:1",
        "changeSetLogicalId": "finalization-change-set:1",
        "resultPayload": {
            "finalChapterId": "final-chapter:1",
            "canonRevision": 4,
            "projectionHash": "a" * 64,
            "planningRevisionId": "planning-revision:1",
            "planningRevision": 3,
            "planningHash": "b" * 64,
        },
    })
    ids = {
        ("final-chapter", "final-chapter:1"): str(UUID(int=31)),
        ("planning-revision", "planning-revision:1"): str(UUID(int=32)),
        ("chapter", "chapter:1"): str(UUID(int=33)),
        ("draft-candidate", "draft-candidate:1"): str(UUID(int=34)),
        ("finalization-change-set", "finalization-change-set:1"): str(UUID(int=35)),
    }

    rewritten = _rewrite_record_data(record, ids, {})

    assert rewritten["resultPayload"] == {
        "finalChapterId": ids[("final-chapter", "final-chapter:1")],
        "canonRevision": 4,
        "projectionHash": "a" * 64,
        "planningRevisionId": ids[("planning-revision", "planning-revision:1")],
        "planningRevision": 3,
        "planningHash": "b" * 64,
    }
    malformed = PackageRecord("finalization-record", "finalization-record:1", data={
        **dict(record.data),
        "resultPayload": {**dict(record.data["resultPayload"]), "extra": "project:1"},
    })
    with pytest.raises(Exception, match="^invalid project import archive$") as raised:
        _rewrite_record_data(malformed, ids, {})
    assert raised.value.__cause__ is None
    assert "project:1" not in str(raised.value)


def test_real_encoders_handle_multiple_engine_options_experience_asset_and_scalar_canon_value() -> None:
    batch = PackageRecord("story-engine-batch", "story-engine-batch:1", data={"createdAt": 1})
    options = tuple(
        PackageRecord("story-engine-option", f"story-engine-option:{index}", order=index, data={
            "batchLogicalId": batch.logical_id, "selectionRevision": 1, "optionOrder": index,
            "payload": {"title": f"Option {index}"}, "contentHash": chr(96 + index) * 64,
            "createdAt": 1,
        })
        for index in (1, 2)
    )
    experience = PackageRecord("asset", "asset:1", data={
        "assetKind": "experience-card", "revision": 1, "name": "Experience", "category": "plot_organization",
        "payload": {"lesson": "keep"}, "provenance": {}, "contentHash": "c" * 64,
        "status": "active", "createdAt": 1,
    })
    event = PackageRecord("canon-event", "canon-event:1", data={
        "canonRevisionLogicalId": "canon-revision:1", "revisionNumber": 1, "eventOrder": 1,
        "entityLogicalId": "canon-entity:1", "factKind": "stable_definition", "fieldPath": "name",
        "value": "scalar", "evidence": {}, "effectiveStartChapter": None, "effectiveEndChapter": None,
        "assertionOperator": "equals", "valueCardinality": "single", "confirmationStatus": "confirmed",
        "createdAt": 1,
    })
    selected = PackageRecord("project-selected-seed", "project-selected-seed:1", data={})
    ids = {
        ("story-engine-batch", batch.logical_id): str(UUID(int=41)),
        **{(item.entity_type, item.logical_id): str(UUID(int=42 + index)) for index, item in enumerate(options)},
        ("asset", experience.logical_id): str(UUID(int=44)),
        ("canon-event", event.logical_id): str(UUID(int=45)),
    }
    rewritten = {
        **{(item.entity_type, item.logical_id): dict(item.data) for item in (*options, experience)},
        (selected.entity_type, selected.logical_id): {
            "selectionRevision": 1, "seedLogicalId": str(UUID(int=46)),
            "seedRevisionLogicalId": str(UUID(int=47)), "seedHash": "d" * 64,
        },
        (event.entity_type, event.logical_id): {
            **dict(event.data), "canonRevisionLogicalId": str(UUID(int=48)),
            "entityLogicalId": str(UUID(int=49)),
        },
    }

    batches = encode_publication_batches(
        (*options, experience, event), rewritten, ids, command_id=COMMAND_ID,
        target_project_id=str(UUID(int=50)), new_title="Imported",
        source_records=(batch, *options, selected, experience, event),
    )

    by_table = {item.table: item for item in batches}
    assert len(by_table["story_engine_batches"].rows) == 1
    assert len(by_table["story_engine_options"].rows) == 2
    assert len(by_table["experience_cards"].rows[0]) == len(by_table["experience_cards"].columns)
    canon_row = dict(zip(by_table["canon_events"].columns, by_table["canon_events"].rows[0], strict=True))
    assert canon_row["value_json"] == '"scalar"'


def test_production_planning_then_outline_topology_rehashes_target_authorities() -> None:
    from backend.domain.chapter_outlines import DraftChapterOutline, EditableChapterOutlineContent, OutlineCapacityPolicy, normalize_chapter_outline
    from backend.domain.planning import DraftPlanningAggregate, normalize_planning_aggregate

    allocated = iter((
        "planning-volume:1", "planning-plot:1", "story-block:1",
        "planning-stage:1", "scene-task:1",
    ))
    planning = normalize_planning_aggregate(
        DraftPlanningAggregate.model_validate({
            "activeStoryBlockRef": "block", "volumes": [{
                "clientNodeKey": "volume", "order": 1, "title": "Volume", "coreChange": "change",
                "mainPressure": "pressure", "ensembleFocus": [], "forbiddenEvents": [],
            }], "plots": [{
                "clientNodeKey": "plot", "order": 1, "title": "Plot", "plotType": "main",
                "storyQuestion": "question", "futureDirection": "future", "expectedPayoff": "payoff",
                "relatedCharacters": [],
            }], "storyBlocks": [{
                "clientNodeKey": "block", "volumeRef": "volume", "plotRefs": ["plot"], "order": 1,
                "title": "Block", "entrySituation": "entry", "blockGoal": "goal", "mainPressure": "pressure",
                "expectedChange": "change", "openQuestions": [], "involvedCharacters": [], "stages": [{
                    "clientNodeKey": "stage", "order": 1, "title": "Stage", "purpose": "purpose",
                    "dramaticQuestion": "question", "sceneTasks": [{
                        "clientNodeKey": "task", "order": 1, "task": "write", "completionEvidence": "done",
                    }],
                }],
            }],
        }),
        previous_confirmed=None, previous_draft=None, id_factory=lambda: next(allocated),
    )
    capacity = OutlineCapacityPolicy(targetMin=1000, targetMax=2000, softCeiling=2500)
    block = planning.story_blocks[0]
    outline = normalize_chapter_outline(
        DraftChapterOutline.model_validate({
            "schemaVersion": "chapter-outline-v1", "chapterNumber": 1,
            "planningRevisionId": "planning-revision:1", "planningRevision": 1,
            "planningHash": planning.content_hash,
            "volumeRef": planning.volumes[0].model_dump(mode="json", by_alias=True, include={"id", "revision", "content_hash"}),
            "storyBlockRef": block.model_dump(mode="json", by_alias=True, include={"id", "revision", "content_hash"}),
            "stageRefs": [block.stages[0].model_dump(mode="json", by_alias=True, include={"id", "revision", "content_hash"})],
            "sceneTaskRefs": [block.stages[0].scene_tasks[0].model_dump(mode="json", by_alias=True, include={"id", "revision", "content_hash"})],
            "chapterGoal": "goal", "expectedCharacters": [], "continuation": [], "plannedTasks": ["write"],
            "scenes": ["scene"], "forbiddenEarlyEvents": [], "capacityPolicy": capacity.model_dump(mode="json", by_alias=True),
        }),
        planning=planning, authoritative_chapter_number=1, planning_revision_id="planning-revision:1",
        planning_revision=1, capacity_policy=capacity, canon_revision=0, projection_revision=0,
        projection_hash="e" * 64,
    )
    planning_record = PackageRecord("planning-revision", "planning-revision:1", revision=1, data={
        "revision": 1, "parentRevision": 0, "selectionRevision": 1,
        "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1",
        "seedHash": "a" * 64, "contractRevision": 1,
        "creationContractLogicalId": "creation-contract:1", "creationHash": "b" * 64,
        "styleContractLogicalId": "style-contract:1", "styleHash": "c" * 64,
        "bibleRevision": 1, "bibleRevisionLogicalId": "creation-bible-revision:1", "bibleHash": "d" * 64,
        "payload": planning.model_dump(mode="json", by_alias=True), "contentHash": planning.content_hash, "createdAt": 1,
    })
    outline_record = PackageRecord("chapter-outline-revision", "chapter-outline-revision:1", revision=1, data={
        "chapterNumber": 1, "revision": 1, "planningRevisionLogicalId": planning_record.logical_id,
        "payload": outline.model_dump(mode="json", by_alias=True), "contentHash": outline.content_hash, "createdAt": 2,
    })
    canon_revision = PackageRecord("canon-revision", "canon-revision:1", data={
        "revisionNumber": 1, "parentRevisionNumber": 0, "sourceType": "finalization",
        "sourceLogicalId": "finalization-change-set:1", "contentHash": "f" * 64, "createdAt": 3,
    })
    canon_event = PackageRecord("canon-event", "canon-event:1", data={
        "canonRevisionLogicalId": canon_revision.logical_id, "revisionNumber": 1, "eventOrder": 1,
        "entityLogicalId": "canon-entity:1", "factKind": "stable_definition", "fieldPath": "profile.name",
        "value": "Name", "evidence": {}, "effectiveStartChapter": None, "effectiveEndChapter": None,
        "assertionOperator": "equals", "valueCardinality": "single", "confirmationStatus": "confirmed", "createdAt": 3,
    })
    receipt_record = PackageRecord("finalization-record", "finalization-record:1", data={
        "chapterLogicalId": "chapter:1", "candidateLogicalId": "draft-candidate:1",
        "changeSetLogicalId": "finalization-change-set:1", "changeSetRevision": 1,
        "candidateHash": "1" * 64, "changeSetHash": "2" * 64,
        "expectedCanonRevision": 0, "committedCanonRevision": 1,
        "resultPayload": {
            "finalChapterId": "final-chapter:1", "canonRevision": 1, "projectionHash": "3" * 64,
            "planningRevisionId": planning_record.logical_id, "planningRevision": 1,
            "planningHash": planning.content_hash,
        }, "resultHash": "4" * 64, "finalizedAt": 4,
    })
    identities = [
        ("project", "project:1"),
        (planning_record.entity_type, planning_record.logical_id),
        (outline_record.entity_type, outline_record.logical_id),
        (canon_revision.entity_type, canon_revision.logical_id), (canon_event.entity_type, canon_event.logical_id),
        (receipt_record.entity_type, receipt_record.logical_id),
        ("creative-seed", "creative-seed:1"), ("creative-seed-revision", "creative-seed-revision:1"),
        ("creation-contract", "creation-contract:1"), ("style-contract", "style-contract:1"),
        ("creation-bible-revision", "creation-bible-revision:1"),
        ("finalization-change-set", "finalization-change-set:1"), ("canon-entity", "canon-entity:1"),
        ("chapter", "chapter:1"), ("draft-candidate", "draft-candidate:1"), ("final-chapter", "final-chapter:1"),
        *_publication_embedded_identities(planning_record), *_publication_embedded_identities(outline_record),
    ]

    identity_map = build_import_identity_map(COMMAND_ID, identities)
    rewritten = _rewrite_records(
        _package((planning_record, outline_record, canon_revision, canon_event, receipt_record)), identity_map,
        COMMAND_ID,
    )
    target_planning = rewritten[(planning_record.entity_type, planning_record.logical_id)]
    target_outline = rewritten[(outline_record.entity_type, outline_record.logical_id)]

    assert target_planning["contentHash"] != planning.content_hash
    assert target_outline["planningHash"] == target_planning["contentHash"]
    assert target_outline["payload"]["planningHash"] == target_planning["contentHash"]
    assert target_outline["payload"]["volumeRef"]["id"] != planning.volumes[0].id
    assert target_outline["contentHash"] != outline.content_hash
    target_canon = rewritten[(canon_revision.entity_type, canon_revision.logical_id)]
    target_receipt = rewritten[(receipt_record.entity_type, receipt_record.logical_id)]
    expected_projection = _target_projection(rewritten, identity_map.ids, revision=1)
    assert target_canon["contentHash"] == expected_projection["contentHash"]
    assert target_receipt["resultPayload"]["planningHash"] == target_planning["contentHash"]
    assert target_receipt["resultPayload"]["projectionHash"] == expected_projection["contentHash"]
    assert target_receipt["resultHash"] == canonical_hash(target_receipt["resultPayload"])


def test_full_production_model_package_builds_closed_publication_plan() -> None:
    from backend.domain.bibles import BiblePayload, canonical_bible_hash
    from backend.domain.chapter_outlines import (
        ChapterOutline,
        DraftChapterOutline,
        EditableChapterOutlineContent,
        OutlineCapacityPolicy,
        normalize_chapter_outline,
    )
    from backend.domain.contracts import CreationContractPayload
    from backend.domain.finalization import FinalizationChangeSet, QualityFinding, QualityReportPayload, change_set_hash
    from backend.domain.model_bindings import BindingItem, BindingRevision
    from backend.domain.planning import DraftPlanningAggregate, PlanningAggregate, normalize_planning_aggregate, planning_content_hash
    from backend.domain.seeds import SeedPayload
    from backend.domain.story_engines import StoryEngineOption
    from backend.services.contracts.drafts import ContractDraftPayload

    seed = SeedPayload.model_validate(SEED_PAYLOAD)
    engine = StoryEngineOption.model_validate({
        "name": "Engine", "storyPromise": "promise", "protagonistDesire": "desire",
        "sustainedPressure": "pressure", "growthDirection": "growth", "conflictLoop": "loop",
        "ensembleRoles": ({"role": "ally", "purpose": "help"},), "advantageAndCost": "cost",
        "satisfactionSources": ("satisfaction",), "longFormVariation": ("variation",),
        "endingAnchor": "ending", "risks": ("risk",), "differentiation": "different",
    })
    placeholder = "11111111-1111-4111-8111-111111111111"
    style_asset_hash = canonical_hash({"voice": "clear"})
    experience_asset_hash = canonical_hash({"lesson": "keep"})
    contract_model = CreationContractPayload.model_validate({
        "schemaVersion": "creation-contract-v1", "channelProfileKey": "channel-v1",
        "genreProfileKey": "genre-v1", "qualityCharterVersion": "quality-v1", "selectionRevision": 1,
        "selectedSeed": seed, "seedRevisionId": placeholder, "seedHash": canonical_hash(seed),
        "selectedEngine": engine, "engineOptionId": placeholder, "engineHash": canonical_hash(engine),
        "primaryStyleRef": {"id": placeholder, "revision": 1, "contentHash": style_asset_hash},
        "experienceCardRefs": ({"id": placeholder, "revision": 1, "contentHash": experience_asset_hash},), "corpusSourceRefs": ({
            "id": placeholder, "revisionId": placeholder, "revision": 1,
            "contentHash": "c" * 64, "selectionMode": "author",
            "fragments": ({"chapterId": placeholder, "fragmentId": placeholder,
                           "fragmentHash": "f" * 64, "chapterCharStart": 1,
                           "chapterCharEnd": 6, "referenceUse": "structure"},),
            "pinnedHistoricalRevision": False,
        },), "targetTotalWords": 100_000,
        "expectedVolumeCount": 4, "expectedChapterCount": 50,
        "chapterWordRangePreference": (1500, 2500), "prohibitedDirections": ("none",),
    })
    contract_payload = contract_model.model_dump(mode="json", by_alias=True)
    contract_payload["seedRevisionId"] = "creative-seed-revision:1"
    contract_payload["engineOptionId"] = "story-engine-option:1"
    contract_payload["primaryStyleRef"]["id"] = "asset:1"
    contract_payload["experienceCardRefs"][0]["id"] = "asset:2"
    contract_payload["corpusSourceRefs"][0]["id"] = "corpus-revision:1"
    contract_payload["corpusSourceRefs"][0]["revisionId"] = "corpus-revision:1"
    contract_payload["corpusSourceRefs"][0]["fragments"][0]["chapterId"] = "corpus-chapter:2"
    contract_payload["corpusSourceRefs"][0]["fragments"][0]["fragmentId"] = "corpus-fragment:2"

    design_item = lambda kind: {"id": kind.replace("bible-", "") + "-1", "text": f"{kind} text"}
    bible = BiblePayload.model_validate({
        "premiseAndPromise": "premise", "worldRules": (design_item("bible-world-rule"),),
        "powerOrProgressionSystem": "power", "protagonist": "hero",
        "coreCast": (design_item("bible-core-cast"),), "factions": (design_item("bible-faction"),),
        "longTermConflicts": (design_item("bible-long-term-conflict"),),
        "relationshipDynamics": (design_item("bible-relationship-dynamic"),),
        "toneAndNarrativeBoundaries": "tone",
        "continuityGuardrails": (design_item("bible-continuity-guardrail"),),
        "openDesignQuestions": (design_item("bible-open-design-question"),),
    })
    bible_payload = bible.model_dump(mode="json", by_alias=True)
    for field, kind in {
        "worldRules": "bible-world-rule", "coreCast": "bible-core-cast", "factions": "bible-faction",
        "longTermConflicts": "bible-long-term-conflict", "relationshipDynamics": "bible-relationship-dynamic",
        "continuityGuardrails": "bible-continuity-guardrail", "openDesignQuestions": "bible-open-design-question",
    }.items():
        bible_payload[field][0]["id"] = f"{kind}:1"
    allocated = iter(("planning-volume:1", "planning-plot:1", "story-block:1", "planning-stage:1", "scene-task:1"))
    planning_draft = DraftPlanningAggregate.model_validate({
            "activeStoryBlockRef": "block",
            "volumes": [{"clientNodeKey": "volume", "order": 1, "title": "Volume", "coreChange": "change", "mainPressure": "pressure", "ensembleFocus": [], "forbiddenEvents": []}],
            "plots": [{"clientNodeKey": "plot", "order": 1, "title": "Plot", "plotType": "main", "storyQuestion": "question", "futureDirection": "future", "expectedPayoff": "payoff", "relatedCharacters": []}],
            "storyBlocks": [{"clientNodeKey": "block", "volumeRef": "volume", "plotRefs": ["plot"], "order": 1, "title": "Block", "entrySituation": "entry", "blockGoal": "goal", "mainPressure": "pressure", "expectedChange": "change", "openQuestions": [], "involvedCharacters": [], "stages": [{"clientNodeKey": "stage", "order": 1, "title": "Stage", "purpose": "purpose", "dramaticQuestion": "question", "sceneTasks": [{"clientNodeKey": "task", "order": 1, "task": "write", "completionEvidence": "done"}]}]}],
        })
    planning = normalize_planning_aggregate(
        planning_draft, previous_confirmed=None, previous_draft=None, id_factory=lambda: next(allocated),
    )
    capacity = OutlineCapacityPolicy(targetMin=1500, targetMax=2500, softCeiling=3000)
    block = planning.story_blocks[0]
    ref = lambda value: value.model_dump(mode="json", by_alias=True, include={"id", "revision", "content_hash"})
    outline = normalize_chapter_outline(
        DraftChapterOutline.model_validate({
            "schemaVersion": "chapter-outline-v1", "chapterNumber": 1,
            "planningRevisionId": "planning-revision:1", "planningRevision": 1, "planningHash": planning.content_hash,
            "volumeRef": ref(planning.volumes[0]), "storyBlockRef": ref(block), "stageRefs": [ref(block.stages[0])],
            "sceneTaskRefs": [ref(block.stages[0].scene_tasks[0])], "chapterGoal": "goal",
            "expectedCharacters": ["hero"], "continuation": [], "plannedTasks": ["write"], "scenes": ["scene"],
            "forbiddenEarlyEvents": [], "capacityPolicy": capacity.model_dump(mode="json", by_alias=True),
        }), planning=planning, authoritative_chapter_number=1, planning_revision_id="planning-revision:1",
        planning_revision=1, capacity_policy=capacity, canon_revision=0, projection_revision=0,
        projection_hash="9" * 64,
    )
    editable_outline_payload = {
        key: value for key, value in outline.model_dump(mode="json", by_alias=True).items()
        if key in {field.alias for field in EditableChapterOutlineContent.model_fields.values()}
    }
    editable_outline_payload["schemaVersion"] = "chapter-outline-draft-v1"
    editable_outline = EditableChapterOutlineContent.model_validate(editable_outline_payload)
    draft_outline_payload = outline.model_dump(mode="json", by_alias=True, exclude={"content_hash", "canon_revision", "projection_revision", "projection_hash"})
    draft_outline = DraftChapterOutline.model_validate(draft_outline_payload)
    evidence = {"startScalar": 0, "endScalar": 4, "excerptHash": "8" * 64, "confidence": 0.9, "rationale": "text"}
    change_set = FinalizationChangeSet.model_validate({
        "schemaVersion": "finalization-changeset-v1", "title": "Final", "summary": "summary",
        "existingEntityIds": ("canon-entity:1",),
        "entities": ({"id": "finalization-entity:1", "entityType": "person", "canonicalName": "New"},),
        "aliases": ({"id": "finalization-alias:1", "entityId": "finalization-entity:1", "alias": "Alias"},),
        "canonEvents": ({"id": "finalization-event:1", "entityId": "canon-entity:1", "factKind": "stable_definition", "fieldPath": "profile.name", "value": "Name", "evidence": evidence, "assertionOperator": "equals", "valueCardinality": "single"},),
        "storyProgressEvents": ({"id": "finalization-progress-event:1", "targetType": "story_block", "targetId": "story-block:1", "status": "advanced", "evidence": evidence},),
        "planningPatches": ({"id": "finalization-planning-patch:1", "targetType": "story_block", "targetId": "story-block:1", "expectedRevision": 1, "expectedHash": block.content_hash, "fieldPath": "title", "replacement": "Updated", "evidence": evidence},),
        "planningSuggestions": ({"id": "finalization-planning-suggestion:1", "targetId": "story-block:1", "message": "Next", "evidence": evidence},),
    })
    finding = QualityFinding.model_validate({
        "id": "quality-finding:1", "dimension": "continuity", "reason": "reason",
        "suggestedAction": "fix", "evidence": evidence,
    })
    quality = QualityReportPayload(status="completed", deterministicBlocks=(), findings=(finding,))
    candidate_text = "candidate prose project:1"
    candidate_hash = sha256(candidate_text.encode()).hexdigest()
    working_text = "working prose project:1"
    working_hash = sha256(working_text.encode()).hexdigest()

    records: list[PackageRecord] = [
        _project_record(),
        PackageRecord("creative-seed", "creative-seed:1", data={"status": "candidate", "createdAt": 1, "updatedAt": 1}),
        PackageRecord("creative-seed-revision", "creative-seed-revision:1", revision=1, data={"seedLogicalId": "creative-seed:1", "revision": 1, "payload": seed.model_dump(mode="json", by_alias=True), "contentHash": canonical_hash(seed), "createdAt": 1}),
        PackageRecord("project-selected-seed", "project-selected-seed:1", data={"seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "selectionRevision": 1, "selectedAt": 1, "updatedAt": 1}),
        PackageRecord("story-engine-batch", "story-engine-batch:1", data={"status": "succeeded", "createdAt": 2, "completedAt": 2}),
        PackageRecord("story-engine-option", "story-engine-option:1", order=1, data={"batchLogicalId": "story-engine-batch:1", "selectionRevision": 1, "optionOrder": 1, "payload": engine.model_dump(mode="json", by_alias=True), "contentHash": canonical_hash(engine), "createdAt": 2}),
    ]
    binding_revision = PackageRecord("project-model-binding-revision", "project-model-binding-revision:1", revision=1, data={"revision": 1, "contentHash": "7" * 64, "sourceProjectLogicalId": "project:1", "createdAt": 2})
    records.extend([binding_revision, *(PackageRecord("project-model-binding-item", f"project-model-binding-item:{index}", order=index, data={"bindingRevisionLogicalId": binding_revision.logical_id, "taskKey": key, "resolutionStatus": "bound", "providerName": "remote", "modelName": "remote-model", "itemHash": "6" * 64}) for index, key in enumerate(sorted(TASK_KEYS), 1)), PackageRecord("project-model-binding-head", "project-model-binding-head:1", data={"revision": 1, "bindingRevisionLogicalId": binding_revision.logical_id, "contentHash": "7" * 64, "updatedAt": 2})])
    contract_payload["modelBindingRef"] = {"id": binding_revision.logical_id, "revision": 1, "contentHash": "7" * 64}
    contract_draft_model = ContractDraftPayload.model_validate({
        "schemaVersion": "contract-draft-v2", "draftStage": "assets",
        "engineOptionId": placeholder, "engineHash": canonical_hash(engine),
        "channelProfileKey": "channel-v1", "genreProfileKey": "genre-v1",
        "qualityCharterVersion": "quality-v1", "targetTotalWords": 100_000,
        "expectedVolumeCount": 4, "expectedChapterCount": 50,
        "chapterWordRangePreference": (1500, 2500), "prohibitedDirections": ("none",),
        "primaryStyleRef": {"id": placeholder, "revision": 1, "contentHash": "a" * 64},
        "experienceCardRefs": (), "corpusSourceRefs": (), "likes": (), "dislikes": (),
        "seedRevisionId": placeholder, "seedHash": canonical_hash(seed),
        "modelBindingRef": {"id": placeholder, "revision": 1, "contentHash": "7" * 64},
    })
    contract_draft = contract_draft_model.model_dump(mode="json", by_alias=True)
    contract_draft["seedRevisionId"] = "creative-seed-revision:1"
    contract_draft["engineOptionId"] = "story-engine-option:1"
    contract_draft["primaryStyleRef"]["id"] = "asset:1"
    contract_draft["modelBindingRef"]["id"] = binding_revision.logical_id
    records.extend([
        PackageRecord("asset", "asset:1", revision=1, data={"assetKind": "style-template", "stableKey": "style", "revision": 1, "name": "Style", "payload": {"voice": "clear"}, "provenance": {}, "contentHash": style_asset_hash, "status": "active", "createdAt": 2}),
        PackageRecord("asset", "asset:2", revision=1, data={"assetKind": "experience-card", "stableKey": "experience", "revision": 1, "name": "Experience", "category": "plot_organization", "payload": {"lesson": "keep"}, "provenance": {}, "contentHash": experience_asset_hash, "status": "active", "createdAt": 2}),
        PackageRecord("asset", "asset:3", revision=1, data={"assetKind": "style-template", "stableKey": "other-style", "revision": 1, "name": "Other Style", "payload": {"voice": "other"}, "provenance": {}, "contentHash": canonical_hash({"voice": "other"}), "status": "active", "createdAt": 2}),
        PackageRecord("project-contract-draft", "project-contract-draft:1", revision=1, data={"revision": 1, "baseHeadRevision": 0, "selectionRevision": 1, "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "engineOptionLogicalId": "story-engine-option:1", "payload": contract_draft, "contentHash": canonical_hash(contract_draft_model), "updatedAt": 3}),
        PackageRecord("creation-contract", "creation-contract:1", revision=1, data={"revision": 1, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "bindingRevisionLogicalId": binding_revision.logical_id, "bindingHash": "7" * 64, "payload": contract_payload, "contentHash": "5" * 64, "createdAt": 3}),
        PackageRecord("style-contract", "style-contract:1", revision=1, data={"revision": 1, "creationContractLogicalId": "creation-contract:1", "payload": {"mergedStyle": {"voice": "clear"}, "likes": ["clarity"], "dislikes": ["noise"]}, "contentHash": "4" * 64, "createdAt": 3}),
        PackageRecord("style-contract-template-ref", "style-contract-template-ref:1", order=1, data={"styleContractLogicalId": "style-contract:1", "templateName": "Style", "templateRevision": 1, "contentHash": style_asset_hash}),
        PackageRecord("creation-contract-experience-ref", "creation-contract-experience-ref:1", order=1, data={"creationContractLogicalId": "creation-contract:1", "experienceTitle": "Experience", "experienceRevision": 1, "contentHash": experience_asset_hash}),
        PackageRecord("project-contract-head", "project-contract-head:1", revision=2, data={"revision": 2, "creationContractLogicalId": "creation-contract:2", "styleContractLogicalId": "style-contract:2", "contentHash": "4" * 64, "updatedAt": 3}),
        PackageRecord("contract-confirmation", "contract-confirmation:1", data={"status": "succeeded", "selectionRevision": 1, "creationContractLogicalId": "creation-contract:1", "styleContractLogicalId": "style-contract:1", "resultRevision": 1, "contentHash": "5" * 64, "createdAt": 3, "completedAt": 3}),
        PackageRecord("creation-bible-revision", "creation-bible-revision:1", revision=1, data={"revision": 1, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "contractRevision": 1, "creationContractLogicalId": "creation-contract:1", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:1", "styleHash": "4" * 64, "bindingRevisionLogicalId": binding_revision.logical_id, "bindingHash": "7" * 64, "policyVersion": "creation-bible-v1", "payload": bible_payload, "contentHash": canonical_bible_hash(bible), "createdAt": 4}),
        PackageRecord("project-bible-head", "project-bible-head:1", data={"revision": 2, "bibleRevisionLogicalId": "creation-bible-revision:2", "contentHash": canonical_bible_hash(bible), "updatedAt": 4}),
        PackageRecord("project-bible-draft", "project-bible-draft:1", revision=1, data={"revision": 1, "baseHeadRevision": 0, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "contractRevision": 1, "creationContractLogicalId": "creation-contract:1", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:1", "styleHash": "4" * 64, "bindingRevisionLogicalId": binding_revision.logical_id, "bindingHash": "7" * 64, "policyVersion": "creation-bible-v1", "payload": bible_payload, "contentHash": canonical_bible_hash(bible), "updatedAt": 4}),
        PackageRecord("bible-confirmation", "bible-confirmation:1", data={"status": "succeeded", "selectionRevision": 1, "contractRevision": 1, "creationContractLogicalId": "creation-contract:1", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:1", "styleHash": "4" * 64, "draftLogicalId": "project-bible-draft:1", "draftVersion": 1, "draftHash": canonical_bible_hash(bible), "bibleRevisionLogicalId": "creation-bible-revision:1", "resultRevision": 1, "contentHash": canonical_bible_hash(bible), "createdAt": 4, "completedAt": 4}),
        PackageRecord("planning-draft", "planning-draft:1", revision=1, data={"revision": 1, "baseHeadRevision": 0, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "contractRevision": 1, "creationContractLogicalId": "creation-contract:1", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:1", "styleHash": "4" * 64, "bibleRevision": 1, "bibleRevisionLogicalId": "creation-bible-revision:1", "bibleHash": canonical_bible_hash(bible), "payload": planning_draft.model_dump(mode="json", by_alias=True), "contentHash": canonical_hash(planning_draft), "updatedAt": 5}),
        PackageRecord("planning-draft", "planning-draft:2", revision=1, data={"draftRevision": 2, "baseHeadRevision": 1, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "contractRevision": 2, "creationContractLogicalId": "creation-contract:2", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:2", "styleHash": "4" * 64, "bibleRevision": 2, "bibleRevisionLogicalId": "creation-bible-revision:2", "bibleHash": canonical_bible_hash(bible), "payload": planning.model_dump(mode="json", by_alias=True), "contentHash": planning.content_hash, "updatedAt": 5}),
        PackageRecord("planning-revision", "planning-revision:1", revision=1, data={"revision": 1, "parentRevision": 0, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "contractRevision": 1, "creationContractLogicalId": "creation-contract:1", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:1", "styleHash": "4" * 64, "bibleRevision": 1, "bibleRevisionLogicalId": "creation-bible-revision:1", "bibleHash": canonical_bible_hash(bible), "payload": planning.model_dump(mode="json", by_alias=True), "contentHash": planning.content_hash, "createdAt": 5}),
        PackageRecord("project-planning-head", "project-planning-head:1", data={"revision": 2, "planningRevisionLogicalId": "planning-revision:2", "contentHash": planning.content_hash, "updatedAt": 5}),
        PackageRecord("planning-confirmation", "planning-confirmation:1", data={"status": "succeeded", "draftLogicalId": "planning-draft:1", "draftRevision": 1, "draftHash": canonical_hash(planning_draft), "expectedHeadRevision": 0, "planningRevisionLogicalId": "planning-revision:1", "resultRevision": 1, "contentHash": planning.content_hash, "createdAt": 5, "completedAt": 5}),
        PackageRecord("chapter-outline-draft", "chapter-outline-draft:1", revision=1, data={"chapterNumber": 1, "revision": 1, "baseHeadRevision": 0, "planningRevisionLogicalId": "planning-revision:1", "planningRevision": 1, "planningHash": planning.content_hash, "canonRevision": 0, "projectionRevision": 0, "projectionHash": "9" * 64, "payload": editable_outline.model_dump(mode="json", by_alias=True), "contentHash": canonical_hash(editable_outline), "updatedAt": 6}),
        PackageRecord("chapter-outline-draft", "chapter-outline-draft:2", revision=2, data={"chapterNumber": 1, "revision": 2, "baseHeadRevision": 0, "planningRevisionLogicalId": "planning-revision:1", "planningRevision": 1, "planningHash": planning.content_hash, "canonRevision": 0, "projectionRevision": 0, "projectionHash": "9" * 64, "payload": draft_outline.model_dump(mode="json", by_alias=True), "contentHash": canonical_hash(draft_outline), "updatedAt": 6}),
        PackageRecord("chapter-outline-draft", "chapter-outline-draft:3", revision=3, data={"chapterNumber": 1, "revision": 3, "baseHeadRevision": 1, "planningRevisionLogicalId": "planning-revision:2", "planningRevision": 2, "planningHash": planning.content_hash, "canonRevision": 0, "projectionRevision": 0, "projectionHash": "9" * 64, "payload": outline.model_dump(mode="json", by_alias=True), "contentHash": outline.content_hash, "updatedAt": 6}),
        PackageRecord("chapter-outline-revision", "chapter-outline-revision:1", revision=1, data={"chapterNumber": 1, "revision": 1, "planningRevisionLogicalId": "planning-revision:1", "payload": outline.model_dump(mode="json", by_alias=True), "contentHash": outline.content_hash, "createdAt": 6}),
        PackageRecord("project-chapter-outline-head", "project-chapter-outline-head:1", data={"chapterNumber": 1, "revision": 2, "outlineRevisionLogicalId": "chapter-outline-revision:2", "contentHash": outline.content_hash, "updatedAt": 6}),
        PackageRecord("chapter-outline-confirmation", "chapter-outline-confirmation:1", data={"status": "succeeded", "chapterNumber": 1, "draftLogicalId": "chapter-outline-draft:1", "draftRevision": 1, "draftHash": canonical_hash(editable_outline), "expectedHeadRevision": 0, "planningRevisionLogicalId": "planning-revision:1", "planningRevision": 1, "planningHash": planning.content_hash, "canonRevision": 0, "projectionRevision": 0, "projectionHash": "9" * 64, "outlineRevisionLogicalId": "chapter-outline-revision:1", "resultRevision": 1, "contentHash": outline.content_hash, "createdAt": 6, "completedAt": 6}),
        PackageRecord("chapter", "chapter:1", data={"planningRevisionLogicalId": "planning-revision:1", "planningRevision": 1, "planningHash": planning.content_hash, "storyBlockLogicalId": "story-block:1", "storyBlockRevision": 1, "storyBlockHash": block.content_hash, "outlineRevisionLogicalId": "chapter-outline-revision:1", "chapterOutlineRevision": 1, "chapterOutlineHash": outline.content_hash, "chapterNumber": 1, "expectedCanonRevision": 0, "status": "final", "createdAt": 7, "finalizedAt": 10}),
        PackageRecord("working-draft", "working-draft:1", revision=1, data={"chapterLogicalId": "chapter:1", "revision": 1, "content": working_text, "contentHash": working_hash, "updatedAt": 7}),
        PackageRecord("draft-candidate", "draft-candidate:1", data={
            "chapterLogicalId": "chapter:1", "workingDraftRevision": 1,
            "content": candidate_text, "contentHash": candidate_hash,
            "basisHash": canonical_hash({
                "schemaVersion": "draft-candidate-basis-v1",
                "outlineRevisionId": "chapter-outline-revision:1", "outlineRevision": 1,
                "outlineHash": outline.content_hash,
                "planningRevisionId": "planning-revision:1", "planningRevision": 1,
                "planningHash": planning.content_hash, "canonRevision": 0,
                "projectionRevision": 0, "projectionHash": "9" * 64,
            }),
            "provenance": {
                "source": "explicit-save-candidate", "workingDraftRevision": 1,
                "schemaVersion": "draft-candidate-basis-v1",
                "outlineRevisionId": "chapter-outline-revision:1", "outlineRevision": 1,
                "outlineHash": outline.content_hash,
                "planningRevisionId": "planning-revision:1", "planningRevision": 1,
                "planningHash": planning.content_hash, "canonRevision": 0,
                "projectionRevision": 0, "projectionHash": "9" * 64,
            }, "createdAt": 8,
        }),
        PackageRecord("reference-use", "reference-use:1", data={"chapterLogicalId": "chapter:1", "candidateLogicalId": "draft-candidate:1", "corpusRevisionLogicalId": "corpus-revision:1", "corpusChapterLogicalId": "corpus-chapter:2", "locationStart": 7, "locationEnd": 14, "referencePurpose": "generation", "referencedTextHash": "e" * 64, "createdAt": 8}),
        PackageRecord("candidate-quality", "candidate-quality:1", data={"chapterLogicalId": "chapter:1", "candidateLogicalId": "draft-candidate:1", "candidateHash": candidate_hash, "expectedCanonRevision": 0, "expectedPlanningHash": planning.content_hash, "expectedOutlineHash": outline.content_hash, "policyVersion": "quality-v1", "contextManifestHash": "3" * 64, "modelName": "remote-model", **quality.model_dump(mode="json", by_alias=True), "contentHash": canonical_hash(quality.model_dump(mode="json", by_alias=True)), "createdAt": 8}),
        PackageRecord("finalization-change-set", "finalization-change-set:1", data={"chapterLogicalId": "chapter:1", "candidateLogicalId": "draft-candidate:1", "status": "confirmed", "candidateHash": candidate_hash, "contentHash": change_set_hash(change_set), "createdAt": 9, "updatedAt": 9, "confirmedAt": 9}),
        PackageRecord("finalization-change-set-revision", "finalization-change-set-revision:1", revision=1, data={"changeSetLogicalId": "finalization-change-set:1", "revision": 1, "payload": change_set.model_dump(mode="json", by_alias=True), "contentHash": change_set_hash(change_set), "source": "extraction", "createdAt": 9}),
        PackageRecord("canon-entity", "canon-entity:1", data={"entityType": "person", "canonicalName": "Hero", "normalizedName": "hero", "createdRevision": 1, "createdAt": 9}),
        PackageRecord("entity-alias", "entity-alias:1", data={"entityLogicalId": "canon-entity:1", "alias": "H", "normalizedAlias": "h", "createdRevision": 1, "createdAt": 9}),
        PackageRecord("canon-revision", "canon-revision:1", data={"revisionNumber": 1, "parentRevisionNumber": 0, "sourceType": "finalization", "sourceLogicalId": "finalization-change-set:1", "contentHash": "2" * 64, "createdAt": 9}),
        PackageRecord("canon-event", "canon-event:1", order=1, data={"canonRevisionLogicalId": "canon-revision:1", "revisionNumber": 1, "eventOrder": 1, "entityLogicalId": "canon-entity:1", "factKind": "stable_definition", "fieldPath": "profile.name", "value": "Hero", "evidence": {}, "effectiveStartChapter": None, "effectiveEndChapter": None, "assertionOperator": "equals", "valueCardinality": "single", "confirmationStatus": "confirmed", "createdAt": 9}),
    ])
    receipt = {"finalChapterId": "final-chapter:1", "canonRevision": 1, "projectionHash": "2" * 64, "planningRevisionId": "planning-revision:1", "planningRevision": 1, "planningHash": planning.content_hash}
    records.extend([
        PackageRecord("finalization-record", "finalization-record:1", data={"chapterLogicalId": "chapter:1", "candidateLogicalId": "draft-candidate:1", "changeSetLogicalId": "finalization-change-set:1", "changeSetRevision": 1, "candidateHash": candidate_hash, "changeSetHash": change_set_hash(change_set), "expectedCanonRevision": 0, "committedCanonRevision": 1, "resultPayload": receipt, "resultHash": canonical_hash(receipt), "finalizedAt": 10}),
        PackageRecord("final-chapter", "final-chapter:1", data={"chapterLogicalId": "chapter:1", "candidateLogicalId": "draft-candidate:1", "finalizationRecordLogicalId": "finalization-record:1", "planningRevisionLogicalId": "planning-revision:1", "planningRevision": 1, "planningHash": planning.content_hash, "outlineRevisionLogicalId": "chapter-outline-revision:1", "chapterOutlineRevision": 1, "chapterOutlineHash": outline.content_hash, "chapterNumber": 1, "title": "Final", "content": candidate_text, "contentHash": candidate_hash, "canonRevision": 1, "finalizedAt": 10}),
        PackageRecord("corpus-revision", "corpus-revision:1", data={"sourceKey": "source", "revision": 1, "relativePath": "source.txt", "displayName": "Source", "author": "Author", "referenceTags": [], "notes": "notes", "provenance": {}, "contentHash": "c" * 64, "byteLength": 14, "encoding": "utf-8", "parserVersion": "p1", "normalizerVersion": "n1", "fragmenterVersion": "f1", "indexVersion": "i1", "status": "analyzed", "importedAt": 1, "analyzedAt": 2, "createdAt": 1, "chapters": [{"logicalId": "corpus-chapter:1", "chapterOrder": 1, "title": "Chapter 1", "rawByteStart": 0, "rawByteEnd": 7, "normalizedCharStart": 0, "normalizedCharEnd": 7, "normalizedText": "project:1", "contentHash": "d" * 64, "createdAt": 1}, {"logicalId": "corpus-chapter:2", "chapterOrder": 2, "title": "Chapter 2", "rawByteStart": 7, "rawByteEnd": 14, "normalizedCharStart": 0, "normalizedCharEnd": 7, "normalizedText": "project:1", "contentHash": "e" * 64, "createdAt": 1}], "fragments": [{"logicalId": "corpus-fragment:1", "chapterOrder": 1, "fragmentOrder": 1, "chapterCharStart": 0, "chapterCharEnd": 7, "normalizedText": "project:1", "contentHash": "e" * 64, "indexPayload": {}, "analysisVersion": "v1", "createdAt": 1}, {"logicalId": "corpus-fragment:2", "chapterOrder": 2, "fragmentOrder": 1, "chapterCharStart": 0, "chapterCharEnd": 7, "normalizedText": "project:1", "contentHash": "f" * 64, "indexPayload": {}, "analysisVersion": "v1", "createdAt": 1}]}),
        PackageRecord("creation-contract-corpus-ref", "creation-contract-corpus-ref:1", order=1, data={"creationContractLogicalId": "creation-contract:1", "corpusRevisionLogicalId": "corpus-revision:1", "contentHash": "c" * 64}),
        PackageRecord("creation-contract-corpus-fragment-ref", "creation-contract-corpus-fragment-ref:1", order=1, data={"creationContractLogicalId": "creation-contract:1", "corpusRevisionLogicalId": "corpus-revision:1", "fragmentOrder": 1, "contentHash": "f" * 64}),
    ])
    outline_two = outline.model_dump(mode="json", by_alias=True)
    outline_two["planningRevisionId"] = "planning-revision:2"
    outline_two["planningRevision"] = 2
    records.extend([
        PackageRecord("creation-contract", "creation-contract:2", revision=2, data={"revision": 2, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "bindingRevisionLogicalId": binding_revision.logical_id, "bindingHash": "7" * 64, "payload": json.loads(json.dumps(contract_payload)), "contentHash": "5" * 64, "createdAt": 3}),
        PackageRecord("style-contract", "style-contract:2", revision=2, data={"revision": 2, "creationContractLogicalId": "creation-contract:2", "payload": {"mergedStyle": {"voice": "clear"}, "likes": ["clarity"], "dislikes": ["noise"]}, "contentHash": "4" * 64, "createdAt": 3}),
        PackageRecord("style-contract-template-ref", "style-contract-template-ref:2", order=1, data={"styleContractLogicalId": "style-contract:2", "templateName": "Style", "templateRevision": 1, "contentHash": style_asset_hash}),
        PackageRecord("creation-contract-experience-ref", "creation-contract-experience-ref:2", order=1, data={"creationContractLogicalId": "creation-contract:2", "experienceTitle": "Experience", "experienceRevision": 1, "contentHash": experience_asset_hash}),
        PackageRecord("creation-bible-revision", "creation-bible-revision:2", revision=2, data={"revision": 2, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "contractRevision": 2, "creationContractLogicalId": "creation-contract:2", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:2", "styleHash": "4" * 64, "bindingRevisionLogicalId": binding_revision.logical_id, "bindingHash": "7" * 64, "policyVersion": "creation-bible-v1", "payload": json.loads(json.dumps(bible_payload)), "contentHash": canonical_bible_hash(bible), "createdAt": 4}),
        PackageRecord("planning-revision", "planning-revision:2", revision=2, data={"revision": 2, "parentRevision": 1, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "contractRevision": 2, "creationContractLogicalId": "creation-contract:2", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:2", "styleHash": "4" * 64, "bibleRevision": 2, "bibleRevisionLogicalId": "creation-bible-revision:2", "bibleHash": canonical_bible_hash(bible), "payload": planning.model_dump(mode="json", by_alias=True), "contentHash": planning.content_hash, "createdAt": 5}),
        PackageRecord("chapter-outline-revision", "chapter-outline-revision:2", revision=2, data={"chapterNumber": 1, "revision": 2, "planningRevisionLogicalId": "planning-revision:2", "payload": outline_two, "contentHash": outline.content_hash, "createdAt": 6}),
        PackageRecord("contract-confirmation", "contract-confirmation:2", data={"status": "succeeded", "selectionRevision": 1, "creationContractLogicalId": "creation-contract:2", "styleContractLogicalId": "style-contract:2", "resultRevision": 2, "contentHash": "5" * 64, "createdAt": 3, "completedAt": 3}),
        PackageRecord("project-bible-draft", "project-bible-draft:2", revision=2, data={"revision": 2, "baseHeadRevision": 1, "selectionRevision": 1, "seedLogicalId": "creative-seed:1", "seedRevisionLogicalId": "creative-seed-revision:1", "seedHash": canonical_hash(seed), "contractRevision": 2, "creationContractLogicalId": "creation-contract:2", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:2", "styleHash": "4" * 64, "bindingRevisionLogicalId": binding_revision.logical_id, "bindingHash": "7" * 64, "policyVersion": "creation-bible-v1", "payload": bible_payload, "contentHash": canonical_bible_hash(bible), "updatedAt": 4}),
        PackageRecord("bible-confirmation", "bible-confirmation:2", data={"status": "succeeded", "selectionRevision": 1, "contractRevision": 2, "creationContractLogicalId": "creation-contract:2", "creationHash": "5" * 64, "styleContractLogicalId": "style-contract:2", "styleHash": "4" * 64, "draftLogicalId": "project-bible-draft:2", "draftVersion": 2, "draftHash": canonical_bible_hash(bible), "bibleRevisionLogicalId": "creation-bible-revision:2", "resultRevision": 2, "contentHash": canonical_bible_hash(bible), "createdAt": 4, "completedAt": 4}),
        PackageRecord("planning-confirmation", "planning-confirmation:2", data={"status": "succeeded", "draftLogicalId": "planning-draft:2", "draftRevision": 2, "draftHash": planning.content_hash, "expectedHeadRevision": 1, "planningRevisionLogicalId": "planning-revision:2", "resultRevision": 2, "contentHash": planning.content_hash, "createdAt": 5, "completedAt": 5}),
        PackageRecord("chapter-outline-confirmation", "chapter-outline-confirmation:2", data={"status": "succeeded", "chapterNumber": 1, "draftLogicalId": "chapter-outline-draft:3", "draftRevision": 3, "draftHash": outline.content_hash, "expectedHeadRevision": 1, "planningRevisionLogicalId": "planning-revision:2", "planningRevision": 2, "planningHash": planning.content_hash, "canonRevision": 0, "projectionRevision": 0, "projectionHash": "9" * 64, "outlineRevisionLogicalId": "chapter-outline-revision:2", "resultRevision": 2, "contentHash": outline.content_hash, "createdAt": 6, "completedAt": 6}),
        PackageRecord("creation-contract-corpus-ref", "creation-contract-corpus-ref:2", order=1, data={"creationContractLogicalId": "creation-contract:2", "corpusRevisionLogicalId": "corpus-revision:1", "contentHash": "c" * 64}),
        PackageRecord("creation-contract-corpus-fragment-ref", "creation-contract-corpus-fragment-ref:2", order=1, data={"creationContractLogicalId": "creation-contract:2", "corpusRevisionLogicalId": "corpus-revision:1", "fragmentOrder": 1, "contentHash": "f" * 64}),
    ])

    chapter_index = next(index for index, record in enumerate(records) if record.entity_type == "chapter")
    bad_chapter = replace(records[chapter_index], data={**records[chapter_index].data, "storyBlockHash": "0" * 64})
    bad_records = [*records]
    bad_records[chapter_index] = bad_chapter
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        build_publication_plan(_package(tuple(bad_records)), COMMAND_ID, "Imported")
    draft_index = next(index for index, record in enumerate(records) if record.logical_id == "planning-draft:1")
    bad_payload = {**records[draft_index].data["payload"], "unexpected": "rejected"}
    bad_draft = replace(records[draft_index], data={**records[draft_index].data, "payload": bad_payload})
    bad_records = [*records]
    bad_records[draft_index] = bad_draft
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        build_publication_plan(_package(tuple(bad_records)), COMMAND_ID, "Imported")
    confirmation_index = next(index for index, record in enumerate(records) if record.logical_id == "planning-confirmation:1")
    crossed = replace(records[confirmation_index], data={**records[confirmation_index].data, "draftLogicalId": "planning-draft:2"})
    bad_records = [*records]
    bad_records[confirmation_index] = crossed
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        build_publication_plan(_package(tuple(bad_records)), COMMAND_ID, "Imported")

    contract_index = next(index for index, record in enumerate(records) if record.logical_id == "creation-contract:1")
    for mutation in (
        {"chapterCharStart": -1},
        {"chapterCharEnd": 8},
        {"chapterCharStart": 4, "chapterCharEnd": 4},
        {"chapterCharStart": 5, "chapterCharEnd": 4},
        {"fragmentHash": "0" * 64},
        {"fragmentId": "corpus-fragment:1", "fragmentHash": "e" * 64},
    ):
        payload = thaw_json_value(records[contract_index].data["payload"])
        payload["corpusSourceRefs"][0]["fragments"][0].update(mutation)
        bad_records = [*records]
        bad_records[contract_index] = replace(
            records[contract_index],
            data={**records[contract_index].data, "payload": payload},
        )
        with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
            build_publication_plan(_package(tuple(bad_records)), COMMAND_ID, "Imported")

    corpus_index = next(index for index, record in enumerate(records) if record.logical_id == "corpus-revision:1")
    other_corpus = replace(
        records[corpus_index],
        logical_id="corpus-revision:2",
        data={
            **records[corpus_index].data,
            "sourceKey": "other-source",
            "contentHash": "0" * 64,
            "chapters": [],
            "fragments": [],
        },
    )
    for mismatched_source in ("corpus-revision:2", "asset:1"):
        payload = thaw_json_value(records[contract_index].data["payload"])
        payload["corpusSourceRefs"][0]["id"] = mismatched_source
        bad_records = [*records, other_corpus]
        bad_records[contract_index] = replace(
            records[contract_index],
            data={**records[contract_index].data, "payload": payload},
        )
        with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
            build_publication_plan(_package(tuple(bad_records)), COMMAND_ID, "Imported")

    frozen_ref_cases = (
        ("style-contract-template-ref:1", {"templateName": "Experience"}, None),
        ("style-contract-template-ref:1", {"contentHash": "0" * 64}, None),
        ("style-contract-template-ref:1", {"templateName": "Other Style", "contentHash": canonical_hash({"voice": "other"})}, None),
        ("style-contract-template-ref:1", {}, 2),
        ("creation-contract-experience-ref:1", {"experienceTitle": "Style"}, None),
        ("creation-contract-experience-ref:1", {"contentHash": "0" * 64}, None),
        ("creation-contract-experience-ref:1", {}, 2),
    )
    for logical_id, mutation, order in frozen_ref_cases:
        ref_index = next(index for index, record in enumerate(records) if record.logical_id == logical_id)
        bad_records = [*records]
        bad_records[ref_index] = replace(
            records[ref_index],
            order=records[ref_index].order if order is None else order,
            data={**records[ref_index].data, **mutation},
        )
        with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
            build_publication_plan(_package(tuple(bad_records)), COMMAND_ID, "Imported")

    plan = build_publication_plan(_package(tuple(records)), COMMAND_ID, "Imported")
    _assert_plan_foreign_keys_exist(plan)
    tables = {batch.table: batch for batch in plan.batches}
    row = lambda table: dict(zip(tables[table].columns, tables[table].rows[0], strict=True))

    assert all(item["resolution_status"] == "unbound" for item in _rows(plan, "project_model_binding_items"))
    assert all(item["provider_id"] is None and item["model_name_snapshot"] is None for item in _rows(plan, "project_model_binding_items"))
    planning_confirmation_rows = sorted(_rows(plan, "planning_confirmation_requests"), key=lambda item: item["result_revision"])
    planning_draft_rows_by_revision = {item["draft_revision"]: item for item in _rows(plan, "planning_drafts")}
    planning_revision_rows_by_revision = {item["revision"]: item for item in _rows(plan, "planning_revisions")}
    for confirmation in planning_confirmation_rows:
        assert confirmation["planning_draft_id"] == planning_draft_rows_by_revision[confirmation["draft_revision"]]["id"]
        assert confirmation["planning_revision_id"] == planning_revision_rows_by_revision[confirmation["result_revision"]]["id"]
        assert confirmation["draft_hash"] == planning_draft_rows_by_revision[confirmation["draft_revision"]]["content_hash"]
        assert confirmation["result_hash"] == planning_revision_rows_by_revision[confirmation["result_revision"]]["content_hash"]
    target_binding = BindingRevision(
        project_id=plan.target_project_id, revision=1,
        items=tuple(BindingItem(task_key=item["task_key"], resolution_status="unbound") for item in _rows(plan, "project_model_binding_items")),
    )
    assert target_binding.binding_complete and not target_binding.binding_ready
    assert row("project_model_binding_heads")["content_hash"] == canonical_hash(target_binding)
    assert (row("candidate_quality_reports")["provider_id"], row("candidate_quality_reports")["provider_profile_revision"], row("candidate_quality_reports")["model_name_snapshot"]) == (None, None, None)
    assert row("working_drafts")["content"] == working_text and row("working_drafts")["content_hash"] == working_hash
    assert row("draft_candidates")["content"] == candidate_text and row("draft_candidates")["content_hash"] == candidate_hash
    candidate_row = row("draft_candidates")
    candidate_provenance = json.loads(candidate_row["provenance_json"])
    candidate_basis = {
        key: candidate_provenance[key] for key in (
            "schemaVersion", "outlineRevisionId", "outlineRevision", "outlineHash",
            "planningRevisionId", "planningRevision", "planningHash", "canonRevision",
            "projectionRevision", "projectionHash",
        )
    }
    assert candidate_row["working_draft_revision"] == 1
    assert candidate_row["basis_hash"] == canonical_hash(candidate_basis)
    assert candidate_provenance["source"] == "explicit-save-candidate"
    assert candidate_provenance["workingDraftRevision"] == 1
    assert candidate_provenance["planningRevisionId"] == row("planning_revisions")["id"]
    assert candidate_provenance["outlineRevisionId"] == row("chapter_outline_revisions")["id"]
    from backend.services.chapter_sessions import ChapterSessionService
    candidate_view = object.__new__(ChapterSessionService)._candidate_view({
        "id": candidate_row["id"], "project_id": plan.target_project_id,
        "chapter_session_id": candidate_row["chapter_session_id"],
        "working_draft_revision": candidate_row["working_draft_revision"],
        "content": candidate_row["content"], "content_hash": candidate_row["content_hash"],
        "basis_hash": candidate_row["basis_hash"], "provenance": candidate_provenance,
        "created_at": candidate_row["created_at"], "effective_status": "drafting",
    }, {
        "chapter_outline_revision_id": candidate_provenance["outlineRevisionId"],
        "chapter_outline_revision": candidate_provenance["outlineRevision"],
        "chapter_outline_hash": candidate_provenance["outlineHash"],
        "planning_revision_id": candidate_provenance["planningRevisionId"],
        "planning_revision": candidate_provenance["planningRevision"],
        "planning_hash": candidate_provenance["planningHash"],
    })
    assert candidate_view.basis_status == "current"
    assert row("corpus_source_revisions")["content_hash"] == "c" * 64 and row("corpus_source_revisions")["byte_length"] == 14
    assert row("corpus_chapters")["normalized_text"] == "project:1" and row("corpus_fragments")["normalized_text"] == "project:1"
    assert all(item["selection_mode"] == "author" for item in _rows(plan, "creation_contract_corpus_refs"))
    assert all(item["role"] == "primary" and item["sort_order"] == 1 for item in _rows(plan, "style_contract_template_refs"))
    assert all(item["sort_order"] == 1 for item in _rows(plan, "creation_contract_experience_refs"))
    fragment_ref_rows = _rows(plan, "creation_contract_corpus_fragment_refs")
    assert all(item["reference_use"] == "structure" for item in fragment_ref_rows)
    assert all(item["chapter_char_start"] == 1 and item["chapter_char_end"] == 6 for item in fragment_ref_rows)
    assert all(item["corpus_chapter_id"] == _rows(plan, "corpus_chapters")[1]["id"] for item in fragment_ref_rows)
    assert all(item["corpus_fragment_id"] == _rows(plan, "corpus_fragments")[1]["id"] for item in fragment_ref_rows)
    assert row("reference_uses")["corpus_chapter_id"] == _rows(plan, "corpus_chapters")[1]["id"]
    for table, id_column in (("creation_contracts", "id"), ("creation_bible_revisions", "id"), ("planning_revisions", "id"), ("chapter_outline_revisions", "id"), ("finalization_change_set_revisions", "id"), ("candidate_quality_reports", "id"), ("canon_events", "id")):
        assert str(UUID(row(table)[id_column])) == row(table)[id_column]
    target_contract = CreationContractPayload.model_validate(json.loads(row("creation_contracts")["content_json"]), strict=False)
    corpus_source = row("corpus_sources")
    corpus_revision = row("corpus_source_revisions")
    corpus_relation = _rows(plan, "creation_contract_corpus_refs")[0]
    target_source_ref = target_contract.corpusSourceRefs[0]
    assert target_source_ref.id == corpus_source["id"] == corpus_relation["corpus_source_id"]
    assert target_source_ref.revisionId == corpus_revision["id"]
    assert target_source_ref.id != target_source_ref.revisionId
    assert all(
        item["corpus_source_id"] == target_source_ref.id
        for item in _rows(plan, "creation_contract_corpus_fragment_refs")
    )
    reference_manifest = json.loads(row("creation_contracts")["reference_manifest_json"])
    assert [item["role"] for item in reference_manifest["styleRefs"]] == ["primary"]
    target_bible = BiblePayload.model_validate(json.loads(row("creation_bible_revisions")["content_json"]), strict=False)
    target_planning = json.loads(row("planning_revisions")["content_json"])
    target_outline = json.loads(row("chapter_outline_revisions")["content_json"])
    target_change_set = FinalizationChangeSet.model_validate(json.loads(row("finalization_change_set_revisions")["payload_json"]), strict=False)
    target_quality = QualityReportPayload.model_validate({
        "status": row("candidate_quality_reports")["status"],
        "deterministicBlocks": json.loads(row("candidate_quality_reports")["deterministic_blocks_json"]),
        "findings": json.loads(row("candidate_quality_reports")["findings_json"]),
    }, strict=False)
    assert row("creation_contracts")["content_hash"] == canonical_hash(target_contract)
    contract_rows = sorted(_rows(plan, "creation_contracts"), key=lambda item: item["revision"])
    style_rows = sorted(_rows(plan, "style_contracts"), key=lambda item: item["revision"])
    bible_rows = sorted(_rows(plan, "creation_bible_revisions"), key=lambda item: item["revision"])
    planning_rows = sorted(_rows(plan, "planning_revisions"), key=lambda item: item["revision"])
    outline_rows = sorted(_rows(plan, "chapter_outline_revisions"), key=lambda item: item["revision"])
    assert len(contract_rows) == len(style_rows) == len(bible_rows) == len(planning_rows) == len(outline_rows) == 2
    for index in range(2):
        assert style_rows[index]["creation_contract_id"] == contract_rows[index]["id"]
        assert bible_rows[index]["creation_contract_id"] == contract_rows[index]["id"]
        assert bible_rows[index]["style_contract_id"] == style_rows[index]["id"]
        assert planning_rows[index]["creation_contract_id"] == contract_rows[index]["id"]
        assert planning_rows[index]["style_contract_id"] == style_rows[index]["id"]
        assert planning_rows[index]["bible_revision_id"] == bible_rows[index]["id"]
        assert outline_rows[index]["planning_revision_id"] == planning_rows[index]["id"]
    target_contract_draft = ContractDraftPayload.model_validate(json.loads(row("project_contract_drafts")["draft_json"]), strict=False)
    target_planning_draft = DraftPlanningAggregate.model_validate(json.loads(row("planning_drafts")["content_json"]), strict=False)
    target_outline_draft = EditableChapterOutlineContent.model_validate(json.loads(row("chapter_outline_drafts")["content_json"]), strict=False)
    assert row("project_contract_drafts")["content_hash"] == canonical_hash(target_contract_draft)
    assert row("planning_drafts")["content_hash"] == canonical_hash(target_planning_draft)
    planning_draft_rows = sorted(_rows(plan, "planning_drafts"), key=lambda item: item["draft_revision"])
    target_formal_planning_draft = PlanningAggregate.model_validate(json.loads(planning_draft_rows[1]["content_json"]), strict=False)
    assert planning_draft_rows[1]["content_hash"] == planning_content_hash(target_formal_planning_draft.model_dump(mode="json", by_alias=True, exclude={"content_hash"}))
    assert row("chapter_outline_drafts")["content_hash"] == canonical_hash(target_outline_draft)
    outline_draft_rows = sorted(_rows(plan, "chapter_outline_drafts"), key=lambda item: item["draft_revision"])
    target_draft_outline = DraftChapterOutline.model_validate(json.loads(outline_draft_rows[1]["content_json"]), strict=False)
    target_formal_outline = ChapterOutline.model_validate(json.loads(outline_draft_rows[2]["content_json"]), strict=False)
    assert outline_draft_rows[1]["content_hash"] == canonical_hash(target_draft_outline)
    assert outline_draft_rows[2]["content_hash"] == canonical_hash(target_formal_outline.model_dump(mode="json", by_alias=True, exclude={"content_hash"}))
    planning_by_id = {
        item["id"]: json.loads(item["content_json"])
        for item in _rows(plan, "planning_revisions")
    }
    for draft_row in outline_draft_rows[1:]:
        draft_payload = json.loads(draft_row["content_json"])
        pinned_planning = planning_by_id[draft_row["planning_revision_id"]]
        expected_hashes = {
            node["id"]: node["contentHash"]
            for node in (*pinned_planning["volumes"], *pinned_planning["storyBlocks"])
        }
        for story_block in pinned_planning["storyBlocks"]:
            for stage in story_block["stages"]:
                expected_hashes[stage["id"]] = stage["contentHash"]
                expected_hashes.update({task["id"]: task["contentHash"] for task in stage["sceneTasks"]})
        assert draft_payload["planningHash"] == draft_row["planning_hash"]
        for ref in (draft_payload["volumeRef"], draft_payload["storyBlockRef"], *draft_payload["stageRefs"], *draft_payload["sceneTaskRefs"]):
            assert ref["contentHash"] == expected_hashes[ref["id"]]
    assert str(UUID(target_contract_draft.seedRevisionId)) == target_contract_draft.seedRevisionId
    assert str(UUID(target_contract_draft.engineOptionId)) == target_contract_draft.engineOptionId
    assert row("creation_bible_revisions")["content_hash"] == canonical_bible_hash(target_bible)
    assert target_planning["contentHash"] == row("planning_revisions")["content_hash"]
    assert target_outline["contentHash"] == row("chapter_outline_revisions")["content_hash"]
    assert row("finalization_change_set_revisions")["content_hash"] == change_set_hash(target_change_set)
    assert row("candidate_quality_reports")["content_hash"] == canonical_hash(target_quality.model_dump(mode="json", by_alias=True))
    assert row("candidate_quality_reports")["expected_planning_hash"] == row("planning_revisions")["content_hash"]
    assert row("candidate_quality_reports")["expected_outline_hash"] == row("chapter_outline_revisions")["content_hash"]
    assert str(UUID(target_contract.seedRevisionId)) == target_contract.seedRevisionId
    assert str(UUID(target_contract.engineOptionId)) == target_contract.engineOptionId
    assert str(UUID(target_contract.primaryStyleRef.id)) == target_contract.primaryStyleRef.id
    assert target_contract.modelBindingRef is not None and str(UUID(target_contract.modelBindingRef.id)) == target_contract.modelBindingRef.id
    for collection in (target_bible.worldRules, target_bible.coreCast, target_bible.factions, target_bible.longTermConflicts, target_bible.relationshipDynamics, target_bible.continuityGuardrails, target_bible.openDesignQuestions):
        assert all(str(UUID(item.id)) == item.id for item in collection)
    planning_ids = [
        *(item["id"] for item in target_planning["volumes"]),
        *(item["id"] for item in target_planning["plots"]),
        *(item["id"] for item in target_planning["storyBlocks"]),
        *(stage["id"] for item in target_planning["storyBlocks"] for stage in item["stages"]),
        *(task["id"] for item in target_planning["storyBlocks"] for stage in item["stages"] for task in stage["sceneTasks"]),
    ]
    assert all(str(UUID(value)) == value for value in planning_ids)
    assert all(str(UUID(target_outline[field]["id"])) == target_outline[field]["id"] for field in ("volumeRef", "storyBlockRef"))
    assert all(str(UUID(item["id"])) == item["id"] for field in ("stageRefs", "sceneTaskRefs") for item in target_outline[field])
    finalization_ids = [
        *(item.id for item in target_change_set.entities), *(item.id for item in target_change_set.aliases),
        *(item.id for item in target_change_set.canon_events), *(item.id for item in target_change_set.story_progress_events),
        *(item.id for item in target_change_set.planning_patches), *(item.id for item in target_change_set.planning_suggestions),
    ]
    assert all(str(UUID(value)) == value for value in finalization_ids)
    assert target_change_set.planning_patches[0].expected_hash == next(item["contentHash"] for item in target_planning["storyBlocks"] if item["id"] == target_change_set.planning_patches[0].target_id)
    target_story_block = next(item for item in target_planning["storyBlocks"] if item["id"] == row("chapter_sessions")["story_block_id"])
    assert row("chapter_sessions")["story_block_revision"] == target_story_block["revision"]
    assert row("chapter_sessions")["story_block_hash"] == target_story_block["contentHash"]
    chapter_session = row("chapter_sessions")
    assert type(chapter_session["draft_operation_fencing_token"]) is int
    assert chapter_session["draft_operation_fencing_token"] == 0
    chapter_record = next(record for record in records if record.entity_type == "chapter")
    assert "draftOperationFencingToken" not in chapter_record.data
    assert "activeDraftOperationId" not in chapter_record.data
    drafts_ddl = (Path(__file__).parents[2] / "schema" / "40_drafts.sql").read_text(encoding="utf-8")
    assert re.search(
        r"draft_operation_fencing_token BIGINT NOT NULL DEFAULT 0",
        drafts_ddl,
    )
    change_set_row = row("finalization_change_sets")
    extraction_id = change_set_row["extraction_id"]
    assert extraction_id == str(uuid5(
        UUID(COMMAND_ID),
        "finalization-extraction/finalization-change-set:1",
    ))
    assert str(UUID(extraction_id)) == extraction_id
    assert change_set_row["status"] == "committed"
    assert change_set_row["active_slot"] is None
    assert all(change_set_row[field] is not None for field in (
        "quality_report_id", "extraction_id", "current_revision",
        "current_revision_hash", "confirmed_revision",
        "confirmed_revision_hash", "confirmed_at",
    ))
    assert "extractionLogicalId" not in next(
        record for record in records if record.logical_id == "finalization-change-set:1"
    ).data
    assert all(batch.table != "finalization_extractions" for batch in plan.batches)
    repeated_plan = build_publication_plan(_package(tuple(records)), COMMAND_ID, "Imported")
    repeated_extraction = _rows(repeated_plan, "finalization_change_sets")[0]["extraction_id"]
    other_plan = build_publication_plan(
        _package(tuple(records)), "48ca226b-7199-4cc4-a3e9-98c6993b17c3", "Imported",
    )
    other_extraction = _rows(other_plan, "finalization_change_sets")[0]["extraction_id"]
    assert repeated_extraction == extraction_id
    assert str(UUID(other_extraction)) == other_extraction
    assert other_extraction != extraction_id
    assert all(str(UUID(item.id)) == item.id for item in target_quality.findings)
    assert row("chapter_outline_revisions")["planning_hash"] == row("planning_revisions")["content_hash"]
    target_receipt = json.loads(row("finalization_records")["result_payload_json"])
    assert set(target_receipt) == {"finalChapterId", "canonRevision", "projectionHash", "planningRevisionId", "planningRevision", "planningHash"}
    assert target_receipt["planningHash"] == row("planning_revisions")["content_hash"]
    assert target_receipt["projectionHash"] == plan.expected_projection["contentHash"]
    assert str(UUID(target_receipt["finalChapterId"])) == target_receipt["finalChapterId"]
    assert str(UUID(target_receipt["planningRevisionId"])) == target_receipt["planningRevisionId"]
    assert row("canon_revisions")["content_hash"] == plan.expected_projection["contentHash"]
    assert str(UUID(row("canon_events")["entity_id"])) == row("canon_events")["entity_id"]
    for batch in plan.batches:
        assert batch.columns == STATIC_TABLE_COLUMNS[batch.table]
