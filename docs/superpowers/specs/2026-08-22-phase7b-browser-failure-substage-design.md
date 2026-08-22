# Phase 7B Browser Failure Substage Design

## Goal

When Stage A stops at `browser-smoke`, report one fixed browser lifecycle
substage without exposing raw browser output or changing execution behavior.

## Design

The Node runner renders its existing fixed failure line plus exactly one marker:

```text
PHASE7B_BROWSER_FAILURE_STAGE=<allowed stage>
```

The value is selected only from the runner's existing closed stage set. Unknown
errors fall back to `contract`. No exception message, type, path, environment
value, process output, or identifier is included.

On a non-zero Node exit, the CLI's existing browser-runner wrapper accepts
exactly one marker whose value is in the same closed set and stores it in local
memory before the browser owner raises the unchanged fixed
`readiness smoke failed` error. Missing, duplicate, or invalid markers produce
no captured value.

`run_cli()` stores the callback value locally. A `browser-smoke` failure appends
one fixed field to the existing failure receipt:

```text
browser_stage=<allowed stage|unavailable>
```

Other Stage A failures and successful output are unchanged.

## Boundaries

- No Stage A execution, database access, Provider call, external network call,
  retry, resume mechanism, new file artifact, or raw log forwarding.
- No changes to database lifecycle, backup, receipt, cleanup, or browser test
  scenarios.
- The callback is process-local and diagnostic only; failure propagation stays
  primary-first and uses the existing fixed public errors.

## Verification

Use test-first coverage for safe Node rendering, strict Python marker parsing,
CLI output, secret suppression, invalid-marker fallback, and unchanged success
behavior. Run the focused JavaScript and Python Phase 7B gates plus static checks.
