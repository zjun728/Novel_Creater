# Cross-Server Writer Core Product Bootstrap Design

## Goal and authority

Provide one guarded command that reads the approved foundation inventory from a legacy MySQL 5.7 server and initializes an absent Writer Core V1 product database on the configured MySQL 8 server. Dry-run is the default. Execute requires `--execute`, `--confirm-bootstrap` equal to the configured target database, an absent target, and a private CLI authority that direct Python callers cannot construct.

Product execution is limited to the configured `novel_creator` target. The core also accepts disposable `novel_creator_test_<32 lowercase hex>` targets so the MySQL 8 integration test can exercise the same DDL/transaction path without product access. Every execute call, including a disposable target, requires the private CLI execute authority; the integration test injects that same private token explicitly. Dry-run retains separate product read authority.

## Legacy source boundary

The source is read only through an explicitly supplied mysql client executable. Every subprocess command is an argument array with `shell=False`, `--login-path=novel57-admin`, `--database=novel_creator`, batch/raw/no-column-name flags, and one query from a closed constant whitelist. No password or DSN is accepted or rendered.

The whitelist contains one source capability query plus exactly three inventory queries for `projects`, `creative_seeds`, and `provider_profiles`. Inventory queries render each row with `JSON_OBJECT`, producing one JSON object per physical output line without tab/newline ambiguity. Project and seed filters contain no non-ASCII SQL literals: they use fixed UTF-8 hex values with byte-exact `BINARY title = 0x...` and `IN (...)` predicates, so selection is independent of the MySQL 5.7 client's negotiated charset and collation. The reader captures stdout/stderr in memory, rejects nonzero exits and malformed JSON generically, and never prints raw client output. It never queries legacy derived tables or task bindings.

The source capability result must identify MySQL 5.7 with JSON support. Inventory cardinality is exact: one `永乐大典` project, one row for each of `永乐长明`, `文渊山海`, and `典镇山河`, all Provider rows, and exactly one Provider whose legacy name/model are `联通云-DeepSeek-V4-Flash` and `DeepSeek-V4-Flash`.

## Mapping and pre-DDL validation

The bootstrap imports the reset module's existing project, seed, Provider, uniqueness, target-collation, JSON/hash, decimal/default/length, insert, and empty-derived-table functions. It does not duplicate those conversions.

The preferred legacy Provider is mapped first, then its target display name/model are canonically rewritten to `联通云` and `deepseek-v4-flash`. Every other Provider uses the existing V1 mapping unchanged. IDs remain stable. Target MySQL 8 performs the authoritative `utf8mb4_0900_ai_ci` collision checks for seed titles and final Provider display names before any DDL.

The resulting foundation selects `典镇山河`, creates Canon revision zero and projection head zero, and creates one canonical task binding with all eight task items pointing to the preferred Provider/model.

## Target lifecycle

The target connection comes only from `require_mysql_config()` and the existing aiomysql admin connection factory. Both dry-run and execute verify the complete MySQL 8 capability gate, confirm the target schema is absent, load and map the full source inventory, and perform target-collation validation before DDL.

Execute acquires a dedicated advisory lock, rechecks target absence, creates the database with `utf8mb4_0900_ai_ci`, calls the official initializer, starts a transaction, inserts the shared foundation state, verifies all expected foundation counts and every derived table count, commits, then releases the lock. The target is considered bootstrap-owned only after `CREATE DATABASE` returns successfully; a failed CREATE never authorizes a DROP.

Any failure after owned DDL begins triggers best-effort rollback, drop of the incomplete target, and lock release. Cleanup failures are combined with the original failure in a `BaseExceptionGroup`. If CLI orchestration and target-session close both fail, both errors are likewise preserved. The source is never mutated.

## Output and secrecy

The receipt contains only project/seed/Provider IDs, project/seed titles, Provider display names/models, preferred Provider ID, and aggregate counts including eight binding items. It excludes passwords, API keys, base URLs, descriptions, notes, thinking configuration, DSNs, raw source rows, raw subprocess diagnostics, and target connection metadata.

`--help` exits zero without reading either server. Runtime errors use one generic failure banner.

## Tests

Pure unit tests inject the subprocess runner, source reader, target session/factory, clock, ID factory, initializer, inserter, and cleanup operations. They prove the fixed SELECT whitelist, shell-free commands, exact mapping and rename, zero derived/binding source reads, dry-run no writes, execute authority and absence gates, eight canonical bindings, secret-free receipts, and grouped rollback/drop/release failures.

A marked disposable MySQL 8 integration test uses an injected in-memory source snapshot and a disposable absent schema to exercise capability checks, official initialization, insertion, verification, commit, and cleanup. It is added but not run in this implementation turn.
