# Cross-Server Product Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guarded one-time command that snapshots the approved foundation rows from legacy MySQL 5.7 and initializes an absent Writer Core V1 target on MySQL 8.

**Architecture:** A fixed-query mysql-client reader produces an in-memory JSON inventory. The bootstrap reuses reset mapping/insertion/validation functions, adds only the canonical preferred Provider rename and cross-server orchestration, and keeps all target DDL behind absence, confirmation, advisory-lock, rollback/drop, and private-authority gates.

**Tech Stack:** Python 3.12, argparse/asyncio/subprocess, mysql CLI login paths, aiomysql admin sessions, existing Writer Core initializer/reset primitives, pytest.

---

### Task 1: Fixed legacy source reader

**Files:**
- Create: `backend/scripts/bootstrap_writer_core_product.py`
- Create: `backend/tests/unit/test_bootstrap_writer_core_product.py`

- [ ] Write failing tests that inject a subprocess runner and assert one capability query plus exactly three `JSON_OBJECT` inventory queries, argument arrays with `shell=False`, `--login-path=novel57-admin`, no password argument, only approved tables, JSON-line parsing, and generic failures without raw stdout/stderr.
- [ ] Run `python -m pytest backend/tests/unit/test_bootstrap_writer_core_product.py -q` and verify RED because the module is absent.
- [ ] Implement `read_legacy_inventory(mysql_client, runner=..., login_path=..., source_database=...)` with a closed constant query whitelist and strict source MySQL 5.7/JSON validation.
- [ ] Re-run the focused test and verify the source-reader tests are GREEN.

### Task 2: Shared V1 mapping and secret-free receipt

**Files:**
- Modify: `backend/scripts/bootstrap_writer_core_product.py`
- Modify: `backend/tests/unit/test_bootstrap_writer_core_product.py`

- [ ] Write failing tests for exact project/three-seed/preferred cardinality, preservation of every Provider ID, the one canonical preferred rename, target-collation collision checks, selected `典镇山河`, stable JSON/hash behavior, and receipt fields that exclude description/base URL/API key/notes/thinking/DSN sentinels.
- [ ] Verify RED for missing `map_legacy_inventory`, `BootstrapReport`, and formatter behavior.
- [ ] Implement mapping by calling reset `_map_project`, `_map_seed`, `_map_provider`, `_require_exact_unique`, and `_require_target_collation_unique`; construct reset `_PreservedState` without copying conversion logic.
- [ ] Re-run focused tests and verify GREEN.

### Task 3: Dry-run target preflight

**Files:**
- Modify: `backend/scripts/bootstrap_writer_core_product.py`
- Modify: `backend/tests/unit/test_bootstrap_writer_core_product.py`

- [ ] Write failing async tests proving dry-run calls the complete target capability gate, requires an absent target, performs source mapping and authoritative collation validation, emits a receipt, and executes no lock/DDL/transaction statements.
- [ ] Verify RED for missing `bootstrap_writer_core_product` orchestration.
- [ ] Implement product/disposable guards, private read authority, target absence query, injected source loader, and dry-run report.
- [ ] Re-run focused tests and verify GREEN.

### Task 4: Execute lifecycle and cleanup

**Files:**
- Modify: `backend/scripts/bootstrap_writer_core_product.py`
- Modify: `backend/tests/unit/test_bootstrap_writer_core_product.py`

- [ ] Write failing tests for exact confirmation/private execute authority, lock then absence recheck, `CREATE DATABASE` plus official initializer, transaction insertion through reset `_insert_preserved_state`, all foundation count verification including eight task items/head zero, commit/release order, and source write count zero.
- [ ] Add failure tests for insert/verify/commit errors with best-effort rollback, incomplete-target drop, lock release, and `BaseExceptionGroup` preservation when cleanup also fails.
- [ ] Implement the lifecycle with injected initializer/inserter/clock/ID factory and fixed cleanup statements guarded to product/disposable target names.
- [ ] Re-run focused tests and verify GREEN.

### Task 5: CLI and deferred integration contract

**Files:**
- Modify: `backend/scripts/bootstrap_writer_core_product.py`
- Modify: `backend/tests/unit/test_bootstrap_writer_core_product.py`
- Create: `backend/tests/integration/test_bootstrap_writer_core_product.py`

- [ ] Write subprocess `--help`, fake `run_cli`, and generic runtime-banner tests. Assert `require_mysql_config()` supplies target credentials, mysql client executable is required, dry-run is default, execute confirmation is mandatory, target/source sessions close, and secrets never enter stdout/stderr.
- [ ] Add a `pytest.mark.mysql` integration test that injects a legacy inventory and uses an absent disposable MySQL 8 schema to exercise execute/verify/cleanup. Do not run this integration test in this turn.
- [ ] Run `python -m pytest backend/tests/unit/test_bootstrap_writer_core_product.py -q`, then ordinary `npm test`; both must exit zero.
- [ ] Run `git diff --check`, inspect the complete diff, verify the script has no source DML and no password-bearing mysql argument, and confirm no real DB/Provider call occurred.
- [ ] Commit implementation with `git commit -m "feat: bootstrap Writer Core across MySQL servers"`.
