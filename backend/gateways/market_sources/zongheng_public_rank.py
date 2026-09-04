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
        containers = rank_page.soup.select(".zh-modules-rank-box")
        if len(containers) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        rows = [
            child
            for child in containers[0].find_all(recursive=False)
            if "zh-modules-rank-book" in child.get("class", ())
        ]
        candidates: list[RankCandidate] = []
        for row in rows:
            titles = row.select(".book-rank--title a[href]")
            ranks = row.select(".book-rank--num")
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


def _rank(value: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return int(value)
