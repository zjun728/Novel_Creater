from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.topics import (
    TopicAssistantResult,
    TopicCandidatePayload,
    TopicCandidateSuggestion,
    TopicDirectionPayload,
    TopicDirectionSuggestion,
    TopicEvidenceRef,
    TopicFailure,
    TopicMessage,
    TopicSubjectRef,
)


DIRECTION = {
    "title": "小城民俗经营悬疑",
    "genreOpportunity": "民俗悬疑稳定，经营成长切入稀缺。",
    "targetAudience": "偏爱规则谜题和稳步经营成长的长篇读者。",
    "readerPromise": "每个地方旧俗既是谜题也是可经营资源。",
    "differentiation": "用地方治理和产业积累替代单纯升级打怪。",
    "longFormPotential": "县、府、州、天下四级扩张可支撑二百万字。",
    "risks": "避免堆砌民俗设定和重复解谜。",
    "evidenceSummary": "公开榜单只作选题参考。",
}

CANDIDATE = {
    "title": "典镇山河",
    "genre": "东方奇幻",
    "logline": "衰败典吏以地方香火重建失序山河。",
    "targetAudience": "偏爱经营、制度成长和群像推进的男频长篇读者。",
    "protagonist": "被贬到边县的年轻典吏。",
    "desire": "守住县城并查明山河失序的根源。",
    "coreConflict": "重建秩序必须借助正在吞噬人心的旧神规则。",
    "worldPressure": "香火衰败、地方割据与旧神复苏同步加剧。",
    "openingHook": "主角上任当夜，县志中被抹去的村庄重新出现。",
    "differentiation": "以基层治理和制度建设承载东方诡异升级。",
    "storyPromise": "每次治理都解决现实困局，也揭开更大的山河旧账。",
    "longFormPotential": "从一县扩展至一府、一州和天下秩序重建。",
    "marketBasis": "引用公开榜单只证明读者兴趣。",
}


def test_direction_requires_the_exact_eight_author_fields():
    assert set(TopicDirectionPayload.model_fields) == {
        "title",
        "genre_opportunity",
        "target_audience",
        "reader_promise",
        "differentiation",
        "long_form_potential",
        "risks",
        "evidence_summary",
    }
    assert TopicDirectionPayload.model_validate(
        DIRECTION,
        strict=True,
    ).model_dump(mode="json", by_alias=True) == DIRECTION


def test_candidate_requires_the_exact_thirteen_author_fields():
    assert set(TopicCandidatePayload.model_fields) == {
        "title",
        "genre",
        "logline",
        "target_audience",
        "protagonist",
        "desire",
        "core_conflict",
        "world_pressure",
        "opening_hook",
        "differentiation",
        "story_promise",
        "long_form_potential",
        "market_basis",
    }
    assert TopicCandidatePayload.model_validate(
        CANDIDATE,
        strict=True,
    ).model_dump(mode="json", by_alias=True) == CANDIDATE


@pytest.mark.parametrize("payload_class,payload", [
    (TopicDirectionPayload, DIRECTION),
    (TopicCandidatePayload, CANDIDATE),
])
def test_author_payloads_reject_missing_extra_blank_and_control_text(
    payload_class,
    payload,
):
    first = next(iter(payload))
    with pytest.raises(ValidationError):
        payload_class.model_validate(
            {key: value for key, value in payload.items() if key != first},
            strict=True,
        )
    with pytest.raises(ValidationError):
        payload_class.model_validate({**payload, "unexpected": "x"}, strict=True)
    with pytest.raises(ValidationError):
        payload_class.model_validate({**payload, first: "   "}, strict=True)
    with pytest.raises(ValidationError):
        payload_class.model_validate({**payload, first: "bad\x00text"}, strict=True)


def test_ai_suggestions_are_not_saved_authorities():
    assert set(TopicDirectionSuggestion.model_fields) == set(
        TopicDirectionPayload.model_fields
    )
    assert set(TopicCandidateSuggestion.model_fields) == set(
        TopicCandidatePayload.model_fields
    )
    forbidden = {"id", "version", "status", "content_hash", "current_version"}
    assert forbidden.isdisjoint(TopicDirectionSuggestion.model_fields)
    assert forbidden.isdisjoint(TopicCandidateSuggestion.model_fields)

    result = TopicAssistantResult.model_validate(
        {
            "reply": "这个方向可以先强化长期矛盾。",
            "directionSuggestions": [DIRECTION],
            "candidateSuggestions": [CANDIDATE],
        },
        strict=True,
    )
    assert isinstance(result.direction_suggestions, tuple)
    assert isinstance(result.candidate_suggestions, tuple)
    with pytest.raises(ValidationError):
        result.reply = "changed"


def test_evidence_reference_requires_stable_id_and_hash():
    value = TopicEvidenceRef.model_validate(
        {"snapshotId": "snapshot-1", "contentHash": "a" * 64},
        strict=True,
    )
    assert value.snapshot_id == "snapshot-1"

    for invalid in (
        {"snapshotId": "", "contentHash": "a" * 64},
        {"snapshotId": "snapshot-1", "contentHash": ""},
        {"snapshotId": "snapshot-1", "contentHash": "A" * 64},
    ):
        with pytest.raises(ValidationError):
            TopicEvidenceRef.model_validate(invalid, strict=True)


def test_subject_reference_is_one_exact_direction_or_candidate_version():
    direction = TopicSubjectRef.model_validate(
        {
            "kind": "direction",
            "id": "direction-1",
            "version": 2,
            "contentHash": "b" * 64,
        },
        strict=True,
    )
    assert direction.kind == "direction"

    with pytest.raises(ValidationError):
        TopicSubjectRef.model_validate(
            {
                "kind": "seed",
                "id": "seed-1",
                "version": 1,
                "contentHash": "b" * 64,
            },
            strict=True,
        )
    with pytest.raises(ValidationError):
        TopicSubjectRef.model_validate(
            {
                "kind": "candidate",
                "id": "candidate-1",
                "version": 0,
                "contentHash": "b" * 64,
            },
            strict=True,
        )


def test_discussion_message_accepts_author_text_but_remains_bounded():
    assert TopicMessage(role="user", content="我想写基层治理题材。").content
    assert TopicMessage(role="assistant", content="可以从县域秩序切入。").content
    with pytest.raises(ValidationError):
        TopicMessage(role="system", content="hidden")
    with pytest.raises(ValidationError):
        TopicMessage(role="user", content="x" * 20_001)
    with pytest.raises(ValidationError):
        TopicMessage(role="user", content="line\x00break")


@pytest.mark.parametrize(
    "code,status",
    [
        ("TOPIC_NOT_FOUND", 404),
        ("TOPIC_PROVIDER_NOT_READY", 422),
        ("TOPIC_PROVIDER_FAILED", 503),
        ("TOPIC_INVALID_RESPONSE", 502),
        ("TOPIC_REQUEST_CONFLICT", 409),
        ("TOPIC_REQUEST_IN_PROGRESS", 409),
        ("TOPIC_OUTCOME_UNKNOWN", 503),
        ("TOPIC_VERSION_CONFLICT", 409),
        ("TOPIC_CANDIDATE_ARCHIVED", 409),
    ],
)
def test_topic_failures_have_fixed_public_codes(code, status):
    failure = TopicFailure(code)
    assert failure.code == code
    assert failure.status_code == status
    assert "api" not in failure.message.casefold()


def test_topic_failure_rejects_unapproved_dynamic_codes():
    with pytest.raises(TypeError):
        TopicFailure("provider said secret text")
