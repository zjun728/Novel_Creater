# Phase 5 Lean Quality Review and Atomic Finalization Design

## 1. Goal

Deliver the shortest complete path from one immutable Draft Candidate to one immutable final
chapter:

1. run deterministic prechecks and an optional model quality review;
2. extract one closed `FinalizationChangeSet` from the Candidate;
3. let the author review and, when necessary, correct that extraction;
4. confirm one exact ChangeSet revision;
5. commit final prose, Canon events, projections, chapter progress, and session state in one
   database transaction.

The author remains the only finalization authority. Quality advice has no score gate and never
rewrites prose. Automation uses injected fake quality/extraction providers only.

## 2. Lean boundary

Phase 5 is a thin application layer over existing authorities:

- `draft_candidates` owns immutable prose and its frozen Planning/Outline/Canon basis;
- existing Canon domain rules own closed event validation and hard-conflict detection;
- existing Canon/Projection persistence owns revision and derived-view construction;
- existing ChapterSession and Planning rows own chapter number, immutable outline pins, and
  future-plan authority;
- existing Provider binding and secret-egress rules own model selection.

The implementation does not add a workflow engine, rule-builder UI, score platform, background
job system, generic approval framework, alternate Canon store, or a second projection pipeline.
Full-draft rewrite, Candidate fusion, general recovery browsing, real-provider quality, product
database readiness, export/backup, and multi-user approval are outside this phase.

## 3. Persistent records

The exact empty-database schema advances once for Phase 5 and keeps four compact records.

### 3.1 Candidate quality report

`candidate_quality_reports` is immutable and binds:

- project, ChapterSession, Candidate id and Candidate content hash;
- expected Canon revision, Planning hash, and Outline hash;
- deterministic-policy version and context-manifest hash;
- Provider profile revision/model snapshot when a model result exists;
- `completed` or `quality_not_completed`;
- closed deterministic blocks and closed advisory findings;
- one canonical content hash and creation time.

A Provider timeout/failure produces `quality_not_completed`; it does not remove the author's
right to continue. Deterministic hash/revision/authority/copy/truncation failures remain hard
blocks even when the quality model is unavailable.

### 3.2 Finalization attempt

`finalization_change_sets` is one preparation attempt and the session-level state holder. It
binds the frozen Candidate and authority manifest, an idempotency key/fingerprint, the quality
report, extraction identity, and state:

`preparing -> awaiting_author -> committing -> committed`

Terminal non-success states are `invalidated`, `cancelled`, and `failed`. A nullable unique active slot allows
at most one `preparing`, `awaiting_author`, or `committing` attempt per ChapterSession. Reusing an
idempotency key with another fingerprint is a conflict.

### 3.3 Immutable ChangeSet revision

`finalization_change_set_revisions` stores revision 1 from the single extraction call. Author
correction creates revision 2, 3, ... without another model call. Each row stores closed payload,
canonical hash, immutable source (`extraction` or `author_correction`), and timestamp. The attempt
points to its current revision and exact hash; confirmation pins that pair.

The payload contains only the Phase 5 commit surface:

- final chapter title and summary;
- new Canon entities, aliases, and events with evidence locations/confidence;
- story-block progress events;
- future Planning patches and non-authoritative suggestions.

Unknown keys, duplicate ids, malformed evidence, references outside the frozen project/session,
and writes to confirmed/implemented Planning are rejected.

### 3.4 Finalization record and final chapter

The existing `finalization_records` and `final_chapters` remain the immutable commit receipt and
exact prose snapshot. They are tightened to pin the confirmed ChangeSet revision/hash and request
fingerprint. One ChapterSession can be finalized once.

## 4. Preparation and review

`POST .../candidates/{candidate_id}/finalization/prepare` accepts only an idempotency key and the
expected Candidate/Canon/Planning/Outline authorities.

Preparation performs:

1. a short transaction locks project/session/Candidate authority, verifies a current saved
   Candidate, rejects an active draft operation, and persists `preparing` plus a frozen manifest;
2. outside SQL, deterministic checks run and the quality gateway is attempted once;
3. if deterministic blocks are absent, the extraction gateway reads the Candidate once and
   returns a closed ChangeSet payload;
4. a second short transaction re-locks the same authorities, invalidates on drift, persists the
   quality report and immutable revision 1, and publishes `awaiting_author`.

Provider responses and Candidate prose are never logged or placed in public errors. A failed
quality call is recorded and extraction may continue. A failed/invalid extraction leaves a
stable `failed` attempt and no ChangeSet revision.

`GET .../finalization` returns the current attempt, report, current immutable revision, hard
blocks, and author-readable advice. It never returns Provider secrets or internal raw errors.

`POST .../finalization/revisions` accepts a complete corrected closed payload plus the expected
current revision/hash. It creates one immutable next revision after deterministic validation and
does not call a Provider.

`POST .../finalization/confirm` pins the expected current revision/hash and records author
confirmation. It does not commit Canon or prose yet; the response exposes the single next action
“定稿本章”.

## 5. Atomic commit

`POST .../finalization/commit` accepts one idempotency key, request fingerprint inputs, and the
confirmed ChangeSet revision/hash. It makes no Provider call.

One transaction locks in stable order:

1. project and projection head;
2. ChapterSession and current Planning/Outline authority;
3. Candidate, finalization attempt, confirmed revision, and idempotency record.

It then revalidates every frozen hash/revision, deterministic block, closed reference, and Canon
hard conflict before any durable domain result. On success the same transaction:

- appends exactly one Canon revision and its events;
- rebuilds all existing Canon projections from that confirmed event set;
- inserts one immutable final chapter with exact Candidate prose and authority pins;
- applies only allowed future Planning progress/patches;
- marks ChapterSession `final` and closes the finalization attempt;
- stores the immutable finalization receipt and authoritative result.

Any error rolls back all effects. Same key and same fingerprint replays the stored result; same
key with a different fingerprint conflicts. An unknown client result is recovered by GET, not by
blindly generating or extracting again.

## 6. Minimal user experience

The Writer page adds one right-side finalization panel rather than a new application section:

- select a current saved Candidate and choose “审查并定稿”;
- show deterministic hard blocks first, then concrete quality findings with paragraph location,
  reason, and suggested action;
- show the complete extracted facts/progress/Planning changes in one review surface;
- permit full-payload corrections through small existing-form controls, with immutable revision
  history summarized rather than a generic diff editor;
- require one explicit overall confirmation and one final “定稿本章” action;
- after success, render the chapter and outline read-only and route the next action to the next
  unfinished outline.

No numeric pass score, auto-fix, automatic finalization, partial approval, hidden second
extraction, or page-level API bypass is allowed.

## 7. Slices and gates

- **5A Foundation:** exact schema, closed domain payloads, deterministic checks, repository
  ownership and idempotency contracts.
- **5B Review:** fake-boundary quality/extraction preparation, report persistence, author
  correction and confirmation APIs.
- **5C Commit/UI:** atomic Canon/projection/final chapter commit, compact Writer UI, one UI-only
  disposable-MySQL browser scenario, and Phase-level close.

Each task uses focused RED/GREEN evidence. Full Python, Node, disposable-MySQL, build, browser,
and resource-residue matrices run once at Phase 5 close under the lean test policy. Reviews do not
expand the phase for non-critical edge cases; new generic recovery, orchestration, scoring, or
content-quality platforms are recorded for later.

## 8. Acceptance

Phase 5 is accepted only when a visible saved Candidate can be reviewed with injected fake
providers, corrected without another extraction, confirmed, and atomically committed through the
UI; final prose, Canon revision, projections, progress, session state, and receipt must all agree
or all remain unchanged. Real-provider quality and product-database readiness remain unaccepted.
