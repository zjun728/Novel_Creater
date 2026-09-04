"""Strict, bounded adapter for Zongheng's public monthly-ticket ranking."""

from __future__ import annotations

import re

from bs4 import Comment

from backend.gateways.market_sources.base import (
    DetailEnrichedRankAdapter,
    MarketSourceFailure,
    RankCandidate,
    canonical_work_url,
    market_entry_from_fields,
    normalized_public_text,
    require_exact_work_path,
)


_WORK_PATH = re.compile(r"/detail/[1-9][0-9]*")
_HEADING_TAGS = frozenset(("h1", "h2", "h3", "h4", "h5", "h6", "header"))
_NONVISIBLE_TAGS = frozenset(("script", "style", "template", "noscript"))


class ZonghengPublicRankAdapter(DetailEnrichedRankAdapter):
    source_url = "https://www.zongheng.com/rank?nav=default"
    platform = "zongheng"
    ranking_name = "monthly_ticket"
    category = "all"
    adapter_version = "zongheng-public-rank-v2"
    work_origin = "https://www.zongheng.com"
    work_origins = (work_origin,)

    def parse_rank_candidates(self, rank_page):
        containers = _monthly_ticket_containers(
            rank_page.soup.select(".zh-modules-rank-box")
        )
        if len(containers) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        rows = [
            child
            for child in containers[0].find_all(recursive=False)
            if "zh-modules-rank-book" in child.get("class", ())
        ]
        candidates: list[RankCandidate] = []
        for position, row in enumerate(rows, start=1):
            titles = row.select(".book-rank--title a[href]")
            ranks = row.select(".book-rank--num")
            if len(titles) != 1 or len(ranks) != 1:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            try:
                detail_url = canonical_work_url(
                    titles[0].get("href"),
                    base_url=self.source_url,
                    work_origins=self.work_origins,
                )
                require_exact_work_path(detail_url, _WORK_PATH)
            except MarketSourceFailure:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
            candidates.append(
                RankCandidate(
                    rank=_rank(ranks[0], position=position),
                    title=_text(titles[0]),
                    detail_url=detail_url,
                )
            )
        return tuple(candidates)

    def parse_detail(self, candidate, detail_page):
        try:
            title = _meta(detail_page.soup, "name", "og:novel:book_name")
            if title != normalized_public_text(candidate.title):
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            if canonical_work_url(
                _meta(detail_page.soup, "name", "og:novel:read_url"),
                base_url=detail_page.url,
                work_origins=self.work_origins,
            ) != detail_page.url:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            return market_entry_from_fields(
                rank=candidate.rank,
                title=title,
                author=_meta(detail_page.soup, "name", "og:novel:author"),
                category=_meta(detail_page.soup, "name", "og:novel:category"),
                work_url=detail_page.url,
                base_url=detail_page.url,
                work_origins=self.work_origins,
                metrics={
                    "status": _meta(detail_page.soup, "name", "og:novel:status"),
                    "description": _meta(detail_page.soup, "name", "og:description"),
                    "tags": _required_text(detail_page.soup, ".book-info--tags"),
                    "numbers": _required_text(detail_page.soup, ".book-info--nums"),
                },
            )
        except MarketSourceFailure:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
        except Exception:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None


def _meta(soup, attribute: str, name: str) -> str:
    nodes = soup.find_all("meta", attrs={attribute: name})
    if len(nodes) != 1:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return normalized_public_text(nodes[0].get("content"), limit=300)


def _required_text(soup, selector: str) -> str:
    nodes = soup.select(selector)
    if len(nodes) != 1:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return normalized_public_text(_text(nodes[0]), limit=200)


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def _monthly_ticket_containers(containers):
    matched = []
    for container in containers:
        headings = [
            child
            for child in container.find_all(recursive=False)
            if child.name in _HEADING_TAGS
            and "rank-heading" in child.get("class", ())
            and _is_visible(child, container)
        ]
        markers = [
            heading
            for heading in headings
            if _visible_text(heading) == "月票榜"
        ]
        if len(markers) > 1 or (markers and len(headings) != 1):
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        if markers:
            matched.append(container)
    return matched


def _is_visible(node, boundary) -> bool:
    current = node
    while current is not None:
        if (
            current.name in _NONVISIBLE_TAGS
            or current.has_attr("hidden")
            or str(current.get("aria-hidden", "")).casefold() == "true"
        ):
            return False
        if current is boundary:
            return True
        current = current.parent
    return False


def _visible_text(heading) -> str:
    fragments = []
    for node in heading.find_all(string=True):
        if isinstance(node, Comment) or not _is_visible(node.parent, heading.parent):
            continue
        value = " ".join(str(node).split())
        if value:
            fragments.append(value)
    raw = " ".join(fragments)
    return normalized_public_text(raw, limit=50) if raw else ""


def _rank(node, *, position: int) -> int:
    value = _text(node)
    elements = node.find_all(recursive=False)
    if position <= 3:
        if value or len(elements) != 1 or elements[0].name != "img":
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        return position
    if elements or value != f"{position:02d}" or re.fullmatch(r"[0-9]{2}", value) is None:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return position
