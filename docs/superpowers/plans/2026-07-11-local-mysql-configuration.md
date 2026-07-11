# Local MySQL Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load private local MySQL credentials safely and add a Windows setup command that validates an existing compatible server before atomically publishing the configuration.

**Architecture:** `backend/config.py` owns strict file/environment parsing and a connector preflight. The setup script owns interactive password capture, reuse of the formal read-only capability gate, secret-free reporting, and ACL-before-replace file publication. Existing database entry points call the preflight only when they use module-default configuration, so injected unit/integration configurations keep working.

**Tech Stack:** Python 3.12, argparse, asyncio, aiomysql, pathlib/tempfile/os.replace, subprocess/icacls, pytest.

---

### Task 1: Strict repository-local configuration

**Files:**
- Modify: `backend/config.py`
- Create: `backend/tests/unit/test_config.py`

- [ ] **Step 1: Write failing loader tests**

Cover safe defaults (`127.0.0.1:3307`, `root`, `novel_creator`, no password), exact allowlist, malformed JSON, non-object JSON, unknown keys, strict file types, invalid ports, file read `OSError`, and per-key environment precedence. Use `tmp_path`; do not import or call a connector.

- [ ] **Step 2: Run the loader tests and verify RED**

Run: `python -m pytest backend/tests/unit/test_config.py -q`

Expected: failures because `load_mysql_config`, `LocalMySQLConfigError`, and `require_mysql_config` do not exist and the old defaults still use port 3306/password `123456`.

- [ ] **Step 3: Implement the strict loader and preflight**

Add:

```python
class LocalMySQLConfigError(RuntimeError): ...

def load_mysql_config(*, environment=None, config_path=LOCAL_CONFIG_PATH): ...
def require_mysql_config(config=None): ...
```

Only accept the five `MYSQL_*` keys, reject booleans as ports, translate file/read/JSON failures to `LocalMySQLConfigError`, overlay environment values, and return the aiomysql options plus fixed pool options. `require_mysql_config` must reject a missing or empty password without rendering it.

- [ ] **Step 4: Run the loader tests and verify GREEN**

Run: `python -m pytest backend/tests/unit/test_config.py -q`

Expected: all tests pass.

### Task 2: Fail before default connector initialization

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/scripts/initialize_database.py`
- Modify: `backend/scripts/reset_writer_core_data.py`
- Modify: `backend/tests/unit/test_database_transaction.py`
- Modify: `backend/tests/unit/test_initialize_database.py`
- Modify: `backend/tests/unit/test_reset_writer_core_data.py`

- [ ] **Step 1: Write failing preflight tests**

Patch each default `MYSQL_CONFIG` to omit the password, inject a connector/pool callable that records invocation, and assert `LocalMySQLConfigError` is raised while the callable remains untouched. Keep existing explicit `connection_config` tests unchanged.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest backend/tests/unit/test_database_transaction.py backend/tests/unit/test_initialize_database.py backend/tests/unit/test_reset_writer_core_data.py -q`

Expected: the fake pool/connection is invoked or the wrong exception is raised.

- [ ] **Step 3: Guard only module-default configuration**

Use `require_mysql_config(MYSQL_CONFIG)` immediately before `aiomysql.create_pool` in `database.py`. In each CLI, call `require_mysql_config()` only inside the existing `if connection_config is None` branch. Do not change behavior for injected configurations.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2 and expect all tests to pass.

### Task 3: Read-only capability validation CLI

**Files:**
- Create: `backend/scripts/configure_local_mysql.py`
- Create: `backend/tests/unit/test_configure_local_mysql.py`
- Modify: `backend/scripts/reset_writer_core_data.py`

- [ ] **Step 1: Write failing CLI behavior tests**

Use fake sessions/connectors to assert defaults, hidden password reader use, no database in connection kwargs, exactly the formal version/collation/JSON/CHECK reads, rejection of MySQL 5.7/non-8/wrong capability rows, close on success/failure, and no writer call on validation failure. Assert a secret sentinel is absent from output and errors.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest backend/tests/unit/test_configure_local_mysql.py -q`

Expected: import failure because the setup module does not exist.

- [ ] **Step 3: Implement injectable async orchestration**

Create an argparse CLI with host `127.0.0.1`, port `3307`, user `root`, database `novel_creator`, and no password argument. Inject `password_reader`, `connector`, `file_writer`, `acl_runner`, `config_path`, and `output`. Reuse `_verify_reset_server_capabilities`; change it to return the verified version string while retaining its existing exceptions and checks. Connect without `db`, close in `finally`, then write only after all checks pass.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2 and expect all tests to pass.

### Task 4: ACL-before-atomic-replace publication

**Files:**
- Modify: `backend/scripts/configure_local_mysql.py`
- Modify: `backend/tests/unit/test_configure_local_mysql.py`

- [ ] **Step 1: Write failing publication tests**

With `tmp_path`, assert the writer creates a same-directory temporary file, flushes it, invokes ACL on the temporary path while the old target is intact, and only then replaces the target. Make ACL fail and assert the old target is byte-for-byte unchanged and no temporary file remains. Verify the successful JSON contains exactly the five allowed keys.

- [ ] **Step 2: Run focused tests and verify RED**

Run the Task 3 test command and expect missing writer/ACL behavior failures.

- [ ] **Step 3: Implement private publication**

Implement `restrict_windows_acl(path, runner=subprocess.run, username=getpass.getuser())` with `icacls`, `/inheritance:r`, and a current-user-only replacement grant. Implement `atomic_write_local_config` with `NamedTemporaryFile(delete=False, dir=target.parent)`, JSON serialization, flush/fsync, ACL call, and `os.replace`; unlink the temp in every failure path and never forward subprocess output.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 3 test command and expect all tests to pass.

### Task 5: Process contract and final verification

**Files:**
- Modify: `backend/tests/unit/test_configure_local_mysql.py`

- [ ] **Step 1: Add subprocess help and failure-wrapper tests**

Assert `python -m backend.scripts.configure_local_mysql --help` exits zero with empty stderr and does not prompt/connect/write. Patch `asyncio.run` to raise a secret-bearing runtime exception and assert `main` returns one with only a generic, secret-free stderr message.

- [ ] **Step 2: Run the full repository unit gate**

Run: `npm test`

Expected: Python, script, and frontend unit suites all exit zero.

- [ ] **Step 3: Review security and scope**

Run `git diff --check`, inspect the full diff, scan tracked source for the removed `123456` password default, confirm `.env.local.json` remains ignored, and confirm no test or command connected to MySQL or a Provider.

- [ ] **Step 4: Commit implementation**

```powershell
git add backend/config.py backend/database.py backend/scripts/initialize_database.py backend/scripts/reset_writer_core_data.py backend/scripts/configure_local_mysql.py backend/tests/unit/test_config.py backend/tests/unit/test_database_transaction.py backend/tests/unit/test_initialize_database.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_configure_local_mysql.py docs/superpowers/plans/2026-07-11-local-mysql-configuration.md
git commit -m "feat: configure private local MySQL access"
```
