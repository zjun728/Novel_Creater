from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
import re

import pytest
from pydantic import ValidationError


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "market"
NOW = 1_721_000_000_000


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class RankAndDetailTransport:
    """Local-only response sequence for detail-enriched rank adapters."""

    def __init__(self, *, rank_url, rank_body, detail_body_for_url):
        self.rank_url = rank_url
        self.rank_body = rank_body
        self.detail_body_for_url = detail_body_for_url
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        if request.url == self.rank_url:
            return _response(self.rank_body, url=request.url)
        body = self.detail_body_for_url(request.url)
        if isinstance(body, BaseException):
            raise body
        return _response(body, url=request.url)


def _policy(
    *,
    platform: str,
    status: str = "verified_public",
    checked_at=NOW - 1_000,
    origins: tuple[str, ...] | None = None,
    prefixes: tuple[str, ...] | None = None,
):
    from backend.domain.market_sources import SourcePolicy

    if platform == "qidian":
        default_origins = ("https://www.qidian.com",)
        default_prefixes = ("/rank/newsign/",)
    elif platform == "qimao":
        default_origins = ("https://www.qimao.com",)
        default_prefixes = ("/paihang/boy/update/date/",)
    elif platform == "jjwxc":
        default_origins = ("https://www.jjwxc.net",)
        default_prefixes = ("/topten.php",)
    elif platform == "zongheng":
        default_origins = ("https://www.zongheng.com",)
        default_prefixes = ("/rank", "/detail/")
    elif platform == "heiyan":
        default_origins = ("https://www.heiyan.com",)
        default_prefixes = ("/top/", "/book/")
    elif platform == "fanqie":
        default_origins = ("https://fanqienovel.com",)
        default_prefixes = ("/rank/1",)
    elif platform == "17k":
        default_origins = ("https://www.17k.com",)
        default_prefixes = ("/top/",)
    elif platform == "hongxiu":
        default_origins = ("https://www.hongxiu.com",)
        default_prefixes = ("/rank",)
    else:
        default_origins = ("https://book.qq.com",)
        default_prefixes = ("/book-rank",)
    return SourcePolicy(
        status=status,
        checkedAt=checked_at,
        evidenceURL="https://evidence.example/public-policy",
        evidenceHash="a" * 64,
        allowedOrigins=origins if origins is not None else default_origins,
        pathPrefixes=prefixes if prefixes is not None else default_prefixes,
        requestIntervalSeconds=3600,
        policyVersion="public-rank-policy-v1",
        enabled=False,
    )


def _response(body: bytes, *, url: str, status=200, headers=None):
    from backend.gateways.market_sources.base import TransportResponse

    return TransportResponse(
        status_code=status,
        url=url,
        headers=(
            {"content-type": "text/html; charset=utf-8"}
            if headers is None
            else headers
        ),
        body=body,
    )


def _candidate_rank_html(
    platform: str,
    *,
    href_for_rank=None,
    extra_field: str = "",
    extra_container: str = "",
) -> str:
    if platform == "fanqie":
        opening = '<section class="fanqie-authoritative">'
        closing = "</section>"
        href = lambda rank: f"/page/{rank}"
    elif platform == "17k":
        opening = '<section class="TYPE"><div class="BOX Top1">'
        closing = "</div></section>"
        href = lambda rank: f"/book/{rank}.html"
    else:
        opening = '<section class="rank-list"><div class="book-rank-list">'
        closing = "</div></section>"
        href = lambda rank: f"/book/{rank}.html"
    rows = "".join(
        f'''<article class="rank-book-item">
          <span class="rank-number">{rank}</span>
          <a class="book-name" href="{(href_for_rank or href)(rank)}">作品{rank}</a>
          <span class="author-name">作者{rank}</span>{extra_field if rank == 1 else ""}
          <span class="book-category">玄幻</span>
        </article>'''
        for rank in range(1, 11)
    )
    return f"<html><body>{opening}{rows}{closing}{extra_container}</body></html>"


async def _fetch_candidate(adapter_class, platform: str, text: str):
    from backend.domain.json_contracts import canonical_hash

    policy = _policy(platform=platform)
    return await adapter_class(
        RecordingTransport(_response(text.encode(), url=adapter_class.source_url))
    ).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )


def test_market_entry_public_metrics_are_deeply_immutable():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market import MarketEntry

    metrics = {"weeklyRecommendations": 321}
    entry = MarketEntry(
        rank=1,
        title="雾港天文钟",
        author="合成作者甲",
        category="奇幻",
        workURL="https://www.qidian.com/book/900000001/",
        publicMetrics=metrics,
    )
    expected_hash = canonical_hash(entry)

    metrics["weeklyRecommendations"] = 999

    assert entry.public_metrics["weeklyRecommendations"] == 321
    with pytest.raises(TypeError):
        entry.public_metrics["weeklyRecommendations"] = 2
    assert canonical_hash(entry) == expected_hash

    entry_without_metrics = MarketEntry(
        rank=2,
        title="盐原回声",
        author="合成作者乙",
        category="科幻",
        workURL="https://www.qidian.com/book/900000002/",
    )
    with pytest.raises(TypeError):
        entry_without_metrics.public_metrics["heat"] = 1


def test_candidate_adapter_registry_has_only_bounded_candidates():
    from backend.gateways.market_sources.fanqie_public_rank import FanqiePublicRankAdapter
    from backend.gateways.market_sources.heiyan_public_rank import HeiyanPublicRankAdapter
    from backend.gateways.market_sources.hongxiu_public_rank import HongxiuPublicRankAdapter
    from backend.gateways.market_sources.jjwxc_public_rank import JJWXCPublicRankAdapter
    from backend.gateways.market_sources.qimao_public_rank import QimaoPublicRankAdapter
    from backend.gateways.market_sources.qq_reading_public_rank import QQReadingPublicRankAdapter
    from backend.gateways.market_sources.registry import (
        build_market_adapters,
        candidate_adapter_factories,
    )
    from backend.gateways.market_sources.seventeen_k_public_rank import SeventeenKPublicRankAdapter
    from backend.gateways.market_sources.zongheng_public_rank import ZonghengPublicRankAdapter

    factories = candidate_adapter_factories()

    assert dict(factories) == {
        "fanqie_public_rank": FanqiePublicRankAdapter,
        "qimao_public_rank": QimaoPublicRankAdapter,
        "qq_reading_public_rank": QQReadingPublicRankAdapter,
        "17k_public_rank": SeventeenKPublicRankAdapter,
        "zongheng_public_rank": ZonghengPublicRankAdapter,
        "hongxiu_public_rank": HongxiuPublicRankAdapter,
        "jjwxc_public_rank": JJWXCPublicRankAdapter,
        "heiyan_public_rank": HeiyanPublicRankAdapter,
    }
    with pytest.raises(TypeError):
        factories["qidian_public_rank"] = object
    transport = object()
    assert all(
        adapter.transport is transport
        for adapter in build_market_adapters(transport).values()
    )


@pytest.mark.asyncio
async def test_fanqie_rejects_private_use_font_text_without_publishing_garbled_entry():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.fanqie_public_rank import (
        FanqiePublicRankAdapter,
    )

    adapter = FanqiePublicRankAdapter
    policy = _policy(platform="fanqie")
    transport = RecordingTransport(
        _response(
            (FIXTURES / "fanqie_obfuscated_official_shape.html").read_bytes(),
            url=adapter.source_url,
        )
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await adapter(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_HTML_UNKNOWN"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_fanqie_reads_one_direct_authoritative_batch_with_observed_ranks():
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.fanqie_public_rank import FanqiePublicRankAdapter

    snapshot = await _fetch_candidate(
        FanqiePublicRankAdapter,
        "fanqie",
        _candidate_rank_html("fanqie"),
    )
    assert [entry.rank for entry in snapshot.entries] == list(range(1, 11))

    hidden_duplicate = (
        '<section hidden><article class="rank-book-item">'
        '<span class="rank-number">11</span>'
        '<a class="book-name" href="/page/11">重复容器作品</a>'
        '<span class="author-name">重复作者</span>'
        '<span class="book-category">玄幻</span>'
        '</article></section>'
    )
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_candidate(
            FanqiePublicRankAdapter,
            "fanqie",
            _candidate_rank_html("fanqie", extra_container=hidden_duplicate),
        )
    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "fixture", "platform"),
    (
        (
            "backend.gateways.market_sources.seventeen_k_public_rank",
            "SeventeenKPublicRankAdapter",
            "seventeen_k_rank_official_shape.html",
            "17k",
        ),
        (
            "backend.gateways.market_sources.hongxiu_public_rank",
            "HongxiuPublicRankAdapter",
            "hongxiu_rank_official_shape.html",
            "hongxiu",
        ),
    ),
)
async def test_candidate_rank_pages_without_observed_author_fail_closed(
    module_name, class_name, fixture, platform
):
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceFailure

    adapter_class = _official_rank_adapter(module_name, class_name)
    policy = _policy(platform=platform)
    transport = RecordingTransport(
        _response(
            (FIXTURES / fixture).read_bytes(),
            url=adapter_class.source_url,
        )
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await adapter_class(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "container_class", "platform"),
    (
        (
            "backend.gateways.market_sources.seventeen_k_public_rank",
            "SeventeenKPublicRankAdapter",
            "TYPE\"><div class=\"BOX Top1",
            "17k",
        ),
        (
            "backend.gateways.market_sources.hongxiu_public_rank",
            "HongxiuPublicRankAdapter",
            "rank-list\"><div class=\"book-rank-list",
            "hongxiu",
        ),
    ),
)
async def test_candidate_adapters_publish_only_complete_observed_rank_rows(
    module_name, class_name, container_class, platform
):
    from backend.domain.json_contracts import canonical_hash

    adapter_class = _official_rank_adapter(module_name, class_name)
    rows = "".join(
        f'''<article class="rank-book-item">
          <a class="book-name" href="/book/{rank}.html">作品{rank}</a>
          <span class="author-name">作者{rank}</span>
          <span class="book-category">玄幻</span>
        </article>'''
        for rank in range(1, 11)
    )
    text = f'<html><body><section class="{container_class}">{rows}</div></section></body></html>'
    policy = _policy(platform=platform)

    snapshot = await adapter_class(
        RecordingTransport(_response(text.encode(), url=adapter_class.source_url))
    ).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert [entry.rank for entry in snapshot.entries] == list(range(1, 11))
    assert snapshot.entries[0].author == "作者1"
    assert snapshot.entries[-1].category == "玄幻"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "platform", "bad_paths"),
    (
        (
            "backend.gateways.market_sources.fanqie_public_rank",
            "FanqiePublicRankAdapter",
            "fanqie",
            ("/book/1.html", "/page/1/extra", "/page/nope", "/page/1?tab=rank", "/page/1#alias"),
        ),
        (
            "backend.gateways.market_sources.seventeen_k_public_rank",
            "SeventeenKPublicRankAdapter",
            "17k",
            ("/rank", "/book/1.html/extra", "/book/nope.html", "/book/1.html?tab=rank", "/book/1.html#alias"),
        ),
        (
            "backend.gateways.market_sources.hongxiu_public_rank",
            "HongxiuPublicRankAdapter",
            "hongxiu",
            ("/rank", "/book/1.html/extra", "/book/nope.html", "/book/1.html?tab=rank", "/book/1.html#alias"),
        ),
    ),
)
async def test_candidate_adapters_reject_noncanonical_work_paths(
    module_name, class_name, platform, bad_paths
):
    from backend.domain.market_sources import MarketSourceFailure

    adapter_class = _official_rank_adapter(module_name, class_name)
    for bad_path in bad_paths:
        with pytest.raises(MarketSourceFailure) as rejected:
            await _fetch_candidate(
                adapter_class,
                platform,
                _candidate_rank_html(
                    platform,
                    href_for_rank=lambda rank: bad_path if rank == 1 else (
                        f"/page/{rank}" if platform == "fanqie" else f"/book/{rank}.html"
                    ),
                ),
            )
        assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "platform"),
    (
        (
            "backend.gateways.market_sources.fanqie_public_rank",
            "FanqiePublicRankAdapter",
            "fanqie",
        ),
        (
            "backend.gateways.market_sources.seventeen_k_public_rank",
            "SeventeenKPublicRankAdapter",
            "17k",
        ),
        (
            "backend.gateways.market_sources.hongxiu_public_rank",
            "HongxiuPublicRankAdapter",
            "hongxiu",
        ),
    ),
)
async def test_candidate_adapters_reject_duplicate_canonical_work_urls(
    module_name, class_name, platform
):
    from backend.domain.market_sources import MarketSourceFailure

    adapter_class = _official_rank_adapter(module_name, class_name)
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_candidate(
            adapter_class,
            platform,
            _candidate_rank_html(
                platform,
                href_for_rank=lambda rank: (
                    "/page/1" if platform == "fanqie" else "/book/1.html"
                ) if rank == 2 else (
                    f"/page/{rank}" if platform == "fanqie" else f"/book/{rank}.html"
                ),
            ),
        )
    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "platform", "field"),
    tuple(
        (module_name, class_name, platform, field)
        for module_name, class_name, platform in (
            (
                "backend.gateways.market_sources.seventeen_k_public_rank",
                "SeventeenKPublicRankAdapter",
                "17k",
            ),
            (
                "backend.gateways.market_sources.hongxiu_public_rank",
                "HongxiuPublicRankAdapter",
                "hongxiu",
            ),
        )
        for field in ("book-name", "author-name", "book-category")
    ),
)
async def test_candidate_adapters_do_not_ignore_duplicate_obfuscated_required_fields(
    module_name, class_name, platform, field
):
    from backend.domain.market_sources import MarketSourceFailure

    adapter_class = _official_rank_adapter(module_name, class_name)
    duplicate = (
        f'<a class="{field}" href="/book/99.html">\ue000</a>'
        if field == "book-name"
        else f'<span class="{field}">\ue000</span>'
    )
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_candidate(
            adapter_class,
            platform,
            _candidate_rank_html(platform, extra_field=duplicate),
        )
    assert rejected.value.code == "MARKET_HTML_UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "platform", "field"),
    tuple(
        (module_name, class_name, platform, field)
        for module_name, class_name, platform in (
            (
                "backend.gateways.market_sources.seventeen_k_public_rank",
                "SeventeenKPublicRankAdapter",
                "17k",
            ),
            (
                "backend.gateways.market_sources.hongxiu_public_rank",
                "HongxiuPublicRankAdapter",
                "hongxiu",
            ),
        )
        for field in ("book-name", "author-name", "book-category")
    ),
)
async def test_candidate_adapters_reject_duplicate_required_fields(
    module_name, class_name, platform, field
):
    from backend.domain.market_sources import MarketSourceFailure

    adapter_class = _official_rank_adapter(module_name, class_name)
    duplicate = (
        f'<a class="{field}" href="/book/99.html">重复</a>'
        if field == "book-name"
        else f'<span class="{field}">重复</span>'
    )
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_candidate(
            adapter_class,
            platform,
            _candidate_rank_html(platform, extra_field=duplicate),
        )
    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_name", "fixture", "url", "platform", "first_title"),
    (
        (
            "QidianPublicRankAdapter",
            "qidian_newsign.html",
            "https://www.qidian.com/rank/newsign/",
            "qidian",
            "雾港天文钟",
        ),
    ),
)
async def test_public_adapters_parse_only_normalized_fixture_facts(
    adapter_name, fixture, url, platform, first_title
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.qidian_public_rank import (
        QidianPublicRankAdapter,
    )
    adapter_class = {
        "QidianPublicRankAdapter": QidianPublicRankAdapter,
    }[adapter_name]
    body = (FIXTURES / fixture).read_bytes()
    transport = RecordingTransport(_response(body, url=url))
    policy = _policy(platform=platform)

    snapshot = await adapter_class(transport).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert snapshot.platform == platform
    assert snapshot.source_url == url
    assert snapshot.entries[0].title == first_title
    assert [entry.rank for entry in snapshot.entries] == [1, 2]
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url == url
    assert request.follow_redirects is False
    assert 0 < request.timeout_seconds <= 10
    assert 0 < request.max_body_bytes <= 512 * 1024


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_name", "fixture", "url", "platform"),
    (
        (
            "QidianPublicRankAdapter",
            "qidian_newsign.html",
            "https://www.qidian.com/rank/newsign/",
            "qidian",
        ),
    ),
)
@pytest.mark.parametrize("damage", ("first-entry-only", "unclosed-container"))
async def test_public_adapters_reject_well_formed_partial_and_truncated_pages(
    adapter_name,
    fixture,
    url,
    platform,
    damage,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.qidian_public_rank import (
        QidianPublicRankAdapter,
    )
    adapter_class = {
        "QidianPublicRankAdapter": QidianPublicRankAdapter,
    }[adapter_name]
    text = (FIXTURES / fixture).read_text(encoding="utf-8")
    if damage == "first-entry-only":
        text = re.sub(
            r"\s*<article data-rank-entry data-rank=\"2\">.*?</article>",
            "",
            text,
            count=1,
            flags=re.DOTALL,
        )
    else:
        text = text.replace("</main>", "", 1)
    transport = RecordingTransport(_response(text.encode("utf-8"), url=url))
    policy = _policy(platform=platform)

    with pytest.raises(MarketSourceFailure) as captured:
        await adapter_class(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert captured.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy_factory", "policy_hash", "expected_code"),
    (
        (lambda: None, "0" * 64, "MARKET_POLICY_MISSING"),
        (
            lambda: _policy(platform="qidian", status="manual_only"),
            None,
            "MARKET_POLICY_NOT_VERIFIED",
        ),
        (
            lambda: _policy(platform="qidian", status="disabled"),
            None,
            "MARKET_POLICY_NOT_VERIFIED",
        ),
        (
            lambda: _policy(platform="qidian", checked_at=NOW + 5 * 60 * 1000 + 1),
            None,
            "MARKET_POLICY_EXPIRED",
        ),
        (
            lambda: _policy(platform="qidian"),
            "0" * 64,
            "MARKET_POLICY_HASH_INVALID",
        ),
    ),
)
async def test_policy_failures_happen_before_transport(
    policy_factory, policy_hash, expected_code
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.qidian_public_rank import (
        QidianPublicRankAdapter,
    )

    transport = RecordingTransport(AssertionError("transport must not open"))
    policy = policy_factory()
    expected_hash = (
        canonical_hash(policy)
        if policy is not None and policy_hash is None
        else policy_hash
    )

    with pytest.raises(MarketSourceFailure) as captured:
        await QidianPublicRankAdapter(transport).fetch(
            policy=policy,
            policy_hash=expected_hash,
            captured_at=NOW,
        )

    assert captured.value.code == expected_code
    assert transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_factory", "expected_code"),
    (
        (
            lambda: _response(
                b"",
                url="https://evil.example/login",
                status=302,
                headers={"location": "https://evil.example/login"},
            ),
            "MARKET_REDIRECT_REJECTED",
        ),
        (
            lambda: _response(
                b"x" * (512 * 1024 + 1),
                url="https://www.qidian.com/rank/newsign/",
            ),
            "MARKET_BODY_TOO_LARGE",
        ),
        (
            lambda: _response(
                "<html><form>请登录后验证 CAPTCHA</form></html>".encode(),
                url="https://www.qidian.com/rank/newsign/",
            ),
            "MARKET_INTERSTITIAL_REJECTED",
        ),
        (
            lambda: _response(
                b"<html><main>unknown layout</main></html>",
                url="https://www.qidian.com/rank/newsign/",
            ),
            "MARKET_HTML_UNKNOWN",
        ),
        (
            lambda: _response(
                (FIXTURES / "qidian_newsign.html").read_bytes(),
                url="https://www.qidian.com/rank/newsign/redirected",
            ),
            "MARKET_REDIRECT_REJECTED",
        ),
    ),
)
async def test_public_adapter_rejects_redirect_size_interstitial_and_unknown_html(
    response_factory, expected_code
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.qidian_public_rank import (
        QidianPublicRankAdapter,
    )

    policy = _policy(platform="qidian")
    transport = RecordingTransport(response_factory())

    with pytest.raises(MarketSourceFailure) as captured:
        await QidianPublicRankAdapter(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert captured.value.code == expected_code
    assert "CAPTCHA" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type",
    (
        "application/octet-stream",
        "text/html; charset=big5",
        "text/html; charset=utf-8; charset=gbk",
    ),
)
async def test_public_adapter_requires_approved_html_content_type(
    content_type,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.qidian_public_rank import (
        QidianPublicRankAdapter,
    )

    policy = _policy(platform="qidian")
    headers = {"content-type": content_type}
    transport = RecordingTransport(
        _response(
            (FIXTURES / "qidian_newsign.html").read_bytes(),
            url="https://www.qidian.com/rank/newsign/",
            headers=headers,
        )
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await QidianPublicRankAdapter(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_CONTENT_TYPE_REJECTED"


@pytest.mark.asyncio
async def test_public_adapter_accepts_xhtml_with_utf8_charset():
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.qidian_public_rank import (
        QidianPublicRankAdapter,
    )

    policy = _policy(platform="qidian")
    transport = RecordingTransport(
        _response(
            (FIXTURES / "qidian_newsign.html").read_bytes(),
            url="https://www.qidian.com/rank/newsign/",
            headers={
                "content-type": "application/xhtml+xml; charset=\"UTF-8\""
            },
        )
    )

    snapshot = await QidianPublicRankAdapter(transport).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert len(snapshot.entries) == 2


_DETAIL_ENRICHED_ADAPTERS = (
    (
        "backend.gateways.market_sources.zongheng_public_rank",
        "ZonghengPublicRankAdapter",
        "zongheng",
        "zongheng_rank_official_shape.html",
        "zongheng_detail_official_shape.html",
        "https://www.zongheng.com/rank?nav=default",
        '<div class="zh-modules-rank-box"><h2>月票榜</h2></div>',
    ),
    (
        "backend.gateways.market_sources.heiyan_public_rank",
        "HeiyanPublicRankAdapter",
        "heiyan",
        "heiyan_rank_official_shape.html",
        "heiyan_detail_official_shape.html",
        "https://www.heiyan.com/top/",
        '<div class="pattern-rank"></div>',
    ),
)


def _detail_fixture_body(fixture: str, *, title: str, url: str) -> bytes:
    return (
        (FIXTURES / fixture)
        .read_text(encoding="utf-8")
        .replace("{{TITLE}}", title)
        .replace("{{URL}}", url)
        .encode("utf-8")
    )


def _detail_title_for_url(url: str) -> str:
    return f"作品{url.rstrip('/').rsplit('/', 1)[-1]}"


def _detail_policy_prefixes(platform: str) -> tuple[str, str]:
    return ("/rank", "/detail/") if platform == "zongheng" else ("/top/", "/book/")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_fetches_one_rank_page_and_exactly_ten_same_origin_details(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash

    adapter_class = _official_rank_adapter(module_name, class_name)
    rank_body = (FIXTURES / rank_fixture).read_bytes()
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=rank_body,
        detail_body_for_url=lambda url: _detail_fixture_body(
            detail_fixture,
            title=_detail_title_for_url(url),
            url=url,
        ),
    )
    adapter = adapter_class(transport)
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    snapshot = await adapter.fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert len(snapshot.entries) == 10
    assert all(entry.author and entry.category for entry in snapshot.entries)
    detail_requests = transport.requests[1:]
    assert len(detail_requests) == 10
    assert all(request.url.startswith(adapter.work_origin) for request in detail_requests)
    detail_path = "/detail/" if platform == "zongheng" else "/book/"
    assert [request.url for request in transport.requests] == [
        source_url,
        *(f"{adapter.work_origin}{detail_path}{rank}" for rank in range(1, 11)),
    ]
    assert len({request.url for request in detail_requests}) == 10
    expected_metrics = (
        {
            "status": "连载",
            "description": "公开简介",
            "tags": "标签甲 标签乙",
            "numbers": "12万字 3000点击",
        }
        if platform == "zongheng"
        else {
            "status": "完结",
            "description": "公开简介",
            "counters": "12万字 3000点击",
        }
    )
    assert all(dict(entry.public_metrics) == expected_metrics for entry in snapshot.entries)


@pytest.mark.asyncio
async def test_zongheng_selects_unique_monthly_ticket_container_with_medal_ranks():
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.zongheng_public_rank import (
        ZonghengPublicRankAdapter,
    )

    source_url = ZonghengPublicRankAdapter.source_url
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=(FIXTURES / "zongheng_rank_official_shape.html").read_bytes(),
        detail_body_for_url=lambda url: _detail_fixture_body(
            "zongheng_detail_official_shape.html",
            title=_detail_title_for_url(url),
            url=url,
        ),
    )
    policy = _policy(platform="zongheng", prefixes=("/rank", "/detail/"))

    snapshot = await ZonghengPublicRankAdapter(transport).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert [entry.rank for entry in snapshot.entries] == list(range(1, 11))
    assert [entry.title for entry in snapshot.entries] == [
        *(f"作品{rank}" for rank in range(1, 11))
    ]
    assert len(transport.requests) == 11


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    (
        lambda text: text.replace("其他榜单五", "月票榜", 1),
        lambda text: text.replace("月票榜", "月度推荐", 1),
        lambda text: text.replace(
            '<img src="/static/rank-1.png" alt="第一名奖牌">',
            '<img src="/static/rank-1.png" alt="第一名奖牌"><img src="/static/noise.png" alt="噪声">',
            1,
        ),
        lambda text: text.replace(">04<", ">4<", 1),
        lambda text: text.replace(">05<", ">04<", 1),
    ),
)
async def test_zongheng_rejects_ambiguous_monthly_container_or_rank_shape(mutation):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.zongheng_public_rank import (
        ZonghengPublicRankAdapter,
    )

    source_url = ZonghengPublicRankAdapter.source_url
    rank_text = (FIXTURES / "zongheng_rank_official_shape.html").read_text(
        encoding="utf-8"
    )
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=mutation(rank_text).encode("utf-8"),
        detail_body_for_url=lambda url: AssertionError("detail transport must not open"),
    )
    policy = _policy(platform="zongheng", prefixes=("/rank", "/detail/"))

    with pytest.raises(MarketSourceFailure) as rejected:
        await ZonghengPublicRankAdapter(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_never_starts_an_eleventh_detail_request(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash

    rank_text = (FIXTURES / rank_fixture).read_text(encoding="utf-8")
    extra = rank_text.replace('data-rank-row="1"', 'data-rank-row="11"', 1)
    extra = extra.replace(">1<", ">11<", 1).replace("作品1", "作品11", 1)
    rank_body = rank_text.replace("</body>", extra[extra.index("<article"):extra.index("</article>") + 10] + "</body>")
    adapter_class = _official_rank_adapter(module_name, class_name)
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=rank_body.encode("utf-8"),
        detail_body_for_url=lambda url: _detail_fixture_body(
            detail_fixture,
            title=_detail_title_for_url(url),
            url=url,
        ),
    )
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    snapshot = await adapter_class(transport).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert len(snapshot.entries) == 10
    assert len(transport.requests) == 11


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_fails_closed_if_its_detail_limit_is_relaxed(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=(FIXTURES / rank_fixture).read_bytes(),
        detail_body_for_url=lambda url: AssertionError("detail transport must not open"),
    )
    adapter = _official_rank_adapter(module_name, class_name)(transport)
    adapter.detail_limit = 11
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await adapter.fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_rejects_off_origin_candidate_before_detail_transport(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    rank_body = (FIXTURES / rank_fixture).read_text(encoding="utf-8").replace(
        'href="/detail/1"', 'href="https://evil.example/book/1"', 1
    ).replace('href="/book/1"', 'href="https://evil.example/book/1"', 1).encode("utf-8")
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=rank_body,
        detail_body_for_url=lambda url: AssertionError("detail transport must not open"),
    )
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await _official_rank_adapter(module_name, class_name)(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_rejects_duplicate_canonical_detail_urls_before_transport(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    detail_path = "/detail/" if platform == "zongheng" else "/book/"
    rank_body = (FIXTURES / rank_fixture).read_text(encoding="utf-8").replace(
        f'href="{detail_path}2"', f'href="{detail_path}1"', 1
    ).encode("utf-8")
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=rank_body,
        detail_body_for_url=lambda url: _detail_fixture_body(
            detail_fixture,
            title=_detail_title_for_url(url),
            url=url,
        ),
    )
    policy = _policy(platform=platform, prefixes=_detail_policy_prefixes(platform))

    with pytest.raises(MarketSourceFailure) as rejected:
        await _official_rank_adapter(module_name, class_name)(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_rejects_fragment_alias_candidates_before_transport(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    detail_path = "/detail/" if platform == "zongheng" else "/book/"
    rank_text = (FIXTURES / rank_fixture).read_text(encoding="utf-8")
    for rank in range(1, 11):
        rank_text = rank_text.replace(
            f'href="{detail_path}{rank}"', f'href="{detail_path}1#{rank}"', 1
        )
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=rank_text.encode("utf-8"),
        detail_body_for_url=lambda url: AssertionError("detail transport must not open"),
    )
    policy = _policy(platform=platform, prefixes=_detail_policy_prefixes(platform))

    with pytest.raises(MarketSourceFailure) as rejected:
        await _official_rank_adapter(module_name, class_name)(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_rejects_sixth_candidate_outside_policy_before_transport(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    detail_path = "/detail/" if platform == "zongheng" else "/book/"
    rank_body = (FIXTURES / rank_fixture).read_text(encoding="utf-8").replace(
        f'href="{detail_path}6"', 'href="/outside-policy/6"', 1
    ).encode("utf-8")
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=rank_body,
        detail_body_for_url=lambda url: AssertionError("detail transport must not open"),
    )
    policy = _policy(platform=platform, prefixes=_detail_policy_prefixes(platform))

    with pytest.raises(MarketSourceFailure) as rejected:
        await _official_rank_adapter(module_name, class_name)(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_canonicalizes_relative_and_protocol_relative_og_urls(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash

    adapter_class = _official_rank_adapter(module_name, class_name)
    adapter = adapter_class(None)
    rank_text = (FIXTURES / rank_fixture).read_text(encoding="utf-8")
    first_href = "/detail/1" if platform == "zongheng" else "/book/1"
    rank_body = rank_text.replace(
        f'href="{first_href}"', f'href="{first_href}/"', 1
    ).encode("utf-8")

    def detail_body_for_url(url):
        path = "/" + url.split("/", 3)[-1]
        og_url = path if url.endswith("/") else f"//{url.split('/')[2]}{path}"
        return _detail_fixture_body(
            detail_fixture,
            title=_detail_title_for_url(url),
            url=og_url,
        )

    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=rank_body,
        detail_body_for_url=detail_body_for_url,
    )
    adapter = adapter_class(transport)
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    snapshot = await adapter.fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert snapshot.entries[0].work_url.endswith("/")
    assert len(transport.requests) == 11


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
@pytest.mark.parametrize("og_url", ("//evil.example/book/1", "/%2e%2e/private"))
async def test_detail_enrichment_rejects_off_origin_or_ambiguous_og_urls(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
    og_url,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=(FIXTURES / rank_fixture).read_bytes(),
        detail_body_for_url=lambda url: _detail_fixture_body(
            detail_fixture,
            title=_detail_title_for_url(url),
            url=og_url,
        ),
    )
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await _official_rank_adapter(module_name, class_name)(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_heiyan_detail_requires_one_book_info_container():
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.heiyan_public_rank import (
        HeiyanPublicRankAdapter,
    )

    source_url = HeiyanPublicRankAdapter.source_url
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=(FIXTURES / "heiyan_rank_official_shape.html").read_bytes(),
        detail_body_for_url=lambda url: _detail_fixture_body(
            "heiyan_detail_official_shape.html",
            title=_detail_title_for_url(url),
            url=url,
        ).replace(
            b"</body>",
            b'<div class="book-info"><span class="book-count">extra</span></div></body>',
            1,
        ),
    )
    policy = _policy(platform="heiyan", prefixes=("/top/", "/book/"))

    with pytest.raises(MarketSourceFailure) as rejected:
        await HeiyanPublicRankAdapter(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
@pytest.mark.parametrize(
    "bad_candidate",
    ("empty-title", "missing-href", "off-origin-href", "ambiguous-path", "bad-rank"),
)
async def test_detail_enrichment_rejects_bad_rank_candidates_before_all_detail_transport(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
    bad_candidate,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    rank_text = (FIXTURES / rank_fixture).read_text(encoding="utf-8")
    detail_path = "/detail/1" if platform == "zongheng" else "/book/1"
    if bad_candidate == "empty-title":
        rank_text = rank_text.replace(">作品1<", "><", 1)
    elif bad_candidate == "missing-href":
        rank_text = rank_text.replace(f' href="{detail_path}"', "", 1)
    elif bad_candidate == "off-origin-href":
        rank_text = rank_text.replace(
            f'href="{detail_path}"', 'href="https://evil.example/book/1"', 1
        )
    elif bad_candidate == "ambiguous-path":
        rank_text = rank_text.replace(
            f'href="{detail_path}"', 'href="/%2e%2e/private"', 1
        )
    else:
        rank_text = (
            rank_text.replace(">04<", ">05<", 1)
            if platform == "zongheng"
            else rank_text.replace(">2<", ">3<", 1)
        )
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=rank_text.encode("utf-8"),
        detail_body_for_url=lambda url: AssertionError("detail transport must not open"),
    )
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await _official_rank_adapter(module_name, class_name)(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_stops_at_the_sixth_failed_detail_without_snapshot(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    adapter_class = _official_rank_adapter(module_name, class_name)

    class SnapshotSpyAdapter(adapter_class):
        def __init__(self, transport):
            super().__init__(transport)
            self.snapshot_calls = 0

        def snapshot(self, entries, *, captured_at):
            self.snapshot_calls += 1
            return super().snapshot(entries, captured_at=captured_at)

    def detail_body_for_url(url):
        body = _detail_fixture_body(
            detail_fixture,
            title=_detail_title_for_url(url),
            url=url,
        )
        if url.rstrip("/").endswith("/6"):
            return body.replace(b'content="\xe5\x85\xac\xe5\xbc\x80author"', b'content=""', 1)
        return body

    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=(FIXTURES / rank_fixture).read_bytes(),
        detail_body_for_url=detail_body_for_url,
    )
    adapter = SnapshotSpyAdapter(transport)
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await adapter.fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert adapter.snapshot_calls == 0
    assert len(transport.requests) == 7
    assert transport.requests[-1].url.rstrip("/").endswith("/6")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_rejects_oversized_detail_pages(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=(FIXTURES / rank_fixture).read_bytes(),
        detail_body_for_url=lambda url: b"x" * (512 * 1024 + 1),
    )
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await _official_rank_adapter(module_name, class_name)(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_BODY_TOO_LARGE"
    assert len(transport.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing_field", ("author", "category")
)
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,_"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
async def test_detail_enrichment_rejects_missing_required_detail_metadata(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    _,
    missing_field,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    detail_text = (FIXTURES / detail_fixture).read_text(encoding="utf-8")
    detail_text = detail_text.replace(
        f'og:novel:{missing_field}" content="公开{missing_field}"',
        f'og:novel:{missing_field}" content=""',
        1,
    )
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=(FIXTURES / rank_fixture).read_bytes(),
        detail_body_for_url=lambda url: (
            detail_text.replace("{{TITLE}}", f"作品{url.rsplit('/', 1)[-1]}")
            .replace("{{URL}}", url)
            .encode("utf-8")
        ),
    )
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await _official_rank_adapter(module_name, class_name)(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"
    assert len(transport.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name,class_name,platform,rank_fixture,detail_fixture,source_url,extra_container"
    ),
    _DETAIL_ENRICHED_ADAPTERS,
)
@pytest.mark.parametrize(
    "damage", ("fewer", "ambiguous", "bad-rank", "detail-title", "detail-url")
)
async def test_detail_enrichment_rejects_incomplete_or_mismatched_pages(
    module_name,
    class_name,
    platform,
    rank_fixture,
    detail_fixture,
    source_url,
    extra_container,
    damage,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    rank_text = (FIXTURES / rank_fixture).read_text(encoding="utf-8")
    if damage == "fewer":
        rank_text = re.sub(
            r'\s*<article[^>]*data-rank-row="10".*?</article>',
            "",
            rank_text,
            count=1,
            flags=re.DOTALL,
        )
    elif damage == "ambiguous":
        rank_text = rank_text.replace("</body>", extra_container + "</body>")
    elif damage == "bad-rank":
        rank_text = (
            rank_text.replace(">04<", ">05<", 1)
            if platform == "zongheng"
            else rank_text.replace(">2<", ">3<", 1)
        )
    detail_title = "不一致作品" if damage == "detail-title" else None
    og_url = "https://evil.example/book/1" if damage == "detail-url" else None
    transport = RankAndDetailTransport(
        rank_url=source_url,
        rank_body=rank_text.encode("utf-8"),
        detail_body_for_url=lambda url: _detail_fixture_body(
            detail_fixture,
            title=detail_title or f"作品{url.rsplit('/', 1)[-1]}",
            url=og_url or url,
        ),
    )
    policy = _policy(
        platform=platform,
        prefixes=_detail_policy_prefixes(platform),
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        await _official_rank_adapter(module_name, class_name)(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


def _fetch_public_document():
    from backend.gateways.market_sources import base

    fetcher = getattr(base, "fetch_public_document", None)
    assert callable(fetcher), "strict public HTML document fetcher is required"
    return fetcher


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("charset", "encoding"),
    (
        ("UTF-8", "utf-8"),
        ("UTF8", "utf-8"),
        ("gb2312", "gb2312"),
        ("GBK", "gbk"),
        ("gb18030", "gb18030"),
    ),
)
async def test_document_accepts_declared_supported_charset_without_policy_age_expiry(
    charset, encoding
):
    from backend.domain.json_contracts import canonical_hash

    policy = _policy(
        platform="qimao",
        checked_at=1_700_000_000_000,
        origins=("https://www.qimao.com",),
        prefixes=("/paihang/", "/shuku/"),
    )
    response = _response(
        "小说排行榜".encode(encoding),
        url="https://www.qimao.com/paihang/boy/update/date/",
        headers={"content-type": f"text/html; charset={charset}"},
    )
    document = await _fetch_public_document()(
        RecordingTransport(response),
        policy=policy,
        policy_hash=canonical_hash(policy),
        url="https://www.qimao.com/paihang/boy/update/date/",
        captured_at=1_800_000_000_000,
    )

    assert document.text == "小说排行榜"
    assert document.soup.get_text() == "小说排行榜"


def _official_rank_adapter(module_name: str, class_name: str):
    return getattr(import_module(module_name), class_name)


async def _fetch_single_page_adapter(
    module_name: str,
    class_name: str,
    platform: str,
    source_url: str,
    text: str,
):
    from backend.domain.json_contracts import canonical_hash

    adapter_class = _official_rank_adapter(module_name, class_name)
    policy = _policy(platform=platform)
    return await adapter_class(
        RecordingTransport(_response(text.encode("utf-8"), url=source_url))
    ).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name",
        "class_name",
        "fixture",
        "source_url",
        "platform",
        "ranking_name",
        "adapter_version",
        "work_urls",
        "first_fields",
        "last_fields",
        "expected_metrics",
    ),
    (
        (
            "backend.gateways.market_sources.qq_reading_public_rank",
            "QQReadingPublicRankAdapter",
            "qq_rank_official_shape.html",
            "https://book.qq.com/book-rank",
            "qq_reading",
            "male_popular",
            "qq-reading-public-rank-v1",
            tuple(f"https://book.qq.com/book-detail/{rank}" for rank in range(1, 11)),
            ("作品一", "作者一", "玄幻"),
            ("作品十", "作者十", "玄幻"),
            {"intro": "公开简介", "status": "连载", "wordCount": "58.5万字"},
        ),
        (
            "backend.gateways.market_sources.qimao_public_rank",
            "QimaoPublicRankAdapter",
            "qimao_rank_official_shape.html",
            "https://www.qimao.com/paihang/boy/update/date/",
            "qimao",
            "boy_update",
            "qimao-public-rank-v1",
            tuple(f"https://www.qimao.com/shuku/{rank}/" for rank in range(1, 11)),
            ("作品一", "作者一", "玄幻奇幻"),
            ("作品十", "作者十", "玄幻奇幻"),
            {"status": "连载中", "wordCount": "200万字", "intro": "公开简介"},
        ),
        (
            "backend.gateways.market_sources.jjwxc_public_rank",
            "JJWXCPublicRankAdapter",
            "jjwxc_rank_official_shape.html",
            "https://www.jjwxc.net/topten.php?orderstr=4",
            "jjwxc",
            "quarterly_score",
            "jjwxc-public-rank-v1",
            tuple(
                f"https://www.jjwxc.net/onebook.php?novelid={rank}"
                for rank in range(1, 11)
            ),
            ("作品一", "作者一", "原创-言情-架空历史-爱情"),
            ("作品十", "作者十", "原创-言情-架空历史-爱情"),
            {
                "status": "完结",
                "wordCount": "348925",
                "score": "3016198144",
                "publishedAt": "2026-09-01 12:34:56",
            },
        ),
    ),
)
async def test_single_page_official_adapters_parse_ten_complete_rows(
    module_name,
    class_name,
    fixture,
    source_url,
    platform,
    ranking_name,
    adapter_version,
    work_urls,
    first_fields,
    last_fields,
    expected_metrics,
):
    from backend.domain.json_contracts import canonical_hash

    adapter_class = _official_rank_adapter(module_name, class_name)
    policy = _policy(platform=platform)
    transport = RecordingTransport(
        _response((FIXTURES / fixture).read_bytes(), url=source_url)
    )

    snapshot = await adapter_class(transport).fetch(
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert snapshot.platform == platform
    assert snapshot.source_url == source_url
    assert snapshot.ranking_name == ranking_name
    assert adapter_class.adapter_version == adapter_version
    assert [entry.rank for entry in snapshot.entries] == list(range(1, 11))
    assert all(entry.title and entry.author and entry.category for entry in snapshot.entries)
    assert [entry.work_url for entry in snapshot.entries] == list(work_urls)
    assert (
        snapshot.entries[0].title,
        snapshot.entries[0].author,
        snapshot.entries[0].category,
    ) == first_fields
    assert (
        snapshot.entries[-1].title,
        snapshot.entries[-1].author,
        snapshot.entries[-1].category,
    ) == last_fields
    assert all(dict(entry.public_metrics) == expected_metrics for entry in snapshot.entries)
    suffixes = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
    assert [
        (
            entry.rank,
            entry.title,
            entry.author,
            entry.category,
            entry.work_url,
            dict(entry.public_metrics),
        )
        for entry in snapshot.entries
    ] == [
        (
            rank,
            f"作品{suffix}",
            f"作者{suffix}",
            first_fields[2],
            work_urls[rank - 1],
            expected_metrics,
        )
        for rank, suffix in enumerate(suffixes, start=1)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "fixture", "source_url", "platform"),
    (
        (
            "backend.gateways.market_sources.qq_reading_public_rank",
            "QQReadingPublicRankAdapter",
            "qq_rank_official_shape.html",
            "https://book.qq.com/book-rank",
            "qq_reading",
        ),
        (
            "backend.gateways.market_sources.qimao_public_rank",
            "QimaoPublicRankAdapter",
            "qimao_rank_official_shape.html",
            "https://www.qimao.com/paihang/boy/update/date/",
            "qimao",
        ),
        (
            "backend.gateways.market_sources.jjwxc_public_rank",
            "JJWXCPublicRankAdapter",
            "jjwxc_rank_official_shape.html",
            "https://www.jjwxc.net/topten.php?orderstr=4",
            "jjwxc",
        ),
    ),
)
async def test_single_page_official_adapters_reject_incomplete_rows(
    module_name, class_name, fixture, source_url, platform
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    adapter_class = _official_rank_adapter(module_name, class_name)
    policy = _policy(platform=platform)
    text = (FIXTURES / fixture).read_text(encoding="utf-8").replace(
        "作品十", "", 1
    )
    transport = RecordingTransport(_response(text.encode("utf-8"), url=source_url))

    with pytest.raises(MarketSourceFailure) as captured:
        await adapter_class(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert captured.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "platform", "fixture", "source_url", "selector"),
    (
        (
            "backend.gateways.market_sources.qq_reading_public_rank",
            "QQReadingPublicRankAdapter",
            "qq_reading",
            "qq_rank_official_shape.html",
            "https://book.qq.com/book-rank",
            ".intro",
        ),
        (
            "backend.gateways.market_sources.qimao_public_rank",
            "QimaoPublicRankAdapter",
            "qimao",
            "qimao_rank_official_shape.html",
            "https://www.qimao.com/paihang/boy/update/date/",
            ".s-book-intro",
        ),
    ),
)
async def test_single_page_intro_is_validated_then_excerpted_to_metric_bound(
    module_name, class_name, platform, fixture, source_url, selector
):
    from bs4 import BeautifulSoup

    long_intro = " ".join(f"公开简介{index}" for index in range(40))
    expected = " ".join(long_intro.split())[:200].rstrip()
    soup = BeautifulSoup((FIXTURES / fixture).read_text(encoding="utf-8"), "html.parser")
    soup.select_one(selector).string = long_intro

    snapshot = await _fetch_single_page_adapter(
        module_name,
        class_name,
        platform,
        source_url,
        str(soup),
    )

    assert len(long_intro) > 200
    assert snapshot.entries[0].public_metrics["intro"] == expected
    assert len(snapshot.entries[0].public_metrics["intro"]) <= 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "platform", "fixture", "source_url", "selector"),
    (
        (
            "backend.gateways.market_sources.qq_reading_public_rank",
            "QQReadingPublicRankAdapter",
            "qq_reading",
            "qq_rank_official_shape.html",
            "https://book.qq.com/book-rank",
            ".intro",
        ),
        (
            "backend.gateways.market_sources.qimao_public_rank",
            "QimaoPublicRankAdapter",
            "qimao",
            "qimao_rank_official_shape.html",
            "https://www.qimao.com/paihang/boy/update/date/",
            ".s-book-intro",
        ),
    ),
)
async def test_single_page_intro_rejects_private_use_after_excerpt_boundary(
    module_name, class_name, platform, fixture, source_url, selector
):
    from bs4 import BeautifulSoup
    from backend.gateways.market_sources.base import MarketSourceFailure

    soup = BeautifulSoup((FIXTURES / fixture).read_text(encoding="utf-8"), "html.parser")
    soup.select_one(selector).string = "公开" * 101 + "\ue000"

    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_single_page_adapter(
            module_name,
            class_name,
            platform,
            source_url,
            str(soup),
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_qq_reads_only_one_rank_container_and_ignores_outside_recommendations():
    text = (FIXTURES / "qq_rank_official_shape.html").read_text(encoding="utf-8")
    snapshot = await _fetch_single_page_adapter(
        "backend.gateways.market_sources.qq_reading_public_rank",
        "QQReadingPublicRankAdapter",
        "qq_reading",
        "https://book.qq.com/book-rank",
        text.replace(
            "</body>",
            '<div class="rank-book"><a class="wrap" href="//book.qq.com/book-detail/99"><h4 class="title">站外推荐</h4></a></div></body>',
        ),
    )

    assert [entry.title for entry in snapshot.entries] == [
        "作品一",
        "作品二",
        "作品三",
        "作品四",
        "作品五",
        "作品六",
        "作品七",
        "作品八",
        "作品九",
        "作品十",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutated_text",
    (
        lambda text: text.replace(
            "</body>",
            '<div class="book-rank main"><div class="tabs"><div class="tabs-content"><div class="rank-book"></div></div></div></div></body>',
        ),
        lambda text: text.replace("tabs-content", "not-tabs-content", 1),
        lambda text: text.replace('class="title">作品十', 'class="missing-title">作品十', 1),
    ),
)
async def test_qq_rejects_ambiguous_container_and_missing_required_selector(mutated_text):
    from backend.gateways.market_sources.base import MarketSourceFailure

    text = (FIXTURES / "qq_rank_official_shape.html").read_text(encoding="utf-8")
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_single_page_adapter(
            "backend.gateways.market_sources.qq_reading_public_rank",
            "QQReadingPublicRankAdapter",
            "qq_reading",
            "https://book.qq.com/book-rank",
            mutated_text(text),
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_qimao_ignores_decorative_metrics_nodes():
    text = (FIXTURES / "qimao_rank_official_shape.html").read_text(encoding="utf-8")
    snapshot = await _fetch_single_page_adapter(
        "backend.gateways.market_sources.qimao_public_rank",
        "QimaoPublicRankAdapter",
        "qimao",
        "https://www.qimao.com/paihang/boy/update/date/",
        text.replace(
            "<em>连载中</em>",
            '<em class="badge">推荐</em><em class="">噪声</em><em>连载中</em>',
            1,
        ),
    )

    assert dict(snapshot.entries[0].public_metrics) == {
        "status": "连载中",
        "wordCount": "200万字",
        "intro": "公开简介",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutated_text",
    (
        lambda text: text.replace("<em>连载中</em>", "", 1),
        lambda text: text.replace("<em>200万字</em>", "<em>200万字</em><em>额外</em>", 1),
        lambda text: text.replace('class="rank-number">1', 'class="rank-number">11', 1),
        lambda text: text.replace("https://www.qimao.com/shuku/1/", "https://evil.example/book/1", 1),
    ),
)
async def test_qimao_rejects_nonsemantic_metrics_bad_rank_and_nonofficial_url(mutated_text):
    from backend.gateways.market_sources.base import MarketSourceFailure

    text = (FIXTURES / "qimao_rank_official_shape.html").read_text(encoding="utf-8")
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_single_page_adapter(
            "backend.gateways.market_sources.qimao_public_rank",
            "QimaoPublicRankAdapter",
            "qimao",
            "https://www.qimao.com/paihang/boy/update/date/",
            mutated_text(text),
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_row",
    (
        '<tr><td>11</td><td>作者</td><td><a class="tooltip" href="onebook.php?novelid=11">坏行</a></td><td>原创</td><td>完结</td><td>1</td><td>2</td></tr>',
        '<tr><td>11</td><td>作者</td><td><a class="tooltip">坏行</a></td><td>原创</td><td>完结</td><td>1</td><td>2</td><td>2026-09-01</td></tr>',
        '<tr><td>11</td><td></td><td><a class="tooltip" href="onebook.php?novelid=11">坏行</a></td><td>原创</td><td>完结</td><td>1</td><td>2</td><td>2026-09-01</td></tr>',
    ),
)
async def test_jjwxc_rejects_any_invalid_observed_row_including_trailing_rows(bad_row):
    from backend.gateways.market_sources.base import MarketSourceFailure

    text = (FIXTURES / "jjwxc_rank_official_shape.html").read_text(encoding="utf-8")
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_single_page_adapter(
            "backend.gateways.market_sources.jjwxc_public_rank",
            "JJWXCPublicRankAdapter",
            "jjwxc",
            "https://www.jjwxc.net/topten.php?orderstr=4",
            text.replace("</tbody>", f"{bad_row}</tbody>"),
        )

    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    (
        b"captcha",
        "请完成人机验证".encode("utf-8"),
        "人机验证".encode("utf-8"),
        "安全验证".encode("utf-8"),
    ),
)
async def test_document_rejects_interstitials(body):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    policy = _policy(platform="qidian")
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_public_document()(
            RecordingTransport(
                _response(body, url="https://www.qidian.com/rank/newsign/")
            ),
            policy=policy,
            policy_hash=canonical_hash(policy),
            url="https://www.qidian.com/rank/newsign/",
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_INTERSTITIAL_REJECTED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    (
        "<main>CAPTCHA验证</main>",
        "<main>人机<span>验证</span></main>",
        "<main>请登录后<span>查看排行榜</span></main>",
    ),
)
async def test_document_rejects_visible_compact_challenge_phrases(body):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    policy = _policy(platform="qidian")
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_public_document()(
            RecordingTransport(
                _response(body.encode("utf-8"), url="https://www.qidian.com/rank/newsign/")
            ),
            policy=policy,
            policy_hash=canonical_hash(policy),
            url="https://www.qidian.com/rank/newsign/",
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_INTERSTITIAL_REJECTED"


@pytest.mark.asyncio
async def test_qq_fixture_rejects_visible_captcha_challenge():
    from backend.gateways.market_sources.base import MarketSourceFailure

    text = (FIXTURES / "qq_rank_official_shape.html").read_text(encoding="utf-8")
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_single_page_adapter(
            "backend.gateways.market_sources.qq_reading_public_rank",
            "QQReadingPublicRankAdapter",
            "qq_reading",
            "https://book.qq.com/book-rank",
            text.replace("</body>", "<div>CAPTCHA验证</div></body>"),
        )

    assert rejected.value.code == "MARKET_INTERSTITIAL_REJECTED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    (
        "<main>公开排行榜</main><footer>双新用户登录后1-20天可参与排行</footer>",
        "<main><p>人机</p><p>验证</p></main>",
        "<main>公开排行榜</main><div hidden>captcha 人机验证</div>",
        '<main>公开排行榜</main><div aria-hidden="true">captcha 人机验证</div>',
    ),
)
async def test_document_ignores_normal_footer_and_hidden_challenge_text(body):
    from backend.domain.json_contracts import canonical_hash

    policy = _policy(platform="qidian")
    document = await _fetch_public_document()(
        RecordingTransport(
            _response(body.encode("utf-8"), url="https://www.qidian.com/rank/newsign/")
        ),
        policy=policy,
        policy_hash=canonical_hash(policy),
        url="https://www.qidian.com/rank/newsign/",
        captured_at=NOW,
    )

    assert document.soup.find("main") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    (
        "<main>公开排行榜</main><footer>登录后可收藏作品</footer>",
        "<main>公开排行榜</main><script>smCaptchaStatus = 'idle'</script>",
        "<main>公开排行榜</main><!-- captcha 人机验证 -->",
        "<main>公开排行榜</main><style>.captcha { display: none; }</style>",
        "<main>公开排行榜</main><script><span>captcha 人机验证</span></script>",
        "<main>公开排行榜</main><template><section>captcha 人机验证</section></template>",
        "<main>公开排行榜</main><noscript><section>captcha 人机验证</section></noscript>",
    ),
)
async def test_document_ignores_normal_visible_footer_and_non_body_challenge_tokens(body):
    from backend.domain.json_contracts import canonical_hash

    policy = _policy(platform="qidian")
    document = await _fetch_public_document()(
        RecordingTransport(
            _response(body.encode("utf-8"), url="https://www.qidian.com/rank/newsign/")
        ),
        policy=policy,
        policy_hash=canonical_hash(policy),
        url="https://www.qidian.com/rank/newsign/",
        captured_at=NOW,
    )

    assert "公开排行榜" in document.soup.get_text()


def test_text_normalizer_rejects_private_use_font_obfuscation():
    from backend.gateways.market_sources import base

    normalizer = getattr(base, "normalized_public_text", None)
    assert callable(normalizer), "public text normalizer is required"
    with pytest.raises(base.MarketSourceFailure) as rejected:
        normalizer("小说\ue000排行榜")

    assert rejected.value.code == "MARKET_HTML_UNKNOWN"


def test_public_excerpt_validates_full_source_before_truncating():
    from backend.gateways.market_sources import base

    excerpt = getattr(base, "normalized_public_excerpt", None)
    assert callable(excerpt), "bounded public excerpt helper is required"
    with pytest.raises(base.MarketSourceFailure) as rejected:
        excerpt("公开" * 101 + "\ue000", source_limit=1_000, limit=200)

    assert rejected.value.code == "MARKET_HTML_UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_code"),
    (
        (
            _response(
                b"",
                url="https://www.qidian.com/rank/newsign/",
                status=302,
                headers={"location": "https://www.qidian.com/rank/newsign/"},
            ),
            "MARKET_REDIRECT_REJECTED",
        ),
        (
            _response(
                b"x" * (512 * 1024 + 1),
                url="https://www.qidian.com/rank/newsign/",
            ),
            "MARKET_BODY_TOO_LARGE",
        ),
        (
            _response(b"<html></html>", url="https://evil.example/rank"),
            "MARKET_REDIRECT_REJECTED",
        ),
    ),
)
async def test_document_preserves_bounded_transport_and_response_boundary(
    response, expected_code
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    policy = _policy(platform="qidian")
    transport = RecordingTransport(response)
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_public_document()(
            transport,
            policy=policy,
            policy_hash=canonical_hash(policy),
            url="https://www.qidian.com/rank/newsign/",
            captured_at=NOW,
        )

    assert rejected.value.code == expected_code
    request = transport.requests[0]
    assert request.follow_redirects is False
    assert 0 < request.timeout_seconds <= 10
    assert 0 < request.max_body_bytes <= 512 * 1024


@pytest.mark.asyncio
async def test_document_rejects_conflicting_declared_charset():
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    policy = _policy(platform="qidian")
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_public_document()(
            RecordingTransport(
                _response(
                    b'<meta charset="gbk">ranking',
                    url="https://www.qidian.com/rank/newsign/",
                )
            ),
            policy=policy,
            policy_hash=canonical_hash(policy),
            url="https://www.qidian.com/rank/newsign/",
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_HTML_UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    (
        "https://www.qidian.com/book/../private",
        "https://www.qidian.com/book/%2e%2e/private",
        "https://www.qidian.com/book/%2E%2E%2Fprivate",
        "https://www.qidian.com/book/%252e%252e%252fprivate",
        "https://www.qidian.com/book/%2fprivate",
        "https://www.qidian.com/book/%5cprivate",
        "https://www.qidian.com/book/%2e%2e%5cprivate",
    ),
)
async def test_document_rejects_ambiguous_encoded_path_structure_before_transport(url):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    policy = _policy(
        platform="qidian",
        origins=("https://www.qidian.com",),
        prefixes=("/book/",),
    )
    transport = RecordingTransport(AssertionError("transport must not open"))

    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_public_document()(
            transport,
            policy=policy,
            policy_hash=canonical_hash(policy),
            url=url,
            captured_at=NOW,
        )

    assert rejected.value.code == "MARKET_URL_NOT_ALLOWED"
    assert transport.requests == []


@pytest.mark.asyncio
async def test_document_allows_nonstructural_percent_encoded_public_path():
    from backend.domain.json_contracts import canonical_hash

    url = "https://www.qidian.com/book/%E5%85%AC%E5%BC%80"
    policy = _policy(
        platform="qidian",
        origins=("https://www.qidian.com",),
        prefixes=("/book/",),
    )
    transport = RecordingTransport(_response(b"public", url=url))

    document = await _fetch_public_document()(
        transport,
        policy=policy,
        policy_hash=canonical_hash(policy),
        url=url,
        captured_at=NOW,
    )

    assert document.url == url


@pytest.mark.asyncio
async def test_document_accepts_equivalent_multiple_charset_declarations(recwarn):
    from backend.domain.json_contracts import canonical_hash

    policy = _policy(platform="qidian")
    response = _response(
        b'<?xml version="1.0" encoding="UTF8"?><meta charset="utf-8">public',
        url="https://www.qidian.com/rank/newsign/",
        headers={"content-type": "application/xhtml+xml; charset=UTF-8"},
    )

    document = await _fetch_public_document()(
        RecordingTransport(response),
        policy=policy,
        policy_hash=canonical_hash(policy),
        url="https://www.qidian.com/rank/newsign/",
        captured_at=NOW,
    )

    assert document.text.endswith("public")
    assert not recwarn


@pytest.mark.asyncio
async def test_document_uses_meta_only_supported_charset_without_replacement():
    from backend.domain.json_contracts import canonical_hash

    policy = _policy(platform="qidian")
    response = _response(
        '<meta charset="gb18030">小说排行榜'.encode("gb18030"),
        url="https://www.qidian.com/rank/newsign/",
        headers={"content-type": "text/html"},
    )

    document = await _fetch_public_document()(
        RecordingTransport(response),
        policy=policy,
        policy_hash=canonical_hash(policy),
        url="https://www.qidian.com/rank/newsign/",
        captured_at=NOW,
    )

    assert document.text.endswith("小说排行榜")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected_code"),
    (
        (b"\xff", "MARKET_HTML_UNKNOWN"),
        (b'<meta charset="utf-8"><meta charset="gbk">public', "MARKET_HTML_UNKNOWN"),
        (b"public", "MARKET_CONTENT_TYPE_REJECTED"),
    ),
)
async def test_document_rejects_invalid_bytes_conflicting_declarations_and_missing_content_type(
    body, expected_code
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure

    policy = _policy(platform="qidian")
    headers = None if body != b"public" else {}
    with pytest.raises(MarketSourceFailure) as rejected:
        await _fetch_public_document()(
            RecordingTransport(
                _response(
                    body,
                    url="https://www.qidian.com/rank/newsign/",
                    headers=headers,
                )
            ),
            policy=policy,
            policy_hash=canonical_hash(policy),
            url="https://www.qidian.com/rank/newsign/",
            captured_at=NOW,
        )

    assert rejected.value.code == expected_code


@pytest.mark.parametrize(
    "work_url",
    (
        "https://[::1",
        "https://www.qidian.com:bad/book/1",
        "/book/\x00private",
    ),
)
def test_canonical_work_url_maps_malformed_urls_to_market_failure(work_url):
    from backend.gateways.market_sources.base import (
        MarketSourceFailure,
        canonical_work_url,
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        canonical_work_url(
            work_url,
            base_url="https://www.qidian.com/rank/newsign/",
            work_origins=("https://www.qidian.com",),
        )

    assert rejected.value.code == "MARKET_URL_NOT_ALLOWED"


@pytest.mark.parametrize("fragment", ("#1", "#detail-alias"))
def test_canonical_work_url_rejects_fragments_but_preserves_legal_queries(fragment):
    from backend.gateways.market_sources.base import (
        MarketSourceFailure,
        canonical_work_url,
    )

    with pytest.raises(MarketSourceFailure) as rejected:
        canonical_work_url(
            f"/book/1{fragment}",
            base_url="https://www.qidian.com/rank/newsign/",
            work_origins=("https://www.qidian.com",),
        )

    assert rejected.value.code == "MARKET_URL_NOT_ALLOWED"
    assert canonical_work_url(
        "/book/1?rank=weekly",
        base_url="https://www.qidian.com/rank/newsign/",
        work_origins=("https://www.qidian.com",),
    ) == "https://www.qidian.com/book/1?rank=weekly"


def _market_entry(rank: int):
    from backend.domain.market import MarketEntry

    return MarketEntry(
        rank=rank,
        title=f"公开作品{rank}",
        author="公开作者",
        category="奇幻",
        workURL=f"https://www.qidian.com/book/{rank}",
        publicMetrics={},
    )


def test_market_entry_from_fields_normalizes_string_rank_with_public_keywords():
    from backend.gateways.market_sources.base import market_entry_from_fields

    entry = market_entry_from_fields(
        rank=" 1 ",
        title=" 公开作品 ",
        author=" 公开作者 ",
        category=" 奇幻 ",
        work_url="/book/1",
        metrics={"weeklyRecommendations": " 321 "},
        base_url="https://www.qidian.com/rank/newsign/",
        work_origins=("https://www.qidian.com",),
    )

    assert entry.rank == 1
    assert entry.title == "公开作品"
    assert entry.public_metrics == {"weeklyRecommendations": "321"}


@pytest.mark.asyncio
async def test_official_rank_adapter_document_accepts_bounded_detail_url():
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import OfficialRankAdapter

    class SyntheticOfficialAdapter(OfficialRankAdapter):
        source_url = "https://www.qidian.com/rank/newsign/"
        platform = "qidian"
        ranking_name = "newsign"
        category = "male"

    detail_url = "https://www.qidian.com/book/1"
    policy = _policy(
        platform="qidian",
        origins=("https://www.qidian.com",),
        prefixes=("/rank/", "/book/"),
    )
    transport = RecordingTransport(_response(b"<html>detail</html>", url=detail_url))

    document = await SyntheticOfficialAdapter(transport).document(
        detail_url,
        policy=policy,
        policy_hash=canonical_hash(policy),
        captured_at=NOW,
    )

    assert document.url == detail_url
    assert transport.requests[0].url == detail_url


def test_official_rank_adapter_snapshot_uses_rank_source_and_requires_ten_entries():
    from backend.gateways.market_sources.base import (
        MarketSourceFailure,
        OfficialRankAdapter,
    )

    class SyntheticOfficialAdapter(OfficialRankAdapter):
        source_url = "https://www.qidian.com/rank/newsign/"
        platform = "qidian"
        ranking_name = "newsign"
        category = "male"

    adapter = SyntheticOfficialAdapter(RecordingTransport(None))
    entries = tuple(_market_entry(rank) for rank in range(1, 11))

    snapshot = adapter.snapshot(entries, captured_at=NOW)

    assert snapshot.source_url == adapter.source_url
    with pytest.raises(MarketSourceFailure) as rejected:
        adapter.snapshot(entries[:9], captured_at=NOW)
    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


def test_official_rank_adapter_snapshot_rejects_duplicate_canonical_work_urls():
    from backend.domain.market import MarketEntry
    from backend.gateways.market_sources.base import (
        MarketSourceFailure,
        OfficialRankAdapter,
    )

    class SyntheticOfficialAdapter(OfficialRankAdapter):
        source_url = "https://www.qidian.com/rank/newsign/"
        platform = "qidian"
        ranking_name = "newsign"
        category = "male"

    entries = list(_market_entry(rank) for rank in range(1, 11))
    entries[1] = MarketEntry(
        rank=2,
        title="公开作品2",
        author="公开作者",
        category="奇幻",
        workURL=entries[0].work_url,
        publicMetrics={},
    )
    with pytest.raises(MarketSourceFailure) as rejected:
        SyntheticOfficialAdapter(RecordingTransport(None)).snapshot(
            tuple(entries),
            captured_at=NOW,
        )
    assert rejected.value.code == "MARKET_PAGE_INCOMPLETE"


@pytest.mark.asyncio
async def test_public_adapter_enforces_overall_wall_clock_on_slow_transport(
    monkeypatch,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources import base
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.qidian_public_rank import (
        QidianPublicRankAdapter,
    )

    class SlowDripTransport:
        def __init__(self):
            self.calls = 0
            self.cancelled = asyncio.Event()

        async def __call__(self, request):
            self.calls += 1
            try:
                while True:
                    await asyncio.sleep(0.01)
            finally:
                self.cancelled.set()

    monkeypatch.setattr(base, "TRANSPORT_TIMEOUT_SECONDS", 0.03)
    transport = SlowDripTransport()
    policy = _policy(platform="qidian")
    started = asyncio.get_running_loop().time()

    with pytest.raises(MarketSourceFailure) as timed_out:
        await QidianPublicRankAdapter(transport).fetch(
            policy=policy,
            policy_hash=canonical_hash(policy),
            captured_at=NOW,
        )

    assert asyncio.get_running_loop().time() - started < 0.3
    assert timed_out.value.code == "MARKET_TRANSPORT_TIMEOUT"
    assert transport.calls == 1
    assert transport.cancelled.is_set()


def test_snapshot_contract_rejects_duplicates_blanks_bad_urls_and_unbounded_entries():
    from backend.domain.market import MarketEntry, MarketSnapshot

    entry = MarketEntry(
        rank=1,
        title="合成作品",
        author="合成作者",
        category="奇幻",
        work_url="https://books.example/1",
        public_metrics={},
    )
    values = dict(
        platform="synthetic",
        ranking_name="popular",
        category="male",
        captured_at=NOW,
        source_url="https://books.example/rank",
        entries=(entry,),
    )

    with pytest.raises(ValidationError):
        MarketEntry(
            rank=1,
            title=" ",
            author="author",
            category="category",
            work_url="https://books.example/1",
            public_metrics={},
        )
    with pytest.raises(ValidationError):
        MarketEntry(
            rank=1,
            title="title",
            author="author",
            category="category",
            work_url="file:///private/book",
            public_metrics={},
        )
    with pytest.raises(ValidationError):
        MarketSnapshot(**{**values, "source_url": "javascript:alert(1)"})
    with pytest.raises(ValidationError):
        MarketSnapshot(**{**values, "entries": (entry, entry)})
    with pytest.raises(ValidationError):
        MarketSnapshot(
            **{
                **values,
                "entries": tuple(
                    entry.model_copy(
                        update={
                            "rank": index,
                            "work_url": f"https://books.example/{index}",
                        }
                    )
                    for index in range(1, 102)
                ),
            }
        )


def test_manual_adapter_accepts_only_strict_normalized_json():
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.manual_snapshot import (
        ManualSnapshotAdapter,
    )

    payload = {
        "platform": "qidian",
        "rankingName": "newsign",
        "category": "male",
        "capturedAt": NOW,
        "sourceURL": "https://www.qidian.com/rank/newsign/",
        "entries": [
            {
                "rank": 1,
                "title": "雾港天文钟",
                "author": "合成作者甲",
                "category": "奇幻",
                "workURL": "https://www.qidian.com/book/900000001/",
                "publicMetrics": {"weeklyRecommendations": 321},
            }
        ],
    }
    adapter = ManualSnapshotAdapter()

    snapshot = adapter.parse(payload)

    assert snapshot.entries[0].public_metrics == {"weeklyRecommendations": 321}
    with pytest.raises(MarketSourceFailure) as captured:
        adapter.parse({**payload, "rawHTML": "<secret>"})
    assert captured.value.code == "MARKET_MANUAL_SNAPSHOT_INVALID"


@pytest.mark.parametrize(
    ("adapter_key", "work_url"),
    (
        ("qidian_public_rank", "https://www.qidian.com/book/900000001/"),
        ("qq_reading_public_rank", "https://book.qq.com/book-detail/900000001"),
        ("fanqie_manual_snapshot", "https://fanqienovel.com/page/7341119980416550947"),
        ("qimao_manual_snapshot", "https://www.qimao.com/shuku/1924588-17384585090116/"),
        ("shuqi_manual_snapshot", "https://www.shuqi.com/book/7446411.html"),
    ),
)
def test_manual_sources_accept_only_their_canonical_public_work_paths(
    adapter_key,
    work_url,
):
    from backend.domain.market_sources import MarketSourceFailure
    from backend.gateways.market_sources.manual_snapshot import (
        ManualSnapshotAdapter,
    )

    payload = {
        "platform": "public_metadata",
        "rankingName": "author_import",
        "category": "all",
        "capturedAt": NOW,
        "sourceURL": "https://evidence.example/public-list",
        "entries": [
            {
                "rank": 1,
                "title": "公开作品",
                "author": "公开作者",
                "category": "公开分类",
                "workURL": work_url,
                "publicMetrics": {},
            }
        ],
    }

    snapshot = ManualSnapshotAdapter().parse(
        payload,
        adapter_key=adapter_key,
    )
    assert snapshot.entries[0].work_url == work_url

    foreign = {
        **payload,
        "entries": [
            {
                **payload["entries"][0],
                "workURL": "https://evil.example/book/7446411.html",
            }
        ],
    }
    with pytest.raises(MarketSourceFailure) as rejected:
        ManualSnapshotAdapter().parse(foreign, adapter_key=adapter_key)
    assert rejected.value.code == "MARKET_MANUAL_SNAPSHOT_INVALID"


@pytest.mark.parametrize(
    "work_url",
    (
        "https://user@www.qidian.com/book/900000001/",
        "https://www.qidian.com:443/book/900000001/",
        "https://ｗｗｗ.qidian.com/book/900000001/",
        "https://www.qidian.com/book/９０００００００１/",
        "https://www.qidian.com/book/%2e%2e/900000001/",
        "https://www.qidian.com/rank/newsign/",
    ),
)
def test_manual_adapter_rejects_noncanonical_or_out_of_boundary_work_urls(
    work_url,
):
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.manual_snapshot import (
        ManualSnapshotAdapter,
    )

    payload = {
        "platform": "qidian",
        "rankingName": "newsign",
        "category": "male",
        "capturedAt": NOW,
        "sourceURL": "https://www.qidian.com/rank/newsign/",
        "entries": [
            {
                "rank": 1,
                "title": "雾港天文钟",
                "author": "合成作者甲",
                "category": "奇幻",
                "workURL": work_url,
                "publicMetrics": {},
            }
        ],
    }

    with pytest.raises(MarketSourceFailure) as rejected:
        ManualSnapshotAdapter().parse(
            payload,
            adapter_key="qidian_public_rank",
        )

    assert rejected.value.code == "MARKET_MANUAL_SNAPSHOT_INVALID"


@pytest.mark.parametrize("field", ("sourceURL", "workURL"))
@pytest.mark.parametrize(
    "control",
    tuple(chr(value) for value in range(32)) + ("\x7f",),
)
def test_manual_adapter_rejects_all_ascii_url_controls_without_echo(
    field,
    control,
):
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.manual_snapshot import (
        ManualSnapshotAdapter,
    )

    source_url = "https://www.qidian.com/rank/newsign/"
    work_url = "https://www.qidian.com/book/900000001/"
    if field == "sourceURL":
        source_url = f"https://www.qi{control}dian.com/rank/newsign/"
    else:
        work_url = f"https://www.qidian.com/book/900{control}000001/"
    payload = {
        "platform": "qidian",
        "rankingName": "newsign",
        "category": "male",
        "capturedAt": NOW,
        "sourceURL": source_url,
        "entries": [
            {
                "rank": 1,
                "title": "雾港天文钟",
                "author": "合成作者甲",
                "category": "奇幻",
                "workURL": work_url,
                "publicMetrics": {},
            }
        ],
    }

    with pytest.raises(MarketSourceFailure) as rejected:
        ManualSnapshotAdapter().parse(
            payload,
            adapter_key="qidian_public_rank",
        )

    assert rejected.value.code == "MARKET_MANUAL_SNAPSHOT_INVALID"
    assert source_url not in str(rejected.value)
    assert work_url not in str(rejected.value)


@pytest.mark.parametrize(
    "url",
    (
        " https://www.qidian.com/book/900000001/",
        "https://www.qidian.com/book/900000001/ ",
        "https://www.qidian.com/book/900000001/?",
        "https://www.qidian.com/book/900000001/#",
    ),
)
def test_shared_public_url_validator_rejects_normalization_changes(url):
    from backend.domain.market import _public_http_url

    with pytest.raises(ValueError):
        _public_http_url(url)


@pytest.mark.parametrize("ranks", ((2, 1), (1, 3)))
def test_manual_adapter_requires_exact_increasing_rank_order(ranks):
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.manual_snapshot import (
        ManualSnapshotAdapter,
    )

    payload = {
        "platform": "qidian",
        "rankingName": "newsign",
        "category": "male",
        "capturedAt": NOW,
        "sourceURL": "https://www.qidian.com/rank/newsign/",
        "entries": [
            {
                "rank": rank,
                "title": f"合成书{index}",
                "author": "合成作者",
                "category": "奇幻",
                "workURL": f"https://www.qidian.com/book/90000000{index}/",
                "publicMetrics": {},
            }
            for index, rank in enumerate(ranks, start=1)
        ],
    }

    with pytest.raises(MarketSourceFailure) as rejected:
        ManualSnapshotAdapter().parse(
            payload,
            adapter_key="qidian_public_rank",
        )

    assert rejected.value.code == "MARKET_MANUAL_SNAPSHOT_INVALID"


def test_non_verified_policy_cannot_claim_an_enabled_schedule():
    from backend.domain.market_sources import SourcePolicy

    with pytest.raises(ValidationError):
        SourcePolicy(
            status="manual_only",
            checkedAt=NOW,
            evidenceURL="https://evidence.example/manual-only",
            evidenceHash="a" * 64,
            allowedOrigins=("https://www.qidian.com",),
            pathPrefixes=("/rank/newsign/",),
            requestIntervalSeconds=3600,
            policyVersion="public-rank-policy-v1",
            enabled=True,
        )

    with pytest.raises(ValidationError):
        SourcePolicy(
            status="verified_public",
            checkedAt=NOW,
            evidenceURL="https://evidence.example/public",
            evidenceHash="a" * 64,
            allowedOrigins=("https://www.qidian.com",),
            pathPrefixes=("/rank/newsign/",),
            requestIntervalSeconds=61,
            policyVersion="public-rank-policy-v1",
            enabled=False,
        )
