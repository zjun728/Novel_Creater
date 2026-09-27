"""Non-empty author read models over real, deterministically reduced MySQL Canon.

The chapter fixture reuses the existing finalized-chapter FK graph. It does not
represent a provider or browser acceptance test, and never writes projections.
"""

from dataclasses import replace
from hashlib import sha256

import pytest

from backend.domain.canon import (
    AssertionOperator, CanonEventInput, ConfirmationStatus, FactKind,
    ValueCardinality,
)
from backend.domain.finalization import change_set_hash
from backend.repositories.canon import CanonRepository
from backend.repositories.continuity import ContinuityRepository
from backend.repositories.finalization import FinalizationRepository
from backend.services.canon import CanonEntityCreate, CanonEventCreate, CanonService
from backend.services.continuity import ContinuityReadError, ContinuityReader
from backend.services.finalization_commit import CommitFinalization
from backend.tests.integration.test_atomic_finalization_mysql import (
    HASH_B, PROJECT_ID, SESSION_ID, _seed, _service,
)
from backend.tests.integration.test_canon_atomic_commit import commit_request
from backend.tests.integration.test_novel_download_repository_mysql import (
    _insert_additional_final_chapter,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


PERSON = "71000000-0000-4000-8000-000000000001"
OTHER = "71000000-0000-4000-8000-000000000002"
CHAPTER_TWO = "沈砚决定寻找失踪的妹妹。林舟仍守在城门。铜铃被埋在桥下。"
CHAPTER_THREE = "沈砚开始独自追查。林舟谎称沈砚已经放弃。铜铃已交还失主。"


def _event(number, entity, field, value, *, chapter, claim=False):
    content = CHAPTER_TWO if chapter == 2 else CHAPTER_THREE
    return CanonEventCreate(
        f"72000000-0000-4000-8000-{number:012d}",
        CanonEventInput(
            entity_id=entity,
            fact_kind=FactKind.CLAIM if claim else FactKind.DYNAMIC_EVENT,
            field_path=field,
            value=value,
            evidence={"startScalar": 0, "endScalar": len(content),
                      "excerptHash": sha256(content.encode("utf-8")).hexdigest()},
            effective_start_chapter=chapter,
            effective_end_chapter=None,
            confirmation_status=ConfirmationStatus.CONFIRMED,
            assertion_operator=AssertionOperator.EQUALS,
            value_cardinality=ValueCardinality.SINGLE,
        ),
    )


async def _seed_history(database):
    factory = transaction_factory_for(database.connection_config)
    async with factory() as session:
        _, change_set = await _seed(session, factory)
    await _service(factory, FinalizationRepository(), (
        "73000000-0000-4000-8000-000000000001",
        "73000000-0000-4000-8000-000000000002",
        "73000000-0000-4000-8000-000000000003",
    )).commit(CommitFinalization(
        project_id=PROJECT_ID, chapter_session_id=SESSION_ID,
        idempotency_key=HASH_B, expected_revision=1,
        expected_revision_hash=change_set_hash(change_set),
    ))
    service = CanonService(CanonRepository(), transaction_factory=factory)
    first = (
        _event(1, PERSON, "arc.goal", "寻找妹妹", chapter=2),
        _event(2, OTHER, "arc.goal", "守住城门", chapter=2),
        _event(3, PERSON, "state.location", "桥头", chapter=2),
        _event(4, None, "plot.mystery.bell", "planted", chapter=2),
        _event(5, PERSON, "plot.mystery.bell", "知道藏处", chapter=2),
    )
    second = (
        _event(6, PERSON, "arc.goal", "独自追查", chapter=3),
        _event(7, PERSON, "arc.goal", "已经放弃", chapter=3, claim=True),
        _event(8, PERSON, "state.location", "城内", chapter=3),
        _event(9, None, "plot.mystery.bell", "resolved", chapter=3),
    )
    for revision, content, events in (
        (2, CHAPTER_TWO, first), (3, CHAPTER_THREE, second),
    ):
        request = replace(
            commit_request(key=str(revision) * 64, expected_head=revision - 1,
                           events=events),
            project_id=PROJECT_ID,
            entities=(CanonEntityCreate(PERSON, "person", "沈砚"),
                      CanonEntityCreate(OTHER, "person", "林舟")) if revision == 2 else (),
            aliases=(),
        )
        result = await service.commit(request)
        assert result.revision_number == revision
        async with factory() as session:
            await _insert_additional_final_chapter(
                session, chapter_number=revision, suffix=str(revision),
                content=content, persisted_hash=sha256(content.encode("utf-8")).hexdigest(),
            )
            # The download fixture copies chapter 1's revision. Bind this
            # fixture chapter to the real Canon commit just created instead.
            await session.execute(
                "UPDATE final_chapters SET canon_revision=%s WHERE project_id=%s AND chapter_num=%s",
                (revision, PROJECT_ID, revision),
            )
    return ContinuityReader(ContinuityRepository(), factory), first, second


@pytest.mark.mysql
async def test_nonempty_projection_sources_and_claims_match_canon(disposable_mysql):
    reader, first, second = await _seed_history(disposable_mysql)
    arcs = await reader.records(PROJECT_ID, kind="arcs", entity_id=PERSON)
    assert arcs["revision"] == 3
    assert len(arcs["items"]) == 1
    arc = arcs["items"][0]
    assert (arc["field"], arc["value"], arc["sourceEventId"],
            arc["formedChapter"], arc["sourceChapter"], arc["isClaim"]) == (
        "arc.goal", "独自追查", second[0].id, 2, 3, False,
    )
    other = await reader.records(PROJECT_ID, kind="arcs", entity_id=OTHER)
    assert [(item["value"], item["formedChapter"], item["sourceChapter"])
            for item in other["items"]] == [("守住城门", 2, 2)]
    state = await reader.records(PROJECT_ID, kind="state", entity_id=PERSON)
    location = next(item for item in state["items"] if item["field"] == "state.location")
    assert (location["value"], location["formedChapter"], location["sourceChapter"]) == ("城内", 2, 3)
    clues = await reader.records(PROJECT_ID, kind="clues")
    assert {(item["entityId"], item["value"], item["formedChapter"], item["sourceChapter"])
            for item in clues["items"]} == {(None, "resolved", 2, 3), (PERSON, "知道藏处", 2, 2)}
    memory = await reader.records(PROJECT_ID, kind="memory", entity_id=PERSON)
    expected = {event.id for event in (*first, *second) if event.event.entity_id == PERSON}
    assert {item["sourceEventId"] for item in memory["items"]} == expected
    assert [item["sourceEventId"] for item in memory["items"] if item["isClaim"]] == [second[1].id]
    for event, content, chapter in ((first[0], CHAPTER_TWO, 2), (second[0], CHAPTER_THREE, 3)):
        evidence = await reader.evidence(PROJECT_ID, event.id)
        assert evidence == {"projectId": PROJECT_ID, "eventId": event.id,
                            "chapterNumber": chapter, "excerpt": content, "verified": True}


@pytest.mark.mysql
async def test_history_paginates_exact_field_and_entity_at_current_revision(disposable_mysql):
    reader, first, second = await _seed_history(disposable_mysql)
    items = []
    offset = 0
    while offset is not None:
        page = await reader.records(PROJECT_ID, kind="facts", entity_id=PERSON,
                                    field_path="arc.goal", limit=1, offset=offset, revision=3)
        assert page["revision"] == 3
        items.extend(page["items"])
        offset = page["nextOffset"]
    assert [item["sourceEventId"] for item in items] == [second[1].id, second[0].id, first[0].id]
    assert [item["isClaim"] for item in items] == [True, False, False]
    assert [item["formedChapter"] for item in items] == [3, 3, 2]
    global_history = await reader.records(PROJECT_ID, kind="facts", global_only=True,
                                          field_path="plot.mystery.bell", revision=3)
    assert [item["sourceEventId"] for item in global_history["items"]] == [second[3].id, first[3].id]
    assert all(item["entityId"] is None for item in global_history["items"])
    wrong_case = await reader.records(PROJECT_ID, kind="facts", entity_id=PERSON,
                                     field_path="arc.GOAL", revision=3)
    assert wrong_case["items"] == []
    with pytest.raises(ContinuityReadError, match="snapshot_changed"):
        await reader.records(PROJECT_ID, kind="facts", entity_id=PERSON,
                             field_path="arc.goal", revision=2)
