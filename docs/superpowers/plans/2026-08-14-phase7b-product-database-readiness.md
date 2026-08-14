# Phase 7B Product Database Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a fail-closed two-stage administrative workflow that preserves the current `novel_creator` database, proves a private logical backup can be restored, prepares an exact v1.13 `novel_creator_v113` database with only approved static data, and changes local configuration only after a second explicit human approval.

**Architecture:** Keep safe immutable contracts separate from database inspection, external MySQL-client I/O, Stage A orchestration, and Stage B configuration cutover. All implementation work is first proved against disposable databases; real backup/new-database work and the later `.env.local.json` switch are separate stop-and-approve gates. Existing production schema initialization, Writer asset seed, market-source seed, strict config loading, ACL writer, disposable-MySQL support, and browser runtime observer are reused rather than reimplemented.

**Tech Stack:** Python 3.13, `asyncio`, `aiomysql`, immutable dataclasses, MySQL 8.4 `mysqldump`/`mysql`, pytest, Node.js, Playwright, Vite, PowerShell, Git.

---

## Fixed safety boundary

- This plan does **not** authorize a real database write, installation, configuration switch, Provider call, market refresh, or legacy-database deletion.
- Product roles are closed to `novel_creator` (retained source) and `novel_creator_v113` (new target).
- Restore drills use only `novel_creator_phase7b_restore_<32 lowercase hex>`.
- Unit and integration tests use only the existing `novel_creator_test_<32 lowercase hex>` disposable namespace.
- `novel_creator` is never accepted by a cleanup or drop guard.
- Phase 7B never deletes individual legacy tables. The whole old database can be retired only in a later separately approved task after Phase 7C.
- Real Stage A stops at `awaiting_cutover_approval`. Stage B cannot be invoked by Stage A and requires a new user approval.
- `mysqldump.exe` and `mysql.exe` must be explicitly supplied as absolute paths and must report a compatible MySQL 8.4 client. The implementation must not search `PATH` or select the installed 5.7/8.0 clients.
- Passwords, DSNs, option-file contents, dump contents, SQL row values, business IDs, text, Provider fields, and absolute private paths never appear in receipts or logs.

## File map

### Create

- `backend/domain/product_database_readiness.py` — closed names, safe immutable inventory/backup/preparation/cutover receipts, canonical receipt hashing, fixed error categories.
- `backend/services/product_database_inventory.py` — read-only information-schema inventory and deterministic structural fingerprint.
- `backend/services/product_database_backup.py` — explicit MySQL 8.4 client preflight, private option-file ownership, atomic dump publication, restore invocation, bounded cleanup.
- `backend/services/product_database_readiness.py` — Stage A state machine and dependency-injected orchestration using the existing initializer and seed services.
- `backend/scripts/prepare_product_database.py` — Stage A CLI; prints an exact preview unless `--execute` is explicitly supplied.
- `backend/scripts/cutover_product_database.py` — Stage B CLI; verifies preparation receipt, atomically changes only `MYSQL_DB`, runs injected smoke, and rolls back on failure.
- `backend/tests/unit/test_product_database_readiness_domain.py` — names, state sequence, receipt hashes, replay rejection, safe serialization.
- `backend/tests/unit/test_product_database_inventory.py` — query/normalization/fingerprint contracts and no-business-data boundary.
- `backend/tests/unit/test_product_database_backup.py` — executable/version guards, option-file secrecy, command vectors, dump publication, cleanup/error precedence.
- `backend/tests/unit/test_product_database_readiness.py` — Stage A sequencing, seed/audit boundary, ownership cleanup, resume rules.
- `backend/tests/unit/test_prepare_product_database_command.py` — preview/execute confirmation, no-write defaults, secret-free output.
- `backend/tests/unit/test_cutover_product_database_command.py` — exact-field config switch, receipt binding, rollback and error precedence.
- `backend/tests/integration/test_product_database_readiness_mysql.py` — disposable dump/restore, bootstrap, seed replay, empty-business audit, failure ledger.
- `frontend/e2e/phase7b-product-database-readiness.spec.mjs` — public read-only empty-library/static-catalog/empty-Provider smoke.
- `frontend/e2e/playwright.phase7b.config.mjs` — single-worker owned-origin configuration.
- `frontend/e2e/run-phase7b.mjs` — one formal process/database/port/root lifecycle with process-local `MYSQL_DB` override.
- `scripts/tests/phase7bBrowserContract.test.mjs` — runner/config/spec inventory, no Provider/outbound, cleanup and safe-summary contract.
- `docs/superpowers/acceptance/2026-08-14-phase7b-product-database-readiness.md` — final evidence written only after Stage B succeeds.

### Modify

- `backend/scripts/configure_local_mysql.py` — expose an atomic writer that preserves the five required MySQL keys plus existing optional corpus-root keys; keep the current five-key setup API unchanged.
- `backend/tests/unit/test_configure_local_mysql.py` — prove optional-key preservation and reject every unknown key.
- `scripts/run-tests.mjs` — register exactly one `browser-phase7b` formal target and its exact spec inventory.
- `package.json` — add root `test:browser:phase7b`.
- `frontend/package.json` — add frontend `test:e2e:phase7b` and `test:browser:phase7b`.

### Reuse without modification

- `backend/scripts/initialize_database.py`
- `backend/scripts/seed_writer_assets.py`
- `backend/scripts/seed_market_sources.py`
- `backend/scripts/configure_local_mysql.py`
- `backend/schema_manifest.py`
- `backend/schema_version.py`
- `backend/tests/support/disposable_mysql.py`
- `frontend/e2e/runtime-observer.mjs`

## Task 1: Safe domain contracts and receipt chain

**Files:**
- Create: `backend/domain/product_database_readiness.py`
- Create: `backend/tests/unit/test_product_database_readiness_domain.py`

- [ ] **Step 1: Write the failing closed-name and receipt tests**

```python
from dataclasses import replace

import pytest

from backend.domain.product_database_readiness import (
    LEGACY_DATABASE,
    NEW_DATABASE,
    DatabaseInventory,
    ProductDatabaseReadinessError,
    ReadinessState,
    inventory_hash,
    validate_database_role,
    validate_restore_database,
)


def inventory(database: str) -> DatabaseInventory:
    return DatabaseInventory(
        database=database,
        server_version="8.4.10",
        schema_version="writer-core-v1.13.0",
        manifest_hash="a" * 64,
        structural_fingerprint="b" * 64,
        table_names=("schema_metadata",),
        row_counts=(("schema_metadata", 1),),
        nonempty_table_count=1,
        total_row_count=1,
    )


def test_database_roles_and_restore_names_are_closed():
    assert validate_database_role("legacy", LEGACY_DATABASE) == LEGACY_DATABASE
    assert validate_database_role("new", NEW_DATABASE) == NEW_DATABASE
    assert validate_restore_database(
        "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"
    ).startswith("novel_creator_phase7b_restore_")
    for unsafe in (LEGACY_DATABASE, NEW_DATABASE, "novel_creator_phase7b_restore_bad", "x"):
        with pytest.raises(ProductDatabaseReadinessError, match="database target is invalid"):
            validate_restore_database(unsafe)


def test_inventory_hash_is_canonical_and_database_bound():
    source = inventory(LEGACY_DATABASE)
    assert inventory_hash(source) == inventory_hash(source)
    assert inventory_hash(source) != inventory_hash(replace(source, database=NEW_DATABASE))


def test_state_order_cannot_skip_cutover_approval():
    assert tuple(ReadinessState) == (
        ReadinessState.INVENTORY_VERIFIED,
        ReadinessState.BACKUP_CREATED,
        ReadinessState.RESTORE_DRILL_VERIFIED,
        ReadinessState.NEW_DATABASE_INITIALIZED,
        ReadinessState.OFFICIAL_DATA_SEEDED,
        ReadinessState.READINESS_VERIFIED,
        ReadinessState.AWAITING_CUTOVER_APPROVAL,
        ReadinessState.CONFIGURATION_SWITCHED,
        ReadinessState.CUTOVER_VERIFIED,
        ReadinessState.LEGACY_RETAINED,
    )
```

- [ ] **Step 2: Run the tests and confirm the module is missing**

Run:

```powershell
python -m pytest backend/tests/unit/test_product_database_readiness_domain.py -q --basetemp=.pytest-phase7b-domain-red
```

Expected: collection fails with `ModuleNotFoundError: backend.domain.product_database_readiness`.

- [ ] **Step 3: Implement the immutable domain contract**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
import re
from typing import Mapping

from backend.domain.json_contracts import canonical_hash

LEGACY_DATABASE = "novel_creator"
NEW_DATABASE = "novel_creator_v113"
RESTORE_DATABASE_PATTERN = re.compile(
    r"^novel_creator_phase7b_restore_[0-9a-f]{32}$"
)


class ProductDatabaseReadinessError(RuntimeError):
    pass


class ReadinessState(StrEnum):
    INVENTORY_VERIFIED = "inventory_verified"
    BACKUP_CREATED = "backup_created"
    RESTORE_DRILL_VERIFIED = "restore_drill_verified"
    NEW_DATABASE_INITIALIZED = "new_database_initialized"
    OFFICIAL_DATA_SEEDED = "official_data_seeded"
    READINESS_VERIFIED = "readiness_verified"
    AWAITING_CUTOVER_APPROVAL = "awaiting_cutover_approval"
    CONFIGURATION_SWITCHED = "configuration_switched"
    CUTOVER_VERIFIED = "cutover_verified"
    LEGACY_RETAINED = "legacy_retained"


@dataclass(frozen=True)
class DatabaseInventory:
    database: str
    server_version: str
    schema_version: str | None
    manifest_hash: str | None
    structural_fingerprint: str
    table_names: tuple[str, ...]
    row_counts: tuple[tuple[str, int], ...]
    nonempty_table_count: int
    total_row_count: int


@dataclass(frozen=True)
class BackupReceipt:
    state: str
    previous_receipt_hash: str
    source_database: str
    backup_filename: str
    backup_sha256: str
    backup_byte_length: int
    client_version: str
    source_inventory_hash: str


@dataclass(frozen=True)
class PreparationReceipt:
    state: str
    previous_receipt_hash: str
    legacy_database: str
    new_database: str
    legacy_inventory_hash: str
    new_inventory_hash: str
    backup_sha256: str
    style_count: int
    experience_card_count: int
    market_source_count: int
    receipts: tuple[StateReceipt, ...]


@dataclass(frozen=True)
class StateReceipt:
    state: str
    previous_receipt_hash: str
    legacy_database: str
    new_database: str
    evidence_hash: str


def validate_database_role(role: str, value: str) -> str:
    expected = {"legacy": LEGACY_DATABASE, "new": NEW_DATABASE}.get(role)
    if expected is None or value != expected:
        raise ProductDatabaseReadinessError("database target is invalid")
    return value


def validate_restore_database(value: str) -> str:
    if type(value) is not str or RESTORE_DATABASE_PATTERN.fullmatch(value) is None:
        raise ProductDatabaseReadinessError("database target is invalid")
    return value


def canonical_receipt_hash(value: Mapping[str, object] | object) -> str:
    payload = asdict(value) if hasattr(value, "__dataclass_fields__") else dict(value)
    json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return canonical_hash(payload)


def inventory_hash(value: DatabaseInventory) -> str:
    return canonical_receipt_hash(value)


def advance_receipt(previous: StateReceipt | None, state: ReadinessState,
                    evidence_hash: str) -> StateReceipt:
    states = tuple(ReadinessState)
    expected_index = 0 if previous is None else states.index(
        ReadinessState(previous.state)
    ) + 1
    if expected_index >= len(states) or states[expected_index] is not state:
        raise ProductDatabaseReadinessError("readiness state sequence is invalid")
    return StateReceipt(
        state=state.value,
        previous_receipt_hash="0" * 64 if previous is None else canonical_receipt_hash(previous),
        legacy_database=LEGACY_DATABASE,
        new_database=NEW_DATABASE,
        evidence_hash=evidence_hash,
    )
```

- [ ] **Step 4: Add tests that reject unknown/extra receipt fields, bad hashes, negative counts, skipped/reordered states, cross-database replay, and secret-bearing keys**

The serializer must accept only dataclass fields, require lowercase 64-character SHA-256 values, require sorted unique table/count tuples, require non-negative exact `int` counts, and reject any mapping key matching `password|secret|dsn|body|sql|provider` case-insensitively.

- [ ] **Step 5: Run, compile, and commit**

```powershell
python -m pytest backend/tests/unit/test_product_database_readiness_domain.py -q --basetemp=.pytest-phase7b-domain-green
python -m py_compile backend/domain/product_database_readiness.py backend/tests/unit/test_product_database_readiness_domain.py
git diff --check
git add backend/domain/product_database_readiness.py backend/tests/unit/test_product_database_readiness_domain.py
git commit -m "feat: add product database readiness contracts"
```

Expected: all tests pass; compile and diff checks exit `0`; commit contains exactly two files.

## Task 2: Read-only database inventory and structural fingerprint

**Files:**
- Create: `backend/services/product_database_inventory.py`
- Create: `backend/tests/unit/test_product_database_inventory.py`

- [ ] **Step 1: Write failing inventory tests with a recording session**

```python
import pytest

from backend.services.product_database_inventory import inventory_database


@pytest.mark.asyncio
async def test_inventory_uses_only_information_schema_counts_and_metadata():
    session = RecordingSession.fixture()
    result = await inventory_database(session, "novel_creator")
    assert result.database == "novel_creator"
    assert result.table_names == tuple(sorted(result.table_names))
    assert result.row_counts == tuple(sorted(result.row_counts))
    assert all(
        token not in " ".join(session.sql).lower()
        for token in ("provider_profiles.api", "payload_json", "content_json", "raw_")
    )


@pytest.mark.asyncio
async def test_structural_fingerprint_changes_for_column_index_fk_or_check():
    baseline = await inventory_database(RecordingSession.fixture(), "novel_creator")
    for mutation in ("column", "index", "foreign_key", "check"):
        changed = await inventory_database(
            RecordingSession.fixture(mutation=mutation), "novel_creator"
        )
        assert changed.structural_fingerprint != baseline.structural_fingerprint
```

The test helper returns fixed safe rows for `SCHEMATA`, `TABLES`, `COLUMNS`, `STATISTICS`, `KEY_COLUMN_USAGE`, `REFERENTIAL_CONSTRAINTS`, `TABLE_CONSTRAINTS`, `CHECK_CONSTRAINTS`, `schema_metadata`, and exact `COUNT(*)` results. It raises if SQL selects a business column or contains `SELECT *`.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_product_database_inventory.py -q --basetemp=.pytest-phase7b-inventory-red
```

Expected: module import fails.

- [ ] **Step 3: Implement the fixed query set and fingerprint**

```python
from __future__ import annotations

from typing import Iterable, Mapping

from backend.domain.json_contracts import canonical_hash
from backend.domain.product_database_readiness import DatabaseInventory, ProductDatabaseReadinessError


def _normalized_rows(rows: Iterable[Mapping[str, object]]) -> tuple[tuple[tuple[str, object], ...], ...]:
    normalized = []
    for row in rows:
        normalized.append(tuple(sorted((str(key), value) for key, value in row.items())))
    return tuple(sorted(normalized))


async def inventory_database(session, database: str) -> DatabaseInventory:
    schema = await session.fetchone(
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
        (database,),
    )
    if schema is None:
        raise ProductDatabaseReadinessError("database inventory target is absent")
    tables = await session.fetchall(
        "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME",
        (database,),
    )
    table_names = tuple(str(row["TABLE_NAME"]) for row in tables)
    row_counts = []
    for table in table_names:
        if not table.replace("_", "").isalnum():
            raise ProductDatabaseReadinessError("database inventory table name is invalid")
        row = await session.fetchone(f"SELECT COUNT(*) AS count FROM `{database}`.`{table}`")
        count = (row or {}).get("count")
        if type(count) is not int or count < 0:
            raise ProductDatabaseReadinessError("database row count is invalid")
        row_counts.append((table, count))
    metadata = await session.fetchone(
        f"SELECT schema_version, manifest_hash FROM `{database}`.schema_metadata "
        "WHERE singleton_id=1"
    ) if "schema_metadata" in table_names else None
    structural = {}
    for label, sql in STRUCTURAL_QUERIES:
        structural[label] = _normalized_rows(await session.fetchall(sql, (database,)))
    fingerprint = canonical_hash({"structure": structural})
    counts = tuple(row_counts)
    return DatabaseInventory(
        database=database,
        server_version=str((await session.fetchone("SELECT VERSION() AS version"))["version"]),
        schema_version=(metadata or {}).get("schema_version"),
        manifest_hash=(metadata or {}).get("manifest_hash"),
        structural_fingerprint=fingerprint,
        table_names=table_names,
        row_counts=counts,
        nonempty_table_count=sum(count > 0 for _, count in counts),
        total_row_count=sum(count for _, count in counts),
    )
```

Define `STRUCTURAL_QUERIES` as an immutable tuple of the seven explicit information-schema selects named above. Every select lists columns explicitly, omits the already-filtered schema-name columns so a restore under a different owned database name compares equal, and orders by all identity/ordinal columns.

- [ ] **Step 4: Add exact comparison helpers**

Implement and test:

```python
def assert_inventory_equal(authority: DatabaseInventory, observed: DatabaseInventory) -> None:
    if (
        authority.table_names != observed.table_names
        or authority.schema_version != observed.schema_version
        or authority.manifest_hash != observed.manifest_hash
        or authority.structural_fingerprint != observed.structural_fingerprint
        or authority.row_counts != observed.row_counts
    ):
        raise ProductDatabaseReadinessError("database inventory comparison failed")
```

Tests mutate each field independently and assert the same fixed exception text with `__cause__ is None`.

- [ ] **Step 5: Run and commit**

```powershell
python -m pytest backend/tests/unit/test_product_database_inventory.py backend/tests/unit/test_product_database_readiness_domain.py -q --basetemp=.pytest-phase7b-inventory-green
python -m py_compile backend/services/product_database_inventory.py backend/tests/unit/test_product_database_inventory.py
git diff --check
git add backend/services/product_database_inventory.py backend/tests/unit/test_product_database_inventory.py
git commit -m "feat: inventory product databases safely"
```

## Task 3: Explicit MySQL 8.4 client and private backup boundary

**Files:**
- Create: `backend/services/product_database_backup.py`
- Create: `backend/tests/unit/test_product_database_backup.py`

- [ ] **Step 1: Write RED tests for explicit binaries and command secrecy**

```python
def test_client_pair_requires_external_absolute_mysql84_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    dump = tmp_path / "mysql84" / "mysqldump.exe"
    restore = tmp_path / "mysql84" / "mysql.exe"
    dump.parent.mkdir(); dump.write_bytes(b"x"); restore.write_bytes(b"x")
    pair = preflight_client_pair(dump, restore, repo, fake_version_runner("8.4.10"))
    assert pair.version == "8.4.10"
    for invalid in (Path("mysqldump.exe"), repo / "mysqldump.exe"):
        with pytest.raises(ProductDatabaseBackupError, match="client path is invalid"):
            preflight_client_pair(invalid, restore, repo, fake_version_runner("8.4.10"))


def test_dump_command_has_option_file_but_no_password_or_database_creation(tmp_path):
    command = dump_command(CLIENT_PAIR, tmp_path / "client.cnf", "novel_creator")
    joined = " ".join(map(str, command))
    assert "--defaults-extra-file=" in joined
    assert "password" not in joined.lower()
    assert "--databases" not in command
    assert "--single-transaction" in command
    assert "--quick" in command
    assert "--hex-blob" in command
    assert "--routines" in command and "--events" in command and "--triggers" in command
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py -q --basetemp=.pytest-phase7b-backup-red
```

Expected: module import fails.

- [ ] **Step 3: Implement path/version validation and exact command vectors**

```python
@dataclass(frozen=True)
class MySQLClientPair:
    mysqldump: Path
    mysql: Path
    version: str


def preflight_client_pair(dump_path, mysql_path, repository_root, version_runner):
    resolved_repo = Path(repository_root).resolve(strict=True)
    resolved = []
    versions = []
    for executable in (dump_path, mysql_path):
        candidate = Path(executable)
        if not candidate.is_absolute() or not candidate.is_file():
            raise ProductDatabaseBackupError("client path is invalid")
        candidate = candidate.resolve(strict=True)
        if candidate == resolved_repo or resolved_repo in candidate.parents:
            raise ProductDatabaseBackupError("client path is invalid")
        match = re.search(r"\b8\.4\.\d+\b", version_runner(candidate))
        if match is None:
            raise ProductDatabaseBackupError("MySQL 8.4 client is required")
        resolved.append(candidate); versions.append(match.group(0))
    if versions[0] != versions[1]:
        raise ProductDatabaseBackupError("MySQL client versions do not match")
    return MySQLClientPair(resolved[0], resolved[1], versions[0])


def dump_command(pair, option_file, database):
    return [
        str(pair.mysqldump), f"--defaults-extra-file={option_file}",
        "--protocol=TCP", "--single-transaction", "--quick", "--hex-blob",
        "--routines", "--events", "--triggers", "--set-gtid-purged=OFF",
        "--skip-add-locks", "--skip-lock-tables", database,
    ]


def restore_command(pair, option_file, database):
    return [
        str(pair.mysql), f"--defaults-extra-file={option_file}",
        "--protocol=TCP", "--binary-mode", database,
    ]
```

Add `preflight_client_connection(pair, option_file, runner)` using the selected `mysql.exe` with `--batch`, `--skip-column-names`, and `--execute=SELECT VERSION()`. Require exit `0` and an exact 8.4-compatible version; discard stderr and never include stdout/stderr in an exception. Unit tests prove that a version-capable but non-connecting client fails before the dump file is created.

- [ ] **Step 4: Implement private option-file and backup publication ownership**

Create `private_mysql_option_file(config, temp_root, acl)` as a context manager. It must create the file first, apply `restrict_windows_acl` before writing, write `[client]`, host/port/user/password/`default-character-set=utf8mb4`, flush and `os.fsync`, yield only its `Path`, then make two bounded unlink attempts. The file path and content must never enter raised messages.

Create `create_logical_backup(...)` that:

1. validates an existing absolute backup directory outside the repository and rejects symlinks or Windows reparse points using `lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT`;
2. creates a private same-directory `.<final>.tmp` file;
3. applies ACL before opening it for dump output;
4. invokes the exact command with stdout directed to the file and stderr captured only for classification, never surfaced;
5. flushes/fsyncs, requires byte length greater than zero, calculates SHA-256 by 64 KiB chunks;
6. publishes with same-directory `os.link(temporary, final)` so an existing final filename is never overwritten, then removes the temporary hard-link name with bounded retry;
7. preserves the published backup on every later failure;
8. returns `BackupReceipt` containing the basename, digest, byte length, client version and source inventory hash.

Tests inject failures at ACL, spawn, nonzero exit, flush, fsync, hash read, publication, temporary unlink and option-file unlink. Assert first operation failure remains primary and cleanup failures are grouped without secrets.

- [ ] **Step 5: Implement restore streaming**

`restore_logical_backup(...)` must verify the backup digest/length before spawning `mysql`, open the dump as stdin, use the explicit restore database, reject `novel_creator`/`novel_creator_v113`, and return no row data. A nonzero exit raises fixed `ProductDatabaseBackupError("logical restore failed")` with no stderr cause/value exposure.

- [ ] **Step 6: Run and commit**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py -q --basetemp=.pytest-phase7b-backup-green
python -m py_compile backend/services/product_database_backup.py backend/tests/unit/test_product_database_backup.py
git diff --check
git add backend/services/product_database_backup.py backend/tests/unit/test_product_database_backup.py
git commit -m "feat: add private mysql backup boundary"
```

## Task 4: Stage A preparation state machine

**Files:**
- Create: `backend/services/product_database_readiness.py`
- Create: `backend/tests/unit/test_product_database_readiness.py`

- [ ] **Step 1: Write a failing happy-path sequencing test**

```python
@pytest.mark.asyncio
async def test_prepare_advances_exactly_to_cutover_gate():
    calls = []
    result = await prepare_product_database(
        request=REQUEST,
        inventory=lambda role: recorded(calls, f"inventory:{role}", inventories[role]),
        create_backup=lambda source: recorded(calls, "backup", BACKUP),
        restore_drill=lambda backup, authority: recorded(calls, "restore", None),
        initialize_new=lambda: recorded(calls, "initialize", INITIALIZED),
        seed_assets=lambda: recorded(calls, "seed-assets", ASSET_REPORT),
        seed_market=lambda: recorded(calls, "seed-market", MARKET_REPORT),
        smoke=lambda database: recorded(calls, "smoke", SMOKE),
    )
    assert calls == [
        "inventory:legacy-before", "backup", "restore", "inventory:legacy-after",
        "initialize", "seed-assets", "seed-market", "inventory:new", "smoke",
    ]
    assert result.state == "awaiting_cutover_approval"
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_product_database_readiness.py -q --basetemp=.pytest-phase7b-readiness-red
```

- [ ] **Step 3: Implement dependency-injected orchestration**

```python
@dataclass(frozen=True)
class PreparationRequest:
    legacy_database: str
    new_database: str
    backup_directory: Path


async def prepare_product_database(*, request, inventory, create_backup,
                                   restore_drill, initialize_new,
                                   seed_assets, seed_market, smoke):
    validate_database_role("legacy", request.legacy_database)
    validate_database_role("new", request.new_database)
    receipts = []
    before = await inventory("legacy-before")
    receipts.append(advance_receipt(None, ReadinessState.INVENTORY_VERIFIED, inventory_hash(before)))
    backup = await create_backup(before)
    receipts.append(advance_receipt(receipts[-1], ReadinessState.BACKUP_CREATED, canonical_receipt_hash(backup)))
    await restore_drill(backup, before)
    receipts.append(advance_receipt(receipts[-1], ReadinessState.RESTORE_DRILL_VERIFIED, inventory_hash(before)))
    after = await inventory("legacy-after")
    assert_inventory_equal(before, after)
    initialized = await initialize_new()
    receipts.append(advance_receipt(receipts[-1], ReadinessState.NEW_DATABASE_INITIALIZED, canonical_receipt_hash(initialized)))
    assets = await seed_assets()
    market = await seed_market()
    receipts.append(advance_receipt(receipts[-1], ReadinessState.OFFICIAL_DATA_SEEDED, canonical_hash({"assets": asdict(assets), "market": asdict(market)})))
    target = await inventory("new")
    assert_new_database_ready(target, initialized, assets, market)
    smoke_result = await smoke(request.new_database)
    if smoke_result.provider_calls != 0 or smoke_result.outbound_requests != 0:
        raise ProductDatabaseReadinessError("readiness smoke crossed network boundary")
    receipts.append(advance_receipt(receipts[-1], ReadinessState.READINESS_VERIFIED, inventory_hash(target)))
    receipts.append(advance_receipt(receipts[-1], ReadinessState.AWAITING_CUTOVER_APPROVAL, canonical_hash({"providerCalls": 0, "outboundRequests": 0})))
    return build_preparation_receipt(before, backup, target, assets, market, tuple(receipts))
```

- [ ] **Step 4: Implement exact new-database audit**

`assert_new_database_ready` must require current `EXPECTED_SCHEMA_VERSION`, current `manifest_hash()`, `tuple(sorted(created_table_names()))`, all tables InnoDB/`utf8mb4_0900_ai_ci`, 10 styles, 64 cards, two market sources, and zeros for projects, Provider profiles/revisions, corpus sources/revisions/chapters/fragments/blobs, drafts/candidates/final chapters, package/import commands/provenance. The static audit derives package versions/hashes from `load_asset_package(MANIFEST_PATH, mode="release")` and `load_market_source_package(MANIFEST_PATH)`; it does not duplicate literal hashes.

- [ ] **Step 5: Add failure and resume matrices**

Tests cover each stage failing, before/after legacy drift, restore mismatch, target absent, target exact-ready resume, target nonempty/partial rejection, seed replay, Provider/outbound nonzero, cleanup of only current-run new/restore DB, retained backup, primary-vs-cleanup precedence, and unchanged legacy authority. No test accepts automatic cleanup of a pre-existing target.

- [ ] **Step 6: Run and commit**

```powershell
python -m pytest backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_product_database_inventory.py -q --basetemp=.pytest-phase7b-readiness-green
python -m py_compile backend/services/product_database_readiness.py backend/tests/unit/test_product_database_readiness.py
git diff --check
git add backend/services/product_database_readiness.py backend/tests/unit/test_product_database_readiness.py
git commit -m "feat: orchestrate product database preparation"
```

## Task 5: Stage A CLI with no-write default

**Files:**
- Create: `backend/scripts/prepare_product_database.py`
- Create: `backend/tests/unit/test_prepare_product_database_command.py`

- [ ] **Step 1: Write RED command tests**

```python
@pytest.mark.asyncio
async def test_default_mode_prints_preview_and_calls_no_mutation(tmp_path):
    writes = ForbiddenWrites()
    lines = []
    status = await run_cli([
        "--legacy-database", "novel_creator",
        "--new-database", "novel_creator_v113",
        "--backup-dir", str(tmp_path),
        "--mysqldump", str(MYSQLDUMP), "--mysql", str(MYSQL),
    ], dependencies=writes, output=lines.append)
    assert status == 0
    assert writes.calls == []
    assert lines == [
        "mode=preview", "legacy_database=novel_creator",
        "new_database=novel_creator_v113", "stage=approval-required",
    ]
```

- [ ] **Step 2: Verify RED, then implement the parser**

The parser requires all five explicit paths/names. `--execute` additionally requires:

```text
--confirm-legacy novel_creator
--confirm-new novel_creator_v113
--confirm-prepare PREPARE-PHASE7B
```

Preview performs argument/path syntax checks only and invokes no connector, subprocess, file writer, or database action. Execute runs client preflight, safe read inventory, then the Stage A service. `main()` prints only `Product database preparation failed.` on error.

- [ ] **Step 3: Add safe receipt publication**

Write the canonical preparation receipt beside the published backup as `<backup-basename>.readiness.json`, using a private same-directory temporary file, ACL-before-content, fsync, atomic absent-only publication, and exact receipt hash. Never write it into the repository.

- [ ] **Step 4: Run and commit**

```powershell
python -m pytest backend/tests/unit/test_prepare_product_database_command.py -q --basetemp=.pytest-phase7b-prepare-cli-green
python -m py_compile backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git diff --check
git add backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git commit -m "feat: add product database preparation command"
```

## Task 6: Stage B atomic cutover and rollback

**Files:**
- Create: `backend/scripts/cutover_product_database.py`
- Create: `backend/tests/unit/test_cutover_product_database_command.py`
- Modify: `backend/scripts/configure_local_mysql.py`
- Modify: `backend/tests/unit/test_configure_local_mysql.py`

- [ ] **Step 1: Write RED tests for exact-field switch and approval**

```python
@pytest.mark.asyncio
async def test_cutover_changes_only_mysql_db_and_finishes_legacy_retained(tmp_path):
    config = tmp_path / ".env.local.json"
    original = mysql_document(database="novel_creator")
    config.write_text(json.dumps(original), encoding="utf-8")
    result = await cutover(
        receipt=PREPARATION_RECEIPT,
        config_path=config,
        confirm_database="novel_creator_v113",
        confirm_cutover="CUTOVER-PHASE7B",
        smoke=successful_smoke,
        writer=atomic_write_local_config,
    )
    current = json.loads(config.read_text(encoding="utf-8"))
    assert current == {**original, "MYSQL_DB": "novel_creator_v113"}
    assert result.state == "legacy_retained"
```

- [ ] **Step 2: Implement receipt/config guards and rollback**

The CLI requires `--receipt`, `--database novel_creator_v113`, `--confirm-cutover CUTOVER-PHASE7B`, and `--execute`. It rejects preview-less invocation, any receipt not at `awaiting_cutover_approval`, mismatched inventory/backup hashes, current config not targeting `novel_creator`, unknown config keys, and either database missing. Reuse `atomic_write_local_config` and `restrict_windows_acl`; preserve all allowed config fields, including optional corpus roots, while changing only `MYSQL_DB`.

Add `atomic_write_local_document` to `configure_local_mysql.py`. It accepts exactly the five required MySQL keys plus any already-present `CORPUS_ROOT` and `MANAGED_CORPUS_ROOT`, rejects all other keys, and uses the existing ACL-before-content/fsync/atomic-replace implementation. Keep `atomic_write_local_config` as a compatibility wrapper that still requires exactly five keys. On smoke failure, atomically write the exact original parsed document back. If rollback also fails, raise an `ExceptionGroup` with smoke first. Flow-control exceptions propagate after bounded rollback attempt.

- [ ] **Step 3: Add recovery mode tests**

`--recover-legacy --database novel_creator --confirm-cutover RECOVER-PHASE7B --execute` is the only recovery action. It changes only `MYSQL_DB` after proving both databases exist. It never drops either database.

- [ ] **Step 4: Run and commit**

```powershell
python -m pytest backend/tests/unit/test_cutover_product_database_command.py backend/tests/unit/test_configure_local_mysql.py -q --basetemp=.pytest-phase7b-cutover-green
python -m py_compile backend/scripts/cutover_product_database.py backend/scripts/configure_local_mysql.py backend/tests/unit/test_cutover_product_database_command.py
git diff --check
git add backend/scripts/cutover_product_database.py backend/tests/unit/test_cutover_product_database_command.py backend/scripts/configure_local_mysql.py backend/tests/unit/test_configure_local_mysql.py
git commit -m "feat: add guarded product database cutover"
```

## Task 7: Disposable MySQL dump/restore/bootstrap/seed integration

**Prerequisite stop:** Before this task, obtain an explicitly selected MySQL 8.4-compatible `mysqldump.exe` and `mysql.exe`. Installing or downloading them is a system/network change and requires separate user authorization. If the paths are absent, report the blocker and do not use the discovered 5.7.25 or 8.0.14 binaries.

**Files:**
- Create: `backend/tests/integration/test_product_database_readiness_mysql.py`

- [ ] **Step 1: Add a capability fixture that fails closed**

Read `TEST_MYSQLDUMP_84` and `TEST_MYSQL_84`; require absolute regular files and call `preflight_client_pair`. Missing variables skip only local developer collection with the exact reason `Phase 7B MySQL 8.4 clients are not configured`; the formal runner treats that skip as a failure.

- [ ] **Step 2: Write the dump/restore proof test**

Use `disposable_mysql_database(initialize_schema=False)` to create a small legacy-shaped source with `schema_metadata`, one parent table, one child table, an index, FK and CHECK. Insert only synthetic values. Inventory, dump, create a Phase7B restore-name database, restore, inventory, and call `assert_inventory_equal`. In `finally`, revalidate and drop only the exact owned restore database. Assert database ledger `created=2, cleaned=2, remaining=0`.

- [ ] **Step 3: Write current bootstrap and official seed replay test**

Use a fresh disposable database initialized by `initialize_database`. Run `AssetSeedService.seed` and `MarketSourceSeedService.seed` twice through database-bound factories. Assert exact current schema/hash/91 tables, asset 10/64, market two, replay counts, and all business tables empty.

- [ ] **Step 4: Add failure-injection cases**

Cover restore nonzero, row-count mismatch, target partial, seed failure, audit failure, restore drop failure, and current-run new-database cleanup. Assert published backup remains and old/source disposable inventory is unchanged.

- [ ] **Step 5: Run and commit**

```powershell
python -m pytest backend/tests/integration/test_product_database_readiness_mysql.py -m mysql -q --basetemp=.pytest-phase7b-mysql-green
git diff --check
git add backend/tests/integration/test_product_database_readiness_mysql.py
git commit -m "test: prove product database readiness on mysql"
```

Expected: all tests pass, no skips in the formal environment, ledger has zero remaining databases.

## Task 8: Read-only Phase 7B browser smoke and runner contracts

**Files:**
- Create: `frontend/e2e/phase7b-product-database-readiness.spec.mjs`
- Create: `frontend/e2e/playwright.phase7b.config.mjs`
- Create: `frontend/e2e/run-phase7b.mjs`
- Create: `scripts/tests/phase7bBrowserContract.test.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: `package.json`
- Modify: `frontend/package.json`

- [ ] **Step 1: Write RED static runner contracts**

Assert exactly one Phase7B spec, one worker, loopback-only origins, `MYSQL_DB` process override equals `novel_creator_v113`, `MARKET_SCHEDULER_ENABLED=false`, no fake/real Provider server, no write allowlist, no `page.request`, `route.fulfill`, `evaluate(fetch)`, request mocking, SQL fixture, or database bootstrap inside the spec. Require owned process/port/root/artifact cleanup and safe fixed-category summary.

- [ ] **Step 2: Register the exact formal target**

Add `browser-phase7b` to `allowedModes`, `formalModes`, command mapping `frontend/e2e/run-phase7b.mjs`, and exact formal spec inventory. Add:

```json
"test:browser:phase7b": "node scripts/run-tests.mjs browser-phase7b"
```

to root `package.json`, plus:

```json
"test:e2e:phase7b": "node e2e/run-phase7b.mjs",
"test:browser:phase7b": "node ../scripts/run-tests.mjs browser-phase7b"
```

to `frontend/package.json`.

- [ ] **Step 3: Implement the read-only spec**

```javascript
import { test, expect } from '@playwright/test'
import { observeRuntime, assertRuntimeEvidenceHealthy } from './runtime-observer.mjs'

test('new product database exposes only approved empty/static state', async ({ page }) => {
  const runtime = observeRuntime(page, { allowedOrigins: JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS) })
  let response = await page.goto('/api/health')
  expect(response.status()).toBe(200)
  expect(JSON.parse(await page.locator('body').innerText())).toEqual({ ok: true })
  await page.goto('/projects')
  await expect(page.getByRole('heading', { name: '项目库' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '从一个名字开始' })).toBeVisible()
  await page.goto('/assets/styles')
  await expect(page.getByRole('heading', { name: '风格模板库' })).toBeVisible()
  await expect(page.getByText('APPROVED STYLES').locator('..')).toContainText('10')
  await expect(page.locator('.style-grid article')).toHaveCount(10)
  await page.goto('/assets/experience')
  await expect(page.getByRole('heading', { name: '经验卡库' })).toBeVisible()
  await expect(page.getByText('APPROVED CARDS').locator('..')).toContainText('64')
  response = await page.goto('/api/market-sources')
  expect(response.status()).toBe(200)
  expect(JSON.parse(await page.locator('body').innerText())).toHaveLength(2)
  await page.goto('/settings/providers')
  await expect(page.getByRole('heading', { name: 'Provider 与模型' })).toBeVisible()
  await expect(page.getByText('还没有 Provider 配置')).toBeVisible()
  assertRuntimeEvidenceHealthy(await runtime.finish())
})
```

These assertions use the current production routes and visible strings. If a RED exposes a contract mismatch, inspect the production serializer/component and correct the test only when the approved 10/64/two/zero state remains provable; do not change product API/UI code.

- [ ] **Step 4: Implement the owned runner**

The runner reserves backend/Vite ports, creates one temporary root with direct-child artifact/result directories, starts backend with copied environment plus only `MYSQL_DB=novel_creator_v113` and `MARKET_SCHEDULER_ENABLED=false`, starts Vite, runs Playwright once, scans runtime evidence for Provider/outbound/write requests, stops children, audits ports, and removes the root with bounded retry. It never creates, initializes, seeds, or drops a database. Safe output fields are only `firstStage`, `firstCause`, `scenarioCount`, `providerCalls`, `outboundRequests`, and resource-ledger counts.

- [ ] **Step 5: Run contracts, syntax, and commit**

```powershell
node --test scripts/tests/phase7bBrowserContract.test.mjs
node --check frontend/e2e/run-phase7b.mjs
node --check frontend/e2e/playwright.phase7b.config.mjs
node --check frontend/e2e/phase7b-product-database-readiness.spec.mjs
node --check scripts/run-tests.mjs
git diff --check
git add frontend/e2e/phase7b-product-database-readiness.spec.mjs frontend/e2e/playwright.phase7b.config.mjs frontend/e2e/run-phase7b.mjs scripts/tests/phase7bBrowserContract.test.mjs scripts/run-tests.mjs package.json frontend/package.json
git commit -m "test: add phase7b readiness browser gate"
```

Do not run the formal browser gate yet.

## Task 9: Tooling verification and two-stage review

**Files:** no production changes expected.

- [ ] **Step 1: Run all Phase 7B unit tests**

```powershell
python -m pytest backend/tests/unit/test_product_database_readiness_domain.py backend/tests/unit/test_product_database_inventory.py backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_cutover_product_database_command.py -q --basetemp=.pytest-phase7b-unit-final
```

- [ ] **Step 2: Run Phase 7B disposable MySQL integration once**

```powershell
python -m pytest backend/tests/integration/test_product_database_readiness_mysql.py -m mysql -q --basetemp=.pytest-phase7b-mysql-final
```

- [ ] **Step 3: Run contracts, compile, full unit suite, and build**

```powershell
node --test scripts/tests/phase7bBrowserContract.test.mjs
python -m py_compile backend/domain/product_database_readiness.py backend/services/product_database_inventory.py backend/services/product_database_backup.py backend/services/product_database_readiness.py backend/scripts/prepare_product_database.py backend/scripts/cutover_product_database.py
npm test
npm run build
git diff --check
git status --short
```

Expected: all commands exit `0`; Python and both Node suites are reported separately; build succeeds; worktree contains only intentional commits and no task-owned residue.

- [ ] **Step 4: Request specification review**

Reviewer checks exact design coverage, approval gates, no legacy cleanup target, no public boundary changes, receipt chain, and exact test evidence. Active Critical/Important/Minor must be `0/0/0` before proceeding.

- [ ] **Step 5: Request quality review**

Reviewer checks secret/path leakage, subprocess argument safety, option-file/backup ownership, symlink/reparse handling, primary-cleanup precedence, disposable ledger, false-green tests, and browser lifecycle. Active Critical/Important must be zero; resolve Minor unless explicitly deferred in writing.

## Task 10: Stop for MySQL 8.4 client and real Stage A approval

**This is a mandatory user-input stop. Do not execute the command in this task automatically.**

- [ ] **Step 1: Present the exact preflight facts**

Report selected absolute client paths and versions, configured server/version, legacy/new names, external backup directory, old inventory hash/table/count summary, proposed backup basename, and product-process shutdown proof. Do not print the password, DSN, full option path, row values, or business IDs.

- [ ] **Step 2: Present the exact Stage A command preview**

```powershell
python -m backend.scripts.prepare_product_database --legacy-database novel_creator --new-database novel_creator_v113 --backup-dir <USER_APPROVED_ABSOLUTE_EXTERNAL_DIRECTORY> --mysqldump <USER_APPROVED_MYSQL84_MYSQLDUMP_EXE> --mysql <USER_APPROVED_MYSQL84_MYSQL_EXE> --execute --confirm-legacy novel_creator --confirm-new novel_creator_v113 --confirm-prepare PREPARE-PHASE7B
```

The two angle-bracket values are display-time substitutions from the user-approved paths; the implementation does not invent defaults.

- [ ] **Step 3: Ask for explicit Stage A approval and stop**

Accept only an unambiguous approval of that exact command/path/name set. A design approval, plan approval, prior generic “continue”, or approval to install the clients is not Stage A authorization.

## Task 11: Execute real Stage A exactly once after approval

**Files:** real backup and readiness receipt are outside the repository; `novel_creator_v113` is intentionally persistent.

- [ ] **Step 1: Recheck clean code/resource state and product-process shutdown**

Run read-only checks for branch/HEAD/status, relevant processes/ports, exact configured DB, client versions, and backup-directory ownership. Abort on drift.

- [ ] **Step 2: Execute the exact approved command once**

Do not retry automatically. On first failure, stop, preserve the backup if already published, audit only owned resources, and report the fixed failure stage.

- [ ] **Step 3: Verify the Stage A receipt independently**

Read-only verify old inventory unchanged, backup digest/length, restore drill cleaned, new DB exact 91-table v1.13 manifest, 10/64/two static counts, all prohibited business counts zero, and receipt chain ending at `awaiting_cutover_approval`.

- [ ] **Step 4: Run the temporary-override browser gate once**

```powershell
npm run test:browser:phase7b
```

Expected: one scenario passes; Provider/outbound/write counts are zero; owned process/port/root/artifact residue zero.

- [ ] **Step 5: Commit no real artifacts and stop**

Confirm the dump/receipt remain outside the repo, `.env.local.json` is unchanged, `novel_creator` and `novel_creator_v113` both exist, and the worktree is clean. Present the Stage A safe receipt.

## Task 12: Stop for separate Stage B cutover approval

**This is a second mandatory user-input stop.**

- [ ] **Step 1: Present exact cutover inputs**

Report preparation receipt hash, old/new inventory hashes, current configured database, exact config path identity, both database presence, normal-smoke command, and rollback command.

- [ ] **Step 2: Present the exact cutover command**

```powershell
python -m backend.scripts.cutover_product_database --receipt <APPROVED_EXTERNAL_READINESS_RECEIPT> --database novel_creator_v113 --confirm-cutover CUTOVER-PHASE7B --execute
```

- [ ] **Step 3: Ask for explicit Stage B approval and stop**

Stage A approval never implies Stage B approval.

## Task 13: Execute Stage B, final verification, and acceptance

**Files:**
- Create: `docs/superpowers/acceptance/2026-08-14-phase7b-product-database-readiness.md`

- [ ] **Step 1: Execute the exact approved cutover command once**

If normal configured smoke fails, let the command restore the original configuration atomically, audit both database identities, and stop. Do not retry automatically.

- [ ] **Step 2: Verify normal configured startup and browser smoke**

Run normal backend startup without `MYSQL_DB` override, then `npm run test:browser:phase7b` in post-cutover mode. Require the same read-only UI/API state, Provider/outbound zero, and cleanup ledger zero.

- [ ] **Step 3: Run final matrix**

```powershell
npm test
npm run test:integration
npm run build
git diff --check
git status --short
```

Run each formal command once with a timeout known to exceed its accepted historical duration. Stop on the first failure and preserve exact first-cause evidence.

- [ ] **Step 4: Write the acceptance document**

Record exact commits, schema/version/hash/table counts, static package versions/hashes/counts, old/new inventory hashes, backup basename/hash/length, restore proof, Stage A and B commands with private absolute paths redacted, test counts, browser result, Provider/outbound zero, resource ledger, spec/quality review results, configuration rollback proof, and the explicit statement: `novel_creator is retained; no legacy table was deleted; retirement requires a separate post-Phase-7C approval.`

- [ ] **Step 5: Review and commit acceptance**

```powershell
git diff --check
git add docs/superpowers/acceptance/2026-08-14-phase7b-product-database-readiness.md
git commit -m "docs: accept phase7b product database readiness"
```

Request final specification and quality reviews. Active Critical/Important must be zero. Do not merge or push until the user explicitly requests integration.

## Plan self-review checklist

- [ ] Every design goal maps to Tasks 1–13.
- [ ] No task changes schema fragments, schema version, API routes, DTOs, UI behavior, Provider logic, or market refresh behavior.
- [ ] All real writes are behind explicit Stage A or Stage B approval stops.
- [ ] `novel_creator` never appears in a drop/cleanup allowlist.
- [ ] Every subprocess uses an explicit absolute executable and a private option file; no password is in argv/output.
- [ ] Backup success survives later failures; old DB inventory is compared before/after.
- [ ] Restore and test databases use closed current-run-owned names and end with zero residue.
- [ ] New DB resume accepts only exact-ready state and rejects partial/nonempty unknown state.
- [ ] Static seeding is exact and idempotent; all business/Provider/corpus state remains empty.
- [ ] Temporary smoke and post-cutover smoke make zero Provider/outbound/write requests.
- [ ] Cutover changes only `MYSQL_DB`, preserves all other local config fields, and rolls back atomically.
- [ ] Old database remains after acceptance; whole-database retirement is deferred to a separately approved post-Phase-7C task.
