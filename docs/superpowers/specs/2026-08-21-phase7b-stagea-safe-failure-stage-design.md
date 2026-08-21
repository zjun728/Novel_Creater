# Phase 7B Stage A Safe Failure Stage Design

## Goal

Make a failed real Stage A command report the fixed stage at which it stopped,
without exposing raw exceptions or changing any database, backup, receipt, or
cutover behavior.

## Context

The approved real Stage A attempt published a new immutable SQL backup and then
returned only `Product database preparation failed.`. Read-only evidence proved
that the legacy inventory was unchanged, the target and disposable databases
were absent, and no new option-file or temporary-file residue remained. The
failure could only be bounded between final backup publication and successful
retention of the new database. Existing statement history could not narrow that
interval.

## Scope

Modify only:

- `backend/scripts/prepare_product_database.py`
- `backend/tests/unit/test_prepare_product_database_command.py`

Do not modify the readiness service, domain contracts, database lifecycle
boundaries, receipt formats, backup formats, Stage B, Provider behavior, schema,
or command-line arguments.

## Design

`run_cli()` keeps one local `stage` string. Existing CLI dependency wrappers set
it immediately before invoking their operation. The allowed values are:

- `preflight`
- `legacy-inventory-before`
- `backup`
- `restore-drill`
- `legacy-inventory-after`
- `schema-proof`
- `new-database-init`
- `asset-seed`
- `market-seed`
- `readiness-audit`
- `browser-smoke`
- `boundary-commit`
- `receipt-publish`

The wrapper must leave the stage unchanged after a dependency returns. A
validation failure between that return and the next dependency therefore stays
at the dependency that produced the value being validated.

If the preparation service returns successfully, the CLI knows the new-database
boundary committed and advances directly to `receipt-publish`. A cleanup-only
failure after a successful body is reported as `boundary-commit`. A primary
failure keeps its primary stage even when a cleanup failure is also present.

## Safe failure output

Before re-raising the existing fixed command failure, execute mode emits exactly
these additional fixed fields:

```text
outcome=failed
stage=<allowed stage>
cleanup=failed|no-failure-reported
```

`cleanup=failed` is selected only when the already-sanitized exception tree
contains the existing fixed cleanup error. Otherwise the value is
`no-failure-reported`; it does not claim that cleanup ran or succeeded.

The implementation must not emit exception types, exception messages, paths,
hashes, credentials, DSNs, option-file contents, SQL contents, business data,
or identifiers. Unknown exceptions use the current local stage and
`cleanup=no-failure-reported`.

The existing successful execute output, preview output, exit codes, and final
`Product database preparation failed.` line remain unchanged.

## Retry and idempotency boundary

This change adds no retry, resume flag, failure receipt, event journal, observer,
or new idempotency mechanism. Existing protections remain authoritative:

- every approved attempt publishes a unique absent-only backup;
- disposable restore and schema-proof databases are exact run-owned resources;
- a newly created target is retained only after its boundary succeeds;
- a fully ready pre-existing target may follow the existing zero-write path;
- a partial or drifted pre-existing target fails closed;
- every real Stage A execution still requires new explicit approval.

## Error handling

Only existing fixed, public-safe cleanup leaves may affect the cleanup field.
Raw exceptions are never inspected for output content. Primary-first ordering and
flow-control behavior remain unchanged. Stage reporting is diagnostic metadata;
it must not suppress, replace, retry, or otherwise alter an exception.

## Tests

Extend existing command tests rather than creating a new framework:

- parameterize representative dependency failures across every allowed stage;
- verify a fixed cleanup leaf produces `cleanup=failed` while preserving the
  primary stage;
- verify unknown and secret-bearing errors produce only fixed fields;
- verify successful execute output and preview behavior remain unchanged;
- verify no service or domain interface changes are required.

Run the focused command tests, the existing Phase 7B focused and lifecycle gates,
`py_compile`, `git diff --check`, and tracked/index status checks. Tests and
implementation must not execute a real Stage A.

## Completion boundary

Completion means the code and tests can report a safe fixed failure stage. It
does not authorize another Stage A attempt, the browser gate, Stage B, Provider
traffic, legacy deletion, or cleanup of either retained SQL backup or the
pre-existing zero-byte option residue.
