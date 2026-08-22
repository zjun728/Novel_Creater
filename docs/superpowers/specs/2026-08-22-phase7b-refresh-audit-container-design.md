# Phase 7B Refresh Audit Container Design

## Goal

Allow the Phase 7B official-data audit to consume the real `aiomysql`
`fetchall()` result without weakening any refresh-state validation.

## Evidence

A disposable MySQL reproduction proved that schema, manifest, table set, row
counts, storage policy, asset replay, market sources, policies, and heads all
pass. The refresh query also succeeds, but `aiomysql.DictCursor.fetchall()`
returns a `list` while `_default_official_audit()` requires an exact `tuple`.

## Design

Normalize the refresh query result to a `tuple` immediately at the database
adapter boundary. Keep every existing strict check unchanged: two expected
sources, exact dictionary columns, exact built-in field types, idle status,
null lease/snapshot/error fields, uniqueness, and source-ID authority.

The unit-test session used by the official-audit tests will return a `list`,
matching the installed `aiomysql` behavior. The existing positive audit test
then serves as the regression test.

## Scope

Modify only:

- `backend/scripts/prepare_product_database.py`
- `backend/tests/unit/test_prepare_product_database_command.py`

Do not change schemas, seed data, lifecycle boundaries, Stage A/B command
behavior, retries, Provider behavior, or public error messages.

## Verification

Use TDD: first change the fake `fetchall()` result to `list` and observe the
positive official-audit test fail, then add the single normalization and observe
it pass. Run the complete command unit file, the Phase 7B focused gate, static
checks, and one separately controlled disposable MySQL positive audit.
