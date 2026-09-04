from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.market import MarketEntry, MarketSnapshot
from backend.domain.market_sources import MarketSourceFailure, load_market_source_package


MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "market-sources-v1.1.0"
    / "manifest.json"
)


def _verified_sources():
    package = load_market_source_package(MANIFEST)
    return tuple(
        source for source in package.sources
        if source.policy.status == "verified_public"
    )


def _snapshot(source, *, count: int = 10, work_origin: str | None = None):
    origin = work_origin or source.policy.allowed_origins[0]
    prefix = next(
        prefix for prefix in source.policy.path_prefixes
        if prefix not in {"/rank", "/rank/", "/top", "/top/", "/book-rank"}
    )
    separator = "" if prefix.endswith(("/", "=")) else "/"
    return MarketSnapshot(
        platform=source.public_config["platform"],
        rankingName=source.public_config["rankingName"],
        category=source.public_config["category"],
        capturedAt=1_800_000_000_000,
        sourceURL=source.policy.evidence_url,
        entries=tuple(
            MarketEntry(
                rank=rank,
                title=f"作品 {rank}",
                author=f"作者 {rank}",
                category="玄幻",
                workURL=f"{origin}{prefix}{separator}{rank}",
                publicMetrics={"score": rank},
            )
            for rank in range(1, count + 1)
        ),
    )


@pytest.mark.asyncio
async def test_live_verifier_fails_when_fewer_than_five_sources_succeed():
    from backend.scripts.verify_live_market_sources import verify_sources

    sources = _verified_sources()
    calls = []

    async def fetch(source):
        calls.append(source.stable_key)
        if source is sources[-1]:
            raise MarketSourceFailure("MARKET_HTTP_FAILED")
        return _snapshot(source)

    result = await verify_sources(sources, fetch=fetch)

    assert result.exit_code == 1
    assert result.succeeded == 4
    assert result.failed == 1
    assert result.public_errors == frozenset({"MARKET_HTTP_FAILED"})
    assert calls == [source.stable_key for source in sources]


@pytest.mark.asyncio
async def test_live_verifier_requires_ten_complete_entries_per_success():
    from backend.scripts.verify_live_market_sources import verify_sources

    sources = _verified_sources()

    async def fetch(source):
        return _snapshot(source, count=9)

    result = await verify_sources(sources, fetch=fetch)

    assert result.exit_code == 1
    assert result.succeeded == 0
    assert result.failed == 5
    assert result.public_errors == frozenset({"MARKET_PAGE_INCOMPLETE"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    (
        (lambda source, value: value.model_copy(update={"platform": "other"}), "MARKET_SNAPSHOT_INVALID"),
        (
            lambda source, value: value.model_copy(
                update={"source_url": "https://example.com/rank"}
            ),
            "MARKET_SNAPSHOT_INVALID",
        ),
        (
            lambda source, value: value.model_copy(
                update={
                    "entries": (
                        value.entries[0].model_copy(
                            update={"work_url": "http://example.com/book/1"}
                        ),
                        *value.entries[1:],
                    )
                }
            ),
            "MARKET_URL_NOT_ALLOWED",
        ),
        (
            lambda source, value: value.model_copy(
                update={
                    "entries": (
                        value.entries[0].model_copy(
                            update={"work_url": f"{value.entries[0].work_url}#fragment"}
                        ),
                        *value.entries[1:],
                    )
                }
            ),
            "MARKET_URL_NOT_ALLOWED",
        ),
    ),
)
async def test_live_verifier_rejects_wrong_identity_and_unapproved_work_urls(
    mutate,
    expected_code,
):
    from backend.scripts.verify_live_market_sources import verify_sources

    source = _verified_sources()[0]
    result = await verify_sources(
        (source,),
        fetch=lambda current: mutate(current, _snapshot(current)),
        required=1,
    )

    assert result.exit_code == 1
    assert result.lines[0] == (
        f"source={source.stable_key} status=failed code={expected_code}"
    )


@pytest.mark.asyncio
async def test_live_verifier_output_uses_only_fixed_public_codes():
    from backend.scripts.verify_live_market_sources import verify_sources

    source = _verified_sources()[0]
    secret = "private transport exception detail"

    async def fetch(_source):
        raise RuntimeError(secret)

    result = await verify_sources((source,), fetch=fetch, required=1)
    rendered = "\n".join(result.lines)

    assert rendered == "\n".join(
        (
            f"source={source.stable_key} status=failed code=MARKET_REFRESH_FAILED",
            "summary succeeded=0 failed=1 required=1",
        )
    )
    assert secret not in rendered


@pytest.mark.asyncio
async def test_live_verifier_rejects_unsafe_stable_key_before_fetch_or_output():
    from backend.scripts.verify_live_market_sources import verify_sources

    source = _verified_sources()[0].model_copy(
        update={"stable_key": "qq-reading.good\nsource=forged status=succeeded"}
    )
    called = False

    async def fetch(_source):
        nonlocal called
        called = True
        return _snapshot(_source)

    result = await verify_sources((source,), fetch=fetch, required=1)
    rendered = "\n".join(result.lines)

    assert result.exit_code == 1
    assert called is False
    assert rendered == "\n".join(
        (
            "source=invalid status=failed code=MARKET_SOURCE_ADAPTER_UNAVAILABLE",
            "summary succeeded=0 failed=1 required=1",
        )
    )
    assert "forged" not in rendered


@pytest.mark.asyncio
async def test_cli_loads_only_hash_bound_verified_registered_sources_without_database(
    monkeypatch,
):
    from backend.gateways.market_sources.registry import candidate_adapter_factories
    from backend.scripts import verify_live_market_sources

    sources = _verified_sources()
    constructed = []
    attempts = []

    def adapter_for(source):
        class Adapter:
            source_url = source.policy.evidence_url
            platform = source.public_config["platform"]
            ranking_name = source.public_config["rankingName"]
            category = source.public_config["category"]

            def __init__(self, transport):
                constructed.append(transport)

            async def fetch(self, *, policy, policy_hash, captured_at):
                attempts.append((source.stable_key, policy_hash, captured_at))
                return _snapshot(source)

        return Adapter

    factories = {source.adapter_key: adapter_for(source) for source in sources}
    monkeypatch.setattr(
        verify_live_market_sources,
        "candidate_adapter_factories",
        lambda: factories,
    )
    monkeypatch.setattr(
        "backend.database.connection",
        lambda: pytest.fail("live verifier must not open a database"),
    )
    output = []

    exit_code = await verify_live_market_sources.run_cli(
        output=output.append,
        transport=object(),
        clock=lambda: 1_800_000_000_000,
    )

    assert exit_code == 0
    assert len(constructed) == len(sources)
    assert [item[0] for item in attempts] == [source.stable_key for source in sources]
    assert len({item[0] for item in attempts}) == 5
    assert output[-1] == "summary succeeded=5 failed=0 required=5"
    assert set(candidate_adapter_factories()).issuperset(factories)
