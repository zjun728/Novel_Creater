import json

import pytest


class RecordingSession:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def fetchone(self, sql, args=None):
        self.calls.append((sql, args))
        return {"version": "8.4.3"}

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_runtime_receipt_uses_only_select_version_and_allowlisted_packages():
    from backend.scripts.verify_runtime_versions import collect_runtime_versions

    session = RecordingSession()
    receipt = await collect_runtime_versions(
        session,
        package_versions={
            "python": "3.13.5",
            "pydantic": "2.11.7",
            "httpx": "0.28.1",
            "fastapi": "0.116.1",
            "starlette": "0.47.2",
            "uvicorn": "0.35.0",
            "pytest": "8.4.1",
            "credential": "must-not-appear",
        },
    )

    assert session.calls == [("SELECT VERSION() AS version", None)]
    assert receipt == {
        "python": "3.13.5",
        "pydantic": "2.11.7",
        "httpx": "0.28.1",
        "fastapi": "0.116.1",
        "starlette": "0.47.2",
        "uvicorn": "0.35.0",
        "pytest": "8.4.1",
        "mysql": "8.4.3",
    }


@pytest.mark.asyncio
async def test_test_mysql_cli_requires_explicit_test_authority_and_closes_session():
    from backend.scripts.verify_runtime_versions import run_cli

    session = RecordingSession()
    configs = []

    async def factory(config):
        configs.append(config)
        return session

    output = []
    environment = {
        "TEST_MYSQL_HOST": "127.0.0.1",
        "TEST_MYSQL_PORT": "3308",
        "TEST_MYSQL_USER": "tester",
        "TEST_MYSQL_PASSWORD": "private-password",
        "MYSQL_HOST": "product-host-must-not-be-used",
        "MYSQL_PASSWORD": "product-password-must-not-be-used",
    }
    await run_cli(
        ["--test-mysql"],
        environment=environment,
        connection_factory=factory,
        package_versions={
            "python": "3.13.5",
            "pydantic": "2.11.7",
            "httpx": "0.28.1",
            "fastapi": "0.116.1",
            "starlette": "0.47.2",
            "uvicorn": "0.35.0",
            "pytest": "8.4.1",
        },
        output=output.append,
    )

    assert configs == [{
        "host": "127.0.0.1",
        "port": 3308,
        "user": "tester",
        "password": "private-password",
        "charset": "utf8mb4",
        "autocommit": True,
    }]
    assert session.closed
    rendered = output[0]
    assert json.loads(rendered)["mysql"] == "8.4.3"
    assert "private-password" not in rendered
    assert "product-host" not in rendered


@pytest.mark.asyncio
async def test_test_mysql_cli_rejects_missing_test_variables_before_connecting():
    from backend.scripts.verify_runtime_versions import RuntimeVersionSafetyError, run_cli

    called = False

    async def factory(_config):
        nonlocal called
        called = True

    with pytest.raises(RuntimeVersionSafetyError, match="TEST_MYSQL_PASSWORD"):
        await run_cli(
            ["--test-mysql"],
            environment={
                "TEST_MYSQL_HOST": "127.0.0.1",
                "TEST_MYSQL_PORT": "3308",
                "TEST_MYSQL_USER": "tester",
            },
            connection_factory=factory,
        )
    assert not called
