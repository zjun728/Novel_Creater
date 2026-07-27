# OpenAI-Compatible Provider Transport Lifecycle Design

**Date:** 2026-07-27  
**Status:** Approved for implementation planning  
**Parent delivery:** Phase 3C Task 6 — Chapter Outline Provider boundary

## Goal

Give the Planning and Chapter Outline gateways one shared, secret-safe,
bounded OpenAI-compatible transport whose response and connection-pool
resources remain correct under ordinary completion, failures, concurrent
calls, shutdown, and repeated task cancellation.

This design fixes the lifecycle root cause found during Task 6 review. It does
not change public HTTP routes, Provider profiles, model bindings, Planning or
Outline domain schemas, database schema, or generation-service behavior.

## Decision

Use a gateway-owned, lifespan-managed `OpenAIJSONTransport` resource.

- Production gateways own one long-lived `httpx.AsyncClient` and connection
  pool per active application lifecycle.
- A call borrows the client and owns only its response.
- An injected transport is always borrowed. Closing the gateway closes its
  adapter and client but never the caller's transport.
- The application lifespan starts and closes the production Planning gateway.
- The Chapter Outline gateway exposes the same lifecycle API and will be
  connected to the application when its generation service is registered.
- Per-call client construction and per-call transport factories are rejected.
  They duplicate cleanup surfaces and prevent connection-pool reuse.

## Components

### `OpenAIJSONTransport`

The shared resource owns:

- lifecycle state;
- the long-lived `AsyncClient`;
- an optional non-closing adapter around a borrowed transport;
- an active-call counter and drain condition;
- strong references to cleanup tasks until they reach a terminal state.

It provides:

- `start()`;
- `aclose()`;
- an internal call lease used by both gateways;
- one bounded JSON request operation that returns a content-free
  success/failure/cancelled result.

It remains the single owner of:

- endpoint construction and validation;
- complete request-body secret scanning;
- timeout policy;
- `Accept-Encoding: identity`;
- rejection of non-identity response encoding;
- raw streaming and byte-budget enforcement;
- raw-response secret scanning before JSON decoding;
- OpenAI-compatible envelope and content extraction.

### Domain gateways

`PlanningProviderGateway` and `ChapterOutlineProviderGateway` retain only:

- prompt construction;
- Provider/model identity checks;
- lifecycle delegation;
- strict domain DTO parsing;
- exact Planning-node reference validation;
- mapping content-free transport outcomes to fixed public-safe errors.

Their existing `generate()` signatures do not change.

### Application lifespan

The Planning router keeps an explicit production gateway handle. FastAPI
startup calls `start()` before the gateway can receive work. Shutdown:

1. stops admitting new calls;
2. waits for active calls to finish their response cleanup;
3. closes the owned client exactly once;
4. reports only fixed, secret-free lifecycle errors.

Repeated test lifespans may explicitly restart a closed gateway. Restarting
creates a new client; a closed client is never reused.

## Ownership and lifecycle state

Resource state:

```text
NEW -> STARTING -> OPEN
OPEN -> DRAINING -> CLOSING -> CLOSED
START/CLOSE failure -> BROKEN
CLOSED --explicit start--> STARTING
```

Invariants:

- only `OPEN` admits a call;
- admission increments `active_calls` while holding the lifecycle lock;
- `DRAINING` rejects new calls;
- each admitted call holds a strong client reference until its response is
  closed and its lease is released;
- client shutdown begins only when `active_calls == 0`;
- concurrent `start()` and `aclose()` callers share the corresponding
  lifecycle task;
- borrowed transports receive zero close calls from the gateway;
- owned/default clients close once per lifecycle;
- `CLOSED` and `BROKEN` retain no request, response, prompt, credential,
  decoded payload, or secret-bearing exception.

Per-call state:

```text
ADMITTED -> SENDING -> RESPONSE_OWNED -> READING
any exit -> FINALIZING -> SUCCESS | FAILURE | CANCELLED
```

Only the call finalizer may close the response and release the lease.

## Cancellation-safe cleanup

Response and client cleanup never run directly inside the cancelled operation
task.

1. Create a named cleanup task and register a strong reference.
2. Await it with `asyncio.shield()`.
3. If the parent receives another cancellation, consume that cancellation with
   `Task.uncancel()`, count it, and continue shielding the same cleanup task.
4. Do not leave finalization until cleanup reaches a terminal state.
5. Clear all sensitive local references.
6. Restore the observed cancellation count on the current task.
7. Return a content-free cancelled result from the transport layer.
8. The domain gateway clears its own sensitive references and raises one new,
   empty `CancelledError` outside the sensitive capture scope.

Response and client cleanup are correctness-first and have no foreground
timeout. A custom borrowed transport must guarantee that `aclose()` eventually
returns. If a future shutdown SLA requires bounded foreground waiting, the
application must transfer strong ownership to a lifecycle cleanup ledger; it
must not cancel an in-progress HTTPX close.

Cleanup failures are converted inside the cleanup task to fixed, content-free
outcomes. Secret-bearing close exceptions never cross a gateway or lifespan
boundary.

## Security and bounded data flow

Before network access:

1. construct the complete request body, including `model`;
2. canonical-serialize it;
3. scan both encoded and decoded values for API key, base URL, DSN, prompt
   runtime secrets, and forbidden internal material;
4. only then create the request.

Response handling:

- request `Accept-Encoding: identity`;
- reject any non-empty, non-identity `Content-Encoding` before iteration;
- stream with `aiter_raw()`;
- reject declared or cumulative raw bytes above the configured budget;
- scan raw bytes before JSON decoding;
- parse one OpenAI-compatible envelope;
- perform one strict domain parse in the gateway.

No raw Provider response, prompt, Authorization header, manifest, request body,
or decoded intermediate is logged or persisted.

## Error behavior

- Cancellation remains cancellation and is never mapped to a Provider failure.
- Transport, HTTP, response-budget, response-security, JSON, envelope, and
  domain failures map to their existing fixed safe categories.
- Safe errors have no sensitive cause or context.
- Full exception-graph and traceback-local inspection must not recover API
  keys, base URLs, Authorization, prompts, raw responses, or decoded payloads.
- Lifecycle failures use fixed safe errors suitable for shutdown aggregation.

## Files in implementation scope

Production:

- `backend/gateways/openai_json_transport.py`
- `backend/gateways/planning_provider.py`
- `backend/gateways/chapter_outline_provider.py`
- `backend/routers/planning.py`
- `backend/main.py`

Tests:

- new `backend/tests/unit/test_openai_json_transport.py`
- `backend/tests/unit/test_planning_gateway.py`
- `backend/tests/unit/test_chapter_outline_gateway.py`
- `backend/tests/unit/test_main_lifespan.py`
- existing secret-scanning tests when needed

No service, repository, database, schema, public route, Provider binding, or
frontend file is in scope.

## TDD acceptance matrix

The implementation must demonstrate:

1. response cleanup survives two and multiple cancellations;
2. cancellation during ordinary response finalization also waits for cleanup;
3. shutdown cleanup survives repeated cancellation;
4. cleanup failures retain no secret-bearing exception graph;
5. borrowed transports work sequentially and concurrently and are never
   closed;
6. default/owned clients are created once and closed once per lifecycle;
7. shutdown drains active calls and rejects new calls;
8. start/close are idempotent and explicit restart creates a new client;
9. start/close races have one authoritative terminal state;
10. complete-body scanning blocks model/base-URL collisions before transport;
11. gzip, br, oversized declared bodies, and oversized streamed raw bodies fail
    before unsafe decoding;
12. Planning and Chapter Outline retain their existing success, failure,
    cancellation, strict-parse, and exact-reference behavior;
13. FastAPI lifespan starts and closes the production Planning gateway;
14. no cleanup task, response stream, client, owned transport, port, process,
    or secret-bearing exception remains after each test.

## Completion boundary

This refactor is complete only when the shared transport lifecycle and both
gateway integrations pass independent specification and quality reviews at
Critical/Important/Minor `0/0/0`.

It does not grant real Provider readiness and does not call a real Provider.
