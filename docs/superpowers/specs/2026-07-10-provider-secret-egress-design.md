# Provider Secret Egress Elimination Design

- Date: 2026-07-10
- Status: Approved for specification by the product-control thread
- Baseline: `codex/control-plane-reset@465cd75ad4ca`
- Security decision: no API response may contain a stored plaintext provider API key

## 1. Purpose

Eliminate every committed HTTP response path that can return a stored provider API key while preserving the production backend AI-proxy flow and normal provider configuration updates.

Provider secrets remain valid only in three places:

1. Provider create, update, and import request bodies.
2. The `provider_profiles.api_key` database column.
3. Backend-internal provider resolution used to construct an upstream authorization header.

They must not appear in provider CRUD responses, exports, frontend state populated from those responses, error payloads created by this slice, logs, tests, or diagnostics.

## 2. Confirmed exposure paths

- `GET /api/providers` selects full provider rows and the generic row converter emits `api_key` as `apiKey`.
- `POST /api/providers` returns a full row after insertion.
- `PUT /api/providers/{pid}` returns a full row both for empty updates and successful updates.
- `POST /api/export/full?includeApiKeys=true` returns every stored provider key. This is an independent exposure and remains unsafe even if CRUD responses are fixed.
- `CompareModal` currently interprets a truthy browser-side `provider.apiKey` as evidence that a provider is configured.
- Provider edits currently submit `apiKey` unconditionally, so replacing response secrets with a blank field would silently clear a stored key during an unrelated edit.

There is no separate provider-detail endpoint in the current API.

## 3. Public provider contract

Every provider object returned by list, create, update, or full export:

- omits both `apiKey` and `api_key` entirely;
- includes `hasApiKey: boolean`;
- otherwise preserves the current public provider fields and camel-case conversion;
- never uses a masked or sentinel key value.

`hasApiKey` is derived in SQL with a boolean expression such as `CASE WHEN COALESCE(api_key, '') <> '' THEN 1 ELSE 0 END AS has_api_key`. The response layer receives only that derived boolean, not the credential column. It is metadata, not a credential, and cannot be used as an update value.

Public provider queries use an explicit column projection that does not fetch `api_key`. A shared provider-response boundary also removes `apiKey` and `api_key` defensively before returning a value. Internal AI-proxy queries remain private and may select the key required for the upstream call.

## 4. Write semantics and frontend behavior

Provider create continues to accept `apiKey`.

Provider update keeps the current API semantics:

- omitted `apiKey`: preserve the stored value;
- non-empty string: replace the stored value;
- explicit empty string: clear the stored value.

The settings UI always opens an existing provider with an empty password input. When `hasApiKey` is true, the field explains that a key is already configured and that leaving the input empty preserves it. The frontend update-payload builder includes `apiKey` only when the user enters a non-empty replacement, preventing unrelated edits from clearing a key. An explicit UI action for clearing a key is outside this slice; API clients can still clear it by deliberately sending an empty string.

Multi-model eligibility uses `hasApiKey && model`, not browser possession of a secret. Normal AI requests continue to send only `providerId` through the backend proxy.

The legacy `VITE_AI_DIRECT_PROVIDER=true` path cannot reuse keys stored in the backend after this change. That compatibility is intentionally terminated: a browser must not obtain a stored backend credential merely because direct-provider mode is enabled.

## 5. Export and import

Full export always uses the public provider projection and never includes `apiKey` or `api_key`.

The existing `includeApiKeys` query parameter remains temporarily recognized only to fail closed. If it is true, the endpoint returns a fixed `400 provider_api_key_export_disabled` response without querying provider rows. Omitting it or passing false produces a secret-free export.

Import continues to accept an explicit `apiKey` from a user-supplied or historical backup. `hasApiKey` is response metadata and is discarded before provider insertion so that a newly exported secret-free backup remains importable. Importing such a backup does not restore credentials even when its historical metadata says `hasApiKey: true`; the user must configure a new key afterward. Import errors introduced by this slice use fixed messages and never include provider input values.

## 6. Implementation boundaries

The change is limited to:

- a shared backend public-provider projection/sanitizer;
- provider list/create/update response construction;
- full-export fail-closed behavior and import metadata filtering;
- frontend provider update-payload and configured-provider helpers;
- settings-form messaging and multi-model eligibility;
- deterministic backend and Node contract tests.

It does not change provider table schema, encrypt stored credentials, add authentication, start a service, contact a provider, access a database, refactor startup DDL, or alter the AI-proxy request protocol.

## 7. Error behavior

- `includeApiKeys=true` returns HTTP 400 with the exact FastAPI response shape `{"detail":{"code":"provider_api_key_export_disabled","message":"Provider API key export is disabled."}}`.
- Provider CRUD keeps existing database and validation status behavior, but response construction must not echo a stored key.
- Sanitization is recursive for the provider object boundary used by this slice so neither snake-case nor camel-case key names survive.
- Tests use unmistakable sentinel secrets and assert that neither the field names nor sentinel values occur in serialized responses.

## 8. Testing strategy

Backend deterministic tests use injected fake database functions and call the real route functions. They cover:

- list, create, empty update, and normal update responses;
- `hasApiKey` true and false;
- no `apiKey`, `api_key`, or sentinel secret in serialized output;
- update omission preserves the key, non-empty input replaces it, and explicit empty input clears it;
- default export is secret-free;
- `includeApiKeys=true` fails before provider fetch;
- import ignores `hasApiKey` while still accepting an explicit inbound `apiKey`.

Node tests exercise real pure frontend helpers rather than `tmp/` source regular expressions. They cover:

- an empty edit field omits `apiKey` from the update request;
- a non-empty replacement includes it;
- provider eligibility depends on `hasApiKey` and `model`;
- the client no longer exposes an option to request key-bearing exports.

All tests run through the supported root `npm test` entry point and require no service, database, or provider.

## 9. Acceptance criteria

- No provider CRUD or export response contains `apiKey`, `api_key`, or the stored secret value.
- Every public provider object contains the correct boolean `hasApiKey`.
- `includeApiKeys=true` fails closed before reading provider data.
- Create/update/import still accept intentional inbound credentials.
- Editing non-secret provider fields preserves an existing key.
- Frontend selection uses `hasApiKey`; proxy request payloads continue to use `providerId` only and never carry `hasApiKey` or a credential.
- Deterministic tests prove the response and update contracts without real external state.
- Independent specification and code-quality reviews find no unresolved Critical or Important issue.
