"""Test-only disposable MySQL harness with fail-closed identity guards."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import secrets
from typing import Awaitable, Callable, Mapping
from urllib.parse import unquote, urlsplit


_ROOT = Path(__file__).parents[3]
_MINIMAL_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "control_plane_minimal_schema.sql"
_APPLY_MIGRATION_PATH = _ROOT / "backend" / "migrations" / "20260710_control_plane_draft_write_batches.sql"
_ROLLBACK_MIGRATION_PATH = _ROOT / "backend" / "migrations" / "20260710_control_plane_draft_write_batches_rollback.sql"
_SCHEMA_PREFIX = "novel_creator_control_plane_disposable_"
_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{24}$")
_CREATE_TABLE_PATTERN = re.compile(
    r"\ACREATE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)
_ALLOWED_FIXTURE_TABLES = {"projects", "chapters", "chapter_versions"}
_SAFE_CONFIGURATION_MESSAGE = "The disposable database harness was not safely configured."
_MINIMAL_FIXTURE_SHA256 = "dc8aa7031ce0da86a2c8d2927b212af686d57e2f6a4271ddfddb5a65613942c0"
_APPLY_MIGRATION_SHA256 = "9e8c0d4a8f9bced55fa7ecfbb25121d9bc3a9ad21a2821de1a5c0651abe8c53d"


class HarnessConfigurationError(RuntimeError):
    """The disposable database harness was not safely configured."""


@dataclass(frozen=True)
class AdminDSN:
    host: str
    port: int
    user: str
    password: str = field(repr=False)


@dataclass
class DisposableMySQL:
    schema_name: str
    run_token: str
    pool: object


def _configuration_error() -> HarnessConfigurationError:
    return HarnessConfigurationError(_SAFE_CONFIGURATION_MESSAGE)


def parse_admin_dsn(raw: str) -> AdminDSN:
    """Accept a loopback mysql:// admin DSN with no selected database."""

    if type(raw) is not str or not raw:
        raise _configuration_error()
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port if parsed.port is not None else 3306
        user = unquote(parsed.username) if parsed.username is not None else None
        password = unquote(parsed.password) if parsed.password is not None else ""
    except (TypeError, ValueError, UnicodeError):
        raise _configuration_error() from None
    if (
        parsed.scheme != "mysql"
        or host not in {"localhost", "127.0.0.1", "::1"}
        or not user
        or parsed.path != ""
        or parsed.query != ""
        or parsed.fragment != ""
        or "?" in raw
        or "#" in raw
        or not (1 <= port <= 65535)
        or any(ord(character) < 32 or ord(character) == 127 for character in user + password)
    ):
        raise _configuration_error()
    return AdminDSN(host=host, port=port, user=user, password=password)


def new_run_token() -> str:
    return secrets.token_hex(12)


def schema_name_for_token(token: str) -> str:
    if type(token) is not str or _TOKEN_PATTERN.fullmatch(token) is None:
        raise _configuration_error()
    return _SCHEMA_PREFIX + token


def validate_schema_identity(schema_name: str, token: str) -> None:
    expected = schema_name_for_token(token)
    if type(schema_name) is not str or schema_name != expected:
        raise _configuration_error()


def _split_sql(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def extract_created_tables(statements: list[str]) -> set[str]:
    tables: set[str] = set()
    for statement in statements:
        matched = _CREATE_TABLE_PATTERN.match(statement)
        if matched is None:
            raise _configuration_error()
        tables.add(matched.group(1).lower())
    return tables


def load_and_validate_minimal_fixture() -> list[str]:
    """Load and validate only the dedicated three-table fixture path."""

    try:
        sql = _MINIMAL_FIXTURE_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise _configuration_error() from None
    if hashlib.sha256(sql.encode("utf-8")).hexdigest() != _MINIMAL_FIXTURE_SHA256:
        raise _configuration_error()
    lowered = sql.lower()
    forbidden_patterns = (
        r"\bif\s+not\s+exists\b",
        r"\bcreate\s+database\b",
        r"\bdrop\s+database\b",
        r"\buse\s+[`a-z_]",
        r"\balter\s+table\b",
        r"\bcreate\s+table\s+[`a-z_][`a-z0-9_]*\s*\.",
    )
    if "`" in sql or any(re.search(pattern, lowered) for pattern in forbidden_patterns):
        raise _configuration_error()
    statements = _split_sql(sql)
    tables = extract_created_tables(statements)
    if len(statements) != 3 or tables != _ALLOWED_FIXTURE_TABLES:
        raise _configuration_error()
    return statements


def _validate_generated_schema_name(schema_name: str) -> str:
    if type(schema_name) is not str or not schema_name.startswith(_SCHEMA_PREFIX):
        raise _configuration_error()
    token = schema_name[len(_SCHEMA_PREFIX) :]
    validate_schema_identity(schema_name, token)
    return token


def _load_apply_migration() -> str:
    try:
        sql = _APPLY_MIGRATION_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise _configuration_error() from None
    if hashlib.sha256(sql.encode("utf-8")).hexdigest() != _APPLY_MIGRATION_SHA256:
        raise _configuration_error()
    statements = _split_sql(sql)
    if len(statements) != 1:
        raise _configuration_error()
    statement = statements[0]
    lowered = statement.lower()
    matched = _CREATE_TABLE_PATTERN.match(statement)
    if (
        matched is None
        or matched.group(1).lower() != "draft_write_batches"
        or "`" in statement
        or re.search(r"\b(if\s+not\s+exists|create\s+database|drop\s+database|use\s+|alter\s+table)\b", lowered)
    ):
        raise _configuration_error()
    return statement


def _load_rollback_migration() -> str:
    try:
        sql = _ROLLBACK_MIGRATION_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise _configuration_error() from None
    if " ".join(sql.split()) != "DROP TABLE draft_write_batches;":
        raise _configuration_error()
    return "DROP TABLE draft_write_batches"


async def create_admin_pool(create_pool: Callable[..., Awaitable[object]], dsn: AdminDSN):
    try:
        return await create_pool(
            host=dsn.host,
            port=dsn.port,
            user=dsn.user,
            password=dsn.password,
            autocommit=True,
            minsize=1,
            maxsize=1,
        )
    except Exception:
        raise _configuration_error() from None


async def create_data_pool(
    create_pool: Callable[..., Awaitable[object]],
    dsn: AdminDSN,
    schema_name: str,
):
    _validate_generated_schema_name(schema_name)
    try:
        return await create_pool(
            host=dsn.host,
            port=dsn.port,
            user=dsn.user,
            password=dsn.password,
            db=schema_name,
            autocommit=True,
            minsize=1,
            maxsize=5,
        )
    except Exception:
        raise _configuration_error() from None


async def schema_exists_exact(admin_pool: object, schema_name: str) -> bool:
    _validate_generated_schema_name(schema_name)
    async with admin_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.schemata WHERE schema_name=%s",
                (schema_name,),
            )
            row = await cursor.fetchone()
    if row is None:
        return False
    if isinstance(row, (tuple, list)):
        selected = row[0] if row else None
    elif isinstance(row, dict):
        selected = row.get("SCHEMA_NAME")
    else:
        selected = None
    if selected != schema_name:
        raise HarnessConfigurationError("Disposable schema identity mismatch")
    return True


async def assert_schema_absent(admin_pool: object, schema_name: str) -> None:
    if await schema_exists_exact(admin_pool, schema_name):
        raise HarnessConfigurationError("Disposable schema already exists")


async def create_exact_schema(admin_pool: object, schema_name: str, token: str) -> None:
    validate_schema_identity(schema_name, token)
    async with admin_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                f"CREATE DATABASE `{schema_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )


async def drop_exact_schema(admin_pool: object, schema_name: str, token: str) -> None:
    validate_schema_identity(schema_name, token)
    async with admin_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(f"DROP DATABASE `{schema_name}`")


async def assert_selected_database(conn: object, expected_schema: str) -> None:
    _validate_generated_schema_name(expected_schema)
    async with conn.cursor() as cursor:
        await cursor.execute("SELECT DATABASE()")
        row = await cursor.fetchone()
    if isinstance(row, (tuple, list)):
        selected = row[0] if row else None
    elif isinstance(row, dict):
        selected = row.get("DATABASE()")
    else:
        selected = None
    if selected != expected_schema:
        raise HarnessConfigurationError("Disposable database identity mismatch")


async def _execute_statements(conn: object, statements: list[str]) -> None:
    async with conn.cursor() as cursor:
        for statement in statements:
            await cursor.execute(statement)


async def apply_fixed_ledger_migration(pool: object, expected_schema: str) -> None:
    _validate_generated_schema_name(expected_schema)
    async with pool.acquire() as conn:
        await assert_selected_database(conn, expected_schema)
        await _execute_statements(conn, [_load_apply_migration()])
        await assert_selected_database(conn, expected_schema)


async def rollback_fixed_ledger_migration(pool: object, expected_schema: str) -> None:
    _validate_generated_schema_name(expected_schema)
    async with pool.acquire() as conn:
        await assert_selected_database(conn, expected_schema)
        await _execute_statements(conn, [_load_rollback_migration()])
        await assert_selected_database(conn, expected_schema)


async def apply_fixed_fixture_and_migration(pool: object, expected_schema: str) -> None:
    _validate_generated_schema_name(expected_schema)
    async with pool.acquire() as conn:
        await assert_selected_database(conn, expected_schema)
        await _execute_statements(conn, load_and_validate_minimal_fixture())
        await assert_selected_database(conn, expected_schema)
        await _execute_statements(conn, [_load_apply_migration()])
        await assert_selected_database(conn, expected_schema)
        await assert_selected_database(conn, expected_schema)


@asynccontextmanager
async def disposable_mysql(
    *,
    environ: Mapping[str, str],
    create_pool: Callable[..., Awaitable[object]],
):
    raw = environ.get("CONTROL_PLANE_DISPOSABLE_MYSQL_DSN")
    if raw is None:
        raise HarnessConfigurationError("CONTROL_PLANE_DISPOSABLE_MYSQL_DSN is required")
    dsn = parse_admin_dsn(raw)
    token = new_run_token()
    schema_name = schema_name_for_token(token)
    admin_pool = await create_admin_pool(create_pool, dsn)
    data_pool = None
    creation_state = "not_attempted"
    primary_error = None
    try:
        await assert_schema_absent(admin_pool, schema_name)
        creation_state = "attempted"
        try:
            await create_exact_schema(admin_pool, schema_name, token)
        except BaseException as create_error:
            try:
                exists = await schema_exists_exact(admin_pool, schema_name)
            except BaseException as reconciliation_error:
                creation_state = "unknown"
                print(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_ORPHAN={schema_name}")
                raise BaseExceptionGroup(
                    "Disposable schema creation outcome could not be confirmed.",
                    [create_error, reconciliation_error],
                ) from None
            if exists:
                creation_state = "created"
                print(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_CREATED={schema_name}")
            else:
                creation_state = "absent"
            raise
        creation_state = "created"
        print(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_CREATED={schema_name}")
        data_pool = await create_data_pool(create_pool, dsn, schema_name)
        await apply_fixed_fixture_and_migration(data_pool, schema_name)
        yield DisposableMySQL(schema_name=schema_name, run_token=token, pool=data_pool)
    except BaseException as error:
        primary_error = error
    finally:
        cleanup_errors: list[BaseException] = []
        if data_pool is not None:
            try:
                data_pool.close()
            except BaseException as error:
                cleanup_errors.append(error)
            try:
                await data_pool.wait_closed()
            except BaseException as error:
                cleanup_errors.append(error)
        if creation_state == "created":
            try:
                validate_schema_identity(schema_name, token)
                await drop_exact_schema(admin_pool, schema_name, token)
                print(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_DROPPED={schema_name}")
            except BaseException as error:
                print(f"CONTROL_PLANE_DISPOSABLE_SCHEMA_ORPHAN={schema_name}")
                cleanup_errors.append(error)
        try:
            admin_pool.close()
        except BaseException as error:
            cleanup_errors.append(error)
        try:
            await admin_pool.wait_closed()
        except BaseException as error:
            cleanup_errors.append(error)

    failures = ([primary_error] if primary_error is not None else []) + cleanup_errors
    if len(failures) == 1:
        raise failures[0]
    if failures:
        raise BaseExceptionGroup("Disposable MySQL lifecycle failed.", failures) from None
