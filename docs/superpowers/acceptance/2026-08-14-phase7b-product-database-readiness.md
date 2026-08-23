# Phase 7B Product Database Readiness Acceptance

**Accepted:** 2026-08-23  
**Repository branch:** `main`  
**Accepted code HEAD:** `064265d9174fdec0e24cc2d69aab3fd2a03c5156`

## Outcome

Phase 7B reached `legacy_retained`. The normal local configuration now selects
`novel_creator_v113`; `novel_creator` remains present and unchanged. Stage A
backup, restore drill, initialization, official-data audit, read-only browser
smoke, receipt publication, Stage B atomic cutover, normal configured smoke,
formal post-cutover browser smoke, the final test matrix, and the production
frontend build all completed successfully.

No real Provider call was made. The formal browser boundary allowed only the
two run-owned loopback origins and aborted every other request before it could
leave the browser. Runtime evidence reported zero Provider calls, zero outbound
requests, and zero owned process, port, root, or artifact residue.

## Immutable evidence

- MySQL server: `8.4.10`
- Schema version: `writer-core-v1.13.0`
- New schema table count: `91`
- Legacy table count: `49`
- New manifest hash: `89b21cba12141afa1a2076cb70c559cd2bd13d71eb904c37c6ce5becc24fd857`
- New structural fingerprint: `41495d94b58b446533cb63b494f449bedbf6def206ed9e20b2e83f84e34c70b6`
- Legacy inventory hash: `4c2d29330785c1715907959bb4c02717362f8147570cac458f8b5c6b9e6adaca`
- New inventory hash: `135b3d58c4ca3722fdf0d4f45f1e6de62c00af9b36c31f4245d0cc6670687c27`
- Exact static counts: styles `10`, experience cards `64`, market sources `2`
- Asset package: version `writer-core-v1.1.0`; manifest SHA-256
  `884fa1ec3290550562b328932f908081318e922b2fe97a28f6abb2a90d026070`
- Style content SHA-256:
  `7c2e6fb458774282b11a08b726b6c9c10bc61e32e212736e02e9c060879a9333`
- Experience-card content SHA-256:
  `60f7c6a713167a26d737b91a62c43012e5f77c8a9bb89e7b877099bf8f6e995b`
- Market package: version `market-sources-v1.0.0`; manifest SHA-256
  `8b30a0f42b8b4de95bcbe7f9a1bda9765c82708b29f09a14015a413e2e7340e9`
- Market-source content SHA-256:
  `d07262fd7063bad904de20369b1587d9a530c66ed06e70c6633e033722b53b4e`
- New nonempty table count: `10`
- New total static row count: `158`
- Preparation receipt hash: `0c4bfb8bd8184c901850cfa85ac925d4d836ba7f4ebe3a24a50bdee9d4ce475a`
- Backup basename: `novel_creator-phase7b-372869ba0a2089d7f173d2da0a72b8e5.sql`
- Backup SHA-256: `de0ddcee61eb95beefae6657730a63ed2e91f30db241d0d542f96c9dcc39c8b3`
- Backup byte length: `44,520,136`

The receipt loader independently matched the receipt state, filename, backup
digest, and byte length. Both database inventories matched the hashes bound into
the Stage A receipt before and after cutover.

### Restore and receipt-chain proof

The Stage A receipt contains this exact ordered, hash-linked state chain:

- `inventory_verified`:
  `4c2d29330785c1715907959bb4c02717362f8147570cac458f8b5c6b9e6adaca`
- `backup_created`:
  `e3bb2cd0052bd19831fbf254b0caa528062a15963435bd841f16caa5d40ed27b`
- `restore_drill_verified`:
  `32be88d7f7bf1bd5290712c0275989e86c81b84116756ad68e7786d8a53c1666`
- `new_database_initialized`:
  `873cdf4cc7a56aff50cbee7dbfc239370cff7d6e84b8ccfb2b817017b8b76d68`
- `official_data_seeded`:
  `202d0fab8ef0afc723823569d86f1a5616d3a4c24f1b73c9e281dbb8963253bb`
- `readiness_verified`:
  `135b3d58c4ca3722fdf0d4f45f1e6de62c00af9b36c31f4245d0cc6670687c27`
- `awaiting_cutover_approval`:
  `ef0eada8bece33882eed00b55f1ab562ce8b3426790cb03103ca1eca2893f58b`

The restore state is published only after the restored inventory equals the
legacy authority on the exact table set, schema version, manifest hash,
structural fingerprint, and every per-table row count. Its ownership ledger
also requires the single created restore database to be the single cleaned
restore database. The post-acceptance server audit found `0` matching restore
databases and `0` matching disposable test databases; both `novel_creator` and
`novel_creator_v113` remain present.

### Empty-state proof

The new database has `91` tables. Exactly the approved 10 infrastructure/static
tables are nonempty; all other `81` tables contain `0` rows. Explicit grouped
audits also found:

- Provider/model-binding: `5` tables, `0` rows.
- Corpus and import: `10` tables, `0` rows.
- Draft, generation, and story-engine: `19` tables, `0` rows.
- Finalization/final chapters: `4` tables, `0` rows.
- Market snapshots, refresh requests, and analyses: `5` tables, `0` rows.

No backup/import payload was loaded into the product database. The sole retained
backup is the approved external Stage A SQL file identified above.

## Controlled commands

Stage A used the approved external backup directory and explicit MySQL 8.4
client paths. Private absolute paths are redacted here:

```text
python -m backend.scripts.prepare_product_database --legacy-database novel_creator --new-database novel_creator_v113 --backup-dir <APPROVED_EXTERNAL_BACKUP_DIRECTORY> --mysqldump <APPROVED_MYSQL84_MYSQLDUMP> --mysql <APPROVED_MYSQL84_MYSQL> --execute --confirm-legacy novel_creator --confirm-new novel_creator_v113 --confirm-prepare PREPARE-PHASE7B
```

Stage B used the hash-bound external readiness receipt:

```text
python -m backend.scripts.cutover_product_database --receipt <APPROVED_EXTERNAL_READINESS_RECEIPT> --database novel_creator_v113 --confirm-cutover CUTOVER-PHASE7B --execute
```

The successful Stage B result was `state=legacy_retained`.

## Configuration and recovery evidence

- Before cutover, the exact local configuration SHA-256 was
  `0e3ddb3683e9c878bc1b2d7244c643dc013716a194df9555e837b8000a35f032`
  and `MYSQL_DB=novel_creator`.
- After cutover, replacing only `MYSQL_DB` with `novel_creator` in memory
  reproduced that exact pre-cutover SHA-256. This proves all other keys and
  values were preserved.
- The published configuration contains exactly the five approved `MYSQL_*`
  keys, selects `novel_creator_v113`, and grants only the current Windows owner
  `Read`, `Write`, `Delete`, and `Synchronize` access.
- The first Stage B attempt failed before publication because the private
  temporary ACL lacked Windows `DELETE`; the original configuration hash and
  database selection remained unchanged. The exact owned temporary residue was
  permission-corrected and removed.
- The failed first Stage B attempt stopped before publication, independently
  proving that its failure path preserved the byte-identical original config.
  The successful Stage B needed no post-publication rollback. Disposable
  cutover tests separately exercised smoke-failure rollback, fresh-lock CAS,
  contention, concurrent-edit preservation, cleanup ordering, and
  flow-control propagation without mutating the real configuration.
- The supported explicit recovery command remains:

```text
python -m backend.scripts.cutover_product_database --recover-legacy --database novel_creator --confirm-cutover RECOVER-PHASE7B --execute
```

## Verification results

- Phase 7B post-cutover formal browser gate, using normal configuration with no
  inherited `MYSQL_*` override: `scenarioCount=1`; `providerCalls=0`;
  `outboundRequests=0`; `processCount=0`; `portCount=0`; `rootCount=0`;
  `artifactCount=0`; no first failure stage or cause.
- Focused ACL/cutover/prepare regression: `493 passed`.
- Focused formal-browser/cutover/prepare regression: `438 passed`.
- Final focused post-cutover runner regression: `39 passed`.
- Final real Windows ACL regression: `94 passed`.
- Phase 7B Node browser contract: `41 passed`.
- `npm test`:
  - Python: `5,140 passed, 9 skipped`.
  - Node formal suites: `432 passed`.
  - Frontend: `783 passed`.
- `npm run test:integration`: `393 passed, 7 skipped` in `3,609.57s`;
  disposable MySQL `created=391`, `cleaned=391`, `remaining=0`. This matrix ran
  on `3b9c317`; later changes were confined to local-config ACL/browser command,
  browser-only boundary code, and their unit/contract tests, with no integration
  database path change.
- `npm run build`: Vite `8.0.13`, `2,978` modules transformed, build succeeded.
- `git diff --check`: clean for every delivered code change.
- Task-owned `tmp/pytest-phase7b-*` directories removed: `23`; remaining: `0`.
  The pre-existing user-owned `.review-worktrees/` directory was not modified.

## Independent reviews

- Initial specification review: Critical `0`, Important `4`, Minor `0`.
  All four findings were remediated: normal-config post-cutover mode, exact
  static/restore/review evidence, explicit prohibited-state zeros, and removal
  of task-owned test residue.
- Initial quality review: Critical `0`, Important `1`, Minor `1`. Both findings
  were remediated with a browser-side outbound deny boundary and a real Windows
  ACL replace/delete test.
- Final specification review before the boundary-isolation follow-up:
  Critical `0`, Important `0`, Minor `0`.
- Final quality review identified two documentation/commit-identity findings
  after the boundary-isolation follow-up: Critical `0`, Important `2`, Minor
  `0`. Both were closed by committing `064265d`, binding this document to its
  full hash, and recording the fresh `npm test` counts above.
- Final post-remediation specification review: Critical `0`, Important `0`,
  Minor `0`.
- Final post-remediation quality review: Critical `0`, Important `0`, Minor
  `0`.

## Delivered fixes

- `457959a` — reopen Windows receipt identities with shared delete access.
- `a6aa6fc` — use stable Windows birth time for receipt path/handle identity.
- `e3d2eed` — grant the private current-user ACL the delete right required for
  atomic configuration replacement and failure cleanup.
- `3b9c317` — provide the formal Phase 7B browser runner its exact new-database
  and disabled-scheduler environment.
- `5cf8ab6` — use normal post-cutover configuration, deny non-owned browser
  origins before transmission, and add real Windows ACL lifecycle coverage.
- `064265d` — isolate the Phase 7B route boundary from the shared UI-only
  runtime observer and restore all historical browser source contracts.

## Retention boundary

`novel_creator` is retained; no legacy table was deleted; retirement requires a
separate post-Phase-7C approval.

Phase 7B did not enable real Provider traffic and did not perform any legacy
database or table deletion.
