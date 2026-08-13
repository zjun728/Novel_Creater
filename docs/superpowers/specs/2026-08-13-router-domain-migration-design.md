# Router Domain Migration Design

## Status

Approved design for moving the complete FastAPI router surface from `backend.routers` to
`backend.domain.routers` without changing product behavior.

## Goal

Make `backend.domain.routers` the single module owner for every product router. Remove the retired
`backend.routers` package and update every production, test, fixture, and browser-runner Python import
in one atomic migration.

## Accepted boundary

This is a module-ownership refactor only. It must not change:

- HTTP paths, methods, request or response DTOs, status codes, headers, or error mappings;
- dependency-injection seams or service/repository construction;
- application lifespan ordering or cleanup behavior;
- schema, persisted data, UI behavior, Provider behavior, or network boundaries;
- browser acceptance scenarios or their resource ledgers.

## Architecture

All 22 router modules move to one closed package:

```text
backend/domain/routers/
  application_settings.py
  assets.py
  bibles.py
  canon.py
  chapter_outlines.py
  chapter_sessions.py
  contracts.py
  corpus.py
  finalization.py
  helpers.py
  market_sources.py
  model_bindings.py
  novel_downloads.py
  planning.py
  project_imports.py
  project_packages.py
  projects.py
  providers.py
  seeds.py
  story_engines.py
  style_trials.py
  __init__.py
```

`backend/main.py` imports routers only from `backend.domain.routers`. Production scripts, API/unit/
integration tests, and embedded Python in browser runners use the same canonical package.

No compatibility proxy remains at `backend.routers`. A proxy would create two import identities for
stateful module-level services and gateways, making dependency overrides, monkeypatches, registries,
and lifecycle ownership ambiguous. Unknown external users of the old internal Python path fail
explicitly instead of silently executing a duplicate module instance.

## Migration mechanics

- The 18 already staged pure moves retain the exact merged-main contents. The two files changed on
  main after the original move (`chapter_sessions.py` and `planning.py`) use the merged-main versions
  at their new paths.
- The four newer routers (`finalization.py`, `novel_downloads.py`, `project_imports.py`, and
  `project_packages.py`) move into the same package.
- Every `backend.routers` import is changed mechanically to `backend.domain.routers`; no import is
  redirected through an alias.
- Relative behavior inside router modules remains unchanged. Imports of domain, repository, service,
  runtime, security, and database owners continue to use their existing canonical modules.

## Failure handling

The migration is fail closed:

- a static contract rejects any tracked Python/JavaScript source that embeds a Python import from
  `backend.routers`;
- the contract rejects any remaining Python module in `backend/routers`;
- application import and route inventory tests must load the canonical package successfully;
- duplicate route registration, missing route registration, and changed public error behavior remain
  covered by the existing API and route-inventory tests.

No runtime fallback catches import failures or retries against the old namespace.

## Test strategy

Implementation follows RED/GREEN:

1. Add a source-boundary test that initially fails because `backend/main.py`, tests, scripts, and four
   router files still use or occupy `backend.routers`.
2. Move the four remaining router modules and update all imports.
3. Run the source-boundary test GREEN.
4. Run API route inventory and all router-focused API tests.
5. Run affected unit/integration collection, Python compilation, `npm test`, and frontend build.
6. Run browser gates only if source or application wiring changes make their accepted runtime path
   materially relevant; otherwise preserve the latest Phase 6A/6B/6C acceptance evidence and record
   the exact verification boundary.

## Acceptance criteria

- `backend/routers` no longer exists.
- `backend/domain/routers` contains the exact 22 Python files: 21 router/helper modules plus
  `__init__.py`.
- Repository source contains zero `backend.routers` Python-import references.
- `backend.main` imports and registers the full route inventory once.
- Focused API/unit tests, full unit suite, build, compilation, and diff checks pass.
- Worktree contains only the intended router migration and its tests/docs before commit.
- The migration is committed independently on `codex/router-domain-migration`; it is not pushed or
  merged without explicit user direction.
