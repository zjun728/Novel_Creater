# Lean Product Scope and Phase 4B3 Selection Tools Design

## 1. Goal

Correct the remaining authority conflicts that encourage unnecessary state and deliver the
smallest safe local-editing slice: exact-selection rewrite, polish, expand, compress, and a
single safe append-only undo.

This design reuses the accepted Phase 4B2 operation boundary. It does not create a second AI
write path, add a table, expand the market scheduler, or pull candidate fusion, finalization,
backup/import, real providers, or product databases into Phase 4B3.

## 2. Authority and precedence

This document supersedes any older product or Phase specification that permits:

- selecting a different Seed after the first Seed confirmation;
- creating a replacement Contract after the first Contract confirmation;
- creating a replacement Bible after the first Bible confirmation;
- treating confirmed Seed, Contract, or Bible revisions as switchable active branches.

The approved permanent sequence is:

```text
Seed -> Contract -> Bible -> Planning -> Chapter Outline -> Working Draft
```

The first confirmed Seed, Contract, and Bible are permanent project baselines. They cannot be
edited, replaced, reactivated, or switched. Planning may change only unrealized future
volumes, plots, StoryBlocks, stages, tasks, and Chapter Outlines. A Chapter Outline may change
until its chapter prose is finalized; finalization permanently locks the corresponding
Outline and realized facts.

Historical database rows and read-only history may remain, but no current UI, store, route,
or service may advertise a successful post-confirmation baseline replacement.

## 3. Product scope reduction

The following decisions prevent this slice from reopening the over-designed roadmap:

- Automatic market scheduling is deferred. Manual refresh/import remains sufficient for the
  current product; Phase 4B3 does not extend scheduler behavior or shutdown ownership.
- Phase 4C will separately deliver candidate load and two-candidate read-only comparison.
  AI candidate fusion is deferred until the core finalization loop is usable.
- Phase 5 will separately define one persisted ChangeSet, one author review, and one atomic
  commit. Phase 4B3 does not prebuild that state machine.
- Phase 6 first delivers finalized-prose TXT/Markdown download. Full package backup/import is
  deferred.
- Thirty-chapter human content acceptance is a separate content-quality activity and does not
  block the engineering completion of the first usable product loop.

Already accepted Phase 4B2 code is not rewritten merely to reduce conceptual complexity.
Future work reuses it without adding another lease, heartbeat, fencing, registry-transfer, or
event-lifecycle layer.

## 4. Phase 4B3 scope

Phase 4B3 delivers exactly these operation types:

- `rewrite_selection`;
- `polish_selection`;
- `expand_selection`;
- `compress_selection`.

It also delivers one-step undo for the most recent successfully applied local AI replacement.

Phase 4B3 does not deliver full-draft rewrite, candidate load, candidate comparison, candidate
fusion, quality audit, Canon writes, finalization, download, backup, import, real-provider
quality, or product-database readiness.

## 5. Existing boundaries to reuse

- `PlainTextDraftEditor` remains the only prose editor.
- Browser textarea UTF-16 positions continue to map to Unicode scalar offsets through the
  existing `plainTextRange` utility.
- `working_drafts` remains the single mutable current buffer.
- `working_draft_revisions` remains the append-only recovery history.
- `draft_operation_attempts` and `draft_operation_events` remain the sole persistent operation
  and reconnect records.
- The existing draft-operation status, event, cancellation, task registry, provider gateway,
  and pool ownership are reused unchanged unless an observed local-operation requirement
  cannot be expressed by their current public contract.
- Provider calls remain outside database transactions.

No database table, database column, or parallel synchronous AI endpoint is added. The exact
bootstrap schema only broadens the existing `draft_operation_attempts.operation_type` check to
the four local types and the existing `working_draft_revisions.replacement_reason` check to
those types plus `undo_local`. Selection data stays inside the closed input manifest. The
existing `working_drafts.source_payload_json` records whether the current revision came from a
local operation, manual autosave, another replacement, or undo.

## 6. Selection request contract

The existing draft-operation creation route accepts the four new operation types. A local
operation request contains:

- `expectedWorkingDraftRevision`;
- `expectedContentHash`;
- `startOffset` and `endOffset` as Unicode scalar offsets;
- `selectedTextHash`, the lowercase SHA-256 of the exact selected UTF-8 text;
- optional one-use `authorInstruction`, trimmed and limited to 1,000 Unicode scalar values;
- canonical lowercase UUID `idempotencyKey`.

The selection must be non-empty. The backend reads the authoritative WorkingDraft, validates
the revision/hash, slices by Unicode scalar offsets, and verifies `selectedTextHash`. The
browser does not send the selected prose as an authoritative replacement target.

The provider input contains the exact selected text, the operation intent, the optional
author instruction, and no more than 300 Unicode scalar values of authoritative WorkingDraft
context on each side. It may include the current confirmed Chapter Outline summary already
present in the operation context manifest. It does not receive all candidates, the complete
corpus, unrelated Canon, or another hidden copy of the full draft.

## 7. Streaming and application

Local-operation deltas represent replacement text only. They appear in a bounded replacement
preview associated with the selected range; they do not stream into the main editor and do
not mutate WorkingDraft state.

On provider completion, the backend performs a short final transaction:

1. lock the ChapterSession and WorkingDraft;
2. revalidate active operation identity/fence, session state, base revision/hash, exact scalar
   range, and selected-text hash;
3. reconstruct the full prose as `prefix + replacement + suffix`;
4. persist the pre-operation full prose as a `working_draft_revisions` recovery record;
5. update `working_drafts` to base revision plus one and its new content hash;
6. persist the result revision/hash on the operation attempt and derive the resulting range as
   `startOffset + replacement scalar length` in the terminal public snapshot;
7. set the WorkingDraft source payload to the local operation ID/type, complete the operation,
   and publish the terminal event.

The frontend accepts only a terminal response whose operation ID, revision, content hash, and
full normalized WorkingDraft snapshot agree. It replaces the editor from that server snapshot
and selects the inserted replacement range. It never assembles or persists the authoritative
full result by applying a raw delta locally.

## 8. Failure and cancellation

For all four local operations, cancellation, failure, expiry, provider timeout, malformed
output, reconnect exhaustion, or final-fence conflict preserves the original WorkingDraft.
Non-empty partial local output may remain as bounded operation evidence/preview, but it is
never committed as a partial selection replacement.

This local-operation rule is intentionally stricter than any accepted `generate_new`
cancellation behavior. It does not change the already accepted `generate_new` contract.

Stable public failures include:

- selection required or out of bounds;
- selected text changed;
- WorkingDraft revision/hash drift;
- another write operation is active;
- Provider unavailable or timed out;
- replacement output empty or invalid;
- undo unavailable because the result is no longer current.

Failures retain the author's visible prose and one-use instruction. Logs and artifacts never
contain the selection, replacement, surrounding prose, provider body, secrets, or DSN.

## 9. One-step append-only undo

The formal undo route is:

```text
POST /api/projects/{pid}/chapter-sessions/{session_id}/working-draft/undo
```

The request contains the current expected WorkingDraft revision/hash and the source local
operation ID. Undo is available only when:

- the latest completed WorkingDraft-changing action is one of the four Phase 4B3 local
  operations;
- the current WorkingDraft revision/hash exactly equals that operation's committed result;
- the WorkingDraft source payload still names that local operation;
- no manual autosave, candidate load, generation, later local operation, or prior undo has
  changed the WorkingDraft.

The undo transaction locks the session and WorkingDraft, revalidates those conditions, appends
a recovery record for the current result, and writes a new WorkingDraft revision containing
the recorded pre-operation prose with an `undo_local` source payload. It never decrements a
revision, deletes an operation, edits a candidate, or mutates history.

Undo deliberately does not add an idempotency ledger or a synthetic Provider operation. A
duplicate or result-unknown request fails its expected revision/hash CAS; the frontend reloads
the authoritative workspace to determine whether the restoration already committed. If the
author has edited or replaced the result, the UI hides the ordinary undo action and the backend
still rejects stale requests fail-closed.

Phase 4B3 supports only this most-recent AI replacement undo. It does not implement a general
editor undo stack or historical operation picker.

## 10. UI behavior

- A compact selection toolbar appears only for a non-empty valid selection.
- It exposes four actions: 改写、润色、扩写、压缩.
- The existing one-use author instruction applies to the selected action only.
- Starting a local operation flushes autosave through the existing coordinator, then enters
  the existing shallow read-only operation overlay.
- The replacement preview is visually separate from the authoritative editor.
- Cancel remains available while the provider operation is cancellable.
- After successful application, a single 撤销本次 AI 修改 action appears while the result
  remains current.
- Manual input or any later WorkingDraft-changing action removes that action immediately.
- No additional modal, history drawer, three-column redesign, or candidate control is added in
  this slice.

## 11. Testing and evidence

Development follows `docs/testing/test-gate-policy.md`.

Focused RED/GREEN evidence covers:

- Unicode scalar range validation, including supplementary characters and unpaired-surrogate
  refusal at the browser boundary;
- request DTO strictness and selected-text hash verification;
- prompt/context minimization for all four operation types;
- final application replacing only the exact range;
- failure/cancellation preserving the original WorkingDraft;
- reconnect publishing the same terminal result without a second provider call;
- one-step undo success, duplicate/stale conflict, manual-edit invalidation, and append-only
  revision behavior;
- frontend toolbar visibility, operation dispatch, replacement preview, terminal snapshot
  adoption, inserted-range selection, and undo visibility.

Slice evidence contains the affected Python unit/API tests, affected frontend/root Node tests,
affected disposable-MySQL operation tests, production frontend build, and one narrow UI-only
fake-provider browser scenario covering the four visible tools plus undo. It does not run the
complete 364-test MySQL suite or full historical browser matrix.

The complete unit, integration, build, formal Phase 4 browser, and residue matrix runs once at
Phase 4 close, not at Phase 4B3 slice close.

## 12. Acceptance criteria

- All four actions are reachable only from a valid visible selection.
- The backend rejects stale revision/hash, invalid scalar range, and selected-text hash drift
  before any provider side effect.
- Provider input is limited to the selected text, bounded adjacent context, current operation
  intent, optional one-use instruction, and minimum confirmed Outline context.
- Streaming output never mutates the editor before a successful terminal commit.
- Successful completion changes only the exact selected range and advances WorkingDraft by one
  revision.
- Local cancellation, failure, expiry, and stale completion preserve the original WorkingDraft.
- The successful terminal snapshot, not raw client deltas, becomes the visible editor state.
- Undo is append-only, CAS-protected, limited to the latest untouched local result, and rejected
  after duplicate, manual, or later writes.
- No new database table, synchronous AI write route, scheduler behavior, candidate/fusion
  behavior, Canon write, finalization behavior, backup/import behavior, real-provider call, or
  product-database access is introduced.
