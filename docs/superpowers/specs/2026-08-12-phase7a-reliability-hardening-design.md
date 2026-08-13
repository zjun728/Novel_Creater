# Phase 7A Reliability Hardening Design

## Status

Approved design for the first Phase 7 slice. Phase 7A closes only the reliability items explicitly
deferred by the Phase 6A, Phase 6B, and Phase 6C acceptance records. It does not add product features,
public states, schema, routes, a metrics platform, or a shared reliability framework.

One separately approved companion contract is implemented on the same branch because it was the
first product cause exposed by the hardened Phase 6A observer: an existing chapter session with no
finalization attempt changes from HTTP 404 to the closed HTTP 200 projection `{ "state": "empty" }`.
That exception is specified and accepted independently by
`2026-08-12-finalization-review-empty-state-design.md`; it is not counted among Phase 7A's nine
no-contract-change reliability items. Missing session authority remains HTTP 404.

The final Phase 6 direct-first-cause closure also corrects the value semantics of existing backup
fields `indexPayload.fragmentId` and `indexPayload.chapterId`: physical database UUIDs are replaced
by the package's existing portable logical identities and mapped back to target UUIDs on import.
This changes backup bytes but adds no route, DTO key, schema, UI state, or Provider behavior. Phase
6A/6B/6C public-fixture alignment and the Phase 2C dispatcher-test isolation are test-boundary fixes.

## Goal

Make the accepted Phase 6 finalized-download, deterministic-backup, and atomic-import boundaries
resilient to delayed concurrent work and secondary cleanup failures while preserving their public API,
UI, security, atomicity, idempotency, and cancellation semantics.

## Accepted baseline

Phase 6 accepted the following boundary with disposable local data:

> Phase 6 finalized download, deterministic secret-free backup, and strict atomic import are accepted with disposable local data. Real-provider quality, product-database readiness, live-site readiness, and novel content quality remain unaccepted.

Phase 7A does not widen that boundary. Provider and outbound calls remain zero, product-database
reads/writes remain zero, and every automated test uses disposable MySQL, owned local files, a deny
proxy, or an owned local browser.

## Deferred-item inventory

Phase 7A closes exactly these recorded items:

1. A download controller can leave its own busy/in-flight state uncleared if
   `operationStore.finish()` throws.
2. Disposing a controller during options loading can leave `loading` true on the destroyed instance.
3. The Phase 6A browser runner deferred context-wide outbound denial, full-window runtime evidence,
   fixture-helper boundary tightening, and cleanup fault injection.
4. A project-package repository rollback failure can skip pool release or replace the primary error.
5. A project-package service cleanup failure can replace the primary error or `CancelledError`.
6. Stale project-package cleanup failures are swallowed before the startup warning boundary can
   observe them.
7. Project backup still uses the generic 30-second binary request timeout.
8. The project-backup download anchor is not removed if `click()` throws.
9. Two commands importing the same corpus digest can exhaust 64 event-loop yields while the winner
   persists its manifest and fail with an unnecessary conflict.

No newly discovered cleanup, retry, logging, frontend, or browser concern enters this slice unless it
is a direct first cause that prevents one of these nine items from being closed.

## Design constraints

- Preserve all public routes, request/response shapes, error codes, UI labels, blocking phases, and
  navigation behavior except for the separately approved finalization empty-state contract above.
- Add no schema, migration, job, workflow, scheduler, visibility state, Provider placeholder, metrics
  backend, or general retry library.
- Keep retry/deadline helpers local to the module that owns the resource.
- Preserve the original business error or `CancelledError` when secondary cleanup fails.
- Never log exception text, filesystem paths, project/command identifiers, body text, secrets, DSNs,
  SQL, Provider output, or corpus contents.
- Use monotonic time for elapsed-time decisions and bounded retry/deadline behavior.
- Do not make a test pass by weakening ownership, hash, path, secret, runtime, or residue checks.

## Architecture

Phase 7A has four reliability slices. Managed corpus-blob publication and deletion share one narrow
internal per-digest claim protocol in the existing project-import module; this is not a general retry,
locking, or reliability framework and introduces no production module.

### 1. Import digest-claim waiting

`backend/services/project_imports.py` owns the per-digest exclusive claim and no-overwrite promotion
rules. Four managed-blob participants use the same claim namespace: project-import publication and
compensating cleanup, ordinary corpus-import publication, startup project-import recovery cleanup,
and corpus-library permanent deletion. Each acquisition has a unique incarnation token in addition
to its logical owner identity, so an old process cannot release a retry's claim. Contention uses a
bounded deadline.

The claim covers both the filesystem decision and the corresponding database publication,
reference check, or deletion transaction. A project-import owner retains it through publication or
compensating cleanup. Runtime cleanup additionally holds an exact fingerprint/owner/live-lease row
fence while it rechecks references and removes bytes, so a fenced old runner cannot delete a later
publisher's blob. Corpus import and permanent deletion retain the claim through transaction
commit/rollback.

Startup recovery keeps scanning the current manifest after a live foreign owner or claim-release
failure; other manifest, database, or file-operation failures defer the remaining work to a later
pass. Every deferred case preserves the complete root and manifest. Project-import compensating
cleanup attempts every blob and claim; an existing operation failure remains primary, while in the
absence of an operation failure a cleanup flow-control exception takes precedence over an ordinary
cleanup error.

Constants:

- claim wait deadline: 30 seconds;
- initial delay: 10 milliseconds;
- exponential delay cap: 250 milliseconds.

The acquisition loop performs an immediate claim attempt. On `FileExistsError`, it computes the
remaining duration using a monotonic clock, fails with the existing fixed
`ProjectImportCommandStateConflict` when the deadline is exhausted, and otherwise awaits the smaller
of the current backoff and remaining duration. The backoff doubles after each wait until the cap.

`CancelledError` and other flow-control `BaseException` values propagate immediately from claim
waiting. A claim alone never grants project-import compensation ownership; the database fence does.
Once a publisher acquires the claim, it follows the existing promotion path and rechecks the
destination blob's content hash, byte length, and managed storage key. There is no second
blob-verification implementation. Internal claim failures in corpus-library permanent deletion map
to the existing `CorpusLifecycleConflict` boundary rather than introducing a new public error.

The clock and sleeper have narrow test seams so unit tests can prove the 30-second boundary without a
wall-clock wait. Production uses the event loop and monotonic clock.

### 2. Backend cleanup and safe observability

#### Repository connection finalization

`backend/repositories/project_packages.py` must always attempt pool release even when rollback fails.
The finalization order is:

1. retain the primary result or exception from snapshot reading;
2. attempt rollback;
3. in a nested `finally`, attempt pool release;
4. resolve the outward result using the precedence table below.

| Primary path | Rollback/release | Outward result |
| --- | --- | --- |
| failed or cancelled | succeeded | original primary error |
| failed or cancelled | failed | original primary error plus fixed safe warning |
| succeeded | succeeded | snapshot |
| succeeded | ordinary cleanup `Exception` | existing fixed, sanitized project-package error |
| succeeded | cleanup flow-control `BaseException` | propagate that flow-control exception |

Neither cleanup exception text nor connection data reaches logs or public errors.

#### Service-owned temporary cleanup

`backend/services/project_packages.py` keeps cleanup ownership in its existing owner. A local bounded
helper attempts cleanup twice. It is used only on service failure paths that still own the temporary
root. A second-attempt success leaves no residue. If both attempts fail, the helper emits one fixed
warning and returns control to the primary exception path. The original service exception or
`CancelledError` remains the outward result.

Response-handoff cleanup remains owned by the existing router wrapper; Phase 7A does not create a
second owner or background queue.

#### Stale cleanup warnings

The existing stale scanner still examines at most 32 immediate owned-prefix children and continues
after a candidate-level failure. Candidate failures produce a fixed candidate-cleanup warning; a
parent enumeration/resolution failure produces a distinct fixed scan warning. Each warning is a
constant event name with no dynamic arguments. The scanner does not reveal paths or exception values
and does not turn startup cleanup into a startup blocker.

### 3. Frontend state and download reliability

#### Controller state

`frontend/src/application/downloads/novelDownloadController.js` places controller-owned in-flight and
busy cleanup in a `finally` that runs even if `operationStore.finish()` throws. The store failure keeps
the existing fixed download failure behavior, but it cannot freeze the controller or block the next
download attempt.

`dispose()` immediately sets options `loading` to false, increments the existing generation fence,
and aborts an in-flight download. A late options response still cannot update options or error state.

#### Backup timeout

`frontend/src/api/db/client.js` defines a project-backup-specific total timeout of 1,200,000
milliseconds. Only `api.projectBackups.create()` uses it. Other binary, JSON, and project-import
requests retain their existing timeouts. External abort remains distinguishable from timeout, and all
success/error/abort paths remove listeners and clear timers.

#### Backup anchor cleanup

`frontend/src/components/projects/ProjectBackupPanel.vue` wraps append/click in `try/finally` and
removes the anchor in the `finally`. The controller remains the sole owner of object-URL revocation.
No new button, progress state, cancellation control, or message is added.

### 4. Phase 6A browser-runner assurance

Only the Phase 6A browser acceptance runner is hardened. Historical runners are not unified or
refactored.

- The deny boundary and runtime observer attach at the runner-owned browser-context lifecycle so a
  popup or newly created page cannot escape observation.
- Runtime evidence covers the entire scenario window and ends with zero owned listeners and pending
  requests.
- Cleanup fault injection reports only fixed categories and counts. Unexpected console, page,
  request, response, origin, pending-request, or listener evidence remains fail closed.
- The fixture may orchestrate public service/repository entry points, but it cannot duplicate product
  hash, state-transition, or authority-building algorithms.
- Success, consumer failure, cancellation, and injected cleanup failure must leave zero owned DB,
  process, port, temp, download, artifact, and Vite residue.

No `page.request`, `page.route`, `page.evaluate`, direct `fetch`, or `axios` shortcut is introduced.

## File boundaries

Expected production changes are limited to:

- `backend/services/project_imports.py`
- `backend/repositories/project_imports.py`
- `backend/services/corpus_import.py`
- `backend/services/corpus_library.py`
- `backend/repositories/project_packages.py`
- `backend/services/project_packages.py`
- `frontend/src/api/db/client.js`
- `frontend/src/application/downloads/novelDownloadController.js`
- `frontend/src/components/projects/ProjectBackupPanel.vue`
- `backend/scripts/prepare_phase6a_browser_db.py` only if the fixture boundary test proves a direct
  helper violation
- the existing Phase 6A runner, config, spec, and runtime observer

Tests live beside the existing focused suites. A new production module requires a separate approved
design change and is not implied by this specification.

## Test strategy

### Import claim tests

- Two different commands promote the same digest while the winner's async manifest persistence is
  deliberately delayed; both complete correctly and exactly one command installs the blob.
- Project import, ordinary corpus import, startup recovery, and corpus-library permanent deletion
  cannot concurrently publish/delete the same digest outside the shared claim. Claims remain held
  until their database transaction commits or rolls back.
- A fenced old runner and a reclaimed retry with the same command identity use different incarnation
  tokens; the old runner cannot release the retry's claim or delete its blob.
- Startup recovery preserves the complete root whenever work is deferred, then completes on a later
  pass. Project-import compensating multi-blob cleanup attempts all items and preserves the declared
  primary-error/flow-control precedence.
- A fake clock/sleeper proves the initial delay, exponential sequence, 250ms cap, and exact 30-second
  deadline without sleeping in real time.
- Cancellation during a wait propagates unchanged.
- Success, conflict, link failure, persistence failure, and cancellation leave no leaked claim or
  command-owned root.

### Backend cleanup tests

- Snapshot success/failure/cancellation is crossed with rollback success/failure and release
  success/failure. Release is always attempted and the precedence table is exact.
- Package creation primary failure and cancellation are crossed with cleanup first-attempt failure,
  second-attempt success, and permanent failure.
- Fixed warning assertions inspect only event names/counts and assert zero dynamic arguments.
- Stale scanning continues after a failed candidate, remains bounded at 32, and distinguishes
  candidate failure from parent scan failure without exposing values.

### Frontend tests

- Backup API passes exactly `1_200_000` milliseconds and preserves external abort/timeout
  classification and timer/listener cleanup.
- A throwing `operationStore.finish()` cannot leave busy or in-flight state and does not prevent a
  subsequent request.
- Dispose during options loading immediately clears loading; a late result cannot mutate state.
- A throwing anchor `click()` still removes the exact anchor, and the controller revokes the object
  URL through its existing owner.

### Runner tests

- A second page/popup is covered by the same deny and observer rules.
- Unexpected outbound traffic and unrelated console/page/request failures remain fatal.
- Expected injected cleanup faults are represented only by fixed safe counters.
- Fixture contract tests reject copied product algorithms or private authority construction.
- All runner exits assert the complete zero-residue ledger.

## Acceptance gates

Implementation proceeds test-first per slice and commits each independently. Final Phase 7A
acceptance runs, serially:

1. all Phase 7A focused Python, Node, and runner-contract tests;
2. `npm test`;
3. `npm run test:integration`;
4. `npm run build`;
5. `npm run test:browser:phase6a`;
6. `npm run test:browser:phase6b`;
7. `npm run test:browser:phase6c`.

The final ledger requires:

- disposable database remaining: 0;
- task-owned process, port, temp, quarantine, staging, download, artifact, and Vite residue: 0;
- Provider and outbound calls: 0;
- product database reads/writes: 0/0;
- specification review active Critical/Important: 0/0;
- quality review active Critical/Important: 0/0.

## Explicit non-goals

- Product database migration, backup/restore, rollback, or disaster recovery; these belong to Phase
  7B.
- Real Provider calls, model matching, budget evaluation, privacy evaluation, or content-quality
  scoring; these belong to Phase 7C.
- Deployment, live-site, security operations, monitoring infrastructure, or release automation;
  these belong to Phase 7D.
- A shared retry/deadline/logging framework.
- New user-visible cleanup, recovery, progress, or cancellation states.
- Cleanup of historical findings not explicitly listed in this specification.
