from __future__ import annotations

import asyncio
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


def _policy(*, platform: str, status: str = "verified_public", checked_at=NOW - 1_000):
    from backend.domain.market_sources import SourcePolicy

    if platform == "qidian":
        origins = ("https://www.qidian.com",)
        prefixes = ("/rank/newsign/",)
    else:
        origins = ("https://book.qq.com",)
        prefixes = ("/book-rank",)
    return SourcePolicy(
        status=status,
        checkedAt=checked_at,
        evidenceURL="https://evidence.example/public-policy",
        evidenceHash="a" * 64,
        allowedOrigins=origins,
        pathPrefixes=prefixes,
        requestIntervalSeconds=3600,
        policyVersion="public-rank-policy-v1",
        enabled=False,
    )


def _response(body: bytes, *, url: str, status=200, headers=None):
    from backend.gateways.market_sources.base import TransportResponse

    return TransportResponse(
        status_code=status,
        url=url,
        headers=headers or {"content-type": "text/html; charset=utf-8"},
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
        (
            "QQReadingPublicRankAdapter",
            "qq_male_popular.html",
            "https://book.qq.com/book-rank",
            "qq_reading",
            "盐原回声",
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
    from backend.gateways.market_sources.qq_reading_public_rank import (
        QQReadingPublicRankAdapter,
    )

    adapter_class = {
        "QidianPublicRankAdapter": QidianPublicRankAdapter,
        "QQReadingPublicRankAdapter": QQReadingPublicRankAdapter,
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
        (
            "QQReadingPublicRankAdapter",
            "qq_male_popular.html",
            "https://book.qq.com/book-rank",
            "qq_reading",
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
    from backend.gateways.market_sources.qq_reading_public_rank import (
        QQReadingPublicRankAdapter,
    )

    adapter_class = {
        "QidianPublicRankAdapter": QidianPublicRankAdapter,
        "QQReadingPublicRankAdapter": QQReadingPublicRankAdapter,
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
            lambda: _policy(platform="qidian", checked_at=1),
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
        "text/html; charset=gbk",
        "text/html; charset = gbk",
        "",
    ),
)
async def test_public_adapter_requires_approved_utf8_html_content_type(
    content_type,
):
    from backend.domain.json_contracts import canonical_hash
    from backend.gateways.market_sources.base import MarketSourceFailure
    from backend.gateways.market_sources.qidian_public_rank import (
        QidianPublicRankAdapter,
    )

    policy = _policy(platform="qidian")
    headers = (
        {"x-synthetic-header": "present"}
        if not content_type
        else {"content-type": content_type}
    )
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
