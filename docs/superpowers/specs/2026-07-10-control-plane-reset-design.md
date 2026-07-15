# Control Plane Reset: QA Gateway and Draft Transaction Design

- Date: 2026-07-10
- Status: Approved for specification by the product-control thread
- Baseline: `codex/novel-creater-sample-library-v3-prompt-hookup@4b85e8d1632e190a5a19b60400516591d360407a`
- Implementation branch: `codex/control-plane-reset`

## 1. Purpose

Reset the Novel Creator QA control plane around the committed product architecture instead of extending the historical phase-e runner chain.

The slice introduces two bounded capabilities:

1. A Node-compatible QA gateway that calls the existing FastAPI AI proxy without constructing or receiving provider adapters, API keys, or provider base URLs.
2. A backend transaction service that persists exactly two draft candidate domain writes atomically, with a canonical manifest hash, an idempotency key, preimage validation, rollback, and disposable-MySQL integration tests.

The product-control thread owns scope, execution audit, and result audit. Implementation may be delegated, but no delegated result is accepted without independent diff and test-output review.

## 2. Current committed facts

- The default product AI path is `WriterView -> writerStore -> providerStore -> frontend AI client -> FastAPI /api/ai/chat-completions -> provider`.
- Browser direct-provider access exists only behind `VITE_AI_DIRECT_PROVIDER=true` and is not part of this QA route.
- The backend AI proxy resolves provider secrets from `provider_profiles`.
- The database pool is configured with `autocommit=True`; existing helper functions do not expose a multi-statement transaction boundary.
- The root `npm test` command intentionally exits with “Error: no test specified”; most committed tests live under `tmp/` and are not connected to a supported root test entry point.
- Historical replacement rows have not been verified against fresh database evidence. Their existence, identity, and need for replacement remain unresolved.

## 3. Scope and non-goals

### In scope

- A supported, repository-owned control-plane QA test entry point.
- A secret-free Node client for the existing backend AI proxy.
- Fake-HTTP unit tests for the Node gateway.
- A dormant backend draft-pair router and domain service that are mounted only by the disposable test application in this slice.
- An explicit SQL migration for the idempotency/control ledger. The new schema must not be added to startup-time `ensure_schema()`.
- Disposable-MySQL integration tests for success, replay, collision, rollback, and concurrency behavior.
- Readiness labels that distinguish contract, database, proxy, and live evidence.

### Out of scope

- Calls to any real provider or model.
- Reads from or writes to the real/product Novel Creator database.
- Historical replacement execution.
- Chapter finalization or post-finalization processing.
- Live or canary runs.
- Provider API-key response redaction, startup DDL refactoring, or broad WriterView/writerStore decomposition. These remain pre-live blockers but are separate slices.
- Updating remote `main`, pushing a release branch, or creating a release tag.
- Reusing or extending phase-e names, reports, runners, or Ready labels.

## 4. Architecture

### 4.1 Supported test entry point

The root package receives explicit control-plane scripts. The default `npm test` must run only deterministic tests that require no provider, service, or database. Disposable-DB tests use a separate opt-in command and the explicit localhost admin/server DSN defined in section 5.3.

The root scripts are:

- `test`: `npm run test:control-plane`; no legacy `tmp/` suite is included implicitly.
- `test:control-plane`: run `test:control-plane:node` followed by `test:control-plane:py`.
- `test:control-plane:node`: `node --test "tools/control-plane-qa/tests/*.test.mjs"`; this glob form is verified with the repository's Node 24 runtime.
- `test:control-plane:py`: `python -m unittest discover -s backend/tests/control_plane -p "test_*.py"`.
- `test:control-plane:db`: `python -m unittest discover -s backend/tests/control_plane -p "mysql_integration_test.py"`; the integration module deliberately does not match `test_*.py`, and this command must refuse non-disposable database targets.

The implementation uses Node's built-in test runner and Python's standard `unittest`; this slice adds no test-framework dependency. Default deterministic tests and opt-in database tests remain separate.

### 4.2 Node-compatible AI proxy gateway

Location: a repository-owned `tools/control-plane-qa/` module, not `tmp/`.

Public input is a closed schema:

```text
backendBaseUrl
taskName
projectId (required unless providerId is present)
providerId (optional)
messages
options: temperature, maxTokens, topP, responseFormat, includeUsage
```

`taskName` is always required. At least one of `projectId` or `providerId` is required. When both are present, `providerId` is the provider-resolution authority and `projectId` remains request context. The slice does not accept a model override.

Unknown envelope and option fields are rejected. `messages` contains 1-200 objects with exactly `role` and string `content`; roles are `system`, `user`, or `assistant`, and total content is limited to 2 MiB.

`taskName` contains 1-120 characters; IDs contain 1-120 characters. `temperature` is a finite number from 0 through 2, `maxTokens` is an integer from 1 through 65536, `topP` is a finite number greater than 0 through 1, `responseFormat` is omitted or `json`, and `includeUsage` is boolean. `thinking` and all other structured provider options are outside this slice.

The gateway recursively scans object keys in the envelope and options, not string values. Keys are lowercased and stripped of `_` and `-` before comparison. It rejects normalized keys `apikey`, `baseurl`, `authorization`, `headers`, `provideradapter`, and `applyadapter`. The closed schema remains the primary control; the deny-list catches nested or future adapter/secret shapes.

`backendBaseUrl` must be an HTTP URL without user-info credentials whose parsed hostname is exactly `127.0.0.1`, `localhost`, or `::1`. Non-loopback hosts and redirects are rejected; `fetch` uses `redirect: 'error'`. HTTPS and remote-backend opt-ins are outside this slice.

Behavior:

1. Normalize `backendBaseUrl` to the existing `/api` base.
2. Build the same identifier-only payload used by the frontend AI client.
3. POST to `/ai/chat-completions`.
4. Return content plus an allowlisted diagnostic object containing only `requestId`, `taskId`, `taskKey`, `providerId`, `providerName`, `modelName`, `httpStatus`, `upstreamStatus`, `elapsedMs`, `retryable`, `retriesAttempted`, and `retrySucceeded` when those fields are present.
5. Normalize backend failures into a typed error with the same allowlist. Raw response bodies and backend `rawHead`, `rawTail`, `upstreamBodyHead`, and `upstreamBodyTail` fields are never forwarded or logged.

Streaming is intentionally outside this slice. The gateway also does not add provider retries. The existing backend proxy policy remains the only retry authority; duplicating retries in QA could issue duplicate model calls.

Tests inject a fake `fetch` implementation. No test may bind a provider adapter or contact a real backend.

### 4.3 Dormant draft-pair transaction API

The service represents two draft candidate writes as one product-domain transaction. It is not an arbitrary SQL executor and does not accept table names, column names, SQL fragments, finalization flags, or final-version mutations.

The router is not imported or included by `backend/main.py` in this slice. A dedicated disposable test-app factory mounts it only when `CONTROL_PLANE_DRAFT_WRITES_ENABLED=true` and receives a service built with an explicitly injected disposable pool plus the generated schema name/run token. The router returns 404 when the flag is absent or false. The service never imports or calls the global `get_pool()`/`MYSQL_CONFIG`; before every transaction it executes `SELECT DATABASE()` on the acquired connection and requires an exact match to the injected `novel_creator_control_plane_disposable_<run-token>` name. Registering this router in the product application or allowing a non-disposable pool requires a separate future approval.

The test-app contract is:

```text
POST /api/projects/{project_id}/draft-write-batches
Idempotency-Key: <opaque stable key>
X-Manifest-SHA256: <64 lowercase hex characters>
```

Request body:

```json
{
  "manifestVersion": 1,
  "purpose": "draft_only_pair",
  "projectId": "uuid",
  "writes": [
    {
      "chapterId": "uuid",
      "chapterNum": 1,
      "sourceVersionId": "uuid",
      "expectedSourceContentSha256": "64-hex",
      "title": "candidate title",
      "content": "candidate content",
      "contentSha256": "64-hex",
      "promptBrief": "1-500 characters"
    },
    {
      "chapterId": "uuid",
      "chapterNum": 2,
      "sourceVersionId": "uuid",
      "expectedSourceContentSha256": "64-hex",
      "title": "candidate title",
      "content": "candidate content",
      "contentSha256": "64-hex",
      "promptBrief": "1-500 characters"
    }
  ]
}
```

The body `projectId` must equal the route `project_id`; a mismatch is `409 project_identity_conflict`. The request must contain exactly two writes with distinct `chapterId` values. Both `sourceVersionId` and `expectedSourceContentSha256` are mandatory for each write. Each write creates a new non-final `chapter_versions` row using only baseline schema columns, with `version_type='qa_draft_candidate'`, `source_model_id=NULL`, and `prompt_brief` prefixed by `[control-plane:<batch-id>] `. It never overwrites historical content and never changes `chapters.final_version_id`, chapter status, finalization markers, story-block settlement, canon facts, or setting state.

`Idempotency-Key` is required, matches visible ASCII `[!-~]{1,120}` with no whitespace, is case-sensitive, and is scoped by project. Titles contain 1-200 characters, caller-supplied prompt briefs contain 1-500 characters before the server prefix, and candidate content is non-empty. Content hashes are lowercase SHA-256 of the exact UTF-8 string bytes with no Unicode normalization; a source version whose content is SQL NULL is `409 source_content_unavailable`. The server rejects unknown request fields.

### 4.4 Canonical manifest

The server owns canonicalization and uses RFC 8785 JSON Canonicalization Scheme (JCS) over the closed request schema. Duplicate JSON object keys are rejected while parsing; strings are not Unicode-normalized; the schema permits no floating-point values. Node and Python implementations must pass the same checked-in RFC 8785-derived fixed vectors, including non-BMP keys and escaped characters.

The server computes SHA-256 over the UTF-8 JCS bytes and compares the lowercase 64-hex result with `X-Manifest-SHA256`. A mismatch fails before opening a write transaction.

The explicit migration creates only `draft_write_batches`; it does not alter `chapter_versions` or add provenance columns. The ledger contains:

- `id CHAR(36)` primary key.
- `project_id CHAR(36)`.
- `idempotency_key VARBINARY(120)` for case-sensitive byte identity.
- `manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin`.
- `result_json JSON`.
- `created_at BIGINT` and `committed_at BIGINT`.
- A unique index on `(project_id, idempotency_key)`.

`result_json` contains exactly `batchId`, `projectId`, `manifestSha256`, two ordered `candidateVersionIds`, and `committedAt`. It does not store chapter content, titles, or prompt text. The migration includes an exact rollback that drops only `draft_write_batches`.

Replay rules:

- Same key and same hash after a committed batch: return the stored result without new candidate rows.
- Same key and different hash: return `409 idempotency_manifest_conflict`.
- Concurrent inserts of the same key serialize on the unique index. If the first request commits, the second returns the committed replay for the same hash or a manifest conflict for a different hash. If the first request rolls back, the second may proceed. A lock-wait timeout returns a retryable `409 idempotency_in_progress`.
- A failed and fully rolled-back attempt leaves no ledger or candidate rows and may be retried with the same key and hash; it may not silently change its manifest after any committed result exists.

### 4.5 Transaction semantics

The backend introduces an explicit `READ COMMITTED` transaction context that owns one aiomysql connection with autocommit disabled for the duration of the unit of work.

All repository calls in this service receive that connection explicitly. They must not call the existing global `execute()`, `persist_provenance_if_columns()`, or any helper that acquires a second connection. The transaction-owned insert uses only the baseline `chapter_versions` columns described in section 4.3.

Within the transaction:

1. Confirm body and route project identities match, then lock the declared project row; a mismatch is `409 project_identity_conflict`, and a missing project is `404 project_not_found`.
2. Insert the idempotency ledger row, allowing the binary unique index to serialize concurrent requests.
3. Lock both chapter rows in stable `(chapter_num, chapter_id)` order.
4. Validate that the two `chapterId` values are distinct, both rows belong to the declared project, and each stored chapter number equals the request. Missing or cross-project rows are `404 chapter_not_found`; number mismatches are `409 chapter_identity_conflict`.
5. Define finalized as `status='final' OR final_version_id IS NOT NULL`; either condition produces `409 chapter_finalized`.
6. Lock both source versions in stable ID order. Each must belong to the declared project and its corresponding chapter. Missing or cross-project sources are `404 source_version_not_found`; wrong-chapter sources are `409 source_identity_conflict`.
7. Compare SHA-256 of each current source content with its required preimage hash; drift is `409 source_preimage_mismatch`.
8. Validate both submitted candidate `contentSha256` values against candidate content.
9. Insert two candidate `chapter_versions` rows using server-generated UUIDs.
10. Store the exact result schema from section 4.4 in the ledger.
11. Commit once.

Before the COMMIT attempt, any domain or SQL error triggers a full rollback. A successful rollback leaves neither ledger nor candidate rows. If rollback itself cannot be confirmed, return retryable `503 transaction_outcome_unknown`; recovery uses the same idempotency key and manifest hash.

If COMMIT is sent but the connection fails before its result is known, discard the connection and return retryable `503 commit_outcome_unknown`; do not claim rollback. Replaying the same key/hash resolves the outcome: a committed ledger returns its stored result, while an absent ledger allows the whole transaction to run again.

After a confirmed commit or rollback, restore the connection's autocommit state to the pool default before release. If restoration cannot be confirmed, close/invalidate the connection and let pool bookkeeping discard it rather than returning it to the reusable pool. A connection associated with `transaction_outcome_unknown` or `commit_outcome_unknown` is always closed/invalidated and never returned as reusable.

On ledger insert error 1062, roll back the current transaction and perform a new `READ COMMITTED` current read of the ledger. Same hash returns the stored committed result; a different hash returns `409 idempotency_manifest_conflict`. MySQL 1205 and 1213 cause a full rollback and a retryable `409 idempotency_in_progress` or `409 transaction_retryable_conflict`; the service performs no automatic retry.

The service may write its control-ledger row in addition to the two domain writes, but it must never leave one candidate committed without the other.

### 4.6 Error contract

- `400`: malformed/JCS-ineligible manifest, unknown or forbidden fields, wrong write count, duplicate `chapterId`, or syntactically invalid hash.
- `404`: feature disabled, or project/chapter/source-version identity not found as defined in section 4.5.
- `409`: identity mismatch, finalized chapter, source preimage mismatch, idempotency conflict, or retryable lock/deadlock collision.
- `422`: submitted candidate content does not match its syntactically valid `contentSha256`.
- `500`: unexpected server failure only after rollback is confirmed.
- `503`: rollback or commit outcome cannot be confirmed; retry only with the same idempotency key and manifest hash.

Provider credentials, provider base URLs, chapter content, and prompt message bodies must not appear in error logs or response diagnostics.

## 5. Testing strategy

### 5.1 Gateway contract tests

- Closed input schema, required-field rules, and providerId-over-project resolution behavior.
- Loopback-only URL parsing, credential rejection, and redirect rejection.
- Identifier-only request construction.
- Rejection of every forbidden secret/adapter key, including nested occurrences.
- Fixed non-stream proxy endpoint selection.
- Fake success response normalization.
- Exact diagnostic allowlist and rejection of raw head/tail/body fields.
- Timeout/abort behavior.
- Proof that only the injected fake `fetch` was called.

Passing these tests grants `Gateway Contract Ready` only.

### 5.2 Transaction unit tests

- Canonical JSON and manifest hashing.
- Input validation and exactly-two-write enforcement.
- Disabled-by-default router behavior and disposable-pool identity enforcement.
- Idempotency state transitions.
- Stable lock ordering.
- Commit/rollback outcome-unknown recovery mapping.
- Mapping of domain failures to safe HTTP errors.

Passing these tests grants `Transaction Unit Ready` only.

### 5.3 Disposable-MySQL integration tests

The test command requires an explicit admin/server DSN without a database name, supplied as `CONTROL_PLANE_DISPOSABLE_MYSQL_DSN`, whose host is `127.0.0.1`, `localhost`, or `::1`. It generates a cryptographically random schema named `novel_creator_control_plane_disposable_<random>`, aborts if that schema already exists, initializes it from a dedicated test-only fixture containing only the baseline `projects`, `chapters`, and `chapter_versions` DDL needed by this slice, applies only the new ledger migration, and injects a pool bound to that schema into the test app/service.

The disposable harness must never execute, parse, or rewrite `backend/schema.sql`, because that file contains fixed `CREATE DATABASE novel_creator` and `USE novel_creator` statements. The dedicated fixture must contain no `CREATE DATABASE`, `DROP DATABASE`, or `USE` statement. Before and after fixture/migration execution, the harness runs `SELECT DATABASE()` and requires the exact generated schema name. It must never import the configured product database name or reuse an existing schema.

The integration suite calls the service directly and uses a minimal test FastAPI app only for route-contract cases. It never imports `backend/main.py`, runs the application lifespan, or starts/stops a backend or MySQL service. Normal and exceptional cleanup drops only the exact generated schema after revalidating its prefix and random run token; an interrupted run prints the exact orphan schema name for deliberate later cleanup.

Required cases:

- Two candidates commit together.
- Forced failure after the first candidate insert leaves zero candidates.
- Same key and same hash replays without duplicates.
- Same key and different hash returns 409 without writes.
- Source preimage drift returns 409 without writes.
- A finalized chapter is rejected without writes.
- Reversed chapter order still locks in stable order.
- Concurrent identical submissions produce one committed batch.
- Migration apply and rollback operate only on the disposable schema.
- Same-key replay resolves an injected `commit_outcome_unknown` whether the original commit landed or did not land.

The forced failure after the first candidate insert is injected only through a test-created service dependency/callback. No HTTP field, production environment variable, module global, or product-app factory exposes a failpoint.

Passing these tests grants `DB Ready` for the transaction service only.

### 5.4 Readiness matrix

| Label | Minimum evidence | Explicitly does not mean |
|---|---|---|
| Gateway Contract Ready | Fake-HTTP gateway tests | Provider, DB, or live readiness |
| Transaction Unit Ready | Pure unit tests | Real transaction behavior |
| DB Ready | Disposable-MySQL integration suite | Real DB or live readiness |
| AI Proxy Ready | Future explicitly approved backend-proxy call | DB or live readiness |
| Live Ready | Future explicit product approval plus fresh real evidence | Never inferred from fake adapters |

No phase-e report or historical artifact can grant any label in this matrix.

## 6. Execution and audit model

Implementation should be decomposed into independently reviewable commits:

1. Supported test entry point and Node QA gateway with fake-HTTP tests.
2. Transaction primitives, migration, domain service, and API endpoint with unit tests.
3. Disposable-MySQL harness and integration tests.

The product-control thread reviews after each commit:

- Diff is confined to the approved slice.
- No provider/model endpoint was contacted.
- No product `MYSQL_CONFIG` or product database configuration was consumed.
- No legacy phase-e runner was reused.
- Test output supports only the readiness label claimed.
- Git status contains no unrelated or generated artifacts.

An independent reviewer should examine security boundaries, transaction atomicity, idempotency behavior, and test evidence before the slice is considered complete.

## 7. Branch and release policy

- Immutable reconciliation baseline: `4b85e8d1632e190a5a19b60400516591d360407a`.
- Working branch: `codex/control-plane-reset`.
- `origin/main` remains the release branch and is not modified in this slice.
- The working branch must not be described as canonical remote product code until it is reviewed, reconciled, and merged through an explicit release decision.
- A future release tag may pin the reconciled commit, but tag creation is outside this slice.

## 8. Acceptance criteria

The slice is accepted only when all of the following are true:

- The supported default tests are deterministic and require no service, provider, or database.
- The Node gateway cannot accept provider credential/configuration fields, structured provider options, or adapter objects and is covered by fake-HTTP tests.
- The backend service accepts exactly two draft candidate writes and cannot mutate final state.
- The router is absent from `backend/main.py`, defaults disabled, and rejects any non-disposable injected pool.
- Manifest hashing and idempotency conflicts behave as specified.
- Disposable-MySQL tests prove atomic commit, rollback, replay, collision handling, and finalized-chapter rejection.
- No test or implementation contacts a real provider or the real/product Novel Creator database.
- No replacement, finalization, or live action occurs.
- Product-control and independent review find no scope expansion or unsupported Ready claim.
