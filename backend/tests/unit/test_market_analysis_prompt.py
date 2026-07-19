from __future__ import annotations

import importlib
import json

import pytest


SNAPSHOT_A = "00000000-0000-0000-0000-000000000201"
SNAPSHOT_B = "00000000-0000-0000-0000-000000000202"


def _feature():
    try:
        domain = importlib.import_module("backend.domain.market_analysis")
        prompt = importlib.import_module("backend.prompts.market_analysis")
    except ModuleNotFoundError:
        pytest.fail("frozen market analysis feature module is missing")
    return domain, prompt


def _snapshot(snapshot_id: str, *, title: str = "雾港天文钟") -> dict:
    return {
        "id": snapshot_id,
        "source_id": "00000000-0000-0000-0000-000000000101",
        "captured_at": 1_721_000_000_000,
        "platform": "qidian",
        "ranking_name": "newsign",
        "category": "male",
        "source_url": "https://www.qidian.com/rank/newsign/",
        "content_hash": "a" * 64,
        "manifest_hash": "b" * 64,
        "entry_count": 1,
        "entries": (
            {
                "rank": 1,
                "title": title,
                "author": "合成作者甲",
                "category": "玄幻",
                "work_url": "https://www.qidian.com/book/900000001/",
                "public_metrics": {"weeklyRecommendations": 321},
                "raw": "PRIVATE_RAW_ENTRY_SENTINEL",
            },
        ),
        "raw_html": "PRIVATE_RAW_SNAPSHOT_SENTINEL",
    }


def _valid_payload() -> dict:
    statement = {
        "text": "榜单当前由穿越升级题材占据较多位置。",
        "snapshotIds": [SNAPSHOT_A],
        "inference": False,
    }
    inference = {
        "text": "穿越与群像经营的组合可能仍有增长空间。",
        "snapshotIds": [SNAPSHOT_A, SNAPSHOT_B],
        "inference": True,
    }
    return {
        "currentHeat": [statement],
        "growthDirections": [inference],
        "crowding": [statement],
        "opportunities": [inference],
        "uncertainties": [
            {
                "text": "公开榜单只反映当前截面，不能证明长期趋势。",
                "snapshotIds": [SNAPSHOT_B],
                "inference": False,
            }
        ],
        "sourceCoverage": {
            "snapshotIds": [SNAPSHOT_A, SNAPSHOT_B],
            "summary": "覆盖两份冻结公开榜单快照。",
        },
    }


def test_analysis_contract_is_strict_cited_and_marks_predictions_as_inference():
    domain, _ = _feature()
    result = domain.parse_market_analysis(
        _valid_payload(),
        snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
    )

    assert set(result.model_dump(mode="json", by_alias=True)) == {
        "currentHeat",
        "growthDirections",
        "crowding",
        "opportunities",
        "uncertainties",
        "sourceCoverage",
    }
    assert result.growth_directions[0].inference is True
    assert result.opportunities[0].inference is True
    assert result.source_coverage.snapshot_ids == (SNAPSHOT_A, SNAPSHOT_B)

    bad = _valid_payload()
    bad["growthDirections"][0]["inference"] = False
    with pytest.raises(ValueError, match="invalid market analysis"):
        domain.parse_market_analysis(
            bad,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        )

    bad = _valid_payload()
    bad["currentHeat"][0]["snapshotIds"] = ["outside-frozen-manifest"]
    with pytest.raises(ValueError, match="invalid market analysis"):
        domain.parse_market_analysis(
            bad,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        )

    bad = _valid_payload()
    bad["sourceCoverage"]["snapshotIds"] = [SNAPSHOT_A]
    with pytest.raises(ValueError, match="invalid market analysis"):
        domain.parse_market_analysis(
            bad,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        )

    bad = {**_valid_payload(), "provider": "PRIVATE_PROVIDER"}
    with pytest.raises(ValueError, match="invalid market analysis"):
        domain.parse_market_analysis(
            bad,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        )


def test_prompt_contains_only_bounded_normalized_snapshot_projection():
    _, prompt = _feature()
    many_entries = tuple(
        {
            "rank": index,
            "title": f"作品{index}",
            "author": f"作者{index}",
            "category": "玄幻",
            "work_url": f"https://www.qidian.com/book/{900000000 + index}/",
            "public_metrics": {"weeklyRecommendations": index},
        }
        for index in range(1, 101)
    )
    snapshot = {**_snapshot(SNAPSHOT_A), "entry_count": 100, "entries": many_entries}

    messages = prompt.build_market_analysis_messages((snapshot,))
    rendered = json.dumps(messages, ensure_ascii=False)

    assert len(messages) == 2
    assert SNAPSHOT_A in rendered
    assert "作品20" in rendered
    assert "作品21" not in rendered
    assert "PRIVATE_RAW_ENTRY_SENTINEL" not in rendered
    assert "PRIVATE_RAW_SNAPSHOT_SENTINEL" not in rendered
    assert "raw_html" not in rendered
    assert len(rendered.encode("utf-8")) <= prompt.MAX_MARKET_ANALYSIS_PROMPT_BYTES


def test_prompt_rejects_unbounded_or_duplicate_snapshot_inputs():
    _, prompt = _feature()
    snapshots = tuple(
        _snapshot(f"00000000-0000-0000-0000-{index:012d}")
        for index in range(1, 6)
    )
    with pytest.raises(ValueError, match="bounded"):
        prompt.build_market_analysis_messages(snapshots)
    with pytest.raises(ValueError, match="unique"):
        prompt.build_market_analysis_messages(
            (_snapshot(SNAPSHOT_A), _snapshot(SNAPSHOT_A))
        )
