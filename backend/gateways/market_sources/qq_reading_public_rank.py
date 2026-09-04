"""Official QQ Reading public ranking adapter."""

from backend.gateways.market_sources.base import (
    MarketSourceFailure,
    OfficialRankAdapter,
    market_entry_from_fields,
    normalized_public_excerpt,
)


class QQReadingPublicRankAdapter(OfficialRankAdapter):
    source_url = "https://book.qq.com/book-rank"
    platform = "qq_reading"
    ranking_name = "male_popular"
    category = "male"
    adapter_version = "qq-reading-public-rank-v1"
    work_origins = ("https://book.qq.com",)

    async def fetch(self, *, policy, policy_hash, captured_at):
        document = await self.document(
            self.source_url,
            policy=policy,
            policy_hash=policy_hash,
            captured_at=captured_at,
        )
        containers = [
            container
            for container in document.soup.select(
                ".book-rank.main > .tabs > .tabs-content"
            )
            if _direct_rank_books(container)
        ]
        if len(containers) != 1:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        rows = _direct_rank_books(containers[0])[:100]
        entries = []
        for rank, row in enumerate(rows, start=1):
            author_category = row.select(".other object a")
            metadata = row.select(".other span")
            try:
                entries.append(
                    market_entry_from_fields(
                        rank=rank,
                        title=_text(row.select_one(".title")),
                        author=_text_at(author_category, 0),
                        category=_text_at(author_category, 1),
                        work_url=(row.select_one("a.wrap[href]") or {}).get("href"),
                        base_url=self.source_url,
                        work_origins=self.work_origins,
                        metrics={
                            "intro": normalized_public_excerpt(
                                _text(row.select_one(".intro")),
                                source_limit=2_000,
                            ),
                            "status": _text_at(metadata, 0),
                            "wordCount": _text_at(metadata, 1),
                        },
                    )
                )
            except MarketSourceFailure:
                raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE") from None
        return self.snapshot(tuple(entries), captured_at=captured_at)


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def _text_at(nodes, index: int) -> str:
    return _text(nodes[index]) if len(nodes) > index else ""


def _direct_rank_books(container):
    return [
        child
        for child in container.children
        if getattr(child, "name", None) is not None
        and "rank-book" in child.get("class", ())
    ]
