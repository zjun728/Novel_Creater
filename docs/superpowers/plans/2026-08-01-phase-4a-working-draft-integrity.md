# Phase 4A WorkingDraft Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the visible plain-text WorkingDraft safely autosave through revision/hash CAS, freeze exactly that persisted text as an idempotent candidate, and expose one Unicode-safe selection/location primitive for later draft operations and audit findings.

**Architecture:** Extend the exact bootstrap schema with recovery and candidate-freeze ledgers, strengthen the existing ChapterSession service rather than adding a second draft authority, and isolate browser buffer/autosave/range behavior in small testable modules. The current synchronous generation path remains temporarily reachable only through the same flush boundary; Phase 4B replaces it with the unified fenced operation service.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, async MySQL 8 repositories, Vue 3/Pinia/Naive UI, JavaScript `node:test`, pytest, exact-schema bootstrap.

---

## File map

**Schema and backend**

- Modify `backend/schema/40_drafts.sql`: add the candidate freeze request ledger used in this slice; recovery/operation tables arrive with the Phase 4B behavior that uses them.
- Modify `backend/schema_version.py`: advance the exact bootstrap schema to `writer-core-v1.7.0`.
- Modify `CURRENT_PROJECT_STATE.md`: record the current committed-source schema version; preserve Phase 3 historical schema facts.
- Modify `backend/domain/drafts.py`: expose safe recovery metadata only if the workspace needs it; never expose source payload bodies.
- Modify `backend/repositories/chapter_sessions.py`: revision/hash CAS and freeze-request replay.
- Modify `backend/services/chapter_sessions.py`: validate content hashes and idempotency fingerprints and freeze the exact persisted text.
- Modify `backend/routers/chapter_sessions.py`: strict request fields and safe public mapping.

**Frontend**

- Modify `frontend/src/api/db/client.js`: send only expected revision/hash, content, and candidate idempotency fields.
- Modify `frontend/src/stores/chapterSessionStore.js`: preserve one write mutex and require exact draft authority.
- Create `frontend/src/utils/plainTextRange.js`: UTF-16 ↔ Unicode scalar offset conversion, hashing input extraction, and exact selection location.
- Create `frontend/src/application/writer/workingDraftAutosave.js`: one-flight debounce/max-wait/flush coordinator.
- Create `frontend/src/application/writer/chapterWriterController.js`: coordinate editor buffer, autosave, candidate flush, generation flush, and navigation.
- Create `frontend/src/components/writer/PlainTextDraftEditor.vue`: one native textarea with selection/location and persistence status.
- Modify `frontend/src/views/ChapterWriterView.vue`: use the controller/editor, remove manual save, and install guarded async navigation/unload behavior.
- Delete `frontend/src/utils/chapterEditorState.js`: its buffer and baseline responsibilities move to the autosave coordinator; two editor state authorities are forbidden.

**Tests**

- Modify `backend/tests/unit/test_schema_manifest.py`.
- Modify `backend/tests/unit/test_schema_version.py`.
- Modify `backend/tests/unit/test_initialize_database.py`.
- Modify `backend/tests/unit/test_chapter_session_repository.py`.
- Modify `backend/tests/unit/test_chapter_session_service.py`.
- Modify `backend/tests/api/test_chapter_session_routes.py`.
- Modify `backend/tests/integration/test_authoritative_chapter_session.py`.
- Modify `backend/tests/api/test_application_settings_routes.py` only where it asserts the literal schema version.
- Modify `frontend/tests/unit/writerCoreApi.test.mjs`.
- Delete `frontend/tests/unit/chapterEditorState.test.mjs` after its late-save and navigation cases are represented in the new autosave/controller tests.
- Create `frontend/tests/unit/plainTextRange.test.mjs`.
- Create `frontend/tests/unit/workingDraftAutosave.test.mjs`.
- Create `frontend/tests/unit/chapterWriterController.test.mjs`.
- Create `frontend/tests/unit/chapterWriterView.test.mjs` for minimal static product-boundary checks that cannot be expressed through the controller.
- Modify `frontend/tests/unit/chapterSessionStore.test.mjs`.

## Task 1: Exact schema foundations

- [ ] **Step 1: Write failing schema tests**

Add assertions that the manifest contains `candidate_freeze_requests` after `draft_candidates`, its required unique keys and foreign keys, and schema version `writer-core-v1.7.0`.

```python
def test_phase4a_draft_integrity_tables_are_in_exact_manifest():
    names = created_table_names()
    assert names.index("draft_candidates") < names.index("candidate_freeze_requests")


def test_expected_schema_version_is_writer_core_v1_7():
    assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.7.0"
```

- [ ] **Step 2: Run the focused tests and prove RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q
```

Expected: failures naming the missing freeze-request table and the old `writer-core-v1.6.0` version.

- [ ] **Step 3: Add the schema tables**

Append this table after `draft_candidates` and before finalization tables:

```sql
CREATE TABLE candidate_freeze_requests (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  idempotency_key VARCHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  draft_candidate_id CHAR(36) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_candidate_freeze_idempotency
    (chapter_session_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id)
    REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, draft_candidate_id)
    REFERENCES draft_candidates(project_id, id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
```

Change `EXPECTED_SCHEMA_VERSION` and the intentional literal-version tests to `writer-core-v1.7.0`. Do not alter the frozen legacy fixture; it proves an older fixture, not the current manifest.

- [ ] **Step 4: Run schema tests GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Commit the schema slice**

```powershell
git add backend/schema/40_drafts.sql backend/schema_version.py CURRENT_PROJECT_STATE.md backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/api/test_application_settings_routes.py
git commit -m "feat: add working draft integrity schema"
```

## Task 2: Revision-and-hash autosave CAS

- [ ] **Step 1: Write service and route RED tests**

Cover valid save, stale revision, correct revision with stale hash, unknown request fields, no candidate creation, and a no-op save whose content already equals the current persisted content.

```python
@pytest.mark.asyncio
async def test_save_working_draft_requires_revision_and_hash():
    repository = FakeChapterRepository()
    service = ChapterSessionService(repository, transaction_factory=tx_factory)
    current = repository.working_draft

    with pytest.raises(ChapterSessionConflict, match="revision or hash drift"):
        await service.save_working_draft(SaveWorkingDraft(
            project_id=PROJECT_ID,
            chapter_session_id=SESSION_ID,
            expected_revision=current["revision"],
            expected_content_hash="0" * 64,
            content="作者刚刚输入的正文",
        ))

    assert repository.working_draft == current
    assert repository.candidates == []
```

Route bodies must accept only:

```json
{
  "expectedRevision": 4,
  "expectedContentHash": "<64 lowercase hex>",
  "content": "屏幕可见正文"
}
```

- [ ] **Step 2: Run focused backend tests RED**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py -q
```

Expected: constructor/body failures for the missing `expected_content_hash` contract.

- [ ] **Step 3: Implement minimal CAS**

Change the command and route body:

```python
@dataclass(frozen=True)
class SaveWorkingDraft:
    project_id: str
    chapter_session_id: str
    expected_revision: int
    expected_content_hash: str
    content: str


class SaveWorkingDraftBody(_StrictBody):
    expectedRevision: int = Field(ge=1)
    expectedContentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str = Field(max_length=100_000)
```

In `save_working_draft`, compare both current fields, calculate the new hash once, return the current workspace without increment when the content/hash are already equal, and otherwise call repository CAS with both expected values:

```python
if (
    int(current["revision"]) != command.expected_revision
    or current["content_hash"] != command.expected_content_hash
):
    raise ChapterSessionConflict("working draft revision or hash drift")
if current["content"] == command.content:
    return await self._workspace(session, chapter_session)

saved = await self.repository.upsert_working_draft(
    session,
    row,
    expected_revision=command.expected_revision,
    expected_content_hash=command.expected_content_hash,
)
```

Do not catch a CAS failure and retry with a newer revision.

- [ ] **Step 4: Run focused backend tests GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Add MySQL concurrency evidence**

Extend `test_authoritative_chapter_session.py` so two saves from the same base revision/hash race and exactly one commits; the loser returns conflict, one draft row remains, and no candidate is created.

Run serially:

```powershell
npm run test:integration
```

Expected: exit 0 and the disposable database ledger reports zero remaining databases.

- [ ] **Step 6: Commit CAS**

```powershell
git add backend/services/chapter_sessions.py backend/repositories/chapter_sessions.py backend/routers/chapter_sessions.py backend/tests/unit/test_chapter_session_service.py backend/tests/unit/test_chapter_session_repository.py backend/tests/api/test_chapter_session_routes.py backend/tests/integration/test_authoritative_chapter_session.py
git commit -m "feat: enforce working draft hash cas"
```

## Task 3: Exact idempotent candidate freeze

- [ ] **Step 1: Write RED tests for visible hash and idempotency**

Test same-key/same-fingerprint replay, same-key/different-fingerprint conflict, expected-hash drift, different key with the same candidate identity, and rollback if the request ledger cannot be inserted. The replay tests must also prove that a later candidate and a later `final` session state do not change the first request's public `savedCandidateId`.

```python
command = SaveDraftCandidate(
    project_id=PROJECT_ID,
    chapter_session_id=SESSION_ID,
    expected_working_draft_revision=3,
    expected_content_hash=sha256_text("屏幕正文"),
    idempotency_key="11111111-1111-4111-8111-111111111111",
)
first = await service.save_candidate(command)
second = await service.save_candidate(command)
assert first.saved_candidate_id == second.saved_candidate_id
assert len(repository.candidates) == 1
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_service.py backend/tests/unit/test_chapter_session_repository.py backend/tests/api/test_chapter_session_routes.py -q
```

Expected: missing command fields and freeze-request repository methods.

- [ ] **Step 3: Implement request fingerprint and ledger**

The strict route body is:

```python
class SaveCandidateBody(_StrictBody):
    expectedWorkingDraftRevision: int = Field(ge=1)
    expectedContentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotencyKey: str = Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{12}$"
        ),
    )
```

Build the fingerprint from public identity only:

```python
request_payload = {
    "projectId": command.project_id,
    "chapterSessionId": command.chapter_session_id,
    "workingDraftRevision": command.expected_working_draft_revision,
    "contentHash": command.expected_content_hash,
}
request_hash = canonical_hash(request_payload)
```

Inside one transaction:

1. lock project/session;
2. read an existing freeze request by `(session, idempotencyKey)` before mutable session-state checks;
3. replay only when `request_hash` matches, returning its recorded candidate ID even after later candidates or a later `final`/superseded state;
4. for a first-time key, require a drafting session and read/validate current Outline basis;
5. validate WorkingDraft revision and content hash;
6. insert or reuse the immutable candidate identity;
7. insert the freeze request referring to that actual persisted candidate;
8. return `CandidateSaveResult(workspace, saved_candidate_id)`; the route adds only `savedCandidateId` to the safe public workspace and never exposes the ledger or key.

Never put candidate content or provider payload in the request ledger.

- [ ] **Step 4: Run unit/API GREEN and MySQL replay evidence**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_service.py backend/tests/unit/test_chapter_session_repository.py backend/tests/api/test_chapter_session_routes.py -q
npm run test:integration
```

Expected: both commands exit 0; integration residue is zero.

- [ ] **Step 5: Commit candidate integrity**

```powershell
git add backend/repositories/chapter_sessions.py backend/services/chapter_sessions.py backend/routers/chapter_sessions.py backend/tests/unit/test_chapter_session_repository.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py backend/tests/integration/test_authoritative_chapter_session.py
git commit -m "feat: freeze visible draft candidates idempotently"
```

## Task 4: Unicode-safe plain-text range primitive

- [ ] **Step 1: Write range RED tests**

Create `plainTextRange.test.mjs` with BMP Chinese, emoji/astral characters, empty/reversed/out-of-bounds selections, exact selected text, and locating scalar offsets back in a textarea-like object.

```javascript
test('converts textarea UTF-16 selection through astral text to scalar offsets', () => {
  const text = '甲😀乙\n丙'
  const range = capturePlainTextRange(text, 1, 4)
  assert.deepEqual(range, {
    startOffset: 1,
    endOffset: 3,
    selectedText: '😀乙',
  })
  assert.deepEqual(scalarRangeToCodeUnits(text, 1, 3), {
    selectionStart: 1,
    selectionEnd: 4,
  })
})
```

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/plainTextRange.test.mjs
```

Expected: module-not-found failure.

- [ ] **Step 3: Implement the conversion and location helpers**

The module must export:

```javascript
export function capturePlainTextRange(text, selectionStart, selectionEnd)
export function scalarRangeToCodeUnits(text, startOffset, endOffset)
export function locatePlainTextRange(textarea, text, startOffset, endOffset)
```

Use `Array.from(text)` for scalar boundaries, reject invalid ranges instead of clamping, and call `focus()` plus `setSelectionRange()` only after validation. Do not search for evidence text.

- [ ] **Step 4: Run GREEN**

```powershell
node --test frontend/tests/unit/plainTextRange.test.mjs
```

Expected: all tests pass.

- [ ] **Step 5: Commit the range primitive**

```powershell
git add frontend/src/utils/plainTextRange.js frontend/tests/unit/plainTextRange.test.mjs
git commit -m "feat: add exact plain text selection ranges"
```

## Task 5: One-flight autosave coordinator

- [ ] **Step 1: Write deterministic RED tests with an injected clock**

Cover 800 ms debounce, 5-second max dirty window, one in-flight save, typing during save, failure/retry, explicit flush, disposal, and no save for unchanged text.

```javascript
test('save completion advances baseline without replacing newer typing', async () => {
  const pending = deferred()
  const state = createWorkingDraftAutosave({
    delayMs: 800,
    maxWaitMs: 5000,
    schedule: clock.schedule,
    cancel: clock.cancel,
    persist: () => pending.promise,
  })
  state.reset(authority('旧稿', 1, OLD_HASH))
  state.edit('准备保存')
  clock.advance(800)
  state.edit('保存期间继续写')
  pending.resolve(authority('准备保存', 2, SAVED_HASH))
  await state.whenIdle()
  assert.equal(state.text.value, '保存期间继续写')
  assert.equal(state.persistedRevision.value, 2)
  assert.equal(state.dirty.value, true)
})
```

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/workingDraftAutosave.test.mjs
```

Expected: module-not-found failure.

- [ ] **Step 3: Implement the coordinator**

Expose `text`, `dirty`, `status`, `persistedRevision`, `persistedHash`, `edit`, `reset`, `flush`, `retry`, `whenIdle`, and `dispose`. `persist` receives an immutable snapshot:

```javascript
{
  editGeneration,
  expectedRevision,
  expectedContentHash,
  content,
}
```

On response, always advance the persisted baseline; copy server content into the visible buffer only when the response generation still equals the current edit generation. A conflict status must preserve visible text and require reload/reconciliation, not automatically retry against a new revision.

- [ ] **Step 4: Run GREEN**

```powershell
node --test frontend/tests/unit/workingDraftAutosave.test.mjs
```

Expected: all tests pass.

- [ ] **Step 5: Commit autosave**

```powershell
git add frontend/src/application/writer/workingDraftAutosave.js frontend/tests/unit/workingDraftAutosave.test.mjs
git commit -m "feat: coordinate recoverable draft autosave"
```

## Task 6: API/store/controller flush boundaries

- [ ] **Step 1: Write RED tests**

In API tests, prove debug/provider fields are stripped and exact authority fields are sent. In store tests, prove save uses both workspace revision and hash. In controller tests, prove candidate and generation wait for `flush()` and use the post-flush revision/hash, and navigation rejects only busy or failed-unsaved states.

```javascript
test('candidate freeze flushes visible text and uses returned authority', async () => {
  const calls = []
  const controller = createChapterWriterController({
    autosave: fakeAutosave({ revision: 7, contentHash: HASH }),
    freezeCandidate: command => calls.push(command),
  })
  await controller.saveCandidate()
  assert.deepEqual(calls, [{
    expectedWorkingDraftRevision: 7,
    expectedContentHash: HASH,
    idempotencyKey: calls[0].idempotencyKey,
  }])
})
```

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
```

Expected: missing hash/idempotency fields and controller module.

- [ ] **Step 3: Implement strict frontend commands**

Update client/store calls to send:

```javascript
saveWorkingDraft: {
  expectedRevision,
  expectedContentHash,
  content,
}

saveCandidate: {
  expectedWorkingDraftRevision,
  expectedContentHash,
  idempotencyKey,
}
```

Generate candidate idempotency keys with the existing `newId()` UUID helper once per user action, not once per HTTP retry. Keep the existing store-wide write mutex. The controller must call `autosave.flush()` before candidate freeze and before the temporary synchronous generation command, then resynchronize autosave from the returned workspace only if no newer edit generation exists.

- [ ] **Step 4: Run GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Commit frontend command integrity**

```powershell
git add frontend/src/api/db/client.js frontend/src/stores/chapterSessionStore.js frontend/src/application/writer/chapterWriterController.js frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
git commit -m "feat: flush visible drafts before writer commands"
```

## Task 7: Plain-text editor and navigation integration

- [ ] **Step 1: Write source/controller RED tests**

Prove the product route imports `PlainTextDraftEditor`, has no “保存工作稿” button, exposes autosave status, does not use `contenteditable`, and uses async flush for route navigation. Keep behavior tests in controller/range modules; do not test Vue internals with string-only assertions when a behavior module can be tested directly.

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/writerCoreApi.test.mjs
```

Expected: view/source contract failures until the component is integrated.

- [ ] **Step 3: Build `PlainTextDraftEditor.vue`**

Use one `<textarea>` with `:value`, `@input`, `@select`, `@keyup`, and `@mouseup`. Emit `update:modelValue` and `selection-change`; expose `locateRange(startOffset, endOffset)` through `defineExpose`. Render word count and the five persistence states with `aria-live="polite"`. Do not render local AI buttons in 4A; Phase 4B connects them when actions exist.

- [ ] **Step 4: Replace manual save in `ChapterWriterView.vue`**

Wire the controller on load, dispose it on unmount, flush before candidate/generation, and make route guards await the controller navigation decision. Install `beforeunload` whenever `dirty || saving || saveFailed || writeBusy` is true and remove it immediately when all four are false. Keep the confirmed-outline link and existing authority load behavior. Delete `chapterEditorState.js` and its old test in the same change so no second buffer/baseline authority remains.

- [ ] **Step 5: Run focused frontend GREEN and build**

```powershell
node --test frontend/tests/unit/plainTextRange.test.mjs frontend/tests/unit/workingDraftAutosave.test.mjs frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/writerCoreApi.test.mjs
npm run build
```

Expected: all selected tests pass; Vite build exits 0.

- [ ] **Step 6: Commit UI integration**

```powershell
git add frontend/src/components/writer/PlainTextDraftEditor.vue frontend/src/views/ChapterWriterView.vue frontend/src/utils/chapterEditorState.js frontend/tests/unit/chapterEditorState.test.mjs frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/writerCoreApi.test.mjs
git commit -m "feat: autosave the plain text writer"
```

## Task 8: Phase 4A verification and reviews

- [ ] **Step 1: Self-review against the Phase 4 design**

Check:

- no manual draft-save action remains;
- every save uses revision plus content hash;
- save completion preserves newer typing;
- candidate freeze flushes first and has stable idempotency;
- Unicode astral selection round-trips;
- no local operation, audit, Canon, or finalization is falsely claimed;
- no browser-side provider path was introduced;
- no secret/provider body/DSN appears in public errors or tests.

- [ ] **Step 2: Run fresh focused gates**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/unit/test_chapter_session_repository.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py -q
node --test frontend/tests/unit/plainTextRange.test.mjs frontend/tests/unit/workingDraftAutosave.test.mjs frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/writerCoreApi.test.mjs
npm run test:integration
npm run build
git diff --check
```

Expected: every command exits 0; MySQL residue is zero; `git diff --check` is empty.

- [ ] **Step 3: Specification review**

Review the complete Phase 4A diff against `docs/superpowers/specs/2026-08-01-phase-4-writer-loop-design.md` and this plan. Resolve Critical/Important/Minor findings until `0/0/0`.

- [ ] **Step 4: Quality review**

After specification review is clean, review correctness, concurrency, maintainability, security, and test quality. Resolve Critical/Important/Minor findings until `0/0/0`.

- [ ] **Step 5: Controller fresh verification**

The controller reruns Step 2, inspects `git status --short`, audits owned test DB/process/port/temp/Vite cache residue, and records only exit codes, pass/fail counts, first root cause if any, and the resource ledger.

- [ ] **Step 6: Commit Phase 4A acceptance boundary**

```powershell
git add docs/superpowers/specs/2026-08-01-phase-4-writer-loop-design.md docs/superpowers/plans/2026-08-01-phase-4a-working-draft-integrity.md
git commit -m "docs: define phase 4 writer integrity"
```

Do not call Phase 4 complete. The next approved plan is Phase 4B Draft Operations, based on the accepted Phase 4A interfaces.
