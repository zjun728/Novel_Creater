import dataclasses
import json
from pathlib import Path
import subprocess
import sys

import pytest

from backend import config


def runtime_mysql_items(**replacements):
    values = {
        "host": "runtime-host",
        "port": 3307,
        "user": "runtime-user",
        "password": "runtime-password",
        "db": "runtime-db",
        "charset": "utf8mb4",
        "autocommit": True,
        "minsize": 1,
        "maxsize": 10,
    }
    values.update(replacements)
    return tuple(values.items())


def assert_safe_runtime_configuration_error(error, suffix):
    assert type(error) is config.RuntimeConfigurationError
    assert error.args == (f"runtime configuration {suffix}",)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert not hasattr(error, "__notes__")


@pytest.fixture(autouse=True)
def no_active_runtime_configuration(monkeypatch):
    monkeypatch.setattr(config, "_active_runtime_configuration", None, raising=False)


@pytest.fixture
def runtime_configuration(workspace_tmp_path):
    corpus_root = workspace_tmp_path / "runtime-corpus"
    managed_root = workspace_tmp_path / "runtime-managed"
    corpus_root.mkdir()
    managed_root.mkdir()
    return config.RuntimeConfiguration(
        mysql_items=runtime_mysql_items(),
        corpus_root=corpus_root,
        managed_corpus_root=managed_root,
        market_scheduler_enabled=True,
    )


def test_import_performs_no_configuration_document_reads():
    script = """
from pathlib import Path

def forbidden_read(*args, **kwargs):
    raise AssertionError("configuration read during import")

Path.read_text = forbidden_read
import backend.config
print("IMPORTED_WITHOUT_READ")
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(config.__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "IMPORTED_WITHOUT_READ"


def test_runtime_configuration_is_frozen_and_exact(runtime_configuration):
    assert type(runtime_configuration) is config.RuntimeConfiguration
    assert type(runtime_configuration.mysql_items) is tuple
    assert runtime_configuration.mysql_pool_options() == {
        "host": "runtime-host",
        "port": 3307,
        "user": "runtime-user",
        "password": "runtime-password",
        "db": "runtime-db",
        "charset": "utf8mb4",
        "autocommit": True,
        "minsize": 1,
        "maxsize": 10,
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        runtime_configuration.market_scheduler_enabled = False


@pytest.mark.parametrize(
    "mysql_items",
    (
        list(runtime_mysql_items()),
        tuple([key, value] for key, value in runtime_mysql_items()),
        type("TupleSubclass", (tuple,), {})(runtime_mysql_items()),
        (
            type("InnerTupleSubclass", (tuple,), {})(runtime_mysql_items()[0]),
            *runtime_mysql_items()[1:],
        ),
        runtime_mysql_items() + (("host", "duplicate-host"),),
        runtime_mysql_items()[:-1],
        runtime_mysql_items() + (("extra", "value"),),
        tuple(reversed(runtime_mysql_items())),
    ),
)
def test_runtime_configuration_rejects_open_mysql_containers(
    workspace_tmp_path, mysql_items,
):
    with pytest.raises(config.RuntimeConfigurationError) as caught:
        config.RuntimeConfiguration(
            mysql_items=mysql_items,
            corpus_root=workspace_tmp_path,
            managed_corpus_root=None,
            market_scheduler_enabled=False,
        )

    assert_safe_runtime_configuration_error(caught.value, "is invalid")


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("host", type("TextSubclass", (str,), {})("host")),
        ("user", None),
        ("password", None),
        ("db", 7),
        ("charset", type("CharsetSubclass", (str,), {})("utf8mb4")),
        ("port", True),
        ("port", type("IntegerSubclass", (int,), {})(3307)),
        ("minsize", False),
        ("maxsize", 10.0),
        ("autocommit", 1),
    ),
)
def test_runtime_configuration_rejects_non_exact_mysql_values(
    workspace_tmp_path, key, value,
):
    with pytest.raises(config.RuntimeConfigurationError) as caught:
        config.RuntimeConfiguration(
            mysql_items=runtime_mysql_items(**{key: value}),
            corpus_root=workspace_tmp_path,
            managed_corpus_root=None,
            market_scheduler_enabled=False,
        )

    assert_safe_runtime_configuration_error(caught.value, "is invalid")


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("host", ""),
        ("host", "   "),
        ("user", "\t"),
        ("password", "\n"),
        ("db", ""),
        ("port", 0),
        ("port", 65536),
        ("charset", "utf8"),
        ("autocommit", False),
        ("minsize", 0),
        ("minsize", 2),
        ("maxsize", -1),
        ("maxsize", 11),
    ),
)
def test_runtime_configuration_rejects_semantically_invalid_mysql_values(
    workspace_tmp_path, key, value,
):
    with pytest.raises(config.RuntimeConfigurationError) as caught:
        config.RuntimeConfiguration(
            mysql_items=runtime_mysql_items(**{key: value}),
            corpus_root=workspace_tmp_path,
            managed_corpus_root=None,
            market_scheduler_enabled=False,
        )

    assert_safe_runtime_configuration_error(caught.value, "is invalid")


def test_runtime_configuration_rejects_non_exact_roots_and_scheduler(
    workspace_tmp_path,
):
    concrete_path_type = type(Path())

    class PathSubclass(concrete_path_type):
        pass

    invalid_fields = (
        {"corpus_root": str(workspace_tmp_path)},
        {"managed_corpus_root": PathSubclass(workspace_tmp_path)},
        {"market_scheduler_enabled": 1},
    )
    for replacement in invalid_fields:
        fields = {
            "mysql_items": runtime_mysql_items(),
            "corpus_root": workspace_tmp_path,
            "managed_corpus_root": None,
            "market_scheduler_enabled": False,
        }
        fields.update(replacement)
        with pytest.raises(config.RuntimeConfigurationError) as caught:
            config.RuntimeConfiguration(**fields)
        assert_safe_runtime_configuration_error(caught.value, "is invalid")


def test_runtime_configuration_copies_cannot_mutate_installed_authority(
    runtime_configuration,
):
    config.install_runtime_configuration(runtime_configuration)
    mutable_copy = runtime_configuration.mysql_pool_options()

    mutable_copy["host"] = "mutated-host"

    assert config.current_runtime_configuration().mysql_pool_options()["host"] == (
        "runtime-host"
    )
    config.clear_runtime_configuration(runtime_configuration)


def test_install_revalidates_a_forged_exact_snapshot(workspace_tmp_path):
    forged = object.__new__(config.RuntimeConfiguration)
    object.__setattr__(forged, "mysql_items", list(runtime_mysql_items()))
    object.__setattr__(forged, "corpus_root", workspace_tmp_path)
    object.__setattr__(forged, "managed_corpus_root", None)
    object.__setattr__(forged, "market_scheduler_enabled", False)

    with pytest.raises(config.RuntimeConfigurationError) as caught:
        config.install_runtime_configuration(forged)

    assert_safe_runtime_configuration_error(caught.value, "installation failed")


def test_install_and_pool_copy_revalidate_semantically_forged_snapshots(
    runtime_configuration,
):
    object.__setattr__(
        runtime_configuration,
        "mysql_items",
        runtime_mysql_items(port=0),
    )
    with pytest.raises(config.RuntimeConfigurationError) as install_error:
        config.install_runtime_configuration(runtime_configuration)
    assert_safe_runtime_configuration_error(
        install_error.value, "installation failed"
    )

    valid = dataclasses.replace(
        runtime_configuration,
        mysql_items=runtime_mysql_items(),
    )
    config.install_runtime_configuration(valid)
    object.__setattr__(valid, "mysql_items", runtime_mysql_items(charset="utf8"))
    with pytest.raises(config.RuntimeConfigurationError) as copy_error:
        valid.mysql_pool_options()
    assert_safe_runtime_configuration_error(copy_error.value, "is invalid")
    config.clear_runtime_configuration(valid)


@pytest.mark.parametrize(
    "missing_field",
    (
        "mysql_items",
        "corpus_root",
        "managed_corpus_root",
        "market_scheduler_enabled",
    ),
)
def test_registry_rejects_exact_snapshots_with_each_field_missing(
    runtime_configuration, missing_field,
):
    forged = dataclasses.replace(runtime_configuration)
    object.__delattr__(forged, missing_field)

    assert config._runtime_configuration_is_valid(forged) is False
    with pytest.raises(config.RuntimeConfigurationError) as install_error:
        config.install_runtime_configuration(forged)
    assert_safe_runtime_configuration_error(
        install_error.value, "installation failed"
    )

    with pytest.raises(config.RuntimeConfigurationError) as copy_error:
        forged.mysql_pool_options()
    assert_safe_runtime_configuration_error(copy_error.value, "is invalid")


def test_current_and_pool_copy_revalidate_every_post_install_mutation(
    runtime_configuration, workspace_tmp_path,
):
    missing_root = workspace_tmp_path / "missing-runtime-root"
    regular_file = workspace_tmp_path / "runtime-root-file"
    regular_file.write_text("not a directory", encoding="utf-8")
    mutations = (
        ("mysql_items", runtime_mysql_items(port=0)),
        ("corpus_root", missing_root),
        ("managed_corpus_root", regular_file),
        ("market_scheduler_enabled", 1),
    )

    for field, value in mutations:
        snapshot = dataclasses.replace(runtime_configuration)
        config.install_runtime_configuration(snapshot)
        object.__setattr__(snapshot, field, value)

        with pytest.raises(config.RuntimeConfigurationError) as current_error:
            config.current_runtime_configuration()
        assert_safe_runtime_configuration_error(
            current_error.value, "is unavailable"
        )
        with pytest.raises(config.RuntimeConfigurationError) as copy_error:
            snapshot.mysql_pool_options()
        assert_safe_runtime_configuration_error(copy_error.value, "is invalid")
        config.clear_runtime_configuration(snapshot)


@pytest.mark.parametrize("root_field", ("corpus_root", "managed_corpus_root"))
def test_runtime_configuration_rejects_missing_file_and_noncanonical_roots(
    workspace_tmp_path, root_field,
):
    missing = workspace_tmp_path / "missing-root"
    regular_file = workspace_tmp_path / "regular-root-file"
    regular_file.write_text("not a directory", encoding="utf-8")
    canonical = workspace_tmp_path / "canonical-root"
    canonical.mkdir()
    noncanonical = canonical / ".." / canonical.name

    for invalid_root in (missing, regular_file, noncanonical):
        fields = {
            "mysql_items": runtime_mysql_items(),
            "corpus_root": workspace_tmp_path,
            "managed_corpus_root": None,
            "market_scheduler_enabled": False,
        }
        fields[root_field] = invalid_root
        with pytest.raises(config.RuntimeConfigurationError) as caught:
            config.RuntimeConfiguration(**fields)
        assert_safe_runtime_configuration_error(caught.value, "is invalid")


@pytest.mark.parametrize("root_field", ("corpus_root", "managed_corpus_root"))
def test_runtime_configuration_rejects_linked_roots(
    workspace_tmp_path, root_field,
):
    actual = workspace_tmp_path / "actual-runtime-root"
    linked = workspace_tmp_path / "linked-runtime-root"
    actual.mkdir()
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    fields = {
        "mysql_items": runtime_mysql_items(),
        "corpus_root": workspace_tmp_path,
        "managed_corpus_root": None,
        "market_scheduler_enabled": False,
    }
    fields[root_field] = linked
    with pytest.raises(config.RuntimeConfigurationError) as caught:
        config.RuntimeConfiguration(**fields)
    assert_safe_runtime_configuration_error(caught.value, "is invalid")


def test_runtime_configuration_rejects_managed_reparse_metadata(
    workspace_tmp_path, monkeypatch,
):
    managed = workspace_tmp_path / "managed-reparse-root"
    managed.mkdir()
    real_metadata = managed.lstat()

    class ReparseMetadata:
        st_mode = real_metadata.st_mode
        st_file_attributes = 0x400

    concrete_path_type = type(Path())
    original_lstat = concrete_path_type.lstat

    def marked_lstat(selected):
        if selected == managed:
            return ReparseMetadata()
        return original_lstat(selected)

    monkeypatch.setattr(concrete_path_type, "lstat", marked_lstat)

    with pytest.raises(config.RuntimeConfigurationError) as caught:
        config.RuntimeConfiguration(
            mysql_items=runtime_mysql_items(),
            corpus_root=workspace_tmp_path,
            managed_corpus_root=managed,
            market_scheduler_enabled=False,
        )
    assert_safe_runtime_configuration_error(caught.value, "is invalid")


def test_runtime_root_validation_wraps_unexpected_metadata_failure(
    workspace_tmp_path, monkeypatch,
):
    managed = workspace_tmp_path / "managed-metadata-failure"
    managed.mkdir()
    concrete_path_type = type(Path())
    original_lstat = concrete_path_type.lstat

    def failing_lstat(selected):
        if selected == managed:
            raise AttributeError("secret-metadata-sentinel")
        return original_lstat(selected)

    monkeypatch.setattr(concrete_path_type, "lstat", failing_lstat)

    with pytest.raises(config.RuntimeConfigurationError) as caught:
        config.RuntimeConfiguration(
            mysql_items=runtime_mysql_items(),
            corpus_root=workspace_tmp_path,
            managed_corpus_root=managed,
            market_scheduler_enabled=False,
        )
    assert_safe_runtime_configuration_error(caught.value, "is invalid")
    assert "secret-metadata-sentinel" not in str(caught.value)


def test_registry_rejects_hostile_class_spoof_without_reading_metadata():
    class FlowSentinel(KeyboardInterrupt):
        pass

    class Hostile:
        @property
        def __class__(self):
            raise FlowSentinel("class metadata was read")

        @property
        def args(self):
            raise FlowSentinel("args metadata was read")

        def __str__(self):
            raise FlowSentinel("string conversion was attempted")

    hostile = Hostile()
    with pytest.raises(config.RuntimeConfigurationError) as install_error:
        config.install_runtime_configuration(hostile)
    assert_safe_runtime_configuration_error(
        install_error.value, "installation failed"
    )

    with pytest.raises(config.RuntimeConfigurationError) as clear_error:
        config.clear_runtime_configuration(hostile)
    assert_safe_runtime_configuration_error(clear_error.value, "cleanup failed")


def test_registry_rejects_hostile_snapshot_subclass_before_field_access():
    class FlowSentinel(SystemExit):
        pass

    class HostileSnapshot(config.RuntimeConfiguration):
        def __getattribute__(self, name):
            raise FlowSentinel(19)

    hostile = object.__new__(HostileSnapshot)

    assert config._runtime_configuration_is_valid(hostile) is False
    with pytest.raises(config.RuntimeConfigurationError) as caught:
        config.install_runtime_configuration(hostile)

    assert_safe_runtime_configuration_error(caught.value, "installation failed")


def test_runtime_configuration_loader_reads_one_document_for_all_values(
    workspace_tmp_path, monkeypatch,
):
    corpus_root = workspace_tmp_path / "loaded-corpus"
    managed_root = workspace_tmp_path / "loaded-managed"
    corpus_root.mkdir()
    managed_root.mkdir()
    path = missing_config(workspace_tmp_path)
    path.write_text(json.dumps({
        "MYSQL_HOST": "file-host",
        "MYSQL_PASSWORD": "file-password",
        "CORPUS_ROOT": str(corpus_root),
        "MANAGED_CORPUS_ROOT": str(managed_root),
    }), encoding="utf-8")
    original_read_text = Path.read_text
    reads = []

    def counted_read_text(selected, *args, **kwargs):
        reads.append(selected)
        return original_read_text(selected, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)

    snapshot = config.load_runtime_configuration(
        environment={
            "MYSQL_HOST": "environment-host",
            "MARKET_SCHEDULER_ENABLED": "true",
        },
        config_path=path,
    )

    assert reads == [path]
    assert snapshot.mysql_pool_options()["host"] == "environment-host"
    assert snapshot.mysql_pool_options()["password"] == "file-password"
    assert snapshot.corpus_root == corpus_root.resolve(strict=True)
    assert snapshot.managed_corpus_root == managed_root.resolve(strict=True)
    assert snapshot.market_scheduler_enabled is True


def test_runtime_configuration_registry_is_identity_bound(runtime_configuration):
    with pytest.raises(
        config.RuntimeConfigurationError,
        match="^runtime configuration is unavailable$",
    ) as unavailable:
        config.current_runtime_configuration()
    assert_safe_runtime_configuration_error(unavailable.value, "is unavailable")

    config.install_runtime_configuration(runtime_configuration)
    assert config.current_runtime_configuration() is runtime_configuration
    with pytest.raises(
        config.RuntimeConfigurationError,
        match="^runtime configuration cleanup failed$",
    ) as wrong_snapshot:
        config.clear_runtime_configuration(dataclasses.replace(runtime_configuration))
    assert_safe_runtime_configuration_error(
        wrong_snapshot.value, "cleanup failed"
    )
    assert config.current_runtime_configuration() is runtime_configuration
    config.clear_runtime_configuration(runtime_configuration)

    with pytest.raises(
        config.RuntimeConfigurationError,
        match="^runtime configuration is unavailable$",
    ) as cleared:
        config.current_runtime_configuration()
    assert_safe_runtime_configuration_error(cleared.value, "is unavailable")


def test_runtime_configuration_rejects_duplicate_and_non_exact_install(
    runtime_configuration,
):
    class RuntimeConfigurationSubclass(config.RuntimeConfiguration):
        pass

    subclass = object.__new__(RuntimeConfigurationSubclass)
    with pytest.raises(
        config.RuntimeConfigurationError,
        match="^runtime configuration installation failed$",
    ) as invalid:
        config.install_runtime_configuration(subclass)
    assert_safe_runtime_configuration_error(
        invalid.value, "installation failed"
    )

    config.install_runtime_configuration(runtime_configuration)
    with pytest.raises(
        config.RuntimeConfigurationError,
        match="^runtime configuration installation failed$",
    ) as duplicate:
        config.install_runtime_configuration(dataclasses.replace(runtime_configuration))
    assert_safe_runtime_configuration_error(
        duplicate.value, "installation failed"
    )
    assert config.current_runtime_configuration() is runtime_configuration
    config.clear_runtime_configuration(runtime_configuration)


def test_administrative_helpers_load_configuration_when_invoked(
    workspace_tmp_path, monkeypatch,
):
    path = missing_config(workspace_tmp_path)
    reads = []

    def fake_loader(*, environment=None, config_path=config.LOCAL_CONFIG_PATH):
        reads.append((environment, config_path))
        return {"password": "command-secret"}

    monkeypatch.setattr(config, "load_mysql_config", fake_loader)

    assert config.require_mysql_config() == {"password": "command-secret"}
    assert reads == [(None, config.LOCAL_CONFIG_PATH)]


def test_administrative_corpus_helpers_load_configuration_when_invoked(
    workspace_tmp_path, monkeypatch,
):
    corpus_root = workspace_tmp_path / "command-corpus"
    managed_root = workspace_tmp_path / "command-managed"
    corpus_root.mkdir()
    managed_root.mkdir()
    calls = []

    monkeypatch.setattr(
        config,
        "load_corpus_root",
        lambda: calls.append("corpus") or corpus_root,
    )
    monkeypatch.setattr(
        config,
        "load_managed_corpus_root",
        lambda: calls.append("managed") or managed_root,
    )

    assert config.require_corpus_root() == corpus_root.resolve(strict=True)
    assert config.require_managed_corpus_root() == managed_root.resolve(strict=True)
    assert calls == ["corpus", "managed"]


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


def test_managed_corpus_root_never_falls_back_to_discovery_root(
    workspace_tmp_path,
):
    source_root = workspace_tmp_path / "source-corpus"
    source_root.mkdir()

    managed = config.load_managed_corpus_root(
        environment={"CORPUS_ROOT": str(source_root)},
        config_path=missing_config(workspace_tmp_path),
    )

    assert managed is None


def test_require_managed_corpus_root_fails_closed_when_unconfigured():
    with pytest.raises(
        config.LocalCorpusConfigError, match="MANAGED_CORPUS_ROOT"
    ):
        config.require_managed_corpus_root(None)


def test_managed_corpus_root_can_be_explicitly_separated_from_source_discovery(
    workspace_tmp_path,
):
    source_root = workspace_tmp_path / "source-corpus"
    managed_root = workspace_tmp_path / "managed-corpus"
    source_root.mkdir()
    managed_root.mkdir()

    managed = config.load_managed_corpus_root(
        environment={
            "CORPUS_ROOT": str(source_root),
            "MANAGED_CORPUS_ROOT": str(managed_root),
        },
        config_path=missing_config(workspace_tmp_path),
    )

    assert managed == managed_root.resolve(strict=True)


def test_managed_corpus_root_rejects_a_filesystem_link(
    workspace_tmp_path,
):
    actual = workspace_tmp_path / "actual-managed"
    linked = workspace_tmp_path / "linked-managed"
    actual.mkdir()
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(config.LocalCorpusConfigError):
        config.load_managed_corpus_root(
            environment={"MANAGED_CORPUS_ROOT": str(linked)},
            config_path=missing_config(workspace_tmp_path),
        )
