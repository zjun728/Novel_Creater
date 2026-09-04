"""Strict, bounded adapter for Zongheng's public default ranking."""

from __future__ import annotations

import re

from backend.gateways.market_sources.base import (
    DetailEnrichedRankAdapter,
    MarketSourceFailure,
    RankCandidate,
    canonical_work_url,
    market_entry_from_fields,
    normalized_public_text,
)


class ZonghengPublicRankAdapter(DetailEnrichedRankAdapter):
    source_url = "https://www.zongheng.com/rank?nav=default"
    platform = "zongheng"
    ranking_name = "default"
    category = "all"
    adapter_version = "zongheng-public-rank-v1"
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
            candidates.append(
                RankCandidate(
                    rank=_rank(ranks[0], position=position),
                    title=_text(titles[0]),
                    detail_url=titles[0].get("href"),
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
        markers = [
            node
            for node in container.find_all(string=True)
            if " ".join(str(node).split()) == "月票榜"
            and not _inside_rank_row(node, container)
        ]
        if len(markers) > 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        if markers:
            matched.append(container)
    return matched


def _inside_rank_row(node, container) -> bool:
    parent = node.parent
    while parent is not None and parent is not container:
        if "zh-modules-rank-book" in parent.get("class", ()):
            return True
        parent = parent.parent
    return False


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
