"""Strict single-page adapter for XXSY's Xiaoxiang ticket rank."""

from __future__ import annotations

import re

from backend.gateways.market_sources.base import (
    MarketSourceFailure,
    OfficialRankAdapter,
    market_entry_from_fields,
    normalized_public_text,
    require_exact_work_path,
)


_WORK_PATH = re.compile(r"/book/[1-9][0-9]*")
_CARD_CLASSES = frozenset({"flex", "mt-24px", "mr-16px", "w-50", "page-one"})
_CONTAINER_CLASSES = frozenset(
    {"flex", "flex-1", "flex-wrap", "relative", "min-h-328px", "ml-30px"}
)
_HEADING_CLASSES = frozenset({"font-source", "text-t1"})
_GRID_CLASSES = frozenset({"flex", "flex-wrap", "relative"})


class XXSYPublicRankAdapter(OfficialRankAdapter):
    source_url = "https://www.xxsy.net/rank/xxyuepiao"
    platform = "xxsy"
    ranking_name = "xiaoxiang_ticket"
    category = "female"
    adapter_version = "xxsy-public-rank-v1"
    work_origins = ("https://www.xxsy.net",)

    async def fetch(self, *, policy, policy_hash, captured_at):
        document = await self.document(
            self.source_url,
            policy=policy,
            policy_hash=policy_hash,
            captured_at=captured_at,
        )
        containers = document.soup.select(
            "div.flex.flex-1.flex-wrap.relative.min-h-328px.ml-30px"
        )
        if (
            len(containers) != 1
            or not _exact_classes(containers[0], _CONTAINER_CLASSES)
            or not _visible(containers[0])
        ):
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        container = containers[0]
        sections = container.find_all(recursive=False)
        if len(sections) != 3:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        heading_wrapper, separator, grid = sections
        heading_children = heading_wrapper.find_all(recursive=False)
        heading_text = (
            heading_children[0].get_text(" ", strip=True)
            if len(heading_children) == 1
            else ""
        )
        if (
            heading_wrapper.name != "div"
            or not _exact_classes(heading_wrapper, frozenset({"flex"}))
            or len(heading_children) != 1
            or heading_children[0].name != "h3"
            or not _exact_classes(heading_children[0], _HEADING_CLASSES)
            or not _visible(heading_children[0])
            or not heading_text
            or _safe_attribute(heading_text) != "潇湘票榜"
        ):
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        if (
            separator.name != "i"
            or not {"block", "line"}.issubset(separator.get("class", ()))
            or set(separator.attrs) != {"class"}
            or separator.find(recursive=False) is not None
            or separator.get_text(strip=True)
        ):
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        if grid.name != "div" or not _exact_classes(grid, _GRID_CLASSES):
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        children = grid.find_all(recursive=False)
        if len(children) != 20 or any(not _card(child) for child in children):
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")

        entries = []
        for rank, card in enumerate(children, start=1):
            try:
                title_node = _unique(card, ".info .text-t34")
                if not _visible(title_node):
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
                title = _safe_text(title_node)
                if _safe_attribute(card.get("title")) != title:
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
                images = card.select("img[alt]")
                if len(images) > 1 or (
                    images
                    and _safe_attribute(images[0].get("alt")) != title
                ):
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
                row = _unique(card, ".info .row1")
                if not _visible(row) or row.find(recursive=False) is not None:
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
                row_text = _safe_text(row)
                if row_text.count(" · ") != 2:
                    raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
                author, word_count, category = row_text.split(" · ")
                entry = market_entry_from_fields(
                    rank=rank,
                    title=title,
                    author=author,
                    category=category,
                    work_url=card.get("href"),
                    base_url=self.source_url,
                    work_origins=self.work_origins,
                    metrics={"wordCount": word_count},
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


def _visible(node) -> bool:
    return not any(
        ancestor.has_attr("hidden")
        or str(ancestor.get("aria-hidden", "")).casefold() == "true"
        for ancestor in (node, *node.parents)
    )


def _safe_text(node) -> str:
    return _safe_attribute(node.get_text(" ", strip=True))


def _safe_attribute(value: object) -> str:
    if not isinstance(value, str):
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    if any(
        ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise MarketSourceFailure("MARKET_HTML_UNKNOWN")
    return normalized_public_text(value, limit=200)


def _unique(container, selector: str):
    nodes = container.select(selector)
    if len(nodes) != 1:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    return nodes[0]


def _card(node) -> bool:
    return (
        node.name == "a"
        and _CARD_CLASSES.issubset(node.get("class", ()))
        and node.has_attr("href")
    )


def _exact_classes(node, expected: frozenset[str]) -> bool:
    values = node.get("class", ())
    return isinstance(values, list) and frozenset(values) == expected
