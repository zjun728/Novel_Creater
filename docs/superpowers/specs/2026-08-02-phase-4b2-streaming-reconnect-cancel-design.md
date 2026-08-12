# Phase 4B2 Streaming, Reconnect, and Cancel Design

**Date:** 2026-08-02
**Status:** User-approved design, pending implementation plan
**Baseline:** Phase4B1 formal `generate_new` accepted at `3aaa8f3` with an
injected fake provider

## 1. Goal

Phase4B2 turns the accepted persistent `generate_new` operation into a real
streaming operation when the bound provider profile enables and supports
streaming. It adds automatic reconnect, bounded persisted partial output, lease
heartbeat renewal, and idempotent cancellation. A bound non-streaming profile
keeps the same persistent operation lifecycle but exposes heartbeats and only a
terminal result.

The author sees genuine provider output appear in the existing plain-text正文
editor. The editor is a read-only preview while the operation is running. A
completed operation atomically replaces the WorkingDraft. Cancellation stops
further generation and, when non-empty safe partial output exists, atomically
saves that partial output as the next editable WorkingDraft revision.

## 2. Accepted product decisions

### 2.1 WorkingDraft remains recoverable

WorkingDraft is an auto-saved mutable workspace, not an author-confirmed
Candidate and not finalized prose. Refresh, browser restart, or reconnect never
discards a persisted WorkingDraft merely because the author has not frozen a
Candidate.

The three visible states remain distinct:

1. streamed preview: an active operation's bounded partial output;
2. WorkingDraft: mutable, auto-saved, and recoverable across refresh;
3. Candidate: an explicit immutable checkpoint created only by the author.

Discarding or restoring a WorkingDraft requires an explicit author action.
Refresh itself is never a destructive command.

### 2.2 Cancel means stop, not discard

If cancellation wins the terminal fence:

- a non-empty normalized partial output becomes a new WorkingDraft revision;
- before/after recovery snapshots and the terminal `cancelled` event commit in
  the same transaction;
- an empty or whitespace-only partial output leaves the existing WorkingDraft
  unchanged;
- no Candidate is created automatically.

The previous WorkingDraft remains available through the append-only recovery
record. A repeated cancel request is idempotent and cannot create another
revision.

### 2.3 Automatic reconnect

Opening or refreshing a ChapterSession automatically discovers its active draft
operation. The browser restores the complete persisted partial snapshot, resumes
event polling after the last applied sequence, and never creates a new operation
or idempotency key during reconnect.

## 3. Scope

Phase4B2 includes only:

- real provider-to-backend streaming for `generate_new` when the bound profile
  has both `stream` and `supportsStreaming` enabled;
- immediate `running` POST responses and supervised in-process execution;
- bounded persisted partial output;
- `delta`, `heartbeat`, and `cancelled` public events;
- lease renewal and restart expiry;
- automatic browser reconnect and event pagination;
- an idempotent cancel route;
- cancellation that preserves non-empty partial output as WorkingDraft;
- the existing plain-text editor's streaming preview and cancel UI;
- fake-streaming-provider automated acceptance.

Phase4B2 does not include:

- `rewrite_full`, selection rewrite, polish, expansion, or compression;
- recovery browsing or undo UI;
- Candidate compare, fusion, or Phase4C layout work;
- Phase4D browser acceptance or a Phase4B-complete claim;
- a real-provider quality claim, product-database readiness, or live-site use;
- any automatic DeepSeek call.

## 4. Architecture choice

The provider-to-backend connection uses the provider's real SSE stream. The
backend-to-browser connection continues to use the existing persisted status and
events APIs with one-second polling. Browser SSE and WebSocket transports are
deliberately not added.

This choice reuses the accepted operation identity, owner checks, event cursor,
idempotency key, and fenced database state. It also makes reconnect deterministic
without adding a second transient delivery protocol.

```text
browser POST
  -> reserve transaction
  -> return running operation
  -> supervised in-process provider task
       -> provider SSE outside every DB transaction
       -> bounded delta/heartbeat transactions
       -> completed/cancelled/failed/expired fenced terminal transaction

browser GET status/events every 1s
  -> partial snapshot + events after sequence
  -> read-only preview in the正文 editor
```

## 5. Backend components

### 5.1 Streaming provider gateway

Provider resolution adds the existing profile fields `stream` and
`supports_streaming` to the frozen writing-provider authority snapshot. The
runner selects streaming only when both fields are true. This decision is fixed
for the operation; later profile edits cannot change an already reserved
attempt.

`ChapterDraftProviderGateway` gains a streaming method that sends
`"stream": true` and yields validated text deltas. The B1 non-streaming method
is used when either frozen field is false; it emits progress heartbeats and one
final result, never fabricated token deltas. A selected streaming request that
fails HTTP, framing, validation, timeout, or transport checks fails the
operation. It never silently retries through the non-streaming method.

The streaming parser must:

- request `Accept-Encoding: identity`;
- reject compressed, listed, repeated, or unknown content encodings before body
  iteration;
- count raw wire bytes and stop at the existing chapter-draft hard ceiling of
  1 MiB;
- impose one 20-minute absolute deadline across the complete provider stream;
- accept only valid UTF-8 SSE framing and OpenAI-compatible data objects with
  exactly choice index `0`; `delta.content` may be absent or null for a
  role/finish frame, but when present it must be text;
- accept the terminal `[DONE]` marker only in its valid position;
- reject malformed, recursive, oversized, or non-text chunks with one fixed safe
  gateway error;
- never attach the remote exception cause or log a raw event, provider body,
  prompt, key, or base URL.

The complete accumulated prose remains bounded to 100,000 Unicode scalar values.
Before any partial output is persisted or exposed, the cumulative partial text is
validated without trimming and scanned against the frozen provider-secret
baseline. Scanning the cumulative value, rather than individual chunks, catches
secrets split across chunk boundaries. Completion and cancellation apply the
existing terminal provider-text validator with `strip=True`. The normalized
terminal text, hash, and scalar count replace the attempt snapshot atomically so
the public terminal operation and any resulting WorkingDraft describe the exact
same content. Empty normalized completion fails; empty normalized cancellation
leaves the WorkingDraft unchanged.

### 5.2 Operation launcher and task registry

Create POST performs only reserve work synchronously. A successful new reserve
returns a `running` operation immediately and launches exactly one supervised
`asyncio` task. Same-key replay returns the stored operation and never launches a
second task.

An application-scoped registry maps operation ID to an opaque task handle and
cancel signal. It contains no prompt, provider secret, response body, partial
output, or authority snapshot. Database ownership and fencing remain the source
of truth; registry membership never authorizes a write.

The registry removes completed tasks with a done callback. Application shutdown
cancels and awaits registered tasks without converting shutdown cancellation into
a business failure. A process crash after reserve but before task launch leaves a
running operation that expires through its lease; it is never automatically
reissued to the provider.

### 5.3 Delta batching and heartbeat

Provider chunks are accumulated before persistence. A delta batch is flushed
when either:

- at least 256 Unicode scalars are buffered; or
- one second has elapsed since the previous persisted delta.

Every accepted flush uses a short transaction and requires the exact project,
ChapterSession, operation ID, fencing token, `running` status, active ownership,
unexpired lease, previous partial hash, and previous event sequence. The same
transaction appends the text to the bounded partial snapshot, updates its hash and
scalar count, extends the lease, and inserts the next `delta` event.

An independent heartbeat runs every 10 seconds when no delta transaction has
renewed the lease during that interval. It extends the matching lease to 30
seconds from the heartbeat time and appends one `heartbeat` event. Provider wait
and timer wait occur outside every database transaction.

At most 2,048 public events may be persisted for one operation. The batching,
one-second cadence, 20-minute provider read bound, and heartbeat suppression keep
valid operations below that ceiling. Attempting to exceed the event or content
bound fails closed as `DraftProviderResultInvalid`; it does not commit partial
output as WorkingDraft.

### 5.4 Terminal state machine

Persistent statuses are:

```text
starting | running | completed | failed | cancelled | expired
```

There is no persistent `cancelling` status. `正在取消` is a local UI request state.

Completion, cancellation, validation/provider failure, and expiry all compete
through the same operation ID + fencing token + active-session ownership fence.
Only one terminal transition can commit.

- If completion wins, cancellation returns the completed operation.
- If cancellation wins, the task signal is sent after the database terminal
  transaction and any late provider result fails the fence.
- If failure or expiry wins, partial output remains bounded attempt-recovery data,
  exposed only by the owner-scoped operation APIs, and never replaces the
  WorkingDraft.
- If a terminal operation is cancelled again, the existing terminal result is
  returned without mutation.

Cancellation commits only the latest persisted partial snapshot. Text still in
the provider task's private batching buffer has never been shown through the
public snapshot and is discarded after the cancellation fence wins; it cannot be
smuggled into the WorkingDraft by the late task.

Status reads may naturally expire an elapsed running lease in a short fenced
transaction. They never start or resume provider work.

## 6. Persistence model

`draft_operation_attempts` adds bounded streaming state:

```text
partial_output_text       LONGTEXT NOT NULL
partial_output_hash       CHAR(64) NOT NULL
partial_output_scalars    INT NOT NULL
heartbeat_at              BIGINT NOT NULL
cancelled_at              BIGINT NULL
```

The empty partial uses the SHA-256 hash of empty UTF-8 bytes and scalar count 0.
Schema checks require non-negative scalar count, valid terminal correlations, and
`cancelled_at` only for `cancelled` attempts. A cancelled operation may have
result revision/hash both present or both absent. Other existing status/result
correlations remain fail closed.

`draft_operation_events.event_type` expands to:

```text
started | delta | heartbeat | completed | failed | cancelled
```

Event payloads are closed:

- `started`: no payload;
- `delta`: `text`, cumulative `partialOutputHash`, and
  `partialOutputScalars`;
- `heartbeat`: no prose and no internal lease/fence value;
- `completed`: result WorkingDraft revision/hash;
- `failed`: fixed `failureCode` only;
- `cancelled`: result revision/hash together, or both null.

Generated delta text is allowed only in this owner-scoped public event contract
and the owner-scoped status snapshot. It is forbidden from logs, error bodies,
diagnostics, test summaries, screenshots, and generic runtime observers.

## 7. Public HTTP contract

The route family remains:

```text
POST /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations
GET  /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}
GET  /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}/events?after=N
POST /api/projects/{pid}/chapter-sessions/{session_id}/draft-operations/{operation_id}/cancel
```

Create returns HTTP 200 with a closed `running` operation after durable reserve.
Same-key replay and terminal replay also return HTTP 200.

The public operation object extends B1 with:

```json
{
  "id": "<operation UUID>",
  "projectId": "<project UUID>",
  "chapterSessionId": "<session UUID>",
  "operationType": "generate_new",
  "status": "starting|running|completed|failed|cancelled|expired",
  "lastEventSequence": 17,
  "partialOutput": "<bounded generated prose>",
  "partialOutputHash": "<64 lowercase hex>",
  "partialOutputScalars": 1234,
  "resultWorkingDraftRevision": 5,
  "resultContentHash": "<64 lowercase hex or null>",
  "failureCode": null,
  "model": {
    "providerId": "<public provider id>",
    "modelName": "<public model name>"
  }
}
```

No lease, heartbeat timestamp, cancel timestamp, fencing token, manifest, prompt,
author instruction, provider body, secret, base URL, DSN, registry state, or raw
exception is public.

Events GET returns at most 100 continuous events:

```json
{
  "operationId": "<operation UUID>",
  "events": [],
  "lastEventSequence": 17,
  "nextAfter": 0,
  "hasMore": false
}
```

`nextAfter` is the last returned sequence, or the request cursor when no event is
returned. `hasMore` is true only when `nextAfter < lastEventSequence`. The client
requests subsequent pages until caught up, then waits one second before polling
again.

Cancel accepts no body or one exact empty JSON object. Any field, duplicate JSON
member, oversized body, wrong media type, or owner mismatch fails with the fixed
public error. Repeated cancel is idempotent.

The ChapterSession workspace exposes only `activeDraftOperationId` as a nullable
canonical UUID. It does not expose task, provider, lease, or partial-output data.

## 8. Frontend state and editor behavior

The coordinator maintains:

- current closed public operation;
- last applied event sequence;
- bounded streamed preview;
- `starting`, `running`, `reconnecting`, `cancelling`, and terminal local states;
- the original WorkingDraft view until a terminal authoritative reload;
- one generation token that fences late status, event, cancel, and workspace
  responses.

While an operation is active, the existing plain-text正文 editor displays the
streamed preview and is native `readonly`, not disabled. It remains focusable,
scrollable, selectable, and copyable. Input, paste, autosave retry, Candidate
changes, generation actions, selection tools, and chapter navigation remain
blocked.

The preview follows new output by default. When the author scrolls upward, auto
follow stops and a `回到最新` control appears. Activating it scrolls to the end and
resumes follow.

Public fixed UI messages are:

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

On refresh or route entry:

1. load the authoritative ChapterSession workspace;
2. if `activeDraftOperationId` exists, read its closed status;
3. immediately display the status partial snapshot;
4. page events after the known sequence and then poll every second;
5. never generate a new operation or key as part of reconnect.

On a fresh coordinator with no retained event cursor, the complete status
snapshot and its `lastEventSequence` are one calibration point: the client sets
both preview and cursor from that response and does not replay earlier deltas on
top of the snapshot. A retained cursor may page only later sequences. Any cursor
ahead of the authoritative status is discarded and recalibrated from status.

Completed and cancelled-with-result operations reload the authoritative
WorkingDraft exactly once before returning the editor to editable mode. Failed,
expired, or cancelled-without-result operations restore the pre-operation
WorkingDraft view.

## 9. Concurrency and failure rules

- The browser may request cancel, but only the database terminal fence authorizes
  cancellation.
- The in-process cancel signal is best effort; a late task cannot write after the
  cancelled terminal transition.
- Heartbeat renewal, delta append, completion, and cancellation require the same
  owner and fencing identity.
- Same-key reconnect and replay never invoke the provider twice.
- A server restart never resumes or recreates a provider task.
- Status/event reads never call the provider.
- Provider failure, malformed SSE, content/secret/event bound failure, lease
  expiry, or stale authority never overwrites the WorkingDraft.
- No path uses `page.request`, route interception, direct browser fetch, shadow
  product services, or a second WorkingDraft write path in automated acceptance.

## 10. Verification strategy

Implementation follows strict RED -> GREEN -> self-review. Specification review
must reach Critical/Important/Minor `0/0/0` before quality review begins; quality
review must also reach `0/0/0`.

Focused unit and API tests prove:

- strict provider SSE parsing, raw-byte and scalar bounds, split-secret scanning,
  and no raw-body/cause leakage;
- exactly one launched task for a new reserve and none for replay;
- delta batching, continuous sequences, event ceiling, heartbeat cadence, and
  lease extension;
- closed operation/event/cancel DTOs and owner scoping;
- reconnect pagination and partial snapshot calibration;
- reset/dispose/navigation fences for every late response;
- read-only editor focus, selection, copy, scroll, auto-follow, and cancel UI;
- no fabricated delta for a non-stream provider.

Disposable-MySQL tests prove:

- delta snapshot and event commit atomically with matching hash/scalar count;
- heartbeat extends only the matching live fence;
- cancel versus completion has exactly one terminal winner;
- cancelled non-empty partial creates one WorkingDraft revision, before/after
  recovery records, and terminal event in one transaction;
- cancelled empty partial leaves WorkingDraft and recovery records unchanged;
- restart/elapsed lease expires without provider work;
- late delta or completion after cancel/expiry cannot modify the draft;
- provider and timer waits hold no database transaction;
- test databases are created and cleaned with remaining residue 0.

Controller acceptance runs MySQL, build, and any long-lived browser gate serially.
It audits only proven-owned test databases, Node/Python tasks, ports, temporary
roots, and Vite `deps_temp` directories. Automatic gates use an injected fake
streaming provider and never read a product database or call a real model.

## 11. Acceptance statement

The eventual Phase4B2 acceptance wording is limited to:

```text
Phase4B2 generate_new streaming, automatic reconnect, and cancellation are
accepted with an injected fake streaming provider. Rewrite/local tools, undo,
full Phase4B, real-provider quality, and product-database readiness remain
unaccepted.
```
