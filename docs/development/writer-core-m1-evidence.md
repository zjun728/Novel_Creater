# Writer Core M1 Evidence

## Evidence identity

- Date: `2026-07-11`
- Evidence level: **L4 M1 No-Provider Ready**
- Branch: `codex/writer-core-v1`
- Baseline: `4b85e8d`
- Evidence code snapshot before this documentation closeout: `54e62ee`
- Worktree: isolated Writer Core V1 implementation worktree

This evidence closes M1 only. It does not claim Provider readiness, body-generation readiness, product completion, or content quality.

## Runtime and retained rollback boundary

- Product database: MySQL `8.4.10` at `127.0.0.1:3307`, schema `novel_creator`.
- Legacy database: MySQL `5.7.25-log`, retained read-only as the rollback source.
- The product runtime uses only the MySQL 8 product database. The legacy database is not a compatibility path and is not written by M1.

## Reconciled foundation data

- Project: `永乐大典`
- Project ID: `88d63943-ab7d-42c4-9319-998b6d61e413`
- Seeds: `典镇山河` (selected), `文渊山海`, `永乐长明`
- Provider profiles: `9`
- Preferred Provider/model: `联通云 / deepseek-v4-flash`
- Task-level binding items: `8`, all pointing to the preferred Provider/model

No old chapter, draft, planning, memory, relation, or other derived writing state was promoted into the Writer Core V1 product database.

## Schema and empty-state evidence

- Schema version: `writer-core-v1.0.0`
- Manifest SHA-256: `0697b6da4826b98c8e502ff7ad68a61b51fe7037b167b6d8175ae9d78dcff826`
- Tables: `34`
- Canon head: `0`
- Projection head: `0`
- Derived writer tables empty: `25/25`

The page and database evidence correlated the same project ID and the same Canon/Projection heads.

## Provider and secrecy boundary

- Sensitive Provider rows matched the in-memory expected inventory: `9/9`.
- API plaintext sensitive-value hits: `0`.
- API exact forbidden-key hits: `0`.
- AI completion / upstream Provider model calls: `0`.

No sensitive row values, raw source rows, connection material, or Provider diagnostics are recorded in this document.

## Automated evidence

- Real MySQL 8 cross-server integration: `2/2` passed.
- Final M1 gate code snapshot: `f9bfd2f`.
- `npm run test:milestone1`: exit `0`.
- Unit results:
  - Python: `393` passed
  - scripts Node tests: `24` passed
  - frontend Node tests: `11` passed
- Integration suite: `30 passed, 1 deselected`.
- Disposable database accounting: created `29`, cleaned `29`, remaining `0`.
- Post-test product database counts: `PASS`.
- Ports `8000` and `5173` after the gate: free.

## Product browser evidence

- Browser suite: `2/2` passed.
- Browser disposable database: dropped.
- Product requests: `8`, all `GET`, including the `/api/providers` configuration read.
- AI completion / upstream Provider model calls: `0`.
- Console errors: `0`.
- Console warnings: `0`.
- The project library and project foundation view read the reconciled product state.
- The retired Writer entry returns to the project library.
- Writer remains explicitly disabled at M1.

Screenshots remain local under ignored `output/playwright/product-ui`. They are evidence artifacts only and are not committed to Git.

## Dry-run encoding findings and fixes

The real legacy dry-run exposed two MySQL 5.7 client-encoding failures. Both were reproduced with focused contracts and fixed through TDD:

1. With a `latin1` connection, ordinary equality against non-ASCII SQL title literals did not match the stored UTF-8 bytes. The fixed project and seed filters now use ASCII-only, byte-exact `BINARY` predicates with fixed UTF-8 hex values.
2. The legacy client could emit a non-UTF-8 byte such as `0xB7`, causing text-mode subprocess decoding to fail before the reader could validate output. All four fixed source queries now transport `HEX(JSON_OBJECT(...))`; the subprocess captures bytes and strictly decodes ASCII hex to UTF-8 JSON objects without rendering raw failures.

The legacy source remains read-only, the whitelist remains four fixed `SELECT` statements, and no table or column scope was expanded.

## Conclusion and next dependency

M1 is closed at **L4 M1 No-Provider Ready** only. There was no AI completion / upstream Provider model call, no body generation, and no content-quality evaluation, so this evidence makes no claim about generated prose or the end-to-end writing workflow.

The only authorized next action is to write and audit the detailed M2 plan for `CreationContract`, `StyleContract`, corpus assets, and experience assets. M2 implementation does not begin until that separate plan is approved.
