from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import (
    DraftPlanningAggregate, PlanningAggregate, PlanningDomainError,
    normalize_planning_aggregate, validate_confirmable_planning,
)
from backend.services.planning import (
    ConfirmPlanningDraft, CreatePlanningDraft, SavePlanningDraft,
    PlanningArchived, PlanningConflict, PlanningRequestInvalid,
)
from backend.repositories.planning import PlanningRepository
from backend.tests.unit.test_planning_service import Harness, editable_payload, planning_payload


def design():
    return {"entityId": None, "displayName": "未来人物", "nodes": [
        {"id": "turn-1", "title": "开始信任", "stage": "试探合作", "goal": "寻找同伴",
         "belief": "", "relationship": "盟友", "ability": "", "expectedChapter": 3},
    ]}


def normalize(payload, previous=None):
    ids = iter(f"node-{n}" for n in range(20))
    return normalize_planning_aggregate(DraftPlanningAggregate.model_validate(payload),
        previous_confirmed=None, previous_draft=previous, id_factory=ids.__next__)


def test_legacy_hash_and_round_trip_omit_optional_design():
    original = normalize(planning_payload())
    # Golden value independently computed with the pre-extension planning-v1 model.
    assert original.content_hash == "fd790f0e52f40cbec30f9099ef5bf6859a6ff7e71946fd76587c04b59ede708d"
    payload = original.model_dump(mode="json", by_alias=True)
    assert "characterDesign" not in payload["plots"][0]
    assert PlanningAggregate.model_validate(payload).model_dump(mode="json", by_alias=True) == payload
    assert canonical_hash({k: v for k, v in payload.items() if k != "contentHash"}) == original.content_hash
    draft = editable_payload(original, title=original.volumes[0].title)
    draft["plots"][0]["characterDesign"] = None
    assert normalize(draft, original) == original
    assert "character_design" not in original.model_dump()["plots"][0]


def test_design_round_trip_changes_only_plot_revision_and_hash():
    previous = normalize(planning_payload())
    payload = editable_payload(previous, title=previous.volumes[0].title)
    payload["plots"][0]["characterDesign"] = design()
    value = normalize(payload, previous)
    assert value.plots[0].revision == previous.plots[0].revision + 1
    assert value.content_hash != previous.content_hash
    assert value.volumes == previous.volumes and value.story_blocks == previous.story_blocks
    assert value.plots[0].model_dump(mode="json", by_alias=True)["characterDesign"] == design()
    assert normalize(editable_payload(value, title=value.volumes[0].title), value) == value
    validate_confirmable_planning(value)


@pytest.mark.parametrize("change", [
    {"entityId": " "}, {"displayName": " "}, {"nodes": [design()["nodes"][0]] * 2},
    {"nodes": [{**design()["nodes"][0], "expectedChapter": True}]},
    {"nodes": [{**design()["nodes"][0], "expectedChapter": 0}]},
    {"nodes": [{**design()["nodes"][0], "title": " "}]},
    {"nodes": [{**design()["nodes"][0], "id": str(i)} for i in range(51)]},
    {"unexpected": "forbidden"},
])
def test_invalid_design_rejected(change):
    payload = planning_payload()
    payload["plots"][0]["characterDesign"] = {**design(), **change}
    with pytest.raises(ValidationError):
        normalize(payload)


@pytest.mark.parametrize("nodes", [[], [{"id": "n", "title": "待补充"}]])
def test_incomplete_design_saves_but_cannot_confirm(nodes):
    payload = planning_payload()
    payload["plots"][0]["characterDesign"] = {**design(), "nodes": nodes}
    value = normalize(payload)
    with pytest.raises(PlanningDomainError, match="character"):
        validate_confirmable_planning(value)


@pytest.mark.asyncio
async def test_reference_save_confirm_revalidation_cas_and_archive():
    harness = Harness()
    harness.repository.read_character_entity = AsyncMock(return_value={"id": "person-1"})
    harness.repository.projections["p1"].update(canon_revision_number=1, projection_revision_number=1)
    draft = await harness.service.create_draft(CreatePlanningDraft("p1", "create"))
    payload = planning_payload()
    payload["plots"][0]["characterDesign"] = {**design(), "entityId": "person-1"}
    command = SavePlanningDraft("p1", draft.draft_id, draft.draft_revision, draft.content_hash, payload, "save")
    saved = await harness.service.save_draft(command)
    assert harness.repository.read_character_entity.await_args.args[1:] == ("p1", "person-1", 1)
    before = deepcopy(harness.repository.drafts)
    with pytest.raises(PlanningConflict):
        await harness.service.save_draft(command)
    assert harness.repository.drafts == before
    harness.repository.read_character_entity = AsyncMock(return_value=None)
    with pytest.raises(PlanningRequestInvalid, match="Canon person"):
        await harness.service.confirm_draft(ConfirmPlanningDraft("p1", saved.draft_id,
            saved.draft_revision, saved.content_hash, "confirm"))
    harness.repository.projects["p1"]["archived_at"] = 123
    with pytest.raises(PlanningArchived):
        await harness.service.save_draft(command)


@pytest.mark.asyncio
async def test_invalid_reference_save_does_not_write():
    harness = Harness()
    harness.repository.read_character_entity = AsyncMock(return_value=None)
    draft = await harness.service.create_draft(CreatePlanningDraft("p1", "create"))
    payload = planning_payload()
    payload["plots"][0]["characterDesign"] = {**design(), "entityId": "other-project-or-item"}
    before = deepcopy(harness.repository.drafts)
    with pytest.raises(PlanningRequestInvalid, match="Canon person"):
        await harness.service.save_draft(SavePlanningDraft("p1", draft.draft_id,
            draft.draft_revision, draft.content_hash, payload, "save"))
    assert harness.repository.drafts == before


@pytest.mark.asyncio
async def test_repository_reference_is_scoped_to_project_person_and_revision():
    session = AsyncMock()
    await PlanningRepository().read_character_entity(session, "p1", "person-1", 7)
    sql, values = session.fetchone.await_args.args
    assert "project_id=%s" in sql and "id=%s" in sql
    assert "entity_type='person'" in sql and "created_revision<=%s" in sql
    assert values == ("p1", "person-1", 7)
