"""Fail-closed local configuration without checked-in secrets or path defaults."""

from __future__ import annotations

import json
import os
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


class LocalMySQLConfigError(RuntimeError):
    """The private local MySQL configuration is absent or unsafe."""


class LocalCorpusConfigError(RuntimeError):
    """The explicitly configured local corpus root is absent or unsafe."""


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
    values = dict(_DEFAULTS)
    file_values = _read_local_document(Path(config_path))
    for name, value in file_values.items():
        if name not in _MYSQL_FILE_KEYS:
            continue
        values[name] = (
            _checked_port(value, environment_value=False)
            if name == "MYSQL_PORT"
            else _checked_text(name, value)
        )
    for name in _MYSQL_FILE_KEYS:
        if name not in source:
            continue
        value = source[name]
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
    selected = MYSQL_CONFIG if config is None else config
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
    selected = file_values.get("CORPUS_ROOT")
    if "CORPUS_ROOT" in source:
        selected = source["CORPUS_ROOT"]
    if selected is None:
        return None
    return _checked_corpus_root(selected)


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
    selected = file_values.get("MANAGED_CORPUS_ROOT")
    if "MANAGED_CORPUS_ROOT" in source:
        selected = source["MANAGED_CORPUS_ROOT"]
    if selected is None:
        return None
    return _checked_corpus_root(selected, "MANAGED_CORPUS_ROOT")


_UNSET = object()


def require_corpus_root(root: Path | None | object = _UNSET) -> Path:
    """Return the configured corpus root or fail before any corpus file access."""
    selected = CORPUS_ROOT if root is _UNSET else root
    if not isinstance(selected, Path):
        raise LocalCorpusConfigError("CORPUS_ROOT is not configured")
    return _checked_corpus_root(str(selected))


def require_managed_corpus_root(root: Path | None | object = _UNSET) -> Path:
    """Return the configured managed root or fail before any blob write."""

    selected = MANAGED_CORPUS_ROOT if root is _UNSET else root
    if not isinstance(selected, Path):
        raise LocalCorpusConfigError("MANAGED_CORPUS_ROOT is not configured")
    return _checked_corpus_root(str(selected), "MANAGED_CORPUS_ROOT")


MYSQL_CONFIG = load_mysql_config()
CORPUS_ROOT = load_corpus_root()
MANAGED_CORPUS_ROOT = load_managed_corpus_root()
