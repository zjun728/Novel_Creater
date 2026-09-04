"""Fail-closed adapter for Fanqie's public reading rank."""

import re
from urllib.parse import urlsplit

from backend.gateways.market_sources.base import (
    MarketSourceFailure,
    OfficialRankAdapter,
    market_entry_from_fields,
    normalized_public_text,
)


_WORK_PATH = re.compile(r"/page/[0-9]+")


class FanqiePublicRankAdapter(OfficialRankAdapter):
    source_url = "https://fanqienovel.com/rank/1"
    platform = "fanqie"
    ranking_name = "reading"
    category = "all"
    adapter_version = "fanqie-public-rank-v1"
    work_origins = ("https://fanqienovel.com",)

    async def fetch(self, *, policy, policy_hash, captured_at):
        document = await self.document(
            self.source_url,
            policy=policy,
            policy_hash=policy_hash,
            captured_at=captured_at,
        )
        matched_rows = document.soup.select(".rank-book-item")
        if not matched_rows:
            raise MarketSourceFailure("MARKET_HTML_UNKNOWN")
        parents = {id(row.parent) for row in matched_rows if row.parent is not None}
        if len(parents) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        parent = matched_rows[0].parent
        assert parent is not None
        rows = [
            child
            for child in parent.find_all(recursive=False)
            if "rank-book-item" in child.get("class", ())
        ]
        if {id(row) for row in rows} != {id(row) for row in matched_rows}:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")

        entries = []
        for row in rows:
            rank = _required_text(row, ".rank-number")
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
        if [entry.rank for entry in entries] != list(range(1, len(entries) + 1)):
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
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
