from __future__ import annotations

import json
import traceback

import pytest
from pydantic import ValidationError

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import BindingItem, BindingRevision
from backend.services.contracts import (
    ConfirmContracts,
    ContractConflict,
    ContractDraftIncomplete,
    ContractDraftInput,
    ContractNotFound,
    ContractPreconditionFailed,
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
        "chapterCapacityPolicy",
        "likes",
        "dislikes",
    ),
)
@pytest.mark.parametrize("unsafe_path", _UNSAFE_PATHS)
def test_every_client_text_field_rejects_path_forms(field_name, unsafe_path):
    harness = ContractHarness()
    values = draft_values(harness.repository)
    values[field_name] = (
        (unsafe_path,) if field_name in {"likes", "dislikes"} else unsafe_path
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
    values["chapterCapacityPolicy"] = "节奏：每章推进一个不可逆选择"

    draft = ContractDraftInput(**values)

    assert draft.channelProfileKey == "渠道：中文连载"
    assert draft.chapterCapacityPolicy.startswith("节奏：")


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
    assert first.creation_contract.modelBindingRevision == 3
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
    assert preview.creation_contract.modelBindingRevision == 3
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
    assert refreshed.creation_contract.modelBindingRevision == 4


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
    }
    snapshot = harness.repository.confirmed["p1"]
    snapshot["creation_json"] = canonical_json(snapshot["creation_json"])
    snapshot["style_json"] = canonical_json(snapshot["style_json"])
    snapshot["likes_json"] = canonical_json(snapshot["likes_json"])
    snapshot["dislikes_json"] = canonical_json(snapshot["dislikes_json"])

    snapshot["creation_hash"] = "0" * 64
    with pytest.raises(ContractPreconditionFailed):
        await harness.service.clone_current("p1")
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
            await harness.service.clone_current("p1")
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
    cloned = await harness.service.clone_current("p1")

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
        await harness.service.clone_current("p1")


@pytest.mark.asyncio
async def test_clone_rejects_confirmed_head_from_superseded_same_seed_selection():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    confirmed = await harness.service.confirm(confirmation(saved))
    assert confirmed.selection_revision == 7
    assert harness.repository.drafts == {}

    harness.repository.selected_seeds["p1"]["selection_revision"] = 8

    with pytest.raises(ContractConflict):
        await harness.service.clone_current("p1")

    assert harness.repository.drafts == {}


@pytest.mark.asyncio
async def test_clone_requires_confirmed_nonzero_head():
    harness = ContractHarness()
    with pytest.raises(ContractConflict):
        await harness.service.clone_current("p1")


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
        await harness.service.clone_current("p1")

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
async def test_confirm_locks_assets_by_stable_type_and_id_but_preserves_draft_order():
    harness = ContractHarness()
    original = harness.repository.cards["card-1"]
    earlier = {
        **original, "id": "card-0", "stable_key": "earlier-card",
        "head_id": "card-0",
    }
    harness.repository.cards["card-0"] = earlier
    refs = tuple({
        "id": row["id"], "revision": row["revision"],
        "contentHash": row["content_hash"],
    } for row in (original, earlier))
    saved = await harness.service.save_draft(command(
        harness, experienceCardRefs=refs,
    ))
    harness.repository.events.clear()

    result = await harness.service.confirm(confirmation(saved))

    assert tuple(ref.id for ref in result.experience_card_refs) == (
        "card-1", "card-0",
    )
    asset_locks = tuple(
        event for event in harness.repository.events
        if event.startswith("lock-asset:")
    )
    assert asset_locks == (
        "lock-asset:corpus:source-1",
        "lock-asset:experience:card-0",
        "lock-asset:experience:card-1",
        "lock-asset:style:style-primary",
        "lock-asset:style:style-secondary",
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
    cloned = await harness.service.clone_current("p1")
    await harness.service.save_draft(command(
        harness, expected=cloned.draft_version, likes=("新修订",),
    ))

    replay = await harness.service.confirm(confirmation(saved))

    assert replay == first
    assert harness.repository.drafts["p1"]["content_hash"] != saved.content_hash


@pytest.mark.parametrize("stage", (
    "after_confirmation_reserve", "after_creation_insert", "after_style_insert",
    "after_engine_refs", "after_style_refs", "after_card_refs",
    "after_corpus_refs", "after_head_cas", "after_draft_delete",
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


@pytest.mark.parametrize("drift", (
    "seed", "engine", "binding", "style", "card", "corpus", "head",
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
    else:
        harness.repository.heads["p1"]["revision"] = 1

    with pytest.raises(ContractConflict):
        await harness.service.confirm(confirmation(saved))

    assert "p1" in harness.repository.drafts
    assert harness.repository.confirmation_requests == {}
    assert harness.repository.creation_contracts == {}


@pytest.mark.asyncio
async def test_head_readiness_tracks_current_eight_binding_provider_readiness_only():
    harness = ContractHarness()
    saved = await harness.service.save_draft(command(harness))
    await harness.service.confirm(confirmation(saved))
    historical = await harness.service.history("p1")
    harness.repository.binding["items"][0]["provider_ready"] = 0

    head = await harness.service.get_head("p1")

    assert head.contract_ready is False
    assert head.reasons == ("binding_not_ready",)
    assert historical[0].contract_ready is True
    assert historical[0].reasons == ()
