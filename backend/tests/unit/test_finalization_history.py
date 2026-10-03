from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from backend.domain.finalization import FinalizationChangeSet, change_set_hash, change_set_payload
from backend.domain.json_contracts import canonical_hash
from backend.repositories.continuity import ContinuityRepository
from backend.repositories.finalization import FinalizationRepository
from backend.services.finalization import FinalizationConflict
from backend.services.projections import build_projection_bundle

HASH = "a" * 64
PROSE = "本章正文。"
CANDIDATE_HASH = sha256(PROSE.encode()).hexdigest()


def context(revision=14):
    basis = {"schemaVersion": "draft-candidate-basis-v1", "outlineRevisionId": "outline",
             "outlineRevision": 1, "outlineHash": HASH, "planningRevisionId": "planning",
             "planningRevision": 1, "planningHash": HASH, "canonRevision": revision,
             "projectionRevision": revision, "projectionHash": HASH}
    manifest = {"schemaVersion": "finalization-context-v1", "projectId": "p", "chapterSessionId": "s",
                "candidateId": "c", "candidateHash": CANDIDATE_HASH, "chapterNumber": 15,
                "expectedCanonRevision": revision, "expectedPlanningHash": HASH,
                "expectedOutlineHash": HASH, "contexts": {"canonHash": HASH}}
    event = {"id": "fact", "entityId": "hero", "fieldPath": "observation.Record", "factKind": "dynamic_event",
             "value": "本章新值", "assertionOperator": "equals", "valueCardinality": "single",
             "evidence": {"startScalar": 0, "endScalar": len(PROSE), "excerptHash": CANDIDATE_HASH,
                          "confidence": 1, "rationale": "本章依据"}}
    changes = FinalizationChangeSet.model_validate({"schemaVersion": "finalization-changeset-v1",
              "title": "本章", "summary": "摘要", "existingEntityIds": ["hero", "other"],
              "entities": [], "aliases": [], "canonEvents": [event], "storyProgressEvents": [],
              "planningPatches": [], "planningSuggestions": []})
    return {"project_id": "p", "chapter_session_id": "s", "attempt_id": "a", "draft_candidate_id": "c",
            "candidate_project_id": "p", "candidate_session_id": "s", "candidate_id": "c",
            "candidate_hash": CANDIDATE_HASH, "candidate_content_hash": CANDIDATE_HASH, "content": PROSE,
            "current_revision": 1, "current_revision_hash": change_set_hash(changes),
            "payload_json": change_set_payload(changes), "expected_canon_revision": revision,
            "expected_planning_hash": HASH, "expected_outline_hash": HASH,
            "context_manifest_json": manifest, "context_manifest_hash": canonical_hash(manifest),
            "provenance_json": basis, "basis_hash": canonical_hash(basis), "baseline_revision_id": "r"}


def replace_events(row, events, *, entities=None):
    payload = deepcopy(row["payload_json"])
    payload["canonEvents"] = events
    if entities is not None:
        payload["entities"] = entities
    changes = FinalizationChangeSet.model_validate(payload)
    row["payload_json"] = change_set_payload(changes)
    row["current_revision_hash"] = change_set_hash(changes)


def source(value="历史值", *, entity="hero", field="observation.Record", revision=14, order=2,
           kind="dynamic_event", status="confirmed", identity="event"):
    return {"id": identity, "project_id": "p", "entity_id": entity, "field_path": field,
            "revision_number": revision, "event_order": order, "fact_kind": kind,
            "confirmation_status": status, "payload_json": json.dumps(value, ensure_ascii=False)}


class SavedRepository:
    def __init__(self, row):
        self.row = row
        self.reads = 0

    async def read_history_context(self, session, project, chapter):
        self.reads += 1
        return deepcopy(self.row)


class HistoryRepository:
    def __init__(self, events=()):
        self.events = list(events)
        self.calls = []
        self.missing_entities = set()

    async def entity(self, session, project, entity, revision):
        self.calls.append(("entity", project, entity, revision))
        if entity in self.missing_entities:
            return None
        # The deliberately current name must never be passed off as historical.
        return {"id": entity, "canonical_name": "不可验证的新名称", "entity_type": "person"}

    async def state_history_reference(self, session, project, entity, field, revision):
        self.calls.append(("history", project, entity, field, revision))
        matches = [item for item in self.events if item["project_id"] == project
                   and item["entity_id"] == entity and item["field_path"] == field
                   and item["revision_number"] <= revision and item["confirmation_status"] == "confirmed"
                   and item["fact_kind"] != "claim"]
        return deepcopy(sorted(matches, key=lambda item: (item["revision_number"], item["event_order"]), reverse=True)[:2])


def reader(row, events=()):
    from backend.services.finalization_history import FinalizationHistoryReader, ReadFinalizationHistory
    saved = SavedRepository(row)
    history = HistoryRepository(events)
    @asynccontextmanager
    async def connection():
        yield object()
    command = ReadFinalizationHistory("p", "s", "a", "c", CANDIDATE_HASH,
                                      row["expected_canon_revision"], 1, row["current_revision_hash"])
    return FinalizationHistoryReader(saved, history, connection), command, saved, history


@pytest.mark.asyncio
async def test_reference_query_matches_exact_owner_path_before_limit_and_is_parameterized():
    class Session:
        async def fetchall(self, sql, args):
            compact = " ".join(sql.split())
            assert "CAST(event.field_path AS BINARY)=CAST(%s AS BINARY)" in compact
            assert "CAST(event.entity_id AS BINARY)=CAST(%s AS BINARY)" in compact
            assert compact.index("CAST(event.field_path") < compact.index("LIMIT 2")
            assert "event.confirmation_status='confirmed'" in compact and "event.fact_kind<>'claim'" in compact
            assert "event.revision_number<=%s" in compact
            assert "ORDER BY event.revision_number DESC, event.event_order DESC" in compact
            assert "unsafe' OR" not in sql and "MAX(" not in sql and "effective_" not in sql
            assert args == ("p", "hero", "unsafe' OR 1=1 --", 14)
            return []
    assert await ContinuityRepository().state_history_reference(Session(), "p", "hero", "unsafe' OR 1=1 --", 14) == []


@pytest.mark.asyncio
async def test_saved_context_query_is_read_only_latest_session_scoped_and_revision_joined():
    class Session:
        async def fetchone(self, sql, args):
            compact = " ".join(sql.split())
            assert "FOR UPDATE" not in compact
            assert "context_manifest_json" in compact and "provenance_json" in compact
            assert "revision.revision=attempt.current_revision" in compact
            assert "revision.content_hash=attempt.current_revision_hash" in compact
            assert "ORDER BY attempt.created_at DESC,attempt.id DESC LIMIT 1" in compact
            assert args == ("p", "s")
            return {"attempt_id": "a"}
    assert await FinalizationRepository().read_history_context(Session(), "p", "s") == {"attempt_id": "a"}


@pytest.mark.asyncio
async def test_reference_selects_last_confirmed_non_claim_with_revision_and_event_order():
    row = context()
    events = [source("旧值", revision=13), source("同版先值", order=1), source("同版末值", order=3),
              source("未来值", revision=15), source("人物说法", kind="claim", order=4),
              source("拒绝值", status="rejected", order=5), source("他人值", entity="other"),
              source("大小写近似路径", field="observation.record", order=6)]
    service, command, saved, history = reader(row, events)
    result = await service.read(command)
    item = result["items"][0]
    assert item["state"] == "present" and item["value"] == "同版末值"
    assert item["source"] == {"eventId": "event", "revision": 14, "eventOrder": 3}
    assert result["canonRevision"] == 14 and result["expectedRevisionHash"] == row["current_revision_hash"]
    assert "不可验证的新名称" not in json.dumps(result, ensure_ascii=False)
    assert saved.reads == 2 and len(history.calls) == 2
    projection_events = [{"id": str(index), "revision_number": item["revision_number"],
                         "event_order": index + 1, "entity_id": item["entity_id"], "field_path": item["field_path"],
                         "fact_kind": item["fact_kind"], "value": json.loads(item["payload_json"]),
                         "confirmation_status": item["confirmation_status"], "evidence": {}}
                        for index, item in enumerate(events) if item["revision_number"] <= 14]
    assert build_projection_bundle(14, projection_events).current_state["hero"]["observation.Record"] == item["value"]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "", [], {}, False, 0, {"nested": [None, "", False, 0, {}, []]}])
async def test_present_values_keep_exact_json_types_and_empty_values(value):
    service, command, _, _ = reader(context(), [source(value)])
    result = await service.read(command)
    assert result["items"][0]["state"] == "present"
    assert result["items"][0]["value"] == value
    assert type(result["items"][0]["value"]) is type(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [0, 14])
async def test_no_state_and_only_claim_are_absent_after_valid_read(revision):
    service, command, _, _ = reader(context(revision), [source(kind="claim", revision=revision)])
    result = await service.read(command)
    assert result["items"] == [{"entityId": "hero", "fieldPath": "observation.Record", "state": "absent"}]


@pytest.mark.asyncio
async def test_deduplicates_saved_keys_and_skips_global_and_new_entities():
    row = context()
    event = row["payload_json"]["canonEvents"][0]
    replace_events(row, [event, {**event, "id": "duplicate"}, {**event, "id": "other", "entityId": "other"},
                        {**event, "id": "global", "entityId": None}, {**event, "id": "new-fact", "entityId": "new"}],
                   entities=[{"id": "new", "entityType": "person", "canonicalName": "新增人物"}])
    service, command, _, history = reader(row, [source("主人旧值"), source("他人旧值", entity="other")])
    result = await service.read(command)
    assert [item["state"] for item in result["items"]] == ["present", "present", "not_applicable", "not_applicable"]
    assert [item.get("value") for item in result["items"][:2]] == ["主人旧值", "他人旧值"]
    assert len([call for call in history.calls if call[0] == "history"]) == 2
    assert all(call[2] not in {None, "new"} for call in history.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("project_id", "another"), ("chapter_session_id", "another"),
    ("attempt_id", "another"), ("candidate_id", "another"), ("candidate_project_id", "another"),
    ("candidate_session_id", "another"), ("candidate_hash", HASH), ("content", "被修改正文"),
    ("expected_canon_revision", 15), ("current_revision", 2), ("current_revision_hash", HASH),
    ("basis_hash", HASH), ("context_manifest_hash", HASH), ("baseline_revision_id", None)])
async def test_invalid_saved_identity_cannot_read_history(field, value):
    row = context()
    service, command, saved, history = reader(row)
    saved.row[field] = value
    with pytest.raises(FinalizationConflict):
        await service.read(command)
    assert history.calls == []


@pytest.mark.asyncio
async def test_valid_hashes_with_inconsistent_manifest_or_provenance_are_rejected():
    for key, value in [("projectId", "another"), ("candidateId", "another"), ("expectedCanonRevision", 15)]:
        row = context()
        row["context_manifest_json"][key] = value
        row["context_manifest_hash"] = canonical_hash(row["context_manifest_json"])
        service, command, _, history = reader(row)
        with pytest.raises(FinalizationConflict):
            await service.read(command)
        assert not history.calls
    row = context()
    row["provenance_json"]["projectionRevision"] = 15
    row["basis_hash"] = canonical_hash(row["provenance_json"])
    service, command, _, history = reader(row)
    with pytest.raises(FinalizationConflict):
        await service.read(command)
    assert not history.calls


@pytest.mark.asyncio
async def test_saved_revision_changing_during_read_discards_result():
    service, command, saved, history = reader(context(), [source()])
    original = history.state_history_reference
    async def mutate(*args):
        result = await original(*args)
        saved.row["current_revision"] = 2
        return result
    history.state_history_reference = mutate
    with pytest.raises(FinalizationConflict):
        await service.read(command)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [source(kind="unknown"), source(order=0), source(revision=15)])
async def test_invalid_source_is_unavailable_instead_of_absent(bad):
    service, command, _, history = reader(context())
    async def invalid(*args):
        return [bad]
    history.state_history_reference = invalid
    result = await service.read(command)
    assert result["items"][0]["state"] == "unavailable" and "value" not in result["items"][0]


@pytest.mark.asyncio
async def test_missing_entity_or_duplicate_top_order_is_unavailable():
    service, command, _, history = reader(context(), [source(), source(identity="duplicate")])
    assert (await service.read(command))["items"][0]["state"] == "unavailable"
    history.missing_entities.add("hero")
    assert (await service.read(command))["items"][0]["state"] == "unavailable"


@pytest.mark.asyncio
async def test_corrupt_json_and_missing_payload_are_unavailable():
    for invalid in ["not-json", "NaN", '{"invalid": Infinity}']:
        row = source()
        row["payload_json"] = invalid
        service, command, _, _ = reader(context(), [row])
        assert (await service.read(command))["items"][0]["state"] == "unavailable"
    row = source()
    row.pop("payload_json")
    service, command, _, _ = reader(context(), [row])
    assert (await service.read(command))["items"][0]["state"] == "unavailable"


@pytest.mark.asyncio
async def test_corrupt_changeset_hash_never_reads_history():
    service, command, saved, history = reader(context())
    saved.row["payload_json"]["summary"] = "不同摘要"
    with pytest.raises(FinalizationConflict):
        await service.read(command)
    assert not history.calls
