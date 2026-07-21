from __future__ import annotations

import importlib
import json

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.market_analysis import parse_market_analysis


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
SNAPSHOT_ID = "00000000-0000-0000-0000-000000000201"
ANALYSIS_ID = "00000000-0000-0000-0000-000000000301"


def _feature():
    try:
        domain = importlib.import_module("backend.domain.seeds")
        prompt = importlib.import_module("backend.prompts.seed")
    except (AttributeError, ModuleNotFoundError):
        pytest.fail("seed inspiration prompt feature is missing")
    return domain, prompt


def _inputs() -> dict:
    return {
        "snapshots": (
            {
                "id": SNAPSHOT_ID,
                "source_id": "00000000-0000-0000-0000-000000000101",
                "content_hash": "a" * 64,
                "manifest_hash": "b" * 64,
                "captured_at": 1_721_000_000_000,
                "platform": "qidian",
                "ranking_name": "newsign",
                "category": "male",
                "source_url": "https://www.qidian.com/rank/newsign/",
                "entries": tuple(
                    {
                        "rank": index,
                        "title": f"公开作品{index}",
                        "author": f"公开作者{index}",
                        "category": "玄幻",
                        "public_metrics": {"weeklyRecommendations": index},
                        "work_url": (
                            f"https://www.qidian.com/book/{900000000 + index}/"
                        ),
                    }
                    for index in range(1, 31)
                ),
                "raw_html": "PRIVATE_RAW_SNAPSHOT_SENTINEL",
            },
        ),
        "analysis": {
            "id": ANALYSIS_ID,
            "result_hash": "c" * 64,
            "analysis_json": {
                "currentHeat": [
                    {
                        "text": "穿越升级题材处于当前热区。",
                        "snapshotIds": [SNAPSHOT_ID],
                        "inference": False,
                    }
                ],
                "growthDirections": [],
                "crowding": [],
                "opportunities": [],
                "uncertainties": [],
                "sourceCoverage": {
                    "snapshotIds": [SNAPSHOT_ID],
                    "summary": "一份冻结公开榜单快照。",
                },
            },
        },
    }


def test_prompt_uses_bounded_current_transcript_and_normalized_frozen_evidence():
    domain, prompt = _feature()
    transcript = (
        domain.SeedChatTurn(role="user", content="我想写穿越到明代的群像故事。"),
        domain.SeedChatTurn(role="assistant", content="可以从知识与权力冲突切入。"),
        domain.SeedChatTurn(role="user", content="主角不要一开始就无敌。"),
    )

    messages = prompt.build_seed_inspiration_messages(
        transcript=transcript,
        inputs=_inputs(),
    )
    rendered = json.dumps(messages, ensure_ascii=False)

    assert len(messages) == 2
    assert "我想写穿越到明代的群像故事" in rendered
    assert SNAPSHOT_ID in rendered
    assert ANALYSIS_ID in rendered
    assert "公开作品20" in rendered
    assert "公开作品21" not in rendered
    assert "PRIVATE_RAW_SNAPSHOT_SENTINEL" not in rendered
    assert "work_url" not in rendered
    assert "source_url" not in rendered
    assert len(rendered.encode("utf-8")) <= prompt.MAX_SEED_PROMPT_BYTES


def test_prompt_normalizes_the_canonical_persisted_market_analysis_shape():
    domain, prompt = _feature()
    inputs = _inputs()
    parsed = parse_market_analysis(
        inputs["analysis"]["analysis_json"],
        snapshot_ids=(SNAPSHOT_ID,),
    )
    inputs["analysis"]["analysis_json"] = canonical_json(parsed)

    messages = prompt.build_seed_inspiration_messages(
        transcript=(domain.SeedChatTurn(role="user", content="给我一个方向"),),
        inputs=inputs,
    )
    evidence = json.loads(messages[1]["content"])

    assert evidence["analysis"]["result"]["sourceCoverage"] == {
        "snapshotIds": [SNAPSHOT_ID],
        "summary": "一份冻结公开榜单快照。",
    }


def test_prompt_rejects_empty_unbounded_or_mismatched_inputs():
    domain, prompt = _feature()
    turn = domain.SeedChatTurn(role="user", content="给我一个方向")

    with pytest.raises(ValueError, match="transcript"):
        prompt.build_seed_inspiration_messages(transcript=(), inputs=_inputs())

    mismatched = _inputs()
    mismatched["analysis"]["analysis_json"]["sourceCoverage"][
        "snapshotIds"
    ] = ["outside"]
    with pytest.raises(ValueError, match="frozen"):
        prompt.build_seed_inspiration_messages(
            transcript=(turn,),
            inputs=mismatched,
        )

    with pytest.raises(ValueError):
        domain.SeedChatTurn(role="user", content="x" * 2_001)


def test_assistant_turn_parser_is_exact_bounded_and_rejects_secret_shaped_text():
    domain, _ = _feature()

    parsed = domain.parse_seed_assistant_turn(
        {"role": "assistant", "content": "可以把知识优势拆成三次递进兑现。"}
    )
    assert parsed.role == "assistant"

    for value in (
        {"role": "user", "content": "越权"},
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "安全", "model": "forged"},
        {"role": "assistant", "content": "apiKey=PRIVATE"},
        {"role": "assistant", "content": "baseURL=https://private.invalid"},
    ):
        with pytest.raises(ValueError, match="assistant turn"):
            domain.parse_seed_assistant_turn(value)


def test_stored_provenance_rejects_hash_valid_but_kind_inconsistent_document():
    domain, _ = _feature()
    facts = {
        "kind": "manual",
        "snapshots": [
            {
                "id": SNAPSHOT_ID,
                "hash": "a" * 64,
                "sourceId": "source-1",
                "sourceURL": "https://www.qidian.com/rank/newsign/",
                "capturedAt": 1,
            }
        ],
        "analysis": None,
        "inspirationAttempt": None,
        "publicNotes": [],
    }
    document = {
        "title": "标题",
        "genre": "玄幻",
        "logline": "一句话",
        "protagonist": "主角",
        "desire": "欲望",
        "coreConflict": "冲突",
        "worldPressure": "压力",
        "openingHook": "开场",
        "differentiation": "差异",
        "_provenance": {
            **facts,
            "provenanceHash": canonical_hash(facts),
        },
    }

    with pytest.raises(ValueError):
        domain.decode_seed_revision(document)
