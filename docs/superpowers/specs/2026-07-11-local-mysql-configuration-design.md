# Local MySQL Configuration Design

## Goal

Replace the checked-in MySQL password fallback with a fail-closed, repository-local configuration file and provide a Windows setup command that verifies an existing MySQL 8.4-compatible server without creating or mutating database state.

## Configuration loading

`backend/config.py` loads `<repository>/.env.local.json` when it exists. The JSON root must be an object containing only `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, and `MYSQL_DB`. File values use strict JSON types: the port is an integer from 1 through 65535 (booleans are rejected), and every other value is a non-empty string. Invalid JSON, an unknown key, a wrong type, or any file read error raises `LocalMySQLConfigError`; none of these cases falls back silently.

Process environment values override corresponding file values one key at a time. Environment values are non-empty strings, with `MYSQL_PORT` parsed and range checked. Defaults exist only for non-secret local metadata: host `127.0.0.1`, port `3307`, user `root`, and database `novel_creator`. There is no default password.

Importing the module remains safe for pure unit tests and performs no connection. `MYSQL_CONFIG` may represent an unconfigured password, while `require_mysql_config()` raises a clear configuration error before any real connector or pool initialization. Database entry points that otherwise consume the module default call this guard first; explicitly injected test configurations remain unaffected.

## Setup command

`backend/scripts/configure_local_mysql.py` accepts `--host`, `--port`, `--user`, and `--database`, with the same local defaults. It never accepts a password argument. It reads the password through `getpass.getpass()` and rejects an empty password.

The command connects without selecting or creating a database and runs the same read-only capability gate as the formal Writer Core reset: the version must have major version 8 and be at least 8.0.16, `utf8mb4_0900_ai_ci` must exist, `JSON_VALID` must work, and `information_schema.CHECK_CONSTRAINTS` must be queryable. The intended local target is MySQL 8.4.10, while the gate checks capabilities instead of comparing only a display string. Connection and close boundaries are explicit and injectable for unit tests. Successful output contains only host, port, user, database, and server version. Failures print one generic message; neither path renders a password or DSN.

## Atomic private file publication

The command creates an empty, explicitly ignored `.env.local.*.tmp` file in the repository root and immediately invokes an injectable ACL runner on that empty file. Only after ACL restriction succeeds does it open the temporary file, serialize exactly the five allowed keys, flush, and fsync. The Windows implementation runs `icacls` with inherited permissions removed and grants the current user access. Captured `icacls` output is never forwarded.

After the private temporary file is fully written, the writer performs a same-directory `os.replace`, so the target retains the restricted temporary file ACL. If ACL restriction, writing, fsync, or replacement fails, the temporary file is removed and any existing `.env.local.json` remains unchanged. An ACL failure or interruption before writing therefore leaves no secret in the temporary file. `.gitignore` explicitly covers both `.env.local.json` and `.env.local.*.tmp`.

If `aiomysql.connect` succeeds but admin cursor creation fails, the connection factory closes the raw connection with `ensure_closed()` when available or `close()` otherwise. A simultaneous cursor and close failure is preserved as a `BaseExceptionGroup` rather than losing either error.

## Error and security boundaries

- Loading malformed or unreadable local configuration fails closed.
- Missing password fails before default database initialization calls a connector.
- The setup command never creates a database, user, table, or other server object.
- ACL failure never publishes the new file.
- Password values do not enter stdout, stderr, exception text created by this feature, subprocess arguments, or logs.
- `--help` exits zero without prompting, connecting, or writing.

## Test strategy

Unit tests cover strict file validation, environment precedence, safe defaults, missing-password preflight, the complete version/collation/JSON/CHECK gate, read-only connector behavior, secret-free output, injected write/ACL order, ACL cleanup with preservation of an existing target, exact persisted keys, and subprocess help. All connector tests use fakes; the test suite must not connect to MySQL or invoke a Provider.
