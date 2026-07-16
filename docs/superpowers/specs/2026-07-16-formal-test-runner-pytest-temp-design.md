# Formal Test Runner Pytest Temp Isolation Design

**Status:** Approved design, 2026-07-16
**Scope:** `scripts/run-tests.mjs` and its Node unit tests only

## Problem

The formal `npm run test:milestone2` aggregate invokes pytest without an explicit
temporary root. On this Windows workstation, pytest's shared default temp root can
be missing or inaccessible. Tests that use `tmp_path` then fail during fixture
setup even though the same suites pass with an explicit `--basetemp`.

## Selected design

The formal runner owns one repository-local pytest temp namespace:
`.codex-test-artifacts/pytest`. Each Python stage receives a deterministic,
stage-specific child through `--basetemp`:

- `m1-regression`
- `unit-api`
- `integration`

The paths are fixed runner constants, never derived from user input. Separate
stages cannot share a basetemp, while standalone suites and the aggregate use the
same command contract.

## Lifecycle and failure handling

Before the first Python stage, the runner creates only the fixed parent namespace.
Before each pytest command, it removes any prior directory for that exact stage and
recreates the parent if necessary. After every child result, and again from the
outer `finally`, it removes only the fixed stage directories and the runner-owned
pytest namespace. It never recursively removes `.codex-test-artifacts` itself.

Cleanup errors are fail-closed: a Python stage is not started when its basetemp
cannot be prepared, and a cleanup failure makes the formal runner non-zero. Error
messages identify the stage but do not print environment variables or database
credentials.

## Command and environment boundaries

The existing test composition and order remain unchanged. The runner adds only
`--basetemp <stage-path>` to pytest argument arrays. It continues to use
`shell:false`, inherits the existing explicit environment, and does not set global
`PYTEST_ADDOPTS` or use the shared system pytest temp root.

## Verification

Node unit tests must prove:

1. every formal pytest command has exactly one approved `--basetemp`;
2. the three Python stages use distinct deterministic paths;
3. preparation happens before spawn;
4. success, child failure, spawn failure, and cleanup failure all execute bounded
   cleanup and return the correct non-zero status;
5. unrelated paths under `.codex-test-artifacts` are never removed;
6. Milestone 2 command order and closed formal test inventory remain unchanged.

Acceptance then reruns `npm run test:milestone2`, followed by the existing build,
diff, artifact, and legacy-name safety scans. No product database or Provider/model
call is part of this change.
