from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "market"
NOW = 1_721_000_000_000


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        return self.response


def _response(body: bytes, *, url: str):
    from backend.gateways.market_sources.base import TransportResponse

    return TransportResponse(
        status_code=200,
        url=url,
        headers={"content-type": "text/html; charset=utf-8"},
        body=body,
    )


def _policy(*, origin: str, prefixes: tuple[str, ...]):
    from backend.domain.market_sources import SourcePolicy

    return SourcePolicy(
        status="verified_public",
        checkedAt=NOW - 1_000,
        evidenceURL=f"{origin}{prefixes[0]}",
        evidenceHash="a" * 64,
        allowedOrigins=(origin,),
        pathPrefixes=prefixes,
        requestIntervalSeconds=3600,
        policyVersion="qualification-test-v1",
        enabled=False,
    )


async def _fetch(adapter_type, fixture: str, policy):
    from backend.domain.json_contracts import canonical_hash

    transport = RecordingTransport(
        _response((FIXTURES / fixture).read_bytes(), url=adapter_type.source_url)
    )
    snapshot = await adapter_type(transport).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )
    return snapshot, transport


@pytest.mark.asyncio
async def test_heiyan_daily_recommendation_is_strict_single_page_first_ten():
    from backend.gateways.market_sources.heiyan_public_rank import HeiyanPublicRankAdapter

    policy = _policy(
        origin="https://www.heiyan.com",
        prefixes=("/top/monthly/day", "/book/"),
    )
    snapshot, transport = await _fetch(
        HeiyanPublicRankAdapter,
        "heiyan_daily_recommendation_official_shape.html",
        policy,
    )

    assert HeiyanPublicRankAdapter.source_url == "https://www.heiyan.com/top/monthly/day?rank=13"
    assert HeiyanPublicRankAdapter.adapter_version == "heiyan-public-rank-v2"
    assert snapshot.ranking_name == "daily_recommendation"
    assert len(snapshot.entries) == 10
    assert [entry.rank for entry in snapshot.entries] == list(range(1, 11))
    assert snapshot.entries[0].title == "作品一"
    assert snapshot.entries[0].author == "作者一"
    assert snapshot.entries[0].category == "玄幻"
    assert snapshot.entries[0].work_url == "https://www.heiyan.com/book/101"
    assert dict(snapshot.entries[0].public_metrics) == {
        "recommendation": "100 推荐",
        "updatedAt": "今天 10:01",
    }
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.replace(
            "</body>",
            '<div class="mod mod-clean update-list"><div class="bd">'
            "<table></table></div></div></body>",
        ),
        lambda value: value.replace('data-collect-index="10"', 'data-collect-index="11"', 1),
        lambda value: value.replace('class="author">作者十', 'class="author">', 1),
        lambda value: value.replace('class="tag">游戏', 'class="tag">', 1),
        lambda value: value.replace('href="/book/110"', 'href="https://evil.example/book/110"', 1),
        lambda value: value.replace('>作品十<', '>作品\ue000十<', 1),
        lambda value: value.replace("</tbody>", "<tr><td>无效尾行</td></tr></tbody>", 1),
    ),
)
async def test_heiyan_rejects_ambiguity_and_invalid_rows(mutation):
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.heiyan_public_rank import HeiyanPublicRankAdapter

    text = mutation(
        (FIXTURES / "heiyan_daily_recommendation_official_shape.html").read_text(
            encoding="utf-8"
        )
    )
    policy = _policy(
        origin="https://www.heiyan.com",
        prefixes=("/top/monthly/day", "/book/"),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await HeiyanPublicRankAdapter(
            RecordingTransport(
                _response(text.encode("utf-8"), url=HeiyanPublicRankAdapter.source_url)
            )
        ).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_readnovel_original_monthly_ticket_parses_twenty_rows_without_invented_metrics():
    from backend.gateways.market_sources.readnovel_public_rank import ReadNovelPublicRankAdapter

    policy = _policy(
        origin="https://www.readnovel.com",
        prefixes=("/rank/ywyuepiao", "/book/"),
    )
    snapshot, transport = await _fetch(
        ReadNovelPublicRankAdapter,
        "readnovel_monthly_ticket_official_shape.html",
        policy,
    )

    assert snapshot.platform == "readnovel"
    assert ReadNovelPublicRankAdapter.adapter_version == "readnovel-public-rank-v2"
    assert snapshot.ranking_name == "monthly_ticket"
    assert snapshot.category == "female"
    assert len(snapshot.entries) == 20
    assert [entry.rank for entry in snapshot.entries] == list(range(1, 21))
    assert snapshot.entries[0].work_url == "https://www.readnovel.com/book/201"
    assert snapshot.entries[-1].work_url == "https://www.readnovel.com/book/220"
    assert all(dict(entry.public_metrics) == {} for entry in snapshot.entries)
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_readnovel_rejects_obsolete_h2_title_shape_without_fallback():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.readnovel_public_rank import ReadNovelPublicRankAdapter

    text = (
        FIXTURES / "readnovel_monthly_ticket_official_shape.html"
    ).read_text(encoding="utf-8").replace("<h4>", "<h2>").replace("</h4>", "</h2>")
    policy = _policy(
        origin="https://www.readnovel.com",
        prefixes=("/rank/ywyuepiao", "/book/"),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await ReadNovelPublicRankAdapter(
            RecordingTransport(
                _response(text.encode("utf-8"), url=ReadNovelPublicRankAdapter.source_url)
            )
        ).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_readnovel_rank_is_derived_from_no_class_not_visible_text():
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.readnovel_public_rank import ReadNovelPublicRankAdapter

    text = (
        FIXTURES / "readnovel_monthly_ticket_official_shape.html"
    ).read_text(encoding="utf-8").replace(
        'class="rank-tag no1">1<',
        'class="rank-tag no1"><',
        1,
    )
    policy = _policy(
        origin="https://www.readnovel.com",
        prefixes=("/rank/ywyuepiao", "/book/"),
    )
    snapshot = await ReadNovelPublicRankAdapter(
        RecordingTransport(
            _response(text.encode("utf-8"), url=ReadNovelPublicRankAdapter.source_url)
        )
    ).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert snapshot.entries[0].rank == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.replace('class="rank-view-list"', 'class="missing"', 1),
        lambda value: value.replace("no10\">10", "no11\">10", 1),
        lambda value: value.replace("作者十", "", 1),
        lambda value: value.replace("/category/youxi\">游戏", "/other/youxi\">游戏", 1),
        lambda value: value.replace("/book/210", "https://evil.example/book/210", 1),
        lambda value: value.replace("作品十", "作品\ue000十", 1),
    ),
)
async def test_readnovel_rejects_unknown_shape_and_invalid_rows(mutation):
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.readnovel_public_rank import ReadNovelPublicRankAdapter

    text = mutation(
        (FIXTURES / "readnovel_monthly_ticket_official_shape.html").read_text(
            encoding="utf-8"
        )
    )
    policy = _policy(
        origin="https://www.readnovel.com",
        prefixes=("/rank/ywyuepiao", "/book/"),
    )
    transport = RecordingTransport(
        _response(text.encode("utf-8"), url=ReadNovelPublicRankAdapter.source_url)
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await ReadNovelPublicRankAdapter(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code in {"MARKET_PAGE_INCOMPLETE", "MARKET_HTML_UNKNOWN"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trailing_content",
    (
        '<li><span class="rank-tag no21">21</span><div class="book-mid-info">'
        '<h4><a href="/book/221">作品二十一</a></h4><p class="author">'
        '<a class="name">作者二十一</a><a href="/category/xuanhuan">玄幻</a>'
        "</p></div></li>",
        '<li><span class="rank-tag no21">21</span><div class="book-mid-info">坏尾行</div></li>',
        '<div class="unexpected-row">坏尾行</div>',
    ),
)
async def test_readnovel_rejects_every_observed_trailing_direct_row(trailing_content):
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.readnovel_public_rank import (
        ReadNovelPublicRankAdapter,
    )

    text = (
        FIXTURES / "readnovel_monthly_ticket_official_shape.html"
    ).read_text(encoding="utf-8").replace("</ul>", f"{trailing_content}</ul>", 1)
    policy = _policy(
        origin="https://www.readnovel.com",
        prefixes=("/rank/ywyuepiao", "/book/"),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await ReadNovelPublicRankAdapter(
            RecordingTransport(
                _response(text.encode("utf-8"), url=ReadNovelPublicRankAdapter.source_url)
            )
        ).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_readnovel_rejects_duplicate_inner_book_list():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.readnovel_public_rank import (
        ReadNovelPublicRankAdapter,
    )

    text = (
        FIXTURES / "readnovel_monthly_ticket_official_shape.html"
    ).read_text(encoding="utf-8").replace(
        "</ul></div></div></div>",
        '</ul></div><div class="book-img-text"><ul><li>duplicate</li></ul>'
        "</div></div></div>",
        1,
    )
    policy = _policy(
        origin="https://www.readnovel.com",
        prefixes=("/rank/ywyuepiao", "/book/"),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await ReadNovelPublicRankAdapter(
            RecordingTransport(
                _response(text.encode("utf-8"), url=ReadNovelPublicRankAdapter.source_url)
            )
        ).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_readnovel_rejects_duplicate_direct_ul_inside_book_list():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.readnovel_public_rank import (
        ReadNovelPublicRankAdapter,
    )

    text = (
        FIXTURES / "readnovel_monthly_ticket_official_shape.html"
    ).read_text(encoding="utf-8").replace(
        "</ul></div></div></div>",
        "</ul><ul><li>duplicate</li></ul></div></div></div>",
        1,
    )
    policy = _policy(
        origin="https://www.readnovel.com",
        prefixes=("/rank/ywyuepiao", "/book/"),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await ReadNovelPublicRankAdapter(
            RecordingTransport(
                _response(text.encode("utf-8"), url=ReadNovelPublicRankAdapter.source_url)
            )
        ).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_xxsy_xiaoxiang_ticket_parses_exact_twenty_direct_cards():
    from bs4 import BeautifulSoup

    from backend.gateways.market_sources.xxsy_public_rank import XXSYPublicRankAdapter

    policy = _policy(
        origin="https://www.xxsy.net",
        prefixes=("/rank/xxyuepiao", "/book/"),
    )
    snapshot, transport = await _fetch(
        XXSYPublicRankAdapter,
        "xxsy_xiaoxiang_ticket_official_shape.html",
        policy,
    )

    assert XXSYPublicRankAdapter.source_url == "https://www.xxsy.net/rank/xxyuepiao"
    assert snapshot.platform == "xxsy"
    assert snapshot.ranking_name == "xiaoxiang_ticket"
    assert snapshot.category == "female"
    assert len(snapshot.entries) == 20
    assert [entry.rank for entry in snapshot.entries] == list(range(1, 21))
    assert snapshot.entries[0].title == "作品一"
    assert snapshot.entries[0].author == "作者一"
    assert snapshot.entries[0].category == "现代言情/都市"
    assert snapshot.entries[0].work_url == "https://www.xxsy.net/book/301"
    assert dict(snapshot.entries[0].public_metrics) == {"wordCount": "100万字"}
    assert len(transport.requests) == 1
    fixture = (FIXTURES / "xxsy_xiaoxiang_ticket_official_shape.html").read_text(
        encoding="utf-8"
    )
    assert BeautifulSoup(fixture, "html.parser").select(".rank-page-shown.flex") == []


@pytest.mark.asyncio
async def test_xxsy_card_injected_heading_cannot_replace_missing_real_heading():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.xxsy_public_rank import XXSYPublicRankAdapter

    text = (
        FIXTURES / "xxsy_xiaoxiang_ticket_official_shape.html"
    ).read_text(encoding="utf-8").replace(
        '<h3 class="font-source text-t1">潇湘票榜</h3>',
        '<h3 class="font-source text-t1"></h3>',
        1,
    ).replace(
        '<div class="info"><div class="text-t34">作品一</div>',
        '<div class="info"><h3 class="font-source text-t1">潇湘票榜</h3>'
        '<div class="text-t34">作品一</div>',
        1,
    )
    policy = _policy(
        origin="https://www.xxsy.net",
        prefixes=("/rank/xxyuepiao", "/book/"),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await XXSYPublicRankAdapter(
            RecordingTransport(
                _response(text.encode("utf-8"), url=XXSYPublicRankAdapter.source_url)
            )
        ).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.replace(
            "</body>",
            '<div class="flex flex-1 flex-wrap relative min-h-328px ml-30px">'
            "duplicate</div></body>",
            1,
        ),
        lambda value: value.replace(
            '<div class="flex flex-wrap relative">',
            '<div class="flex flex-wrap relative"></div>'
            '<div class="flex flex-wrap relative">',
            1,
        ),
        lambda value: value.replace(
            '<i class="block line"></i>',
            '<i class="block line">unexpected</i>',
            1,
        ),
        lambda value: value.replace(
            "  </div>\n</div>\n</body>",
            '<a class="flex mt-24px mr-16px w-50 page-one" href="/book/321" '
            'title="作品二十一"><div class="info"><div class="text-t34">作品二十一</div>'
            '<div class="row1">作者二十一 · 1万字 · 短篇</div></div></a>\n  </div>\n</div>\n</body>',
            1,
        ),
        lambda value: value.replace(
            'href="/book/320"', 'href="/book/320?from=rank"', 1
        ),
        lambda value: value.replace(
            "作者二十 · 11万字 · 现实生活", "作者二十 - 11万字 - 现实生活", 1
        ),
        lambda value: value.replace('title="作品二十"', 'title="不一致"', 1),
        lambda value: value.replace(
            '<div class="text-t34">作品二十',
            '<div class="text-t34" hidden>作品二十',
            1,
        ),
        lambda value: value.replace("作者二十 ·", "作者\ue000二十 ·", 1),
        lambda value: value.replace("作者二十 ·", "作者\x01二十 ·", 1),
    ),
)
async def test_xxsy_rejects_ambiguous_or_invalid_page_contract(mutation):
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.xxsy_public_rank import XXSYPublicRankAdapter

    text = mutation(
        (FIXTURES / "xxsy_xiaoxiang_ticket_official_shape.html").read_text(
            encoding="utf-8"
        )
    )
    policy = _policy(
        origin="https://www.xxsy.net",
        prefixes=("/rank/xxyuepiao", "/book/"),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await XXSYPublicRankAdapter(
            RecordingTransport(
                _response(text.encode("utf-8"), url=XXSYPublicRankAdapter.source_url)
            )
        ).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code in {"MARKET_PAGE_INCOMPLETE", "MARKET_HTML_UNKNOWN"}


def test_registry_and_package_use_five_qualified_sources():
    from backend.domain.market_sources import load_market_source_package
    from backend.gateways.market_sources.registry import candidate_adapter_factories

    manifest = (
        Path(__file__).resolve().parents[2]
        / "assets"
        / "market-sources-v1.1.0"
        / "manifest.json"
    )
    package = load_market_source_package(manifest)
    verified = {
        source.stable_key: source.display_name
        for source in package.sources
        if source.policy.status == "verified_public"
    }

    assert {"readnovel_public_rank", "xxsy_public_rank"} <= set(candidate_adapter_factories())
    assert verified == {
        "qq-reading.male-popular": "QQ 阅读男生人气榜",
        "qimao.public-catalog": "七猫男生更新榜",
        "heiyan.daily-recommendation": "黑岩每日推荐榜",
        "readnovel.original-monthly-ticket": "小说阅读网原创月票榜",
        "xxsy.xiaoxiang-ticket": "潇湘票榜",
    }
    assert len(package.sources) == 10
    assert next(
        source for source in package.sources
        if source.stable_key == "jjwxc.quarterly-score"
    ).policy.status == "manual_only"
    assert next(
        source for source in package.sources
        if source.stable_key == "zongheng.monthly"
    ).policy.status == "manual_only"
