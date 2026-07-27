# OpenAI-Compatible Provider Transport Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-call HTTP client ownership with one gateway/lifespan-owned, cancellation-safe OpenAI-compatible transport used by Planning and Chapter Outline generation.

**Architecture:** `OpenAIJSONTransport` owns one long-lived `httpx.AsyncClient`, lifecycle state, call leases, drain coordination, and strongly held cleanup tasks. Domain gateways keep prompt and strict DTO logic; FastAPI lifespan starts and closes the production Planning gateway without changing public routes or generation-service contracts.

**Tech Stack:** Python 3.12, asyncio, FastAPI lifespan, httpx 0.28.1, Pydantic 2, pytest, pytest-asyncio.

---

## File map

### Create

- `backend/tests/unit/test_openai_json_transport.py`: isolated lifecycle, ownership, cancellation, cleanup, and raw-response bounds.

### Modify

- `backend/gateways/openai_json_transport.py`: lifecycle resource and bounded request implementation.
- `backend/gateways/planning_provider.py`: lifecycle delegation and Planning domain parsing.
- `backend/gateways/chapter_outline_provider.py`: lifecycle delegation and Outline domain parsing.
- `backend/routers/planning.py`: retain the production gateway handle.
- `backend/main.py`: start and close the production gateway in application lifespan.
- `backend/tests/unit/test_planning_gateway.py`: Planning gateway lifecycle and secrecy behavior.
- `backend/tests/unit/test_chapter_outline_gateway.py`: Outline gateway lifecycle and secrecy behavior.
- `backend/tests/unit/test_main_lifespan.py`: production lifecycle ordering and safe shutdown.
- `backend/tests/unit/test_provider_response_secret_scanning.py`: lifecycle-error secret scanning.

No service, repository, database, schema, public route, binding, or frontend file is in scope.

## Task 1: Build the lifecycle-owned transport resource

**Files:**

- Modify: `backend/gateways/openai_json_transport.py`
- Create: `backend/tests/unit/test_openai_json_transport.py`
- Modify: `backend/tests/unit/test_provider_response_secret_scanning.py`

- [ ] **Step 1: Write lifecycle and ownership RED tests**

Require this internal API:

```python
resource = OpenAIJSONTransport(
    transport=borrowed_transport,
    timeout_seconds=120.0,
    response_byte_limit=131_072,
)
await resource.start()
result = await resource.request(
    provider=provider_runtime,
    model_name="deepseek-v4-flash",
    messages=messages,
)
await resource.aclose()
```

Test:

```python
assert resource.state == "open"
assert result.succeeded is True
assert borrowed_transport.close_calls == 0
assert resource.active_calls == 0
assert resource.cleanup_task_count == 0
```

Cover idempotent concurrent `start()`, idempotent concurrent `aclose()`,
`CLOSED -> start()` creating a new client, default-owned client closing once,
borrowed transport never closing, two overlapping calls with independent
responses, `DRAINING` rejecting new calls, and client close beginning only
after both call leases release.

- [ ] **Step 2: Run lifecycle RED**

```powershell
python -m pytest backend/tests/unit/test_openai_json_transport.py -q
```

Expected: fail because the current module exposes only a per-call function and
has no resource lifecycle, state, drain, or lease behavior.

- [ ] **Step 3: Write repeated-cancellation RED tests**

Use close-aware blocking response streams and owned clients. For response and
client close:

```python
task.cancel()
await close_started.wait()
task.cancel()
task.cancel()
assert task.done() is False
close_release.set()
with pytest.raises(asyncio.CancelledError):
    await task
assert close_completed.is_set()
assert close_calls == 1
assert leaked_cleanup_tasks() == ()
```

Also cancel during ordinary finalization after the body has been read. Inject
close failures containing API-key, URL, prompt, Authorization, and raw-response
sentinels. Recursively scan exception causes, contexts, traceback locals,
requests, responses, and decoded values; no sentinel may be recoverable.

- [ ] **Step 4: Implement the state machine and cleanup settlement**

Implement states:

```python
NEW = "new"
STARTING = "starting"
OPEN = "open"
DRAINING = "draining"
CLOSING = "closing"
CLOSED = "closed"
BROKEN = "broken"
```

Admission runs under one lifecycle lock:

```python
if self._state != OPEN:
    return TRANSPORT_FAILURE
self._active_calls += 1
client = self._client
```

Finalization always creates a named cleanup task. Settlement must:

```python
cleanup = asyncio.create_task(close_resource(), name=cleanup_name)
self._cleanup_tasks.add(cleanup)
cancel_count = current_task.cancelling()
while not cleanup.done():
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        current_task.uncancel()
        cancel_count += 1
for _ in range(cancel_count):
    current_task.cancel()
```

The cleanup task catches secret-bearing close errors internally and returns
only a content-free outcome. It strongly owns response/client references until
terminal. The call releases its lease and notifies drain only after response
cleanup is terminal.

The shared request keeps the approved boundaries:

```python
headers["Accept-Encoding"] = "identity"
request_body = {"model": model_name, "messages": messages, "stream": False}
scan_complete_request_before_network(request_body, provider)
async for chunk in response.aiter_raw():
    enforce_cumulative_raw_budget(chunk)
```

Reject non-empty non-identity `Content-Encoding` before iteration.

- [ ] **Step 5: Run Task 1 GREEN**

```powershell
python -m pytest backend/tests/unit/test_openai_json_transport.py backend/tests/unit/test_provider_response_secret_scanning.py -q
```

Expected: all pass; repeated cancellation waits for terminal cleanup, borrowed
transport close count is zero, owned client close count is one, cleanup-task
registry is empty.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- backend/gateways/openai_json_transport.py backend/tests/unit/test_openai_json_transport.py backend/tests/unit/test_provider_response_secret_scanning.py
git commit -m "refactor: own provider transport lifecycle"
```

## Task 2: Attach both domain gateways to the lifecycle resource

**Files:**

- Modify: `backend/gateways/planning_provider.py`
- Modify: `backend/gateways/chapter_outline_provider.py`
- Modify: `backend/tests/unit/test_planning_gateway.py`
- Modify: `backend/tests/unit/test_chapter_outline_gateway.py`

- [ ] **Step 1: Write gateway lifecycle RED tests**

Require both gateways to expose:

```python
await gateway.start()
try:
    value = await gateway.generate(...)
finally:
    await gateway.aclose()
```

Test sequential and concurrent calls use one client lifecycle, borrowed
transport remains open, explicit gateway close drains active calls, and restart
creates a new client. Preserve the existing `generate()` signatures.

- [ ] **Step 2: Write clean-cancellation RED tests**

For Planning and Chapter Outline, cancel while body reading, while response
closing, and repeatedly while cleanup is blocked. Assert:

```python
with pytest.raises(asyncio.CancelledError) as captured:
    await task
assert captured.value.args == ()
assert captured.value.__cause__ is None
assert captured.value.__context__ is None
assert recursive_secret_scan(captured.value) == ()
```

The recursive scan includes every traceback frame, nested `httpx.Request`,
`httpx.Response`, Authorization header, prompt, manifest, raw body, and decoded
mapping.

- [ ] **Step 3: Run gateway RED**

```powershell
python -m pytest backend/tests/unit/test_planning_gateway.py backend/tests/unit/test_chapter_outline_gateway.py -q
```

Expected: fail because gateways do not delegate lifecycle to a persistent
resource and current cancellation cleanup remains per call.

- [ ] **Step 4: Implement lifecycle delegation**

Each gateway owns one `OpenAIJSONTransport` resource:

```python
async def start(self) -> None:
    await self._resource.start()

async def aclose(self) -> None:
    await self._resource.aclose()
```

`generate()` obtains only the content-free shared result. It retains:

- provider/model identity validation;
- prompt construction;
- one strict domain parse;
- exact-node-reference validation;
- fixed domain error categories.

On cancelled result, clear provider, manifest, messages, prompt, decoded result,
and `self` references inside a helper scope, then raise a new empty
`CancelledError` after leaving that scope. No captured HTTPX exception crosses
the resource boundary.

- [ ] **Step 5: Run Task 2 GREEN and adjacent regressions**

```powershell
python -m pytest backend/tests/unit/test_openai_json_transport.py backend/tests/unit/test_planning_gateway.py backend/tests/unit/test_chapter_outline_gateway.py backend/tests/unit/test_chapter_outline_prompt.py backend/tests/unit/test_provider_response_secret_scanning.py -q
```

Expected: all pass; both gateways share lifecycle behavior while preserving
their domain contracts.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- backend/gateways/planning_provider.py backend/gateways/chapter_outline_provider.py backend/tests/unit/test_planning_gateway.py backend/tests/unit/test_chapter_outline_gateway.py
git commit -m "refactor: share provider gateway lifecycle"
```

## Task 3: Wire production lifecycle and verify the package

**Files:**

- Modify: `backend/routers/planning.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/unit/test_main_lifespan.py`
- Test: all Task 6 and Planning provider boundary tests

- [ ] **Step 1: Write application-lifespan RED tests**

Require the Planning router to retain one production gateway handle and the
FastAPI lifespan to call:

```python
await planning_provider_gateway.start()
try:
    yield
finally:
    await planning_provider_gateway.aclose()
```

Test:

- startup occurs before the app accepts Planning generation work;
- shutdown waits for active calls to drain;
- repeated test lifespans restart with a new client;
- startup failure prevents serving;
- provider close failure becomes one fixed secret-free lifecycle failure;
- application failure remains primary if shutdown also fails;
- cancellation during shutdown cannot interrupt client cleanup.

- [ ] **Step 2: Run lifespan RED**

```powershell
python -m pytest backend/tests/unit/test_main_lifespan.py -q
```

Expected: fail because the application lifespan does not own the Planning
gateway resource.

- [ ] **Step 3: Implement explicit production wiring**

Expose one internal Planning router handle:

```python
planning_provider_gateway = PlanningProviderGateway()
```

The route dependency uses that exact handle. Integrate its lifecycle into the
existing FastAPI lifespan without changing public routes or response DTOs.
Shutdown aggregation receives only fixed lifecycle errors; no Provider runtime
or prompt is retained.

The Chapter Outline gateway is not yet registered by a generation service, so
Task 3 must not add a dead production instance.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_openai_json_transport.py backend/tests/unit/test_planning_gateway.py backend/tests/unit/test_chapter_outline_gateway.py backend/tests/unit/test_chapter_outline_prompt.py backend/tests/unit/test_provider_response_secret_scanning.py -q
```

Expected: all pass.

- [ ] **Step 5: Run Task 6 adjacent regression gate**

```powershell
python -m pytest backend/tests/unit/test_planning_prompt.py backend/tests/unit/test_planning_gateway.py backend/tests/unit/test_provider_policy.py backend/tests/unit/test_provider_response_secret_scanning.py backend/tests/unit/test_chapter_outline_domain.py backend/tests/unit/test_chapter_outline_prompt.py backend/tests/unit/test_chapter_outline_gateway.py backend/tests/unit/test_openai_json_transport.py backend/tests/unit/test_main_lifespan.py -q
python -m compileall -q backend
git diff --check
```

Expected: all tests pass, compile succeeds, and no whitespace errors exist.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- backend/routers/planning.py backend/main.py backend/tests/unit/test_main_lifespan.py
git commit -m "refactor: manage provider gateway lifespan"
```

## Final review gate

- [ ] **Step 1: Request independent specification review**

Review the design and this plan against the complete diff from
`a1c1301` through the final Task 3 commit. Fix findings until
Critical/Important/Minor is `0/0/0`.

- [ ] **Step 2: Request independent quality review**

Only after specification review is `0/0/0`, independently re-run:

- multiple-cancel response and client cleanup probes;
- borrowed/default ownership and concurrent drain probes;
- full exception-graph secret scans;
- compressed and raw response budget probes;
- application lifespan start/restart/shutdown probes.

Fix findings until Critical/Important/Minor is `0/0/0`.

- [ ] **Step 3: Run fresh final verification**

```powershell
python -m pytest backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_openai_json_transport.py backend/tests/unit/test_planning_gateway.py backend/tests/unit/test_chapter_outline_gateway.py backend/tests/unit/test_chapter_outline_prompt.py backend/tests/unit/test_provider_response_secret_scanning.py -q
python -m compileall -q backend
git diff --check
git status --short --branch
```

Do not call a real Provider, access the product database, start application
services, merge, or push during this lifecycle refactor.
