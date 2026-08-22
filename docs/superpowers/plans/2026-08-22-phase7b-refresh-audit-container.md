# Phase 7B Refresh Audit Container Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the official-data refresh audit accept the real `aiomysql` list result while preserving all strict data checks.

**Architecture:** Align the existing test session with the installed adapter's return type, then normalize that result once at the official-audit boundary. No validation rule or public contract changes.

**Tech Stack:** Python 3.12, aiomysql, asyncio, pytest.

---

### Task 1: Reproduce and fix the container mismatch

**Files:**
- Modify: `backend/tests/unit/test_prepare_product_database_command.py:3548`
- Modify: `backend/scripts/prepare_product_database.py:1421`

- [ ] **Step 1: Write the failing regression condition**

Change the official-audit test session to mirror `aiomysql`:

```python
return list(refresh_rows)
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_prepare_product_database_command.py::test_default_official_audit_reads_exact_idle_refresh_state_authority -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-refresh-audit-red
```

Expected: fail with `new database readiness audit failed` because the current
implementation requires `type(refresh_rows) is tuple`.

- [ ] **Step 3: Implement the minimal boundary normalization**

Wrap the existing database result without changing its SQL:

```python
refresh_rows = tuple(
    await session.fetchall(
        # existing exact SELECT
    )
)
```

- [ ] **Step 4: Verify GREEN**

Run the exact RED command again. Expected: one passed test and zero warnings.

- [ ] **Step 5: Run focused regression tests**

```powershell
python -m pytest backend/tests/unit/test_prepare_product_database_command.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-refresh-audit-command
python -m pytest backend/tests/unit/test_product_database_backup.py backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_project_import_staging.py -q -W error -p no:cacheprovider --basetemp=tmp/pytest-phase7b-refresh-audit-focused
python -m py_compile backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git diff --check
```

Expected: zero failures, errors, or warnings.

- [ ] **Step 6: Verify the real adapter path once**

Run one controlled disposable MySQL audit using only `TEST_MYSQL_*`, create and
delete one exact run-owned `novel_creator_test_<32 lowercase hex>` database, and
require `official_data=pass`, `disposable_created=1`, and
`disposable_cleaned=1`. Do not run Stage A/B or access either product database.

- [ ] **Step 7: Commit the implementation**

```powershell
git add backend/scripts/prepare_product_database.py backend/tests/unit/test_prepare_product_database_command.py
git commit -m "fix: normalize phase7b refresh audit rows"
```

Expected: exactly the two implementation files are included.
