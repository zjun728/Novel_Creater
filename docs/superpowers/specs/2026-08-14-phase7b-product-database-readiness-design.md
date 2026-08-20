# Phase 7B Product Database Readiness Design

## Status

Approved design for preparing a new Writer Core v1.13 product database beside the existing v1.1
product database, proving the old database backup is restorable, and placing the final application
configuration switch behind a separate human approval gate.

## Observed starting state

The repository is on `main` at the accepted Router Domain Migration head. The configured local
product database is `novel_creator` on MySQL 8.4.10. A read-only inventory on 2026-08-14 established:

- the database metadata reports `writer-core-v1.1.0`;
- it contains 49 tables, while the immutable current manifest requires 91 tables and
  `writer-core-v1.13.0`;
- the manifest hash does not match the current repository manifest
  `89b21cba12141afa1a2076cb70c559cd2bd13d71eb904c37c6ce5becc24fd857`;
- 46 current tables are absent and four retired planning tables remain;
- 33 tables are non-empty, including one project, three creative seeds, nine Provider profiles, and
  a corpus containing 1,579 chapters and 6,306 fragments;
- all observed tables use InnoDB and `utf8mb4_0900_ai_ci`.

The application performs schema verification only and must not execute DDL during ordinary startup.
The existing initializer accepts only an absent or empty target database. There is no supported
v1.1-to-v1.13 migration path.

MySQL client programs are not currently on `PATH`. Installed clients found during discovery are
MySQL 5.7.25 and MySQL Shell/Workbench 8.0.14, both older than the MySQL 8.4.10 product server. Phase
7B must fail before backup work unless an explicitly selected MySQL 8.4-compatible `mysqldump` and
`mysql` client pair passes a version/capability preflight. It must not silently select the legacy
installed binaries.

## Goals

Phase 7B will:

1. preserve the existing `novel_creator` database without Phase 7B DDL/DML and prove its table set,
   structural fingerprint, and per-table row counts remain unchanged as the live rollback database;
2. create a private logical backup outside the repository and prove it can be restored;
3. initialize a separate `novel_creator_v113` database from the exact current manifest;
4. seed only the approved built-in Writer assets and market sources;
5. prove the new database and a temporarily configured application are ready without calling a
   Provider or making outbound requests;
6. stop at a human approval gate before changing `.env.local.json`;
7. after separate approval, atomically switch the application to the new database and prove the
   normal configured startup path;
8. retain the old database until Phase 7C real-Provider and `典镇山河` acceptance succeeds and the
   user separately approves whole-database retirement.

## Non-goals

Phase 7B does not:

- migrate old project, Provider, corpus, draft, Canon, projection, backup, or import-command rows;
- alter the v1.13 schema manifest or add a v1.1-to-v1.13 migration framework;
- delete, rename, update, lock for writes, or partially prune the old database;
- create a project or copy Provider credentials into the new database;
- call a real Provider, fetch market data, or evaluate generated content;
- deploy a live site, add production monitoring, or perform the Phase 7C thirty-chapter acceptance;
- delete individual legacy tables. Old storage retirement is a later whole-database operation.

## Selected strategy

The selected strategy is a controlled parallel cutover.

- Old database: `novel_creator`, retained unchanged.
- New database: `novel_creator_v113`, created from the v1.13 manifest.
- Restore-drill databases: a random name matching one closed Phase 7B-owned prefix and 32 lowercase
  hexadecimal characters.
- Configuration: unchanged throughout preparation; temporary application processes receive
  `MYSQL_DB=novel_creator_v113` as a process-local environment override.
- Permanent configuration cutover: a second stage that cannot execute without a new explicit user
  approval.

An in-place migration is rejected because authority, revision, hash, and projection shapes changed
across the 42-table delta and no production migration contract exists. Rebuilding the same database
name is rejected because rollback would depend on restoring the dump rather than selecting the
untouched old database.

## Architecture

### 1. Readiness inventory

A read-only inventory component connects through the existing strict local MySQL configuration and
returns only safe metadata:

- configured-database identity equality;
- server version;
- schema version and manifest-hash equality;
- table names, engines, collations, and per-table row counts;
- deterministic structural fingerprint derived from information-schema tables, columns, indexes,
  foreign keys, and CHECK constraints.

It never returns business IDs, text columns, Provider fields, credentials, or connection strings.
The old-database inventory becomes the authority for the backup restore drill.

### 2. External client preflight

The preparation command requires explicit absolute paths to `mysqldump.exe` and `mysql.exe`.
Preflight verifies that both paths are regular files, are outside the repository, report an accepted
MySQL 8.4-compatible version, and can connect to the configured server with a read-only capability
query. No executable is discovered by taking the first item on `PATH`.

Credentials are supplied through a command-owned temporary MySQL option file, never through command
arguments or output. The option file is created outside the repository, receives current-user-only
ACL before credential content is written, is flushed, and is removed with bounded cleanup on every
exit path.

### 3. Private logical backup

The user supplies an explicit absolute `--backup-dir` outside the repository. The directory must
already exist, must not be a symlink/reparse-point escape, and must be restrictable to the current
Windows user.

The dump is an InnoDB-consistent logical backup using a single transaction, quick streaming, binary
safe data, triggers, routines, and events. It does not include `CREATE DATABASE` or `USE` statements,
so the same dump can be restored only into an explicitly selected drill database. The application
and task-owned product writers must be stopped before the inventory/dump pair, preventing row-count
drift across the proof boundary.

The command writes to a private temporary file, flushes it, computes SHA-256 and byte length, then
atomically publishes the final dump. A later failure never deletes a successfully published backup.
The safe receipt contains only backup filename, SHA-256, byte length, client version, source schema
version, source structural fingerprint, table count, non-empty-table count, and total row count.

### 4. Restore drill

The restore drill creates one random Phase 7B-owned database with `utf8mb4_0900_ai_ci`, imports the
dump, and compares it with the pre-dump authority:

- exact table set;
- schema metadata version and hash;
- deterministic structural fingerprint;
- exact per-table row counts.

The drill never runs application services or Provider code. It drops only the exact random database
created by the current command, after revalidating its closed name and ownership ledger. Restore
failure preserves the backup but fails preparation. Cleanup failure is reported separately and
cannot be hidden by the primary restore failure.

### 5. New database initialization

`novel_creator_v113` must be absent or empty. Any non-empty or partially initialized state fails
closed; Phase 7B does not patch it in place. Initialization delegates to the production manifest and
must produce:

- schema version `writer-core-v1.13.0`;
- manifest hash `89b21cba12141afa1a2076cb70c559cd2bd13d71eb904c37c6ce5becc24fd857`;
- exactly 91 manifest tables;
- InnoDB and `utf8mb4_0900_ai_ci` throughout.

If this invocation created the new database and a later preparation step fails, it may drop only
that exact current-run-owned database after identity revalidation. It never treats `novel_creator`
as a cleanup target. A pre-existing exact-ready new database is audit-only and may be resumed; a
pre-existing partial or unknown database requires separate explicit cleanup approval.

### 6. Official static data seed

Preparation uses process-local `MYSQL_DB=novel_creator_v113` and the existing explicit seed services.
It seeds exactly:

- Writer asset package `writer-core-v1.1.0`: 10 style templates and 64 experience cards;
- market-source package `market-sources-v1.0.0`: two built-in sources and their closed policy/refresh
  authorities.

Package hashes and exact counts are derived from their production manifests. Seeding must be
idempotent. The post-seed audit requires zero projects, zero Provider profiles, zero corpus sources,
zero drafts/final chapters, and zero project import/package history. No market refresh is executed.

### 7. Temporary application smoke

Before permanent cutover, a task-owned backend and frontend start on reserved loopback ports with a
process-local new-database override. The smoke path exercises only public UI/API reads:

- health succeeds and startup accepts the exact schema;
- project library is an explicit empty state;
- Writer asset inventory exposes the approved 10/64 package;
- market source inventory exposes the two built-in sources;
- Provider inventory is empty and no Provider readiness call is attempted.

The runtime observer fails on console/page errors, unexpected origin, non-2xx responses, request
failures, listener residue, Provider/outbound traffic, or owned process/port/temp residue. It does
not write projects or alter application settings.

#### Browser sandbox ownership amendment

The browser process runner does not create, own, rename, or recursively delete its own root. Node.js
cannot atomically create and bind a Windows directory identity before an untrusted path replacement,
so a `mkdtemp` followed by `stat` or `open` is not an ownership proof.

A narrow Python outer owner creates the private browser sandbox, binds its creation identity to a
Windows no-share-delete directory lease, starts the Node lifecycle runner, and retains that lease
until every child process has stopped. The Node runner receives the root and a one-run nonce, treats
the root as borrowed, and may create only direct task artifacts inside it. It never recursively
deletes the root and never emits the final zero-resource acceptance marker.

The Node runner returns a private, fixed-schema scenario/runtime evidence record to the Python owner.
Only after the owner has stopped the process tree, audited reserved ports, removed task artifacts,
deleted the exact leased root, and closed the lease may it emit the canonical
`PHASE7B_BROWSER_SMOKE_SUMMARY=` record. The canonical record contains only fixed stage/cause,
scenario, Provider/outbound, process, port, root, and artifact counts. Cleanup failure produces the
true nonzero count or a fixed cleanup category; it never pre-reports zero.

Stage A reuses the lease already held by `prepare_product_database.py`. The standalone formal
`browser-phase7b` target invokes the same Python owner/finalizer through a narrow wrapper, so both
entry points share one ownership and summary protocol. Runner-only root/nonce variables are removed
before the backend is spawned. A backend or Vite process is registered for cleanup immediately after
successful start and before any later observer or setup step can fail.

### 8. Permanent cutover

Permanent cutover is a separate CLI action and a separate user approval. It requires:

- the exact successful preparation receipt and new-database fingerprint;
- current `.env.local.json` still targeting `novel_creator`;
- both databases still present with their recorded identities;
- exclusive ownership of the product-database lifecycle lock;
- explicit `--database novel_creator_v113` and matching confirmation.

The CLI validates `--execute`, the selected mode, the exact database name, and the exact cutover or
recovery confirmation before opening a receipt, backup, configuration document, or database
connection. The published preparation receipt binds the backup basename, SHA-256, and exact byte
length. After approval, cutover derives the sibling backup only from that closed basename and reuses
the backup service's single-open verification boundary: every path component must be non-link and
non-reparse, the opened regular-file identity must match the path identity, `fstat` size must equal
the receipt length before hashing, and the same handle must produce the receipt SHA-256. The command
never hashes an unbounded, differently sized file and never relies on the receipt filename stem.

Normal application startup and cutover share one internal product-database lifecycle lock. Its
opaque name is derived from the normalized absolute `.env.local.json` path and exposes no path or
credential. On Windows it is a zero-wait named mutex with an injectable API for deterministic tests.
On POSIX it is a zero-wait advisory lock on a stable, hash-named file under the operating-system
temporary directory; the empty lock file is not deleted, so inode replacement and cleanup races are
outside the protocol. Both implementations serialize only repository participants and expose the
same acquire/hold/release contract.
The backend acquires it before any database access or background-service startup and retains it
until all gateways, schedulers, registries, and the database pool have completed shutdown. A second
backend instance, an abandoned mutex, acquisition failure, release failure, or close failure fails
with a fixed secret-free lifecycle category; a body failure remains primary over release/close
failures. Flow-control exceptions retain only their safe type and exact integer `SystemExit` code.

Cutover acquires the same lock before reading the configuration, inventory, or writing the CAS
document. This replaces command-line process discovery; process enumeration is not an authority.
The lock is held through evidence revalidation and atomic configuration publication, then released
before normal-config browser smoke so that the smoke backend can acquire and hold it through its
complete lifespan. After the smoke process tree has stopped, cutover reacquires the lock and
revalidates the exact switched snapshot before reporting success. If smoke fails, cutover first
reacquires the lock and only then attempts the one bounded CAS rollback. If another backend wins the
gap, cutover does not overwrite its configuration: the smoke error remains primary and the lock or
rollback failure is retained as cleanup evidence. Recovery uses the same acquire-before-read/write
rule. Repository-supported product startup and administrative cutover are the lock participants;
uncooperative direct filesystem editors remain governed by the existing exact CAS pre/post checks.

#### Locked startup configuration snapshot amendment

The lifecycle lock must precede configuration **observation**, not only database and background
service work. Importing `backend.main`, `backend.database`, routers, services, or scheduler modules
therefore performs no repository-local configuration read and captures no MySQL, corpus-root, or
scheduler value. `LOCAL_CONFIG_PATH` may remain an import-time path constant because deriving that
path performs no configuration I/O.

After startup acquires the lifecycle lock, it reads the local document and environment exactly once
into one closed, immutable runtime configuration snapshot. The snapshot contains the validated
MySQL pool fields, optional discovery and managed corpus roots, and the market-scheduler enabled
flag. Startup installs that exact snapshot before schema verification, reconciliation, pool
creation, route-owned service construction, or scheduler construction. Every backend consumer uses
the installed snapshot; it must not retain an earlier imported value or reread the document during
the same lifespan.

The process owns at most one installed snapshot. Installation fails closed if a snapshot is already
active. Access before installation or after clearing fails with a fixed secret-free configuration
error. Shutdown first drains all application resources and closes the database pool, then clears
the snapshot, and only then releases the lifecycle lock. Startup failure follows the same ordering:
all resources acquired after installation are cleaned, the snapshot is cleared exactly once, and
the lock is released last. Ordinary and flow-control error precedence continues to use the shared
lifecycle boundary; no raw configuration value, path content, credential, or exception metadata is
published.

Administrative scripts remain explicit readers: their existing load functions may read the local
document when the command invokes them, but importing `backend.config` itself is I/O-free. The
backend database pool uses the installed snapshot rather than those command helpers. Request-time
corpus and application-settings paths, creative-asset factories, startup reconciliation, and the
market scheduler all resolve from the same installed snapshot.

This closes the deterministic stale-import race: if cutover owns the lifecycle lock while a backend
process imports its modules, the import observes no database selection. The backend waits for the
lock and only then loads the post-cutover document. Conversely, while a backend holds the lock its
installed snapshot remains authoritative until complete shutdown, so a repository-supported
cutover cannot change the document underneath the running process.

The cutover preserves every existing configuration field and changes only `MYSQL_DB`. It writes a
same-directory private temporary file, flushes and fsyncs it, applies current-user-only ACL, and
atomically replaces `.env.local.json`.

After replacement, the normal configured application starts and repeats the smoke checks. A failed
smoke atomically restores the prior configuration document. If rollback also fails, both errors are
reported and both databases remain untouched. A safe recovery command can switch back to
`novel_creator` with explicit name confirmation; no secret-bearing rollback copy is required.

## State machine

Preparation advances monotonically through these fixed states:

1. `inventory_verified`
2. `backup_created`
3. `restore_drill_verified`
4. `new_database_initialized`
5. `official_data_seeded`
6. `readiness_verified`
7. `awaiting_cutover_approval`

The separately approved cutover advances through:

8. `configuration_switched`
9. `cutover_verified`
10. `legacy_retained`

Receipts are canonical, secret-free documents. Each state binds the previous receipt hash, the
database roles, schema/manifest fingerprints, and safe counts. A command cannot skip a state, accept
a receipt for a different database, or silently continue after a failed step.

## Failure and cleanup rules

- Any client preflight, inventory, backup, restore, initialization, seed, audit, or smoke failure
  stops the stage immediately.
- The old product database is never in an automatic DDL or cleanup allowlist.
- Database names and confirmation values must match exactly and satisfy closed role-specific
  patterns before any receipt, backup, configuration, connection, or DDL access.
- Product startup, cutover, rollback, and recovery use the shared lifecycle lock rather than a
  process-list heuristic. No configuration write occurs without lock ownership.
- Only current-run-created random restore databases and current-run-created new databases are
  eligible for cleanup.
- A successful backup is retained even if all later steps fail.
- Cleanup attempts all independently owned resources in reverse acquisition order.
- Browser sandbox deletion authority belongs only to the Python lease owner. The Node runner is a
  borrower and cannot delete the root or claim a final zero-resource ledger.
- The first operation failure remains primary; cleanup failures are retained without replacing it.
  Flow-control exceptions are never swallowed.
- Logs and receipts contain only fixed stages, error categories, versions, hashes, filenames, byte
  lengths, table names, counts, and resource ledgers. They never contain passwords, DSNs, option-file
  contents, dump contents, SQL row values, business IDs, text, or Provider data.
- No command automatically retries a destructive database action.

## Test strategy

Implementation is test-first.

### Unit contracts

Unit tests cover:

- role-specific database-name guards and double confirmation;
- refusal to target `novel_creator` for cleanup;
- executable version/path validation;
- password absence from command arguments, logs, receipts, and exceptions;
- option-file and backup ACL/atomic-publication cleanup precedence;
- approval-before-I/O ordering and receipt-bound, same-handle backup verification;
- canonical receipt chaining and cross-database replay rejection;
- configuration atomic switch, rollback, crash recovery, and exact-field preservation;
- lifecycle-lock acquisition, abandoned/contended/error states, backend whole-lifespan ownership,
  second-instance rejection, release/close ordering, and sanitized flow control;
- import-time zero-configuration-I/O, lock-before-snapshot ordering, one immutable snapshot per
  lifespan, exact consumer consistency, and clear-before-lock-release on every startup/shutdown
  outcome;
- a deterministic cutover/import race in which backend module import observes no database and the
  later locked startup loads only the post-cutover configuration;
- Windows named-mutex and POSIX advisory-lock implementations producing the same fail-closed
  participant semantics without storing paths, credentials, or business data;
- cutover release-before-smoke, reacquire-before-success, reacquire-before-rollback, and a competing
  backend winning either gap without an unsafe configuration overwrite;
- browser owner/borrower handoff, root identity acquisition, process registration order, truthful
  post-cleanup summary, and primary-before-cleanup failure ordering;
- fixed secret-free error categories.

### Disposable MySQL integration

Integration tests use only random disposable databases and prove:

- a small legacy-shaped fixture can be dumped and restored with exact structural and row-count
  equality;
- current manifest bootstrap produces the exact 91-table v1.13 database;
- official asset and market packages seed their exact counts and replay idempotently;
- all business/Provider/corpus/import tables remain empty;
- failure injection at backup, restore, bootstrap, seed, audit, commit, rollback, and cleanup points
  leaves the correct backup/database/config authority;
- created/cleaned/remaining database ledgers are exact.

### Formal Phase 7B gates

Stage A formal acceptance performs one controlled real-old-database backup and restore drill, then
creates and verifies `novel_creator_v113`. It runs the temporary-override browser smoke exactly once
after all lower-layer gates pass. It must report Provider/outbound zero; restore-drill database
remaining zero; the intentional persistent new product database present exactly once; and owned
process, port, option-file, temp, download, and artifact residue zero.

Stage B runs only after separate approval. It performs the atomic configuration switch, normal
startup smoke, relevant MySQL integration, the full unit suite, frontend production build,
specification review, and quality review. Active Critical and Important findings must be zero.

## Approval gates

The design and implementation plan do not authorize database writes by themselves.

1. Implement and verify the tooling only against disposable databases.
2. Obtain explicit approval before the first real Stage A command creates a backup file, restore
   database, or `novel_creator_v113`.
3. Stop after Stage A readiness and present its receipt.
4. Obtain a second explicit approval before changing `.env.local.json`.
5. Retain `novel_creator` after successful cutover.
6. Only after Phase 7C real-Provider and `典镇山河` acceptance succeeds may a new, separately approved
   task make a final backup and drop the whole old database. Individual old tables are never pruned.

## Public boundary

Phase 7B changes no HTTP route, public DTO, status code, schema manifest, UI state contract, Provider
behavior, or market/network behavior. It adds local administrative tooling, tests, receipts, and
acceptance documentation. Real Provider calls and outbound market refreshes remain zero.

## Acceptance criteria

Phase 7B is accepted only when:

- the old database remains present with no Phase 7B DDL/DML and with its recorded table set,
  structural fingerprint, and per-table row counts unchanged;
- a private logical backup exists outside the repository with verified SHA-256 and restorable proof;
- the restore drill matches the old inventory structurally and by exact per-table row counts;
- `novel_creator_v113` is exact v1.13/91-table current manifest;
- the new database contains only the approved 10 styles, 64 experience cards, and two market sources
  plus their closed static authorities;
- project, Provider, corpus, draft/final, backup, and import business state is empty;
- temporary-override and post-cutover application smoke checks pass with zero Provider/outbound;
- configuration cutover performs no receipt/backup/config/database I/O before the second exact user
  approval, is mutually exclusive with a running product backend, and can be rolled back only while
  holding the same lifecycle lock;
- backend module import performs no repository-local configuration I/O, and each backend lifespan
  loads exactly one immutable runtime configuration snapshot only after acquiring that lock;
- all disposable databases and task-owned processes/files except the published backup are cleaned;
- full verification and both final reviews have no active Critical or Important findings;
- `novel_creator` remains available until the separately approved post-Phase-7C retirement task.
