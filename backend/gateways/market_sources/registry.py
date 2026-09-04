"""Candidate public-rank adapters, intentionally separate from enabled sources."""

from types import MappingProxyType

from backend.gateways.market_sources.fanqie_public_rank import (
    FanqiePublicRankAdapter,
)
from backend.gateways.market_sources.heiyan_public_rank import HeiyanPublicRankAdapter
from backend.gateways.market_sources.hongxiu_public_rank import HongxiuPublicRankAdapter
from backend.gateways.market_sources.jjwxc_public_rank import JJWXCPublicRankAdapter
from backend.gateways.market_sources.qimao_public_rank import QimaoPublicRankAdapter
from backend.gateways.market_sources.qq_reading_public_rank import (
    QQReadingPublicRankAdapter,
)
from backend.gateways.market_sources.seventeen_k_public_rank import (
    SeventeenKPublicRankAdapter,
)
from backend.gateways.market_sources.zongheng_public_rank import (
    ZonghengPublicRankAdapter,
)


def candidate_adapter_factories():
    return MappingProxyType(
        {
            "fanqie_public_rank": FanqiePublicRankAdapter,
            "qimao_public_rank": QimaoPublicRankAdapter,
            "qq_reading_public_rank": QQReadingPublicRankAdapter,
            "17k_public_rank": SeventeenKPublicRankAdapter,
            "zongheng_public_rank": ZonghengPublicRankAdapter,
            "hongxiu_public_rank": HongxiuPublicRankAdapter,
            "jjwxc_public_rank": JJWXCPublicRankAdapter,
            "heiyan_public_rank": HeiyanPublicRankAdapter,
        }
    )


def official_adapter_versions():
    versions = frozenset(
        adapter_type.adapter_version
        for adapter_type in candidate_adapter_factories().values()
    )
    if len(versions) != len(candidate_adapter_factories()) or any(
        not isinstance(version, str) or not version for version in versions
    ):
        raise RuntimeError("market adapter versions must be unique and non-empty")
    return versions


def build_market_adapters(transport):
    return {
        key: adapter_type(transport)
        for key, adapter_type in candidate_adapter_factories().items()
    }
