# Phase 7B Stage A Safe Failure Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fixed, secret-free Stage A failure-stage output without changing the readiness service, database lifecycle, receipts, backups, or execution authorization.

**Architecture:** Keep one local `stage` string inside `run_cli()` and update it in the CLI's existing dependency wrappers. Classify cleanup only from exact, already-safe error types and messages, emit three fixed fields before preserving the current exception behavior, and extend the existing command failure matrix instead of adding a new framework.

**Tech Stack:** Python 3.12, asyncio, pytest, existing Phase 7B dependency injection and fixed-error contracts.

---

## Fixed boundaries

- Work only in `D:\Projects\Novel_Creater\.worktrees\phase7b-implementation` on `codex/phase7b-implementation`.
- Modify only `backend/scripts/prepare_product_database.py` and `backend/tests/unit/test_prepare_product_database_command.py`.
- Do not change service/domain interfaces, database SQL, lifecycle boundaries, backup or receipt formats, CLI arguments, Stage B, Provider behavior, or schema.
- Do not add a class, observer, event bus, journal, failure receipt, retry, resume flag, or new idempotency mechanism.
- Do not execute real Stage A, the browser gate, Stage B, a Provider call, or any database write.
- Preserve both retained SQL backups and the pre-existing zero-byte option residue.

## File map

- Modify `backend/scripts/prepare_product_database.py` — track one fixed local stage, safely classify fixed cleanup leaves, and emit three fixed failure fields.
- Modify `backend/tests/unit/test_prepare_product_database_command.py` — extend the existing execute failure matrix and add focused cleanup/secret-output assertions.

## Task 1: Add failing safe-stage command tests

**Files:**
- Modify: `backend/tests/unit/test_prepare_product_database_command.py:3680-3944`
- Test: `backend/tests/unit/test_prepare_product_database_command.py`

- [ ] **Step 1: Import the existing safe error types**

Add these imports beside the current readiness/backup imports:

```python
from backend.domain.product_database_readiness import ProductDatabaseReadinessError
from backend.services.product_database_backup import ProductDatabaseBackupError
```

Do not import private cleanup constants from either service.

- [ ] **Step 2: Extend the existing all-stage matrix with expected public stages**

Change the existing `stage` parameter into `(injected_stage, public_stage)` and use this exact mapping:

```python
(
    ("client-preflight", "preflight"),
    ("connection", "preflight"),
    ("inventory", "legacy-inventory-before"),
    ("backup", "backup"),
    ("restore", "restore-drill"),
    ("proof", "schema-proof"),
    ("seed-assets", "asset-seed"),
    ("seed-market", "market-seed"),
    ("audit", "readiness-audit"),
    ("smoke", "browser-smoke"),
    ("publication", "receipt-publish"),
)
```

Keep the existing flow-control, ownership, cleanup, backup-retention, target-retention, and secret assertions. Replace `assert output == []` with:

```python
assert output == [
    "outcome=failed",
    f"stage={public_stage}",
    "cleanup=no-failure-reported",
]
```

Continue using `injected_stage` for dependency injection and existing expected-resource assertions.

- [ ] **Step 3: Add the four missing-stage cases to the existing test world**

Add one focused parameterized test using `RealTask4ExecuteWorld` and the existing `_arguments()` helper. The cases and injection points must be:

```python
(
    ("legacy-after", "legacy-inventory-after"),
    ("boundary-enter", "new-database-init"),
    ("storage", "readiness-audit"),
    ("boundary-commit", "boundary-commit"),
)
```

Implement the test-only injections as follows:

```python
class StageWorld(RealTask4ExecuteWorld):
    def __init__(self, injected_stage: str) -> None:
        super().__init__()
        self.injected_stage = injected_stage
        self.legacy_inventory_calls = 0

    async def inventory_database(
        self, config: object, database: str
    ) -> DatabaseInventory:
        if database == LEGACY_DATABASE:
            self.legacy_inventory_calls += 1
            if (
                self.injected_stage == "legacy-after"
                and self.legacy_inventory_calls == 2
            ):
                raise RuntimeError("password=secret-legacy-after")
        return await super().inventory_database(config, database)

    async def read_storage(
        self, config: object, database: str
    ) -> tuple[TableStorage, ...]:
        if self.injected_stage == "storage":
            raise RuntimeError("dsn=mysql://secret-storage")
        return await super().read_storage(config, database)
```

For `boundary-enter`, wrap `super().database_boundary()` and raise a secret-bearing `RuntimeError` from `__aenter__`. For `boundary-commit`, delegate `__aenter__` and raise this already-safe fixed error from `__aexit__` only when the body has no primary:

```python
raise ProductDatabaseReadinessError("product database cleanup failed")
```

Assert each case raises, contains no secret in `repr(raised.value)`, publishes no receipt, and emits:

```python
[
    "outcome=failed",
    f"stage={public_stage}",
    (
        "cleanup=failed"
        if injected_stage == "boundary-commit"
        else "cleanup=no-failure-reported"
    ),
]
```

- [ ] **Step 4: Add one primary-plus-cleanup classification test**

Reuse `ExecuteWorld` and override its option context so that the body fails at `seed-assets` while `__exit__` raises the existing fixed backup error:

```python
raise ProductDatabaseBackupError("private mysql option file cleanup failed")
```

Assert primary-first exception behavior is unchanged, secrets remain absent, and output is exactly:

```python
[
    "outcome=failed",
    "stage=asset-seed",
    "cleanup=failed",
]
```

- [ ] **Step 5: Verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_prepare_product_database_command.py::test_execute_all_stage_flow_matrix_uses_real_task4_and_closes_resources backend/tests/unit/test_prepare_product_database_command.py::test_execute_reports_missing_fixed_stages backend/tests/unit/test_prepare_product_database_command.py::test_execute_reports_primary_stage_and_fixed_cleanup_failure -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-safe-stage-red
```

Expected: failures because current `run_cli()` emits no failure fields. Confirm the resource/secret assertions still pass up to the new output assertions.

## Task 2: Implement the minimal CLI-local stage reporter

**Files:**
- Modify: `backend/scripts/prepare_product_database.py:23-63`
- Modify: `backend/scripts/prepare_product_database.py:2047-2203`
- Test: `backend/tests/unit/test_prepare_product_database_command.py`

- [ ] **Step 1: Import only the two safe error types**

Add `ProductDatabaseReadinessError` to the existing domain import and `ProductDatabaseBackupError` from the backup service. Do not import private constants.

- [ ] **Step 2: Add the closed cleanup-message set and two small helpers**

Place this constant after `ProductDatabasePreparationCommandError`:

```python
_FIXED_CLEANUP_MESSAGES = frozenset(
    {
        "private mysql option file cleanup failed",
        "logical backup cleanup failed",
        "logical restore cleanup failed",
        "product database cleanup failed",
        _BOUNDARY_CLEANUP_ERROR,
        _PROOF_CLEANUP_ERROR,
        _RECEIPT_CLEANUP_ERROR,
        _RESTORE_DRILL_CLEANUP_ERROR,
    }
)
```

Add the helpers immediately below it:

```python
def _fixed_failure_messages(error: BaseException) -> tuple[str, ...]:
    if isinstance(error, BaseExceptionGroup):
        return tuple(
            message
            for child in error.exceptions
            for message in _fixed_failure_messages(child)
        )
    if type(error) in (
        ProductDatabasePreparationCommandError,
        ProductDatabaseReadinessError,
        ProductDatabaseBackupError,
    ):
        return (str(error),)
    return ()


def _safe_failure_fields(stage: str, error: BaseException) -> tuple[str, str]:
    messages = _fixed_failure_messages(error)
    cleanup_failed = any(
        message in _FIXED_CLEANUP_MESSAGES for message in messages
    )
    if (
        stage == "browser-smoke"
        and messages
        and all(message in _FIXED_CLEANUP_MESSAGES for message in messages)
    ):
        stage = "boundary-commit"
    return stage, "failed" if cleanup_failed else "no-failure-reported"
```

These helpers may compare only exact strings from the three fixed safe error types. They must not inspect or emit arbitrary exception messages.

- [ ] **Step 3: Track one local stage in `run_cli()`**

Immediately after execute approval validation, initialize:

```python
stage = "preflight"
```

Add `nonlocal stage` and these assignments before the existing operations:

```python
# inventory(role)
stage = {
    "legacy-before": "legacy-inventory-before",
    "legacy-after": "legacy-inventory-after",
    "new": "readiness-audit",
}[role]

# create_backup
stage = "backup"

# restore_drill
stage = "restore-drill"

# current_schema_proof
stage = "schema-proof"

# boundary
stage = "new-database-init"

# seed_assets
stage = "asset-seed"

# seed_market
stage = "market-seed"

# read_storage and audit_official_data
stage = "readiness-audit"

# smoke
stage = "browser-smoke"
```

Do not mark a dependency complete when it returns. Immediately after `prepare_service` returns, set:

```python
stage = "boundary-commit"
```

Immediately after the option context exits and before `publish_receipt`, set:

```python
stage = "receipt-publish"
```

- [ ] **Step 4: Emit fixed failure fields without changing exception behavior**

Replace the execute-mode catch body with:

```python
except BaseException as error:
    failed_stage, cleanup = _safe_failure_fields(stage, error)
    for line in (
        "outcome=failed",
        f"stage={failed_stage}",
        f"cleanup={cleanup}",
    ):
        output(line)
    _raise_public(_sanitized(error, _EXECUTION_ERROR))
```

Do not change `_sanitized`, `_primary_first_context`, `main`, success output, or preview output.

- [ ] **Step 5: Run GREEN**

Run the exact RED command again.

Expected: all selected cases pass with warnings treated as errors.

- [ ] **Step 6: Run the complete command unit file**

```powershell
python -m pytest backend/tests/unit/test_prepare_product_database_command.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-safe-stage-command
```

Expected: zero failures and warnings. Existing success output, preview, flow-control, cleanup, and secret-sanitization tests remain green.

- [ ] **Step 7: Compile, inspect, and commit the two-file implementation**

```powershell
python -m py_compile backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git diff --check
git diff -- backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git add backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git diff --cached --name-only
git commit -m "fix: report safe phase7b stage failures"
```

Expected: exactly the two approved implementation files are committed.

## Task 3: Verify compatibility and stop before real execution

**Files:**
- Test only: existing Phase 7B files

- [ ] **Step 1: Run the focused four-file gate**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_project_import_staging.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-safe-stage-focused
```

Expected: zero failures and warnings.

- [ ] **Step 2: Run the Phase 7B lifecycle gate**

```powershell
python -m pytest backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_cutover_product_database_command.py backend/tests/unit/test_product_database_lifecycle_lock.py backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_config.py backend/tests/unit/test_database_transaction.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-safe-stage-lifecycle
```

Expected: zero failures and warnings; only documented host-specific skips are permitted.

- [ ] **Step 3: Verify scope and retained external resources**

```powershell
python -m py_compile backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git diff --check
git status --short --untracked-files=no
git show --stat --oneline HEAD
Get-FileHash -Algorithm SHA256 D:\Projects\Novel_Creater\.env.local.json
Get-ChildItem -LiteralPath D:\NovelCreatorBackups\phase7b-stagea-20260821 -Force | Select-Object Name,Length
```

Require tracked/index clean; the source-config hash remains `0e3ddb3683e9c878bc1b2d7244c643dc013716a194df9555e837b8000a35f032`; both retained SQL backups and the pre-existing zero-byte option residue remain present; no readiness receipt is created by tests.

- [ ] **Step 4: Review and present the safe stop receipt**

Run a spec-compliance review followed by a code-quality review. Require active Critical/Important issues to be zero. Report the implementation commit, RED/GREEN evidence, complete test counts, Git state, and retained external resources.

Stop before real Stage A. State explicitly that this plan does not authorize a retry, browser gate, Stage B, Provider traffic, legacy deletion, or external artifact cleanup.
