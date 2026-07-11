import re
from pathlib import Path

import pytest

from backend.tests.support.disposable_mysql import (
    TEST_PREFIX,
    assert_disposable_name,
    new_database_name,
    test_server_config as load_test_server_config,
)
from backend.tests.support import disposable_mysql


def test_server_config_requires_all_explicit_test_variables(monkeypatch):
    for name in (
        "TEST_MYSQL_HOST",
        "TEST_MYSQL_PORT",
        "TEST_MYSQL_USER",
        "TEST_MYSQL_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MYSQL_HOST", "must-not-be-used")
    monkeypatch.setenv("MYSQL_PASSWORD", "must-not-be-used")

    with pytest.raises(RuntimeError, match="TEST_MYSQL_HOST") as error:
        load_test_server_config()

    assert "MYSQL_HOST" not in str(error.value).replace("TEST_MYSQL_HOST", "")


def test_disposable_database_names_are_exact_uuid_hex_names():
    name = new_database_name()

    assert name.startswith(TEST_PREFIX)
    assert re.fullmatch(r"novel_creator_test_[a-f0-9]{32}", name)
    assert_disposable_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "novel_creator",
        "novel_creator_test_",
        "novel_creator_test_ABCDEF0123456789abcdef0123456789",
        "novel_creator_test_abcdef0123456789abcdef0123456789_suffix",
        "other_test_abcdef0123456789abcdef0123456789",
    ],
)
def test_disposable_database_guard_refuses_every_other_name(name):
    with pytest.raises(RuntimeError, match="Refusing non-disposable database"):
        assert_disposable_name(name)


def test_disposable_support_does_not_import_product_database_configuration():
    source = Path(disposable_mysql.__file__).read_text(encoding="utf-8")
    assert "backend.database" not in source
    assert "backend.config" not in source
    assert "MYSQL_HOST" not in source.replace("TEST_MYSQL_HOST", "")
    assert "MYSQL_PASSWORD" not in source.replace("TEST_MYSQL_PASSWORD", "")


def _explicit_test_environment(monkeypatch):
    monkeypatch.setenv("TEST_MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("TEST_MYSQL_PORT", "33060")
    monkeypatch.setenv("TEST_MYSQL_USER", "root")
    monkeypatch.setenv("TEST_MYSQL_PASSWORD", "test-only")


@pytest.mark.asyncio
async def test_create_ack_loss_still_checks_and_drops_guarded_database(monkeypatch):
    _explicit_test_environment(monkeypatch)
    name = "novel_creator_test_0123456789abcdef0123456789abcdef"

    class AckLostAdmin:
        def __init__(self):
            self.exists = False
            self.calls = []

        async def execute(self, sql, args=None):
            self.calls.append(sql)
            if sql.startswith("CREATE DATABASE"):
                self.exists = True
                raise RuntimeError("CREATE acknowledgement lost")
            if sql.startswith("DROP DATABASE"):
                self.exists = False

        async def fetchone(self, sql, args=None):
            return {"SCHEMA_NAME": name} if self.exists else None

        async def close(self):
            pass

    admin = AckLostAdmin()

    async def open_admin(config):
        return admin

    monkeypatch.setattr(disposable_mysql, "new_database_name", lambda: name)
    monkeypatch.setattr(disposable_mysql, "_open_admin_session", open_admin)

    with pytest.raises(RuntimeError, match="acknowledgement lost"):
        async with disposable_mysql.disposable_mysql_database(initialize_schema=False):
            raise AssertionError("must not yield")

    assert admin.exists is False
    assert admin.calls == [
        f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci",
        f"DROP DATABASE `{name}`",
    ]


@pytest.mark.asyncio
async def test_body_and_cleanup_failures_are_preserved_together(monkeypatch):
    _explicit_test_environment(monkeypatch)
    name = "novel_creator_test_0123456789abcdef0123456789abcdef"

    class CleanupFailingAdmin:
        async def execute(self, sql, args=None):
            if sql.startswith("DROP DATABASE"):
                raise RuntimeError("injected DROP failure")

        async def fetchone(self, sql, args=None):
            return {"SCHEMA_NAME": name}

        async def close(self):
            pass

    class FakeRaw:
        def close(self):
            pass

    async def open_admin(config):
        return CleanupFailingAdmin()

    async def connect(**config):
        return FakeRaw()

    monkeypatch.setattr(disposable_mysql, "new_database_name", lambda: name)
    monkeypatch.setattr(disposable_mysql, "_open_admin_session", open_admin)
    monkeypatch.setattr(disposable_mysql.aiomysql, "connect", connect)

    with pytest.raises(BaseExceptionGroup) as raised:
        async with disposable_mysql.disposable_mysql_database(initialize_schema=False):
            raise ValueError("injected body failure")

    assert [type(error) for error in raised.value.exceptions] == [ValueError, RuntimeError]
    assert str(raised.value.exceptions[0]) == "injected body failure"
    assert "partial state may remain" in str(raised.value.exceptions[1])
    assert "injected DROP failure" in str(raised.value.exceptions[1].__cause__)
