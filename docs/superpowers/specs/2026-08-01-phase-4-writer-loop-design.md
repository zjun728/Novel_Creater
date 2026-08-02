# Phase 4 Writer Loop Design

**Status:** approved product direction; formal implementation baseline
**Date:** 2026-08-01
**Depends on:** Phase 3 immutable-boundary acceptance at `d4873e0`
**Primary source:** `docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`

Where an older design discusses replaceable Seed, Contract, or Bible revisions, the accepted Phase 3 immutable-boundary specification and acceptance evidence take precedence: the first confirmed Seed, Contract, and Bible are permanent project baselines; only unrealized Planning and an unfinalized chapter Outline may change.

## 1. Goal

Phase 4 turns the temporary chapter page into the authoritative prose workbench. An author can type in a plain-text editor, rely on recoverable autosave, generate or revise prose through one fenced AI-operation path, explicitly freeze candidates, load and compare candidates, and fuse two candidates back into the mutable working draft.

The product must preserve the exact text the author can see. No delayed save, provider result, candidate command, or stale browser response may overwrite newer typing.

## 2. Product boundary

Phase 4 includes:

- one plain-text `WorkingDraft` editor;
- debounced CAS autosave with visible persistence state;
- generation of a new chapter working draft;
- full-draft rewrite;
- exact-selection rewrite, AI polish, expansion, and compression;
- recoverable draft replacement and undo;
- persistent operation attempts, lease, heartbeat, fencing, cancellation, status, and streamed output;
- explicit immutable candidate freeze;
- candidate load, selection of at most two candidates, comparison, and fusion;
- a formal three-column desktop workbench and a UI-only browser gate.

Phase 4 does not include:

- quality or AI-flavour audit execution;
- audit scores or audit records;
- Canon extraction or mutation;
- Setting, memory, character-arc, clue, or realization projections;
- `FinalizationChangeSet`, confirmation, or finalization;
- real-provider, live-site, product-database, or novel-quality readiness claims.

Phase 5 will consume the selection-location contract defined here. It will not replace the editor or invent a second range system.

## 3. Author workflow

The fixed chapter workflow is:

1. Open the authoritative chapter route and load the confirmed outline, the single ChapterSession, the current WorkingDraft, recoverable replacements, and candidates.
2. Type or paste prose. The editor autosaves without creating a candidate.
3. Generate a new working draft, rewrite the full draft, or select exact text and run a local operation.
4. Review the completed replacement in the WorkingDraft and undo it if needed.
5. Explicitly save the visible, persisted WorkingDraft as an immutable candidate.
6. Load a candidate into the WorkingDraft, compare at most two candidates, or fuse exactly two candidates into a new WorkingDraft revision.
7. Leave quality audit and finalization to Phase 5.

There is no manual “保存工作稿” button. “保存为候选” remains explicit and never runs automatically.

## 4. Plain-text editor and exact selection

### 4.1 Editor primitive

`PlainTextDraftEditor` wraps one native plain-text textarea. It does not use rich text, Markdown blocks, HTML, or a `contenteditable` document model. The canonical browser buffer is one JavaScript string.

Textarea `selectionStart`/`selectionEnd` values are UTF-16 code-unit positions and are never sent directly as cross-language offsets. A dedicated range helper converts them to Unicode scalar-value offsets for API requests and converts scalar offsets back to textarea positions for location. Python applies the scalar offsets to its Unicode string. Hashes use the exact selected string encoded as UTF-8; neither side performs Unicode normalization. This preserves astral characters and prevents browser/server range drift.

The editor exposes:

- current text;
- `selectionStart` and `selectionEnd`;
- focus and deterministic range selection;
- scroll-to-selection;
- read-only operation mode;
- word count and autosave status.

No invisible formatting or DOM-node mapping may alter offsets.

### 4.2 Author selection tools

When `selectionStart < selectionEnd`, the editor shows a light selection toolbar with:

- 局部改写 (`rewrite_selection`);
- AI 润色 (`polish_selection`);
- 扩写 (`expand_selection`);
- 压缩 (`compress_selection`);
- one optional instruction that applies only to that operation.

AI polish reduces explanation, summary voice, formulaic parallelism, repeated meaning, generic character voices, and mechanical phrasing while preserving facts, intent, point of view, relationships, and emotional direction. It is not an automatic quality verdict.

The captured selection is immutable operation input:

```text
baseWorkingDraftRevision
baseWorkingDraftHash
startOffset
endOffset
selectedTextHash
operationType
authorInstruction
```

The backend validates the revision, whole-draft hash, bounds, and selected-text hash. It never searches for a matching substring.

### 4.3 Applying a local result

The original WorkingDraft remains unchanged while output is running. The UI shows real streamed output in a separate buffer. After the provider result is complete, the server constructs:

```text
base[0:startOffset] + providerResult + base[endOffset:]
```

and commits it with the operation fence in one short transaction. Only then does the browser replace its editor buffer. All text outside the selected range must remain byte-for-byte equivalent after UTF-8 encoding.

Cancellation commits the latest safe persisted non-empty partial to the WorkingDraft. Empty partial, failure, and expiry preserve the prior WorkingDraft. A stale selection, provider failure, disconnect, or lease expiry cannot overwrite the prior WorkingDraft.

### 4.4 Phase 5 audit location contract

An audit finding will bind to candidate ID, candidate content hash, start/end offsets, selected-text hash, category, reason, and suggestion. Clicking a finding will call the same editor range-selection primitive, scroll to the evidence, focus the editor or read-only candidate viewer, and present the same selected state as a mouse selection.

Clicking a finding only locates evidence; it never edits text. The author must explicitly choose “按建议改写”, “AI 润色”, or ignore the suggestion.

If the active WorkingDraft hash differs from the audited candidate hash, the product must not apply old offsets to new text. It opens that immutable candidate read-only at the exact range and offers “载入此候选到工作稿”.

## 5. Autosave integrity

### 5.1 Persistence state

The editor footer shows exactly one of:

- 未暂存;
- 正在暂存;
- 已暂存 HH:mm:ss;
- 暂存失败，重试;
- 与服务端版本冲突.

Autosave starts 800 ms after the last edit and has a 5-second maximum dirty window. Only one save request is in flight. If typing continues during a save, the response advances the persisted baseline but does not replace the newer local buffer; the next save flushes the newer generation.

### 5.2 CAS request

Every autosave submits:

```text
expectedWorkingDraftRevision
expectedContentHash
content
```

The server locks the project/session/draft, rechecks that the project is active and the session is drafting, validates both CAS values, writes revision `+1`, and returns the authoritative workspace. A conflict never overwrites either side.

### 5.3 Flush boundaries

The client stops the debounce timer and flushes visible text before:

- any AI operation;
- candidate freeze;
- candidate load;
- candidate fusion;
- application route navigation.

Normal application navigation waits for a successful flush and is blocked only while a write operation is active or when unsaved text cannot be persisted. A browser refresh or tab/window close cannot await that flush, so `beforeunload` is registered whenever the buffer is dirty, an autosave is in flight, autosave has failed, or a write operation is active; it is removed immediately after the draft is safely persisted and idle.

## 6. Draft recovery records

`WorkingDraft` remains the only mutable current buffer. Phase 4 adds immutable `WorkingDraftRevision` recovery records for consequential replacements, not for every keystroke autosave.

Before and after each successful generation, full rewrite, local operation, candidate load, fusion, or undo, the server records the exact content, hash, working-draft revision, replacement reason, operation/candidate source ID when present, and timestamp.

Undo never decrements the active revision. It copies a selected recovery record into a new WorkingDraft revision under CAS, preserving an append-only recovery trail.

## 7. Draft operation model

### 7.1 Operation types

The single operation service accepts:

- `generate_new`;
- `rewrite_full`;
- `rewrite_selection`;
- `polish_selection`;
- `expand_selection`;
- `compress_selection`;
- `fuse_candidates`.

Only `generate_new` ignores current prose as creative input. `rewrite_full` uses the full persisted draft. Local operations use only the exact selected text plus the minimum surrounding/context manifest needed to preserve continuity. Fusion reads exactly two immutable candidates.

### 7.2 Persistent attempt

Every request creates or replays a `DraftOperationAttempt` with:

- operation and project/session identity;
- idempotency key and request fingerprint;
- operation type and public status;
- base draft revision/hash;
- optional exact selection coordinates/hash;
- optional two candidate IDs/hashes;
- immutable context/model/input manifest and manifest hash;
- monotonically increasing fencing token;
- lease and heartbeat times;
- last public event sequence;
- bounded partial output;
- stable public error code;
- committed result revision/hash when successful;
- timestamps.

Statuses are `starting`, `running`, `completed`, `failed`, `cancelled`, and `expired`. Partial output is diagnostic/recovery data for the attempt; it is not a WorkingDraft revision or candidate.

### 7.3 Lease and fencing

The server locks the ChapterSession to acquire the single active draft operation. Acquisition increments the session fencing counter and stores the active operation ID. Heartbeats extend only the matching operation and fencing token.

The final commit locks the session and WorkingDraft and revalidates:

- active operation ID;
- fencing token;
- unexpired lease;
- session is still drafting;
- base WorkingDraft revision/hash;
- selection or candidate inputs;
- pinned context manifest remains valid.

A late or superseded result may finish its attempt record but cannot mutate the WorkingDraft.

An unfinalized chapter Outline may be adjusted under the accepted immutable-boundary rules. Every new operation reads the server-authoritative current confirmed Outline and records it in the immutable context manifest; the ChapterSession's entry pins remain historical entry identity. If the current Outline or unrealized Planning basis changes while an operation is running, the final manifest fence rejects that result. Existing draft text remains editable and recoverable, and candidates retain their own basis status.

Provider calls occur outside database transactions. No transaction remains open while waiting for model output or streaming to the browser.

### 7.4 Events, reconnect, and cancellation

Public event types are:

- `started`;
- `delta`;
- `heartbeat`;
- `completed`;
- `failed`;
- `cancelled`.

Every event carries operation ID and monotonically increasing sequence. Persisted events are bounded by operation output limits and support reconnect after a known sequence. If exact events are no longer retained, the status endpoint returns the attempt state, current bounded partial output, and committed result metadata without starting another provider call.

Providers that support streaming emit real deltas. Non-stream providers emit progress heartbeats and one completed result; the application never fabricates token chunks.

Cancellation marks the matching attempt and signals the in-process provider task. Cancellation commits the latest safe persisted non-empty partial to the WorkingDraft. Empty partial, failure, and expiry preserve the prior WorkingDraft. A result arriving after cancellation fails the final fence and cannot alter the draft. Server restart leaves a running attempt recoverable as expired after its lease; the original draft remains authoritative.

## 8. Candidate semantics

### 8.1 Freeze

Candidate freeze first flushes the visible buffer, then submits persisted WorkingDraft revision/hash and a client-generated canonical lowercase UUID idempotency key. Restricting the key to UUID form prevents arbitrary secret-shaped values from being stored in the request ledger. The server locks and rechecks both values, current outline/planning basis, and session status before freezing exactly that content.

Candidate content and provenance are immutable. Candidate identity remains `(chapter_session_id, content_hash, basis_hash)`. A separate freeze-request record maps idempotency key and request fingerprint to the returned candidate so same-key replay is stable and same-key/different-request conflicts. A successful first request and every replay explicitly return the same public `savedCandidateId`; a recorded replay remains stable after later candidates or session-state changes, while a first-time freeze still requires a drafting session.

### 8.2 Load and undo

Loading a candidate copies its immutable content into a new WorkingDraft revision after a CAS check. It never edits, deletes, or reactivates the candidate and never changes the ChapterSession entry pins. The previous and resulting WorkingDraft contents are recovery records.

### 8.3 Compare and fusion

The right column permits zero, one, or two selected candidates. Exactly two enables side-by-side comparison and fusion. Comparison is read-only and identifies each candidate by author-facing name, creation time, word count, source operation, model, current/stale basis status, and content hash abbreviation.

Fusion is an AI operation over exactly those two immutable candidate hashes plus an optional one-use author instruction. Its result becomes a new WorkingDraft revision, not a candidate. The author must explicitly save it as a candidate.

## 9. Three-column workbench

At desktop widths the route uses:

- left: chapter identity, confirmed outline, current StoryBlock/Stage/SceneTask context, and collapsed basis details;
- centre: the plain-text editor, selection toolbar, operation output, word count, autosave state, and primary action;
- right: candidates, recoverable replacements, selection/compare/fusion controls, and a reserved Phase 5 audit area.

The centre editor retains a readable measure. At narrower desktop widths the side columns become drawers; the centre is not squeezed below a usable writing width. Formal acceptance covers 1280×720 and above, with 1440 and 1920 widths checked explicitly.

While an operation is `starting` or `running`, the workbench has one shallow read-only overlay. Text remains readable and scrollable, but editing, paste, selection tools, candidate changes, and chapter navigation are disabled. The author can cancel supported operations and can stop auto-follow by scrolling upward.

## 10. API surface

The formal route family is:

```text
GET    /api/projects/{pid}/chapter-sessions/{chapter_number}
PUT    /api/projects/{pid}/chapter-sessions/{session_id}/working-draft
POST   /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations
GET    /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}
GET    /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}/events
POST   /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}/cancel
POST   /api/projects/{pid}/chapter-sessions/{session_id}/candidates
POST   /api/projects/{pid}/chapter-sessions/{session_id}/candidates/{candidate_id}/load
POST   /api/projects/{pid}/chapter-sessions/{session_id}/working-draft/undo
```

The current synchronous `generate-working-draft` route is removed when the unified operation route becomes live; no compatibility route, hidden UI action, or second write path remains.

All bodies reject unknown fields. Public responses omit provider request/response bodies, secrets, DSNs, raw exceptions, internal leases, and unbounded partial output.

## 11. Data model

The exact bootstrap schema advances from `writer-core-v1.6.0` to the next Phase 4 version and adds:

- `working_draft_revisions`;
- `draft_operation_attempts`;
- `draft_operation_events`;
- `candidate_freeze_requests`;
- ChapterSession active-operation and fencing fields.

Existing `working_drafts` and `draft_candidates` remain authoritative for current draft and immutable candidates. Phase 4 does not add quality, Canon, memory, Setting, or finalization writes.

The project still initializes an empty database from the current exact schema. This phase does not implement an in-place production migration or read a product database.

## 12. Security and external boundaries

- Automated tests use an injectable fake provider only at the outbound gateway boundary.
- No automated gate calls a real model, real provider, live website, or product database.
- Browser tests interact through visible UI only: no `page.request`, `page.route`, browser `fetch`/Axios, `page.evaluate` mutation, or direct database write.
- Provider keys, base URLs, model payloads, response bodies, DSNs, and author prose are not emitted to general logs or test summaries.
- Safe diagnostics report fixed categories, loopback method/path/status, counts, operation state, and resource ownership only.
- Test databases use only owned `novel_creator_test_%` names and prove create/cleanup parity.
- Runner cleanup is limited to proven owned process, port, temp root, and Vite cache resources.

## 13. Delivery slices

Phase 4 is delivered as sequential vertical slices:

1. **4A WorkingDraft Integrity:** schema foundations, revision/hash CAS, autosave coordinator, navigation flush, plain-text selection primitive, candidate freeze integrity.
2. **4B Draft Operations:** persistent attempts, lease/fence/events, generate/full/local operations, streaming/reconnect/cancel, recovery and undo.
3. **4C Candidate Workbench:** load, two-candidate compare, fusion, metadata, and three-column integration.
4. **4D Formal Gate:** UI-only fake-provider browser scenarios, source contracts, security/resource ledger, acceptance evidence, full regression, and Phase 4 commit/push.

MySQL integration, build, and browser gates run serially. Each slice uses TDD, implementer self-review, specification review to `0/0/0`, then quality review to `0/0/0` before the controller accepts it.

## 14. Acceptance criteria

Phase 4 is complete only when fresh evidence proves:

- typing is debounced and persisted without a manual save button;
- a save response cannot overwrite text typed after that save began;
- autosave conflict preserves local and server content and blocks unsafe continuation;
- every long operation flushes the visible buffer first;
- provider waiting holds no database transaction;
- only one fenced write operation can affect a session;
- cancellation, expiry, stale result, and reconnect never duplicate generation or overwrite the draft;
- local operations replace only the exact selected range;
- a completed replacement is undoable through an append-only new revision;
- candidate freeze captures the visible persisted hash and is idempotent;
- candidate load leaves the candidate immutable;
- no more than two candidates can be compared and fusion returns only a WorkingDraft;
- the browser can select text and invoke all four local tools through visible UI;
- the common location primitive can scroll to and select an exact supplied range for Phase 5;
- Python, root Node, frontend unit, disposable MySQL integration, build, and formal Phase 4 browser gates pass fresh;
- browser summary reports expected scenario count and zero unsafe diagnostics;
- owned database/process/port/temp/Vite-cache residue is zero;
- no real provider, product database, Canon write, audit, or finalization claim appears in acceptance evidence.
