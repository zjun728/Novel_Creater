# Router Domain Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `backend.domain.routers` the sole owner of all 22 router-package Python files and remove every executable import of the retired `backend.routers` namespace without changing product behavior.

**Architecture:** Complete the migration as one atomic namespace cutover: first add a fail-closed source contract, then move the remaining four files and mechanically rewrite every production, test, fixture, and embedded-runner import. Do not add a compatibility package or alias because two import identities would make module-level gateways, dependency overrides, and lifecycle ownership ambiguous. The implementation is sequential because the move and import rewrite share one namespace boundary; independent verification commands may run in parallel only after the source contract is green.

**Tech Stack:** Python 3, FastAPI, pytest, Node.js test runner, PowerShell, Vite, Git.

---

## File map

### New test owner

- Create `backend/tests/unit/test_router_domain_boundary.py`: exact 22-file package inventory, retired-directory absence, and repository source-import boundary.

### Router package move

- Delete `backend/routers/__init__.py` and the 21 router/helper modules under `backend/routers/`.
- Create the same 22 files under `backend/domain/routers/` with unchanged bodies except for the two canonical intra-router imports listed below.
- The 18 files already present in the working tree remain pure blob-identical moves from merged `HEAD` before import rewriting.
- Move the four remaining files without editing their bodies:
  - `backend/routers/finalization.py` -> `backend/domain/routers/finalization.py`
  - `backend/routers/novel_downloads.py` -> `backend/domain/routers/novel_downloads.py`
  - `backend/routers/project_imports.py` -> `backend/domain/routers/project_imports.py`
  - `backend/routers/project_packages.py` -> `backend/domain/routers/project_packages.py`

### Production and fixture imports

- Modify `backend/main.py`.
- Modify `backend/domain/routers/bibles.py`.
- Modify `backend/domain/routers/projects.py`.
- Modify `backend/scripts/prepare_phase6b_browser_db.py`.

### API test imports

- Modify every router-importing file in `backend/tests/api/`:
  - `test_application_settings_routes.py`
  - `test_asset_routes.py`
  - `test_bible_routes.py`
  - `test_canon_routes.py`
  - `test_chapter_outline_routes.py`
  - `test_chapter_session_routes.py`
  - `test_contract_routes.py`
  - `test_corpus_routes.py`
  - `test_draft_operation_routes.py`
  - `test_finalization_routes.py`
  - `test_market_source_routes.py`
  - `test_model_binding_routes.py`
  - `test_novel_download_routes.py`
  - `test_planning_routes.py`
  - `test_product_routes.py`
  - `test_project_import_routes.py`
  - `test_project_package_routes.py`
  - `test_provider_redaction.py`
  - `test_public_domain_errors.py`
  - `test_secret_error_redaction.py`
  - `test_seed_routes.py`
  - `test_story_engine_routes.py`
  - `test_style_trial_routes.py`

### Unit and integration test imports

- Modify `backend/tests/unit/test_main_lifespan.py`.
- Modify `backend/tests/unit/test_planning_repository.py`.
- Modify `backend/tests/integration/test_chapter_outline_lifecycle.py`.
- Modify `backend/tests/integration/test_seed_archived_capabilities_api.py`.

### Embedded browser-fixture imports

- Modify `frontend/e2e/run-phase2a.mjs`.
- Modify `frontend/e2e/run-phase2b.mjs`.
- Modify `frontend/e2e/run-phase5.mjs`.
- Modify `frontend/e2e/run-phase6b.mjs`.
- Modify `frontend/e2e/run-phase6c.mjs`.

No route implementation, DTO, service, repository, schema, Vue component, or CSS file changes are authorized by this plan.

### Task 1: Add the fail-closed router namespace contract

**Files:**
- Create: `backend/tests/unit/test_router_domain_boundary.py`

- [ ] **Step 1: Write the failing contract test**

Create the file with this complete content:

```python
import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LEGACY_ROUTER_ROOT = REPOSITORY_ROOT / "backend" / "routers"
DOMAIN_ROUTER_ROOT = REPOSITORY_ROOT / "backend" / "domain" / "routers"
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "backend",
    REPOSITORY_ROOT / "frontend" / "e2e",
    REPOSITORY_ROOT / "scripts",
)
SOURCE_SUFFIXES = {".py", ".mjs"}
LEGACY_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+backend\.routers(?:\b|\.)",
    re.MULTILINE,
)
EXPECTED_ROUTER_FILES = {
    "__init__.py",
    "application_settings.py",
    "assets.py",
    "bibles.py",
    "canon.py",
    "chapter_outlines.py",
    "chapter_sessions.py",
    "contracts.py",
    "corpus.py",
    "finalization.py",
    "helpers.py",
    "market_sources.py",
    "model_bindings.py",
    "novel_downloads.py",
    "planning.py",
    "project_imports.py",
    "project_packages.py",
    "projects.py",
    "providers.py",
    "seeds.py",
    "story_engines.py",
    "style_trials.py",
}


def _legacy_import_locations() -> list[str]:
    locations = []
    for source_root in SOURCE_ROOTS:
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            source = path.read_text(encoding="utf-8")
            for match in LEGACY_IMPORT.finditer(source):
                line_number = source.count("\n", 0, match.start()) + 1
                locations.append(
                    f"{path.relative_to(REPOSITORY_ROOT).as_posix()}:{line_number}"
                )
    return locations


def test_domain_router_package_has_exact_closed_inventory():
    assert {path.name for path in DOMAIN_ROUTER_ROOT.glob("*.py")} == (
        EXPECTED_ROUTER_FILES
    )


def test_retired_router_package_is_physically_absent():
    assert not LEGACY_ROUTER_ROOT.exists()


def test_repository_sources_do_not_import_retired_router_namespace():
    assert _legacy_import_locations() == []
```

- [ ] **Step 2: Run the contract and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_router_domain_boundary.py -q --basetemp=.pytest-router-boundary-red
```

Expected: FAIL. The inventory test reports the four missing domain files, the retired-directory test sees `backend/routers`, and the import test reports `backend.routers` references. Do not weaken any assertion to obtain GREEN.

- [ ] **Step 3: Record the RED evidence and leave the test uncommitted**

Record the three failing test names and the first fixed failure cause in the execution notes. Do not commit a deliberately red tree; Task 2 turns this same contract green before the first implementation commit.

### Task 2: Complete the atomic package move and canonical import rewrite

**Files:**
- Move: all 22 Python files from `backend/routers/` to `backend/domain/routers/`
- Modify: every production, test, fixture, and embedded-runner file listed in the file map
- Test: `backend/tests/unit/test_router_domain_boundary.py`

- [ ] **Step 1: Verify the 18 existing moves still match merged `HEAD`**

Run this read-only hash check before changing imports:

```powershell
$existingMoves = @(
  '__init__.py', 'application_settings.py', 'assets.py', 'bibles.py',
  'canon.py', 'chapter_outlines.py', 'chapter_sessions.py', 'contracts.py',
  'corpus.py', 'helpers.py', 'market_sources.py', 'model_bindings.py',
  'planning.py', 'projects.py', 'providers.py', 'seeds.py',
  'story_engines.py', 'style_trials.py'
)
$mismatches = foreach ($name in $existingMoves) {
  $headHash = git rev-parse "HEAD:backend/routers/$name"
  $worktreeHash = git hash-object "backend/domain/routers/$name"
  if ($headHash -ne $worktreeHash) { $name }
}
if ($mismatches) { throw "Non-mechanical existing moves: $($mismatches -join ', ')" }
```

Expected: exit 0 with no mismatches. If a mismatch appears, stop and reconcile it against merged `HEAD`; do not overwrite a user change.

- [ ] **Step 2: Move the remaining four files without editing their bodies**

Move these exact source/target pairs:

```text
backend/routers/finalization.py      -> backend/domain/routers/finalization.py
backend/routers/novel_downloads.py   -> backend/domain/routers/novel_downloads.py
backend/routers/project_imports.py   -> backend/domain/routers/project_imports.py
backend/routers/project_packages.py  -> backend/domain/routers/project_packages.py
```

Use a pure rename operation. Immediately verify each target blob equals its merged-`HEAD` source:

```powershell
$remainingMoves = @(
  'finalization.py', 'novel_downloads.py',
  'project_imports.py', 'project_packages.py'
)
$mismatches = foreach ($name in $remainingMoves) {
  $headHash = git rev-parse "HEAD:backend/routers/$name"
  $worktreeHash = git hash-object "backend/domain/routers/$name"
  if ($headHash -ne $worktreeHash) { $name }
}
if ($mismatches) { throw "Non-mechanical remaining moves: $($mismatches -join ', ')" }
```

Expected: exit 0 with no mismatches.

- [ ] **Step 3: Rewrite every import to the canonical namespace**

Apply only these two textual transformations to the files in the file map:

```python
# Before
from backend.routers import planning
from backend.routers.contracts import get_contract_service
import backend.routers.planning as planning_router

# After
from backend.domain.routers import planning
from backend.domain.routers.contracts import get_contract_service
import backend.domain.routers.planning as planning_router
```

The transformation is exhaustive:

```text
from backend.routers        -> from backend.domain.routers
import backend.routers      -> import backend.domain.routers
```

Do not alter import aliases, imported names, router objects, dependency providers, function bodies, strings unrelated to Python imports, or formatting beyond the changed namespace.

- [ ] **Step 4: Verify the source contract is GREEN**

Run:

```powershell
python -m pytest backend/tests/unit/test_router_domain_boundary.py -q --basetemp=.pytest-router-boundary-green
```

Expected: `3 passed`. Also run this independent source scan:

```powershell
$roots = @('backend', 'frontend/e2e', 'scripts')
$violations = foreach ($root in $roots) {
  if (Test-Path $root) {
    Get-ChildItem -LiteralPath $root -Recurse -File |
      Where-Object { $_.Extension -in '.py', '.mjs' } |
      Select-String -Pattern '^\s*(from|import)\s+backend\.routers(\b|\.)'
  }
}
if ($violations) { $violations; throw 'Retired router imports remain' }
```

Expected: exit 0 and no violations.

- [ ] **Step 5: Compile the migrated package and import the application**

Run:

```powershell
$routerFiles = Get-ChildItem backend/domain/routers -File -Filter '*.py'
python -m py_compile backend/main.py backend/scripts/prepare_phase6b_browser_db.py $routerFiles.FullName
python -c "import backend.main; print(len(backend.main.app.routes))"
```

Expected: both commands exit 0. The second command prints a positive route count without `ModuleNotFoundError` or duplicate-module warnings.

- [ ] **Step 6: Run focused router and lifespan tests**

Run:

```powershell
python -m pytest backend/tests/unit/test_router_domain_boundary.py backend/tests/api backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_planning_repository.py -q --basetemp=.pytest-router-focused
```

Expected: PASS with no failures. Existing skips, if any, must be reported rather than converted to passes.

- [ ] **Step 7: Commit the atomic migration**

Stage only the router moves, canonical import rewrites, and boundary test:

```powershell
git add backend/main.py backend/routers backend/domain/routers backend/scripts/prepare_phase6b_browser_db.py backend/tests/api backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_planning_repository.py backend/tests/unit/test_router_domain_boundary.py backend/tests/integration/test_chapter_outline_lifecycle.py backend/tests/integration/test_seed_archived_capabilities_api.py frontend/e2e/run-phase2a.mjs frontend/e2e/run-phase2b.mjs frontend/e2e/run-phase5.mjs frontend/e2e/run-phase6b.mjs frontend/e2e/run-phase6c.mjs
git diff --cached --check
git commit -m "refactor: move routers into domain package"
```

Expected: `git diff --cached --check` exits 0 and the commit contains no route behavior, DTO, schema, UI, or unrelated file changes.

### Task 3: Verify route inventory and affected integration collection

**Files:**
- Test: `backend/tests/api/test_route_inventory.py`
- Test: `backend/tests/integration/test_chapter_outline_lifecycle.py`
- Test: `backend/tests/integration/test_seed_archived_capabilities_api.py`

- [ ] **Step 1: Run the exact public route inventory**

Run:

```powershell
python -m pytest backend/tests/api/test_route_inventory.py -q --basetemp=.pytest-router-inventory
```

Expected: all tests PASS. `APPROVED_FORMAL_ROUTES` remains byte-for-byte unchanged; do not update it to accommodate a route difference.

- [ ] **Step 2: Collect the two affected integration modules**

Run:

```powershell
python -m pytest backend/tests/integration/test_chapter_outline_lifecycle.py backend/tests/integration/test_seed_archived_capabilities_api.py --collect-only -q
```

Expected: exit 0 with both files collected and no import error. This migration does not authorize changing integration fixtures or markers.

- [ ] **Step 3: Verify embedded browser runners remain syntactically valid**

Run:

```powershell
node --check frontend/e2e/run-phase2a.mjs
node --check frontend/e2e/run-phase2b.mjs
node --check frontend/e2e/run-phase5.mjs
node --check frontend/e2e/run-phase6b.mjs
node --check frontend/e2e/run-phase6c.mjs
```

Expected: all five commands exit 0 with no output.

- [ ] **Step 4: Confirm the commit is mechanically scoped**

Run:

```powershell
git show --stat --oneline HEAD
git diff HEAD^ HEAD --check
git status --short
```

Expected: the commit includes only the files named by Tasks 1 and 2; diff check exits 0; the worktree is clean except for explicitly documented pre-existing artifacts, which must not be staged or deleted.

### Task 4: Run the full unit and build gates

**Files:**
- Verify only; no planned source changes

- [ ] **Step 1: Run the full unit suite once**

Run:

```powershell
npm test
```

Expected: exit 0. Record the exact Python passed/skipped counts and Node passed count from this run. On the first failure, stop and diagnose it with the `systematic-debugging` skill before changing code or rerunning the whole suite.

- [ ] **Step 2: Build the frontend once**

Run:

```powershell
npm run build
```

Expected: exit 0. Report the module count and any warnings exactly; do not classify warnings as failures unless the build does.

- [ ] **Step 3: Decide the browser-gate boundary from evidence**

Do not run a formal browser gate by default. The migration changes Python import locations and embedded fixture imports but not route behavior, browser interactions, or runtime resource ownership; the boundary contract, application import, focused API suite, route inventory, runner syntax checks, full unit suite, and build directly exercise the change.

Run a browser gate only if one of those checks reveals a runtime wiring defect that cannot be closed at a lower layer. If that happens, run only the smallest affected formal gate once and record its resource ledger; do not blindly rerun all Phase 2/5/6 browser suites.

- [ ] **Step 4: Perform final repository checks**

Run:

```powershell
git diff --check
git status --short
git log -2 --oneline
```

Expected: diff check exits 0; the router migration commit follows the design/plan documentation commit; status is clean except for explicitly documented, pre-existing artifacts.

### Task 5: Review the final migration and hand off the branch

**Files:**
- Review: `docs/superpowers/specs/2026-08-13-router-domain-migration-design.md`
- Review: all files in the Task 2 commit

- [ ] **Step 1: Run the specification coverage review**

Use the `requesting-code-review` skill against the exact migration commit. The review must check:

```text
1. Exactly 22 Python files exist under backend/domain/routers.
2. backend/routers is absent.
3. No executable source imports backend.routers.
4. backend.main registers the exact pre-migration route inventory once.
5. No compatibility proxy or sys.modules alias exists.
6. Router bodies differ only where the canonical import path changed.
7. No route, DTO, status, error mapping, DI, lifespan, schema, UI, Provider, or network behavior changed.
```

Expected: no active Critical or Important findings. Fix valid findings with RED/GREEN tests and a separate narrow commit; do not amend away review history after sharing the commit.

- [ ] **Step 2: Re-run checks affected by any review fix**

If review produces a code change, run the boundary contract, focused API/lifespan tests, route inventory, full `npm test`, and `npm run build` again. If review is read-only and finds no code issue, retain the fresh Task 4 evidence without an artificial rerun.

- [ ] **Step 3: Report the completed branch without pushing or merging**

The final handoff must include:

```text
- branch: codex/router-domain-migration
- documentation commit SHA
- migration commit SHA
- any review-fix commit SHA
- boundary/focused/full/build counts
- browser-gate decision and rationale
- exact git status
```

Do not push or merge until the user gives a new explicit instruction.

## Self-review result

- Spec coverage: every approved architecture, failure-handling, testing, and acceptance requirement maps to Tasks 1-5.
- Placeholder scan: the plan contains no deferred implementation markers or unspecified code steps.
- Type consistency: the expected inventory is consistently 22 Python files total, comprising 21 router/helper modules and `__init__.py`.
- Scope consistency: the plan preserves the current 18 pure moves, adds the remaining four, rewrites only import namespaces, and explicitly rejects compatibility aliases and product behavior changes.
