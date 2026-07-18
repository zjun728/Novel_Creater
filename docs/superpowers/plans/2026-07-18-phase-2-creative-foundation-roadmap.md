# Phase 2 Creative Foundation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development` to execute one delivery package at a time. Each
> implementation task uses test-driven development and receives a spec review
> and a code-quality review before the next task starts.

**Goal:** Deliver the complete creation-preparation path from global creative
assets and safe model configuration through market evidence, seed selection,
story engine, creation contract, and confirmed creation bible.

**Authority:** The only product authority is
`docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`.
The July 11 M2 plans and unreachable M2 pages are implementation history only.

**Baseline:** Start from clean `main@9909eaf510f077104b50b4ca10647e19a344a6f2`
or a later commit containing this roadmap. Use branch
`codex/phase2-creative-foundation` in
`C:\Users\zhangjun\.codex\worktrees\phase2-creative-foundation\Novel_Creater`.

**Tech stack:** Vue 3, Vue Router 4, Pinia 3, Naive UI, Node test runner,
Playwright, FastAPI, Pydantic 2, aiomysql, pytest, MySQL 8.

---

## Delivery constraints

- Do not copy untracked files from another worktree.
- Do not add migration or compatibility branches. Phase 2 builds one exact
  empty-schema manifest, `writer-core-v1.3.0`.
- Do not touch the product database while packages 2A–2D are being developed.
  Every integration/browser run creates and drops a runner-owned database named
  `novel_creator_test_<32 lowercase hex>`.
- Do not call a real Provider/model during packages 2A–2D. Unit tests inject
  strict fakes. Real Provider and product-database acceptance remain Phase 7.
- Do not expose plaintext API keys, Base URLs, passwords, tokens,
  `Authorization` headers, DSNs, corpus roots, or large corpus excerpts in any
  response, error, log, screenshot, or artifact.
- Frontend code never calls a Provider directly. Every AI action uses a typed
  backend gateway and an actual project binding revision.
- Do not add dead Phase 3–6 navigation. At the end of Phase 2 the working
  project modules are Overview, Seeds, Contract, Bible, and Model Binding.
- Test behavior through services, HTTP, rendered components, and browser
  interaction. Source-regex assertions may supplement but never replace
  behavioral tests.
- Keep the approved `writer-core-v1.1.0` asset package version. Schema version
  and asset package version are independent.
- Delete superseded runtime code in the same package that replaces it. Preserve
  historical plans and acceptance reports as non-runtime evidence.

## Frozen product decisions

- Global navigation contains Project Library, Creative Assets, and Settings.
- Creative Assets owns `/assets/styles`, `/assets/experience`, and
  `/assets/corpus`; Settings does not duplicate asset management.
- A project owns any number of seed candidates and exactly one active
  selection. `activeSeedSelectionRevision` increases on every selection,
  including reselecting an older seed.
- Seed selection is a separate project module. The contract wizard does not
  repeat seed selection.
- A seed may be entered manually or saved explicitly from AI/market
  inspiration. AI chat never creates a seed implicitly.
- Story-engine generation returns exactly three structured choices. Manual
  entry uses ordinary form fields, never raw JSON.
- A contract freezes the exact seed-selection revision, engine option, primary
  and secondary styles, experience cards, corpus versions/fragments, capacity
  targets, and prohibited directions.
- Confirmed contracts are immutable revisions. Editing starts a new draft based
  on a selected historical revision and affects future work only.
- A confirmed contract enables creation-bible drafting. A bible cannot be
  deleted or reset; edits create new immutable revisions.
- Manual seed, engine, contract, and bible work remains available without a
  ready model. Only the corresponding AI action is blocked.
- The first finalized chapter locks active-seed switching and editing of every
  referenced seed. Unreferenced candidates may still be created and permanently
  deleted with one danger confirmation.

## Schema target and aggregate fence

Phase 2 creates `writer-core-v1.3.0` once in package 2A. The manifest adds:

- application fallback settings;
- immutable seed-selection revisions plus one active selection head;
- content-addressed corpus blobs and immutable corpus source revisions;
- market sources, refresh state, immutable snapshots, entries, and analyses;
- seed provenance and selection generation references;
- `selection_revision` on engine batches, contract drafts, contracts, and
  confirmation requests;
- corpus-fragment manifests frozen by contracts;
- creation-bible drafts, attempts, revisions, heads, and confirmation requests.
- selection/contract/Bible generation references on planning roots and chapter
  sessions, inherited transitively by working drafts and candidates.

The active chain is:

```text
project
  -> projectSeedSelectionHead.activeSeedSelectionRevision
  -> immutable projectSeedSelectionRevision
  -> storyEngineBatch.selectionRevision
  -> creationContract.selectionRevision
  -> creationBible.selectionRevision + contractRevision
```

Every active/readiness query must match all upstream IDs, revisions, and hashes.
An older row remains readable but is `superseded`; it can never become active
again merely because the same seed revision is selected later.

Planning roots and chapter sessions store the upstream generation directly.
Working drafts and candidates are pinned through their non-null FK to the
immutable chapter session rather than duplicating the generation fields. Every
“current draft/session” query joins that session and compares selection,
contract, Bible, and planning manifest revisions/hashes before returning an
active result.

## Package sequence

| Package | Plan | Depends on | Exit gate |
| --- | --- | --- | --- |
| 2A | `2026-07-18-phase-2a-assets-providers-and-schema.md` | Phase 1 | Exact v1.3 schema, safe Provider/default model, global creative assets, corpus CAS |
| 2B | `2026-07-18-phase-2b-market-and-seeds.md` | 2A | Evidence-backed market snapshots and independent seed-selection module |
| 2C | `2026-07-18-phase-2c-story-engine-and-contract.md` | 2A, 2B | Three engine choices and immutable, fragment-frozen creation contract |
| 2D | `2026-07-18-phase-2d-bible-and-phase-acceptance.md` | 2A–2C | Immutable bible, project readiness, full browser acceptance |

Do not overlap schema or shared route-shell edits across packages. Within one
package, independent backend and frontend tasks may run in parallel only after
their public DTO/route contract is committed.

## Canonical routes after Phase 2

Global:

```text
/projects
/projects/archived
/assets/styles
/assets/experience
/assets/corpus
/settings/providers
/settings/application
```

Project:

```text
/projects/:projectId/overview
/projects/:projectId/seeds
/projects/:projectId/contract
/projects/:projectId/bible
/projects/:projectId/settings/models
/projects/:projectId/write/chapters/:chapterNumber
```

The existing chapter route remains available only for the Phase 1 resumable
session. Phase 2 readiness must not pretend that Phase 4 writer work is done.

## Public API rules

- Provider summary fields are display ID, name, provider type, model name,
  enabled/readiness flags, capabilities, and non-secret notes. `apiKey`,
  `baseURL`, and their snake-case forms are forbidden.
- Provider connection test returns exactly
  `{ok, code, latencyMs, publicMessage}`.
- Market adapters return stored normalized public facts, source URL, capture
  time, content hash, and public availability state. They do not return raw
  HTML, cookies, headers, or adapter exceptions.
- Asset/corpus list APIs return bounded summaries. Corpus detail APIs return
  bounded previews; full text is only read internally for explicit reference
  assembly and backup.
- Mutation APIs require expected revision/hash plus an idempotency key where a
  retry could duplicate a result.
- Public errors use fixed codes/messages and never interpolate request content,
  SQL, Provider output, file paths, or secrets.

## Market-source safety policy

Initial automatic adapters are limited to public, unauthenticated official
ranking pages from Qidian and QQ Reading. Adapters do not bypass login,
CAPTCHA, access controls, or a source policy. If public access/policy cannot be
verified or parsing changes, the adapter fails closed, records a public failure
code, and retains the last successful snapshot. Manual public-snapshot import is
the supported fallback.

Models analyze only persisted snapshots. They may describe current heat,
direction, crowding, opportunities, and uncertainty; they may not claim a
whole-network search or present prediction as fact.

## Test matrix

Every package runs:

```powershell
npm test
npm run test:integration
npm run build
```

The integration command must report equal created/cleaned disposable database
counts and `remaining=0`.

Package-specific browser runners use runner-owned backend/frontend processes,
bounded ports, automatic cleanup, and sentinel scanning. The final Phase 2
runner must cover:

1. create/open a project and restore route context after refresh;
2. browse all 10 styles and 64 experience cards;
3. import, archive, restore, and reference-protect a synthetic corpus;
4. configure fallback and project bindings without seeing any secret;
5. import a public market snapshot and see source time/status;
6. manually create multiple seeds, select one, and switch A→B→A without
   reactivating an old contract;
7. create a manual engine, select styles/cards/corpus fragments, confirm a
   contract, and inspect immutable history;
8. draft/edit/confirm a bible and inspect its immutable history;
9. verify project overview exposes one correct next action at every readiness
   state;
10. verify archived projects are read-only and back/forward/direct URL/narrow
    viewport behavior remains correct.

No fake-adapter unit or browser test may grant real Provider Ready, product DB
Ready, or content-quality acceptance.

## Package completion protocol

For each package:

1. implement each task red/green with focused tests;
2. run the package-focused unit/API/integration/component suite;
3. run an independent spec review;
4. fix every Critical/Important finding;
5. run an independent code-quality review;
6. run the global test/build gates;
7. commit only the package scope;
8. record an acceptance report under `docs/acceptance/`.

After 2D, merge the clean branch into `main` and push only if every gate passes.
Product database rebuild and real Provider calls require a separate Phase 7
execution checkpoint; this roadmap does not authorize either action.
