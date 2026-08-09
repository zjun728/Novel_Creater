from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from backend.domain.bibles import BiblePayload
from backend.domain.chapter_outlines import ChapterOutline
from backend.domain.contracts import CreationContractPayload
from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import PlanningAggregate
from backend.domain.project_packages import PackageRecord, RECORD_FIELD_ALLOWLISTS, freeze_json_value
from backend.domain.project_packages import ProjectPackageBusy, ProjectPackageConflict, ProjectPackageInvalid, ProjectPackageNotFound
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption
from backend.tests.unit.test_finalization_domain import _payload as _finalization_change_set_payload
from backend.repositories.project_packages import (
    INTERNAL_NON_PACKAGE_TABLES,
    PROJECT_OWNED_TABLES,
    PROJECT_TABLE_RECORD_TYPES,
    PROJECT_TABLE_COLUMN_POLICIES,
    SHARED_EXCLUDED_TABLES,
    NORMALIZED_SHARED_RECORD_TYPES,
    FROZEN_CORPUS_BLOB_TABLES,
    LOGICAL_REFERENCE_TARGETS,
    NESTED_LOGICAL_REFERENCE_TARGETS,
    POLYMORPHIC_LOGICAL_REFERENCE_TARGETS,
    FrozenCorpusBlob,
    ProjectPackageSnapshot,
    ProjectPackageRepository,
    PROJECT_OWNED_QUERY_PLANS,
    PACKAGE_COLUMN_EXPORT_DECISIONS,
    PACKAGE_COLUMN_EXPORT_DECISION_FINGERPRINT,
)
from backend.security.project_package_paths import reject_sensitive_keys


def _schema_tables() -> set[str]:
    schema_dir = Path(__file__).parents[2] / "schema"
    return {
        match.group(1)
        for path in schema_dir.glob("*.sql")
        for match in re.finditer(r"(?im)^CREATE TABLE\s+([a-z_]+)", path.read_text(encoding="utf-8"))
    }


def _schema_columns() -> dict[str, set[str]]:
    schema_dir = Path(__file__).parents[2] / "schema"
    schema_text = "\n".join(path.read_text(encoding="utf-8") for path in schema_dir.glob("*.sql"))
    columns: dict[str, set[str]] = {}
    for table, body in re.findall(r"CREATE TABLE\s+([a-z_]+)\s*\((.*?)\)\s*ENGINE=", schema_text, re.DOTALL):
        columns[table] = {
            match.group(1)
            for line in body.splitlines()
            if (match := re.match(r"\s{2}([a-z][a-z0-9_]*)\s+", line))
            and match.group(1) not in {"primary", "unique", "foreign", "check", "key", "constraint"}
        }
    return columns


def _schema_foreign_key_targets() -> dict[tuple[str, str], str]:
    schema_dir = Path(__file__).parents[2] / "schema"
    schema_text = "\n".join(path.read_text(encoding="utf-8") for path in schema_dir.glob("*.sql"))
    targets: dict[tuple[str, str], str] = {}
    for table, body in re.findall(r"CREATE TABLE\s+([a-z_]+)\s*\((.*?)\)\s*ENGINE=", schema_text, re.DOTALL):
        for local, target in re.findall(r"FOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s+([a-z_]+)\s*\(", body):
            for column in re.findall(r"[a-z_]+", local):
                targets[(table, column)] = target
    return targets


def _schema_foreign_key_edges() -> dict[tuple[str, str], tuple[str, str]]:
    schema_dir = Path(__file__).parents[2] / "schema"
    schema_text = "\n".join(path.read_text(encoding="utf-8") for path in schema_dir.glob("*.sql"))
    edges: dict[tuple[str, str], tuple[str, str]] = {}
    for table, body in re.findall(r"CREATE TABLE\s+([a-z_]+)\s*\((.*?)\)\s*ENGINE=", schema_text, re.DOTALL):
        for local, target, remote in re.findall(
            r"FOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s+([a-z_]+)\s*\(([^)]+)\)", body
        ):
            local_columns = re.findall(r"[a-z_]+", local)
            remote_columns = re.findall(r"[a-z_]+", remote)
            assert len(local_columns) == len(remote_columns)
            for local_column, remote_column in zip(local_columns, remote_columns, strict=True):
                edges[(table, local_column)] = (target, remote_column)
    return edges


def test_explicit_ownership_inventory_closes_over_every_create_only_schema_table() -> None:
    schema_tables = _schema_tables()

    assert len(schema_tables) == 89
    assert PROJECT_OWNED_TABLES | SHARED_EXCLUDED_TABLES | INTERNAL_NON_PACKAGE_TABLES == schema_tables
    assert PROJECT_OWNED_TABLES.isdisjoint(SHARED_EXCLUDED_TABLES)
    assert PROJECT_OWNED_TABLES.isdisjoint(INTERNAL_NON_PACKAGE_TABLES)
    assert SHARED_EXCLUDED_TABLES.isdisjoint(INTERNAL_NON_PACKAGE_TABLES)


def test_key_tables_are_classified_by_authority_not_by_name() -> None:
    assert {"projects", "draft_operation_events", "final_chapters", "canon_events", "reference_uses"} <= PROJECT_OWNED_TABLES
    assert {
        "provider_profiles", "provider_profile_mutation_requests", "application_settings",
        "style_template_heads", "experience_card_heads", "market_sources", "market_refresh_requests",
        "corpus_source_heads", "corpus_import_runs", "corpus_source_deletions",
    } <= SHARED_EXCLUDED_TABLES
    assert {
        "schema_metadata", "current_state_projections", "memory_views", "arc_projections",
        "plot_thread_projections", "projection_heads",
    } == INTERNAL_NON_PACKAGE_TABLES


def test_each_project_owned_table_maps_to_an_explicit_public_or_normalized_record_type() -> None:
    assert set(PROJECT_TABLE_RECORD_TYPES) == PROJECT_OWNED_TABLES
    assert all(record_type in RECORD_FIELD_ALLOWLISTS for record_type in PROJECT_TABLE_RECORD_TYPES.values())


def test_every_project_owned_schema_column_has_an_explicit_export_policy() -> None:
    schema_columns = _schema_columns()

    assert set(PROJECT_TABLE_COLUMN_POLICIES) == PROJECT_OWNED_TABLES
    assert {table: set(policy) for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()} == {
        table: schema_columns[table] for table in PROJECT_OWNED_TABLES
    }
    assert {
        policy for table_policy in PROJECT_TABLE_COLUMN_POLICIES.values() for policy in table_policy.values()
    } <= {"public_field", "logical_reference", "nested_logical_reference", "polymorphic_logical_reference", "normalized_inert_evidence", "derived", "excluded_sensitive_operational"}
    future_schema_columns = dict(schema_columns)
    future_schema_columns["projects"] = schema_columns["projects"] | {"future_secret"}
    assert {table: set(policy) for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()} != {
        table: future_schema_columns[table] for table in PROJECT_OWNED_TABLES
    }


def test_column_policy_is_static_and_never_exports_operation_event_payloads() -> None:
    repository_source = (Path(__file__).parents[2] / "repositories" / "project_packages.py").read_text(encoding="utf-8")

    assert "_schema_owned_column_policies" not in repository_source
    assert "read_text(" not in repository_source
    assert PROJECT_TABLE_COLUMN_POLICIES["draft_operation_events"]["closed_payload_json"] == "excluded_sensitive_operational"


def test_shared_market_and_corpus_foreign_keys_are_not_package_logical_references() -> None:
    for table, column in {
        ("seed_inspiration_attempts", "market_source_id"),
        ("seed_inspiration_attempts", "market_snapshot_id"),
        ("creation_contract_corpus_refs", "corpus_source_id"),
        ("creation_contract_corpus_fragment_refs", "corpus_source_id"),
        ("creation_contract_corpus_fragment_refs", "corpus_chapter_id"),
        ("creation_contract_corpus_fragment_refs", "corpus_fragment_id"),
        ("reference_uses", "corpus_source_id"),
        ("reference_uses", "corpus_chapter_id"),
    }:
        assert PROJECT_TABLE_COLUMN_POLICIES[table][column] != "logical_reference"
    assert PROJECT_TABLE_COLUMN_POLICIES["finalization_change_sets"]["extraction_id"] == "excluded_sensitive_operational"


def test_every_logical_reference_has_a_project_or_normalized_fk_target() -> None:
    foreign_keys = _schema_foreign_key_targets()
    permitted = PROJECT_OWNED_TABLES | set(NORMALIZED_SHARED_RECORD_TYPES)
    logical_references = {
        (table, column)
        for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()
        for column, category in policy.items()
        if category == "logical_reference"
    }

    assert set(LOGICAL_REFERENCE_TARGETS) <= logical_references
    unresolved = {
        pair for pair in logical_references
        if foreign_keys.get(pair, LOGICAL_REFERENCE_TARGETS.get(pair)) not in permitted
    }
    assert not unresolved


def test_nested_and_polymorphic_references_have_explicit_real_semantics() -> None:
    assert PROJECT_TABLE_COLUMN_POLICIES["planning_generation_attempts"]["operation_id"] == "excluded_sensitive_operational"
    assert PROJECT_TABLE_COLUMN_POLICIES["chapter_outline_generation_attempts"]["operation_id"] == "excluded_sensitive_operational"
    assert PROJECT_TABLE_COLUMN_POLICIES["story_engine_batches"]["attempt_id"] == "excluded_sensitive_operational"
    assert NESTED_LOGICAL_REFERENCE_TARGETS == {("chapter_sessions", "story_block_id"): "story-block"}
    assert POLYMORPHIC_LOGICAL_REFERENCE_TARGETS[("canon_revisions", "source_id")] == {
        "bootstrap": None, "finalization": "finalization_change_sets", "manual_test": None,
    }


def test_shared_normalization_never_claims_a_blob_is_a_package_record() -> None:
    assert set(NORMALIZED_SHARED_RECORD_TYPES) <= SHARED_EXCLUDED_TABLES
    assert all(record_type in RECORD_FIELD_ALLOWLISTS for record_type in NORMALIZED_SHARED_RECORD_TYPES.values())
    assert "corpus_blobs" not in NORMALIZED_SHARED_RECORD_TYPES
    assert FROZEN_CORPUS_BLOB_TABLES == frozenset({"corpus_blobs"})


def test_public_record_allowlists_have_no_provider_or_execution_sensitive_fields() -> None:
    forbidden = {
        "id", "projectId", "providerId", "providerUuid", "baseUrl", "apiKey", "hasApiKey", "enabled",
        "ownerToken", "lease", "prompt", "requestJson", "rawOutput", "delta", "absolutePath",
        "localPath", "filesystemPath", "idempotencyKey",
    }
    public_fields = {field for fields in RECORD_FIELD_ALLOWLISTS.values() for field in fields}

    assert not forbidden & public_fields
    for field in public_fields:
        reject_sensitive_keys({field: None})


def test_snapshot_and_frozen_blob_are_immutable_package_boundary_dtos() -> None:
    source_projection = {"hashes": [{"nested": ["x"]}], "count": 0}
    snapshot = ProjectPackageSnapshot(
        source_project_logical_id="project:1",
        lifecycle_revision=0,
        graph_records=(PackageRecord("project", "project:1", data={"label": "project"}),),
        operation_records=(),
        provider_history_records=(),
        frozen_asset_records=(),
        corpus_revision_records=(),
        corpus_blobs=(FrozenCorpusBlob("corpus-blob:1", "a" * 64, 0, "sha256/aa/" + "a" * 64),),
        projection_validation=source_projection,
        referenced_secret_values=(b"private",),
        counts={"project": 1},
    )

    assert snapshot.source_project_logical_id == "project:1"
    assert snapshot.corpus_blobs[0].content_hash == "a" * 64
    source_projection["hashes"][0]["nested"].append("source-only")
    assert snapshot.projection_validation["hashes"][0]["nested"] == ("x",)
    with pytest.raises(TypeError):
        snapshot.projection_validation["hashes"][0]["nested"] += ("y",)


@pytest.mark.parametrize("storage_key", ["C:/corpus/blob", "/corpus/blob", "sha256/aa/not-the-hash", "sha256/aa/%2e%2e/blob"])
def test_frozen_blob_requires_its_exact_managed_storage_key(storage_key: str) -> None:
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        FrozenCorpusBlob("corpus-blob:1", "a" * 64, 0, storage_key)


def test_snapshot_rejects_non_tuple_record_collections_with_a_fixed_error() -> None:
    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        ProjectPackageSnapshot(
            source_project_logical_id="project:1", lifecycle_revision=0,
            graph_records=[], operation_records=(), provider_history_records=(), frozen_asset_records=(),
            corpus_revision_records=(), corpus_blobs=(), projection_validation={}, referenced_secret_values=(),
        )


@pytest.mark.asyncio
async def test_repository_starts_one_read_only_repeatable_read_snapshot_before_authority_reads() -> None:
    calls: list[tuple[str, object]] = []

    class Session:
        async def execute(self, sql, args=None):
            calls.append((sql, args))
        async def fetchone(self, sql, args=None):
            calls.append((sql, args))
            return None
        async def fetchall(self, sql, args=None):
            calls.append((sql, args))
            return []
    class Pool:
        async def acquire(self):
            return Session()
        def release(self, raw): pass
    repository = ProjectPackageRepository(pool=Pool(), session_factory=lambda session: session)

    with pytest.raises(ProjectPackageNotFound, match="project package not found"):
        await repository.read_snapshot("project:1", 0)

    assert calls[:3] == [
        ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ", None),
        ("START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT", None),
        ("SELECT id,lifecycle_revision FROM projects WHERE id=%s", ("project:1",)),
    ]


@pytest.mark.asyncio
async def test_repository_rejects_lifecycle_revision_conflicts_before_payload_reads() -> None:
    class Session:
        async def execute(self, sql, args=None): pass
        async def fetchone(self, sql, args=None): return {"id": "db-uuid", "lifecycle_revision": 7}
    class Pool:
        async def acquire(self): return Session()
        def release(self, raw): pass

    with pytest.raises(ProjectPackageConflict, match="project package conflict"):
        await ProjectPackageRepository(pool=Pool(), session_factory=lambda session: session).read_snapshot("project:1", 6)


def test_owned_query_plan_closes_over_all_owned_tables_with_safe_static_sql() -> None:
    schema_columns = _schema_columns()
    foreign_keys = _schema_foreign_key_edges()
    assert set(PROJECT_OWNED_QUERY_PLANS) == PROJECT_OWNED_TABLES
    direct = indirect = special = 0
    for table, plan in PROJECT_OWNED_QUERY_PLANS.items():
        assert "SELECT *" not in plan.sql.upper()
        assert plan.sql.count("%s") == 1
        assert "ORDER BY" in plan.sql.upper()
        expected_columns = {
            column
            for column, category in PROJECT_TABLE_COLUMN_POLICIES[table].items()
            if category != "excluded_sensitive_operational"
        }
        assert set(plan.selected_columns) == expected_columns
        assert set(plan.selected_columns) <= schema_columns[table]
        assert plan.order_columns
        assert set(plan.order_columns) <= schema_columns[table]
        for column in plan.selected_columns:
            assert f"t0.{column} AS {column}" in plan.sql

        current_table = table
        for join in plan.ownership_joins:
            assert join.child_table == current_table
            assert foreign_keys[(join.child_table, join.child_column)] == (
                join.parent_table,
                join.parent_column,
            )
            current_table = join.parent_table
        assert current_table == plan.scope_table
        assert plan.scope_column in schema_columns[plan.scope_table]
        if table == "projects":
            special += 1
            assert not plan.ownership_joins
            assert plan.scope_column == "id"
        elif plan.ownership_joins:
            indirect += 1
            assert plan.scope_column == "project_id"
        else:
            direct += 1
            assert plan.scope_table == table
            assert plan.scope_column == "project_id"
    assert (direct, indirect, special) == (53, 6, 1)


@pytest.mark.asyncio
async def test_repository_rejects_busy_draft_market_or_finalization_before_payload_reads() -> None:
    class Session:
        async def execute(self, sql, args=None): pass
        async def fetchone(self, sql, args=None):
            if "FROM projects" in sql: return {"id": "db", "lifecycle_revision": 7}
            return {"present": 1}
    class Pool:
        async def acquire(self): return Session()
        def release(self, raw): pass
    with pytest.raises(ProjectPackageBusy, match="project package busy"):
        await ProjectPackageRepository(pool=Pool(), session_factory=lambda value: value).read_snapshot("project:1", 7)


def _owned_row(table: str, **values) -> dict[str, object]:
    row = {column: None for column in PROJECT_OWNED_QUERY_PLANS[table].selected_columns}
    row.update(values)
    return row


def _planning_authority_json(block_id: str, content_hash: str) -> str:
    return json.dumps({
        "schemaVersion": "planning-v1", "activeStoryBlockId": block_id,
        "volumes": [{
            "id": f"{block_id}-volume", "revision": 1, "contentHash": "1" * 64,
            "lifecycle": "active", "order": 1, "title": "Volume", "coreChange": "Change",
            "mainPressure": "Pressure", "ensembleFocus": [], "forbiddenEvents": [],
        }],
        "plots": [{
            "id": f"{block_id}-plot", "revision": 1, "contentHash": "2" * 64,
            "lifecycle": "active", "order": 1, "title": "Plot", "plotType": "main",
            "storyQuestion": "Question?", "futureDirection": "Forward",
            "expectedPayoff": "Payoff", "relatedCharacters": [],
        }],
        "storyBlocks": [{
            "id": block_id, "revision": 1, "contentHash": "3" * 64, "lifecycle": "active",
            "volumeId": f"{block_id}-volume", "plotIds": [f"{block_id}-plot"], "order": 1,
            "title": "Block", "entrySituation": "Entry", "blockGoal": "Goal",
            "mainPressure": "Pressure", "expectedChange": "Change", "openQuestions": [],
            "involvedCharacters": [], "stages": [{
                "id": f"{block_id}-stage", "revision": 1, "contentHash": "4" * 64,
                "lifecycle": "active", "storyBlockId": block_id, "order": 1, "title": "Stage",
                "purpose": "Purpose", "dramaticQuestion": "Question?", "sceneTasks": [{
                    "id": f"{block_id}-task", "revision": 1, "contentHash": "5" * 64,
                    "lifecycle": "active", "stageId": f"{block_id}-stage", "order": 1,
                    "task": "Act", "completionEvidence": "Done",
                }],
            }],
        }],
        "contentHash": content_hash,
    })


def _full_finalization_change_set_payload() -> tuple[dict[str, object], tuple[str, ...]]:
    raw_ids = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
        "55555555-5555-4555-8555-555555555555",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        "88888888-8888-4888-8888-888888888888",
    )
    (
        existing_entity_id,
        entity_id,
        alias_id,
        event_id,
        progress_id,
        patch_id,
        suggestion_id,
        planning_target_id,
    ) = raw_ids
    payload = _finalization_change_set_payload()
    payload["existingEntityIds"] = [existing_entity_id]
    payload["entities"][0]["id"] = entity_id
    payload["aliases"][0].update({"id": alias_id, "entityId": entity_id})
    payload["canonEvents"][0].update({"id": event_id, "entityId": existing_entity_id})
    payload["storyProgressEvents"][0].update({"id": progress_id, "targetId": planning_target_id})
    payload["planningPatches"][0].update({"id": patch_id, "targetId": planning_target_id})
    payload["planningSuggestions"][0].update({"id": suggestion_id, "targetId": planning_target_id})
    return payload, raw_ids


def _bible_authority_json() -> str:
    return json.dumps({
        "premiseAndPromise": "Promise", "powerOrProgressionSystem": "Progress",
        "protagonist": "Hero", "toneAndNarrativeBoundaries": "Tone",
        **{
            field: [{"id": f"{field}-1", "text": field}]
            for field in (
                "worldRules", "coreCast", "factions", "longTermConflicts",
                "relationshipDynamics", "continuityGuardrails", "openDesignQuestions",
            )
        },
    })


def _outline_authority_json(
    planning_id: str, block_id: str, planning_hash: str, content_hash: str,
) -> str:
    return json.dumps({
        "schemaVersion": "chapter-outline-v1", "chapterNumber": 1,
        "planningRevisionId": planning_id, "planningRevision": 4, "planningHash": planning_hash,
        "volumeRef": {"id": f"{block_id}-volume", "revision": 1, "contentHash": "1" * 64},
        "storyBlockRef": {"id": block_id, "revision": 1, "contentHash": "3" * 64},
        "stageRefs": [{"id": f"{block_id}-stage", "revision": 1, "contentHash": "4" * 64}],
        "sceneTaskRefs": [{"id": f"{block_id}-task", "revision": 1, "contentHash": "5" * 64}],
        "chapterGoal": "Goal", "expectedCharacters": [], "continuation": [],
        "plannedTasks": ["Act"], "scenes": ["Scene"], "forbiddenEarlyEvents": [],
        "capacityPolicy": {"targetMin": 1, "targetMax": 2, "softCeiling": 3},
        "canonRevision": 0, "projectionRevision": 0, "projectionHash": "e" * 64,
        "contentHash": content_hash,
    })


def _creation_contract_authority_json(
    *,
    seed_revision_id: str,
    engine_option_id: str,
    primary_style_id: str,
    secondary_style_id: str | None,
    experience_card_id: str | None,
    corpus_source_id: str | None,
    corpus_revision_id: str | None,
    corpus_chapter_id: str | None,
    corpus_fragment_id: str | None,
    binding_revision_id: str | None,
    corpus_fragment_start: int = 0,
    corpus_fragment_end: int = 9,
) -> str:
    seed = SeedPayload(
        title="Archive",
        genre="Fantasy",
        logline="A keeper restores a forbidden archive.",
        protagonist="The keeper",
        desire="Restore the missing names.",
        coreConflict="Each restoration wakes a threat.",
        worldPressure="The archive is being erased.",
        openingHook="The archive predicts the keeper's death.",
        differentiation="Memory is a costly magic system.",
    )
    engine = StoryEngineOption(
        name="Archive engine",
        storyPromise="Each restored record reveals a larger erasure.",
        protagonistDesire="Preserve the forgotten people.",
        sustainedPressure="Erasure advances while the cost rises.",
        growthDirection="The keeper learns to share authority.",
        conflictLoop="Recover, restore, awaken, and pay.",
        ensembleRoles=({"role": "Archivist", "purpose": "Challenge the keeper."},),
        advantageAndCost="Records grant power but consume memory.",
        satisfactionSources=("Recovered histories",),
        longFormVariation=("Local, regional, and imperial archives",),
        endingAnchor="The keeper records their own name last.",
        risks=("Repetitive recovery beats",),
        differentiation="Archive restoration drives every conflict.",
    )
    payload = CreationContractPayload(
        schemaVersion="creation-contract-v1",
        channelProfileKey="web-fiction",
        genreProfileKey="fantasy",
        qualityCharterVersion="quality-v1",
        selectionRevision=1,
        selectedSeed=seed,
        seedRevisionId=seed_revision_id,
        seedHash=canonical_hash(seed),
        selectedEngine=engine,
        engineOptionId=engine_option_id,
        engineHash=canonical_hash(engine),
        primaryStyleRef={
            "id": primary_style_id, "revision": 2, "contentHash": "a" * 64,
        },
        secondaryStyleRef=None if secondary_style_id is None else {
            "id": secondary_style_id, "revision": 3, "contentHash": "b" * 64,
        },
        experienceCardRefs=() if experience_card_id is None else ({
            "id": experience_card_id, "revision": 4, "contentHash": "c" * 64,
        },),
        corpusSourceRefs=() if corpus_source_id is None else ({
            "id": corpus_source_id,
            "revisionId": corpus_revision_id,
            "revision": 5,
            "contentHash": "d" * 64,
            "selectionMode": "author",
            "fragments": ({
                "chapterId": corpus_chapter_id,
                "fragmentId": corpus_fragment_id,
                "fragmentHash": "e" * 64,
                "chapterCharStart": corpus_fragment_start,
                "chapterCharEnd": corpus_fragment_end,
                "referenceUse": "style",
            },),
            "pinnedHistoricalRevision": True,
        },),
        targetTotalWords=100_000,
        expectedVolumeCount=4,
        expectedChapterCount=40,
        chapterWordRangePreference=(2_000, 3_000),
        prohibitedDirections=("No effortless victory",),
        authorNotes="Preserve character agency.",
        modelBindingRef=None if binding_revision_id is None else {
            "id": binding_revision_id, "revision": 6, "contentHash": "f" * 64,
        },
    )
    return payload.model_dump_json()


def _minimal_creation_contract_fixture(
    *,
    contract_id: str,
    seed_id: str,
    seed_revision_id: str,
    engine_batch_id: str,
    engine_option_id: str,
    style_contract_id: str,
    style_template_id: str,
    revision: int = 1,
    experience_card_id: str | None = None,
    corpus_source_id: str | None = None,
    corpus_revision_id: str | None = None,
    corpus_chapter_id: str | None = None,
    corpus_fragment_id: str | None = None,
) -> tuple[CreationContractPayload, dict[str, list[dict[str, object]]], dict[str, object]]:
    content_json = _creation_contract_authority_json(
        seed_revision_id=seed_revision_id,
        engine_option_id=engine_option_id,
        primary_style_id=style_template_id,
        secondary_style_id=None,
        experience_card_id=experience_card_id,
        corpus_source_id=corpus_source_id,
        corpus_revision_id=corpus_revision_id,
        corpus_chapter_id=corpus_chapter_id,
        corpus_fragment_id=corpus_fragment_id,
        binding_revision_id=None,
    )
    contract = CreationContractPayload.model_validate_json(content_json)
    rows = {
        "creative_seeds": [_owned_row(
            "creative_seeds", id=seed_id, project_id="project-db",
        )],
        "creative_seed_revisions": [_owned_row(
            "creative_seed_revisions", id=seed_revision_id, project_id="project-db",
            seed_id=seed_id, revision=1, payload_json=contract.selectedSeed.model_dump_json(),
            content_hash=contract.seedHash,
        )],
        "story_engine_batches": [_owned_row(
            "story_engine_batches", id=engine_batch_id, project_id="project-db",
            status="completed",
        )],
        "story_engine_options": [_owned_row(
            "story_engine_options", id=engine_option_id, project_id="project-db",
            batch_id=engine_batch_id, option_order=1,
            payload_json=contract.selectedEngine.model_dump_json(),
            content_hash=contract.engineHash,
        )],
        "creation_contracts": [_owned_row(
            "creation_contracts", id=contract_id, project_id="project-db",
            revision=revision, seed_id=seed_id, seed_revision_id=seed_revision_id,
            seed_hash=contract.seedHash, content_json=content_json, content_hash="0" * 64,
        )],
        "style_contracts": [_owned_row(
            "style_contracts", id=style_contract_id, project_id="project-db",
            creation_contract_id=contract_id, revision=revision,
            merged_style_json="{}", likes_json="[]", dislikes_json="[]",
            content_hash="1" * 64,
        )],
        "creation_contract_engine_refs": [_owned_row(
            "creation_contract_engine_refs", creation_contract_id=contract_id,
            project_id="project-db", engine_option_id=engine_option_id,
            engine_hash=contract.engineHash,
        )],
        "style_contract_template_refs": [_owned_row(
            "style_contract_template_refs", style_contract_id=style_contract_id,
            style_template_id=style_template_id, asset_revision=2,
            asset_hash="a" * 64, role="primary", sort_order=1,
        )],
    }
    extra_rows = {"FROM style_templates": [{
        "id": style_template_id, "stable_key": "primary", "revision": 2,
        "name": "Primary", "payload_json": "{}", "provenance_json": "{}",
        "content_hash": "a" * 64, "status": "active", "created_at": 1,
    }]}
    return contract, rows, extra_rows


class _SnapshotSession:
    def __init__(self, rows_by_table: dict[str, list[dict[str, object]]], *, busy=False, extra_rows=None):
        self.rows_by_table = rows_by_table
        self.busy = busy
        self.extra_rows = extra_rows or {}
        self.calls: list[tuple[str, object]] = []

    async def execute(self, sql, args=None):
        self.calls.append((sql, args))

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        if sql == "SELECT id,lifecycle_revision FROM projects WHERE id=%s":
            return {"id": "project-db", "lifecycle_revision": 7}
        if "SELECT 1 AS present WHERE EXISTS" in sql:
            return {"present": 1} if self.busy else None
        return None

    async def fetchall(self, sql, args=None):
        self.calls.append((sql, args))
        for table, plan in PROJECT_OWNED_QUERY_PLANS.items():
            if sql == plan.sql:
                return self.rows_by_table.get(table, [])
        for marker, rows in self.extra_rows.items():
            if marker in sql:
                if isinstance(rows, dict):
                    return rows.get(args, [])
                return rows
        return []

    async def rollback(self):
        self.calls.append(("ROLLBACK", None))


class _SnapshotPool:
    def __init__(self, session):
        self.session = session

    async def acquire(self):
        return self.session

    def release(self, raw):
        self.session.calls.append(("RELEASE", None))


@pytest.mark.asyncio
async def test_repository_materializes_every_owned_plan_and_returns_secret_free_public_records() -> None:
    secret = "SECRET_SENTINEL_MUST_STAY_PRIVATE"
    session = _SnapshotSession({
        "projects": [_owned_row(
            "projects", id="project-db", lifecycle_revision=7, title="Stable title",
            status="active", target_words=1000, target_chapters=2, current_chapter=1,
            created_at=11, updated_at=12,
        )],
    })

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    plan_calls = [(sql, args) for sql, args in session.calls if sql in {plan.sql for plan in PROJECT_OWNED_QUERY_PLANS.values()}]
    assert len(plan_calls) == len(PROJECT_OWNED_QUERY_PLANS) == 60
    assert all(args == ("project-db",) for _, args in plan_calls)
    assert snapshot.source_project_logical_id == "project:1"
    assert snapshot.graph_records[0].logical_id == "project:1"
    assert snapshot.graph_records[0].data["title"] == "Stable title"
    assert "id" not in snapshot.graph_records[0].data
    assert "projectId" not in snapshot.graph_records[0].data
    assert secret not in repr(snapshot.graph_records)
    assert session.calls[-2:] == [("ROLLBACK", None), ("RELEASE", None)]


@pytest.mark.asyncio
async def test_style_contract_exports_complete_authoritative_payload_without_database_ids() -> None:
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
        "style_contracts": [_owned_row(
            "style_contracts", id="style-contract-db", project_id="project-db",
            revision=3, merged_style_json='{"voice":{"pace":"fast"}}',
            likes_json='["tight scenes",{"imagery":"rain"}]',
            dislikes_json='{"omit":["exposition"]}', content_hash="a" * 64,
        )],
    })

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    record = next(item for item in snapshot.graph_records if item.entity_type == "style-contract")
    assert record.to_public_dict()["data"]["payload"] == {
        "mergedStyle": {"voice": {"pace": "fast"}},
        "likes": ["tight scenes", {"imagery": "rain"}],
        "dislikes": {"omit": ["exposition"]},
    }
    assert "style-contract-db" not in repr(record.to_public_dict())
    assert all(
        PACKAGE_COLUMN_EXPORT_DECISIONS[("style_contracts", column)] != "@omit-normalized"
        for column in ("merged_style_json", "likes_json", "dislikes_json")
    )


@pytest.mark.asyncio
async def test_style_contract_rejects_invalid_authoritative_json_with_fixed_error() -> None:
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
        "style_contracts": [_owned_row(
            "style_contracts", id="style-contract-db", project_id="project-db",
            revision=3, merged_style_json="not-json", likes_json="[]", dislikes_json="{}",
            content_hash="a" * 64,
        )],
    })

    with pytest.raises(ProjectPackageInvalid, match="invalid package value") as raised:
        await ProjectPackageRepository(
            pool=_SnapshotPool(session), session_factory=lambda value: value,
        ).read_snapshot("project-db", 7)

    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_authority_payloads_rewrite_all_typed_definitions_and_cross_references() -> None:
    ids = {
        "planning": "00000000-0000-0000-0000-000000000100",
        "volume": "00000000-0000-0000-0000-000000000101",
        "plot": "00000000-0000-0000-0000-000000000102",
        "block": "00000000-0000-0000-0000-000000000103",
        "stage": "00000000-0000-0000-0000-000000000104",
        "task": "00000000-0000-0000-0000-000000000105",
        "bible": "00000000-0000-0000-0000-000000000200",
        "outline": "00000000-0000-0000-0000-000000000300",
    }
    node_hashes = {name: str(index) * 64 for index, name in enumerate(
        ("volume", "plot", "block", "stage", "task"), start=1,
    )}
    planning = PlanningAggregate.model_validate({
        "schemaVersion": "planning-v1", "activeStoryBlockId": ids["block"],
        "volumes": [{
            "id": ids["volume"], "revision": 1, "contentHash": node_hashes["volume"],
            "lifecycle": "active", "order": 1, "title": "Volume", "coreChange": "Change",
            "mainPressure": "Pressure", "ensembleFocus": ["A"], "forbiddenEvents": ["B"],
        }],
        "plots": [{
            "id": ids["plot"], "revision": 1, "contentHash": node_hashes["plot"],
            "lifecycle": "active", "order": 1, "title": "Plot", "plotType": "main",
            "storyQuestion": "Question?", "futureDirection": "Forward",
            "expectedPayoff": "Payoff", "relatedCharacters": ["A"],
        }],
        "storyBlocks": [{
            "id": ids["block"], "revision": 1, "contentHash": node_hashes["block"],
            "lifecycle": "active", "volumeId": ids["volume"], "plotIds": [ids["plot"]],
            "order": 1, "title": "Block", "entrySituation": "Entry", "blockGoal": "Goal",
            "mainPressure": "Pressure", "expectedChange": "Change", "openQuestions": ["Q"],
            "involvedCharacters": ["A"], "stages": [{
                "id": ids["stage"], "revision": 1, "contentHash": node_hashes["stage"],
                "lifecycle": "active", "storyBlockId": ids["block"], "order": 1,
                "title": "Stage", "purpose": "Purpose", "dramaticQuestion": "Dramatic?",
                "sceneTasks": [{
                    "id": ids["task"], "revision": 1, "contentHash": node_hashes["task"],
                    "lifecycle": "active", "stageId": ids["stage"], "order": 1,
                    "task": "Act", "completionEvidence": "Done",
                }],
            }],
        }],
        "contentHash": "f" * 64,
    })
    bible_lists = {
        field: ({"id": f"00000000-0000-0000-0000-{index:012d}", "text": field},)
        for index, field in enumerate((
            "worldRules", "coreCast", "factions", "longTermConflicts",
            "relationshipDynamics", "continuityGuardrails", "openDesignQuestions",
        ), start=201)
    }
    bible = BiblePayload.model_validate({
        "premiseAndPromise": "Promise", "powerOrProgressionSystem": "Progress",
        "protagonist": "Hero", "toneAndNarrativeBoundaries": "Tone", **bible_lists,
    })
    outline = ChapterOutline.model_validate({
        "schemaVersion": "chapter-outline-v1", "chapterNumber": 1,
        "planningRevisionId": ids["planning"], "planningRevision": 4,
        "planningHash": "f" * 64,
        "volumeRef": {"id": ids["volume"], "revision": 1, "contentHash": node_hashes["volume"]},
        "storyBlockRef": {"id": ids["block"], "revision": 1, "contentHash": node_hashes["block"]},
        "stageRefs": [{"id": ids["stage"], "revision": 1, "contentHash": node_hashes["stage"]}],
        "sceneTaskRefs": [{"id": ids["task"], "revision": 1, "contentHash": node_hashes["task"]}],
        "chapterGoal": "Goal", "expectedCharacters": ["A"], "continuation": ["Continue"],
        "plannedTasks": ["Act"], "scenes": ["Scene"], "forbiddenEarlyEvents": ["Reveal"],
        "capacityPolicy": {"targetMin": 1, "targetMax": 2, "softCeiling": 3},
        "canonRevision": 0, "projectionRevision": 0, "projectionHash": "e" * 64,
        "contentHash": "d" * 64,
    })
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
        "planning_revisions": [_owned_row(
            "planning_revisions", id=ids["planning"], project_id="project-db", revision=4,
            content_json=json.dumps(planning.model_dump(mode="json", by_alias=True)), content_hash="f" * 64,
        )],
        "creation_bible_revisions": [_owned_row(
            "creation_bible_revisions", id=ids["bible"], project_id="project-db", revision=2,
            content_json=json.dumps(bible.model_dump(mode="json", by_alias=True)), content_hash="c" * 64,
        )],
            "chapter_outline_revisions": [_owned_row(
                "chapter_outline_revisions", id=ids["outline"], project_id="project-db",
                planning_revision_id=ids["planning"], revision=1,
            content_json=json.dumps(outline.model_dump(mode="json", by_alias=True)), content_hash="d" * 64,
        )],
    })

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    records = {record.entity_type: record.to_public_dict()["data"] for record in snapshot.graph_records}
    planning_payload = records["planning-revision"]["payload"]
    volume, plot, block = planning_payload["volumes"][0], planning_payload["plots"][0], planning_payload["storyBlocks"][0]
    stage, task = block["stages"][0], block["stages"][0]["sceneTasks"][0]
    assert planning_payload["activeStoryBlockId"] == block["id"]
    assert block["volumeId"] == volume["id"]
    assert block["plotIds"] == [plot["id"]]
    assert stage["storyBlockId"] == block["id"]
    assert task["stageId"] == stage["id"]
    assert {volume["contentHash"], plot["contentHash"], block["contentHash"], stage["contentHash"], task["contentHash"]} == set(node_hashes.values())
    bible_payload = records["creation-bible-revision"]["payload"]
    assert bible_payload["worldRules"][0]["id"].startswith("bible-world-rule:")
    outline_payload = records["chapter-outline-revision"]["payload"]
    assert outline_payload["planningRevisionId"] == records["chapter-outline-revision"]["planningRevisionLogicalId"]
    assert outline_payload["volumeRef"]["id"] == volume["id"]
    assert outline_payload["storyBlockRef"]["id"] == block["id"]
    assert outline_payload["stageRefs"][0]["id"] == stage["id"]
    assert outline_payload["sceneTaskRefs"][0]["id"] == task["id"]
    public_snapshot = repr(records)
    assert all(database_id not in public_snapshot for database_id in ids.values())
    assert all(item["id"] not in public_snapshot for values in bible_lists.values() for item in values)


@pytest.mark.asyncio
async def test_authority_payload_rejects_an_unknown_raw_identity_without_cause() -> None:
    payload = json.loads(_planning_authority_json("block-db", "a" * 64))
    payload["volumes"][0]["unknownId"] = "00000000-0000-0000-0000-000000000999"
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
        "planning_revisions": [_owned_row(
            "planning_revisions", id="planning-db", project_id="project-db", revision=1,
            content_json=json.dumps(payload), content_hash="a" * 64,
        )],
    })

    with pytest.raises(ProjectPackageInvalid, match="invalid package value") as raised:
        await ProjectPackageRepository(
            pool=_SnapshotPool(session), session_factory=lambda value: value,
        ).read_snapshot("project-db", 7)

    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_repository_rejects_a_dangling_logical_reference_with_fixed_error() -> None:
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
        "creative_seed_revisions": [_owned_row(
            "creative_seed_revisions", id="seed-revision-db", project_id="project-db",
            seed_id="missing-seed-db", revision=1, payload_json="{}", content_hash="a" * 64,
            created_at=1,
        )],
    })

    with pytest.raises(ProjectPackageInvalid, match="invalid package value") as raised:
        await ProjectPackageRepository(
            pool=_SnapshotPool(session), session_factory=lambda value: value,
        ).read_snapshot("project-db", 7)

    assert raised.value.__cause__ is None
    assert "missing-seed-db" not in str(raised.value)
    assert session.calls[-2:] == [("ROLLBACK", None), ("RELEASE", None)]


@pytest.mark.asyncio
async def test_repository_busy_sql_blocks_starting_and_running_not_pending() -> None:
    session = _SnapshotSession({})
    with pytest.raises(ProjectPackageInvalid):
        await ProjectPackageRepository(
            pool=_SnapshotPool(session), session_factory=lambda value: value,
        ).read_snapshot("project-db", 7)

    busy_sql = next(sql for sql, _ in session.calls if "SELECT 1 AS present WHERE EXISTS" in sql)
    assert "status IN ('starting','running')" in busy_sql
    assert "pending" not in busy_sql


@pytest.mark.asyncio
async def test_repository_keeps_provider_secrets_private_and_exports_only_public_history() -> None:
    api_key = "PRIVATE_API_KEY_SENTINEL"
    base_url = "https://private-provider.invalid/sentinel"
    session = _SnapshotSession(
        {
            "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
            "project_model_binding_revisions": [_owned_row(
                "project_model_binding_revisions", id="binding-db", project_id="project-db",
                revision=2, content_hash="a" * 64, created_at=1,
            )],
            "project_model_binding_items": [_owned_row(
                "project_model_binding_items", binding_revision_id="binding-db", task_key="planning",
                resolution_status="resolved", provider_name_snapshot="Owned provider",
                model_name_snapshot="owned-model", item_hash="b" * 64,
            )],
            "project_model_binding_heads": [_owned_row(
                "project_model_binding_heads", project_id="project-db", revision=2,
                binding_revision_id="binding-db", content_hash="a" * 64, updated_at=2,
            )],
        },
        extra_rows={"FROM provider_profiles p": [{
            "provider_name": "Profile-only provider", "model_name": "profile-only-model",
            "api_key": api_key, "base_url": base_url,
        }]},
    )

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    public = repr(tuple(record.to_public_dict() for record in snapshot.provider_history_records))
    assert all(record.entity_type == "provider-history" for record in snapshot.provider_history_records)
    assert "Owned provider" in public and "owned-model" in public
    assert "Profile-only provider" not in public and "profile-only-model" not in public
    provider_history = snapshot.provider_history_records[0]
    assert provider_history.data["taskKey"] == "planning"
    assert provider_history.data["bindingRevisionLogicalId"].startswith("project-model-binding-revision:")
    assert provider_history.data["bindingHash"] == "a" * 64
    assert {record.entity_type for record in snapshot.graph_records} >= {
        "project-model-binding-revision", "project-model-binding-item", "project-model-binding-head",
    }
    assert api_key not in public and base_url not in public
    assert snapshot.referenced_secret_values == (api_key.encode(), base_url.encode())
    provider_sql = next(sql for sql, _ in session.calls if "FROM provider_profiles p" in sql)
    assert "p.id AS" not in provider_sql
    assert "p.base_url AS base_url" in provider_sql
    assert "p.api_key AS api_key" in provider_sql


@pytest.mark.asyncio
async def test_repository_freezes_exact_referenced_style_template_revision() -> None:
    session = _SnapshotSession(
        {
            "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
            "style_contracts": [_owned_row(
                "style_contracts", id="style-contract-db", project_id="project-db",
                revision=1, merged_style_json="{}", likes_json="[]", dislikes_json="[]",
                content_hash="b" * 64,
            )],
            "style_contract_template_refs": [_owned_row(
                "style_contract_template_refs", style_contract_id="style-contract-db",
                style_template_id="style-template-db", asset_revision=3, asset_hash="c" * 64,
                role="primary", sort_order=1,
            )],
        },
        extra_rows={"FROM style_templates": [{
            "id": "style-template-db", "stable_key": "classic", "revision": 3,
            "name": "Classic", "payload_json": '{"tone":"warm"}',
            "provenance_json": '{"source":"fixture"}', "content_hash": "c" * 64,
            "status": "archived", "created_at": 4,
        }]},
    )

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    assert len(snapshot.frozen_asset_records) == 1
    assert snapshot.frozen_asset_records[0].data["assetKind"] == "style-template"
    assert snapshot.frozen_asset_records[0].data["revision"] == 3
    assert snapshot.frozen_asset_records[0].data["payload"]["tone"] == "warm"
    style_ref = next(record for record in snapshot.graph_records if record.entity_type == "style-contract-template-ref")
    assert style_ref.data["templateName"] == "Classic"
    assert style_ref.data["templateRevision"] == 3
    assert style_ref.data["contentHash"] == "c" * 64
    assert "style-template-db" not in repr(tuple(record.to_public_dict() for record in snapshot.frozen_asset_records))


@pytest.mark.asyncio
async def test_repository_rejects_invalid_authoritative_json_without_cause() -> None:
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
        "planning_revisions": [_owned_row(
            "planning_revisions", id="planning-db", project_id="project-db", revision=1,
            content_json="{not-json", content_hash="d" * 64, created_at=1,
        )],
    })
    with pytest.raises(ProjectPackageInvalid, match="invalid package value") as raised:
        await ProjectPackageRepository(
            pool=_SnapshotPool(session), session_factory=lambda value: value,
        ).read_snapshot("project-db", 7)
    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_engine_and_experience_refs_export_complete_restore_authority() -> None:
    contract, rows, extra_rows = _minimal_creation_contract_fixture(
        contract_id="contract-db",
        seed_id="seed-db",
        seed_revision_id="seed-revision-db",
        engine_batch_id="batch-db",
        engine_option_id="engine-db",
        style_contract_id="style-contract-db",
        style_template_id="style-template-db",
        experience_card_id="experience-db",
    )
    rows["creation_contract_experience_refs"] = [_owned_row(
        "creation_contract_experience_refs", creation_contract_id="contract-db",
        experience_card_id="experience-db", asset_revision=4, asset_hash="c" * 64,
        sort_order=1,
    )]
    extra_rows["FROM experience_cards"] = [{
        "id": "experience-db", "stable_key": "mentor", "revision": 4,
        "title": "Mentor", "category": "character", "payload_json": "{}",
        "provenance_json": "{}", "content_hash": "c" * 64,
        "status": "active", "created_at": 1,
    }]
    session = _SnapshotSession(
        {
            "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
            **rows,
        },
        extra_rows=extra_rows,
    )

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    records = {record.entity_type: record.data for record in snapshot.graph_records}
    engine = records["creation-contract-engine-ref"]
    assert engine["creationContractLogicalId"].startswith("creation-contract:")
    assert engine["storyEngineLogicalId"].startswith("story-engine-option:")
    assert engine["contentHash"] == contract.engineHash
    experience = records["creation-contract-experience-ref"]
    assert experience["experienceTitle"] == "Mentor"
    assert experience["experienceRevision"] == 4
    assert experience["contentHash"] == "c" * 64


@pytest.mark.asyncio
async def test_repository_freezes_referenced_corpus_revision_and_blob_descriptor() -> None:
    content_hash = "d" * 64
    storage_key = f"sha256/dd/{content_hash}"
    _, rows, extra_rows = _minimal_creation_contract_fixture(
        contract_id="contract-db",
        seed_id="seed-db",
        seed_revision_id="seed-revision-db",
        engine_batch_id="batch-db",
        engine_option_id="engine-db",
        style_contract_id="style-contract-db",
        style_template_id="style-template-db",
        corpus_source_id="source-db",
        corpus_revision_id="revision-db",
        corpus_chapter_id="chapter-db",
        corpus_fragment_id="fragment-db",
    )
    rows.update({
        "creation_contract_corpus_refs": [_owned_row(
            "creation_contract_corpus_refs", creation_contract_id="contract-db",
            corpus_source_id="source-db", source_revision=5, source_hash="d" * 64,
            selection_mode="full", sort_order=1,
        )],
        "creation_contract_corpus_fragment_refs": [_owned_row(
            "creation_contract_corpus_fragment_refs", creation_contract_id="contract-db",
            corpus_source_id="source-db", corpus_chapter_id="chapter-db",
            corpus_fragment_id="fragment-db", source_revision=5, source_hash="d" * 64,
            fragment_hash="e" * 64, chapter_char_start=0, chapter_char_end=9,
            reference_use="style", sort_order=1,
        )],
    })
    session = _SnapshotSession(
        {
            "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
            **rows,
            "reference_uses": [_owned_row(
                "reference_uses", id="reference-use-db", project_id="project-db",
                corpus_source_id="source-db", corpus_chapter_id="chapter-db",
                reference_purpose="background", referenced_text_hash="6" * 64, created_at=5,
            )],
        },
        extra_rows={
            **extra_rows,
            "JOIN corpus_source_revisions r ON r.id=c.source_revision_id": [{
                "source_id": "source-db", "revision": 5, "content_hash": "d" * 64,
            }],
            "FROM corpus_source_revisions r": [{
                "id": "revision-db", "source_id": "source-db", "source_key": "fixture-source",
                "revision": 5, "content_hash": "d" * 64, "relative_path": "fixture.txt",
                "display_name": "Fixture", "author": "Author", "reference_tags_json": "[]",
                "notes": "", "provenance_json": "{}", "byte_length": 9, "encoding": "utf-8",
                "parser_version": "p1", "normalizer_version": "n1", "fragmenter_version": "f1",
                "index_version": "i1", "status": "analyzed", "imported_at": 1,
                "analyzed_at": 2, "created_at": 1, "blob_byte_length": 9, "storage_key": storage_key,
            }],
            "FROM corpus_chapters c": [{
                "chapter_id": "chapter-db", "chapter_order": 1, "title": "Chapter one",
                "raw_byte_start": 0, "raw_byte_end": 9, "normalized_char_start": 0,
                "normalized_char_end": 9, "normalized_text": "chapter text",
                "content_hash": "4" * 64, "created_at": 3,
            }],
            "FROM corpus_fragments f": [{
                "fragment_id": "fragment-db",
                "fragment_order": 1, "chapter_char_start": 0, "chapter_char_end": 9,
                "normalized_text": "fragment text", "content_hash": "e" * 64,
                "analysis_version": "v1", "index_payload": '{"terms":[]}', "created_at": 4,
            }],
        },
    )

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    assert snapshot.corpus_revision_records[0].data["sourceKey"] == "fixture-source"
    assert snapshot.corpus_revision_records[0].data["referenceTags"] == ()
    assert snapshot.corpus_revision_records[0].data["chapters"][0]["chapterOrder"] == 1
    assert snapshot.corpus_revision_records[0].data["fragments"][0]["fragmentOrder"] == 1
    assert snapshot.corpus_revision_records[0].data["chapters"][0]["normalizedText"] == "chapter text"
    assert snapshot.corpus_revision_records[0].data["fragments"][0]["logicalId"] == "corpus-fragment:1"
    assert "chapter-db" not in repr(snapshot.corpus_revision_records[0].to_public_dict())
    assert snapshot.corpus_blobs == (FrozenCorpusBlob("corpus-blob:1", "d" * 64, 9, storage_key),)
    corpus_ref = next(record for record in snapshot.graph_records if record.entity_type == "creation-contract-corpus-ref")
    assert corpus_ref.data["corpusRevisionLogicalId"] == snapshot.corpus_revision_records[0].logical_id
    assert corpus_ref.data["contentHash"] == "d" * 64
    fragment_ref = next(
        record for record in snapshot.graph_records
        if record.entity_type == "creation-contract-corpus-fragment-ref"
    )
    assert fragment_ref.data["corpusRevisionLogicalId"] == snapshot.corpus_revision_records[0].logical_id
    assert fragment_ref.data["contentHash"] == "e" * 64
    reference_use = next(record for record in snapshot.graph_records if record.entity_type == "reference-use")
    assert reference_use.data["corpusRevisionLogicalId"] == snapshot.corpus_revision_records[0].logical_id
    assert "source-db" not in repr(tuple(record.to_public_dict() for record in snapshot.corpus_revision_records))


@pytest.mark.asyncio
async def test_creation_contract_payload_rewrites_every_frozen_database_reference() -> None:
    raw_ids = {
        "seed": "11111111-1111-4111-8111-111111111111",
        "seed_revision": "22222222-2222-4222-8222-222222222222",
        "batch": "33333333-3333-4333-8333-333333333333",
        "engine": "44444444-4444-4444-8444-444444444444",
        "binding": "55555555-5555-4555-8555-555555555555",
        "contract": "66666666-6666-4666-8666-666666666666",
        "style_contract": "77777777-7777-4777-8777-777777777777",
        "primary_style": "88888888-8888-4888-8888-888888888888",
        "secondary_style": "99999999-9999-4999-8999-999999999999",
        "experience": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "corpus_source": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "corpus_revision": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "corpus_chapter": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "corpus_fragment": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    }
    content_json = _creation_contract_authority_json(
        seed_revision_id=raw_ids["seed_revision"],
        engine_option_id=raw_ids["engine"],
        primary_style_id=raw_ids["primary_style"],
        secondary_style_id=raw_ids["secondary_style"],
        experience_card_id=raw_ids["experience"],
        corpus_source_id=raw_ids["corpus_source"],
        corpus_revision_id=raw_ids["corpus_revision"],
        corpus_chapter_id=raw_ids["corpus_chapter"],
        corpus_fragment_id=raw_ids["corpus_fragment"],
        binding_revision_id=raw_ids["binding"],
        corpus_fragment_start=10,
        corpus_fragment_end=110,
    )
    contract = CreationContractPayload.model_validate_json(content_json)
    storage_key = f"sha256/dd/{'d' * 64}"
    session = _SnapshotSession(
        {
            "projects": [_owned_row(
                "projects", id="project-db", lifecycle_revision=7, title="P",
            )],
            "creative_seeds": [_owned_row(
                "creative_seeds", id=raw_ids["seed"], project_id="project-db",
            )],
            "creative_seed_revisions": [_owned_row(
                "creative_seed_revisions", id=raw_ids["seed_revision"],
                project_id="project-db", seed_id=raw_ids["seed"], revision=1,
                payload_json=contract.selectedSeed.model_dump_json(),
                content_hash=contract.seedHash,
            )],
            "story_engine_batches": [_owned_row(
                "story_engine_batches", id=raw_ids["batch"], project_id="project-db",
                status="completed",
            )],
            "story_engine_options": [_owned_row(
                "story_engine_options", id=raw_ids["engine"], project_id="project-db",
                batch_id=raw_ids["batch"], option_order=1,
                payload_json=contract.selectedEngine.model_dump_json(),
                content_hash=contract.engineHash,
            )],
            "project_model_binding_revisions": [_owned_row(
                "project_model_binding_revisions", id=raw_ids["binding"],
                project_id="project-db", source_project_id="project-db", revision=6,
                content_hash="f" * 64,
            )],
            "creation_contracts": [_owned_row(
                "creation_contracts", id=raw_ids["contract"], project_id="project-db",
                revision=1, seed_id=raw_ids["seed"],
                seed_revision_id=raw_ids["seed_revision"], seed_hash=contract.seedHash,
                binding_revision_id=raw_ids["binding"], binding_hash="f" * 64,
                content_json=content_json, content_hash="0" * 64,
            )],
            "style_contracts": [_owned_row(
                "style_contracts", id=raw_ids["style_contract"], project_id="project-db",
                creation_contract_id=raw_ids["contract"], revision=1,
                merged_style_json="{}", likes_json="[]", dislikes_json="[]",
                content_hash="1" * 64,
            )],
            "creation_contract_engine_refs": [_owned_row(
                "creation_contract_engine_refs", creation_contract_id=raw_ids["contract"],
                project_id="project-db", engine_option_id=raw_ids["engine"],
                engine_hash=contract.engineHash,
            )],
            "style_contract_template_refs": [
                _owned_row(
                    "style_contract_template_refs", style_contract_id=raw_ids["style_contract"],
                    style_template_id=raw_ids["primary_style"], asset_revision=2,
                    asset_hash="a" * 64, role="primary", sort_order=1,
                ),
                _owned_row(
                    "style_contract_template_refs", style_contract_id=raw_ids["style_contract"],
                    style_template_id=raw_ids["secondary_style"], asset_revision=3,
                    asset_hash="b" * 64, role="secondary", sort_order=2,
                ),
            ],
            "creation_contract_experience_refs": [_owned_row(
                "creation_contract_experience_refs", creation_contract_id=raw_ids["contract"],
                experience_card_id=raw_ids["experience"], asset_revision=4,
                asset_hash="c" * 64, sort_order=1,
            )],
            "creation_contract_corpus_refs": [_owned_row(
                "creation_contract_corpus_refs", creation_contract_id=raw_ids["contract"],
                corpus_source_id=raw_ids["corpus_source"], source_revision=5,
                source_hash="d" * 64, selection_mode="full", sort_order=1,
            )],
            "creation_contract_corpus_fragment_refs": [_owned_row(
                "creation_contract_corpus_fragment_refs",
                creation_contract_id=raw_ids["contract"],
                corpus_source_id=raw_ids["corpus_source"],
                corpus_chapter_id=raw_ids["corpus_chapter"],
                corpus_fragment_id=raw_ids["corpus_fragment"], source_revision=5,
                source_hash="d" * 64, fragment_hash="e" * 64,
                chapter_char_start=0, chapter_char_end=9,
                reference_use="style", sort_order=1,
            )],
        },
        extra_rows={
            "FROM style_templates": {
                (raw_ids["primary_style"], 2, "a" * 64): [{
                    "id": raw_ids["primary_style"], "stable_key": "primary",
                    "revision": 2, "name": "Primary", "payload_json": "{}",
                    "provenance_json": "{}", "content_hash": "a" * 64,
                    "status": "active", "created_at": 1,
                }],
                (raw_ids["secondary_style"], 3, "b" * 64): [{
                    "id": raw_ids["secondary_style"], "stable_key": "secondary",
                    "revision": 3, "name": "Secondary", "payload_json": "{}",
                    "provenance_json": "{}", "content_hash": "b" * 64,
                    "status": "active", "created_at": 2,
                }],
            },
            "FROM experience_cards": [{
                "id": raw_ids["experience"], "stable_key": "experience",
                "revision": 4, "title": "Experience", "category": "plot",
                "payload_json": "{}", "provenance_json": "{}",
                "content_hash": "c" * 64, "status": "active", "created_at": 3,
            }],
            "FROM corpus_source_revisions r": [{
                "id": raw_ids["corpus_revision"], "source_id": raw_ids["corpus_source"],
                "source_key": "fixture-source", "revision": 5, "content_hash": "d" * 64,
                "relative_path": "fixture.txt", "display_name": "Fixture", "author": "Author",
                "reference_tags_json": "[]", "notes": "", "provenance_json": "{}",
                "byte_length": 9, "encoding": "utf-8", "parser_version": "p1",
                "normalizer_version": "n1", "fragmenter_version": "f1",
                "index_version": "i1", "status": "analyzed", "imported_at": 1,
                "analyzed_at": 2, "created_at": 1, "blob_byte_length": 9,
                "storage_key": storage_key,
            }],
            "FROM corpus_chapters c": [{
                "chapter_id": raw_ids["corpus_chapter"], "chapter_order": 1,
                "title": "Chapter", "raw_byte_start": 0, "raw_byte_end": 9,
                "normalized_char_start": 0, "normalized_char_end": 9,
                "normalized_text": "chapter", "content_hash": "2" * 64,
                "created_at": 3,
            }],
            "FROM corpus_fragments f": [{
                "fragment_id": raw_ids["corpus_fragment"], "fragment_order": 1,
                "chapter_char_start": 0, "chapter_char_end": 300,
                "normalized_text": "fragment", "content_hash": "e" * 64,
                "analysis_version": "v1", "index_payload": "{}", "created_at": 4,
            }],
        },
    )

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    creation = next(
        record for record in snapshot.graph_records if record.entity_type == "creation-contract"
    )
    payload = creation.data["payload"]
    graph_by_type = {record.entity_type: record for record in snapshot.graph_records}
    assets_by_hash = {
        record.data["contentHash"]: record for record in snapshot.frozen_asset_records
    }
    corpus = snapshot.corpus_revision_records[0]
    assert payload["selectedSeed"] == freeze_json_value(contract.selectedSeed.model_dump(mode="json"))
    assert payload["selectedEngine"] == freeze_json_value(contract.selectedEngine.model_dump(mode="json"))
    assert payload["seedHash"] == contract.seedHash
    assert payload["engineHash"] == contract.engineHash
    assert payload["seedRevisionId"] == graph_by_type["creative-seed-revision"].logical_id
    assert payload["engineOptionId"] == graph_by_type["story-engine-option"].logical_id
    assert payload["primaryStyleRef"]["id"] == assets_by_hash["a" * 64].logical_id
    assert payload["secondaryStyleRef"]["id"] == assets_by_hash["b" * 64].logical_id
    assert payload["experienceCardRefs"][0]["id"] == assets_by_hash["c" * 64].logical_id
    assert payload["corpusSourceRefs"][0]["id"] == corpus.logical_id
    assert payload["corpusSourceRefs"][0]["revisionId"] == corpus.logical_id
    assert payload["corpusSourceRefs"][0]["fragments"][0]["chapterId"] == corpus.data["chapters"][0]["logicalId"]
    assert payload["corpusSourceRefs"][0]["fragments"][0]["fragmentId"] == corpus.data["fragments"][0]["logicalId"]
    assert payload["corpusSourceRefs"][0]["fragments"][0]["chapterCharStart"] == 10
    assert payload["corpusSourceRefs"][0]["fragments"][0]["chapterCharEnd"] == 110
    assert corpus.data["fragments"][0]["chapterCharStart"] == 0
    assert corpus.data["fragments"][0]["chapterCharEnd"] == 300
    assert payload["modelBindingRef"]["id"] == graph_by_type["project-model-binding-revision"].logical_id
    assert all(raw_id not in repr(snapshot) for raw_id in raw_ids.values())


@pytest.mark.asyncio
async def test_creation_contract_payload_rejects_missing_frozen_reference_without_cause() -> None:
    missing_seed_revision_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    content_json = _creation_contract_authority_json(
        seed_revision_id=missing_seed_revision_id,
        engine_option_id="engine-option",
        primary_style_id="primary-style",
        secondary_style_id="secondary-style",
        experience_card_id="experience-card",
        corpus_source_id="corpus-source",
        corpus_revision_id="corpus-revision",
        corpus_chapter_id="corpus-chapter",
        corpus_fragment_id="corpus-fragment",
        binding_revision_id="binding-revision",
    )
    session = _SnapshotSession({
        "projects": [_owned_row(
            "projects", id="project-db", lifecycle_revision=7, title="P",
        )],
        "creation_contracts": [_owned_row(
            "creation_contracts", id="contract-db", project_id="project-db",
            revision=1, content_json=content_json, content_hash="0" * 64,
        )],
    })

    with pytest.raises(ProjectPackageInvalid, match="invalid package value") as raised:
        await ProjectPackageRepository(
            pool=_SnapshotPool(session), session_factory=lambda value: value,
        ).read_snapshot("project-db", 7)

    assert raised.value.__cause__ is None
    assert missing_seed_revision_id not in str(raised.value)


@pytest.mark.asyncio
async def test_finalization_receipt_rewrites_closed_result_authority_ids() -> None:
    finalization_record_id = "11111111-1111-4111-8111-111111111111"
    final_chapter_id = "22222222-2222-4222-8222-222222222222"
    planning_revision_id = "33333333-3333-4333-8333-333333333333"
    planning_hash = "a" * 64
    projection_hash = "b" * 64
    receipt = {
        "finalChapterId": final_chapter_id,
        "canonRevision": 3,
        "projectionHash": projection_hash,
        "planningRevisionId": planning_revision_id,
        "planningRevision": 1,
        "planningHash": planning_hash,
    }
    session = _SnapshotSession({
        "projects": [_owned_row(
            "projects", id="project-db", lifecycle_revision=7, title="P",
        )],
        "planning_revisions": [_owned_row(
            "planning_revisions", id=planning_revision_id, project_id="project-db",
            revision=1, content_json=_planning_authority_json("block-db", planning_hash),
            content_hash=planning_hash,
        )],
        "finalization_records": [_owned_row(
            "finalization_records", id=finalization_record_id, project_id="project-db",
            committed_canon_revision=3, result_payload_json=json.dumps(receipt),
            finalized_at=10,
        )],
        "final_chapters": [_owned_row(
            "final_chapters", id=final_chapter_id, project_id="project-db",
            finalization_record_id=finalization_record_id, chapter_num=1,
            content="final", content_hash="c" * 64,
            planning_revision_id=planning_revision_id, planning_revision=1,
            planning_hash=planning_hash, canon_revision=3, finalized_at=10,
        )],
    })

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    by_type = {record.entity_type: record for record in snapshot.graph_records}
    result = by_type["finalization-record"].data["resultPayload"]
    assert result == {
        "finalChapterId": by_type["final-chapter"].logical_id,
        "canonRevision": 3,
        "projectionHash": projection_hash,
        "planningRevisionId": by_type["planning-revision"].logical_id,
        "planningRevision": 1,
        "planningHash": planning_hash,
    }
    assert final_chapter_id not in repr(snapshot)
    assert planning_revision_id not in repr(snapshot)


@pytest.mark.asyncio
async def test_finalization_authority_payloads_rewrite_all_local_and_external_ids() -> None:
    payload, raw_ids = _full_finalization_change_set_payload()
    existing_entity_id, entity_id, _, _, _, _, _, planning_target_id = raw_ids
    finding_id = "99999999-9999-4999-8999-999999999999"
    quality_finding = {
        "id": finding_id,
        "dimension": "dialogue_credibility",
        "reason": "人物语气缺少区分",
        "suggestedAction": "调整第二段对话",
        "evidence": {
            "startScalar": 0, "endScalar": 4, "excerptHash": "a" * 64,
            "confidence": 0.9, "rationale": "正文直接陈述",
        },
    }
    session = _SnapshotSession({
        "projects": [_owned_row(
            "projects", id="project-db", lifecycle_revision=7, title="P",
        )],
        "planning_revisions": [_owned_row(
            "planning_revisions", id="planning-db", project_id="project-db",
            revision=1, content_json=_planning_authority_json(planning_target_id, "b" * 64),
            content_hash="b" * 64,
        )],
        "canon_entities": [_owned_row(
            "canon_entities", id=existing_entity_id, project_id="project-db",
            entity_type="person", canonical_name="Existing", normalized_name="existing",
            created_revision=1, created_at=1,
        )],
        "finalization_change_sets": [_owned_row(
            "finalization_change_sets", id="change-set-db", project_id="project-db",
            status="awaiting_author", current_revision=1, current_revision_hash="c" * 64,
        )],
        "finalization_change_set_revisions": [_owned_row(
            "finalization_change_set_revisions", id="change-set-revision-db",
            project_id="project-db", change_set_id="change-set-db", revision=1,
            payload_json=json.dumps(payload), content_hash="c" * 64,
            source="extraction", created_at=2,
        )],
        "candidate_quality_reports": [_owned_row(
            "candidate_quality_reports", id="quality-db", project_id="project-db",
            status="completed", findings_json=json.dumps([quality_finding]),
            deterministic_blocks_json="[]", content_hash="d" * 64, created_at=2,
        )],
    })

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    by_type = {record.entity_type: record for record in snapshot.graph_records}
    rewritten = by_type["finalization-change-set-revision"].data["payload"]
    canon_logical_id = by_type["canon-entity"].logical_id
    story_block_logical_id = rewritten["storyProgressEvents"][0]["targetId"]
    assert rewritten["existingEntityIds"] == (canon_logical_id,)
    assert rewritten["entities"][0]["id"].startswith("finalization-entity:")
    assert rewritten["aliases"][0]["id"].startswith("finalization-alias:")
    assert rewritten["aliases"][0]["entityId"] == rewritten["entities"][0]["id"]
    assert rewritten["canonEvents"][0]["id"].startswith("finalization-event:")
    assert rewritten["canonEvents"][0]["entityId"] == canon_logical_id
    assert rewritten["storyProgressEvents"][0]["id"].startswith("finalization-progress-event:")
    assert rewritten["planningPatches"][0]["id"].startswith("finalization-planning-patch:")
    assert rewritten["planningPatches"][0]["targetId"] == story_block_logical_id
    assert rewritten["planningSuggestions"][0]["id"].startswith(
        "finalization-planning-suggestion:"
    )
    assert rewritten["planningSuggestions"][0]["targetId"] == story_block_logical_id
    assert rewritten["planningPatches"][0]["expectedHash"] == payload["planningPatches"][0]["expectedHash"]
    assert rewritten["canonEvents"][0]["evidence"]["excerptHash"] == "a" * 64
    finding = by_type["candidate-quality"].data["findings"][0]
    assert finding["id"].startswith("quality-finding:")
    assert finding["reason"] == quality_finding["reason"]
    rendered = repr(snapshot)
    assert entity_id not in rendered
    assert finding_id not in rendered
    assert all(raw_id not in rendered for raw_id in raw_ids)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_kind",
    ("dangling-canon", "unknown-local", "planning-type-mismatch", "extra-field", "quality-extra"),
)
async def test_finalization_authority_payloads_fail_closed_without_cause(
    failure_kind: str,
) -> None:
    payload, raw_ids = _full_finalization_change_set_payload()
    existing_entity_id, _, _, _, _, _, _, planning_target_id = raw_ids
    canon_rows = [_owned_row(
        "canon_entities", id=existing_entity_id, project_id="project-db",
        entity_type="person", canonical_name="Existing", normalized_name="existing",
        created_revision=1, created_at=1,
    )]
    quality_finding = {
        "id": "99999999-9999-4999-8999-999999999999",
        "dimension": "dialogue_credibility",
        "reason": "人物语气缺少区分",
        "suggestedAction": "调整第二段对话",
        "evidence": {
            "startScalar": 0, "endScalar": 4, "excerptHash": "a" * 64,
            "confidence": 0.9, "rationale": "正文直接陈述",
        },
    }
    if failure_kind == "dangling-canon":
        canon_rows = []
    elif failure_kind == "unknown-local":
        payload["aliases"][0]["entityId"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    elif failure_kind == "planning-type-mismatch":
        payload["storyProgressEvents"][0]["targetType"] = "stage"
    elif failure_kind == "extra-field":
        payload["unexpectedId"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    else:
        quality_finding["unexpectedId"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    session = _SnapshotSession({
        "projects": [_owned_row(
            "projects", id="project-db", lifecycle_revision=7, title="P",
        )],
        "planning_revisions": [_owned_row(
            "planning_revisions", id="planning-db", project_id="project-db",
            revision=1, content_json=_planning_authority_json(planning_target_id, "b" * 64),
            content_hash="b" * 64,
        )],
        "canon_entities": canon_rows,
        "finalization_change_sets": [_owned_row(
            "finalization_change_sets", id="change-set-db", project_id="project-db",
            status="awaiting_author", current_revision=1, current_revision_hash="c" * 64,
        )],
        "finalization_change_set_revisions": [_owned_row(
            "finalization_change_set_revisions", id="change-set-revision-db",
            project_id="project-db", change_set_id="change-set-db", revision=1,
            payload_json=json.dumps(payload), content_hash="c" * 64,
            source="extraction", created_at=2,
        )],
        "candidate_quality_reports": [_owned_row(
            "candidate_quality_reports", id="quality-db", project_id="project-db",
            status="completed", findings_json=json.dumps([quality_finding]),
            deterministic_blocks_json="[]", content_hash="d" * 64, created_at=2,
        )],
    })

    with pytest.raises(ProjectPackageInvalid, match="invalid package value") as raised:
        await ProjectPackageRepository(
            pool=_SnapshotPool(session), session_factory=lambda value: value,
        ).read_snapshot("project-db", 7)

    assert raised.value.__cause__ is None
    assert all(raw_id not in str(raised.value) for raw_id in raw_ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ("dangling", "mismatch", "extra-field"))
async def test_finalization_receipt_rejects_dangling_mismatched_or_open_shape_without_cause(
    failure_kind: str,
) -> None:
    finalization_record_id = "44444444-4444-4444-8444-444444444444"
    final_chapter_id = "55555555-5555-4555-8555-555555555555"
    planning_revision_id = "66666666-6666-4666-8666-666666666666"
    planning_hash = "d" * 64
    receipt = {
        "finalChapterId": final_chapter_id,
        "canonRevision": 2,
        "projectionHash": "e" * 64,
        "planningRevisionId": planning_revision_id,
        "planningRevision": 1,
        "planningHash": planning_hash,
    }
    final_chapter_planning_hash = planning_hash
    if failure_kind == "dangling":
        receipt["finalChapterId"] = "77777777-7777-4777-8777-777777777777"
    elif failure_kind == "mismatch":
        final_chapter_planning_hash = "f" * 64
    else:
        receipt["unexpectedId"] = "88888888-8888-4888-8888-888888888888"
    session = _SnapshotSession({
        "projects": [_owned_row(
            "projects", id="project-db", lifecycle_revision=7, title="P",
        )],
        "planning_revisions": [_owned_row(
            "planning_revisions", id=planning_revision_id, project_id="project-db",
            revision=1, content_json=_planning_authority_json("block-db", planning_hash),
            content_hash=planning_hash,
        )],
        "finalization_records": [_owned_row(
            "finalization_records", id=finalization_record_id, project_id="project-db",
            committed_canon_revision=2, result_payload_json=json.dumps(receipt),
            finalized_at=10,
        )],
        "final_chapters": [_owned_row(
            "final_chapters", id=final_chapter_id, project_id="project-db",
            finalization_record_id=finalization_record_id, chapter_num=1,
            content="final", content_hash="c" * 64,
            planning_revision_id=planning_revision_id, planning_revision=1,
            planning_hash=final_chapter_planning_hash, canon_revision=2, finalized_at=10,
        )],
    })

    with pytest.raises(ProjectPackageInvalid, match="invalid package value") as raised:
        await ProjectPackageRepository(
            pool=_SnapshotPool(session), session_factory=lambda value: value,
        ).read_snapshot("project-db", 7)

    assert raised.value.__cause__ is None
    assert all(raw_id not in str(raised.value) for raw_id in receipt.values() if isinstance(raw_id, str))


@pytest.mark.asyncio
async def test_repository_resolves_nested_story_block_and_polymorphic_canon_source() -> None:
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
        "planning_revisions": [_owned_row(
            "planning_revisions", id="planning-db", project_id="project-db", revision=1,
            content_json=_planning_authority_json("block-db", "1" * 64), content_hash="1" * 64,
        )],
        "chapter_sessions": [_owned_row(
            "chapter_sessions", id="chapter-db", project_id="project-db", chapter_num=1,
            planning_revision_id="planning-db", story_block_id="block-db", status="draft",
        )],
        "finalization_change_sets": [_owned_row(
            "finalization_change_sets", id="change-set-db", project_id="project-db",
            status="committed", current_revision=1, current_revision_hash="2" * 64,
        )],
        "finalization_records": [_owned_row(
            "finalization_records", id="finalization-db", project_id="project-db",
            change_set_id="change-set-db", committed_canon_revision=1,
            result_payload_json=json.dumps({
                "finalChapterId": "final-chapter-db", "canonRevision": 1,
                "projectionHash": "3" * 64, "planningRevisionId": "planning-db",
                "planningRevision": 1, "planningHash": "1" * 64,
            }),
            finalized_at=3,
        )],
        "final_chapters": [_owned_row(
            "final_chapters", id="final-chapter-db", project_id="project-db",
            finalization_record_id="finalization-db", chapter_num=1,
            content="final", content_hash="4" * 64,
            planning_revision_id="planning-db", planning_revision=1,
            planning_hash="1" * 64, canon_revision=1, finalized_at=3,
        )],
        "canon_revisions": [_owned_row(
            "canon_revisions", id="canon-revision-db", project_id="project-db", revision_number=1,
            source_type="finalization", source_id="change-set-db", content_hash="2" * 64, created_at=3,
        )],
    })

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    canon = next(record for record in snapshot.graph_records if record.entity_type == "canon-revision")
    change_set = next(
        record for record in snapshot.graph_records
        if record.entity_type == "finalization-change-set"
    )
    assert canon.data["sourceLogicalId"] == change_set.logical_id
    assert canon.data["sourceLogicalId"].startswith("finalization-change-set:")
    assert "finalization-db" not in repr(canon.to_public_dict())
    assert "block-db" not in repr(tuple(record.to_public_dict() for record in snapshot.graph_records))


@pytest.mark.asyncio
async def test_repository_rejects_finalization_canon_source_without_change_set() -> None:
    orphan_source_id = "orphan-source-db"
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
        "finalization_records": [_owned_row(
            "finalization_records", id=orphan_source_id, project_id="project-db",
            committed_canon_revision=1, finalized_at=3,
        )],
        "canon_revisions": [_owned_row(
            "canon_revisions", id="canon-revision-db", project_id="project-db", revision_number=1,
            source_type="finalization", source_id=orphan_source_id,
            content_hash="2" * 64, created_at=3,
        )],
    })

    with pytest.raises(ProjectPackageInvalid, match="invalid package value") as raised:
        await ProjectPackageRepository(
            pool=_SnapshotPool(session), session_factory=lambda value: value,
        ).read_snapshot("project-db", 7)

    assert raised.value.__cause__ is None
    assert orphan_source_id not in str(raised.value)
    assert session.calls[-2:] == [("ROLLBACK", None), ("RELEASE", None)]


@pytest.mark.asyncio
async def test_repository_projection_rows_only_contribute_count_and_hash_validation() -> None:
    projection_hash = "3" * 64
    session = _SnapshotSession(
        {"projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")]},
        extra_rows={"FROM current_state_projections": [{"content_hash": projection_hash}]},
    )
    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    assert snapshot.projection_validation["currentStateProjections"] == {
        "count": 1, "hashes": (projection_hash,),
    }
    assert all(record.entity_type != "current-state-projection" for record in snapshot.graph_records)


@pytest.mark.asyncio
async def test_inherited_binding_source_is_inert_and_never_requires_or_leaks_external_project_id() -> None:
    external_project_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P2")],
        "project_model_binding_revisions": [_owned_row(
            "project_model_binding_revisions", id="binding-db", project_id="project-db",
            revision=1, content_hash="7" * 64, source_project_id=external_project_id, created_at=1,
        )],
    })

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    binding = next(
        record for group in (snapshot.graph_records, snapshot.provider_history_records)
        for record in group if record.entity_type == "project-model-binding-revision"
    )
    assert binding.data["sourceKind"] == "inherited"
    assert "sourceProjectLogicalId" not in binding.data
    assert external_project_id not in repr(snapshot)


def test_every_non_secret_classified_column_has_an_explicit_export_or_normalization_decision() -> None:
    classified = {
        (table, column)
        for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()
        for column, category in policy.items()
        if category not in {"derived", "excluded_sensitive_operational"}
    }
    assert set(PACKAGE_COLUMN_EXPORT_DECISIONS) == classified
    assert all(
        isinstance(decision, str) and decision and decision != "@undecided"
        for decision in PACKAGE_COLUMN_EXPORT_DECISIONS.values()
    )
    assert PACKAGE_COLUMN_EXPORT_DECISION_FINGERPRINT == (
        "15ea66b6eb6784daff215debdd202e1c82924b9902d5e868bb82c61a034fa90b"
    )
    assert {
        (table, column): PACKAGE_COLUMN_EXPORT_DECISIONS[(table, column)]
        for table, column in {
            ("creation_contract_engine_refs", "engine_option_id"),
            ("creation_contract_engine_refs", "engine_hash"),
            ("style_contract_template_refs", "asset_hash"),
            ("creation_contract_experience_refs", "asset_hash"),
            ("creation_contract_corpus_refs", "source_hash"),
            ("creation_contract_corpus_fragment_refs", "fragment_hash"),
        }
    } == {
        ("creation_contract_engine_refs", "engine_option_id"): "storyEngineLogicalId",
        ("creation_contract_engine_refs", "engine_hash"): "contentHash",
        ("style_contract_template_refs", "asset_hash"): "contentHash",
        ("creation_contract_experience_refs", "asset_hash"): "contentHash",
        ("creation_contract_corpus_refs", "source_hash"): "contentHash",
        ("creation_contract_corpus_fragment_refs", "fragment_hash"): "contentHash",
    }


@pytest.mark.asyncio
async def test_key_recovery_relations_are_exported_as_package_logical_ids_and_public_versions() -> None:
    _, contract_rows, extra_rows = _minimal_creation_contract_fixture(
        contract_id="creation-contract-db",
        seed_id="seed-db",
        seed_revision_id="seed-revision-db",
        engine_batch_id="engine-batch-db",
        engine_option_id="engine-option-db",
        style_contract_id="style-contract-db",
        style_template_id="style-template-db",
        revision=2,
    )
    session = _SnapshotSession({
        "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
        **contract_rows,
        "creation_bible_revisions": [_owned_row(
            "creation_bible_revisions", id="bible-db", project_id="project-db", revision=3,
            content_json=_bible_authority_json(), content_hash="4" * 64,
        )],
        "planning_revisions": [_owned_row(
            "planning_revisions", id="planning-db", project_id="project-db", revision=4,
            seed_id="seed-db", seed_revision_id="seed-revision-db",
            creation_contract_id="creation-contract-db", style_contract_id="style-contract-db",
            bible_revision_id="bible-db", selection_revision=1, contract_revision=2,
            bible_revision=3, content_json=_planning_authority_json("story-block-db", "5" * 64),
            content_hash="5" * 64,
        )],
        "chapter_outline_revisions": [_owned_row(
            "chapter_outline_revisions", id="outline-db", project_id="project-db", revision=5,
            chapter_num=1, planning_revision_id="planning-db", planning_revision=4,
            planning_hash="5" * 64,
            content_json=_outline_authority_json("planning-db", "story-block-db", "5" * 64, "6" * 64),
            content_hash="6" * 64,
        )],
        "chapter_sessions": [_owned_row(
            "chapter_sessions", id="chapter-db", project_id="project-db", chapter_num=1,
            planning_revision_id="planning-db", planning_revision=4, planning_hash="5" * 64,
            chapter_outline_revision_id="outline-db", chapter_outline_revision=5,
            chapter_outline_hash="6" * 64, story_block_id="story-block-db",
            story_block_revision=7, story_block_hash="7" * 64, status="draft",
        )],
        "working_drafts": [_owned_row(
            "working_drafts", id="working-draft-db", project_id="project-db",
            chapter_session_id="chapter-db", revision=1, content="draft", content_hash="8" * 64,
        )],
        "draft_candidates": [_owned_row(
            "draft_candidates", id="candidate-db", project_id="project-db",
            chapter_session_id="chapter-db", content="candidate", content_hash="9" * 64,
        )],
        "draft_operation_attempts": [_owned_row(
            "draft_operation_attempts", id="operation-db", project_id="project-db",
            chapter_session_id="chapter-db", operation_type="polish_selection", status="completed",
        )],
        "working_draft_revisions": [_owned_row(
            "working_draft_revisions", id="working-revision-db", project_id="project-db",
            working_draft_id="working-draft-db", chapter_session_id="chapter-db",
            source_candidate_id="candidate-db", source_operation_id="operation-db",
            working_draft_revision=2, content="revision", content_hash="a" * 64,
        )],
        "finalization_records": [_owned_row(
            "finalization_records", id="finalization-db", project_id="project-db",
            chapter_session_id="chapter-db", draft_candidate_id="candidate-db",
            committed_canon_revision=1,
            result_payload_json=json.dumps({
                "finalChapterId": "final-chapter-db", "canonRevision": 1,
                "projectionHash": "c" * 64, "planningRevisionId": "planning-db",
                "planningRevision": 4, "planningHash": "5" * 64,
            }),
            finalized_at=9,
        )],
        "final_chapters": [_owned_row(
            "final_chapters", id="final-chapter-db", project_id="project-db",
            chapter_session_id="chapter-db", draft_candidate_id="candidate-db",
            finalization_record_id="finalization-db", planning_revision_id="planning-db",
            planning_revision=4, planning_hash="5" * 64,
            chapter_outline_revision_id="outline-db", chapter_outline_revision=5,
            chapter_outline_hash="6" * 64, chapter_num=1, content="final", content_hash="b" * 64,
            canon_revision=1, finalized_at=10,
        )],
    }, extra_rows=extra_rows)

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)
    by_type = {record.entity_type: record for record in snapshot.graph_records}

    planning = by_type["planning-revision"].data
    assert {"seedLogicalId", "seedRevisionLogicalId", "creationContractLogicalId", "styleContractLogicalId", "bibleRevisionLogicalId"} <= set(planning)
    chapter = by_type["chapter"].data
    assert {"planningRevisionLogicalId", "outlineRevisionLogicalId", "storyBlockLogicalId", "planningRevision", "planningHash", "chapterOutlineRevision", "chapterOutlineHash", "storyBlockRevision", "storyBlockHash"} <= set(chapter)
    working_revision = by_type["working-draft-revision"].data
    assert {"workingDraftLogicalId", "chapterLogicalId", "candidateLogicalId", "operationLogicalId"} <= set(working_revision)
    final_chapter = by_type["final-chapter"].data
    assert {"chapterLogicalId", "candidateLogicalId", "planningRevisionLogicalId", "outlineRevisionLogicalId", "finalizationRecordLogicalId"} <= set(final_chapter)


@pytest.mark.asyncio
async def test_market_analysis_exports_only_referenced_snapshot_evidence() -> None:
    snapshot_id = "market-snapshot-db"
    source_id = "market-source-db"
    snapshot_hash = "c" * 64
    analysis_hash = "d" * 64
    session = _SnapshotSession(
        {
            "projects": [_owned_row("projects", id="project-db", lifecycle_revision=7, title="P")],
            "market_analyses": [_owned_row(
                "market_analyses", id="analysis-db", project_id="project-db",
                status="succeeded", analysis_json="{}", result_hash=analysis_hash,
                created_at=1, completed_at=2,
            )],
            "seed_inspiration_attempts": [_owned_row(
                "seed_inspiration_attempts", id="inspiration-db", project_id="project-db",
                market_source_id=source_id, market_snapshot_id=snapshot_id,
                market_snapshot_hash=snapshot_hash, market_analysis_id="analysis-db",
                market_analysis_hash=analysis_hash, status="succeeded", created_at=2, completed_at=3,
            )],
        },
        extra_rows={"FROM market_snapshots s": [{
            "snapshot_hash": snapshot_hash, "captured_at": 1_700_000_000_000,
        }]},
    )

    snapshot = await ProjectPackageRepository(
        pool=_SnapshotPool(session), session_factory=lambda value: value,
    ).read_snapshot("project-db", 7)

    market = next(record for record in snapshot.graph_records if record.entity_type == "market-analysis")
    assert market.data == {
        "snapshotHash": snapshot_hash,
        "timeRange": {"capturedAt": 1_700_000_000_000},
        "contentHash": analysis_hash,
        "createdAt": 1,
    }
    public = repr(market.to_public_dict())
    assert snapshot_id not in public and source_id not in public
    market_sql = next(sql for sql, _ in session.calls if "FROM market_snapshots s" in sql)
    assert "source_url" not in market_sql
    assert "SELECT *" not in market_sql.upper()
