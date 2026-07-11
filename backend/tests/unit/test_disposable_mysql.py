import re

import pytest

from backend.tests.support.disposable_mysql import (
    TEST_PREFIX,
    assert_disposable_name,
    new_database_name,
    test_server_config as load_test_server_config,
)


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
