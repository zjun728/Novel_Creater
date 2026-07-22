from __future__ import annotations

from copy import deepcopy
import json
import traceback
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import BindingItem, BindingRevision
from backend.domain.seeds import (
    SeedPayload,
    build_seed_provenance,
    seed_revision_document,
)
from backend.http_errors import ProjectArchived
from backend.services.contracts import (
    ConfirmContracts,
    ContractConflict,
    ContractDraftIncomplete,
    ContractDraftInput,
    ContractHistoryPage,
    ContractNotFound,
    ContractPreconditionFailed,
    ContractService,
    SaveContractDraft,
)
from backend.tests.support.contract_fakes import (
    SEED_PAYLOAD,
    ContractHarness,
    draft_values,
)


def command(harness, expected=0, **overrides):
    return SaveContractDraft(
        project_id="p1",
        expected_draft_version=expected,
        draft=ContractDraftInput(**draft_values(harness.repository, **overrides)),
    )


def add_seed_provenance(harness):
    provenance = build_seed_provenance(
        kind="manual",
        snapshots=(),
        analysis=None,
        inspiration_attempt=None,
        public_notes=("作者手动保存。",),
    )
    payload_json = canonical_json(
        seed_revision_document(SeedPayload(**SEED_PAYLOAD), provenance)
    )
    harness.repository.selected_seeds["p1"]["payload_json"] = payload_json
    harness.repository.seed_revisions["seed-revision-1"][
        "payload_json"
    ] = payload_json


def test_seed_reference_is_server_managed_and_client_input_forbids_forgery():
    harness = ContractHarness()
    values = draft_values(harness.repository)

    draft = ContractDraftInput(**values)

    assert "seedRevisionId" not in draft.model_dump()
    assert "seedHash" not in draft.model_dump()
    with pytest.raises(ValidationError):
        ContractDraftInput(**{
            **values,
            "seedRevisionId": "forged-revision",
            "seedHash": "f" * 64,
        })


@pytest.mark.parametrize(
    ("stage", "overrides", "complete"),
    (
        ("engine", {
            "primaryStyleRef": None, "secondaryStyleRef": None,
            "likes": None, "dislikes": None,
            "experienceCardRefs": None, "corpusSourceRefs": None,
        }, False),
        ("style", {
            "experienceCardRefs": None, "corpusSourceRefs": None,
        }, False),
        ("assets", {}, True),
    ),
)
def test_contract_draft_v2_accepts_each_progressive_stage(stage, overrides, complete):
    harness = ContractHarness()
    draft = ContractDraftInput(**draft_values(
        harness.repository, draftStage=stage, **overrides
    ))

    assert draft.schemaVersion == "contract-draft-v2"
    assert draft.draftStage == stage
    assert draft.is_complete is complete


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("targetTotalWords", 100_000_001),
        ("expectedVolumeCount", 1_001),
        ("expectedChapterCount", 100_001),
        ("chapterWordRangePreference", (100_001, 100_001)),
        ("chapterWordRangePreference", (1, 100_001)),
        ("targetTotalWords", 10**5_000),
    ),
    ids=(
        "target-total", "volume-count", "chapter-count",
        "chapter-range-low", "chapter-range-high", "extreme-target-total",
    ),
)
def test_invalid_capacity_cannot_construct_direct_save_command_or_enter_transaction(
    field_name, value,
):
    harness = ContractHarness()

    with pytest.raises(ValidationError):
        SaveContractDraft(
            project_id="p1",
            expected_draft_version=0,
            draft=ContractDraftInput(**draft_values(
                harness.repository, **{field_name: value}
            )),
        )

    assert harness.transaction_enter_count == 0
    assert harness.repository.write_count == 0


@pytest.mark.parametrize(
    ("stage", "overrides"),
    (
        ("engine", {"primaryStyleRef": {"id": "style-primary", "revision": 2,
                                        "contentHash": "a" * 64}}),
        ("engine", {"likes": ()}),
        ("style", {"primaryStyleRef": None}),
        ("style", {"experienceCardRefs": ()}),
        ("assets", {"likes": None}),
        ("assets", {"experienceCardRefs": None}),
    ),
)
def test_contract_draft_v2_rejects_fields_from_the_wrong_stage(stage, overrides):
    harness = ContractHarness()
    base = draft_values(harness.repository, draftStage=stage)
    if stage == "engine":
        base.update({
            "primaryStyleRef": None, "secondaryStyleRef": None,
            "likes": None, "dislikes": None,
            "experienceCardRefs": None, "corpusSourceRefs": None,
        })
    elif stage == "style":
        base.update({"experienceCardRefs": None, "corpusSourceRefs": None})
    base.update(overrides)

    with pytest.raises(ValidationError):
        ContractDraftInput(**base)


_UNSAFE_PATHS = (
    r"C:\private\novel.txt",
    "/home/author/novel.txt",
    r"\\server\share\novel.txt",
    r"C:private\novel.txt",
    "safe/../private/novel.txt",
)


@pytest.mark.parametrize(
    "field_name",
    (
        "channelProfileKey",
        "genreProfileKey",
        "qualityCharterVersion",
        "authorNotes",
        "prohibitedDirections",
        "likes",
        "dislikes",
    ),
)
@pytest.mark.parametrize("unsafe_path", _UNSAFE_PATHS)
def test_every_client_text_field_rejects_path_forms(field_name, unsafe_path):
    harness = ContractHarness()
    values = draft_values(harness.repository)
    values[field_name] = (
        (unsafe_path,)
        if field_name in {"likes", "dislikes", "prohibitedDirections"}
        else unsafe_path
    )

    with pytest.raises(ValidationError):
        ContractDraftInput(**values)


@pytest.mark.parametrize("ref_kind", ("engine", "primary", "card", "corpus"))
@pytest.mark.parametrize("unsafe_path", _UNSAFE_PATHS)
def test_every_client_identifier_rejects_path_forms(ref_kind, unsafe_path):
    harness = ContractHarness()
    values = draft_values(harness.repository)
    if ref_kind == "engine":
        values["engineOptionId"] = unsafe_path
    elif ref_kind == "primary":
        values["primaryStyleRef"] = {
            **values["primaryStyleRef"], "id": unsafe_path,
        }
    elif ref_kind == "card":
        values["experienceCardRefs"] = ({
            **values["experienceCardRefs"][0], "id": unsafe_path,
        },)
    else:
        values["corpusSourceRefs"] = ({
            **values["corpusSourceRefs"][0], "id": unsafe_path,
        },)

    with pytest.raises(ValidationError):
        ContractDraftInput(**values)


def test_safe_text_validation_does_not_reject_normal_chinese_colons():
    harness = ContractHarness()
    values = draft_values(harness.repository)
    values["channelProfileKey"] = "渠道：中文连载"
    values["authorNotes"] = "节奏：每章推进一个不可逆选择"

    draft = ContractDraftInput(**values)

    assert draft.channelProfileKey == "渠道：中文连载"
    assert draft.authorNotes.startswith("节奏：")


@pytest.mark.parametrize(
    "field_name",
    ("channelProfileKey", "genreProfileKey", "qualityCharterVersion"),
)
def test_relational_profile_and_version_keys_share_the_120_character_limit(field_name):
    harness = ContractHarness()
    values = draft_values(harness.repository)
    values[field_name] = "x" * 121

    with pytest.raises(ValidationError):
        ContractDraftInput(**values)


@pytest.mark.asyncio
async def test_corrupt_stored_path_is_not_echoed_through_exception_traceback():
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))
    sentinel = r"C:\private\novel-sentinel.txt"
    row = harness.repository.drafts["p1"]
    raw = json.loads(row["draft_json"])
    raw["channelProfileKey"] = sentinel
    row["draft_json"] = canonical_json(raw)
    row["content_hash"] = canonical_hash(raw)

    with pytest.raises(ContractPreconditionFailed) as captured:
        await harness.service.get_draft("p1")

    rendered = "".join(traceback.format_exception(captured.value))
    assert sentinel not in rendered


@pytest.mark.asyncio
async def test_create_reload_update_uses_one_draft_and_version_cas_from_head_zero():
    harness = ContractHarness()

    created = await harness.service.save_draft(command(harness))
    reloaded = await harness.service.get_draft("p1")
    updated = await harness.service.save_draft(
        command(harness, expected=1, likes=("克制", "选择有代价"))
    )

    assert created.draft_version == 1
    assert created.selection_revision == 7
    assert created.base_head_revision == 0
    assert created.draft.seedRevisionId == "seed-revision-1"
    assert created.draft.seedHash == harness.repository.selected_seeds["p1"]["seed_hash"]
    assert "lock-selected-seed" in harness.repository.events
    assert created.draft.modelBindingRef.id == "binding-revision-3"
    assert created.draft.modelBindingRef.revision == 3
    assert created.draft.modelBindingRef.contentHash == harness.repository.binding["content_hash"]
    assert reloaded == created
    assert updated.draft_version == 2
    assert updated.base_head_revision == 0
    assert updated.draft.likes == ("克制", "选择有代价")
    assert len(harness.repository.drafts) == 1
    assert harness.repository.drafts["p1"]["seed_revision_id"] == "seed-revision-1"
    assert harness.repository.drafts["p1"]["engine_option_id"] == "engine-1"
    assert harness.repository.drafts["p1"]["content_hash"] == canonical_hash(updated.draft)


@pytest.mark.asyncio
async def test_save_accepts_not_ready_binding_and_can_return_to_engine_stage():
    harness = ContractHarness()
    harness.repository.binding["items"][0]["provider_ready"] = 0

    created = await harness.service.save_draft(command(harness))
    returned = await harness.service.save_draft(command(
        harness,
        expected=1,
        draftStage="engine",
        primaryStyleRef=None,
        secondaryStyleRef=None,
        likes=None,
        dislikes=None,
        experienceCardRefs=None,
        corpusSourceRefs=None,
    ))

    assert created.draft_version == 1
    assert returned.draft.draftStage == "engine"
    assert returned.draft.primaryStyleRef is None
    assert returned.draft.likes is None
    assert returned.draft.experienceCardRefs is None


@pytest.mark.asyncio
async def test_manual_contract_draft_does_not_require_a_binding_snapshot():
    harness = ContractHarness()
    harness.repository.binding_head = {
        "head_revision": 0,
        "head_binding_revision_id": None,
        "head_hash": None,
    }

    saved = await harness.service.save_draft(command(harness))

    assert saved.draft.modelBindingRef is None


@pytest.mark.asyncio
async def test_manual_confirmation_without_binding_is_atomic_and_replayable():
    harness = ContractHarness()
    harness.repository.binding_head = {
        "head_revision": 0,
        "head_binding_revision_id": None,
        "head_hash": None,
    }
    saved = await harness.service.save_draft(command(harness))

    first = await harness.service.confirm(confirmation(
        saved, key="manual-without-binding"
    ))
    replay = await harness.service.confirm(confirmation(
        saved, key="manual-without-binding"
    ))

    creation = next(iter(harness.repository.creation_contracts.values()))
    assert first == replay
    assert first.binding_ref is None
    assert first.creation_contract.modelBindingRef is None
    assert creation["binding_revision_id"] is None
    assert creation["binding_hash"] is None
    assert harness.repository.heads["p1"]["revision"] == 1
    assert "p1" not in harness.repository.drafts


def test_corpus_fragment_manifest_rejects_bad_ranges_duplicates_and_budget():
    harness = ContractHarness()
    values = draft_values(harness.repository)
    source = values["corpusSourceRefs"][0]
    fragment = source["fragments"][0]

    with pytest.raises(ValidationError):
        ContractDraftInput(**{
            **values,
            "corpusSourceRefs": ({
                **source,
                "fragments": ({
                    **fragment,
                    "chapterCharEnd": fragment["chapterCharStart"],
                },),
            },),
        })
    with pytest.raises(ValidationError):
        ContractDraftInput(**{
            **values,
            "corpusSourceRefs": ({
                **source, "fragments": (fragment, fragment),
            },),
        })
    with pytest.raises(ValidationError):
        ContractDraftInput(**{
            **values,
            "corpusSourceRefs": ({
                **source,
                "fragments": tuple(
                    {
                        **fragment,
                        "fragmentId": f"fragment-{index}",
                        "chapterCharStart": index * 300,
                        "chapterCharEnd": index * 300 + 300,
                    }
                    for index in range(1, 15)
                ),
            },),
        })


@pytest.mark.asyncio
async def test_same_corpus_fragment_can_freeze_two_distinct_ordered_ranges():
    harness = ContractHarness()
    values = draft_values(harness.repository)
    source = values["corpusSourceRefs"][0]
    first = source["fragments"][0]
    second = {
        **first,
        "chapterCharStart": 110,
        "chapterCharEnd": 200,
        "referenceUse": "structure",
    }
    values["corpusSourceRefs"] = ({
        **source,
        "fragments": (first, second),
    },)
    saved = await harness.service.save_draft(SaveContractDraft(
        project_id="p1",
        expected_draft_version=0,
        draft=ContractDraftInput(**values),
    ))

    preview = await harness.service.preview("p1")
    confirmed = await harness.service.confirm(confirmation(
        saved, key="same-fragment-two-ranges"
    ))

    assert preview.contract_ready is True
    assert tuple(
        (fragment.chapterCharStart, fragment.chapterCharEnd)
        for fragment in confirmed.corpus_source_refs[0].fragments
    ) == ((10, 110), (110, 200))
    assert tuple(
        (row["chapter_char_start"], row["chapter_char_end"])
        for row in harness.repository.corpus_fragment_refs
    ) == ((10, 110), (110, 200))
    manifest = json.loads(next(iter(
        harness.repository.creation_contracts.values()
    ))["reference_manifest_json"])
    assert [
        (fragment["chapterCharStart"], fragment["chapterCharEnd"])
        for fragment in manifest["corpusSourceRefs"][0]["fragments"]
    ] == [(10, 110), (110, 200)]


@pytest.mark.asyncio
async def test_preview_treats_missing_zero_head_as_stable_initial_base():
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))
    del harness.repository.heads["p1"]

    preview = await harness.service.preview("p1")

    assert "contract_head_missing" not in preview.reasons
    assert "draft_base_drift" not in preview.reasons


@pytest.mark.asyncio
async def test_preview_reports_binding_created_after_unbound_draft_as_drift():
    harness = ContractHarness()
    original_head = dict(harness.repository.binding_head)
    harness.repository.binding_head = {
        "head_revision": 0,
        "head_binding_revision_id": None,
        "head_hash": None,
    }
    await harness.service.save_draft(command(harness))
    harness.repository.binding_head = original_head

    preview = await harness.service.preview("p1")

    assert preview.binding_ref is None
    assert "binding_drift" in preview.reasons


@pytest.mark.asyncio
async def test_preview_aggregates_every_upstream_drift_without_mutating_draft():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    draft_before = dict(harness.repository.drafts["p1"])
    writes_before = harness.repository.write_count
    harness.repository.selected_seeds["p1"].update({
        "selection_revision": 8,
        "seed_hash": "0" * 64,
    })
    harness.repository.engines["engine-1"].update({
        "selection_revision": 8,
        "content_hash": "1" * 64,
    })
    harness.repository.styles["style-primary"]["head_hash"] = "2" * 64
    harness.repository.cards["card-1"]["head_hash"] = "3" * 64
    harness.repository.sources["source-1"]["head_hash"] = "4" * 64
    harness.repository.fragments["fragment-1"]["fragment_hash"] = "5" * 64
    harness.repository.binding_head["head_hash"] = "6" * 64
    harness.repository.heads["p1"] = {
        "project_id": "p1",
        "revision": 1,
        "creation_contract_id": "missing-creation",
        "style_contract_id": "missing-style",
        "creation_hash": "7" * 64,
        "style_hash": "8" * 64,
    }

    preview = await harness.service.preview("p1")

    assert {
        "selection_drift",
        "seed_drift",
        "engine_invalid",
        "engine_seed_drift",
        "style_drift:primary",
        "experience_drift:card-1",
        "corpus_drift:source-1",
        "corpus_fragment_invalid:fragment-1",
        "binding_drift",
        "draft_base_drift",
        "contract_head_drift",
    }.issubset(set(preview.reasons))
    assert harness.repository.drafts["p1"] == draft_before
    assert harness.repository.write_count == writes_before
    assert preview.draft_version == saved.draft_version


@pytest.mark.asyncio
async def test_preview_reports_seed_missing_selection_and_identity_drift_independently():
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))
    harness.repository.seed_revisions.clear()
    harness.repository.selected_seeds["p1"].update({
        "selection_revision": 8,
        "seed_id": "seed-2",
        "seed_revision_id": "seed-revision-2",
        "seed_hash": "0" * 64,
    })

    preview = await harness.service.preview("p1")

    assert preview.contract_ready is False
    assert preview.reasons == (
        "seed_missing",
        "selection_drift",
        "seed_drift",
    )


@pytest.mark.asyncio
async def test_explicit_readable_historical_corpus_pin_survives_archive_and_new_head():
    harness = ContractHarness()
    source = harness.repository.sources["source-1"]
    source["archived_at"] = 1_000_001
    source["head_id"] = "source-revision-6"
    source["head_revision"] = 6
    source["head_hash"] = "6" * 64
    values = draft_values(harness.repository)
    values["corpusSourceRefs"] = ({
        **values["corpusSourceRefs"][0],
        "pinnedHistoricalRevision": True,
    },)

    saved = await harness.service.save_draft(SaveContractDraft(
        project_id="p1",
        expected_draft_version=0,
        draft=ContractDraftInput(**values),
    ))
    preview = await harness.service.preview("p1")

    assert saved.draft.corpusSourceRefs[0].pinnedHistoricalRevision is True
    assert not any(reason.startswith("corpus_inactive") for reason in preview.reasons)
    assert not any(reason.startswith("corpus_drift") for reason in preview.reasons)


@pytest.mark.asyncio
async def test_preview_and_live_confirm_reject_incomplete_stage_before_dependency_locks():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(
        harness,
        draftStage="engine",
        primaryStyleRef=None,
        secondaryStyleRef=None,
        likes=None,
        dislikes=None,
        experienceCardRefs=None,
        corpusSourceRefs=None,
    ))
    harness.repository.events.clear()

    with pytest.raises(ContractDraftIncomplete):
        await harness.service.preview("p1")
    with pytest.raises(ContractDraftIncomplete):
        await harness.service.confirm(ConfirmContracts(
            project_id="p1",
            idempotency_key="incomplete-stage",
            expected_draft_version=saved.draft_version,
            expected_draft_hash=saved.content_hash,
        ))

    assert harness.repository.events == []


@pytest.mark.parametrize(
    ("column", "tampered"),
    (
        ("seed_revision_id", "seed-revision-tampered"),
        ("seed_hash", "f" * 64),
        ("engine_option_id", "engine-tampered"),
    ),
)
@pytest.mark.asyncio
async def test_reload_rejects_draft_json_and_index_column_mismatch(column, tampered):
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))
    harness.repository.drafts["p1"][column] = tampered

    with pytest.raises(ContractPreconditionFailed) as captured:
        await harness.service.get_draft("p1")

    assert captured.value.__cause__ is None


@pytest.mark.asyncio
async def test_draft_create_and_update_reject_wrong_versions_and_archived_or_missing():
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))

    with pytest.raises(ContractConflict):
        await harness.service.save_draft(command(harness, expected=0))
    with pytest.raises(ContractConflict):
        await harness.service.save_draft(command(harness, expected=9))
    harness.repository.binding["items"][0]["provider_ready"] = 0
    with pytest.raises(ContractConflict):
        await harness.service.save_draft(command(harness, expected=9))
    with pytest.raises(ContractNotFound):
        await harness.service.get_draft("missing")
    with pytest.raises(ContractNotFound):
        await harness.service.get_draft("archived")


@pytest.mark.asyncio
async def test_archived_project_can_read_existing_draft_but_cannot_preview_or_write():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    writes = harness.repository.write_count
    harness.repository.projects["p1"]["status"] = "archived"

    assert await harness.service.get_draft("p1") == saved
    with pytest.raises(ContractNotFound):
        await harness.service.preview("p1")
    with pytest.raises(ProjectArchived):
        await harness.service.save_draft(command(
            harness, expected=saved.draft_version,
        ))
    with pytest.raises(ProjectArchived):
        await harness.service.confirm(confirmation(saved, key="archived-confirm"))

    assert harness.repository.write_count == writes
    assert harness.repository.drafts["p1"]["draft_version"] == saved.draft_version


@pytest.mark.asyncio
async def test_archived_project_can_read_confirmed_head_and_history_but_not_clone():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    confirmed = await harness.service.confirm(confirmation(saved))
    writes = harness.repository.write_count
    harness.repository.projects["p1"]["status"] = "archived"

    assert await harness.service.get_head("p1") == confirmed
    assert await harness.service.history("p1") == ContractHistoryPage(
        items=(confirmed,), next_before_revision=None,
    )
    with pytest.raises(ProjectArchived):
        await harness.service.clone_revision("p1", confirmed.revision)

    assert harness.repository.write_count == writes
    assert "p1" not in harness.repository.drafts


def test_draft_is_strict_bounded_and_rejects_duplicate_or_same_style_refs():
    harness = ContractHarness()
    values = draft_values(harness.repository)
    with pytest.raises(ValidationError):
        ContractDraftInput(**{**values, "rubric": "secret full rubric"})
    with pytest.raises(ValidationError):
        ContractDraftInput(**{**values, "likes": ("x",) * 21})
    with pytest.raises(ValidationError):
        ContractDraftInput(**{**values, "engineOptionId": "x" * 37})
    with pytest.raises(ValidationError):
        ContractDraftInput(
            **{**values, "experienceCardRefs": values["experienceCardRefs"] * 2}
        )
    with pytest.raises(ValidationError):
        ContractDraftInput(**{**values, "likes": ("克制", "克制")})
    with pytest.raises(ValidationError):
        ContractDraftInput(**{**values, "dislikes": (r"C:\\private\\novel.txt",)})
    with pytest.raises(ValidationError):
        ContractDraftInput(
            **{**values, "secondaryStyleRef": values["primaryStyleRef"]}
        )
    with pytest.raises(ValidationError):
        ContractDraftInput(
            **{
                **values,
                "corpusSourceRefs": ({
                    **values["corpusSourceRefs"][0], "selectionMode": "unsafe"
                },),
            }
        )


@pytest.mark.asyncio
async def test_preview_is_deterministic_read_only_and_freezes_exact_dependencies():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    writes_before = harness.repository.write_count

    first = await harness.service.preview("p1")
    second = await harness.service.preview("p1")

    assert first == second
    assert harness.repository.write_count == writes_before
    assert first.contract_ready is True
    assert first.reasons == ()
    assert first.expected_revision == saved.base_head_revision + 1 == 1
    assert first.seed_ref.revision_id == saved.draft.seedRevisionId
    assert first.seed_ref.content_hash == saved.draft.seedHash
    assert first.engine_ref.id == saved.draft.engineOptionId
    assert first.engine_ref.content_hash == saved.draft.engineHash
    assert first.binding_ref.revision == 3
    assert first.binding_ref.content_hash == harness.repository.binding["content_hash"]
    assert first.style_refs[0].content_hash == saved.draft.primaryStyleRef.contentHash
    assert first.experience_card_refs[0].revision == 3
    assert first.corpus_source_refs[0].revision == 5
    assert first.creation_contract.qualityCharterVersion == "writer-core-quality-v1"
    assert first.creation_contract.modelBindingRef.revision == 3
    assert "rubric" not in first.creation_contract.model_dump()
    assert "checklist" not in first.creation_contract.model_dump()
    assert first.style_contract.narrativeDistance == "近距离第三人称"
    assert first.style_contract.sentenceParagraphRhythm == "行动段短促，反思段舒展"
    assert first.style_contract.dialogueAndSubtext == "对白：对白简短；潜台词：冲突藏在回避中"
    assert first.style_contract.characterVoices == ("主角克制，县令锋利",)
    assert first.style_contract.emotionAndInteriority == (
        "情绪：以选择承载情绪；内心：内心活动贴近当下感官"
    )
    assert first.style_contract.actionExplanationEnvironment == (
        "动作：先写动作；说明：动作后解释；环境：环境参与阻碍；"
        "身体反应：压力通过呼吸与肌肉反应显现"
    )
    assert first.style_contract.primaryRules == ("克制现实主义", "避免空泛抒情")
    assert first.style_contract.secondaryFlavor == (
        "章回悬念：章回体悬念；仅作局部风味，不覆盖主风格的叙事距离、"
        "语言底色和整体阅读体验。"
    )
    assert first.style_contract.narrativeDistance != "全知视角"
    expected_style_hash = canonical_hash({
        "mergedStyle": first.style_contract.model_dump(mode="json"),
        "likes": list(saved.draft.likes),
        "dislikes": list(saved.draft.dislikes),
    })
    assert first.style_hash == expected_style_hash


@pytest.mark.asyncio
async def test_preview_accepts_m2c_4000_char_prompts_and_composed_style_fields():
    harness = ContractHarness()
    row = harness.repository.styles["style-primary"]
    payload = json.loads(row["payload_json"])
    for field in (
        "reading_experience", "narrative_distance", "rhythm",
        "diction_density", "dialogue", "subtext", "character_voices",
        "emotion", "interiority", "action", "explanation", "environment",
        "body_response",
    ):
        payload[field] = field[0] * 4_000
    payload["preferred_techniques"] = ("技" * 4_000,)
    payload["risks"] = ("险" * 4_000,)
    content_hash = canonical_hash(payload)
    row.update({
        "payload_json": canonical_json(payload),
        "content_hash": content_hash,
        "head_hash": content_hash,
    })

    await harness.service.save_draft(command(harness))
    preview = await harness.service.preview("p1")

    assert preview.style_contract is not None
    assert len(preview.style_contract.characterVoices[0]) == 4_000
    assert len(preview.style_contract.dialogueAndSubtext) > 8_000
    assert len(preview.style_contract.actionExplanationEnvironment) > 16_000


@pytest.mark.asyncio
async def test_preview_accepts_a_frozen_seed_revision_with_provenance():
    harness = ContractHarness()
    add_seed_provenance(harness)
    await harness.service.save_draft(command(harness))

    preview = await harness.service.preview("p1")

    assert preview.contract_ready is True
    assert preview.reasons == ()
    assert preview.seed_ref.content_hash == canonical_hash(SEED_PAYLOAD)


@pytest.mark.asyncio
async def test_preview_reports_seed_and_binding_drift_without_substitution_or_write():
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))
    original_engine = harness.repository.engines["engine-1"]["id"]
    harness.repository.selected_seeds["p1"]["seed_revision_id"] = "seed-revision-2"
    harness.repository.binding_head = {
        "head_revision": 4,
        "head_binding_revision_id": "binding-revision-4",
        "head_hash": "c" * 64,
    }

    preview = await harness.service.preview("p1")

    assert preview.contract_ready is False
    assert "seed_drift" in preview.reasons
    assert "binding_drift" in preview.reasons
    assert preview.engine_ref.id == original_engine
    assert preview.creation_contract.modelBindingRef.revision == 3
    assert harness.repository.write_count == 1


@pytest.mark.asyncio
async def test_resave_explicitly_refreshes_frozen_binding_and_restores_readiness():
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))
    revision4 = {
        **harness.repository.binding,
        "revision": 4,
        "binding_revision_id": "binding-revision-4",
    }
    revision4["content_hash"] = canonical_hash(BindingRevision(
        project_id="p1", revision=4,
        items=tuple(BindingItem(**{
            key: row[key] for key in (
                "task_key", "resolution_status", "provider_id",
                "provider_name_snapshot", "model_name_snapshot",
            )
        }) for row in revision4["items"]),
    ))
    harness.repository.binding_revisions["binding-revision-4"] = revision4
    harness.repository.binding_head = {
        "head_revision": 4,
        "head_binding_revision_id": "binding-revision-4",
        "head_hash": revision4["content_hash"],
    }

    drifted = await harness.service.preview("p1")
    saved = await harness.service.save_draft(command(harness, expected=1))
    refreshed = await harness.service.preview("p1")

    assert drifted.contract_ready is False
    assert "binding_drift" in drifted.reasons
    assert saved.draft.modelBindingRef.id == "binding-revision-4"
    assert saved.draft.modelBindingRef.revision == 4
    assert refreshed.contract_ready is True
    assert refreshed.creation_contract.modelBindingRef.revision == 4


@pytest.mark.asyncio
async def test_resave_refreshes_server_frozen_seed_and_exposes_old_engine_drift():
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))
    revised_payload = {
        **SEED_PAYLOAD,
        "title": "典镇山河·再修版",
    }
    revised_hash = canonical_hash(revised_payload)
    revised = {
        "seed_id": "seed-1",
        "selection_revision": 8,
        "seed_revision_id": "seed-revision-2",
        "seed_hash": revised_hash,
        "payload_json": canonical_json(revised_payload),
    }
    harness.repository.selected_seeds["p1"] = revised
    harness.repository.seed_revisions["seed-revision-2"] = revised

    drifted = await harness.service.preview("p1")
    saved = await harness.service.save_draft(command(harness, expected=1))
    refreshed = await harness.service.preview("p1")

    assert "seed_drift" in drifted.reasons
    assert saved.draft.seedRevisionId == "seed-revision-2"
    assert saved.draft.seedHash == revised_hash
    assert "seed_drift" not in refreshed.reasons
    assert "engine_seed_drift" in refreshed.reasons
    assert refreshed.contract_ready is False


@pytest.mark.asyncio
async def test_same_seed_reselection_marks_old_engine_generation_not_ready():
    harness = ContractHarness()
    initial = await harness.service.save_draft(command(harness))
    harness.repository.selected_seeds["p1"]["selection_revision"] = 8

    refreshed = await harness.service.save_draft(
        command(harness, expected=initial.draft_version)
    )
    preview = await harness.service.preview("p1")

    assert refreshed.selection_revision == 8
    assert preview.contract_ready is False
    assert preview.reasons == ("engine_seed_drift",)
    with pytest.raises(ContractConflict):
        await harness.service.confirm(
            confirmation(refreshed, key="old-engine-selection")
        )
    assert harness.repository.confirmation_requests == {}
    assert harness.repository.creation_contracts == {}


@pytest.mark.asyncio
async def test_preview_reports_asset_head_drift_but_keeps_frozen_revision_and_hash():
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))
    frozen = harness.repository.styles["style-primary"]["content_hash"]
    harness.repository.styles["style-primary"]["head_revision"] = 3
    harness.repository.styles["style-primary"]["head_hash"] = "f" * 64

    preview = await harness.service.preview("p1")

    assert preview.contract_ready is False
    assert "style_drift:primary" in preview.reasons
    assert preview.style_refs[0].revision == 2
    assert preview.style_refs[0].content_hash == frozen


@pytest.mark.asyncio
async def test_preview_rejects_missing_draft_but_reports_invalid_frozen_seed():
    harness = ContractHarness()
    with pytest.raises(ContractPreconditionFailed):
        await harness.service.preview("p1")
    await harness.service.save_draft(command(harness))
    harness.repository.seed_revisions["seed-revision-1"]["payload_json"] = '{"bad":true}'
    preview = await harness.service.preview("p1")
    assert preview.contract_ready is False
    assert "seed_invalid" in preview.reasons
    assert preview.creation_contract is None


@pytest.mark.parametrize(
    ("missing", "reason", "null_field"),
    (
        ("seed", "seed_missing", "creation_contract"),
        ("engine", "engine_missing", "creation_contract"),
        ("style", "style_missing:primary", "style_contract"),
        ("binding", "binding_missing", "creation_contract"),
    ),
)
@pytest.mark.asyncio
async def test_preview_missing_dependencies_returns_deterministic_readable_snapshot(
    missing, reason, null_field
):
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    writes = harness.repository.write_count
    if missing == "seed":
        harness.repository.seed_revisions.clear()
    elif missing == "engine":
        harness.repository.engines.clear()
    elif missing == "style":
        harness.repository.styles.pop("style-primary")
    else:
        harness.repository.binding_revisions.clear()

    first = await harness.service.preview("p1")
    second = await harness.service.preview("p1")

    assert first == second
    assert first.contract_ready is False
    assert reason in first.reasons
    assert getattr(first, null_field) is None
    assert harness.repository.write_count == writes
    assert first.seed_ref.revision_id == saved.draft.seedRevisionId
    assert first.engine_ref.id == saved.draft.engineOptionId
    assert first.binding_ref.id == saved.draft.modelBindingRef.id


@pytest.mark.asyncio
async def test_preview_invalid_binding_returns_null_creation_instead_of_422():
    harness = ContractHarness()
    await harness.service.save_draft(command(harness))
    harness.repository.binding["items"][0]["task_key"] = "invalid-task"

    preview = await harness.service.preview("p1")

    assert preview.contract_ready is False
    assert "binding_invalid" in preview.reasons
    assert preview.creation_contract is None
    assert preview.creation_hash is None


@pytest.mark.asyncio
async def test_clone_confirmed_head_creates_version_one_and_never_overwrites():
    harness = ContractHarness()
    initial = await harness.service.save_draft(command(harness))
    preview = await harness.service.preview("p1")
    harness.repository.drafts.clear()
    harness.repository.heads["p1"] = {
        "project_id": "p1", "revision": 7,
        "creation_contract_id": "creation-7", "style_contract_id": "style-7",
        "creation_hash": preview.creation_hash, "style_hash": preview.style_hash,
    }
    reference_manifest = harness.service._reference_manifest(preview)
    harness.repository.confirmed["p1"] = {
        "project_id": "p1",
        "revision": 7,
        "selection_revision": initial.selection_revision,
        "channel_profile_key": initial.draft.channelProfileKey,
        "genre_profile_key": initial.draft.genreProfileKey,
        "quality_charter_version": initial.draft.qualityCharterVersion,
        "total_word_min": initial.draft.targetTotalWords,
        "total_word_max": initial.draft.targetTotalWords,
        "chapter_capacity_policy": canonical_json({
            "expectedVolumeCount": initial.draft.expectedVolumeCount,
            "expectedChapterCount": initial.draft.expectedChapterCount,
            "chapterWordRangePreference": list(
                initial.draft.chapterWordRangePreference
            ),
        }),
        "seed_id": preview.seed_ref.id,
        "seed_revision_id": initial.draft.seedRevisionId,
        "seed_hash": initial.draft.seedHash,
        "engine_option_id": initial.draft.engineOptionId,
        "engine_batch_id": preview.engine_ref.batch_id,
        "engine_hash": initial.draft.engineHash,
        "binding_revision_id": preview.binding_ref.id,
        "binding_revision": preview.binding_ref.revision,
        "binding_hash": preview.binding_ref.content_hash,
        "creation_hash": preview.creation_hash,
        "style_hash": preview.style_hash,
        "head_creation_hash": preview.creation_hash,
        "head_style_hash": preview.style_hash,
        "creation_contract_id": "creation-7",
        "style_contract_id": "style-7",
        "reference_manifest_json": canonical_json(reference_manifest),
        "reference_manifest_hash": canonical_hash(reference_manifest),
        "creation_json": preview.creation_contract.model_dump(mode="json"),
        "style_json": preview.style_contract.model_dump(mode="json"),
        "likes_json": list(initial.draft.likes),
        "dislikes_json": list(initial.draft.dislikes),
        "style_refs": tuple(ref.model_dump(mode="json") for ref in preview.style_refs),
        "experience_card_refs": tuple(
            ref.model_dump(mode="json") for ref in preview.experience_card_refs
        ),
            "corpus_source_refs": tuple(
                ref.model_dump(mode="json") for ref in preview.corpus_source_refs
            ),
            "corpus_fragment_refs": tuple({
                "sourceId": source.id,
                **fragment.model_dump(mode="json"),
            } for source in preview.corpus_source_refs
              for fragment in source.fragments),
    }
    snapshot = harness.repository.confirmed["p1"]
    snapshot["creation_json"] = canonical_json(snapshot["creation_json"])
    snapshot["style_json"] = canonical_json(snapshot["style_json"])
    snapshot["likes_json"] = canonical_json(snapshot["likes_json"])
    snapshot["dislikes_json"] = canonical_json(snapshot["dislikes_json"])

    snapshot["creation_hash"] = "0" * 64
    with pytest.raises(ContractPreconditionFailed):
        await harness.service.clone_revision("p1", 7)
    harness.repository.confirmed["p1"]["creation_hash"] = preview.creation_hash

    corruptions = ("binding", "seed", "engine", "style", "card", "corpus")
    for kind in corruptions:
        target, field = {
            "binding": (
                harness.repository.binding_revisions["binding-revision-3"],
                "content_hash",
            ),
            "seed": (
                harness.repository.seed_revisions["seed-revision-1"], "seed_hash",
            ),
            "engine": (harness.repository.engines["engine-1"], "content_hash"),
            "style": (harness.repository.styles["style-primary"], "content_hash"),
            "card": (harness.repository.cards["card-1"], "content_hash"),
            "corpus": (harness.repository.sources["source-1"], "source_hash"),
        }[kind]
        original = target[field]
        target[field] = "f" * 64
        with pytest.raises(ContractPreconditionFailed):
            await harness.service.clone_revision("p1", 7)
        # Rollback replaces fake repository containers; restore by semantic key.
        if kind == "seed":
            harness.repository.seed_revisions["seed-revision-1"][field] = original
        elif kind == "corpus":
            harness.repository.sources["source-1"][field] = original
        elif kind == "engine":
            harness.repository.engines["engine-1"][field] = original
        elif kind == "style":
            harness.repository.styles["style-primary"][field] = original
        elif kind == "card":
            harness.repository.cards["card-1"][field] = original
        else:
            harness.repository.binding_revisions["binding-revision-3"][field] = original

    harness.repository.styles["style-primary"]["head_revision"] = 99
    harness.repository.styles["style-primary"]["head_hash"] = "9" * 64
    cloned = await harness.service.clone_revision("p1", 7)

    assert cloned.draft_version == 1
    assert cloned.base_head_revision == 7
    assert cloned.draft == initial.draft
    harness.repository.binding_head = {
        "head_revision": 4,
        "head_binding_revision_id": "binding-revision-4",
        "head_hash": "c" * 64,
    }
    drifted_clone = await harness.service.preview("p1")
    assert drifted_clone.contract_ready is False
    assert "style_drift:primary" in drifted_clone.reasons
    with pytest.raises(ContractConflict):
        await harness.service.clone_revision("p1", 7)


@pytest.mark.asyncio
async def test_clone_historical_revision_in_same_selection_uses_current_head_base():
    harness = ContractHarness()
    initial = await harness.service.save_draft(command(harness))
    await harness.service.confirm(confirmation(initial))
    historical = deepcopy(harness.repository.confirmed_revisions[("p1", 1)])
    current = {
        **deepcopy(historical),
        "revision": 2,
        "creation_contract_id": "creation-2",
        "style_contract_id": "style-2",
    }
    harness.repository.confirmed_revisions[("p1", 2)] = current
    harness.repository.confirmed["p1"] = current
    harness.repository.heads["p1"] = {
        "project_id": "p1",
        "revision": 2,
        "creation_contract_id": "creation-2",
        "style_contract_id": "style-2",
        "creation_hash": current["creation_hash"],
        "style_hash": current["style_hash"],
    }

    cloned = await harness.service.clone_revision("p1", 1)

    assert cloned.draft == initial.draft
    assert cloned.selection_revision == historical["selection_revision"]
    assert cloned.base_head_revision == 2
    assert cloned.draft_version == 1
    assert cloned.id != initial.id


@pytest.mark.parametrize(
    ("case", "field", "tampered", "relation_updates", "capacity_updates"),
    (
        ("selection", "selectionRevision", 8, {}, {}),
        ("channel", "channelProfileKey", "tampered-channel", {}, {}),
        ("genre", "genreProfileKey", "tampered-genre", {}, {}),
        ("charter", "qualityCharterVersion", "tampered-charter-v2", {}, {}),
        ("word-min", "targetTotalWords", 1_000_001,
         {"total_word_max": 1_000_001}, {}),
        ("word-max", "targetTotalWords", 999_999,
         {"total_word_min": 999_999}, {}),
        ("volumes", "expectedVolumeCount", 9, {}, {}),
        ("chapters", "expectedChapterCount", 401, {}, {}),
        ("chapter-range", "chapterWordRangePreference", [2_600, 3_600], {}, {}),
        ("capacity-extra", None, None, {}, {"unexpected": 1}),
    ),
)
@pytest.mark.asyncio
async def test_clone_non_head_revision_rejects_creation_payload_relational_drift(
    case, field, tampered, relation_updates, capacity_updates,
):
    harness = ContractHarness()
    first_draft = await harness.service.save_draft(command(harness))
    await harness.service.confirm(confirmation(
        first_draft, key=f"confirm-first-{case}",
    ))
    second_draft = await harness.service.clone_revision("p1", 1)
    await harness.service.confirm(confirmation(
        second_draft, key=f"confirm-second-{case}",
    ))
    historical = harness.repository.confirmed_revisions[("p1", 1)]
    creation = json.loads(historical["creation_json"])
    if field is not None:
        creation[field] = tampered
    historical["creation_json"] = canonical_json(creation)
    historical["creation_hash"] = canonical_hash(creation)
    historical.update(relation_updates)
    if capacity_updates:
        capacity = json.loads(historical["chapter_capacity_policy"])
        capacity.update(capacity_updates)
        historical["chapter_capacity_policy"] = canonical_json(capacity)

    with pytest.raises(ContractPreconditionFailed):
        await harness.service.clone_revision("p1", 1)

    assert "p1" not in harness.repository.drafts


@pytest.mark.asyncio
async def test_clone_historical_revision_rejects_a_b_a_selection_generation():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    await harness.service.confirm(confirmation(saved))
    harness.repository.selected_seeds["p1"]["selection_revision"] = 9

    with pytest.raises(ContractConflict):
        await harness.service.clone_revision("p1", 1)

    assert harness.repository.drafts == {}


@pytest.mark.asyncio
async def test_clone_rejects_confirmed_head_from_superseded_same_seed_selection():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    confirmed = await harness.service.confirm(confirmation(saved))
    assert confirmed.selection_revision == 7
    assert harness.repository.drafts == {}

    harness.repository.selected_seeds["p1"]["selection_revision"] = 8

    with pytest.raises(ContractConflict):
        await harness.service.clone_revision("p1", 1)

    assert harness.repository.drafts == {}


@pytest.mark.asyncio
async def test_clone_requires_existing_source_revision():
    harness = ContractHarness()
    with pytest.raises(ContractNotFound):
        await harness.service.clone_revision("p1", 1)


@pytest.mark.parametrize("corruption", ("primary", "card", "corpus", "manifest"))
@pytest.mark.asyncio
async def test_clone_rejects_incomplete_or_tampered_reference_manifest(corruption):
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    await harness.service.confirm(confirmation(saved, key=f"confirm-{corruption}"))
    snapshot = harness.repository.confirmed["p1"]
    if corruption == "primary":
        snapshot["style_refs"] = tuple(
            ref for ref in snapshot["style_refs"] if ref["role"] != "primary"
        )
    elif corruption == "card":
        snapshot["experience_card_refs"] = ()
    elif corruption == "corpus":
        snapshot["corpus_source_refs"] = ()
    else:
        manifest = json.loads(snapshot["reference_manifest_json"])
        manifest["schemaVersion"] = "tampered-manifest"
        snapshot["reference_manifest_json"] = canonical_json(manifest)

    with pytest.raises(ContractPreconditionFailed):
        await harness.service.clone_revision("p1", 1)

    assert "p1" not in harness.repository.drafts


@pytest.mark.asyncio
async def test_plain_save_cannot_bypass_clone_after_a_confirmed_head():
    harness = ContractHarness()
    harness.repository.heads["p1"] = {
        "project_id": "p1", "revision": 1,
        "creation_contract_id": "creation-1", "style_contract_id": "style-1",
        "creation_hash": "a" * 64, "style_hash": "b" * 64,
    }

    with pytest.raises(ContractConflict):
        await harness.service.save_draft(command(harness))


def confirmation(saved, *, key="confirm-once", content_hash=None):
    return ConfirmContracts(
        project_id="p1",
        idempotency_key=key,
        expected_draft_version=saved.draft_version,
        expected_draft_hash=content_hash or saved.content_hash,
    )


@pytest.mark.asyncio
async def test_confirm_atomically_consumes_draft_and_freezes_all_relations():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))

    result = await harness.service.confirm(confirmation(saved))

    assert result.revision == 1
    assert result.selection_revision == 7
    assert harness.repository.creation_contracts[
        result.creation_contract_id
    ]["selection_revision"] == 7
    assert harness.repository.confirmation_requests[
        ("p1", "confirm-once")
    ]["selection_revision"] == 7
    assert result.creation_contract_id
    assert result.style_contract_id
    assert result.creation_hash == canonical_hash(result.creation_contract)
    assert result.style_hash == canonical_hash({
        "mergedStyle": result.style_contract.model_dump(mode="json"),
        "likes": list(result.likes),
        "dislikes": list(result.dislikes),
    })
    assert result.binding_ref.revision == 3
    assert len(result.binding_ref.items) == 8
    assert result.engine_ref.id == "engine-1"
    assert tuple(ref.role for ref in result.style_refs) == ("primary", "secondary")
    assert result.experience_card_refs[0].id == "card-1"
    assert result.corpus_source_refs[0].selectionMode == "author"
    assert "p1" not in harness.repository.drafts
    assert harness.repository.heads["p1"]["revision"] == 1
    assert len(harness.repository.confirmation_requests) == 1
    request = next(iter(harness.repository.confirmation_requests.values()))
    assert request["id"] == saved.id
    assert request["request_hash"] == canonical_hash({
        "projectId": "p1", "draftId": saved.id,
        "draftVersion": saved.draft_version, "draftHash": saved.content_hash,
        "baseHeadRevision": saved.base_head_revision, "expectedRevision": 1,
        "selectionRevision": saved.selection_revision,
        "seedRef": {
            "revisionId": result.seed_ref.revision_id,
            "contentHash": result.seed_ref.content_hash,
        },
        "engineRef": {
            "id": result.engine_ref.id,
            "contentHash": result.engine_ref.content_hash,
        },
        "bindingRef": {
            "id": result.binding_ref.id, "revision": result.binding_ref.revision,
            "contentHash": result.binding_ref.content_hash,
        },
        "styleRefs": [ref.model_dump(mode="json") for ref in result.style_refs],
        "experienceCardRefs": [
            ref.model_dump(mode="json") for ref in result.experience_card_refs
        ],
        "corpusSourceRefs": [
            ref.model_dump(mode="json") for ref in result.corpus_source_refs
        ],
    })


@pytest.mark.asyncio
async def test_confirm_accepts_a_frozen_seed_revision_with_provenance():
    harness = ContractHarness()
    add_seed_provenance(harness)
    saved = await harness.service.save_draft(command(harness))

    result = await harness.service.confirm(
        confirmation(saved, key="confirm-provenance-seed")
    )

    assert result.revision == 1
    assert result.seed_ref.content_hash == canonical_hash(SEED_PAYLOAD)
    assert "p1" not in harness.repository.drafts


@pytest.mark.asyncio
async def test_confirm_locks_assets_by_stable_type_and_id_but_preserves_draft_order():
    harness = ContractHarness()
    original = harness.repository.cards["card-1"]
    earlier = {
        **original, "id": "card-0", "stable_key": "earlier-card",
        "head_id": "card-0",
    }
    harness.repository.cards["card-0"] = earlier
    source = harness.repository.sources["source-1"]
    earlier_source = {
        **source,
        "id": "source-0",
        "revision_id": "source-revision-4",
        "source_key": "earlier-authorized-work",
        "revision": 4,
        "source_hash": "d" * 64,
        "head_id": "source-revision-4",
        "head_revision": 4,
        "head_hash": "d" * 64,
    }
    harness.repository.sources["source-0"] = earlier_source
    harness.repository.fragments["fragment-0"] = {
        **harness.repository.fragments["fragment-1"],
        "source_id": "source-0",
        "source_revision_id": "source-revision-4",
        "source_revision": 4,
        "source_hash": "d" * 64,
        "source_head_revision_id": "source-revision-4",
        "source_head_revision": 4,
        "source_head_hash": "d" * 64,
        "chapter_id": "chapter-0",
        "fragment_id": "fragment-0",
        "fragment_hash": "0" * 64,
    }
    refs = tuple({
        "id": row["id"], "revision": row["revision"],
        "contentHash": row["content_hash"],
    } for row in (original, earlier))
    corpus_refs = tuple({
        "id": row["id"], "revisionId": row["revision_id"],
        "revision": row["revision"], "contentHash": row["source_hash"],
        "selectionMode": "author",
        "fragments": ({
            "chapterId": chapter_id,
            "fragmentId": fragment_id,
            "fragmentHash": fragment_hash,
            "chapterCharStart": 10,
            "chapterCharEnd": 110,
            "referenceUse": "style",
        },),
        "pinnedHistoricalRevision": False,
    } for row, chapter_id, fragment_id, fragment_hash in (
        (source, "chapter-1", "fragment-1", "f" * 64),
        (earlier_source, "chapter-0", "fragment-0", "0" * 64),
    ))
    saved = await harness.service.save_draft(command(
        harness, experienceCardRefs=refs, corpusSourceRefs=corpus_refs,
    ))
    harness.repository.events.clear()

    result = await harness.service.confirm(confirmation(saved))

    assert tuple(ref.id for ref in result.experience_card_refs) == (
        "card-1", "card-0",
    )
    assert tuple(ref.id for ref in result.corpus_source_refs) == (
        "source-1", "source-0",
    )
    asset_locks = tuple(
        event for event in harness.repository.events
        if event.startswith("lock-asset:")
    )
    assert asset_locks == (
        "lock-asset:corpus:source-0",
        "lock-asset:corpus:source-1",
        "lock-asset:experience:card-0",
        "lock-asset:experience:card-1",
        "lock-asset:style:style-primary",
        "lock-asset:style:style-secondary",
    )
    assert tuple(
        event for event in harness.repository.events
        if event.startswith("lock-fragments:")
    ) == (
        "lock-fragments:source-0:source-revision-4",
        "lock-fragments:source-1:source-revision-5",
    )


@pytest.mark.asyncio
async def test_confirm_same_key_replays_but_different_hash_is_stable_conflict():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    first = await harness.service.confirm(confirmation(saved))

    replay = await harness.service.confirm(confirmation(saved))
    with pytest.raises(ContractConflict):
        await harness.service.confirm(confirmation(
            saved, content_hash="f" * 64,
        ))

    assert replay == first
    assert harness.repository.heads["p1"]["revision"] == 1
    assert len(harness.repository.creation_contracts) == 1


@pytest.mark.asyncio
async def test_confirm_replay_ignores_an_unrelated_newer_clone_draft():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    first = await harness.service.confirm(confirmation(saved))
    cloned = await harness.service.clone_revision("p1", 1)
    await harness.service.save_draft(command(
        harness, expected=cloned.draft_version, likes=("新修订",),
    ))

    replay = await harness.service.confirm(confirmation(saved))

    assert replay == first
    assert harness.repository.drafts["p1"]["content_hash"] != saved.content_hash


@pytest.mark.asyncio
async def test_history_and_replay_mark_superseded_selection_generation_read_only():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    first = await harness.service.confirm(confirmation(saved))
    harness.repository.selected_seeds["p1"]["selection_revision"] += 2

    historical = (await harness.service.history("p1")).items
    replay = await harness.service.confirm(confirmation(saved))

    assert first.contract_ready is True
    assert historical[0].contract_ready is False
    assert historical[0].reasons == ("superseded",)
    assert replay.contract_ready is False
    assert replay.reasons == ("superseded",)
    assert harness.repository.heads["p1"]["revision"] == 1
    assert len(harness.repository.creation_contracts) == 1


@pytest.mark.asyncio
async def test_history_and_replay_mark_replaced_contract_revision_superseded():
    harness = ContractHarness()
    first_draft = await harness.service.save_draft(command(harness))
    first = await harness.service.confirm(confirmation(
        first_draft, key="confirm-revision-1"
    ))
    second_draft = await harness.service.clone_revision("p1", 1)
    second = await harness.service.confirm(confirmation(
        second_draft, key="confirm-revision-2"
    ))

    history = (await harness.service.history("p1")).items
    replay = await harness.service.confirm(confirmation(
        first_draft, key="confirm-revision-1"
    ))

    assert first.selection_revision == second.selection_revision
    assert tuple(item.revision for item in history) == (2, 1)
    assert history[0].contract_ready is True
    assert history[0].superseded_reasons == ()
    assert history[1].contract_ready is False
    assert history[1].reasons == ("superseded",)
    assert history[1].superseded_reasons == ("contract_revision_replaced",)
    assert replay.contract_ready is False
    assert replay.reasons == ("superseded",)
    assert replay.superseded_reasons == ("contract_revision_replaced",)


@pytest.mark.asyncio
async def test_history_uses_exclusive_revision_cursor_without_duplicates_or_gaps():
    harness = ContractHarness()
    draft = await harness.service.save_draft(command(harness))
    for revision in (1, 2, 3):
        await harness.service.confirm(confirmation(
            draft, key=f"history-page-{revision}"
        ))
        if revision < 3:
            draft = await harness.service.clone_revision("p1", revision)

    first = await harness.service.history("p1", limit=2)
    second = await harness.service.history(
        "p1", limit=2, before_revision=first.next_before_revision
    )
    empty = await harness.service.history("p1", limit=2, before_revision=1)

    assert tuple(item.revision for item in first.items) == (3, 2)
    assert first.next_before_revision == 2
    assert tuple(item.revision for item in second.items) == (1,)
    assert second.next_before_revision is None
    assert empty == ContractHistoryPage(items=(), next_before_revision=None)


@pytest.mark.parametrize("before_revision", (0, -1, True, 1.0, "1"))
@pytest.mark.asyncio
async def test_history_rejects_non_positive_or_non_integer_revision_cursor(
    before_revision,
):
    harness = ContractHarness()

    with pytest.raises(ContractPreconditionFailed):
        await harness.service.history("p1", before_revision=before_revision)


@pytest.mark.parametrize("limit", (True, 1.0, "1", 0, 101))
@pytest.mark.asyncio
async def test_history_rejects_non_strict_or_out_of_bounds_limit(limit):
    harness = ContractHarness()

    with pytest.raises(ContractPreconditionFailed):
        await harness.service.history("p1", limit=limit)

    assert harness.repository.drafts == {}
    assert harness.repository.write_count == 0


@pytest.mark.asyncio
async def test_revision_zero_history_is_a_frozen_typed_empty_page_without_writes():
    harness = ContractHarness()

    page = await harness.service.history("p1")

    assert harness.repository.heads["p1"]["revision"] == 0
    assert isinstance(page, ContractHistoryPage)
    assert page.items == ()
    assert page.next_before_revision is None
    assert harness.repository.drafts == {}
    assert harness.repository.write_count == 0
    with pytest.raises(AttributeError):
        page.next_before_revision = 1


def test_history_service_declares_the_typed_page_return_contract():
    hints = get_type_hints(ContractService.history)

    assert hints["return"] is ContractHistoryPage


@pytest.mark.parametrize("stage", (
    "after_confirmation_reserve", "after_creation_insert", "after_style_insert",
    "after_engine_refs", "after_style_refs", "after_card_refs",
    "after_corpus_refs", "after_corpus_fragment_refs", "after_head_cas",
    "after_draft_delete",
    "before_request_success",
))
@pytest.mark.asyncio
async def test_every_confirmation_failpoint_rolls_back_all_writes(stage):
    harness = ContractHarness(failpoint=lambda current: (_ for _ in ()).throw(
        RuntimeError(current)
    ) if current == stage else None)
    saved = await harness.service.save_draft(command(harness))
    draft_before = dict(harness.repository.drafts["p1"])

    with pytest.raises(RuntimeError, match=stage):
        await harness.service.confirm(confirmation(saved))

    assert harness.repository.drafts["p1"] == draft_before
    assert harness.repository.heads["p1"]["revision"] == 0
    assert harness.repository.confirmation_requests == {}
    assert harness.repository.creation_contracts == {}
    assert harness.repository.style_contracts == {}
    assert harness.repository.corpus_fragment_refs == []


@pytest.mark.parametrize("drift", (
    "seed", "engine", "binding", "style", "card", "corpus", "fragment", "head",
))
@pytest.mark.asyncio
async def test_confirmation_rejects_every_frozen_fact_or_head_drift(drift):
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    if drift == "seed":
        harness.repository.selected_seeds["p1"]["seed_hash"] = "f" * 64
    elif drift == "engine":
        harness.repository.engines["engine-1"]["content_hash"] = "f" * 64
    elif drift == "binding":
        harness.repository.binding_head["head_hash"] = "f" * 64
    elif drift == "style":
        harness.repository.styles["style-primary"]["head_hash"] = "f" * 64
    elif drift == "card":
        harness.repository.cards["card-1"]["head_hash"] = "f" * 64
    elif drift == "corpus":
        harness.repository.sources["source-1"]["head_hash"] = "f" * 64
    elif drift == "fragment":
        harness.repository.fragments["fragment-1"]["fragment_hash"] = "0" * 64
    else:
        harness.repository.heads["p1"]["revision"] = 1

    with pytest.raises(ContractConflict):
        await harness.service.confirm(confirmation(saved))

    assert "p1" in harness.repository.drafts
    assert harness.repository.confirmation_requests == {}
    assert harness.repository.creation_contracts == {}


@pytest.mark.asyncio
async def test_head_readiness_does_not_depend_on_provider_callability():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    await harness.service.confirm(confirmation(saved))
    historical = (await harness.service.history("p1")).items
    harness.repository.binding["items"][0]["provider_ready"] = 0

    head = await harness.service.get_head("p1")

    assert head.contract_ready is True
    assert head.reasons == ()
    assert historical[0].contract_ready is True
    assert historical[0].reasons == ()
