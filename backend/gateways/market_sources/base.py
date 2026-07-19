"""Bounded transport and strict shared parsing support."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
from typing import Awaitable, Callable, Mapping
from urllib.parse import urljoin, urlsplit

from pydantic import ValidationError

from backend.domain.json_contracts import canonical_hash
from backend.domain.market import MAX_MARKET_ENTRIES, MarketEntry
from backend.domain.market_sources import MarketSourceFailure, SourcePolicy


MAX_BODY_BYTES = 512 * 1024
TRANSPORT_TIMEOUT_SECONDS = 8.0
MAX_POLICY_AGE_MS = 30 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class TransportRequest:
    url: str
    timeout_seconds: float = TRANSPORT_TIMEOUT_SECONDS
    max_body_bytes: int = MAX_BODY_BYTES
    follow_redirects: bool = False


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    url: str
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[TransportRequest], Awaitable[TransportResponse]]


class HttpxMarketTransport:
    """Production transport that refuses redirects and bounds streamed bytes."""

    async def __call__(self, request: TransportRequest) -> TransportResponse:
        import httpx

        try:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                async with client.stream(
                    "GET",
                    request.url,
                    timeout=request.timeout_seconds,
                    headers={
                        "Accept": "text/html,application/xhtml+xml",
                        "User-Agent": "NovelCreator-PublicMarket/1.0",
                    },
                ) as response:
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > request.max_body_bytes:
                            raise MarketSourceFailure("MARKET_BODY_TOO_LARGE")
                        chunks.append(chunk)
                    return TransportResponse(
                        status_code=response.status_code,
                        url=str(response.url),
                        headers=dict(response.headers),
                        body=b"".join(chunks),
                    )
        except MarketSourceFailure:
            raise
        except Exception:
            raise MarketSourceFailure("MARKET_TRANSPORT_FAILED") from None


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _url_allowed(url: str, *, origins: tuple[str, ...], prefixes: tuple[str, ...]) -> bool:
    parsed = urlsplit(url)
    return _origin(url) in origins and any(
        parsed.path.startswith(prefix) for prefix in prefixes
    )


def verify_transport_policy(
    policy: SourcePolicy | None,
    policy_hash: str | None,
    *,
    source_url: str,
    captured_at: int,
) -> None:
    """Reject all non-verifiable policy states before transport opens."""

    if policy is None:
        raise MarketSourceFailure("MARKET_POLICY_MISSING")
    if policy.status != "verified_public":
        raise MarketSourceFailure("MARKET_POLICY_NOT_VERIFIED")
    if policy_hash != canonical_hash(policy):
        raise MarketSourceFailure("MARKET_POLICY_HASH_INVALID")
    age = captured_at - policy.checked_at
    if age < -5 * 60 * 1000 or age > MAX_POLICY_AGE_MS:
        raise MarketSourceFailure("MARKET_POLICY_EXPIRED")
    if not _url_allowed(
        source_url,
        origins=policy.allowed_origins,
        prefixes=policy.path_prefixes,
    ):
        raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")


@dataclass
class _EntryBuilder:
    rank: int
    title: str = ""
    author: str = ""
    category: str = ""
    href: str = ""
    metrics: dict[str, str | int | float | bool] | None = None


class NormalizedRankHTMLParser(HTMLParser):
    """Parse only explicit public-rank markers; unknown layouts are rejected."""

    def __init__(self, marker: str) -> None:
        super().__init__(convert_charrefs=True)
        self.marker = marker
        self.saw_marker = False
        self.entries: list[_EntryBuilder] = []
        self.current: _EntryBuilder | None = None
        self.capture: str | None = None
        self.capture_depth = 0

    def handle_starttag(self, tag: str, attrs_list):
        attrs = dict(attrs_list)
        if attrs.get("data-market-ranking") == self.marker:
            self.saw_marker = True
        if "data-rank-entry" in attrs:
            if self.current is not None:
                raise MarketSourceFailure("MARKET_HTML_UNKNOWN")
            try:
                rank = int(attrs.get("data-rank", ""))
            except ValueError:
                raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID") from None
            self.current = _EntryBuilder(rank=rank, metrics={})
        if self.current is None:
            return
        if "data-book-title" in attrs:
            self.current.href = attrs.get("href", "")
            self.capture = "title"
            self.capture_depth = 1
        elif "data-book-author" in attrs:
            self.capture = "author"
            self.capture_depth = 1
        elif "data-book-category" in attrs:
            self.capture = "category"
            self.capture_depth = 1
        elif "data-public-metric" in attrs:
            name = attrs.get("data-public-metric", "")
            raw_value = attrs.get("data-value", "").strip()
            value: str | int = int(raw_value) if re.fullmatch(r"-?\d+", raw_value) else raw_value
            assert self.current.metrics is not None
            self.current.metrics[name] = value
        elif self.capture is not None:
            self.capture_depth += 1

    def handle_endtag(self, tag: str):
        if self.capture is not None:
            self.capture_depth -= 1
            if self.capture_depth <= 0:
                self.capture = None
                self.capture_depth = 0
        if tag == "article" and self.current is not None:
            self.entries.append(self.current)
            self.current = None
            self.capture = None
            self.capture_depth = 0

    def handle_data(self, data: str):
        if self.current is None or self.capture is None:
            return
        current = getattr(self.current, self.capture)
        setattr(self.current, self.capture, current + data)


def parse_marked_entries(
    text: str,
    *,
    marker: str,
    source_url: str,
    work_origins: tuple[str, ...],
) -> tuple[MarketEntry, ...]:
    parser = NormalizedRankHTMLParser(marker)
    try:
        parser.feed(text)
        parser.close()
    except MarketSourceFailure:
        raise
    except Exception:
        raise MarketSourceFailure("MARKET_HTML_UNKNOWN") from None
    if not parser.saw_marker or not parser.entries or parser.current is not None:
        raise MarketSourceFailure("MARKET_HTML_UNKNOWN")
    if len(parser.entries) > MAX_MARKET_ENTRIES:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")

    entries: list[MarketEntry] = []
    try:
        for item in parser.entries:
            work_url = urljoin(source_url, item.href.strip())
            if _origin(work_url) not in work_origins:
                raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")
            entries.append(
                MarketEntry(
                    rank=item.rank,
                    title=item.title.strip(),
                    author=item.author.strip(),
                    category=item.category.strip(),
                    work_url=work_url,
                    public_metrics=item.metrics or {},
                )
            )
    except MarketSourceFailure:
        raise
    except ValidationError:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID") from None
    return tuple(entries)


class PublicRankAdapter:
    source_url = ""
    platform = ""
    ranking_name = ""
    category = ""
    marker = ""
    adapter_version = ""
    work_origins: tuple[str, ...] = ()

    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    async def fetch(
        self,
        *,
        policy: SourcePolicy | None,
        policy_hash: str | None,
        captured_at: int,
    ):
        from backend.domain.market import MarketSnapshot

        verify_transport_policy(
            policy,
            policy_hash,
            source_url=self.source_url,
            captured_at=captured_at,
        )
        request = TransportRequest(url=self.source_url)
        try:
            response = await self.transport(request)
        except MarketSourceFailure:
            raise
        except Exception:
            raise MarketSourceFailure("MARKET_TRANSPORT_FAILED") from None
        if 300 <= response.status_code < 400:
            raise MarketSourceFailure("MARKET_REDIRECT_REJECTED")
        if response.status_code != 200:
            raise MarketSourceFailure("MARKET_HTTP_FAILED")
        if response.url != self.source_url:
            raise MarketSourceFailure("MARKET_REDIRECT_REJECTED")
        assert policy is not None
        if not _url_allowed(
            response.url,
            origins=policy.allowed_origins,
            prefixes=policy.path_prefixes,
        ):
            raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")
        if len(response.body) > request.max_body_bytes:
            raise MarketSourceFailure("MARKET_BODY_TOO_LARGE")
        try:
            text = response.body.decode("utf-8")
        except UnicodeDecodeError:
            raise MarketSourceFailure("MARKET_HTML_UNKNOWN") from None
        folded = " ".join(text.casefold().split())
        if any(
            token in folded
            for token in ("captcha", "请登录", "登录后", "人机验证", "安全验证")
        ):
            raise MarketSourceFailure("MARKET_INTERSTITIAL_REJECTED")
        entries = parse_marked_entries(
            text,
            marker=self.marker,
            source_url=self.source_url,
            work_origins=self.work_origins,
        )
        try:
            return MarketSnapshot(
                platform=self.platform,
                ranking_name=self.ranking_name,
                category=self.category,
                captured_at=captured_at,
                source_url=self.source_url,
                entries=entries,
            )
        except ValidationError:
            raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID") from None
