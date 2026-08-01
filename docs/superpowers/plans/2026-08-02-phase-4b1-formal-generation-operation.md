# Phase 4B1 Formal Generation Operation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary synchronous chapter-generation write path with one persistent, idempotent, fenced `generate_new` operation that safely commits a WorkingDraft and can be recovered through formal status/events APIs.

**Architecture:** The browser flushes the visible WorkingDraft, creates one canonical UUID idempotency key for the user action, and submits a strict `generate_new` command. The backend reserves a durable attempt in a short transaction, calls the injected chapter provider outside every transaction, and commits only after re-locking the Session and revalidating operation ownership, fencing token, lease, WorkingDraft CAS, current Outline/Planning basis, projection authority, and provider authority. The first slice returns terminal status without fabricated token streaming; B2 will add delta streaming, heartbeat renewal and cancellation, while B3 will add full/local rewrite and undo endpoints.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, aiomysql/MySQL 8, pytest/pytest-asyncio, Vue 3/Pinia, native fetch client, Node test runner, Vite.

---

## Scope boundary

This plan implements only the first Phase 4B vertical slice:

- `generate_new` persistent attempts;
- same-key replay and same-key/different-request conflict;
- one active operation per ChapterSession;
- monotonic fencing and finite lease;
- two short database transactions around one provider call;
- immutable before/after WorkingDraft recovery snapshots;
- `started`, `completed`, and `failed` persisted public events;
- POST, status GET, and event GET formal routes;
- unknown HTTP outcome recovery by replaying the same POST body/key;
- frontend operation state, shallow read-only overlay, and authoritative workspace reload;
- physical removal of the temporary `generate-working-draft` route and old client call.

This plan deliberately does not claim:

- streaming `delta` or heartbeat renewal;
- cancel or restart recovery;
- `rewrite_full`, selection operations, or candidate fusion;
- recovery-record browsing or undo;
- Phase 4C workbench, Phase 4D browser acceptance, Phase 5 audit/finalization;
- any real-provider, product-database, or novel-quality acceptance.

`DRAFT_OPERATION_LEASE_MS` is exactly `1_260_000`, sixty seconds longer than the existing 1,200-second provider read timeout. Expiry still fences late results and permits a later request to take a new token. B2 replaces this conservative lease with periodic heartbeat renewal and cancellation.

## Public contract fixed by this plan

The strict create body is:

```json
{
  "operationType": "generate_new",
  "expectedWorkingDraftRevision": 4,
  "expectedContentHash": "<64 lowercase hex>",
  "idempotencyKey": "11111111-1111-4111-8111-111111111111",
  "authorInstruction": "多一点人物之间的试探"
}
```

The public operation object is closed to:

```json
{
  "id": "<canonical lowercase UUID>",
  "projectId": "<project id>",
  "chapterSessionId": "<session id>",
  "operationType": "generate_new",
  "status": "starting|running|completed|failed|expired",
  "lastEventSequence": 2,
  "resultWorkingDraftRevision": 5,
  "resultContentHash": "<64 lowercase hex or null>",
  "failureCode": null,
  "model": {
    "providerId": "<public provider id>",
    "modelName": "<public model name>"
  }
}
```

No public response includes input manifests, prompts, author prose, provider bodies, API keys, base URLs, DSNs, fencing tokens, leases, raw exceptions, or recovery snapshot content.

## File structure

New focused modules:

- `backend/services/draft_operations.py`: command validation, reserve/call/settle state machine, public result types.
- `frontend/src/application/writer/draftOperationCoordinator.js`: one user action/key, replay-safe request, terminal state, and authoritative reload coordination.
- `backend/tests/unit/test_draft_operation_service.py`: state-machine tests with in-memory repository and injected fake gateway.
- `backend/tests/api/test_draft_operation_routes.py`: strict public DTO and retired-route tests.
- `backend/tests/integration/test_draft_operation_integrity.py`: MySQL ownership, replay, fencing, rollback and recovery evidence.
- `frontend/tests/unit/draftOperationCoordinator.test.mjs`: client state and replay tests.

Existing modules retain one responsibility:

- `backend/repositories/chapter_sessions.py`: SQL primitives only.
- `backend/routers/chapter_sessions.py`: strict HTTP validation and public projection only.
- `backend/gateways/chapter_draft_provider.py`: outbound provider boundary only.
- `frontend/src/stores/chapterSessionStore.js`: product API authority and workspace state only.
- `frontend/src/application/writer/chapterWriterController.js`: flush/action lock and editor resynchronization only.
- `frontend/src/views/ChapterWriterView.vue`: presentation and user actions only.

## Agent/model routing

The controller selects the lowest-cost model that can safely complete each bounded role and may upgrade the same task when evidence shows the initial choice is insufficient:

- Terra Medium: mechanical schema expectation updates, single-file DTO/client wiring, and routine focused tests;
- Terra High: clearly specified multi-file repository, API, coordinator, and UI implementation;
- Sol High: transaction/state-machine implementation, concurrency or cancellation-sensitive debugging, specification review, quality review, and final cross-slice audit.

One task has one implementer. Specification and quality reviewers run serially. A reviewer does not become an implementer, and completed reviewers are not reused for unrelated work. If an implementer returns `NEEDS_CONTEXT`, the controller supplies missing context; if it returns `BLOCKED` because reasoning is insufficient, the controller upgrades that same bounded task rather than spawning repeated substitutes.

## Task 1: Exact operation and recovery schema

**Files:**
- Modify: `backend/schema/40_drafts.sql`
- Modify: `backend/schema_version.py`
- Modify: `CURRENT_PROJECT_STATE.md`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_initialize_database.py`
- Modify: `backend/tests/integration/test_schema_bootstrap.py`

- [ ] **Step 1: Write schema RED tests**

Extend exact manifest tests to require:

```python
EXPECTED_PHASE4B1_TABLES = {
    "working_draft_revisions",
    "draft_operation_attempts",
    "draft_operation_events",
}

for table in EXPECTED_PHASE4B1_TABLES:
    assert table in manifest.tables

chapter_sessions = manifest.tables["chapter_sessions"]
assert chapter_sessions.columns["draft_operation_fencing_token"].nullable is False
assert chapter_sessions.columns["active_draft_operation_id"].nullable is True
assert manifest.schema_version == "writer-core-v1.8.0"
```

Require unique identities for `(chapter_session_id, idempotency_key)`, `(chapter_session_id, active_slot)`, `(chapter_session_id, fencing_token)`, recovery `(chapter_session_id, working_draft_revision, snapshot_role)`, and event `(draft_operation_id, sequence_num)`. Also require database-enforced owner identities for WorkingDraft `(project_id, chapter_session_id, id)`, attempt `(project_id, id)` and `(project_id, chapter_session_id, id)` so recovery and event rows cannot compose identifiers from different owners.

- [ ] **Step 2: Run schema RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q
```

Expected: failures for the missing tables/session columns and old `writer-core-v1.7.0` version.

- [ ] **Step 3: Add the minimal exact schema**

Advance `EXPECTED_SCHEMA_VERSION` to `writer-core-v1.8.0`. Add these Session columns:

```sql
draft_operation_fencing_token BIGINT NOT NULL DEFAULT 0,
active_draft_operation_id CHAR(36) NULL,
CHECK (draft_operation_fencing_token >= 0)
```

Create tables in foreign-key dependency order: `working_drafts`, `draft_operation_attempts`, `working_draft_revisions`, then `draft_operation_events`. The contracts below describe their required fields and constraints even where the explanatory order differs.

Add `working_draft_revisions` with exact immutable fields:

```sql
CREATE TABLE working_draft_revisions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  working_draft_id CHAR(36) NOT NULL,
  working_draft_revision INT NOT NULL,
  snapshot_role VARCHAR(24) NOT NULL,
  replacement_reason VARCHAR(40) NOT NULL,
  source_operation_id CHAR(36) NOT NULL,
  content LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_working_draft_recovery
    (chapter_session_id, working_draft_revision, snapshot_role),
  FOREIGN KEY (project_id, chapter_session_id, working_draft_id)
    REFERENCES working_drafts(project_id, chapter_session_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id, source_operation_id)
    REFERENCES draft_operation_attempts(project_id, chapter_session_id, id)
    ON DELETE CASCADE,
  CHECK (working_draft_revision > 0),
  CHECK (snapshot_role IN ('before','after')),
  CHECK (replacement_reason IN ('generate_new'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
```

Add `draft_operation_attempts` with these exact groups of fields:

```text
identity: id, project_id, chapter_session_id, operation_type
idempotency: idempotency_key, request_fingerprint
ownership: active_slot, fencing_token, lease_expires_at
base CAS: base_working_draft_revision, base_working_draft_hash
context: input_manifest_json, input_manifest_hash
public model: provider_id, model_name_snapshot
result: result_working_draft_revision, result_content_hash
state: status, last_event_sequence, failure_code
time: created_at, updated_at, completed_at
```

Define attempt owner keys `(project_id, id)` and `(project_id, chapter_session_id, id)`. Define the WorkingDraft owner key `(project_id, chapter_session_id, id)` before recovery snapshots. Use only `generate_new` for `operation_type`; statuses are `starting`, `running`, `completed`, `failed`, `expired`; `active_slot` is `1` only while starting/running and otherwise NULL. A completed row requires result revision/hash and no failure code; failed requires a fixed failure code and no result; expired has neither result nor failure.

Add `draft_operation_events` with operation identity, monotonically increasing sequence, type `started|completed|failed`, closed `payload_json`, and timestamp. Its `(project_id, draft_operation_id)` foreign key must target the attempt owner key; do not use independent project and operation foreign keys. Do not add provider request/response columns.

Add a real disposable-MySQL behavior test proving that cross-Session draft/source-operation recovery rows and cross-project event rows are rejected, same-owner before/after/event rows are accepted, and deleting one Session cascades only that Session's operation state while another owner remains intact.

Update `CURRENT_PROJECT_STATE.md` only to record `writer-core-v1.8.0` as source schema and Phase4B1 as in progress; do not call Phase4B or Phase4 complete.

- [ ] **Step 4: Run schema GREEN and MySQL exact bootstrap**

Run serially:

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q
python -m pytest backend/tests/integration/test_schema_bootstrap.py -m mysql -q --basetemp .codex-test-artifacts/pytest/integration
```

Expected: both commands exit 0; integration reports equal created/cleaned counts and remaining=0.

- [ ] **Step 5: Commit schema**

```powershell
git add backend/schema/40_drafts.sql backend/schema_version.py CURRENT_PROJECT_STATE.md backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/integration/test_schema_bootstrap.py
git commit -m "feat: add persistent draft operation schema"
```

## Task 2: SQL ownership, event and recovery primitives

**Files:**
- Modify: `backend/repositories/chapter_sessions.py`
- Modify: `backend/tests/unit/test_chapter_session_repository.py`

- [ ] **Step 1: Write repository RED tests**

Add contract tests for these methods:

```python
lock_session_for_operation(session, project_id, chapter_session_id)
lock_working_draft_for_operation(session, project_id, chapter_session_id)
read_draft_operation_by_key(session, chapter_session_id, idempotency_key)
read_draft_operation(session, project_id, chapter_session_id, operation_id)
read_active_draft_operation(session, chapter_session_id)
next_draft_operation_fencing_token(session, project_id, chapter_session_id)
insert_draft_operation(session, row)
mark_draft_operation_running(session, operation_id, fencing_token, now)
complete_draft_operation(session, row)
fail_draft_operation(session, row)
expire_draft_operation(session, operation_id, fencing_token, now)
expire_draft_operation_for_drift(
    session, project_id, chapter_session_id, operation_id, fencing_token, now
)
insert_draft_operation_event(session, row)
list_draft_operation_events(session, operation_id, after_sequence, limit)
insert_working_draft_revision(session, row)
```

Tests must assert SQL contains project/session ownership predicates, the operation/fencing pair on every terminal update, `FOR UPDATE` on Session, operation and WorkingDraft ownership reads, event limits restricted to `1..100`, and no secret/provider payload columns. Natural expiration must be one atomic lease guard: `lease_expires_at <= now`; a `starting` attempt may be expired only when the Session active pointer is NULL or points to itself, while a `running` attempt requires the Session pointer to point to itself. Drift expiration is a separate fenced primitive for an active `running` attempt whose Session pointer is still self-owned and whose lease is still live (`lease_expires_at > now`); it must not synthesize a future timestamp to reuse natural expiration.

- [ ] **Step 2: Run repository RED**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_repository.py -q
```

Expected: missing-method failures.

- [ ] **Step 3: Implement minimal SQL methods**

Use parameterized SQL for every value. `next_draft_operation_fencing_token` must lock the Session row and update `draft_operation_fencing_token = current + 1`. `insert_draft_operation_event` must update `last_event_sequence` only when the same operation owns the expected next sequence. Terminal updates must clear both `active_slot` and `chapter_sessions.active_draft_operation_id` only when the operation ID and fencing token still match.

Recovery insertion is append-only. A duplicate business identity is accepted only as an exact replay of every immutable field: primary ID, WorkingDraft ID, replacement reason, source operation ID, content, hash and creation timestamp (with project/Session/revision/role already fixed by the lookup). Any mismatch is rejected; an existing snapshot is never updated.

- [ ] **Step 4: Run repository GREEN**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_repository.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit repository primitives**

```powershell
git add backend/repositories/chapter_sessions.py backend/tests/unit/test_chapter_session_repository.py
git commit -m "feat: persist fenced draft operation state"
```

## Task 3: Generate-new reserve/call/settle service

**Files:**
- Create: `backend/services/draft_operations.py`
- Create: `backend/tests/unit/test_draft_operation_service.py`
- Modify: `backend/prompts/chapter_draft.py`
- Modify: `backend/tests/unit/test_chapter_draft_prompt.py`

- [ ] **Step 1: Write service RED tests**

Define the desired command and result API in tests:

```python
@dataclass(frozen=True)
class StartDraftOperation:
    project_id: str
    chapter_session_id: str
    operation_type: str
    expected_working_draft_revision: int
    expected_content_hash: str
    idempotency_key: str
    author_instruction: str = ""

@dataclass(frozen=True)
class DraftOperationResult:
    operation_id: str
    project_id: str
    chapter_session_id: str
    operation_type: str
    status: str
    last_event_sequence: int
    result_working_draft_revision: int | None
    result_content_hash: str | None
    failure_code: str | None
    provider_id: str
    model_name: str
```

Cover one behavior per test:

- valid `generate_new` reserves, calls the fake gateway outside a transaction, and commits revision +1;
- base revision or hash mismatch fails before provider invocation;
- same key/same fingerprint replays starting/running/completed/failed without a second provider call;
- same key/different fingerprint raises a fixed idempotency conflict;
- a live active operation rejects a different key;
- an expired active operation becomes expired and a new token can reserve;
- late result after expiry/new token cannot update WorkingDraft;
- current Outline/Planning, projection or provider authority drift expires the result without changing draft;
- provider error/invalid/secret-shaped output records fixed failure without changing draft;
- successful commit writes before and after recovery snapshots atomically;
- recovery insertion, event insertion or WorkingDraft CAS failure rolls the entire settle transaction back;
- no transaction context remains active during gateway invocation;
- request fingerprint and manifest never contain provider secrets or base URL.

- [ ] **Step 2: Run service RED**

```powershell
python -m pytest backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_draft_prompt.py -q
```

Expected: module-not-found and missing prompt-contract failures.

- [ ] **Step 3: Implement strict validation and canonical fingerprints**

Accept only `generate_new`, canonical lowercase UUID keys, positive revision, lowercase SHA-256 hash, and an author instruction of at most 2,000 Unicode scalar values. Build the request fingerprint from:

```python
{
    "projectId": command.project_id,
    "chapterSessionId": command.chapter_session_id,
    "operationType": "generate_new",
    "baseWorkingDraftRevision": command.expected_working_draft_revision,
    "baseWorkingDraftHash": command.expected_content_hash,
    "authorInstruction": normalized_instruction,
}
```

Build an immutable input manifest from public identities and exact story context only: current confirmed Outline identity/content and its Planning basis, current Planning Head identity/hash, historical Session entry pins, the Planning basis and current immutable Seed/Contract/Bible authority fields, Canon/projection identities, WorkingDraft revision/hash, binding identity/hash, public provider/model identity, operation type, and author instruction. Session entry pins, current Outline and current Planning Head are independent snapshots and may legitimately differ; do not require equality between them. The current Outline's referenced Planning must still match the permanent Seed/Contract/Bible baseline, and its projection must match current projection authority. Do not store API key, base URL, provider body or generated prose in the manifest.

Normalize the complete provider authority before hashing. MySQL `DECIMAL` temperature must have a stable canonical representation; zero is a valid configured temperature and only NULL uses the default. Require a finite non-negative temperature and a positive non-boolean output-token count. Hashing or validation failure is fail-closed, never a comparable `None` sentinel. API key and base URL may participate only in the ephemeral in-memory authority fingerprint so mid-call provider drift is fenced; they never enter the manifest, attempt/event/recovery rows, public result or errors. Freeze their normalized secret variants in an immutable tuple before the call, and pass isolated copies of provider/config/messages to the gateway so gateway mutation cannot change the later response-scan baseline or authority context.

- [ ] **Step 4: Implement reserve/call/settle**

Reserve in transaction 1:

1. lock active project and target Session;
2. replay an existing key before mutable-state checks;
3. require drafting status and exact WorkingDraft revision/hash;
4. read current confirmed Outline/Planning, projection and writing-provider authority;
5. expire only an elapsed active operation;
6. increment the Session fencing token;
7. insert a `starting` attempt and `started` event sequence 1;
8. mark it running and set `active_draft_operation_id`.

Call `ChapterDraftProviderGateway.generate` after transaction 1 exits. Reuse `build_chapter_draft_messages`, but make `generate_new` explicit so the prompt does not treat existing draft prose as rewrite input.

Settle in transaction 2:

1. lock project, Session, operation and WorkingDraft;
2. require matching active operation ID, fencing token and unexpired lease;
3. revalidate Session, current Outline/Planning, projection, provider and manifest identities;
4. require exact base revision/hash;
5. validate and redact provider output using existing provider-security helpers;
6. insert the immutable `before` recovery snapshot;
7. CAS WorkingDraft to revision +1 and generated hash;
8. insert immutable `after` snapshot;
9. insert completed event sequence 2 with only result revision/hash;
10. complete the attempt and clear Session active ownership.

Provider/validation failure settles to fixed codes such as `DraftProviderFailed` or `DraftProviderResultInvalid`. Only the gateway's declared safe `ChapterDraftProviderError` boundary becomes the fixed provider failure. An unexpected non-cancellation program exception must not masquerade as a normal business failure: raise a fixed internal exception without its raw text and leave the durable running attempt recoverable by lease; cancellation remains uncaught. An elapsed lease uses the natural-expiration primitive; authority, manifest or base drift while the lease is still live uses the dedicated drift-expiration primitive. Both settle to `expired` without public raw detail. Coordination/storage failures are re-raised so a rolled-back terminal write is never presented as durable, including failures of the final complete/fail attempt update itself.

All replay and terminal states use one fail-closed public projection. In B1, `starting`, `running` and `expired` require `last_event_sequence == 1`; `completed` and `failed` require sequence `2`, in addition to canonical identity, operation type, model/provider and result/failure correlations. Expiration must not substitute placeholder public fields or preserve a malformed sequence.

- [ ] **Step 5: Run service GREEN**

```powershell
python -m pytest backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_draft_prompt.py -q
```

Expected: all selected tests pass with one fake provider call on same-key replay.

- [ ] **Step 6: Commit service**

```powershell
git add backend/services/draft_operations.py backend/prompts/chapter_draft.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_draft_prompt.py
git commit -m "feat: run fenced generate new operations"
```

## Task 4: Formal operation HTTP surface and old-route retirement

**Files:**
- Modify: `backend/routers/chapter_sessions.py`
- Create: `backend/tests/api/test_draft_operation_routes.py`
- Modify: `backend/tests/api/test_chapter_session_routes.py`
- Delete: `backend/services/chapter_draft_generation.py`
- Delete: `backend/tests/unit/test_chapter_draft_generation.py`
- Modify: `backend/main.py` only if dependency assembly requires it

- [ ] **Step 1: Write API RED tests**

Require:

```text
POST /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations
GET  /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}
GET  /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}/events?after=0
```

Test exact body allowlisting, canonical hash/UUID validation, only `generate_new`, instruction bound, project/session/operation ownership, after >= 0, maximum 100 public events, and closed operation/event responses. Assert unknown fields including `prompt`, `messages`, `provider`, `model`, `apiKey`, `baseUrl`, `debug`, and `responseBody` return the fixed public request error.

Add a source/runtime assertion that POSTing the old `/generate-working-draft` path returns 404 and that no router or service symbol for `generate_working_draft` remains.

- [ ] **Step 2: Run API RED**

```powershell
python -m pytest backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py -q
```

Expected: missing formal routes and old-route-retirement failures.

- [ ] **Step 3: Implement strict routes and public projections**

Use Pydantic `extra="forbid"` bodies. POST always returns HTTP 200 for both the first execution and an idempotent replay; clients use the closed operation body's `status` and never infer business completion from a differing transport status. Status GET never triggers provider work. Event GET returns:

```json
{
  "operationId": "<id>",
  "events": [
    {"sequence": 1, "type": "started", "createdAt": 123},
    {"sequence": 2, "type": "completed", "createdAt": 456,
     "resultWorkingDraftRevision": 5,
     "resultContentHash": "<hash>"}
  ]
}
```

Failed events expose only `failureCode`; no event exposes content or internal ownership.

Delete the temporary service, tests, dependency factory and old route in the same change. Do not retain a compatibility alias.

- [ ] **Step 4: Run API GREEN and retired-runtime checks**

```powershell
python -m pytest backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py -q
node --test frontend/tests/unit/phase2RuntimeInventory.test.mjs
```

Expected: formal routes pass and old route/service are absent from the active graph.

- [ ] **Step 5: Commit API cutover**

```powershell
git add backend/routers/chapter_sessions.py backend/main.py backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py backend/services/chapter_draft_generation.py backend/tests/unit/test_chapter_draft_generation.py frontend/tests/unit/phase2RuntimeInventory.test.mjs
git commit -m "feat: expose formal draft operations"
```

## Task 5: Disposable MySQL operation integrity

**Files:**
- Create: `backend/tests/integration/test_draft_operation_integrity.py`

- [ ] **Step 1: Write MySQL RED scenarios**

Use only `disposable_mysql`. Prove database ownership first with `SELECT DATABASE()` and the exact `novel_creator_test_[0-9a-f]{32}` pattern. Add scenarios for:

- success creates one attempt, two recovery snapshots, two events, and one new WorkingDraft revision;
- concurrent same-key requests produce one provider invocation/effect and one attempt;
- concurrent different keys permit only one live active slot;
- expired first attempt plus late result cannot beat the later fencing token;
- same key/different request is rejected without new rows;
- failure and CAS drift leave WorkingDraft/recovery unchanged and clear or expire active ownership correctly;
- provider wait is observed while a second database connection can read unrelated state, proving no held transaction;
- event sequence and result metadata match the committed WorkingDraft;
- no attempt/event/manifest column stores API key, base URL or provider response body.

- [ ] **Step 2: Run MySQL RED**

```powershell
python -m pytest backend/tests/integration/test_draft_operation_integrity.py -m mysql -q --basetemp .codex-test-artifacts/pytest/integration
```

Expected: failures until repository/service transaction semantics are complete.

- [ ] **Step 3: Make only integration-driven corrections**

Correct SQL predicates, locks, unique-key conflict handling and rollback behavior without changing the public contract. Every correction starts from the failing integration assertion and reruns only that scenario before the full file.

- [ ] **Step 4: Run MySQL GREEN**

```powershell
python -m pytest backend/tests/integration/test_draft_operation_integrity.py -m mysql -q --basetemp .codex-test-artifacts/pytest/integration
```

Expected: all scenarios pass; disposable MySQL created=cleaned and remaining=0.

- [ ] **Step 5: Commit integration evidence**

```powershell
git add backend/tests/integration/test_draft_operation_integrity.py backend/repositories/chapter_sessions.py backend/services/draft_operations.py
git commit -m "test: prove draft operation integrity"
```

## Task 6: Closed frontend API and replay-safe operation coordinator

**Files:**
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Create: `frontend/src/application/writer/draftOperationCoordinator.js`
- Create: `frontend/tests/unit/draftOperationCoordinator.test.mjs`

- [ ] **Step 1: Write frontend RED tests**

API tests require exact POST/status/event paths, encoded segments, strict outgoing keys, and closed public response projection. Coordinator tests define:

```javascript
const coordinator = createDraftOperationCoordinator({
  startOperation,
  readOperation,
  reloadWorkspace,
  idFactory,
})

await coordinator.generateNew({
  expectedWorkingDraftRevision: 4,
  expectedContentHash: HASH,
  authorInstruction: '多一点人物试探',
})
```

Cover:

- one canonical UUID generated per user action;
- the same frozen command/key is reused after an unknown transport outcome;
- same action cannot start twice;
- completed response reloads authoritative workspace exactly once;
- failed/expired response does not reload or alter editor text;
- dispose/context reset ignores late operation/reload responses;
- public state is read-only and contains no request body, prose, provider payload or key;
- no client method for `generate-working-draft` remains.

- [ ] **Step 2: Run frontend RED**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs
```

Expected: missing formal client/coordinator and retired-method failures.

- [ ] **Step 3: Implement the closed client**

Expose:

```javascript
createDraftOperation(projectId, sessionId, command)
readDraftOperation(projectId, sessionId, operationId)
listDraftOperationEvents(projectId, sessionId, operationId, afterSequence)
```

The client sends only the five approved create fields and accepts only the public operation/event fields. Sensitive keys at any depth fail closed before fetch. Remove `generateWorkingDraft` and its old path.

- [ ] **Step 4: Implement the coordinator**

Expose read-only `status`, `operation`, `busy`, `failureCode`, and methods `generateNew`, `retryUnknown`, `resetContext`, `dispose`. `generateNew` freezes one command and UUID for the action. A known terminal response clears retry state; an unknown transport error retains the frozen command in private memory so explicit retry replays it. A completed operation calls `reloadWorkspace()` and returns that authoritative workspace, never operation output text.

- [ ] **Step 5: Run frontend GREEN**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit frontend operation boundary**

```powershell
git add frontend/src/api/db/client.js frontend/src/application/writer/draftOperationCoordinator.js frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs
git commit -m "feat: coordinate persistent draft generation"
```

## Task 7: Store/controller/view formal generation cutover

**Files:**
- Modify: `frontend/src/stores/chapterSessionStore.js`
- Modify: `frontend/src/application/writer/chapterWriterController.js`
- Modify: `frontend/src/views/ChapterWriterView.vue`
- Modify: `frontend/tests/unit/chapterSessionStore.test.mjs`
- Modify: `frontend/tests/unit/chapterWriterController.test.mjs`
- Modify: `frontend/tests/unit/chapterWriterView.test.mjs`
- Modify: `frontend/tests/unit/phase2RuntimeInventory.test.mjs`

- [ ] **Step 1: Write UI integration RED tests**

Prove:

- controller flushes visible text before coordinator `generateNew`;
- post-flush revision/hash and controller-owned instruction are passed;
- completed operation resynchronizes autosave only when no newer edit generation exists;
- failed/expired/unknown outcomes never replace local text;
- operation busy disables editing, paste, candidate changes and navigation through one action state;
- operation text remains readable and scrollable under the shallow overlay;
- route/context change resets coordinator private retry state before any await;
- UI shows fixed statuses `正在生成`, `生成完成`, `生成失败`, `生成结果已失效`, and `结果未知，可重试` without raw store/provider errors;
- the source graph contains no old API method, old route token or second generation write path.

- [ ] **Step 2: Run UI RED**

```powershell
node --test frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/phase2RuntimeInventory.test.mjs
```

Expected: failures for old synchronous method and missing coordinator state.

- [ ] **Step 3: Wire the formal operation**

The store exposes create/read/events calls and reloads the current authoritative chapter workspace after completion. It does not own idempotency retry memory. The controller owns one coordinator, flushes before generation, keeps its existing action lock, and fences late workspace reloads with edit generation and route context.

The View uses one shallow overlay driven by coordinator/controller state. It does not render provider output separately in B1 because the non-stream operation commits only terminal output; after completion it displays the authoritative WorkingDraft. Keep the candidate action separate and never auto-freeze generated text.

- [ ] **Step 4: Run UI GREEN and build**

```powershell
node --test frontend/tests/unit/plainTextRange.test.mjs frontend/tests/unit/workingDraftAutosave.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/phase2RuntimeInventory.test.mjs
npm run build
```

Expected: all selected tests and Vite build pass.

- [ ] **Step 5: Commit UI cutover**

```powershell
git add frontend/src/stores/chapterSessionStore.js frontend/src/application/writer/chapterWriterController.js frontend/src/views/ChapterWriterView.vue frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/phase2RuntimeInventory.test.mjs
git commit -m "feat: generate through persistent draft operations"
```

## Task 8: Phase 4B1 acceptance, review and controlled-real-test handoff

**Files:**
- Modify: `CURRENT_PROJECT_STATE.md`
- Create: `docs/acceptance/2026-08-02-phase-4b1-formal-generation.md`

- [ ] **Step 1: Self-review the complete B1 diff**

Check:

- one formal `generate_new` write path and no temporary route/client/service remains;
- every request uses revision+hash and canonical UUID idempotency;
- provider wait holds no transaction;
- replay never calls provider twice;
- lease/fence and authority drift prevent late overwrite;
- before/after recovery records are atomic with WorkingDraft commit;
- no candidate is created automatically;
- no public response/log/test output contains author prose, secrets, provider body, base URL or DSN;
- no streaming/cancel/rewrite/undo/Phase4B-complete claim appears.

- [ ] **Step 2: Run fresh focused gates**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/unit/test_chapter_session_repository.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_draft_prompt.py backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py -q
node --test frontend/tests/unit/plainTextRange.test.mjs frontend/tests/unit/workingDraftAutosave.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/phase2RuntimeInventory.test.mjs
python -m pytest backend/tests/integration/test_draft_operation_integrity.py -m mysql -q --basetemp .codex-test-artifacts/pytest/integration
npm run build
git diff --check
```

Expected: every command exits 0 and disposable database residue is zero.

- [ ] **Step 3: Specification review to 0/0/0**

Review the complete `2b99516..HEAD` B1 diff against `docs/superpowers/specs/2026-08-01-phase-4-writer-loop-design.md` and this plan. Resolve every Critical/Important/Minor finding with the same implementer, TDD and fresh focused evidence until counts are `0/0/0`.

- [ ] **Step 4: Quality review to 0/0/0**

After specification review is clean, review concurrency, transaction boundaries, idempotency, lease/fencing, recovery atomicity, secret safety, frontend late-response fencing, accessibility and test quality. Resolve findings through the same implementer until `0/0/0`.

- [ ] **Step 5: Controller fresh full gates and resource ledger**

Run serially:

```powershell
npm run test:integration
npm run build
git diff --check
```

Then audit only proven-owned `novel_creator_test_%` databases, Node/Python runner processes, ports 8000/4173/5173, `.codex-test-artifacts`, and Vite `deps_temp*`. Expected residue for every category: 0.

- [ ] **Step 6: Record the exact acceptance boundary**

The acceptance document records only exit codes, passed/failed/skipped counts, first root cause if a gate required repair, review counts, and the zero-residue ledger. It states:

```text
Phase4B1 formal generate_new is accepted with an injected fake provider.
Streaming, cancellation, rewrite/local tools, undo, full Phase4B, real-provider
quality and product-database readiness remain unaccepted.
```

Update `CURRENT_PROJECT_STATE.md` to name Phase4B2 streaming/reconnect/cancel as the unique next engineering step. Separately state that a controlled DeepSeek V3 Flash smoke test requires an explicit user approval and a valid token and is not an automated gate.

- [ ] **Step 7: Commit B1 acceptance**

```powershell
git add CURRENT_PROJECT_STATE.md docs/acceptance/2026-08-02-phase-4b1-formal-generation.md docs/superpowers/plans/2026-08-02-phase-4b1-formal-generation-operation.md
git commit -m "docs: accept formal draft generation"
```

Do not push or run a real provider until the user explicitly authorizes that external action after reviewing the fake-provider acceptance evidence.
