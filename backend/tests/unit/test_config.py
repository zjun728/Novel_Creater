import json
from pathlib import Path

import pytest

from backend import config


def missing_config(workspace_tmp_path):
    return workspace_tmp_path / ".env.local.json"


def test_loader_uses_only_non_secret_local_defaults(workspace_tmp_path):
    loaded = config.load_mysql_config(
        environment={},
        config_path=missing_config(workspace_tmp_path),
    )

    assert loaded == {
        "host": "127.0.0.1",
        "port": 3307,
        "user": "root",
        "password": None,
        "db": "novel_creator",
        "charset": "utf8mb4",
        "autocommit": True,
        "minsize": 1,
        "maxsize": 10,
    }
    assert "123456" not in Path(config.__file__).read_text(encoding="utf-8")


def test_environment_overrides_file_one_key_at_a_time(workspace_tmp_path):
    path = missing_config(workspace_tmp_path)
    path.write_text(json.dumps({
        "MYSQL_HOST": "file-host",
        "MYSQL_PORT": 3308,
        "MYSQL_USER": "file-user",
        "MYSQL_PASSWORD": "file-password",
        "MYSQL_DB": "file-db",
    }), encoding="utf-8")

    loaded = config.load_mysql_config(
        environment={
            "MYSQL_HOST": "env-host",
            "MYSQL_PASSWORD": "env-password",
        },
        config_path=path,
    )

    assert loaded["host"] == "env-host"
    assert loaded["port"] == 3308
    assert loaded["user"] == "file-user"
    assert loaded["password"] == "env-password"
    assert loaded["db"] == "file-db"


@pytest.mark.parametrize(
    "document",
    (
        "not json",
        "[]",
        '{"MYSQL_PASSWORD":"secret","UNKNOWN":"value"}',
        '{"MYSQL_HOST":7}',
        '{"MYSQL_PORT":"3307"}',
        '{"MYSQL_PORT":true}',
        '{"MYSQL_PORT":0}',
        '{"MYSQL_PORT":65536}',
        '{"MYSQL_PASSWORD":""}',
    ),
)
def test_loader_rejects_invalid_local_documents(workspace_tmp_path, document):
    path = missing_config(workspace_tmp_path)
    path.write_text(document, encoding="utf-8")

    with pytest.raises(config.LocalMySQLConfigError):
        config.load_mysql_config(environment={}, config_path=path)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("MYSQL_PORT", "not-a-port"),
        ("MYSQL_PORT", "0"),
        ("MYSQL_PORT", "65536"),
        ("MYSQL_HOST", ""),
        ("MYSQL_PASSWORD", ""),
    ),
)
def test_loader_rejects_invalid_environment_values(workspace_tmp_path, name, value):
    with pytest.raises(config.LocalMySQLConfigError):
        config.load_mysql_config(
            environment={name: value},
            config_path=missing_config(workspace_tmp_path),
        )


def test_loader_fails_closed_when_local_file_cannot_be_read(workspace_tmp_path):
    with pytest.raises(config.LocalMySQLConfigError):
        config.load_mysql_config(environment={}, config_path=workspace_tmp_path)


def test_loader_wraps_invalid_utf8_as_a_configuration_error(workspace_tmp_path):
    path = missing_config(workspace_tmp_path)
    path.write_bytes(b"\xff")

    with pytest.raises(config.LocalMySQLConfigError, match="read"):
        config.load_mysql_config(environment={}, config_path=path)


def test_missing_password_preflight_is_clear_and_secret_free(workspace_tmp_path):
    loaded = config.load_mysql_config(
        environment={},
        config_path=missing_config(workspace_tmp_path),
    )

    with pytest.raises(config.LocalMySQLConfigError, match="MYSQL_PASSWORD") as caught:
        config.require_mysql_config(loaded)

    assert "123456" not in str(caught.value)


def test_preflight_returns_a_copy_of_complete_config(workspace_tmp_path):
    loaded = config.load_mysql_config(
        environment={"MYSQL_PASSWORD": "secret-sentinel"},
        config_path=missing_config(workspace_tmp_path),
    )

    required = config.require_mysql_config(loaded)

    assert required == loaded
    assert required is not loaded
