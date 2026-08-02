# Phase 4B2 Streaming, Reconnect, and Cancel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the accepted persistent `generate_new` operation with genuine provider streaming, bounded durable partial output, automatic browser reconnect, lease heartbeats, and idempotent cancellation that preserves the latest visible non-empty partial as the next editable WorkingDraft revision.

**Architecture:** The bound provider profile freezes `stream` and `supports_streaming` into the operation authority. A supervised application task consumes either a strict OpenAI-compatible SSE stream or the existing non-stream result outside every database transaction; short fenced transactions persist delta batches, heartbeats, and one terminal winner. The browser uses owner-scoped status plus paginated events over one-second polling, renders partial output in the existing native readonly textarea without touching autosave state, and reloads the authoritative WorkingDraft only after completion or cancellation-with-result.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, asyncio/httpx, aiomysql/MySQL 8, pytest/pytest-asyncio, Vue 3/Pinia, native fetch, Node test runner, Vite, Playwright.

---

## Scope and immutable boundaries

This plan implements only Phase4B2 `generate_new` streaming/reconnect/cancel. It does not implement full or selection rewrite, polish, expansion, compression, undo/recovery browsing, Candidate comparison, Phase4C layout, Phase4D full browser acceptance, real-provider quality, product-database readiness, or any automatic DeepSeek call.

The following decisions are fixed:

- WorkingDraft remains mutable, auto-saved, and recoverable across refresh. Candidate remains an explicit author checkpoint.
- Streaming partial text is a display buffer, never an autosave edit.
- Streaming is selected only when the frozen provider authority has both `stream` and `supports_streaming` true. A selected stream never silently falls back to a second non-stream provider call.
- Cancellation commits only the latest persisted partial snapshot. A task-private unflushed buffer is discarded when cancellation wins.
- Completion, cancellation, provider/validation failure, and expiry use one operation/session/fencing/lease ownership fence. Exactly one terminal transition commits.
- Status and event reads are owner-scoped and never call or resume a provider.
- No logs, errors, diagnostics, screenshots, reports, or browser artifacts contain prompts, provider bodies, generated prose, credentials, base URLs, DSNs, or product-database material.
- Automated tests use only disposable `novel_creator_test_*` databases and an injected loopback fake provider.

## File structure and ownership

New focused modules:

- `backend/gateways/openai_sse.py`: incremental UTF-8 SSE framing and closed OpenAI-compatible delta projection.
- `backend/runtime/draft_operation_tasks.py`: application-scoped task/cancel registry.
- `backend/services/draft_operation_execution.py`: provider wait, batching, heartbeat timing, and callback sequencing; no SQL.
- `frontend/src/application/writer/draftOperationTimeline.js`: pure snapshot/event cursor and partial calibration.
- `frontend/src/utils/sha256Text.js`: asynchronous exact UTF-8 SHA-256 used only for bounded public partial calibration.
- Focused tests for each new module.
- `frontend/e2e/run-phase4b2.mjs`, `playwright.phase4b2.config.ts`, and `phase4b2-draft-streaming.spec.ts`: owned fake-provider browser gate.

Existing files retain their current responsibility: schema owns constraints; repository owns SQL only; service owns reserve/fenced settlement; router owns strict HTTP and public DTOs; main owns lifecycle order; frontend client/store own transport authority; coordinator owns reconnect/action fencing; controller keeps autosave separate; editor/view own native textarea presentation.

One implementer owns each production file for the whole plan. One Sol High implementer owns all Task 4 edits to `backend/services/draft_operations.py` and `backend/repositories/chapter_sessions.py`; review fixes return to that same implementer. Specification and quality reviewers are different Sol High agents and run serially.

## Fixed constants

```text
lease duration                 30,000 ms
heartbeat cadence             10,000 ms
delta flush threshold         256 Unicode scalars or 1,000 ms
provider absolute deadline    1,200,000 ms
wire response ceiling         1 MiB
partial output ceiling        100,000 Unicode scalars
event ceiling                 2,048 per operation
event page size               100
browser poll cadence          1,000 ms
```

Persistent statuses are `starting|running|completed|failed|cancelled|expired`. Public events are `started|delta|heartbeat|completed|failed|cancelled`. `cancelling` and `reconnecting` are frontend-only.

## Task 1: Reconcile the governing design and extend the exact schema

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-phase-4-writer-loop-design.md`
- Modify: `backend/schema/40_drafts.sql`
- Modify: `backend/schema_version.py`
- Modify: `CURRENT_PROJECT_STATE.md`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_initialize_database.py`
- Modify: `backend/tests/integration/test_schema_bootstrap.py`

- [ ] **Step 1: Write schema and governing-document RED tests**

Require `writer-core-v1.9.0`, the five streaming columns, cancelled correlations, expanded events, sequence ceiling, unchanged table count 87, and the new master-design cancellation rule.

```python
assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.9.0"
for fragment in (
    "partial_output_text longtext not null",
    "partial_output_hash char(64) not null",
    "partial_output_scalars int not null",
    "heartbeat_at bigint not null",
    "cancelled_at bigint null",
    "status in ('starting','running','completed','failed','cancelled','expired')",
    "event_type in ('started','delta','heartbeat','completed','failed','cancelled')",
    "check (sequence_num between 1 and 2048)",
):
    assert fragment in normalized_draft_schema
```

- [ ] **Step 2: Run schema RED**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q
```

Expected: FAIL only for v1.9.0 and missing B2 contracts.

- [ ] **Step 3: Add the minimal exact schema**

Add:

```sql
partial_output_text LONGTEXT NOT NULL,
partial_output_hash CHAR(64) NOT NULL,
partial_output_scalars INT NOT NULL,
heartbeat_at BIGINT NOT NULL,
cancelled_at BIGINT NULL,
CHECK (partial_output_scalars BETWEEN 0 AND 100000),
CHECK (heartbeat_at >= created_at),
CHECK (
  (status = 'cancelled' AND cancelled_at IS NOT NULL)
  OR (status <> 'cancelled' AND cancelled_at IS NULL)
)
```

A cancelled attempt has no failure code and result revision/hash both present or both null. Active statuses retain `active_slot=1` and null terminal fields. Expand events exactly:

```sql
CHECK (sequence_num BETWEEN 1 AND 2048),
CHECK (event_type IN ('started','delta','heartbeat','completed','failed','cancelled')),
CHECK (
  (event_type IN ('started','heartbeat') AND closed_payload_json IS NULL)
  OR (event_type IN ('delta','completed','failed','cancelled')
      AND closed_payload_json IS NOT NULL)
)
```

Set v1.9.0. Update master Phase4 sections 4 and 7.4: cancel commits the latest safe persisted non-empty partial; empty partial, failure, and expiry preserve the prior WorkingDraft. Mark B2 in progress, not accepted. Existing databases require explicit reinitialization; do not add runtime migration or touch a product DB.

- [ ] **Step 4: Run schema GREEN and disposable-MySQL bootstrap**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q
python -m pytest backend/tests/integration/test_schema_bootstrap.py -m mysql -q --basetemp .codex-test-artifacts/pytest/integration
```

Expected: PASS; remaining test databases 0.

- [ ] **Step 5: Commit**

```powershell
git add docs/superpowers/specs/2026-08-01-phase-4-writer-loop-design.md backend/schema/40_drafts.sql backend/schema_version.py CURRENT_PROJECT_STATE.md backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/integration/test_schema_bootstrap.py
git diff --cached --check
git commit -m "feat: persist streaming draft state"
```

## Task 2: Implement the strict streaming provider boundary

**Files:**
- Create: `backend/gateways/openai_sse.py`
- Modify: `backend/gateways/chapter_draft_provider.py`
- Create: `backend/tests/unit/test_openai_sse.py`
- Modify: `backend/tests/unit/test_chapter_draft_provider_gateway.py`

- [ ] **Step 1: Write SSE/gateway RED tests**

Cover byte splits inside UTF-8 and CRLF, multiline `data:`, ignored comments, role/finish frames, exactly one choice index 0, text deltas, valid terminal `[DONE]`, data after DONE, unknown SSE fields, malformed/recursive/oversized JSON, non-text content, media type, listed/repeated/compressed encoding, declared/raw overflow, absolute timeout, response close on cancel, and fixed errors with no body/cause.

```python
parser = OpenAITextSSEParser()
assert parser.feed(b'data: {"choices":[{"index":0,"delta":{"content":"\\xe4') == ()
assert parser.feed(b'\\xbd\\xa0"}}]}\\n\\n') == ("你",)
assert parser.feed(b"data: [DONE]\\n\\n") == ()
parser.finish()
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_openai_sse.py backend/tests/unit/test_chapter_draft_provider_gateway.py -q
```

- [ ] **Step 3: Implement the bounded interfaces**

```python
class OpenAITextSSEParser:
    def feed(self, chunk: bytes) -> tuple[str, ...]: ...
    def finish(self) -> None: ...

class ChapterDraftProviderGateway:
    async def generate(...) -> str: ...
    async def stream(
        self, *, provider: Mapping[str, object],
        messages: Sequence[Mapping[str, str]],
        generation_config: Mapping[str, object],
    ) -> AsyncIterator[str]: ...
```

`stream` sends `stream: true`, `Accept: text/event-stream` and `Accept-Encoding: identity`; requires the SSE media type; counts `aiter_raw()` bytes before parsing; applies one 1,200-second deadline to the full stream; and maps all remote/framing failures to safe existing gateway errors without chaining. Keep `generate` for frozen non-stream profiles. No runtime fallback.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_openai_sse.py backend/tests/unit/test_chapter_draft_provider_gateway.py -q
git add backend/gateways/openai_sse.py backend/gateways/chapter_draft_provider.py backend/tests/unit/test_openai_sse.py backend/tests/unit/test_chapter_draft_provider_gateway.py
git diff --cached --check
git commit -m "feat: stream chapter draft provider output"
```

## Task 3: Add the bounded application task registry

**Files:**
- Create: `backend/runtime/draft_operation_tasks.py`
- Create: `backend/tests/unit/test_draft_operation_tasks.py`

- [ ] **Step 1: Write registry RED tests**

Prove restart, unique registration, done removal, exception consumption without logging, cooperative signal plus cancellation, missing cancel idempotency, and bounded shutdown cleanup.

```python
registry = DraftOperationTaskRegistry()
await registry.start()
signal = registry.launch(OPERATION_ID, worker)
assert not signal.is_set()
assert registry.cancel(OPERATION_ID)
await registry.aclose()
assert registry.size == 0
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_draft_operation_tasks.py -q
```

- [ ] **Step 3: Implement**

```python
class DraftOperationTaskRegistry:
    async def start(self) -> None: ...
    def launch(
        self,
        operation_id: str,
        worker: Callable[[asyncio.Event], Awaitable[None]],
    ) -> asyncio.Event: ...
    def cancel(self, operation_id: str) -> bool: ...
    async def aclose(self) -> None: ...
    @property
    def size(self) -> int: ...
```

Entries contain only operation ID, task handle, and event. `cancel` sets the event then cancels the task. `aclose` stops launches, cancels/gathers, consumes exceptions, clears entries, and never writes business state.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_draft_operation_tasks.py -q
git add backend/runtime/draft_operation_tasks.py backend/tests/unit/test_draft_operation_tasks.py
git diff --cached --check
git commit -m "feat: supervise draft operation tasks"
```

## Task 4: Implement the fenced streaming/heartbeat/cancel state machine

**Files:**
- Create: `backend/services/draft_operation_execution.py`
- Modify: `backend/services/draft_operations.py`
- Modify: `backend/repositories/chapter_sessions.py`
- Modify: `backend/tests/unit/test_draft_operation_service.py`
- Modify: `backend/tests/unit/test_chapter_session_repository.py`
- Create: `backend/tests/unit/test_draft_operation_execution.py`

- [ ] **Step 1: Write state-machine RED tests**

Cover immediate running return; one launch only for new reserve; replay/no relaunch including launch failure; frozen capability; 256-scalar/one-second flush; cumulative split-secret scan; non-stream heartbeat without delta; ten-second renewal; 30-second lease; dynamic sequences; terminal reservation at event 2048; content bound; completion/cancel/failure/expiry races; persisted-only cancel; empty/repeated cancel; late fence rejection; and `CancelledError` not becoming failure.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_draft_operation_execution.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py -q
```

- [ ] **Step 3: Implement the SQL-free execution loop**

```python
DELTA_FLUSH_SCALARS = 256
DELTA_FLUSH_MS = 1_000
HEARTBEAT_MS = 10_000
DRAFT_OPERATION_LEASE_MS = 30_000
MAX_DRAFT_OPERATION_EVENTS = 2_048

class DraftOperationExecution:
    async def run_stream(self, *, stream, on_delta, on_heartbeat, on_complete): ...
    async def run_non_stream(self, *, generate, on_heartbeat, on_complete): ...
```

Provider/timer waits are outside transactions. Cumulative output is validated without trimming and scanned before every persisted delta. Private buffer is discarded on cancellation. Non-stream emits heartbeat/final only.

- [ ] **Step 4: Add exact repository primitives**

Provider resolution selects `p.stream,p.supports_streaming`. Add:

```python
async def append_draft_operation_delta(self, session, row: dict) -> bool: ...
async def append_draft_operation_heartbeat(self, session, row: dict) -> bool: ...
async def cancel_draft_operation(self, session, row: dict) -> bool: ...
```

Every write requires exact project/Session/operation/fence, `running`, active slot/Session owner, unexpired lease, previous partial hash and event sequence. Delta updates partial/hash/scalars, `heartbeat_at`, lease, timestamp, and event atomically. Heartbeat updates `heartbeat_at` and lease plus payload-free event atomically. Nonterminal writes stop at sequence 2047 so terminal failure can occupy 2048.

- [ ] **Step 5: Refactor the service public surface**

```python
@dataclass(frozen=True)
class DraftOperationResult:
    # existing identity/model/result fields
    partial_output: str
    partial_output_hash: str
    partial_output_scalars: int

class DraftOperationService:
    async def start(self, command: StartDraftOperation) -> DraftOperationResult: ...
    async def read(self, project_id: str, session_id: str, operation_id: str) -> DraftOperationResult: ...
    async def cancel(self, project_id: str, session_id: str, operation_id: str) -> DraftOperationResult: ...
```

Reserve commits empty SHA-256/scalar state and 30-second lease before launch. Replay never launches. A registry launch failure returns fixed unavailable and the durable attempt expires; replay still never launches. `read` may expire elapsed leases but never starts work. Expiry has no public event and leaves sequence unchanged.

`cancel` locks the latest persisted snapshot and terminal fence. After commit it signals the registry. Non-empty normalized partial writes recovery before/after, WorkingDraft CAS, cancelled event/result/state/ownership in one transaction. Empty partial writes only event/state/ownership. After restart, cancel trusts the already scanned persisted partial and must not fetch mutable provider secrets. Terminal rows replay unchanged.

Freeze `stream` and `supports_streaming` in the private authority hash. Validate all stored new columns, dynamic sequences 1..2048, hash/scalar calibration, cancelled correlations, and public partial bound.

- [ ] **Step 6: Run GREEN, self-review transaction waits, and commit**

```powershell
python -m pytest backend/tests/unit/test_draft_operation_execution.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py backend/tests/unit/test_draft_operation_tasks.py backend/tests/unit/test_chapter_draft_provider_gateway.py backend/tests/unit/test_openai_sse.py -q
git add backend/services/draft_operation_execution.py backend/services/draft_operations.py backend/repositories/chapter_sessions.py backend/tests/unit/test_draft_operation_execution.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py
git diff --cached --check
git commit -m "feat: persist streamed draft progress"
```

## Task 5: Expose closed status/events/cancel and active workspace authority

**Files:**
- Modify: `backend/domain/drafts.py`
- Modify: `backend/services/chapter_sessions.py`
- Modify: `backend/routers/chapter_sessions.py`
- Modify: `backend/tests/unit/test_chapter_session_service.py`
- Modify: `backend/tests/api/test_chapter_session_routes.py`
- Modify: `backend/tests/api/test_draft_operation_routes.py`
- Modify: `backend/tests/api/test_route_inventory.py`

- [ ] **Step 1: Write API/workspace RED tests**

Require top-level `activeDraftOperationId`; partial fields; cancelled; 100-item pagination envelope; closed event payloads; status expiry; owner scoping; cancel with absent body or exact empty object; fixed errors; route inventory; and absence of task/lease/fence/prompt/provider body/secret/base URL/DSN.

```python
assert response.json() == {
    "operationId": OPERATION_ID,
    "events": expected_page,
    "lastEventSequence": 137,
    "nextAfter": 100,
    "hasMore": True,
}
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py backend/tests/api/test_route_inventory.py backend/tests/unit/test_chapter_session_service.py -q
```

- [ ] **Step 3: Implement closed projections and service-backed reads**

Add `active_draft_operation_id: str | None` to `ChapterWorkspace` and expose only top-level `activeDraftOperationId`. Extend operation with `partialOutput`, hash, and scalars. Validate continuous pages per event type. `nextAfter` is last returned sequence or request cursor; `hasMore` compares with operation last sequence. Route status/events through service read so expiry is shared.

Create one module-global `DraftOperationTaskRegistry`, inject that exact instance into the module-global `DraftOperationService`, and export the registry for lifespan wiring. Tests override the service dependency and never create a second production registry.

- [ ] **Step 4: Add strict cancel**

```python
@router.post(
    "/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}/cancel"
)
async def cancel_draft_operation(...):
    await _read_empty_cancel_body(request)
    result = await service.cancel(pid, session_id, operation_id)
    return _public_draft_operation(_require_closed_draft_operation(...))
```

Accept zero bytes without content type or bounded exact JSON object with empty keys and exact JSON media type. Reject fields, duplicate/non-object/oversize/wrong or duplicate media type, and noncanonical owner before service access.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py backend/tests/api/test_route_inventory.py backend/tests/unit/test_chapter_session_service.py -q
git add backend/domain/drafts.py backend/services/chapter_sessions.py backend/routers/chapter_sessions.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_route_inventory.py
git diff --cached --check
git commit -m "feat: expose reconnectable draft operations"
```

## Task 6: Bind the registry to application lifespan

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/unit/test_main_lifespan.py`

- [ ] **Step 1: Write lifecycle RED tests**

Prove registry start after schema verification and before serving; shutdown drains draft tasks before provider gateways/pool; errors remain primary and sanitized; repeated outer cancellation cannot interrupt cleanup; second lifespan starts clean.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_main_lifespan.py -q
```

- [ ] **Step 3: Wire one shared registry**

Use the registry exported by `backend.routers.chapter_sessions`; do not create another. Start before yield. In finally, settle one named `aclose()` task through the existing cancellation-resistant helper before provider gateways, scheduler, and pool. Shutdown never creates business `failed` or `cancelled` state.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_draft_operation_tasks.py -q
git add backend/main.py backend/tests/unit/test_main_lifespan.py
git diff --cached --check
git commit -m "feat: drain draft tasks on shutdown"
```

## Task 7: Extend frontend transport and store boundaries

**Files:**
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/chapterSessionStore.js`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/chapterSessionStore.test.mjs`

- [ ] **Step 1: Write RED tests**

Require exact partial/status/event/pagination fields, top-level active operation ID, cancel POST without body, recursive extra/sensitive-field rejection, scalar/hash bounds, and no automatic create during workspace reload.

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs
```

- [ ] **Step 3: Implement**

Add `cancelDraftOperation(projectId, sessionId, operationId)` to client/store. Extend closed operation/event allowlists only with approved fields. Normalize active ID as null or canonical UUID. The store remains stateless for provider tasks.

- [ ] **Step 4: Run GREEN and commit**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs
git add frontend/src/api/db/client.js frontend/src/stores/chapterSessionStore.js frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs
git diff --cached --check
git commit -m "feat: expose draft stream transport"
```

## Task 8: Implement reconnect/event calibration/preview/cancel coordination

**Files:**
- Create: `frontend/src/utils/sha256Text.js`
- Create: `frontend/src/application/writer/draftOperationTimeline.js`
- Modify: `frontend/src/application/writer/draftOperationCoordinator.js`
- Modify: `frontend/src/application/writer/chapterWriterController.js`
- Create: `frontend/tests/unit/sha256Text.test.mjs`
- Create: `frontend/tests/unit/draftOperationTimeline.test.mjs`
- Modify: `frontend/tests/unit/draftOperationCoordinator.test.mjs`
- Modify: `frontend/tests/unit/chapterWriterController.test.mjs`

- [ ] **Step 1: Write RED tests**

Cover fresh snapshot calibration without replay; retained suffix paging; gap/hash/scalar failure; drain pages before one-second wait; refresh resume with no key/POST; same-key unknown recovery; preview never edits autosave; terminal reload rules; cancel/repeated cancel; reset/dispose/navigation late fences; heartbeat without preview mutation.

```js
await timeline.calibrate(operation({ partialOutput: '甲', lastEventSequence: 8 }))
assert.equal(timeline.preview, '甲')
assert.equal(timeline.cursor, 8)
await timeline.applyPage(events({ after: 8, text: '乙', sequence: 9 }))
assert.equal(timeline.preview, '甲乙')
```

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/sha256Text.test.mjs frontend/tests/unit/draftOperationTimeline.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
```

- [ ] **Step 3: Implement exact asynchronous UTF-8 hashing and the pure timeline**

`sha256Text` uses `TextEncoder` and `crypto.subtle.digest('SHA-256', bytes)`, returns 64 lowercase hex characters, rejects malformed Unicode and missing Web Crypto with a fixed local `TypeError`, and never logs the input.

```js
export function createDraftOperationTimeline({ hashText = sha256Text } = {}) {
  return Object.freeze({
    async calibrate(operation) {},
    async applyPage(page) {},
    reset() {},
    get preview() {},
    get cursor() {},
  })
}
```

Use Unicode scalar counts and SHA-256 with exact UTF-8, no normalization. A cursor ahead of status recalibrates from the authoritative snapshot.

- [ ] **Step 4: Extend coordinator/controller**

Coordinator constructor adds `listEvents` and `cancelOperation`. Add:

```js
resume(operationId)    // GET only; no POST/key
cancelActive()         // cancel current operation
get preview()
get reconnecting()
get cancelling()
```

For a fresh resume, status calibrates the complete partial and cursor directly, so old deltas are not replayed. For an already retained cursor, each cycle drains every event page after the cursor without sleeping, then reads status to trigger/catch expiry and verify exact text/hash/scalars. If status is ahead because a delta committed during the read, drain again to that sequence; if it is behind, fail closed. Sleep one second only after cursor and status agree. Completed or cancelled-with-result reloads once; failed/expired/cancelled-empty returns null. Preserve B1 unknown POST replay.

Controller exposes `editorText`, `streamingPreview`, `cancelGeneration`, and `resumeDraftOperation`. Preview is selected only while the operation owns the action lock and never calls `autosave.edit`. Resume does not flush/create a key. Cancel acts inside the active generation lock.

- [ ] **Step 5: Run GREEN and commit**

```powershell
node --test frontend/tests/unit/sha256Text.test.mjs frontend/tests/unit/draftOperationTimeline.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
git add frontend/src/utils/sha256Text.js frontend/src/application/writer/draftOperationTimeline.js frontend/src/application/writer/draftOperationCoordinator.js frontend/src/application/writer/chapterWriterController.js frontend/tests/unit/sha256Text.test.mjs frontend/tests/unit/draftOperationTimeline.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
git diff --cached --check
git commit -m "feat: reconnect streamed draft previews"
```

## Task 9: Render streaming in the existing plain-text editor

**Files:**
- Modify: `frontend/src/components/writer/PlainTextDraftEditor.vue`
- Modify: `frontend/src/views/ChapterWriterView.vue`
- Create: `frontend/tests/unit/plainTextDraftEditor.test.mjs`
- Modify: `frontend/tests/unit/chapterWriterView.test.mjs`

- [ ] **Step 1: Write RED tests**

Prove native readonly, focus/selection/copy/scroll, blocked input/paste/retry/candidate/navigation, preview binding, scroll-up follow suspension and `回到最新`, nonblocking route resume, only cancel while active, and exact fixed messages.

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/plainTextDraftEditor.test.mjs frontend/tests/unit/chapterWriterView.test.mjs
```

- [ ] **Step 3: Implement editor auto-follow**

Add `streaming: Boolean`. While streaming, watch `modelValue` and after `nextTick` scroll only if local `autoFollow`. More than 24 px from bottom disables follow and shows accessible `回到最新`. Button restores bottom/follow. Reset on streaming boundary. Keep textarea, not contenteditable.

- [ ] **Step 4: Wire view without touching autosave**

Bind `controller.editorText.value` and `controller.streamingPreview.value`. After `autosave.reset(workspace)`, start resume for non-null active ID without awaiting terminal completion; attach fixed safe catch. Add `停止生成`; disable every other command/navigation.

Use only:

```text
正在生成
正在恢复连接
正在取消
已停止，已保留生成内容
已停止，正文未改变
生成完成
生成失败
生成已失效
```

- [ ] **Step 5: Run GREEN and commit**

```powershell
node --test frontend/tests/unit/plainTextDraftEditor.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/writerCoreApi.test.mjs
git add frontend/src/components/writer/PlainTextDraftEditor.vue frontend/src/views/ChapterWriterView.vue frontend/tests/unit/plainTextDraftEditor.test.mjs frontend/tests/unit/chapterWriterView.test.mjs
git diff --cached --check
git commit -m "feat: show cancellable draft streaming"
```

## Task 10: Prove transactional behavior with disposable MySQL

**Files:**
- Create: `backend/tests/integration/test_draft_operation_streaming_integrity.py`

- [ ] **Step 1: Write MySQL RED tests**

Prove atomic delta snapshot/hash/scalars/event/lease; matching-fence heartbeat; cancel/completion one winner; non-empty cancel one revision and recovery pair; empty/repeated cancel no revision; restart expiry and late-write fence; provider/timer waits leave a second connection readable.

- [ ] **Step 2: Run RED serially**

```powershell
python -m pytest backend/tests/integration/test_draft_operation_streaming_integrity.py -m mysql -q --basetemp .codex-test-artifacts/pytest/integration
```

- [ ] **Step 3: Return failures to the Task 4 implementer**

A new agent must not patch Task 4 production files. Report only safe state/method/status evidence, run the single failing test, then the whole file once.

- [ ] **Step 4: Commit integration evidence**

```powershell
git add backend/tests/integration/test_draft_operation_streaming_integrity.py
git diff --cached --check
git commit -m "test: prove streaming draft transactions"
```

## Task 11: Add the owned fake-provider browser gate

**Files:**
- Create: `backend/scripts/prepare_phase4b2_browser_db.py`
- Create: `frontend/e2e/run-phase4b2.mjs`
- Create: `frontend/e2e/playwright.phase4b2.config.ts`
- Create: `frontend/e2e/phase4b2-draft-streaming.spec.ts`
- Create: `scripts/tests/phase4B2BrowserContract.test.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: `package.json`
- Modify: `frontend/package.json`

- [ ] **Step 1: Write runner/source RED tests**

Require formal `browser-phase4b2` files and imports of `product-runner`, deny proxy, DB residue, and safe diagnostics. Require owned processes/ports/temp/artifacts/database, loopback fake only, Vite cache cleanup, no recursive runner. Forbid `page.request`, `page.route`, direct fetch/axios, and `page.evaluate` product bypass.

- [ ] **Step 2: Run RED**

```powershell
node --test scripts/tests/phase4B2BrowserContract.test.mjs scripts/tests/browser-runner.test.mjs scripts/tests/phase3BrowserSupport.test.mjs
```

- [ ] **Step 3: Build exact disposable fixture/fake provider**

Fixture validates `novel_creator_test_*` and creates one real project with confirmed immutable basis, Planning, StoryBlock, confirmed Outline, Session, WorkingDraft, and loopback writing binding. It never accesses product DB.

Fake server accepts only loopback `POST /chat/completions`, consumes bounded request without logging it, validates streaming internally, and records only scenario, method/path/status, connection/call count, terminal disposition. No payload/prose.

- [ ] **Step 4: Implement four serial UI-only scenarios**

```text
@complete       readonly partial -> completed editable WorkingDraft
@reconnect      reload restores partial without duplication/provider recall
@cancel-output  stop preserves latest visible partial and survives reload
@cancel-empty   stop before first delta leaves original WorkingDraft
```

Also prove no Candidate, external origin, console/request failure, or unsafe artifact. Playwright uses visible UI and safe method/path/status observation only.

- [ ] **Step 5: Wire/run support GREEN**

Add `test:browser:phase4b2` to both package files and `browser-phase4b2` to suite names, MySQL suites, commands, and formal inventory.

```powershell
node --test scripts/tests/phase4B2BrowserContract.test.mjs scripts/tests/browser-runner.test.mjs scripts/tests/phase3BrowserSupport.test.mjs
```

- [ ] **Step 6: Run browser once, serially**

```powershell
npm run test:browser:phase4b2
```

Expected: 4/4; one fake call per started scenario; real provider 0; product DB reads/writes 0/0; DB/process/port/temp/artifact/Vite residue 0.

- [ ] **Step 7: Commit**

```powershell
git add backend/scripts/prepare_phase4b2_browser_db.py frontend/e2e/run-phase4b2.mjs frontend/e2e/playwright.phase4b2.config.ts frontend/e2e/phase4b2-draft-streaming.spec.ts scripts/tests/phase4B2BrowserContract.test.mjs scripts/run-tests.mjs package.json frontend/package.json
git diff --cached --check
git commit -m "test: accept streamed draft recovery"
```

## Task 12: Serial reviews, fresh gates, acceptance, and residue audit

**Files:**
- Create: `docs/acceptance/2026-08-02-phase-4b2-streaming-reconnect-cancel.md`
- Modify: `CURRENT_PROJECT_STATE.md`
- Modify: this plan only after fresh evidence exists

- [ ] **Step 1: Implementer/controller diff review**

Each implementer checks owned files for scope, transaction waits, closed DTOs, leakage, and late fences. Controller reviews the full diff from `8ff40f0` and runs `git diff --check`.

- [ ] **Step 2: Specification review to 0/0/0**

One Sol High spec reviewer compares approved design/plan/diff. Fixes return to original owners; repeat until Critical/Important/Minor = 0/0/0.

- [ ] **Step 3: Quality review to 0/0/0**

Only after spec is clean, a different Sol High reviewer audits races, SQL fences, parser bounds, lifecycle cleanup, frontend isolation, browser safety, and tests. Fix with original owners; repeat to 0/0/0.

- [ ] **Step 4: Controller fresh unit/API**

```powershell
npm test
```

Expected: exit 0; retain counts only.

- [ ] **Step 5: Controller fresh disposable MySQL**

```powershell
npm run test:integration
```

Expected: exit 0; created=cleaned; remaining test DB 0.

- [ ] **Step 6: Controller fresh build**

```powershell
npm run build
```

- [ ] **Step 7: Controller fresh browser**

```powershell
npm run test:browser:phase4b2
```

Expected: 4/4 and zero residue. On failure use systematic-debugging, form one hypothesis, and run one smallest scenario; never loop blindly.

- [ ] **Step 8: Audit control plane and owned residue**

Check active agents, completed roles, branch/HEAD/status, proven-owned Node/Python tasks, known ports, owned temp/artifacts, Vite `deps_temp`, and only `novel_creator_test_*` names. Do not inspect product DB or kill normal MySQL.

- [ ] **Step 9: Write bounded acceptance and commit**

The exact claim is:

```text
Phase4B2 generate_new streaming, automatic reconnect, and cancellation are
accepted with an injected fake streaming provider. Rewrite/local tools, undo,
full Phase4B, real-provider quality, and product-database readiness remain
unaccepted.
```

```powershell
git add docs/acceptance/2026-08-02-phase-4b2-streaming-reconnect-cancel.md CURRENT_PROJECT_STATE.md docs/superpowers/plans/2026-08-02-phase-4b2-streaming-reconnect-cancel.md
git diff --cached --check
git commit -m "docs: accept streamed draft operations"
```

## Final stop condition

Do not call Phase4B2 complete, push, or advance to B3 until Task 12 is fresh and clean. Do not call Phase4B complete after B2; rewrite/local operations and undo remain outstanding.
