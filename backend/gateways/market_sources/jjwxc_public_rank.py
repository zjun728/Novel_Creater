"""Official JJWXC public ranking adapter."""

from backend.gateways.market_sources.base import (
    MarketSourceFailure,
    OfficialRankAdapter,
    market_entry_from_fields,
)


class JJWXCPublicRankAdapter(OfficialRankAdapter):
    source_url = "https://www.jjwxc.net/topten.php?orderstr=4"
    platform = "jjwxc"
    ranking_name = "quarterly_score"
    category = "female"
    adapter_version = "jjwxc-public-rank-v1"
    work_origins = ("https://www.jjwxc.net",)

    async def fetch(self, *, policy, policy_hash, captured_at):
        document = await self.document(
            self.source_url,
            policy=policy,
            policy_hash=policy_hash,
            captured_at=captured_at,
        )
        rows = document.soup.select("tr:has(a.tooltip)")[:100]
        entries = []
        for row in rows:
            cells = row.find_all("td", recursive=False)
            if len(cells) != 8:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            title = cells[2].select_one("a.tooltip[href]")
            if title is None:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            try:
                entries.append(
                    market_entry_from_fields(
                        rank=_text(cells[0]),
                        title=_text(title),
                        author=_text(cells[1]),
                        category=_text(cells[3]),
                        work_url=(title or {}).get("href"),
                        base_url=self.source_url,
                        work_origins=self.work_origins,
                        metrics={
                            "status": _text(cells[4]),
                            "wordCount": _text(cells[5]),
                            "score": _text(cells[6]),
                            "publishedAt": _text(cells[7]),
                        },
                    )
                )
            except MarketSourceFailure:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
        _require_consecutive_ranks(entries)
        return self.snapshot(tuple(entries), captured_at=captured_at)


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def _require_consecutive_ranks(entries) -> None:
    if tuple(entry.rank for entry in entries) != tuple(range(1, len(entries) + 1)):
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
