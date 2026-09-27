"""Real ZIP -> publication -> MySQL -> ZIP character-plan compatibility."""

import json
from hashlib import sha256

import pytest

from backend.domain.finalization import FinalizationChangeSet
from backend.domain.planning import PlanningAggregate, planning_content_hash
from backend.domain.project_packages import thaw_json_value
from backend.repositories.planning import PlanningRepository
from backend.services.planning import PlanningService, CreatePlanningDraft, SavePlanningDraft, ConfirmPlanningDraft
from backend.tests.integration.test_character_design_planning_mysql import character_design_fixture
from backend.tests.integration.test_continuity_issue_packages_mysql import (
    PROJECT_ID, _seed_finalized_project, _packages, _publish, _lifecycle, finalized_fixture,
)
from backend.tests.integration.test_planning_aggregate_lifecycle import _editable


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]
PERSON = "75000000-0000-4000-8000-000000000001"


class _CharacterExtraction:
    async def extract(self, *, manifest, **kwargs):
        payload = {
            "schemaVersion": "finalization-changeset-v1", "title": f"第{manifest.chapter_number}章",
            "summary": "人物作出选择。", "existingEntityIds": [], "entities": [], "aliases": [],
            "canonEvents": [], "storyProgressEvents": [], "planningPatches": [], "planningSuggestions": [],
        }
        if manifest.chapter_number == 1:
            prose = finalized_fixture.FINAL_ONE
            payload["entities"] = [{"id": PERSON, "entityType": "person", "canonicalName": "沈砚"}]
            payload["canonEvents"] = [{
                "id": "75000000-0000-4000-8000-000000000002", "entityId": PERSON,
                "factKind": "dynamic_event", "fieldPath": "arc.belief", "value": "决定信任同伴",
                "evidence": {"startScalar": 0, "endScalar": len(prose),
                    "excerptHash": sha256(prose.encode()).hexdigest(), "confidence": 1.0,
                    "rationale": "正文直接表达信任选择"},
                "effectiveStartChapter": 1, "effectiveEndChapter": None,
                "assertionOperator": "equals", "valueCardinality": "single",
            }]
        return FinalizationChangeSet.model_validate(payload)


def _designs(package):
    return [(record.entity_type, record.data["payload"]["plots"])
        for record in package.graph_index.values()
        if record.entity_type in {"planning-revision", "planning-draft"}]


def _design_meanings(package):
    # Package logical ordering can change after UUID remapping; node hashes must
    # change as well. Compare author meaning while resolving the person explicitly.
    values = []
    for kind, plots in _designs(package):
        for plot in plots:
            if plot.get("characterDesign") is None:
                continue
            design = thaw_json_value(plot["characterDesign"])
            reference = design.pop("entityId")
            if reference is not None:
                person = package.graph_index[("canon-entity", reference)]
                assert person.data["entityType"] == "person"
                design["personName"] = person.data["canonicalName"]
            else:
                design["personName"] = None
            values.append(json.dumps([kind, plot["title"], design], sort_keys=True, ensure_ascii=False))
    return sorted(values)


async def test_character_plan_zip_publication_mysql_and_reexport(disposable_mysql, monkeypatch, tmp_path):
    monkeypatch.setattr(finalized_fixture, "FINAL_ONE", "沈砚决定信任同伴。")
    monkeypatch.setattr(finalized_fixture, "_Extraction", _CharacterExtraction)
    transaction = await _seed_finalized_project(disposable_mysql, monkeypatch)
    planning = PlanningService(PlanningRepository(), transaction_factory=transaction)
    draft = await planning.create_draft(CreatePlanningDraft(PROJECT_ID, "package-character-create"))
    payload = _editable(draft.content)
    design = {**character_design_fixture(), "entityId": PERSON}
    payload["plots"][0]["characterDesign"] = design
    payload["plots"].append({"clientNodeKey": "unlinked-character", "order": 99,
        "title": "未来人物尚未登场", "plotType": "character", "storyQuestion": "能否独立？",
        "futureDirection": "独立", "expectedPayoff": "自行决定", "relatedCharacters": ["沈砚"],
        "characterDesign": {**design, "entityId": None}})
    saved = await planning.save_draft(SavePlanningDraft(PROJECT_ID, draft.draft_id,
        draft.draft_revision, draft.content_hash, payload, "package-character-save"))
    confirmed = await planning.confirm_draft(ConfirmPlanningDraft(PROJECT_ID, saved.draft_id,
        saved.draft_revision, saved.content_hash, "package-character-confirm"))
    # Keep an editable new draft in the source package as well as confirmed data.
    pending = await planning.create_draft(CreatePlanningDraft(PROJECT_ID, "package-character-pending"))
    pending_payload = _editable(pending.content)
    pending_payload["plots"][1]["characterDesign"]["nodes"][0]["title"] = "尚未确认的独立选择"
    await planning.save_draft(SavePlanningDraft(PROJECT_ID, pending.draft_id,
        pending.draft_revision, pending.content_hash, pending_payload, "package-character-pending-save"))

    lifecycle = _lifecycle(transaction)
    source = await lifecycle.get(PROJECT_ID)
    async with _packages(disposable_mysql, tmp_path) as export:
        first = await export(PROJECT_ID, source.lifecycle_revision)
        assert any(kind == "planning-draft" and any(plot.get("characterDesign") for plot in plots)
                   for kind, plots in _designs(first))
        plan = await _publish(first, transaction)
        target = await lifecycle.get(plan.target_project_id)
        async with transaction() as session:
            person = await session.fetchone("SELECT id,entity_type FROM canon_entities WHERE project_id=%s", (target.id,))
            assert person["id"] != PERSON and person["entity_type"] == "person"
            row = await session.fetchone("SELECT content_json,content_hash FROM planning_revisions WHERE project_id=%s ORDER BY revision DESC LIMIT 1", (target.id,))
            restored = PlanningAggregate.model_validate_json(row["content_json"])
            assert restored.plots[0].character_design.entity_id == person["id"]
            assert restored.plots[1].character_design.entity_id is None
            assert restored.plots[0].character_design.nodes == confirmed.content.plots[0].character_design.nodes
            assert row["content_hash"] != confirmed.content_hash
            assert row["content_hash"] == planning_content_hash(restored.model_dump(mode="json", by_alias=True, exclude={"content_hash"}))
            arcs = await session.fetchall("SELECT entity_id,arc_key,payload_json FROM arc_projections WHERE project_id=%s AND revision_number=(SELECT projection_revision_number FROM projection_heads WHERE project_id=%s)", (target.id, target.id))
            assert len(arcs) == 1 and arcs[0]["entity_id"] == person["id"]
            assert arcs[0]["arc_key"] == "arc.belief"
            assert json.loads(arcs[0]["payload_json"]) == "决定信任同伴"
            assert await session.fetchone("SELECT id FROM canon_entities WHERE id=%s AND project_id=%s", (PERSON, PROJECT_ID))
        second = await export(target.id, target.lifecycle_revision)
        assert _design_meanings(second) == _design_meanings(first)
