"""Strict adapter for the fixed Qidian public new-sign ranking URL."""

from backend.gateways.market_sources.base import PublicRankAdapter


class QidianPublicRankAdapter(PublicRankAdapter):
    source_url = "https://www.qidian.com/rank/newsign/"
    platform = "qidian"
    ranking_name = "newsign"
    category = "male"
    marker = "qidian-newsign"
    adapter_version = "qidian-public-rank-v1"
    work_origins = ("https://www.qidian.com",)
