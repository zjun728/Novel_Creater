"""Prepare or remove one disposable database for the Phase 2 browser gate."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from functools import partial
from urllib.parse import urlsplit

import aiomysql

from backend.database import DatabaseSession
from backend.scripts import prepare_product_shell_browser_db as schema_database
from backend.scripts import seed_market_sources, seed_writer_assets
from backend.services.provider_profiles import (
    ProviderCreateCommand,
    ProviderProfileService,
    SqlProviderProfileRepository,
)


BrowserDatabaseSafetyError = schema_database.BrowserDatabaseSafetyError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or drop one disposable Phase 2 browser database"
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--drop", action="store_true")
    return parser


def _required_environment(
    environment: Mapping[str, str], name: str
) -> str:
    value = environment.get(name)
    if not isinstance(value, str) or not value.strip():
        raise BrowserDatabaseSafetyError(
            f"Phase 2 browser fixture requires {name}"
        )
    return value


def fake_provider_command(
    environment: Mapping[str, str],
) -> ProviderCreateCommand:
    """Build the one private fake-Provider fixture from runner-owned inputs."""
    base_url = _required_environment(
        environment, "BROWSER_PROVIDER_BASE_URL"
    ).strip()
    try:
        parsed = urlsplit(base_url)
    except ValueError as exc:
        raise BrowserDatabaseSafetyError(
            "Fake Provider must use the runner-owned loopback gateway"
        ) from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.path.rstrip("/") != "/v1"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise BrowserDatabaseSafetyError(
            "Fake Provider must use the runner-owned loopback gateway"
        )
    return ProviderCreateCommand(
        name="Phase 2 Browser Provider",
        provider_type="openai-compatible",
        model=_required_environment(
            environment, "BROWSER_MODEL_SENTINEL"
        ).strip(),
        base_url=base_url,
        api_key=_required_environment(
            environment, "BROWSER_SECRET_SENTINEL"
        ).strip(),
        enabled=True,
        sort_order=0,
        stream=False,
        max_context_tokens=128_000,
        max_output_tokens=8_192,
        temperature=0.7,
        top_p=0.95,
        supports_json=True,
        supports_streaming=False,
        notes="",
        thinking=None,
        idempotency_key="phase2-browser-provider-fixture-v1",
    )


async def seed_fake_provider(
    *,
    environment: Mapping[str, str],
    connection_config: Mapping[str, object],
    output: Callable[[str], None] = print,
) -> None:
    """Persist one callable profile without exposing its private fields."""
    command = fake_provider_command(environment)
    database_name = connection_config.get("db")
    schema_database.assert_browser_database_name(database_name)
    transaction_factory = partial(
        _explicit_mysql_session,
        connection_config,
        transactional=True,
    )
    connection_factory = partial(
        _explicit_mysql_session,
        connection_config,
        transactional=False,
    )
    service = ProviderProfileService(
        SqlProviderProfileRepository(),
        transaction_factory=transaction_factory,
        connection_factory=connection_factory,
        connection_gateway=None,
    )
    await service.create(command)
    output("provider_count=1")


@asynccontextmanager
async def _explicit_mysql_session(
    connection_config: Mapping[str, object],
    *,
    transactional: bool,
):
    """Open one connection against only the caller's disposable database."""
    database_name = connection_config.get("db")
    schema_database.assert_browser_database_name(database_name)
    raw = await aiomysql.connect(
        host=connection_config["host"],
        port=connection_config["port"],
        user=connection_config["user"],
        password=connection_config["password"],
        db=database_name,
        charset="utf8mb4",
        autocommit=not transactional,
    )
    errors: list[BaseException] = []
    try:
        if transactional:
            await raw.begin()
        try:
            yield DatabaseSession(raw)
        except BaseException as body_error:
            if transactional:
                try:
                    await raw.rollback()
                except BaseException as rollback_error:
                    raise BaseExceptionGroup(
                        "Phase 2 Provider fixture and rollback both failed",
                        [body_error, rollback_error],
                    ) from body_error
            raise
        else:
            if transactional:
                await raw.commit()
    except BaseException as error:
        errors.append(error)
    try:
        ensure_closed = getattr(raw, "ensure_closed", None)
        if ensure_closed is not None:
            await ensure_closed()
        else:
            raw.close()
    except BaseException as error:
        errors.append(error)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup(
            "Phase 2 Provider fixture and connection close both failed",
            errors,
        )


def _receipt_value(receipts: Sequence[str], name: str) -> str:
    prefix = name + "="
    values = [
        line[len(prefix) :]
        for receipt in receipts
        for line in receipt.splitlines()
        if line.startswith(prefix)
    ]
    if len(values) != 1 or not values[0]:
        raise BrowserDatabaseSafetyError(
            f"Phase 2 fixture receipt is missing {name}"
        )
    return values[0]


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    schema_runner: Callable[..., Awaitable[int]] | None = None,
    market_runner: Callable[..., Awaitable[int]] | None = None,
    asset_runner: Callable[..., Awaitable[int]] | None = None,
    provider_runner: Callable[..., Awaitable[None]] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    args = _parser().parse_args(argv)
    source = os.environ if environment is None else environment
    schema_database.assert_browser_database_name(args.database)
    mysql = schema_database.browser_mysql_config(source)
    schema_operation = schema_runner or schema_database.run_cli

    if args.drop:
        return await schema_operation(
            ["--database", args.database, "--drop"],
            environment=source,
            output=output,
        )

    # Validate all private fixture inputs before creating any resource.
    fake_provider_command(source)
    database_config = {
        **mysql,
        "db": args.database,
        "minsize": 1,
        "maxsize": 10,
    }
    transaction_factory = partial(
        _explicit_mysql_session,
        database_config,
        transactional=True,
    )
    seed_args = [
        "--execute",
        "--database",
        args.database,
        "--confirm-seed",
        args.database,
    ]
    market_operation = market_runner or seed_market_sources.run_cli
    asset_operation = asset_runner or seed_writer_assets.run_cli
    provider_operation = provider_runner or seed_fake_provider
    receipts: list[str] = []
    prepared = False
    try:
        await schema_operation(
            ["--database", args.database],
            environment=source,
            output=lambda _message: None,
        )
        prepared = True
        await market_operation(
            seed_args,
            connection_config=database_config,
            transaction_factory=transaction_factory,
            output=receipts.append,
        )
        await asset_operation(
            seed_args,
            connection_config=database_config,
            transaction_factory=transaction_factory,
            output=receipts.append,
        )
        await provider_operation(
            environment=source,
            connection_config=database_config,
            output=receipts.append,
        )
        source_count = _receipt_value(receipts, "source_count")
        style_count = _receipt_value(receipts, "style_count")
        card_count = _receipt_value(receipts, "card_count")
        provider_count = _receipt_value(receipts, "provider_count")
        if (source_count, style_count, card_count, provider_count) != (
            "5",
            "10",
            "64",
            "1",
        ):
            raise BrowserDatabaseSafetyError(
                "Phase 2 fixture counts do not match the approved package"
            )
        output("action=prepared")
        output("source_count=5")
        output("style_count=10")
        output("card_count=64")
        output("provider_count=1")
    except BaseException as prepare_error:
        if not prepared:
            raise
        try:
            await schema_operation(
                ["--database", args.database, "--drop"],
                environment=source,
                output=lambda _message: None,
            )
        except BaseException as cleanup_error:
            raise BaseExceptionGroup(
                "Phase 2 fixture preparation and owned cleanup both failed",
                [prepare_error, cleanup_error],
            ) from prepare_error
        raise

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("Phase 2 browser database operation failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
