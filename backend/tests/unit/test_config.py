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


def test_corpus_root_has_no_implicit_product_default(workspace_tmp_path):
    assert config.load_corpus_root(
        environment={},
        config_path=missing_config(workspace_tmp_path),
    ) is None


def test_corpus_root_environment_value_is_absolute_existing_and_canonical(
    workspace_tmp_path,
):
    corpus_root = workspace_tmp_path / "explicit-corpus"
    corpus_root.mkdir()

    loaded = config.load_corpus_root(
        environment={"CORPUS_ROOT": str(corpus_root)},
        config_path=missing_config(workspace_tmp_path),
    )

    assert loaded == corpus_root.resolve(strict=True)


def test_corpus_root_file_value_is_independent_from_mysql_connector_config(
    workspace_tmp_path,
):
    corpus_root = workspace_tmp_path / "explicit-corpus"
    corpus_root.mkdir()
    path = missing_config(workspace_tmp_path)
    path.write_text(json.dumps({
        "MYSQL_PASSWORD": "secret-sentinel",
        "CORPUS_ROOT": str(corpus_root),
    }), encoding="utf-8")

    mysql = config.load_mysql_config(environment={}, config_path=path)
    loaded_root = config.load_corpus_root(environment={}, config_path=path)

    assert loaded_root == corpus_root.resolve(strict=True)
    assert "CORPUS_ROOT" not in mysql
    assert "corpus_root" not in mysql
    assert set(mysql) == {
        "host",
        "port",
        "user",
        "password",
        "db",
        "charset",
        "autocommit",
        "minsize",
        "maxsize",
    }


def test_corpus_root_environment_value_overrides_file_value(workspace_tmp_path):
    file_root = workspace_tmp_path / "file-corpus"
    environment_root = workspace_tmp_path / "environment-corpus"
    file_root.mkdir()
    environment_root.mkdir()
    path = missing_config(workspace_tmp_path)
    path.write_text(
        json.dumps({"CORPUS_ROOT": str(file_root)}),
        encoding="utf-8",
    )

    loaded = config.load_corpus_root(
        environment={"CORPUS_ROOT": str(environment_root)},
        config_path=path,
    )

    assert loaded == environment_root.resolve(strict=True)


def test_corpus_loader_uses_its_own_error_boundary_for_invalid_documents(
    workspace_tmp_path,
):
    path = missing_config(workspace_tmp_path)
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(config.LocalCorpusConfigError):
        config.load_corpus_root(environment={}, config_path=path)


@pytest.mark.parametrize("value", ("", "relative/corpus", 7, True))
def test_corpus_root_rejects_empty_relative_and_non_text_values(
    workspace_tmp_path, value
):
    path = missing_config(workspace_tmp_path)
    path.write_text(json.dumps({"CORPUS_ROOT": value}), encoding="utf-8")

    with pytest.raises(config.LocalCorpusConfigError):
        config.load_corpus_root(environment={}, config_path=path)


def test_corpus_root_rejects_missing_paths_and_regular_files_without_leaking_value(
    workspace_tmp_path,
):
    missing = workspace_tmp_path / "sensitive-missing-corpus"
    regular_file = workspace_tmp_path / "sensitive-file-corpus"
    regular_file.write_text("synthetic", encoding="utf-8")

    for invalid in (missing, regular_file):
        with pytest.raises(config.LocalCorpusConfigError) as caught:
            config.load_corpus_root(
                environment={"CORPUS_ROOT": str(invalid)},
                config_path=missing_config(workspace_tmp_path),
            )
        assert str(invalid) not in str(caught.value)


def test_require_corpus_root_fails_closed_when_unconfigured():
    with pytest.raises(config.LocalCorpusConfigError, match="CORPUS_ROOT"):
        config.require_corpus_root(None)


def test_require_corpus_root_revalidates_an_explicit_path(workspace_tmp_path):
    with pytest.raises(config.LocalCorpusConfigError):
        config.require_corpus_root(workspace_tmp_path / "missing-corpus")
