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
