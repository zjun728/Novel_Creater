"""Strict adapter for the fixed QQ Reading public ranking URL."""

from backend.gateways.market_sources.base import PublicRankAdapter


class QQReadingPublicRankAdapter(PublicRankAdapter):
    source_url = "https://book.qq.com/book-rank"
    platform = "qq_reading"
    ranking_name = "male_popular"
    category = "male"
    marker = "qq-male-popular"
    adapter_version = "qq-reading-public-rank-v1"
    work_origins = ("https://book.qq.com",)
