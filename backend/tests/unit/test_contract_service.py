from __future__ import annotations

import json
import traceback

import pytest
from pydantic import ValidationError

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.services.contracts import (
    ContractConflict,
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
    assert created.base_head_revision == 0
    assert created.draft.seedRevisionId == "seed-revision-1"
    assert created.draft.seedHash == harness.repository.selected_seeds["p1"]["seed_hash"]
    assert "lock-selected-seed" in harness.repository.events
    assert created.draft.modelBindingRef.id == "binding-revision-3"
    assert created.draft.modelBindingRef.revision == 3
    assert created.draft.modelBindingRef.contentHash == "b" * 64
    assert reloaded == created
    assert updated.draft_version == 2
    assert updated.base_head_revision == 0
    assert updated.draft.likes == ("克制", "选择有代价")
    assert len(harness.repository.drafts) == 1
    assert harness.repository.drafts["p1"]["seed_revision_id"] == "seed-revision-1"
    assert harness.repository.drafts["p1"]["engine_option_id"] == "engine-1"
    assert harness.repository.drafts["p1"]["content_hash"] == canonical_hash(updated.draft)


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
    assert first.binding_ref.content_hash == "b" * 64
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
        "content_hash": "c" * 64,
    }
    harness.repository.binding_revisions["binding-revision-4"] = revision4
    harness.repository.binding_head = {
        "head_revision": 4,
        "head_binding_revision_id": "binding-revision-4",
        "head_hash": "c" * 64,
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
async def test_preview_rejects_missing_draft_and_invalid_frozen_seed_payload():
    harness = ContractHarness()
    with pytest.raises(ContractPreconditionFailed):
        await harness.service.preview("p1")
    await harness.service.save_draft(command(harness))
    harness.repository.seed_revisions["seed-revision-1"]["payload_json"] = '{"bad":true}'
    with pytest.raises(ContractPreconditionFailed):
        await harness.service.preview("p1")


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
    harness.repository.confirmed["p1"] = {
        "revision": 7,
        "seed_revision_id": initial.draft.seedRevisionId,
        "seed_hash": initial.draft.seedHash,
        "engine_option_id": initial.draft.engineOptionId,
        "engine_hash": initial.draft.engineHash,
        "binding_revision_id": preview.binding_ref.id,
        "binding_revision": preview.binding_ref.revision,
        "binding_hash": preview.binding_ref.content_hash,
        "creation_hash": preview.creation_hash,
        "style_hash": preview.style_hash,
        "head_creation_hash": preview.creation_hash,
        "head_style_hash": preview.style_hash,
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

    cloned = await harness.service.clone_current("p1")

    assert cloned.draft_version == 1
    assert cloned.base_head_revision == 7
    assert cloned.draft == initial.draft
    harness.repository.binding_head = {
        "head_revision": 4,
        "head_binding_revision_id": "binding-revision-4",
        "head_hash": "c" * 64,
    }
    assert (await harness.service.preview("p1")).contract_ready is False
    with pytest.raises(ContractConflict):
        await harness.service.clone_current("p1")


@pytest.mark.asyncio
async def test_clone_requires_confirmed_nonzero_head():
    harness = ContractHarness()
    with pytest.raises(ContractConflict):
        await harness.service.clone_current("p1")


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
