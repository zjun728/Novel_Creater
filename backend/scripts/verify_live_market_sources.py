"""Read-only qualification for hash-bound official public market sources."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from pathlib import Path
import re
import sys
import time
from typing import Awaitable, Callable, Sequence
from urllib.parse import urlsplit

from backend.domain.market import MAX_MARKET_ENTRIES, MarketEntry, MarketSnapshot
from backend.domain.market_sources import (
    MarketSourceDefinition,
    MarketSourceFailure,
    PACKAGE_VERSION,
    load_market_source_package,
)
from backend.gateways.market_sources.base import (
    HttpxMarketTransport,
    canonical_work_url,
    verify_transport_policy,
)
from backend.gateways.market_sources.registry import candidate_adapter_factories


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / PACKAGE_VERSION
    / "manifest.json"
)
REQUIRED_SOURCE_COUNT = 5
_STABLE_KEY = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")


@dataclass(frozen=True)
class LiveSourceVerification:
    lines: tuple[str, ...]
    succeeded: int
    failed: int
    required: int
    public_errors: frozenset[str]
    exit_code: int


def _fixed_failure_code(failure: BaseException) -> str:
    if isinstance(failure, MarketSourceFailure):
        return failure.code
    return "MARKET_REFRESH_FAILED"


def _validated_snapshot(
    source: MarketSourceDefinition,
    value: object,
    *,
    used_platforms: set[str],
) -> MarketSnapshot:
    if not isinstance(value, MarketSnapshot):
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    try:
        snapshot = MarketSnapshot.model_validate(
            value.model_dump(mode="python", by_alias=True),
            strict=True,
        )
    except Exception:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID") from None

    expected = source.public_config
    if (
        snapshot.platform != expected["platform"]
        or snapshot.ranking_name != expected["rankingName"]
        or snapshot.category != expected["category"]
        or snapshot.source_url != source.policy.evidence_url
        or snapshot.platform in used_platforms
    ):
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    if not 10 <= len(snapshot.entries) <= MAX_MARKET_ENTRIES:
        raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
    if urlsplit(snapshot.source_url).scheme != "https":
        raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")

    verify_transport_policy(
        source.policy,
        source.policy_hash,
        source_url=snapshot.source_url,
        captured_at=snapshot.captured_at,
    )
    work_urls: set[str] = set()
    for expected_rank, entry in enumerate(snapshot.entries, start=1):
        if (
            not isinstance(entry, MarketEntry)
            or entry.rank != expected_rank
            or not entry.title.strip()
            or not entry.author.strip()
            or not entry.category.strip()
        ):
            raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
        if urlsplit(entry.work_url).scheme != "https":
            raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")
        if canonical_work_url(
            entry.work_url,
            base_url=snapshot.source_url,
            work_origins=source.policy.allowed_origins,
        ) != entry.work_url:
            raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")
        verify_transport_policy(
            source.policy,
            source.policy_hash,
            source_url=entry.work_url,
            captured_at=snapshot.captured_at,
        )
        if entry.work_url in work_urls:
            raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
        work_urls.add(entry.work_url)
    return snapshot


async def verify_sources(
    sources: Sequence[MarketSourceDefinition],
    *,
    fetch: Callable[[MarketSourceDefinition], object | Awaitable[object]],
    required: int = REQUIRED_SOURCE_COUNT,
) -> LiveSourceVerification:
    """Attempt every supplied source once and retain only fixed public evidence."""

    lines: list[str] = []
    public_errors: set[str] = set()
    used_platforms: set[str] = set()
    succeeded = 0
    failed = 0
    for source in sources:
        stable_key = getattr(source, "stable_key", None)
        if (
            not isinstance(stable_key, str)
            or len(stable_key) > 160
            or _STABLE_KEY.fullmatch(stable_key) is None
        ):
            code = "MARKET_SOURCE_ADAPTER_UNAVAILABLE"
            public_errors.add(code)
            failed += 1
            lines.append(f"source=invalid status=failed code={code}")
            continue
        try:
            pending = fetch(source)
            value = await pending if inspect.isawaitable(pending) else pending
            snapshot = _validated_snapshot(
                source,
                value,
                used_platforms=used_platforms,
            )
            used_platforms.add(snapshot.platform)
            succeeded += 1
            lines.append(
                f"source={stable_key} status=succeeded "
                f"entries={len(snapshot.entries)} captured_at={snapshot.captured_at}"
            )
        except Exception as failure:
            code = _fixed_failure_code(failure)
            public_errors.add(code)
            failed += 1
            lines.append(
                f"source={stable_key} status=failed code={code}"
            )

    lines.append(
        f"summary succeeded={succeeded} failed={failed} required={required}"
    )
    exit_code = 0 if succeeded >= required and len(used_platforms) >= required else 1
    return LiveSourceVerification(
        lines=tuple(lines),
        succeeded=succeeded,
        failed=failed,
        required=required,
        public_errors=frozenset(public_errors),
        exit_code=exit_code,
    )


async def run_cli(
    *,
    output: Callable[[str], None] = print,
    transport=None,
    clock: Callable[[], int] | None = None,
) -> int:
    package = load_market_source_package(MANIFEST_PATH)
    sources = tuple(
        source
        for source in package.sources
        if source.policy.status == "verified_public"
    )
    factories = candidate_adapter_factories()
    shared_transport = transport or HttpxMarketTransport()
    captured_at = (clock or (lambda: int(time.time() * 1000)))()

    async def fetch(source: MarketSourceDefinition):
        factory = factories.get(source.adapter_key)
        if factory is None:
            raise MarketSourceFailure("MARKET_SOURCE_ADAPTER_UNAVAILABLE")
        adapter = factory(shared_transport)
        if (
            getattr(adapter, "source_url", None) != source.policy.evidence_url
            or getattr(adapter, "platform", None) != source.public_config["platform"]
            or getattr(adapter, "ranking_name", None)
            != source.public_config["rankingName"]
            or getattr(adapter, "category", None) != source.public_config["category"]
        ):
            raise MarketSourceFailure("MARKET_SOURCE_ADAPTER_UNAVAILABLE")
        return await adapter.fetch(
            policy=source.policy,
            policy_hash=source.policy_hash,
            captured_at=captured_at,
        )

    result = await verify_sources(sources, fetch=fetch)
    for line in result.lines:
        output(line)
    return result.exit_code


def main() -> int:
    try:
        return asyncio.run(run_cli())
    except Exception:
        print(
            "source=package status=failed code=MARKET_SOURCE_PACKAGE_INVALID",
            file=sys.stderr,
        )
        print(
            f"summary succeeded=0 failed=1 required={REQUIRED_SOURCE_COUNT}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
