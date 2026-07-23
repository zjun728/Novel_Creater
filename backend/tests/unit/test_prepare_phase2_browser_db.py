import pytest

import backend.scripts.prepare_phase2_browser_db as browser_db


DATABASE = "novel_creator_test_0123456789abcdef0123456789abcdef"
TEST_ENVIRONMENT = {
    "TEST_MYSQL_HOST": "127.0.0.1",
    "TEST_MYSQL_PORT": "33060",
    "TEST_MYSQL_USER": "root",
    "TEST_MYSQL_PASSWORD": "test-only",
    "MYSQL_DB": "product_database_must_not_be_used",
    "BROWSER_PROVIDER_BASE_URL": "http://127.0.0.1:43127/v1",
    "BROWSER_SECRET_SENTINEL": "phase2-test-secret-never-print",
    "BROWSER_MODEL_SENTINEL": "phase2-test-model-never-print",
}


@pytest.mark.asyncio
async def test_prepare_delegates_schema_and_exact_phase2_packages_in_order():
    calls = []
    output = []

    async def schema_runner(argv, **kwargs):
        calls.append(("schema", argv, kwargs["environment"]))
        return 0

    async def market_runner(argv, **kwargs):
        calls.append(("market", argv, kwargs["connection_config"]))
        kwargs["output"](
            "mode=execute\nsource_count=2\npackage_hash=" + "a" * 64
        )
        return 0

    async def asset_runner(argv, **kwargs):
        calls.append(("assets", argv, kwargs["connection_config"]))
        kwargs["output"](
            "mode=execute\npackage_version=writer-assets-v1\n"
            "package_hash=" + "b" * 64 + "\nstyle_count=10\ncard_count=64"
        )
        return 0

    async def provider_runner(**kwargs):
        calls.append(
            (
                "provider",
                kwargs["environment"],
                kwargs["connection_config"],
            )
        )
        kwargs["output"]("provider_count=1")

    result = await browser_db.run_cli(
        ["--database", DATABASE],
        environment=TEST_ENVIRONMENT,
        schema_runner=schema_runner,
        market_runner=market_runner,
        asset_runner=asset_runner,
        provider_runner=provider_runner,
        output=output.append,
    )

    assert result == 0
    assert [call[0] for call in calls] == [
        "schema",
        "market",
        "assets",
        "provider",
    ]
    assert calls[0][1] == ["--database", DATABASE]
    assert calls[0][2] is TEST_ENVIRONMENT
    expected_config = {
        "host": "127.0.0.1",
        "port": 33060,
        "user": "root",
        "password": "test-only",
        "db": DATABASE,
    }
    assert calls[1][1] == [
        "--execute",
        "--database",
        DATABASE,
        "--confirm-seed",
        DATABASE,
    ]
    assert calls[1][2] == expected_config
    assert calls[2][1] == calls[1][1]
    assert calls[2][2] == expected_config
    assert calls[3][1] is TEST_ENVIRONMENT
    assert calls[3][2] == expected_config
    assert output == [
        "action=prepared",
        "source_count=2",
        "style_count=10",
        "card_count=64",
        "provider_count=1",
    ]
    rendered = "\n".join(output)
    assert TEST_ENVIRONMENT["BROWSER_SECRET_SENTINEL"] not in rendered
    assert TEST_ENVIRONMENT["BROWSER_PROVIDER_BASE_URL"] not in rendered
    assert TEST_ENVIRONMENT["BROWSER_MODEL_SENTINEL"] not in rendered


@pytest.mark.asyncio
async def test_drop_delegates_only_owned_database_cleanup():
    calls = []

    async def schema_runner(argv, **kwargs):
        calls.append((argv, kwargs["environment"]))
        return 0

    async def unexpected_runner(*_args, **_kwargs):
        raise AssertionError("fixture seeders must not run during cleanup")

    result = await browser_db.run_cli(
        ["--database", DATABASE, "--drop"],
        environment=TEST_ENVIRONMENT,
        schema_runner=schema_runner,
        market_runner=unexpected_runner,
        asset_runner=unexpected_runner,
        provider_runner=unexpected_runner,
        output=lambda _message: None,
    )

    assert result == 0
    assert calls == [(["--database", DATABASE, "--drop"], TEST_ENVIRONMENT)]


@pytest.mark.asyncio
async def test_fixture_failure_drops_only_the_owned_database_and_preserves_error():
    calls = []
    failure = RuntimeError("synthetic Phase 2 fixture failure")

    async def schema_runner(argv, **_kwargs):
        calls.append(tuple(argv))
        return 0

    async def market_runner(_argv, **_kwargs):
        raise failure

    async def asset_runner(*_args, **_kwargs):
        raise AssertionError("asset package must not run after market failure")

    with pytest.raises(RuntimeError) as captured:
        await browser_db.run_cli(
            ["--database", DATABASE],
            environment=TEST_ENVIRONMENT,
            schema_runner=schema_runner,
            market_runner=market_runner,
            asset_runner=asset_runner,
            provider_runner=asset_runner,
            output=lambda _message: None,
        )

    assert captured.value is failure
    assert calls == [
        ("--database", DATABASE),
        ("--database", DATABASE, "--drop"),
    ]


@pytest.mark.asyncio
async def test_incomplete_test_authority_fails_before_any_operation():
    calls = []
    environment = dict(TEST_ENVIRONMENT)
    environment.pop("TEST_MYSQL_PASSWORD")

    async def schema_runner(*_args, **_kwargs):
        calls.append("schema")
        return 0

    with pytest.raises(
        browser_db.BrowserDatabaseSafetyError,
        match="TEST_MYSQL_PASSWORD",
    ):
        await browser_db.run_cli(
            ["--database", DATABASE],
            environment=environment,
            schema_runner=schema_runner,
        )

    assert calls == []


def test_fake_provider_fixture_accepts_only_one_runner_owned_loopback_gateway():
    command = browser_db.fake_provider_command(TEST_ENVIRONMENT)

    assert command.name == "Phase 2 Browser Provider"
    assert command.provider_type == "openai-compatible"
    assert command.base_url == TEST_ENVIRONMENT["BROWSER_PROVIDER_BASE_URL"]
    assert command.api_key == TEST_ENVIRONMENT["BROWSER_SECRET_SENTINEL"]
    assert command.model == TEST_ENVIRONMENT["BROWSER_MODEL_SENTINEL"]
    assert command.enabled is True

    for invalid_url in (
        "https://127.0.0.1:43127/v1",
        "http://localhost:43127/v1",
        "http://127.0.0.1/v1",
        "http://127.0.0.1:43127/v1/chat/completions",
        "http://127.0.0.1:43127/v1?secret=1",
        "http://user:secret@127.0.0.1:43127/v1",
    ):
        environment = {
            **TEST_ENVIRONMENT,
            "BROWSER_PROVIDER_BASE_URL": invalid_url,
        }
        with pytest.raises(
            browser_db.BrowserDatabaseSafetyError,
            match="runner-owned",
        ):
            browser_db.fake_provider_command(environment)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_receipt", ("", "provider_count=2"))
async def test_invalid_fixture_receipt_drops_exact_owned_database(provider_receipt):
    calls = []

    async def schema_runner(argv, **_kwargs):
        calls.append(tuple(argv))
        return 0

    async def market_runner(_argv, **kwargs):
        kwargs["output"]("source_count=2")
        return 0

    async def asset_runner(_argv, **kwargs):
        kwargs["output"]("style_count=10\ncard_count=64")
        return 0

    async def provider_runner(**kwargs):
        if provider_receipt:
            kwargs["output"](provider_receipt)

    with pytest.raises(browser_db.BrowserDatabaseSafetyError):
        await browser_db.run_cli(
            ["--database", DATABASE],
            environment=TEST_ENVIRONMENT,
            schema_runner=schema_runner,
            market_runner=market_runner,
            asset_runner=asset_runner,
            provider_runner=provider_runner,
            output=lambda _message: None,
        )

    assert calls == [
        ("--database", DATABASE),
        ("--database", DATABASE, "--drop"),
    ]
