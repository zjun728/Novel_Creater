"""Strict single-page adapter for Heiyan's daily recommendation ranking."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from backend.gateways.market_sources.base import (
    MarketSourceFailure,
    OfficialRankAdapter,
    market_entry_from_fields,
)


_WORK_PATH = re.compile(r"/book/[1-9][0-9]*")


class HeiyanPublicRankAdapter(OfficialRankAdapter):
    source_url = "https://www.heiyan.com/top/monthly/day?rank=13"
    platform = "heiyan"
    ranking_name = "daily_recommendation"
    category = "all"
    adapter_version = "heiyan-public-rank-v2"
    work_origins = ("https://www.heiyan.com",)

    async def fetch(self, *, policy, policy_hash, captured_at):
        document = await self.document(
            self.source_url,
            policy=policy,
            policy_hash=policy_hash,
            captured_at=captured_at,
        )
        containers = document.soup.select(
            ".mod.mod-clean.update-list > .bd > table"
        )
        if len(containers) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        bodies = containers[0].select(":scope > tbody#tbody")
        if len(bodies) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        rows = bodies[0].select(":scope > tr")
        if len(rows) < 10:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")

        entries = []
        for expected_rank, row in enumerate(rows, start=1):
            try:
                cells = row.find_all("td", recursive=False)
                if len(cells) != 6:
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
                title = _unique(cells[2], "div.range a.name[data-collect-index]")
                rank = _rank(title.get("data-collect-index"))
                if rank != expected_rank:
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
                entry = market_entry_from_fields(
                    rank=rank,
                    title=_text(title),
                    author=_text(_unique(cells[3], "div.range a.author")),
                    category=_text(_unique(cells[1], "a.tag")),
                    work_url=title.get("href"),
                    base_url=self.source_url,
                    work_origins=self.work_origins,
                    metrics={
                        "recommendation": _text(_unique(cells[4], "div")),
                        "updatedAt": _text(_unique(cells[5], "span.time")),
                    },
                )
                _require_work_path(entry.work_url)
                entries.append(entry)
            except MarketSourceFailure:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
            except Exception:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
        return self.snapshot(tuple(entries[:10]), captured_at=captured_at)


def _unique(container, selector: str):
    nodes = container.select(selector)
    if len(nodes) != 1:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return nodes[0]


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def _rank(value: object) -> int:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[1-9][0-9]*", value) is None
    ):
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return int(value)


def _require_work_path(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment or _WORK_PATH.fullmatch(parsed.path) is None:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
