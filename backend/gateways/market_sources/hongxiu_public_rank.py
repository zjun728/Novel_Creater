"""Fail-closed adapter for Hongxiu's observed public rank shape."""

import re
from urllib.parse import urlsplit

from backend.gateways.market_sources.base import (
    MarketSourceFailure,
    OfficialRankAdapter,
    market_entry_from_fields,
    normalized_public_text,
)


_WORK_PATH = re.compile(r"/book/[0-9]+\.html")


class HongxiuPublicRankAdapter(OfficialRankAdapter):
    source_url = "https://www.hongxiu.com/rank"
    platform = "hongxiu"
    ranking_name = "rank"
    category = "all"
    adapter_version = "hongxiu-public-rank-v1"
    work_origins = ("https://www.hongxiu.com",)

    async def fetch(self, *, policy, policy_hash, captured_at):
        document = await self.document(
            self.source_url,
            policy=policy,
            policy_hash=policy_hash,
            captured_at=captured_at,
        )
        containers = document.soup.select(".rank-list .book-rank-list")
        if len(containers) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        rows = [
            row
            for row in containers[0].find_all(recursive=False)
            if "rank-book-item" in row.get("class", ())
        ]
        entries = []
        for rank, row in enumerate(rows, start=1):
            title = _required_node(row, "a.book-name[href]")
            author = _required_text(row, ".author-name")
            category = _required_text(row, ".book-category")
            try:
                entry = market_entry_from_fields(
                    rank=rank,
                    title=_text(title),
                    author=author,
                    category=category,
                    work_url=title.get("href"),
                    base_url=self.source_url,
                    work_origins=self.work_origins,
                    metrics={},
                )
                parsed = urlsplit(entry.work_url)
                if not _WORK_PATH.fullmatch(parsed.path) or parsed.query:
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
                entries.append(entry)
            except MarketSourceFailure as failure:
                if failure.code == "MARKET_HTML_UNKNOWN":
                    raise
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
        return self.snapshot(tuple(entries), captured_at=captured_at)


def _required_node(row, selector: str):
    nodes = row.select(selector)
    for node in nodes:
        normalized_public_text(_text(node))
    if len(nodes) != 1:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return nodes[0]


def _required_text(row, selector: str) -> str:
    return normalized_public_text(_text(_required_node(row, selector)))


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""
