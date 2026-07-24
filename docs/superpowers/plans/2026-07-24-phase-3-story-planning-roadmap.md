# Phase 3 Story Planning Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development` to execute one delivery package at a time. Every
> implementation task uses test-driven development, then receives a spec review
> and a code-quality review before the next task starts.

**Goal:** Deliver the complete author-controlled story-planning path from a
confirmed creation bible through revisioned volumes, plots, story blocks, and a
confirmed next-chapter outline.

**Architecture:** One project-level Planning aggregate owns future design
through one draft and one immutable head. StoryBlock `volumeId/plotIds` are the
only relationship authority. Chapter outlines are separate immutable revisions
that pin one Planning revision and the exact stable planning nodes they use.
Canon remains the only authority for events that have actually happened.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, aiomysql, MySQL 8, pytest,
Vue 3, Pinia 3, Vue Router 4, Naive UI, Node test runner, Playwright.

---

## Authority and baseline

- Product authority:
  `docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`
- Phase 3 design:
  `docs/superpowers/specs/2026-07-24-phase-3-story-planning-design.md`
- Baseline:
  `main@f11faad531f04250f2a987390a468dfd14bf06a3`
- Delivery branch:
  `codex/phase3-story-planning`
- Worktree:
  `C:\Users\zhangjun\.codex\worktrees\phase3-story-planning\Novel_Creater`

The design commit is `4082267`. Do not copy untracked files from another
worktree and do not edit the old `dd1a`, Phase 2, M4, or M5 worktrees.

## Delivery constraints

- No compatibility migration, alias, fallback query, or dual Planning runtime.
- The empty-schema target is exactly `writer-core-v1.5.0`.
- Phase 3 development and automated acceptance use only disposable databases
  named `novel_creator_test_<32 lowercase hex>`.
- Do not read or write the product database.
- Do not call a real Provider/model. Strict fakes may replace only the external
  AI gateway boundary in packages 3B–3D.
- No API response, error, log, report, screenshot, artifact, or diagnostic may
  contain an API key, Authorization value, password, DSN, prompt, raw Provider
  output, or corpus text.
- Planning stores future design only. It has no `completed` planning state and
  no mutation that marks a Stage or SceneTask as actually completed.
- Phase 3 has no Canon write API. `actualProgress` is a read-only projection
  and may truthfully be empty until Phase 5.
- Manual Planning and Outline work remains available when the `planning` model
  is not ready.
- A Planning or Outline AI result enters only an editable draft. It never
  confirms a revision, creates a ChapterSession, or writes Canon.
- Do not expose Phase 4–6 dead navigation.
- Shared schema, MySQL, build, and final browser gates run serially.

## Frozen aggregate chain

```text
project
  -> activeSeedSelectionRevision
  -> confirmed creation contract revision/hash
  -> confirmed creation bible revision/hash
  -> projectPlanningHead revision/id/hash
  -> immutable Planning aggregate
      -> Volume
      -> Plot
      -> StoryBlock.volumeId/plotIds
          -> Stage
              -> SceneTask
  -> projectChapterOutlineHead(chapterNumber) revision/id/hash
  -> immutable ChapterOutline
  -> later ChapterSession
```

All stable planning node IDs are allocated by the backend and are never reused
within project history. Local node revision increases exactly when normalized
content, order, parent, or `active -> retired` changes. A retired confirmed ID
cannot be reactivated.

## Package sequence

| Package | Plan | Depends on | Exit gate |
| --- | --- | --- | --- |
| 3A | `2026-07-24-phase-3a-planning-aggregate-foundation.md` | Phase 2 | v1.5 schema, Planning aggregate draft/confirm/history, old initial-plan chain removed, chapter creation closed without confirmed outline |
| 3B | `2026-07-24-phase-3b-volumes-and-plots.md` | 3A | Manual/AI Planning draft, Volume and Plot routes, project next action and archived/superseded history |
| 3C | `2026-07-24-phase-3c-story-blocks-and-outlines.md` | 3A–3B | StoryBlock/Stage/SceneTask editor, Outline draft/confirm/history, ChapterSession exact pin and authoritative chapter entry |
| 3D | `2026-07-24-phase-3d-boundary-and-acceptance.md` | 3A–3C | Future/actual read model, full UI-only browser acceptance and Phase 3 report |

Do not start package 3B until 3A is committed and its package gates are green.
Do not overlap schema edits between packages.

## Package 3A boundary

3A creates the final v1.5 table shape once. It:

- replaces the four old mutable planning tables with Planning aggregate and
  ChapterOutline draft/revision/head/request tables;
- creates Planning head revision 0 in the project-creation transaction;
- replaces deterministic `create_initial_plan` with manual Planning draft,
  save, confirm, history, and read-state services;
- removes `POST /planning/initial`;
- rewrites the single `planningStore` public contract;
- rewrites `PlanningWorkspace.vue` in place so no old initial-plan action
  remains;
- changes ChapterSession persistence to the final Planning/Outline pins;
- rejects ChapterSession creation while there is no current confirmed Outline;
- updates explicit reset/verifier inventories without adding migration support.

3A does not generate Planning with AI, expose the three planning pages, or let
the user confirm an Outline. Those become product UI in 3B/3C.

## Package 3B boundary

3B adds:

- `/projects/:projectId/planning/volumes`;
- `/projects/:projectId/planning/plots`;
- the shared Planning workspace and unsaved-change protection;
- explicit AI Planning operation with one active lease, idempotency,
  fingerprint, fencing, and status reconciliation;
- project navigation and the full service-authoritative next-action insertion;
- archived and superseded read-only Planning history.

Volume does not store Plot or StoryBlock IDs. Plot does not store StoryBlock
IDs. Those views derive only from `StoryBlock.volumeId/plotIds`.

## Package 3C boundary

3C adds:

- `/projects/:projectId/planning/story-blocks`;
- StoryBlock, Stage, and SceneTask editing without chapter-count rules;
- manual and AI ChapterOutline drafts;
- immutable Outline confirmation/history;
- current-Planning and current-Canon/Projection fences;
- server-authoritative chapter number;
- ChapterSession creation pinned to the exact Planning, StoryBlock, and Outline
  revisions/hashes.

An Outline confirmed against an older Planning head is superseded if no Session
uses it. Existing Sessions, drafts, and candidates continue to pin their old
revisions.

## Package 3D boundary

3D composes:

```text
futurePlan + actualProgress + canonProjectionStatus
```

The composition is read-only. No Phase 3 endpoint marks progress complete.
The package closes browser, secret-scan, cleanup, and documentation evidence.

## Canonical routes after Phase 3

The following Phase 3 routes become reachable:

```text
/projects/:projectId/planning/volumes
/projects/:projectId/planning/plots
/projects/:projectId/planning/story-blocks
```

The existing chapter route remains canonical:

```text
/projects/:projectId/write/chapters/:chapterNumber
```

It may create a Session only when the URL chapter number equals the
server-authoritative chapter number and a current confirmed Outline exists.

Canon/state detail routes remain hidden until they have a complete product
surface. Phase 3 does not add empty navigation cards for them.

## Test matrix

Every package runs focused tests first, then:

```powershell
npm test
npm run test:integration
npm run build
git diff --check
```

Integration output must show equal created/cleaned disposable-database counts
and `remaining=0`.

3B and 3C add focused browser regression runners. 3D adds one formal Phase 3
UI-only runner that covers:

1. finish the existing Phase 2 preparation path;
2. create a manual Planning draft without a ready model;
3. add Volumes and Plots and confirm revision 1;
4. adjust future design into revision 2 without overwriting revision 1;
5. add a StoryBlock with Stages and SceneTasks and no chapter count;
6. create and confirm the next-chapter Outline;
7. prove Session creation is rejected before Outline confirmation and succeeds
   only after exact confirmation;
8. prove a Planning head change supersedes an unused old Outline;
9. prove an existing Session remains pinned to its historical revisions;
10. prove A→B→A selection never reactivates old Planning/Outline;
11. prove archived routes are read-only and back/forward/refresh restore state;
12. prove `actualProgress` is empty rather than fabricated when Canon is 0;
13. prove every captured response/log/artifact is secret-safe;
14. prove owned databases, processes, ports, and temp roots have zero residue.

The browser must not use `page.request`, `page.route`, `page.evaluate`, `fetch`,
Axios, or another API bypass to perform product actions.

## Package completion protocol

For each package:

1. one implementer executes one task with RED → GREEN → self-review;
2. an independent spec reviewer reports Critical/Important/Minor findings;
3. the same implementer fixes findings;
4. after spec 0/0/0, an independent quality reviewer runs;
5. the same implementer fixes quality findings;
6. the primary controller reads the diff and fresh command output;
7. focused tests and package gates run serially;
8. the package is committed with a narrow message;
9. its acceptance evidence is recorded without unverified claims.

After 3D, run the full Phase 3 gates from a clean worktree, merge safely into
`main`, and push without force only if every gate passes. Real Provider and
product-database execution remain Phase 7 checkpoints.
