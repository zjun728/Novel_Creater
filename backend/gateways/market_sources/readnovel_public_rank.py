"""Strict single-page adapter for ReadNovel's original monthly-ticket rank."""

from __future__ import annotations

import re

from backend.gateways.market_sources.base import (
    MarketSourceFailure,
    OfficialRankAdapter,
    market_entry_from_fields,
    require_exact_work_path,
)


_WORK_PATH = re.compile(r"/book/[1-9][0-9]*")


class ReadNovelPublicRankAdapter(OfficialRankAdapter):
    source_url = "https://www.readnovel.com/rank/ywyuepiao?pageNum=1"
    platform = "readnovel"
    ranking_name = "monthly_ticket"
    category = "female"
    adapter_version = "readnovel-public-rank-v2"
    work_origins = ("https://www.readnovel.com",)

    async def fetch(self, *, policy, policy_hash, captured_at):
        document = await self.document(
            self.source_url,
            policy=policy,
            policy_hash=policy_hash,
            captured_at=captured_at,
        )
        containers = document.soup.select("div.rank-body > div.rank-view-list")
        if len(containers) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        lists = containers[0].select(":scope > .book-img-text")
        if len(lists) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        inner_lists = lists[0].find_all("ul", recursive=False)
        if len(inner_lists) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        rows = inner_lists[0].find_all(recursive=False)
        if len(rows) != 20 or any(row.name != "li" for row in rows):
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")

        entries = []
        for expected_rank, row in enumerate(rows, start=1):
            try:
                rank_node = _unique(row, "span.rank-tag")
                if _rank_from_classes(rank_node.get("class", ())) != expected_rank:
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
                title = _unique(row, ".book-mid-info h4 a[href]")
                entry = market_entry_from_fields(
                    rank=expected_rank,
                    title=_text(title),
                    author=_text(_unique(row, ".book-mid-info p.author a.name")),
                    category=_text(
                        _unique(
                            row,
                            '.book-mid-info p.author a[href^="/category/"]',
                        )
                    ),
                    work_url=title.get("href"),
                    base_url=self.source_url,
                    work_origins=self.work_origins,
                    metrics={},
                )
                require_exact_work_path(entry.work_url, _WORK_PATH)
                entries.append(entry)
            except MarketSourceFailure as failure:
                code = (
                    "MARKET_HTML_UNKNOWN"
                    if failure.code == "MARKET_HTML_UNKNOWN"
                    else "MARKET_PAGE_INCOMPLETE"
                )
                raise MarketSourceFailure(code) from None
            except Exception:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
        return self.snapshot(tuple(entries), captured_at=captured_at)


def _unique(container, selector: str):
    nodes = container.select(selector)
    if len(nodes) != 1:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return nodes[0]


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def _rank_from_classes(values: object) -> int:
    if not isinstance(values, list):
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    ranks = [
        match
        for value in values
        if (match := re.fullmatch(r"no([1-9][0-9]*)", value))
    ]
    if len(ranks) != 1:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return int(ranks[0].group(1))
