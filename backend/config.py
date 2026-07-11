"""Fail-closed local MySQL configuration without a checked-in secret."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG_PATH = REPOSITORY_ROOT / ".env.local.json"
_ALLOWED_FILE_KEYS = frozenset({
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DB",
})
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


def _read_local_document(config_path: Path) -> dict[str, object]:
    try:
        source = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as exc:
        raise LocalMySQLConfigError(
            "Could not read the repository-local MySQL configuration"
        ) from exc
    try:
        document = json.loads(source)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LocalMySQLConfigError(
            "Repository-local MySQL configuration is not valid JSON"
        ) from exc
    if type(document) is not dict:
        raise LocalMySQLConfigError("Local MySQL configuration must be a JSON object")
    unknown = set(document) - _ALLOWED_FILE_KEYS
    if unknown:
        raise LocalMySQLConfigError("Local MySQL configuration contains unknown keys")
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
        values[name] = (
            _checked_port(value, environment_value=False)
            if name == "MYSQL_PORT"
            else _checked_text(name, value)
        )
    for name in _ALLOWED_FILE_KEYS:
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


MYSQL_CONFIG = load_mysql_config()
