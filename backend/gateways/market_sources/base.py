"""Bounded transport and strict shared parsing support."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from html.parser import HTMLParser
import math
import re
from typing import Awaitable, Callable, Mapping
from urllib.parse import urljoin, urlsplit
import warnings

from bs4 import BeautifulSoup, Comment, XMLParsedAsHTMLWarning
from pydantic import ValidationError

from backend.domain.json_contracts import canonical_hash
from backend.domain.market import MAX_MARKET_ENTRIES, MarketEntry
from backend.domain.market_sources import MarketSourceFailure, SourcePolicy


MAX_BODY_BYTES = 512 * 1024
TRANSPORT_TIMEOUT_SECONDS = 8.0
_SUPPORTED_HTML_CHARSETS = {
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "gb2312": "gb2312",
    "gbk": "gbk",
    "gb18030": "gb18030",
}
_DOCUMENT_CHARSET = re.compile(
    r"<meta\b[^>]*\bcharset\s*=\s*[\"']?\s*([a-z0-9_-]+)",
    re.IGNORECASE,
)
_DOCUMENT_CONTENT_CHARSET = re.compile(
    r"<meta\b[^>]*\bcontent\s*=\s*[\"'][^>]*?\bcharset\s*=\s*([a-z0-9_-]+)",
    re.IGNORECASE,
)
_XML_CHARSET = re.compile(
    r"<\?xml\b[^>]*\bencoding\s*=\s*[\"']\s*([a-z0-9_-]+)",
    re.IGNORECASE,
)
_PERCENT_ESCAPE = re.compile(r"%([0-9a-f]{2})", re.IGNORECASE)
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9a-f]{2})", re.IGNORECASE)


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


@dataclass(frozen=True)
class PublicHTMLDocument:
    """One bounded, verified, non-interactive public HTML response."""

    url: str
    text: str
    soup: BeautifulSoup


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
    _ = parsed.port
    return f"{parsed.scheme}://{parsed.netloc}"


def _has_url_controls(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _path_is_unambiguous(path: str) -> bool:
    if "\\" in path or _INVALID_PERCENT_ESCAPE.search(path):
        return False
    if any(segment in {".", ".."} for segment in path.split("/")):
        return False
    return all(
        int(match.group(1), 16) not in {0x25, 0x2E, 0x2F, 0x5C, 0x7F}
        and int(match.group(1), 16) > 0x1F
        for match in _PERCENT_ESCAPE.finditer(path)
    )


def _path_matches_prefix(path: str, prefix: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(f"{prefix}/")


def _url_allowed(url: str, *, origins: tuple[str, ...], prefixes: tuple[str, ...]) -> bool:
    if _has_url_controls(url):
        return False
    try:
        parsed = urlsplit(url)
        origin = _origin(url)
    except (TypeError, ValueError):
        return False
    return (
        origin in origins
        and _path_is_unambiguous(parsed.path)
        and any(_path_matches_prefix(parsed.path, prefix) for prefix in prefixes)
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
    if captured_at - policy.checked_at < -5 * 60 * 1000:
        raise MarketSourceFailure("MARKET_POLICY_EXPIRED")
    if not _url_allowed(
        source_url,
        origins=policy.allowed_origins,
        prefixes=policy.path_prefixes,
    ):
        raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")


def normalized_public_text(value: object, limit: int = 300) -> str:
    """Return bounded display text while rejecting font-obfuscated HTML."""

    if not isinstance(value, str) or limit < 1:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    if any("\ue000" <= character <= "\uf8ff" for character in value):
        raise MarketSourceFailure("MARKET_HTML_UNKNOWN")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > limit:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    return normalized


def normalized_public_excerpt(
    value: object,
    *,
    source_limit: int,
    limit: int = 200,
) -> str:
    """Validate a bounded full field before returning its display excerpt."""

    if source_limit < limit:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    normalized = normalized_public_text(value, limit=source_limit)
    return normalized[:limit].rstrip()


def _response_charset(response: TransportResponse) -> str:
    headers = {
        str(key).casefold(): str(value)
        for key, value in response.headers.items()
    }
    content_type = headers.get("content-type", "")
    parts = tuple(part.strip() for part in content_type.split(";"))
    media_type = parts[0].casefold() if parts else ""
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise MarketSourceFailure("MARKET_CONTENT_TYPE_REJECTED")
    charsets = tuple(
        value.strip().strip("\"'").casefold()
        for part in parts[1:]
        if "=" in part
        for key, value in (part.split("=", 1),)
        if key.strip().casefold() == "charset"
    )
    if len(charsets) > 1:
        raise MarketSourceFailure("MARKET_CONTENT_TYPE_REJECTED")
    if charsets and charsets[0] not in _SUPPORTED_HTML_CHARSETS:
        raise MarketSourceFailure("MARKET_CONTENT_TYPE_REJECTED")
    return _SUPPORTED_HTML_CHARSETS[charsets[0]] if charsets else ""


def _document_charset(body: bytes) -> str:
    # Charset declarations are ASCII syntax, so this inspection never decodes
    # response text permissively.
    declaration = body[:8192].decode("latin-1")
    values = {
        _SUPPORTED_HTML_CHARSETS.get(match.group(1).casefold())
        for pattern in (
            _DOCUMENT_CHARSET,
            _DOCUMENT_CONTENT_CHARSET,
            _XML_CHARSET,
        )
        for match in pattern.finditer(declaration)
    }
    if None in values or len(values) > 1:
        raise MarketSourceFailure("MARKET_HTML_UNKNOWN")
    return values.pop() if values else ""


def _decode_html(response: TransportResponse) -> str:
    header_charset = _response_charset(response)
    document_charset = _document_charset(response.body)
    if header_charset and document_charset and header_charset != document_charset:
        raise MarketSourceFailure("MARKET_HTML_UNKNOWN")
    charset = header_charset or document_charset or "utf-8"
    try:
        return response.body.decode(charset, errors="strict")
    except UnicodeDecodeError:
        raise MarketSourceFailure("MARKET_HTML_UNKNOWN") from None


async def _bounded_transport_response(
    transport: Transport,
    *,
    policy: SourcePolicy | None,
    policy_hash: str | None,
    url: str,
    captured_at: int,
) -> TransportResponse:
    verify_transport_policy(
        policy,
        policy_hash,
        source_url=url,
        captured_at=captured_at,
    )
    request = TransportRequest(url=url)
    try:
        async with asyncio.timeout(TRANSPORT_TIMEOUT_SECONDS):
            response = await transport(request)
    except TimeoutError:
        raise MarketSourceFailure("MARKET_TRANSPORT_TIMEOUT") from None
    except MarketSourceFailure:
        raise
    except Exception:
        raise MarketSourceFailure("MARKET_TRANSPORT_FAILED") from None
    if 300 <= response.status_code < 400:
        raise MarketSourceFailure("MARKET_REDIRECT_REJECTED")
    if response.status_code != 200:
        raise MarketSourceFailure("MARKET_HTTP_FAILED")
    if response.url != url:
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
    return response


async def fetch_public_document(
    transport: Transport,
    *,
    policy: SourcePolicy | None,
    policy_hash: str | None,
    url: str,
    captured_at: int,
) -> PublicHTMLDocument:
    """Fetch only an approved public HTML document with strict decoding."""

    response = await _bounded_transport_response(
        transport,
        policy=policy,
        policy_hash=policy_hash,
        url=url,
        captured_at=captured_at,
    )
    text = _decode_html(response)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(text, "html.parser")
    excluded_tags = {"script", "style", "template", "noscript"}
    block_tags = {
        "address", "article", "aside", "blockquote", "div", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main", "nav",
        "p", "section", "table", "td", "th", "tr", "ul",
    }
    fragments: dict[int, list[str]] = {}
    for value in soup.find_all(string=True):
        if (
            isinstance(value, Comment)
            or not value.strip()
            or any(
                ancestor.name in excluded_tags
                or ancestor.has_attr("hidden")
                or str(ancestor.get("aria-hidden", "")).casefold() == "true"
                for ancestor in value.parents
            )
        ):
            continue
        container = next(
            (ancestor for ancestor in value.parents if ancestor.name in block_tags),
            value.parent,
        )
        fragments.setdefault(id(container), []).append(value.strip())
    visible_text = " ".join(" ".join(values) for values in fragments.values())
    folded = " ".join(visible_text.casefold().split())
    compact_fragments = tuple("".join(values) for values in fragments.values())
    if (
        "captcha" in folded
        or any(
            token in fragment
            for fragment in compact_fragments
            for token in ("人机验证", "请完成人机验证", "安全验证", "请登录后查看排行榜")
        )
    ):
        raise MarketSourceFailure("MARKET_INTERSTITIAL_REJECTED")
    return PublicHTMLDocument(url=response.url, text=text, soup=soup)


def canonical_work_url(
    href: object,
    *,
    base_url: str,
    work_origins: tuple[str, ...],
) -> str:
    if not isinstance(href, str) or not href.strip():
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    if _has_url_controls(href) or _has_url_controls(base_url):
        raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")
    try:
        work_url = urljoin(base_url, href.strip())
        parsed = urlsplit(work_url)
        origin = _origin(work_url)
    except (TypeError, ValueError):
        raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED") from None
    if (
        _has_url_controls(work_url)
        or parsed.fragment
        or not _path_is_unambiguous(parsed.path)
        or origin not in work_origins
    ):
        raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")
    return work_url


def require_exact_work_path(url: str, pattern: re.Pattern[str]) -> None:
    """Reject canonical same-origin URLs that are not exact work-detail paths."""

    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
    if (
        parsed.query
        or parsed.fragment
        or pattern.fullmatch(parsed.path) is None
    ):
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")


def bounded_public_metrics(
    values: object,
) -> dict[str, str | int | float | bool]:
    if not isinstance(values, Mapping) or len(values) > 32:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    normalized: dict[str, str | int | float | bool] = {}
    for key, value in values.items():
        if not isinstance(key, str):
            raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
        if isinstance(value, str):
            normalized[key] = normalized_public_text(value, limit=200)
        elif isinstance(value, bool | int):
            normalized[key] = value
        elif isinstance(value, float) and math.isfinite(value):
            normalized[key] = value
        else:
            raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    return normalized


def market_entry_from_fields(
    *,
    rank: object,
    title: object,
    author: object,
    category: object,
    work_url: object,
    base_url: str,
    work_origins: tuple[str, ...],
    metrics: object,
) -> MarketEntry:
    try:
        normalized_rank = int(str(rank).strip())
    except (TypeError, ValueError):
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID") from None
    try:
        return MarketEntry(
            rank=normalized_rank,
            title=normalized_public_text(title),
            author=normalized_public_text(author, limit=200),
            category=normalized_public_text(category, limit=160),
            work_url=canonical_work_url(
                work_url,
                base_url=base_url,
                work_origins=work_origins,
            ),
            public_metrics=bounded_public_metrics(metrics),
        )
    except MarketSourceFailure:
        raise
    except ValidationError:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID") from None


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
        self.expected_count: int | None = None
        self.container_stack: list[str] = []
        self.container_closed = False
        self.entries: list[_EntryBuilder] = []
        self.current: _EntryBuilder | None = None
        self.capture: str | None = None
        self.capture_depth = 0

    def handle_starttag(self, tag: str, attrs_list):
        attrs = dict(attrs_list)
        if attrs.get("data-market-ranking") == self.marker:
            if self.saw_marker or self.container_stack or self.container_closed:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            self.saw_marker = True
            try:
                self.expected_count = int(attrs.get("data-rank-count", ""))
            except ValueError:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
            if (
                attrs.get("data-rank-complete") != "true"
                or self.expected_count < 1
                or self.expected_count > MAX_MARKET_ENTRIES
            ):
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            self.container_stack.append(tag)
        elif self.container_stack:
            self.container_stack.append(tag)
        if not self.container_stack:
            return
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
        if self.container_stack:
            if self.container_stack[-1] != tag:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            self.container_stack.pop()
            if not self.container_stack:
                self.container_closed = True

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
    expected_ranks = (
        ()
        if parser.expected_count is None
        else tuple(range(1, parser.expected_count + 1))
    )
    actual_ranks = tuple(entry.rank for entry in parser.entries)
    if not parser.saw_marker:
        raise MarketSourceFailure("MARKET_HTML_UNKNOWN")
    if (
        not parser.container_closed
        or parser.container_stack
        or parser.current is not None
        or actual_ranks != expected_ranks
    ):
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    if len(parser.entries) > MAX_MARKET_ENTRIES:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")

    entries: list[MarketEntry] = []
    for item in parser.entries:
        entries.append(
            market_entry_from_fields(
                rank=item.rank,
                title=item.title,
                author=item.author,
                category=item.category,
                work_url=item.href,
                base_url=source_url,
                work_origins=work_origins,
                metrics=item.metrics or {},
            )
        )
    return tuple(entries)


class OfficialRankAdapter:
    """Shared boundary for official ranking adapters with complete pages."""

    source_url = ""
    platform = ""
    ranking_name = ""
    category = ""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    async def document(
        self,
        url: str,
        *,
        policy: SourcePolicy | None,
        policy_hash: str | None,
        captured_at: int,
    ) -> PublicHTMLDocument:
        return await fetch_public_document(
            self.transport,
            policy=policy,
            policy_hash=policy_hash,
            url=url,
            captured_at=captured_at,
        )

    def snapshot(
        self,
        entries: tuple[MarketEntry, ...],
        *,
        captured_at: int,
    ):
        from backend.domain.market import MarketSnapshot

        if not 10 <= len(entries) <= MAX_MARKET_ENTRIES:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        if len({entry.work_url for entry in entries}) != len(entries):
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
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


@dataclass(frozen=True)
class RankCandidate:
    """One rank-page fact that must be verified against its detail page."""

    rank: int
    title: str
    detail_url: str


class DetailEnrichedRankAdapter(OfficialRankAdapter):
    """Fetch a complete ten-work rank and enrich it serially, never beyond ten."""

    detail_limit = 10
    work_origin = ""
    work_origins: tuple[str, ...] = ()

    async def fetch(
        self,
        *,
        policy: SourcePolicy | None,
        policy_hash: str | None,
        captured_at: int,
    ):
        rank_page = await self.document(
            self.source_url,
            policy=policy,
            policy_hash=policy_hash,
            captured_at=captured_at,
        )
        try:
            candidates = tuple(self.parse_rank_candidates(rank_page))
        except MarketSourceFailure:
            raise
        except Exception:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
        if self.detail_limit != 10:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        selected = candidates[:10]
        if len(selected) != 10:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")

        origins = self.work_origins or ((self.work_origin,) if self.work_origin else ())
        if not origins:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        validated_candidates: list[tuple[RankCandidate, str, str]] = []
        for expected_rank, candidate in enumerate(selected, start=1):
            if (
                not isinstance(candidate, RankCandidate)
                or candidate.rank != expected_rank
            ):
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            try:
                expected_title = normalized_public_text(candidate.title)
                detail_url = canonical_work_url(
                    candidate.detail_url,
                    base_url=self.source_url,
                    work_origins=origins,
                )
            except MarketSourceFailure:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
            validated_candidates.append((candidate, detail_url, expected_title))
        if len({detail_url for _, detail_url, _ in validated_candidates}) != 10:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        for _, detail_url, _ in validated_candidates:
            try:
                verify_transport_policy(
                    policy,
                    policy_hash,
                    source_url=detail_url,
                    captured_at=captured_at,
                )
            except MarketSourceFailure as failure:
                if failure.code == "MARKET_URL_NOT_ALLOWED":
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
                raise

        entries: list[MarketEntry] = []
        detail_requests = 0
        for expected_rank, (candidate, detail_url, expected_title) in enumerate(
            validated_candidates,
            start=1,
        ):
            if detail_requests >= 10:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            detail_requests += 1
            detail_page = await self.document(
                detail_url,
                policy=policy,
                policy_hash=policy_hash,
                captured_at=captured_at,
            )
            try:
                entry = self.parse_detail(candidate, detail_page)
                if (
                    not isinstance(entry, MarketEntry)
                    or entry.rank != expected_rank
                    or entry.title != expected_title
                    or entry.work_url != detail_url
                ):
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            except MarketSourceFailure:
                raise
            except Exception:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
            entries.append(entry)
        return self.snapshot(tuple(entries), captured_at=captured_at)

    def parse_rank_candidates(self, rank_page: PublicHTMLDocument):
        raise NotImplementedError

    def parse_detail(
        self,
        candidate: RankCandidate,
        detail_page: PublicHTMLDocument,
    ) -> MarketEntry:
        raise NotImplementedError


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

        document = await fetch_public_document(
            self.transport,
            policy=policy,
            policy_hash=policy_hash,
            url=self.source_url,
            captured_at=captured_at,
        )
        entries = parse_marked_entries(
            document.text,
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
