from __future__ import annotations

import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from backend.prompts.finalization import (
    FINALIZATION_MAX_PROMPT_BYTES,
    FinalizationProviderManifest,
    build_extraction_messages,
    build_quality_messages,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _manifest(**overrides):
    candidate_prose = overrides.pop("candidate_prose", "沈砚走进山门。")
    value = {
        "schema_version": "finalization-provider-v1",
        "chapter_number": 1,
        "candidate_hash": sha256(candidate_prose.encode("utf-8")).hexdigest(),
        "candidate_prose": candidate_prose,
        "canon_context": {"revision": 0, "entities": []},
        "planning_context": {"revision": 1, "storyBlocks": []},
        "outline_context": {"revision": 1, "chapterGoal": "进入山门"},
        "contract_context": {"revision": 1, "genre": "玄幻"},
        "bible_context": {"revision": 1, "rules": []},
        "policy_version": "quality-v1",
        "binding": {
            "provider_id": "provider-1",
            "model_name": "finalization-model",
            "provider_profile_revision": 3,
        },
    }
    value.update(overrides)
    return FinalizationProviderManifest.model_validate(value, strict=True)


def test_manifest_is_closed_frozen_bounded_and_secret_free():
    value = _manifest()

    assert value.chapter_number == 1
    with pytest.raises(ValidationError):
        value.chapter_number = 2
    with pytest.raises(ValidationError):
        FinalizationProviderManifest.model_validate({
            **value.model_dump(mode="json"),
            "unexpected": True,
        }, strict=True)
    with pytest.raises(ValidationError):
        _manifest(candidate_prose="api_key=PRIVATE_SENTINEL")


def test_quality_and_extraction_messages_keep_roles_separate_and_json_only():
    manifest = _manifest()

    quality = build_quality_messages(manifest=manifest)
    extraction = build_extraction_messages(manifest=manifest)

    assert tuple(item["role"] for item in quality) == ("system", "user")
    assert tuple(item["role"] for item in extraction) == ("system", "user")
    quality_system = json.loads(quality[0]["content"])
    extraction_system = json.loads(extraction[0]["content"])
    quality_user = json.loads(quality[1]["content"])
    extraction_user = json.loads(extraction[1]["content"])
    assert quality_system["task"] == "quality_audit"
    assert quality_system["mayCreateCanonFacts"] is False
    assert quality_system["outputShape"] == {
        "findings": [{
            "id": "unique finding id",
            "dimension": (
                "plot_effectiveness|content_richness|character_vitality|"
                "dialogue_credibility|emotional_naturalness|continuity|"
                "pacing|style_stability|ai_flavor|reading_motivation"
            ),
            "reason": "specific reason",
            "severity": "required | suggested | optional",
            "suggestedAction": "specific action",
            "evidence": {
                "paragraphRange": {"start": "exact first paragraph id from candidateParagraphs", "end": "exact last paragraph id from candidateParagraphs"},
                "confidence": "number from 0 to 1",
                "rationale": "brief reason",
            },
        }],
    }
    assert extraction_system["task"] == "finalization_extraction"
    assert extraction_system["singleExtraction"] is True
    for key in ('candidateHash', 'candidateParagraphs', 'canonContext', 'planningContext', 'progressScope'):
        assert quality_user[key] == extraction_user[key]
    assert extraction_user['bibleContext'] == extraction_user['contractContext'] == {}
    assert quality_user['bibleContext'] == manifest.bible_context
    assert quality_user["candidateParagraphs"] == [{"id": "p1", "text": "沈砚走进山门。"}]
    assert "candidateProse" not in quality_system
    assert "candidateProse" not in extraction_system


def test_extraction_prompt_declares_the_exact_closed_changeset_shape():
    system = json.loads(build_extraction_messages(manifest=_manifest())[0]["content"])

    shape = system["outputShape"]
    assert set(shape) == {
        "schemaVersion", "title", "summary", "existingEntityIds",
        "entities", "aliases", "canonEvents", "storyProgressEvents",
        "planningPatches", "planningSuggestions",
    }
    assert shape["schemaVersion"] == "finalization-changeset-v1"
    assert "existingEntityIds" in system["requiredCollections"]
    assert shape["entities"][0] == {
        "id": "unique change id",
        "entityType": "person|organization|place|item",
        "canonicalName": "name",
    }
    assert shape["storyProgressEvents"][0]["targetType"] == (
        "story_block|stage|scene_task"
    )
    assert shape["planningPatches"][0]["expectedHash"] == (
        "exact target hash from planningContext"
    )
    assert shape["planningSuggestions"][0]["targetId"] == (
        "exact planning id or null"
    )
    assert system["forbiddenOutput"] == [
        "changeset wrapper", "top-level evidence", "excerptHash",
        "unknown fields", "markdown", "commentary",
    ]


def test_prompt_bytes_are_bounded_before_provider_call():
    manifest = _manifest(candidate_prose="文" * 100_000)

    messages = build_extraction_messages(manifest=manifest)

    rendered = json.dumps(messages, ensure_ascii=False).encode("utf-8")
    assert len(rendered) <= FINALIZATION_MAX_PROMPT_BYTES
    with pytest.raises(ValidationError):
        _manifest(candidate_prose="文" * 100_001)


@pytest.mark.parametrize(
    "field",
    ("canon_context", "planning_context", "outline_context", "contract_context", "bible_context"),
)
def test_context_must_be_finite_strict_json_object(field):
    with pytest.raises(ValidationError):
        _manifest(**{field: {"bad": float("nan")}})
    with pytest.raises(ValidationError):
        _manifest(**{field: ["not", "an", "object"]})


@pytest.mark.parametrize("builder", [build_quality_messages, build_extraction_messages])
def test_paragraph_range_examples_match_strict_evidence_hydration(builder):
    from backend.gateways.finalization_provider import _hydrate_evidence

    prose = "第一段。\n\n第二段。\n\n第三段。\n\n第四段。\n\n第五段。"
    system = json.loads(builder(manifest=_manifest(candidate_prose=prose))[0]["content"])
    rule = system["evidenceParagraphRange"]
    assert "including both endpoints and every paragraph between them" in rule["meaning"]
    assert "the server includes all of p2, p3 and p4" in rule["distantEvidence"]
    assert "Check every evidence.paragraphRange before returning JSON" in rule["beforeOutput"]
    assert "omit the unsupported item" in rule["beforeOutput"]
    assert rule["validExamples"] == [{"start": "p2", "end": "p2"}, {"start": "p2", "end": "p4"}]
    assert rule["invalidExamples"] == {
        "reverseOrder": {"start": "p4", "end": "p2"},
        "unknownId": {"start": "p2", "end": "p9"},
        "extraKey": {"start": "p2", "end": "p4", "middle": "p3"},
    }
    for ids in rule["validExamples"]:
        evidence = _hydrate_evidence({"paragraphRange": ids, "confidence": 0.9, "rationale": "supported"}, prose)
        excerpt = prose[evidence["startScalar"]:evidence["endScalar"]]
        assert evidence["excerptHash"] == sha256(excerpt.encode("utf-8")).hexdigest()
    for ids in rule["invalidExamples"].values():
        with pytest.raises(ValueError):
            _hydrate_evidence({"paragraphRange": ids, "confidence": 0.9, "rationale": "unsupported"}, prose)


@pytest.mark.parametrize("builder", [build_quality_messages, build_extraction_messages])
def test_progress_scope_distinguishes_chapter_tasks_from_unfinished_parent_tasks(builder):
    from copy import deepcopy

    planning = {"content": {"storyBlocks": [{
        "id": "block-scope", "blockGoal": "完成全部调查", "stages": [{
            "id": "stage-scope", "title": "调查阶段", "purpose": "核查两条线索",
            "sceneTasks": [
                {"id": "task-bound", "task": "调查第一条线索", "completionEvidence": "取得第一条记录"},
                {"id": "task-other", "task": "调查第二条线索", "completionEvidence": "取得第二条记录"},
            ],
        }],
    }]}}
    outline = {"content": {"storyBlockRef": {"id": "block-scope"}, "sceneTaskRefs": [{"id": "task-bound"}]}}
    original = deepcopy((planning, outline))
    manifest = _manifest(planning_context=planning, outline_context=outline, canon_context={"actualProgress": []})
    user = json.loads(builder(manifest=manifest)[1]["content"])
    scope = user["progressScope"]
    assert scope["available"] is True
    assert scope["boundSceneTaskIds"] == ["task-bound"]
    assert scope["notPreviouslyCompletedTaskIds"] == ["task-bound", "task-other"]
    stage = scope["stages"][0]
    assert stage["notPreviouslyCompletedTaskIds"] == ["task-bound", "task-other"]
    assert [task["boundToCurrentOutline"] for task in stage["requiredSceneTasks"]] == [True, False]
    assert all(task["confirmedStatus"] == "not_confirmed_completed" for task in stage["requiredSceneTasks"])
    assert stage["requiredSceneTasks"][1]["completionEvidence"] == "取得第二条记录"
    assert (planning, outline) == original
    assert user["planningContext"] == planning and user["outlineContext"] == outline

    canonical = {"actualProgress": [{
        "field_path": "plot.progress.scene_task.task-other",
        "payload": {"targetType": "scene_task", "targetId": "task-other", "status": "completed"},
    }]}
    completed = json.loads(builder(manifest=_manifest(
        planning_context=planning, outline_context=outline, canon_context=canonical,
    ))[1]["content"])["progressScope"]
    assert completed["notPreviouslyCompletedTaskIds"] == ["task-bound"]
    assert completed["stages"][0]["requiredSceneTasks"][1]["confirmedStatus"] == "completed"
    assert completed["confirmedStatus"] == "not_confirmed_completed"

    canonical["actualProgress"][0]["field_path"] = "plot.progress.scene_task.different-task"
    mismatched = json.loads(builder(manifest=_manifest(
        planning_context=planning, outline_context=outline, canon_context=canonical,
    ))[1]["content"])["progressScope"]
    assert mismatched["notPreviouslyCompletedTaskIds"] == ["task-bound", "task-other"]


def test_extraction_prompt_requires_explicit_child_completion_before_parent_completion():
    system = json.loads(build_extraction_messages(manifest=_manifest())[0]["content"])
    rules = " ".join(system["rules"])
    assert "Finishing this chapter or every bound task does not complete a stage or story block" in rules
    assert "scene_task completed event in this same ChangeSet" in rules
    assert "Never invent child completion" in rules
    assert "started/advanced" in rules
