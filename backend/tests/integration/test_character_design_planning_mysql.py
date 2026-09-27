"""Real disposable MySQL acceptance for future character plans, without Canon writes."""

import json

import pytest

from backend.repositories.planning import PlanningRepository
from backend.services.planning import (
    PlanningService, CreatePlanningDraft, SavePlanningDraft, ConfirmPlanningDraft,
    PlanningRequestInvalid, PlanningArchived,
)
from backend.tests.integration.test_continuity_read_models_mysql import (
    _seed_history, PERSON, OTHER, PROJECT_ID,
)
from backend.tests.integration.test_planning_aggregate_lifecycle import _editable
from backend.tests.support.disposable_mysql import transaction_factory_for

pytestmark = pytest.mark.mysql


def character_design_fixture():
    return {"entityId": PERSON, "displayName": "沈砚的未来设计", "nodes": [
        {"id": "trust-turn", "title": "主动信任同伴", "stage": "从独查转向合作",
         "goal": "找回妹妹", "belief": "信任须由行动建立", "relationship": "与林舟建立合作",
         "ability": "辨别线索", "expectedChapter": 4},
        {"id": "choice-turn", "title": "承担选择后果", "stage": "独立决定",
         "goal": "保护同伴", "belief": "不把代价推给他人", "relationship": "形成稳定同盟",
         "ability": "组织行动", "expectedChapter": 5},
    ]}


async def seed_character_design_fixture(database):
    """Reusable browser fixture: confirmed chapters/arcs; future plan is not yet edited."""
    reader, _, _ = await _seed_history(database)
    # The old atomic-commit seed used prose here; this fixture exercises the
    # current Planning service and therefore supplies its required capacity shape.
    await database.session.execute(
        "UPDATE creation_contracts SET chapter_capacity_policy=%s WHERE project_id=%s",
        (json.dumps({"chapterWordRangePreference": [1000, 3000]}), PROJECT_ID),
    )
    transaction = transaction_factory_for(database.connection_config)
    return PlanningService(PlanningRepository(), transaction_factory=transaction), reader


async def authoritative_snapshot(database):
    session = database.session
    return {
        "head": await session.fetchone("SELECT * FROM projection_heads WHERE project_id=%s", (PROJECT_ID,)),
        "arcs": await session.fetchall("SELECT * FROM arc_projections WHERE project_id=%s ORDER BY id", (PROJECT_ID,)),
        "originalPlanning": await session.fetchone(
            "SELECT content_json,content_hash FROM planning_revisions WHERE project_id=%s AND revision=1", (PROJECT_ID,)),
        "canon": await session.fetchall("SELECT * FROM canon_events WHERE project_id=%s ORDER BY id", (PROJECT_ID,)),
    }


@pytest.mark.asyncio
async def test_character_design_create_save_confirm_read_preserves_actual_history(disposable_mysql):
    service, reader = await seed_character_design_fixture(disposable_mysql)
    before = await authoritative_snapshot(disposable_mysql)
    draft = await service.create_draft(CreatePlanningDraft(PROJECT_ID, "character-create"))
    payload = _editable(draft.content)
    payload["plots"][0]["characterDesign"] = character_design_fixture()
    # Same-name display text without an explicit reference must never associate.
    payload["plots"].append({"clientNodeKey": "unlinked-person", "order": 99,
        "title": "同名未关联设计", "plotType": "character", "storyQuestion": "能否成长？",
        "futureDirection": "独立", "expectedPayoff": "作出决定", "relatedCharacters": ["林舟"],
        "characterDesign": {**character_design_fixture(), "entityId": None, "displayName": "林舟"}})
    saved = await service.save_draft(SavePlanningDraft(PROJECT_ID, draft.draft_id,
        draft.draft_revision, draft.content_hash, payload, "character-save"))
    # A draft must not leak into the confirmed read model.
    assert (await reader.future_design(PROJECT_ID, entity_id=PERSON))["linkedPlots"] == []
    confirmed = await service.confirm_draft(ConfirmPlanningDraft(PROJECT_ID, saved.draft_id,
        saved.draft_revision, saved.content_hash, "character-confirm"))
    assert confirmed.content.plots[0].character_design.model_dump(mode="json", by_alias=True) == character_design_fixture()
    linked = await reader.future_design(PROJECT_ID, entity_id=PERSON)
    assert len(linked["linkedPlots"]) == 1
    assert linked["linkedPlots"][0]["characterDesign"] == character_design_fixture()
    assert (await reader.future_design(PROJECT_ID, entity_id=OTHER))["linkedPlots"] == []
    assert (await reader.future_design(PROJECT_ID))["linkedPlots"] == []
    assert await authoritative_snapshot(disposable_mysql) == before


@pytest.mark.asyncio
async def test_character_design_rejects_cross_project_nonperson_and_archive(disposable_mysql):
    service, _ = await seed_character_design_fixture(disposable_mysql)
    session = disposable_mysql.session
    foreign_project = "74000000-0000-4000-8000-000000000001"
    foreign_person = "74000000-0000-4000-8000-000000000002"
    item = "74000000-0000-4000-8000-000000000003"
    await session.execute("""INSERT INTO projects
        (id,title,genre,description,target_words,target_chapters,status,current_chapter,created_at,updated_at)
        VALUES (%s,'foreign fixture','fantasy','test',100000,100,'drafting',0,1,1)""", (foreign_project,))
    for entity, project, kind in ((foreign_person, foreign_project, "person"), (item, PROJECT_ID, "item")):
        await session.execute("""INSERT INTO canon_entities
            (id,project_id,entity_type,canonical_name,normalized_name,created_revision,created_at)
            VALUES (%s,%s,%s,'沈砚','沈砚',1,1)""", (entity, project, kind))
    draft = await service.create_draft(CreatePlanningDraft(PROJECT_ID, "invalid-create"))
    for entity in (foreign_person, item):
        payload = _editable(draft.content)
        payload["plots"][0]["characterDesign"] = {**character_design_fixture(), "entityId": entity}
        with pytest.raises(PlanningRequestInvalid, match="Canon person"):
            await service.save_draft(SavePlanningDraft(PROJECT_ID, draft.draft_id,
                draft.draft_revision, draft.content_hash, payload, "invalid-save"))
    row = await session.fetchone("SELECT content_hash,draft_revision FROM planning_drafts WHERE id=%s", (draft.draft_id,))
    assert row == {"content_hash": draft.content_hash, "draft_revision": draft.draft_revision}
    await session.execute("UPDATE projects SET archived_at=1 WHERE id=%s", (PROJECT_ID,))
    with pytest.raises(PlanningArchived):
        await service.save_draft(SavePlanningDraft(PROJECT_ID, draft.draft_id,
            draft.draft_revision, draft.content_hash, _editable(draft.content), "archived-save"))
