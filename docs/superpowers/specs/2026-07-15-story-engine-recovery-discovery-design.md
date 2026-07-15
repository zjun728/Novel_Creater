# Story-engine recovery discovery design

**Date:** 2026-07-15
**Status:** Author-approved design
**Scope:** M2E Task 3 recovery UI prerequisite

## Problem

The story-engine service can reconcile a batch only when the caller already knows its batch ID. The formal ProjectView does not currently discover project batches when it loads. A process interruption can therefore leave a Provider batch in `reserved`, `running`, or `outcome_unknown` while the author has no production UI path to inspect or reconcile it.

The M2 recovery browser goal must not solve this with a direct API request, route mock, hard-coded fixture ID, URL parameter, or test-only control. Those approaches would test a shadow workflow instead of the product.

## Decision

Add a read-only, project-scoped recovery-discovery endpoint and render its results in the existing story-engine step. Discovery never changes batch state and never calls a Provider. Reconciliation remains an explicit author action through the existing reconcile command.

## Backend contract

### Route

`GET /api/projects/{pid}/story-engine-batches/recoverable`

The route has no request body, query switches, batch-ID input, or test mode.

### Selection rules

The repository returns at most ten batches that satisfy all of the following:

- the project is active and matches `{pid}`;
- `source_type = 'provider'`;
- the batch belongs to the project's current selected seed revision and hash;
- the batch belongs to the project's current binding revision and hash;
- `status IN ('reserved', 'running', 'outcome_unknown')`.

Rows are ordered by `created_at ASC, id ASC` so the author sees older unresolved work first. A missing active project returns the existing public 404. A project without a selected seed or current binding returns `200 {"items": []}`.

The response is deliberately smaller than the normal batch result:

```json
{
  "items": [
    {
      "id": "public-batch-id",
      "status": "running",
      "publicErrorCode": null,
      "createdAt": 1720000000000,
      "finishedAt": null
    }
  ]
}
```

It must not contain Provider keys, Provider base URLs, request JSON, raw responses, database configuration, corpus paths, idempotency keys, private error text, or novel content.

### Existing reconcile semantics

The existing command remains unchanged:

`POST /api/projects/{pid}/story-engine-batches/{batch_id}/reconcile`

- a stale `reserved` batch becomes `failed/not_started`;
- an expired `running` batch becomes `outcome_unknown`;
- a non-expired `reserved` or `running` batch remains unchanged;
- a terminal batch is returned unchanged;
- reconciliation never invokes the Provider and a normal reconcile does not manufacture a 409.

## Frontend behavior

`creationContractStore.load(projectId)` loads the draft, contract head, and recoverable batch summaries together under the existing latest-request guard. Project switches or stale responses cannot install recovery state for another project.

The story-engine step renders a clearly labelled `待恢复的故事发动机批次` section when the list is non-empty. Each row shows only its public state and exposes one accessible `核对批次` button. The batch ID may be present as bounded public diagnostic text but must not be accepted from user input or the URL.

Clicking a row's button calls the existing reconcile endpoint exactly once:

- `failed/not_started` is shown as resolved and removed from the recoverable collection;
- `outcome_unknown` remains visible and is installed as the current engine batch so the existing warning and explicit “核对后仍要新建批次” acknowledgement continue to apply;
- `reserved` or `running` remains visible with a message that it is not yet eligible for recovery;
- request failure leaves the row visible and presents the existing public error without automatic retry.

Loading, refreshing, returning to the project, or opening a second tab performs discovery GETs only. There is no automatic reconcile, automatic Provider retry, or automatic creation of a replacement batch.

## Concurrency and error boundaries

- Discovery is read-only and does not lock or mutate batches.
- Reconcile retains its existing transaction and compare-and-set behavior.
- Each row disables its action while that row is reconciling; rapid repeat clicks cannot create parallel reconcile commands from one tab.
- A stale discovery response cannot overwrite newer project state.
- A genuine 409 remains a reload-required conflict in the existing store. M2 validates 409 through a real concurrent draft/contract UI write, not by asserting that reconcile returns 409.

## Verification

Implementation follows test-first development:

1. Repository/service/API unit tests prove project/current-seed/current-binding filtering, ordering, maximum count, empty state, 404, and response redaction.
2. Frontend store/component tests prove guarded discovery, explicit-only reconciliation, per-row busy behavior, failed-row removal, `outcome_unknown` retention, and no hidden Provider generation.
3. The formal recovery Playwright spec begins at the real ProjectView, discovers the two disposable-DB preconditions, clicks the two real reconcile controls, observes `failed/not_started` and `outcome_unknown`, refreshes, and confirms the unknown batch remains visible.
4. The browser network allowlist permits only the exact reconcile writes. It contains no Provider-generation or manual-batch creation route.
5. Source-closure gates continue to reject direct request helpers, fetch/axios, product API imports, and route interception inside formal browser specs.

All automated recovery verification uses a random disposable `novel_creator_test_<32hex>` database. It does not read or write the product database and does not call a Provider/model.

## Non-goals

- No compatibility path for old schemas or old test artifacts.
- No automatic recovery, retry, replacement batch, or Provider call.
- No generic batch history screen.
- No schema change or new persistent acknowledgement state.
- No test-only route, fixture ID, URL parameter, or hidden API helper.
