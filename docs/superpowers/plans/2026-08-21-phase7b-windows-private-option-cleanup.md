# Phase 7B Windows Private Option Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Phase 7B private MySQL option files owner-only and reliably deletable on Windows, then diagnose the published backup through one bounded restore drill without retrying real Stage A.

**Architecture:** Keep the local-configuration `(R,W)` ACL contract unchanged and route only Phase 7B backup resources through the existing verified owner-only full-control permissions boundary. Preserve the owner-handle scrub and identity-bound delete algorithm. After code verification, run one temporary helper that restores the published dump into the closed `novel_creator_phase7b_restore_<32hex>` namespace, compares inventory, and proves cleanup.

**Tech Stack:** Python 3.12, ctypes/Win32 file handles, Windows ACLs via `icacls`, pytest, asyncio, aiomysql, MySQL 8.4 clients, Git.

---

## Fixed boundaries

- Work only in `D:\Projects\Novel_Creater\.worktrees\phase7b-implementation` on `codex/phase7b-implementation`.
- Do not change `backend.scripts.configure_local_mysql.restrict_windows_acl`.
- Do not weaken owner identity, reparse-point, hard-link, scrub, cleanup precedence, or secret-sanitization checks.
- Do not write `novel_creator` or `novel_creator_v113`.
- The diagnostic may create only one run-owned `novel_creator_phase7b_restore_<32 lowercase hex>` and must drop it in `finally`.
- Preserve the published SQL backup and the existing zero-byte option-file residue.
- Do not run real Stage A, Stage B, a Provider call, or a market refresh.

## File map

- Modify `backend/services/product_database_backup.py` — select the shared verified private-permissions boundary for Phase 7B resources.
- Modify `backend/tests/unit/test_product_database_backup.py` — add a real Windows ACL lifecycle regression and adapter tests.
- Temporarily create then remove `tmp/run_phase7b_published_backup_restore_diagnostic.py` — one-shot secret-free bridge and restore audit; never commit it.

## Task 1: Reproduce the production ACL cleanup defect

**Files:**
- Modify: `backend/tests/unit/test_product_database_backup.py`
- Test: `backend/tests/unit/test_product_database_backup.py`

- [ ] **Step 1: Add the independent ACL-oracle imports**

```python
from backend.security.private_files import (
    _windows_current_process_sid,
    _windows_private_acl_is_valid,
    apply_private_permissions,
)
```

- [ ] **Step 2: Write the real Windows failing regression**

Add near the existing real Windows owner-handle tests:

```python
@pytest.mark.skipif(os.name != "nt", reason="Windows private ACL lifecycle")
def test_default_private_option_acl_is_private_and_deletable(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir()
    failure: BaseException | None = None
    option: Path | None = None
    acl_valid = False
    residue_lengths: tuple[int, ...] = ()
    try:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 3306, "user": "u", "password": "secret"},
            private,
        ) as option:
            acl_valid = _windows_private_acl_is_valid(
                option, _windows_current_process_sid(), is_directory=False
            )
    except BaseException as error:
        failure = error
        residue_lengths = tuple(path.stat().st_size for path in private.iterdir())
    finally:
        for path in tuple(private.iterdir()):
            apply_private_permissions(path, is_directory=False)
            path.unlink()
    assert failure is None
    assert acl_valid
    assert residue_lengths == ()
    assert option is not None and not option.exists()
    assert list(private.iterdir()) == []
```

- [ ] **Step 3: Run RED and record the exact symptom**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py::test_default_private_option_acl_is_private_and_deletable -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-option-acl-red
```

Expected on current code: one assertion failure; `failure` is `ProductDatabaseBackupError("private mysql option file cleanup failed")`, `residue_lengths` is `(0,)`, and the test's independent remediation leaves no pytest residue.

- [ ] **Step 4: Run the deletion-algorithm control**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py::test_private_option_owner_handle_blocks_replacement_for_entire_use -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-option-owner-control
```

Expected: pass, proving the owner-handle deletion path works when the ACL does not remove `DELETE` access.

## Task 2: Route Phase 7B resources through verified private permissions

**Files:**
- Modify: `backend/services/product_database_backup.py`
- Modify: `backend/tests/unit/test_product_database_backup.py`

- [ ] **Step 1: Write adapter RED tests**

```python
@pytest.mark.parametrize(("kind", "expected"), (("file", False), ("directory", True)))
def test_phase7b_private_permissions_adapter_uses_exact_resource_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, expected: bool
):
    path = tmp_path / kind
    path.mkdir() if expected else path.write_bytes(b"")
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        backup,
        "apply_private_permissions",
        lambda selected, *, is_directory: calls.append((selected, is_directory)),
    )
    backup._restrict_phase7b_private_resource(path)
    assert calls == [(path, expected)]


def test_phase7b_private_permissions_adapter_rejects_unsupported_type(tmp_path: Path):
    with pytest.raises(OSError):
        backup._restrict_phase7b_private_resource(tmp_path / "missing")


def test_phase7b_private_permissions_adapter_remains_windows_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "file"
    path.write_bytes(b"")
    monkeypatch.setattr(backup.os, "name", "posix")
    with pytest.raises(OSError):
        backup._restrict_phase7b_private_resource(path)
```

- [ ] **Step 2: Run the adapter tests and verify RED**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py::test_phase7b_private_permissions_adapter_uses_exact_resource_type backend/tests/unit/test_product_database_backup.py::test_phase7b_private_permissions_adapter_rejects_unsupported_type backend/tests/unit/test_product_database_backup.py::test_phase7b_private_permissions_adapter_remains_windows_only -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-option-adapter-red
```

Expected: fail because `_restrict_phase7b_private_resource` and the imported permissions dependency do not exist in the backup module.

- [ ] **Step 3: Implement the minimal adapter**

Replace the configuration ACL import with:

```python
from backend.security.private_files import apply_private_permissions
```

Add before `private_mysql_option_file`:

```python
def _restrict_phase7b_private_resource(path: Path) -> None:
    if os.name != "nt":
        raise OSError
    metadata = path.lstat()
    if _is_reparse(path):
        raise OSError
    if stat.S_ISDIR(metadata.st_mode):
        is_directory = True
    elif stat.S_ISREG(metadata.st_mode):
        is_directory = False
    else:
        raise OSError
    apply_private_permissions(path, is_directory=is_directory)
```

Change only the default `acl_runner` of `private_mysql_option_file` and `preflight_backup_directory` to `_restrict_phase7b_private_resource`. Do not change cleanup functions or Windows access masks.

- [ ] **Step 4: Run GREEN for the new and controlling tests**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py::test_default_private_option_acl_is_private_and_deletable backend/tests/unit/test_product_database_backup.py::test_phase7b_private_permissions_adapter_uses_exact_resource_type backend/tests/unit/test_product_database_backup.py::test_phase7b_private_permissions_adapter_rejects_unsupported_type backend/tests/unit/test_product_database_backup.py::test_phase7b_private_permissions_adapter_remains_windows_only backend/tests/unit/test_product_database_backup.py::test_private_option_owner_handle_blocks_replacement_for_entire_use -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-option-acl-green
```

Expected: `5 passed`, no warnings, no selected-basetemp residue.

- [ ] **Step 5: Run the complete backup unit file**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-option-backup-full
```

Expected: all tests pass; this Windows host runs the new regression rather than skipping it.

- [ ] **Step 6: Compile, inspect, and commit**

```powershell
python -m py_compile backend/services/product_database_backup.py backend/tests/unit/test_product_database_backup.py
git diff --check
git diff -- backend/services/product_database_backup.py backend/tests/unit/test_product_database_backup.py
git add backend/services/product_database_backup.py backend/tests/unit/test_product_database_backup.py
git diff --cached --name-only
git commit -m "fix: make phase7b option files deletable"
```

Expected: exactly the two repair files are committed.

## Task 3: Verify Stage A and permissions compatibility

**Files:**
- Test only: existing Phase 7B files

- [ ] **Step 1: Run focused compatibility tests**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_configure_local_mysql.py backend/tests/unit/test_project_import_staging.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-option-focused
```

Expected: all pass without warnings. The local-config `(R,W)` command contract remains unchanged and shared full-control ACL verification passes.

- [ ] **Step 2: Run the Phase 7B lifecycle gate**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_cutover_product_database_command.py backend/tests/unit/test_product_database_lifecycle_lock.py backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_config.py backend/tests/unit/test_database_transaction.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-option-lifecycle
```

Expected: zero failures and warnings; only the documented Windows-host POSIX symlink case may skip.

- [ ] **Step 3: Verify exact inputs before external diagnosis**

```powershell
git status --short --untracked-files=no
git branch --show-current
Get-FileHash -Algorithm SHA256 D:\Projects\Novel_Creater\.env.local.json
Get-FileHash -Algorithm SHA256 D:\NovelCreatorBackups\phase7b-stagea-20260821\novel_creator-phase7b-be7922d5795706ede9c03cf6b42e8b86.sql
```

Require tracked/index clean, branch `codex/phase7b-implementation`, config hash `0e3ddb3683e9c878bc1b2d7244c643dc013716a194df9555e837b8000a35f032`, and dump hash `a02a15d5f11abd8bc563b86b7f9cd8c5cf82c9abea49f40dd563c7ae462a2130`. Abort on drift.

## Task 4: Run one published-backup restore diagnosis

**Files:**
- Temporarily create: `tmp/run_phase7b_published_backup_restore_diagnostic.py`
- Preserve: SQL backup and existing zero-byte option residue

- [ ] **Step 1: Create the one-shot secret-free helper**

The helper must insert the worktree root into `sys.path` before backend imports; validate source-config and dump hashes; require product database identities to be exactly `(novel_creator,)`; require zero pre-existing restore-prefix databases; and print only fixed safe fields. Implement one explicit create/restore/inventory/drop lifecycle so its created/cleaned ledger remains observable even on failure. Use the existing closed SQL-name builders and restore service; do not duplicate SQL quoting.

The helper's exact constants and lifecycle are:

```python
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = Path(r"D:\Projects\Novel_Creater\.env.local.json")
BACKUP_DIRECTORY = Path(r"D:\NovelCreatorBackups\phase7b-stagea-20260821")
BACKUP = BACKUP_DIRECTORY / "novel_creator-phase7b-be7922d5795706ede9c03cf6b42e8b86.sql"
MYSQLDUMP = Path(r"D:\Software\MySQL Server 8.4\bin\mysqldump.exe")
MYSQL = Path(r"D:\Software\MySQL Server 8.4\bin\mysql.exe")
EXPECTED_CONFIG_SHA256 = "0e3ddb3683e9c878bc1b2d7244c643dc013716a194df9555e837b8000a35f032"
EXPECTED_BACKUP_SHA256 = "a02a15d5f11abd8bc563b86b7f9cd8c5cf82c9abea49f40dd563c7ae462a2130"
EXPECTED_BACKUP_LENGTH = 44_520_136


async def _database_names(config: dict[str, object]) -> tuple[str, ...]:
    connection = await aiomysql.connect(
        host=str(config["host"]), port=int(config["port"]),
        user=str(config["user"]), password=str(config["password"]),
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                "WHERE SCHEMA_NAME IN (%s,%s) OR SCHEMA_NAME LIKE %s ESCAPE '=' "
                "ORDER BY SCHEMA_NAME",
                ("novel_creator", "novel_creator_v113", "novel=creator=phase7b=restore=%"),
            )
            return tuple(str(row[0]) for row in await cursor.fetchall())
    finally:
        connection.close()


async def _diagnose() -> int:
    raw = SOURCE_CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_CONFIG_SHA256:
        raise RuntimeError
    document = json.loads(raw.decode("utf-8"))
    if type(document) is not dict or set(document) != {
        "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DB"
    } or document["MYSQL_DB"] != "novel_creator":
        raise RuntimeError
    if BACKUP.stat().st_size != EXPECTED_BACKUP_LENGTH:
        raise RuntimeError
    if hashlib.sha256(BACKUP.read_bytes()).hexdigest() != EXPECTED_BACKUP_SHA256:
        raise RuntimeError
    config = {
        "host": document["MYSQL_HOST"], "port": int(document["MYSQL_PORT"]),
        "user": document["MYSQL_USER"], "password": document["MYSQL_PASSWORD"],
        "db": document["MYSQL_DB"],
    }
    if await _database_names(config) != ("novel_creator",):
        raise RuntimeError
    pair = preflight_client_pair(
        MYSQLDUMP, MYSQL, REPOSITORY_ROOT,
        lambda path: subprocess.run(
            [str(path), "--version"], check=False, capture_output=True, text=True
        ),
    )
    restore_database = validate_restore_database(
        f"novel_creator_phase7b_restore_{secrets.token_hex(16)}"
    )
    authority = await prepare._default_inventory(config, LEGACY_DATABASE)
    created = cleaned = 0
    inventory_equal = False
    session = None
    failed = False
    try:
        session = await prepare._open_default_session(config)
        await session.execute(prepare._create_database_sql(restore_database))
        created = 1
        with private_mysql_option_file(
            config, BACKUP_DIRECTORY, repository_root=REPOSITORY_ROOT
        ) as option:
            preflight_client_connection(pair, option, subprocess.run)
            restore_logical_backup(
                pair, option, BACKUP, EXPECTED_BACKUP_SHA256,
                EXPECTED_BACKUP_LENGTH, restore_database,
            )
        observed = await inventory_database(session, restore_database)
        assert_inventory_equal(authority, observed)
        inventory_equal = True
    except BaseException:
        failed = True
    finally:
        if created and session is not None:
            try:
                await session.execute(prepare._drop_database_sql(restore_database))
                cleaned = 1
            except BaseException:
                failed = True
        if session is not None:
            try:
                await session.close()
            except BaseException:
                failed = True
    after_names = await _database_names(config)
    remaining = sum(name.startswith("novel_creator_phase7b_restore_") for name in after_names)
    source_after = await prepare._default_inventory(config, LEGACY_DATABASE)
    assert_inventory_equal(authority, source_after)
    if tuple(name for name in after_names if not name.startswith("novel_creator_phase7b_restore_")) != ("novel_creator",):
        failed = True
    if remaining:
        failed = True
    print(f"diagnostic={'failed' if failed else 'passed'}")
    print("stage=restore-drill")
    print(f"client_version={pair.version}")
    print(f"inventory_equal={inventory_equal}")
    print(f"created_count={created}")
    print(f"cleaned_count={cleaned}")
    print(f"remaining_restore_count={remaining}")
    return int(failed)
```

Wrap `asyncio.run(_diagnose())` in a top-level `try/except BaseException` that prints only `diagnostic=failed` and `stage=preflight` before returning `1`; never print or re-raise the raw exception.

An outer `finally` must independently query only `information_schema.SCHEMATA` for the exact restore prefix and print:

```text
diagnostic=passed|failed
stage=restore-drill
client_version=8.4.10
inventory_equal=True|False
created_count=0|1
cleaned_count=0|1
remaining_restore_count=0
```

If any restore database remains, exit nonzero and stop without broad cleanup or retry.

- [ ] **Step 2: Compile and inspect the helper**

```powershell
python -m py_compile tmp/run_phase7b_published_backup_restore_diagnostic.py
Select-String -Path tmp/run_phase7b_published_backup_restore_diagnostic.py -Pattern 'MYSQL_PASSWORD\s*=|password\s*=\s*["'']|DROP DATABASE.*novel_creator`?$'
```

Expected: compile succeeds, secret/broad-drop scan has no matches, and source inspection shows exactly one `restore_logical_backup` call.

- [ ] **Step 3: Execute exactly once**

```powershell
python tmp\run_phase7b_published_backup_restore_diagnostic.py
```

Do not retry. On nonzero exit, preserve the backup, perform only the next read-only audit, remove helper source, and stop.

- [ ] **Step 4: Audit independently**

Using the unchanged source configuration in memory, query only `information_schema.SCHEMATA` for `novel_creator`, `novel_creator_v113`, and `novel_creator_phase7b_restore_%`. Require old present, new absent, restore count zero. Re-hash source config and SQL backup; do not read SQL contents or business rows.

- [ ] **Step 5: Remove only helper source**

Delete `tmp/run_phase7b_published_backup_restore_diagnostic.py` with `apply_patch`. Preserve the SQL backup and pre-existing zero-byte option residue. Record any policy-blocked ignored `.pyc` rather than bypassing policy.

## Task 5: Final verification and safe stop

**Files:**
- Modify only for a concrete defect in the approved two-file repair scope.

- [ ] **Step 1: Run fresh final verification**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_project_import_staging.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-option-final
python -m py_compile backend/services/product_database_backup.py backend/tests/unit/test_product_database_backup.py
git diff --check
git status --short --untracked-files=no
```

Expected: zero failures/warnings; compile and diff checks exit `0`; tracked/index state is clean after the repair commit.

- [ ] **Step 2: Inspect scope**

```powershell
git show --stat --oneline HEAD
git diff 41023d3..HEAD -- backend/services/product_database_backup.py backend/tests/unit/test_product_database_backup.py docs/superpowers/specs/2026-08-21-phase7b-windows-private-option-cleanup-design.md docs/superpowers/plans/2026-08-21-phase7b-windows-private-option-cleanup.md
```

Require no changes to product names, delete allowlists, Stage A confirmations, Stage B, Provider code, schema, or local-config ACL behavior.

- [ ] **Step 3: Present the safe stop receipt**

Report the repair commit, RED/GREEN evidence, complete test counts, diagnostic outcome, created/cleaned/remaining restore counts, source-config and backup hashes, Git state, and retained residues. State explicitly that real Stage A was not retried and still requires a new exact approval.
