"""Fail-closed local configuration without checked-in secrets or path defaults."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG_PATH = REPOSITORY_ROOT / ".env.local.json"
_MYSQL_FILE_KEYS = frozenset({
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DB",
})
_ALLOWED_FILE_KEYS = _MYSQL_FILE_KEYS | {
    "CORPUS_ROOT",
    "MANAGED_CORPUS_ROOT",
}
_OUTPUT_KEYS = {
    "MYSQL_HOST": "host",
    "MYSQL_PORT": "port",
    "MYSQL_USER": "user",
    "MYSQL_PASSWORD": "password",
    "MYSQL_DB": "db",
}
_DEFAULTS: dict[str, object] = {
    "MYSQL_HOST": "127.0.0.1",
    "MYSQL_PORT": 3307,
    "MYSQL_USER": "root",
    "MYSQL_PASSWORD": None,
    "MYSQL_DB": "novel_creator",
}
_RUNTIME_MYSQL_KEYS = (
    "host",
    "port",
    "user",
    "password",
    "db",
    "charset",
    "autocommit",
    "minsize",
    "maxsize",
)
_RUNTIME_TEXT_KEYS = frozenset({
    "host",
    "user",
    "password",
    "db",
    "charset",
})
_RUNTIME_INTEGER_KEYS = frozenset({"port", "minsize", "maxsize"})
_RUNTIME_PATH_TYPE = type(Path())


class LocalMySQLConfigError(RuntimeError):
    """The private local MySQL configuration is absent or unsafe."""


class LocalCorpusConfigError(RuntimeError):
    """The explicitly configured local corpus root is absent or unsafe."""


class LocalSchedulerConfigError(RuntimeError):
    """The optional local market scheduler flag is invalid."""


class RuntimeConfigurationError(RuntimeError):
    """The process-local runtime configuration authority is unavailable."""


@dataclass(frozen=True)
class RuntimeConfiguration:
    """One immutable configuration snapshot owned by a backend lifespan."""

    mysql_items: tuple[tuple[str, object], ...]
    corpus_root: Path | None
    managed_corpus_root: Path | None
    market_scheduler_enabled: bool

    def __post_init__(self) -> None:
        if not _runtime_configuration_is_valid(self):
            raise RuntimeConfigurationError(
                "runtime configuration is invalid"
            ) from None

    def mysql_pool_options(self) -> dict[str, object]:
        if not _runtime_configuration_is_valid(self):
            raise RuntimeConfigurationError(
                "runtime configuration is invalid"
            ) from None
        return dict(self.mysql_items)


_active_runtime_configuration: RuntimeConfiguration | None = None


def _runtime_configuration_is_valid(snapshot: RuntimeConfiguration) -> bool:
    mysql_items = snapshot.mysql_items
    if type(mysql_items) is not tuple or len(mysql_items) != len(
        _RUNTIME_MYSQL_KEYS
    ):
        return False
    for index, expected_key in enumerate(_RUNTIME_MYSQL_KEYS):
        item = mysql_items[index]
        if type(item) is not tuple or len(item) != 2:
            return False
        key, value = item
        if type(key) is not str or key != expected_key:
            return False
        if key in _RUNTIME_TEXT_KEYS and type(value) is not str:
            return False
        if key in _RUNTIME_INTEGER_KEYS and type(value) is not int:
            return False
        if key == "autocommit" and type(value) is not bool:
            return False
        if key in {"host", "user", "password", "db"} and not value.strip():
            return False
        if key == "port" and not 1 <= value <= 65535:
            return False
        if key == "charset" and value != "utf8mb4":
            return False
        if key == "autocommit" and value is not True:
            return False
        if key == "minsize" and value != 1:
            return False
        if key == "maxsize" and value != 10:
            return False
    if (
        snapshot.corpus_root is not None
        and type(snapshot.corpus_root) is not _RUNTIME_PATH_TYPE
    ):
        return False
    if (
        snapshot.managed_corpus_root is not None
        and type(snapshot.managed_corpus_root) is not _RUNTIME_PATH_TYPE
    ):
        return False
    return type(snapshot.market_scheduler_enabled) is bool


def load_market_scheduler_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Enable the local scheduler only through one explicit boolean flag."""

    source = os.environ if environment is None else environment
    value = source.get("MARKET_SCHEDULER_ENABLED")
    if value is None:
        return False
    if value == "true":
        return True
    if value == "false":
        return False
    raise LocalSchedulerConfigError(
        "MARKET_SCHEDULER_ENABLED must be exactly 'true' or 'false'"
    )


def _checked_port(value: object, *, environment_value: bool) -> int:
    if environment_value:
        if type(value) is not str:
            raise LocalMySQLConfigError("MYSQL_PORT environment value must be text")
        try:
            port = int(value)
        except ValueError as exc:
            raise LocalMySQLConfigError("MYSQL_PORT must be an integer") from exc
    else:
        if type(value) is not int:
            raise LocalMySQLConfigError("MYSQL_PORT file value must be an integer")
        port = value
    if not 1 <= port <= 65535:
        raise LocalMySQLConfigError("MYSQL_PORT must be between 1 and 65535")
    return port


def _checked_text(name: str, value: object) -> str:
    if type(value) is not str or not value.strip():
        raise LocalMySQLConfigError(f"{name} must be non-empty text")
    return value


def _read_local_document(
    config_path: Path,
    *,
    error_type: type[RuntimeError] = LocalMySQLConfigError,
    subject: str = "MySQL",
) -> dict[str, object]:
    try:
        source = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as exc:
        raise error_type(
            f"Could not read the repository-local {subject} configuration"
        ) from exc
    try:
        document = json.loads(source)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise error_type(
            f"Repository-local {subject} configuration is not valid JSON"
        ) from exc
    if type(document) is not dict:
        raise error_type(f"Local {subject} configuration must be a JSON object")
    unknown = set(document) - _ALLOWED_FILE_KEYS
    if unknown:
        raise error_type(f"Local {subject} configuration contains unknown keys")
    return document


def load_mysql_config(
    *,
    environment: Mapping[str, str] | None = None,
    config_path: Path = LOCAL_CONFIG_PATH,
) -> dict[str, object]:
    """Load strict file values, overlay explicit environment values, and add pool options."""
    source = os.environ if environment is None else environment
    file_values = _read_local_document(Path(config_path))
    return _mysql_config_from_document(document=file_values, environment=source)


def _mysql_config_from_document(
    *, document: Mapping[str, object], environment: Mapping[str, str],
) -> dict[str, object]:
    values = dict(_DEFAULTS)
    for name, value in document.items():
        if name not in _MYSQL_FILE_KEYS:
            continue
        values[name] = (
            _checked_port(value, environment_value=False)
            if name == "MYSQL_PORT"
            else _checked_text(name, value)
        )
    for name in _MYSQL_FILE_KEYS:
        if name not in environment:
            continue
        value = environment[name]
        values[name] = (
            _checked_port(value, environment_value=True)
            if name == "MYSQL_PORT"
            else _checked_text(name, value)
        )

    loaded = {_OUTPUT_KEYS[name]: values[name] for name in _OUTPUT_KEYS}
    loaded.update({
        "charset": "utf8mb4",
        "autocommit": True,
        "minsize": 1,
        "maxsize": 10,
    })
    return loaded


def require_mysql_config(
    config: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return a safe copy or fail before a real MySQL connector is called."""
    selected = load_mysql_config() if config is None else config
    if type(selected.get("password")) is not str or not selected["password"]:
        raise LocalMySQLConfigError(
            "MYSQL_PASSWORD is not configured; run the local MySQL setup command"
        )
    return dict(selected)


def _checked_corpus_root(
    value: object, name: str = "CORPUS_ROOT"
) -> Path:
    if type(value) is not str or not value.strip():
        raise LocalCorpusConfigError(
            f"{name} must be non-empty absolute text"
        )
    candidate = Path(value)
    if not candidate.is_absolute():
        raise LocalCorpusConfigError(f"{name} must be an absolute path")
    try:
        metadata = candidate.lstat()
        if name == "MANAGED_CORPUS_ROOT" and (
            stat.S_ISLNK(metadata.st_mode)
            or bool(
                getattr(metadata, "st_file_attributes", 0)
                & 0x400
            )
        ):
            raise LocalCorpusConfigError(
                "MANAGED_CORPUS_ROOT cannot be a filesystem link"
            )
        resolved = candidate.resolve(strict=True)
    except LocalCorpusConfigError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalCorpusConfigError(f"{name} does not exist safely") from exc
    if not resolved.is_dir():
        raise LocalCorpusConfigError(f"{name} must identify a directory")
    return resolved


def load_corpus_root(
    *,
    environment: Mapping[str, str] | None = None,
    config_path: Path = LOCAL_CONFIG_PATH,
) -> Path | None:
    """Load only an explicitly configured, existing corpus directory."""
    source = os.environ if environment is None else environment
    file_values = _read_local_document(
        Path(config_path),
        error_type=LocalCorpusConfigError,
        subject="corpus",
    )
    return _corpus_root_from_document(
        document=file_values,
        environment=source,
        name="CORPUS_ROOT",
    )


def load_managed_corpus_root(
    *,
    environment: Mapping[str, str] | None = None,
    config_path: Path = LOCAL_CONFIG_PATH,
) -> Path | None:
    """Load only an explicitly configured managed corpus directory."""

    source = os.environ if environment is None else environment
    file_values = _read_local_document(
        Path(config_path),
        error_type=LocalCorpusConfigError,
        subject="corpus",
    )
    return _corpus_root_from_document(
        document=file_values,
        environment=source,
        name="MANAGED_CORPUS_ROOT",
    )


def _corpus_root_from_document(
    *, document: Mapping[str, object], environment: Mapping[str, str], name: str,
) -> Path | None:
    selected = document.get(name)
    if name in environment:
        selected = environment[name]
    if selected is None:
        return None
    return _checked_corpus_root(selected, name)


def load_runtime_configuration(
    *,
    environment: Mapping[str, str] | None = None,
    config_path: Path = LOCAL_CONFIG_PATH,
) -> RuntimeConfiguration:
    """Read once and build the closed configuration authority for one lifespan."""

    source = os.environ if environment is None else environment
    document = _read_local_document(Path(config_path))
    mysql = _mysql_config_from_document(document=document, environment=source)
    return RuntimeConfiguration(
        mysql_items=tuple(mysql.items()),
        corpus_root=_corpus_root_from_document(
            document=document,
            environment=source,
            name="CORPUS_ROOT",
        ),
        managed_corpus_root=_corpus_root_from_document(
            document=document,
            environment=source,
            name="MANAGED_CORPUS_ROOT",
        ),
        market_scheduler_enabled=load_market_scheduler_enabled(environment=source),
    )


def install_runtime_configuration(snapshot: RuntimeConfiguration) -> None:
    global _active_runtime_configuration
    if (
        type(snapshot) is not RuntimeConfiguration
        or _active_runtime_configuration is not None
        or not _runtime_configuration_is_valid(snapshot)
    ):
        raise RuntimeConfigurationError(
            "runtime configuration installation failed"
        ) from None
    _active_runtime_configuration = snapshot


def current_runtime_configuration() -> RuntimeConfiguration:
    if _active_runtime_configuration is None:
        raise RuntimeConfigurationError(
            "runtime configuration is unavailable"
        ) from None
    return _active_runtime_configuration


def clear_runtime_configuration(snapshot: RuntimeConfiguration) -> None:
    global _active_runtime_configuration
    if _active_runtime_configuration is not snapshot:
        raise RuntimeConfigurationError(
            "runtime configuration cleanup failed"
        ) from None
    _active_runtime_configuration = None


_UNSET = object()


def require_corpus_root(root: Path | None | object = _UNSET) -> Path:
    """Return the configured corpus root or fail before any corpus file access."""
    selected = load_corpus_root() if root is _UNSET else root
    if not isinstance(selected, Path):
        raise LocalCorpusConfigError("CORPUS_ROOT is not configured")
    return _checked_corpus_root(str(selected))


def require_managed_corpus_root(root: Path | None | object = _UNSET) -> Path:
    """Return the configured managed root or fail before any blob write."""

    selected = load_managed_corpus_root() if root is _UNSET else root
    if not isinstance(selected, Path):
        raise LocalCorpusConfigError("MANAGED_CORPUS_ROOT is not configured")
    return _checked_corpus_root(str(selected), "MANAGED_CORPUS_ROOT")
