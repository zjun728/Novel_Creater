"""Official Qimao public ranking adapter."""

from backend.gateways.market_sources.base import (
    MarketSourceFailure,
    OfficialRankAdapter,
    market_entry_from_fields,
    normalized_public_excerpt,
)


class QimaoPublicRankAdapter(OfficialRankAdapter):
    source_url = "https://www.qimao.com/paihang/boy/update/date/"
    platform = "qimao"
    ranking_name = "boy_update"
    category = "male"
    adapter_version = "qimao-public-rank-v1"
    work_origins = ("https://www.qimao.com",)

    async def fetch(self, *, policy, policy_hash, captured_at):
        document = await self.document(
            self.source_url,
            policy=policy,
            policy_hash=policy_hash,
            captured_at=captured_at,
        )
        rows = document.soup.select(".rank-list-item")[:100]
        entries = []
        for row in rows:
            details = row.select(".s-book-info a")
            metrics = [
                metric
                for metric in row.select(".s-book-info em")
                if not metric.has_attr("class") and _text(metric)
            ]
            title = row.select_one(".s-book-title[href]")
            if len(metrics) != 2:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
            try:
                entries.append(
                    market_entry_from_fields(
                        rank=_text(row.select_one(".rank-number")),
                        title=_text(title),
                        author=_text_at(details, 0),
                        category=_text_at(details, 1),
                        work_url=(title or {}).get("href"),
                        base_url=self.source_url,
                        work_origins=self.work_origins,
                        metrics={
                            "status": _text_at(metrics, 0),
                            "wordCount": _text_at(metrics, 1),
                            "intro": normalized_public_excerpt(
                                _text(row.select_one(".s-book-intro")),
                                source_limit=2_000,
                            ),
                        },
                    )
                )
            except MarketSourceFailure:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
        _require_consecutive_ranks(entries)
        return self.snapshot(tuple(entries), captured_at=captured_at)


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def _text_at(nodes, index: int) -> str:
    return _text(nodes[index]) if len(nodes) > index else ""


def _require_consecutive_ranks(entries) -> None:
    if tuple(entry.rank for entry in entries) != tuple(range(1, len(entries) + 1)):
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
