# Phase 7B Browser Failure Substage Implementation Plan

**Goal:** Preserve one allowlisted browser failure substage through the existing
Node-to-Python Stage A boundary.

## Task 1: Add RED tests

- Extend `scripts/tests/phase7bBrowserContract.test.mjs` for the fixed failure
  marker, whitelist selection, fallback, and secret suppression.
- Extend `backend/tests/unit/test_prepare_product_database_command.py` for strict
  non-zero-exit marker parsing and the `browser_stage` CLI field.
- Run only the new tests and confirm they fail for the missing behavior.

## Task 2: Implement the safe channel

- Update `frontend/e2e/run-phase7b.mjs` to render the fixed allowlisted marker.
- Update `backend/scripts/prepare_product_database.py` to parse exactly one valid
  marker, send it through an optional in-memory callback, and append the fixed
  CLI field only for `browser-smoke` failures.
- Preserve all existing public exceptions and lifecycle behavior.

## Task 3: Verify and commit

- Re-run the RED tests to GREEN.
- Run both complete touched test files and the focused Phase 7B compatibility
  gate, then run compile/syntax and `git diff --check` checks.
- Review the diff for scope and secret safety, commit the tracked changes, and
  stop before any real Stage A execution.
