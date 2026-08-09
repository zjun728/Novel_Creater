# Phase 4C Candidate Load and Read-only Compare Design

## 1. Goal and authority

Deliver the smallest useful Candidate workbench on top of the accepted WorkingDraft and
Candidate boundaries:

- load one immutable Candidate into the current WorkingDraft under CAS;
- select at most two Candidates and compare them side by side without mutation.

This document narrows the older Phase 4C description. Candidate fusion, a general recovery
browser, full-draft rewrite, a three-column redesign, Phase 5 audit/finalization, and additional
AI work are not part of this slice. No Provider is required by either product action.

## 2. Existing boundaries to reuse

- `draft_candidates` remains the immutable Candidate store and keeps identity
  `(chapter_session_id, content_hash, basis_hash)`.
- The existing Chapter workspace already returns Candidate prose and basis status; comparison
  therefore needs no second content endpoint, comparison table, or persisted selection state.
- `working_drafts` remains the only mutable prose buffer.
- `working_draft_revisions` remains the append-only consequential replacement history.
- Existing autosave flush, controller action lock, ChapterSession service, workspace serializer,
  Store normalization, route family, disposable MySQL fixtures, and owned browser lifecycle are
  reused.

No CandidateService, comparison aggregate, selection ledger, Provider operation, or fusion
placeholder is added.

## 3. Necessary schema adjustment

Candidate load must record before/after recovery snapshots without inventing a Provider
operation. The current recovery table requires `source_operation_id`, so the exact bootstrap
schema advances to `writer-core-v1.11.0` with the minimum source generalization:

- existing `source_operation_id` becomes nullable;
- one nullable `source_candidate_id` column references the immutable Candidate;
- `candidate_load` is added to the existing `replacement_reason` CHECK;
- a CHECK requires exactly one source: Candidate load uses only `source_candidate_id`; all
  existing reasons use only `source_operation_id`.

Because the recovery table is created before `draft_candidates` in the exact bootstrap order,
the Candidate foreign key is added by a manifest-owned `ALTER TABLE` statement immediately after
the Candidate table is created. This statement is part of fresh empty-database construction; it
is not a runtime or in-place migration.

No table, migration path, compatibility path, product-database read, or runtime DDL is added.

## 4. Candidate load API and transaction

The existing formal route becomes live:

```text
POST /api/projects/{pid}/chapter-sessions/{session_id}/candidates/{candidate_id}/load
```

The strict JSON body contains only:

- `expectedWorkingDraftRevision`;
- `expectedContentHash`.

The service validates non-empty project/session/Candidate identities and exact revision/hash
types, then performs one short transaction:

1. lock the active project, ChapterSession, and WorkingDraft in the established order;
2. require a drafting, non-superseded session with no active DraftOperation;
3. read the Candidate by exact project/session/id and verify its UTF-8 content hash;
4. recheck the WorkingDraft revision/hash CAS;
5. append the current WorkingDraft as a `candidate_load` before snapshot sourced by Candidate;
6. write Candidate content into WorkingDraft at revision `+1`, with a closed
   `candidate-load` source payload;
7. append the resulting WorkingDraft as the matching after snapshot;
8. return the full authoritative Chapter workspace.

Any failure rolls back all three writes. Candidate content, provenance, basis, identity, and
timestamps are never updated or deleted.

A stale-basis Candidate may be loaded for author editing. It remains visibly stale and cannot
become finalization-ready merely by loading it. A later explicit “保存为候选” freezes the current
WorkingDraft against the then-current basis under the already accepted Candidate-freeze rules.

Candidate load is not added to the one-step local-AI undo. It invalidates that ephemeral undo;
recovery browsing remains deferred.

## 5. Public Candidate metadata

The workspace adds only `createdAt`, already stored on every Candidate. The UI derives:

- a stable page-local label (`候选 1`, `候选 2`, ...);
- Unicode-scalar character count from immutable content;
- abbreviated content hash;
- current/stale basis label;
- formatted creation time.

Source operation and model are not fabricated. Existing provenance cannot safely distinguish a
subsequent manual autosave from the last AI source, so richer provenance is deferred until it
can be defined without misleading the author.

## 6. Frontend behavior

Candidate load first flushes visible autosave, freezes the selected Candidate identity/content
hash and current persisted WorkingDraft revision/hash, then calls the load route through the
existing controller action lock. Only a full returned workspace whose project/session,
revision `+1`, Candidate identity/content/hash, and WorkingDraft content/hash agree is adopted.
Unknown or malformed results reload nothing implicitly and never assemble prose client-side.

The Candidate card list permits zero, one, or two selected ids:

- selecting a third Candidate is disabled while two are selected;
- exactly two selections reveal one side-by-side read-only comparison region;
- comparison uses plain `<pre>` prose views, not another editor;
- selections are ephemeral route state and are pruned when Candidates disappear;
- each Candidate retains one explicit “载入为工作稿” action;
- the action is disabled while autosave or another write is active.

No fusion button, modal, history drawer, persistent compare state, diff algorithm, or automatic
Candidate choice is introduced.

## 7. Failure and security

Stable public failures cover invalid request, missing Candidate/session, stale WorkingDraft CAS,
non-drafting/superseded session, active operation, malformed Candidate content/hash, and storage
failure. UI errors are fixed Chinese messages and do not include server/provider/raw prose.

Automated evidence never calls a Provider, live website, or product database. Logs, summaries,
and artifacts contain no Candidate/WorkingDraft body, secret, DSN, or raw exception.

## 8. Acceptance criteria

- Candidate load flushes the visible buffer before using persisted CAS authority.
- The server rejects cross-project/session Candidate ids, stale CAS, active operations, and
  corrupt Candidate content before any WorkingDraft mutation.
- A successful load advances WorkingDraft once, records exact before/after recovery rows, and
  leaves the Candidate byte-for-byte immutable.
- Stale-basis Candidates stay visibly stale after loading.
- The client adopts only the complete calibrated workspace returned by the server.
- Zero/one/two Candidate selections are supported; a third cannot be selected; exactly two show
  a read-only side-by-side comparison.
- Candidate metadata is honest and derived only from stored public facts.
- Candidate fusion, full-draft rewrite, general recovery browsing, Canon/finalization,
  real-provider quality, and product-database readiness remain unaccepted.

## 9. Lean evidence

Development uses focused RED/GREEN tests. Slice acceptance runs affected Python/API/schema,
affected frontend/root Node, affected disposable-MySQL integrity, production build, and one
narrow UI-only browser scenario that saves two Candidates, compares them, and loads one.

The browser scenario uses no Provider process and asserts outbound Provider calls `0`, visible UI
only, exact owned resource cleanup, and no body-bearing diagnostics. Full Phase 4 and release
matrices remain deferred to Phase 4 close.
