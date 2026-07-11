"""Explicitly gated disposable MySQL integration fixtures."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from backend.tests.support.disposable_mysql import (
    disposable_mysql_database,
    empty_disposable_mysql_database,
)


_REQUIRED = (
    "TEST_MYSQL_HOST",
    "TEST_MYSQL_PORT",
    "TEST_MYSQL_USER",
    "TEST_MYSQL_PASSWORD",
)
_CREATED: list[str] = []
_CLEANED: list[str] = []


@pytest_asyncio.fixture
async def disposable_mysql(request):
    if request.node.get_closest_marker("mysql") is None:
        raise RuntimeError("disposable_mysql fixture requires @pytest.mark.mysql")
    missing = [name for name in _REQUIRED if name not in os.environ]
    if missing:
        pytest.skip(
            "Disposable MySQL integration tests require explicit variables: "
            + ", ".join(missing)
        )
    async with disposable_mysql_database(
        on_created=_CREATED.append,
        on_cleaned=_CLEANED.append,
    ) as database:
        yield database


@pytest_asyncio.fixture
async def empty_disposable_mysql(request):
    if request.node.get_closest_marker("mysql") is None:
        raise RuntimeError("empty_disposable_mysql fixture requires @pytest.mark.mysql")
    missing = [name for name in _REQUIRED if name not in os.environ]
    if missing:
        pytest.skip(
            "Disposable MySQL integration tests require explicit variables: "
            + ", ".join(missing)
        )
    async with empty_disposable_mysql_database(
        on_created=_CREATED.append,
        on_cleaned=_CLEANED.append,
    ) as database:
        yield database


def pytest_terminal_summary(terminalreporter):
    if _CREATED or _CLEANED:
        remaining = sorted(set(_CREATED) - set(_CLEANED))
        terminalreporter.write_line(
            "disposable_mysql: "
            f"created={len(_CREATED)} cleaned={len(_CLEANED)} "
            f"remaining={len(remaining)}"
        )
