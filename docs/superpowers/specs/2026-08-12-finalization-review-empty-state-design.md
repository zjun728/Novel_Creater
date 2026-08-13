# Finalization Review Empty-State Design

## Context

The Writer loads the finalization review whenever a chapter workspace exists. A
valid workspace may not have a finalization attempt yet. The current backend
represents that normal state as HTTP 404, while the frontend catches the 404 and
treats it as an empty review. Browsers still report the failed fetch, so the
Phase 6A runtime observer correctly fails an otherwise successful scenario.

## Contract

- An existing chapter session with no finalization attempt returns HTTP 200 and
  an explicit closed empty-review projection.
- A missing project, chapter, or chapter session remains HTTP 404.
- Existing non-empty review projections and their conflict/error semantics do
  not change.
- The frontend consumes the empty projection as normal state and keeps the
  primary action at `prepare`; it no longer relies on catching 404 for this
  state.
- The runtime observer remains zero-tolerance. No 4xx or console-error allowlist
  is added.

## Components and Data Flow

The finalization review service first resolves the project/chapter/session
authority. If that authority is absent it raises the existing not-found error.
If the authority exists but no attempt snapshot exists, it returns the same
public review DTO family with an explicit empty-state discriminator and no
attempt payload. The route serializes this as HTTP 200.

The frontend API serializer accepts the closed empty projection. The
finalization controller maps it to its existing initial UI state: no review,
no error, and `prepare` as the primary action. Non-empty projections follow the
existing path unchanged.

## Error Handling

The change does not broaden error handling. Malformed projections remain fixed
client errors; missing session authority remains 404; conflicts and persistence
errors retain their current mappings. Raw exception text, identifiers, URLs,
and payload values are not added to logs or browser evidence.

## Test Strategy

Implementation follows RED-GREEN TDD:

1. Backend service/route tests prove existing-session/no-attempt is 200 empty,
   while missing session remains 404 and a populated review is unchanged.
2. Frontend API/controller tests replace the old 404-as-empty expectation with
   200-empty handling and assert the primary action remains `prepare`.
3. Focused backend and frontend suites run before the Phase 6A runner contracts.
4. One replacement Phase 6A formal run must finish with all runtime counters and
   cleanup ledgers at zero.

## Scope

Only the finalization review service/route DTO boundary, frontend API/controller,
and their focused tests may change. Database schema, fixture authority, runtime
observer tolerance, and unrelated finalization workflows are out of scope.
