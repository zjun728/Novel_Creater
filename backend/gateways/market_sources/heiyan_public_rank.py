"""Strict, bounded adapter for Heiyan's public top ranking."""

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


class HeiyanPublicRankAdapter(DetailEnrichedRankAdapter):
    source_url = "https://www.heiyan.com/top/"
    platform = "heiyan"
    ranking_name = "top"
    category = "all"
    adapter_version = "heiyan-public-rank-v1"
    work_origin = "https://www.heiyan.com"
    work_origins = (work_origin,)

    def parse_rank_candidates(self, rank_page):
        containers = rank_page.soup.select(".pattern-rank")
        if len(containers) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        candidates: list[RankCandidate] = []
        for row in containers[0].find_all(recursive=False):
            titles = row.select("a.name[href]")
            ranks = row.select(".rank-num")
            if len(titles) != 1 or len(ranks) != 1:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            candidates.append(
                RankCandidate(
                    rank=_rank(_text(ranks[0])),
                    title=_text(titles[0]),
                    detail_url=titles[0].get("href"),
                )
            )
        return tuple(candidates)

    def parse_detail(self, candidate, detail_page):
        try:
            title = _meta(detail_page.soup, "og:novel:book_name")
            if title != normalized_public_text(candidate.title):
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            if canonical_work_url(
                _meta(detail_page.soup, "og:novel:read_url"),
                base_url=detail_page.url,
                work_origins=self.work_origins,
            ) != detail_page.url:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            return market_entry_from_fields(
                rank=candidate.rank,
                title=title,
                author=_meta(detail_page.soup, "og:novel:author"),
                category=_meta(detail_page.soup, "og:novel:category"),
                work_url=detail_page.url,
                base_url=detail_page.url,
                work_origins=self.work_origins,
                metrics={
                    "status": _meta(detail_page.soup, "og:novel:status"),
                    "description": _meta(detail_page.soup, "og:description"),
                    "counters": _required_counters(detail_page.soup),
                },
            )
        except MarketSourceFailure:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
        except Exception:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None


def _meta(soup, name: str) -> str:
    nodes = soup.find_all("meta", attrs={"property": name})
    if len(nodes) != 1:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return normalized_public_text(nodes[0].get("content"), limit=300)


def _required_counters(soup) -> str:
    containers = soup.select(".book-info")
    if len(containers) != 1:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    nodes = containers[0].select(".book-count")
    if not nodes:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return normalized_public_text(" ".join(_text(node) for node in nodes), limit=200)


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def _rank(value: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return int(value)
