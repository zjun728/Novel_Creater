# P0 Author Product Interface Contracts

- Design authority: `docs/superpowers/specs/2026-08-30-p0-author-product-design.md`
- Baseline: Writer Core on `main`
- Rule: reads may aggregate existing authorities; writes must call the owning command service.

## Permanent lifecycle rules

| Object | Before confirmation | After confirmation |
| --- | --- | --- |
| Project Seed | revise candidates and select explicitly | selected revision is the project seed authority |
| Creation Contract | draft, generate, compare, clone, confirm once | permanent read-only baseline; clone/save/reconfirm remain rejected |
| Creation Bible | edit, generate, compare, confirm once | permanent read-only baseline; clone/save/reconfirm remain rejected |
| Chapter | one authoritative drafting session | immutable final chapter plus pinned Outline/Planning authority |

No P0 route may weaken these rules.

## Query contracts

| Plan | Method and path | Class | Reads | Must not do |
| --- | --- | --- | --- | --- |
| B | `GET /api/projects/{project_id}/overview` | Q | project, seed/contract/Bible/Planning heads, Writer state, Canon/Projection heads, final-chapter aggregates, ContinuityIssue count | infer heads in the frontend or write status |
| F | `GET /api/projects/{project_id}/workbench/bootstrap?chapter={n}` | Q | server authority, requested chapter, current session or final chapter ref, pinned/current outline ref, Canon/Projection heads | create a ChapterSession or classify from 404/null in the frontend |
| F | `GET /api/projects/{project_id}/workbench/volumes` | Q | pinned final authorities plus the current confirmed Outline when present | return prose or full Planning/Outline JSON |
| F | `GET /api/projects/{project_id}/workbench/volumes/{volume_id}/chapters?cursor={opaque}&limit={1..100}` | Q | one stable volume and its bounded chapter index | scan or return the whole manuscript |
| E | `GET /api/projects/{project_id}/continuity/entities/{entity_id}` | Q | Bible/Planning future design and explicitly referenced Canon/Projection state | join identities by name or save a second fact copy |
| F | `GET /api/projects/{project_id}/workbench/chapters/{chapter_number}/audit` | Q | existing Finalization, ChangeSet, Canon events, Projection evidence, and pinned authority | create an audit fact or mutate history |

Historical volume membership comes only from the Planning/Outline pinned at finalization. A current chapter without a confirmed Outline is returned as unassigned with a stable blocked reason; the frontend never guesses a volume.

## New bounded-context commands

| Plan | Method and path | Class | Transaction boundary |
| --- | --- | --- | --- |
| C | `POST /api/topic-discussions` | N | create one global discussion; no project is required |
| C | `POST /api/topic-discussions/{discussion_id}/messages` | N | append one user message and one recorded model operation/result |
| C | `POST /api/topic-discussions/{discussion_id}/directions` | N | save an immutable direction version from an explicit message/evidence set |
| C | `POST /api/topic-discussions/{discussion_id}/candidates` | N | save an immutable global candidate version from explicit discussion state |
| C | `POST /api/topic-candidates/{candidate_id}/versions/{version}/projects` | N | atomically create the project, copy into existing project Seed revision/head, record provenance/idempotency, leave Seed unconfirmed |
| E | `POST /api/projects/{project_id}/continuity/issues` | N | create a process-debt record referencing existing chapter/Finalization/Canon identities |
| E | `PUT /api/projects/{project_id}/continuity/issues/{issue_id}/status` | N | change only `pending`, `resolved`, or `dismissed` status |

The topic-to-project command uses an idempotency key and returns the same project ID and project Seed revision on replay. It never creates a second project-seed snapshot authority and never auto-confirms the Seed.

## Existing write authorities retained

- Seed confirmation continues through the current project Seed selection service.
- Contract and Bible writes continue through their current pre-confirmation services.
- ChapterSession creation remains an explicit command after confirmed current Outline and synchronized Canon/Projection checks.
- WorkingDraft, draft operations, Candidate, FinalizationChangeSet, and atomic finalization keep their current routes and services.
- Canon/Projection routes remain read-only; finalization is the only P0 path that commits chapter facts and projection changes.
- A FinalizationChangeSet may apply the existing allow-listed future Planning patch inside the atomic transaction; it may not mark planned content as an occurred fact.

## Route cutover rule

After Plan F, `/projects/:projectId/workbench` and `/projects/:projectId/workbench/chapters/:chapterNumber` are the only mounted writing/reading components. Old write and manuscript URLs may be pure redirects only. They may not mount old views, load old stores, or call old APIs.
