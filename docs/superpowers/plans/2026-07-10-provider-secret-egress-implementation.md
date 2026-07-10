# Provider Secret Egress Elimination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure stored provider API keys are accepted only as inbound credentials and never appear in any provider CRUD or export response.

**Architecture:** Add one backend public-provider boundary that uses a SQL-derived `has_api_key` boolean and a defensive sanitizer, then route provider CRUD and export through it while leaving the internal AI proxy unchanged. Add pure frontend helpers for update payloads, configured-provider eligibility, and secret-free export paths so Node tests exercise behavior directly without browser or source-regex tests.

**Tech Stack:** FastAPI, Pydantic 2, Python `unittest`/`AsyncMock`, Vue 3, Pinia, Node built-in test runner.

---

## File map

- Create `backend/routers/provider_public.py`: explicit public SQL projection and provider response sanitizer.
- Create `backend/tests/control_plane/test_provider_secret_responses.py`: deterministic CRUD/export/import response tests with fake database functions.
- Modify `backend/routers/providers.py`: use the public projection for list/create/update responses.
- Modify `backend/routers/export.py`: disable key-bearing exports, use public providers, and ignore `hasApiKey` during import.
- Create `frontend/src/utils/providerSecurity.js`: pure update, eligibility, and export-path helpers.
- Create `tools/control-plane-qa/tests/provider-security.test.mjs`: real behavior tests for the frontend helpers.
- Modify `frontend/src/stores/providerStore.js`: build update requests without a default blank key.
- Modify `frontend/src/components/settings/ProviderForm.vue`: force an empty edit field and explain preserve-on-blank behavior.
- Modify `frontend/src/components/writer/CompareModal.vue`: use `hasApiKey` eligibility.
- Modify `frontend/src/api/db/client.js`: remove the `includeApiKeys` client option.

### Task 1: Backend public provider response boundary and CRUD

**Files:**
- Create: `backend/routers/provider_public.py`
- Create: `backend/tests/control_plane/test_provider_secret_responses.py`
- Modify: `backend/routers/providers.py:5,78-119`

- [ ] **Step 1: Write failing public-boundary and CRUD response tests**

Create a standard-library `IsolatedAsyncioTestCase`. Add `backend/` to `sys.path` before importing the route modules, patch module-local database functions, and use a sentinel key that must never survive serialization.

```python
SENTINEL = "SECRET_MUST_NEVER_LEAVE_BACKEND"


def provider_row(*, has_key=True):
    return {
        "id": "provider-1",
        "name": "Provider",
        "provider_type": "openai-compatible",
        "base_url": "https://example.invalid/v1",
        "api_key": SENTINEL if has_key else "",
        "model": "model-1",
        "stream": 1,
        "max_context_tokens": 200000,
        "max_output_tokens": 4096,
        "temperature": 0.8,
        "top_p": 0.9,
        "supports_json": 1,
        "supports_streaming": 1,
        "notes": "",
        "thinking": None,
        "created_at": 1,
        "updated_at": 2,
        "has_api_key": 1 if has_key else 0,
    }


def assert_secret_free(testcase, value, *, has_key):
    encoded = json.dumps(value, ensure_ascii=False)
    testcase.assertNotIn("apiKey", value)
    testcase.assertNotIn("api_key", value)
    testcase.assertNotIn(SENTINEL, encoded)
    testcase.assertIs(value["hasApiKey"], has_key)
```

```python
class ProviderSecretCrudTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_returns_has_api_key_without_secret(self):
        fetchall = AsyncMock(return_value=[provider_row(has_key=True)])
        with patch.object(providers, "fetchall", fetchall):
            result = await providers.list_providers()
        assert_secret_free(self, result[0], has_key=True)
        self.assertNotIn("SELECT *", fetchall.await_args.args[0].upper())

    async def test_create_returns_has_api_key_without_secret(self):
        execute = AsyncMock()
        fetchone = AsyncMock(return_value=provider_row(has_key=True))
        request = providers.ProviderCreate(
            name="Provider", apiKey=SENTINEL, model="model-1"
        )
        with patch.object(providers, "execute", execute), patch.object(
            providers, "fetchone", fetchone
        ):
            result = await providers.create_provider(request)
        assert_secret_free(self, result, has_key=True)
        self.assertIn(SENTINEL, execute.await_args.args[1])
        self.assertNotIn("SELECT *", fetchone.await_args.args[0].upper())

    async def test_empty_update_returns_has_api_key_without_secret(self):
        fetchone = AsyncMock(return_value=provider_row(has_key=True))
        execute = AsyncMock()
        with patch.object(providers, "fetchone", fetchone), patch.object(
            providers, "execute", execute
        ):
            result = await providers.update_provider(
                "provider-1", providers.ProviderUpdate()
            )
        assert_secret_free(self, result, has_key=True)
        execute.assert_not_awaited()

    async def test_named_update_returns_has_api_key_without_secret(self):
        fetchone = AsyncMock(return_value=provider_row(has_key=True))
        execute = AsyncMock()
        with patch.object(providers, "fetchone", fetchone), patch.object(
            providers, "execute", execute
        ):
            result = await providers.update_provider(
                "provider-1", providers.ProviderUpdate(name="Renamed")
            )
        assert_secret_free(self, result, has_key=True)

    async def test_update_omits_api_key_when_request_omits_it(self):
        execute = AsyncMock()
        with patch.object(providers, "execute", execute), patch.object(
            providers, "fetchone", AsyncMock(return_value=provider_row(has_key=True))
        ):
            await providers.update_provider(
                "provider-1", providers.ProviderUpdate(name="Renamed")
            )
        sql, args = execute.await_args.args
        self.assertNotIn("api_key=%s", sql)
        self.assertNotIn(SENTINEL, args)

    async def test_update_replaces_non_empty_api_key(self):
        execute = AsyncMock()
        replacement = "REPLACEMENT_KEY"
        with patch.object(providers, "execute", execute), patch.object(
            providers, "fetchone", AsyncMock(return_value=provider_row(has_key=True))
        ):
            await providers.update_provider(
                "provider-1", providers.ProviderUpdate(apiKey=replacement)
            )
        sql, args = execute.await_args.args
        self.assertIn("api_key=%s", sql)
        self.assertIn(replacement, args)

    async def test_update_clears_explicit_empty_api_key(self):
        execute = AsyncMock()
        with patch.object(providers, "execute", execute), patch.object(
            providers, "fetchone", AsyncMock(return_value=provider_row(has_key=False))
        ):
            result = await providers.update_provider(
                "provider-1", providers.ProviderUpdate(apiKey="")
            )
        sql, args = execute.await_args.args
        self.assertIn("api_key=%s", sql)
        self.assertIn("", args)
        assert_secret_free(self, result, has_key=False)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest backend.tests.control_plane.test_provider_secret_responses -v
```

Expected: assertion FAIL because current CRUD responses expose `apiKey` and use `SELECT *`; imports and test setup must succeed.

- [ ] **Step 3: Implement the minimal public-provider boundary**

Create `backend/routers/provider_public.py` with an explicit projection. The expression may inspect the credential only inside MySQL; the result row contains only `has_api_key`.

```python
from .helpers import convert_row

PUBLIC_PROVIDER_COLUMNS = """
id, name, provider_type, base_url, model, stream,
max_context_tokens, max_output_tokens, temperature, top_p,
supports_json, supports_streaming, notes, thinking, created_at, updated_at,
CASE WHEN COALESCE(api_key, '') <> '' THEN 1 ELSE 0 END AS has_api_key
""".strip()


def public_provider_query(suffix: str = "") -> str:
    suffix = suffix.strip()
    return f"SELECT {PUBLIC_PROVIDER_COLUMNS} FROM provider_profiles" + (
        f" {suffix}" if suffix else ""
    )


def to_public_provider(row):
    if not row:
        return None
    safe = dict(row)
    safe.pop("api_key", None)
    safe.pop("apiKey", None)
    result = convert_row(safe)
    result["hasApiKey"] = bool(result.get("hasApiKey", False))
    return result


def to_public_providers(rows):
    return [to_public_provider(row) for row in (rows or [])]
```

Modify `providers.py` to use it:

```python
from .provider_public import public_provider_query, to_public_provider, to_public_providers


async def _fetch_public_provider(pid: str):
    row = await fetchone(public_provider_query("WHERE id=%s"), (pid,))
    return to_public_provider(row)


@router.get("/providers")
async def list_providers():
    rows = await fetchall(public_provider_query("ORDER BY created_at"))
    return to_public_providers(rows)
```

Return `await _fetch_public_provider(pid)` from create, empty update, and successful update. Keep `ProviderCreate`, `ProviderUpdate`, INSERT/UPDATE semantics, default-provider lookup, and AI-proxy internals unchanged.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m unittest backend.tests.control_plane.test_provider_secret_responses -v
```

Expected: CRUD and update-contract tests PASS with no DB connection.

- [ ] **Step 5: Commit the backend CRUD boundary**

```powershell
git add backend/routers/provider_public.py backend/routers/providers.py backend/tests/control_plane/test_provider_secret_responses.py
git commit -m "fix(providers): remove API keys from CRUD responses"
```

### Task 2: Fail-closed export and compatible import

**Files:**
- Modify: `backend/routers/export.py:1-34,72-85`
- Modify: `backend/tests/control_plane/test_provider_secret_responses.py`

- [ ] **Step 1: Add failing export/import tests**

Add tests that call the real async route functions with patched `fetchall` and `_insert`:

```python
async def test_export_is_secret_free_by_default(self):
    async def fake_fetchall(sql, args=None):
        if "provider_profiles" in sql:
            return [provider_row(has_key=True)]
        return []
    with patch.object(export, "fetchall", side_effect=fake_fetchall):
        result = await export.export_full()
    assert_secret_free(self, result["providers"][0], has_key=True)


async def test_include_api_keys_true_fails_before_provider_fetch(self):
    with patch.object(export, "fetchall", new_callable=AsyncMock) as fetchall:
        with self.assertRaises(HTTPException) as caught:
            await export.export_full(includeApiKeys=True)
    self.assertEqual(caught.exception.status_code, 400)
    self.assertEqual(caught.exception.detail, {
        "code": "provider_api_key_export_disabled",
        "message": "Provider API key export is disabled.",
    })
    fetchall.assert_not_awaited()


async def test_import_discards_has_api_key_metadata_but_accepts_inbound_key(self):
    payload = {
        "providers": [{
            "id": "old-provider",
            "name": "Imported",
            "hasApiKey": True,
            "apiKey": "EXPLICIT_INBOUND_KEY",
        }],
        "projects": [],
    }
    with patch.object(export, "_insert", new_callable=AsyncMock) as insert:
        await export.import_full(payload)
    table, provider = insert.await_args.args
    self.assertEqual(table, "provider_profiles")
    self.assertNotIn("hasApiKey", provider)
    self.assertEqual(provider["apiKey"], "EXPLICIT_INBOUND_KEY")
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest backend.tests.control_plane.test_provider_secret_responses -v
```

Expected: FAIL because `includeApiKeys=true` still returns secrets, default export retains an `apiKey` field, and import does not discard `hasApiKey`.

- [ ] **Step 3: Implement fail-closed export and metadata filtering**

Modify `export.py`:

```python
from .provider_public import public_provider_query, to_public_providers


@router.post("/export/full")
async def export_full(projectId: str = "", includeApiKeys: bool = False):
    if includeApiKeys:
        raise HTTPException(
            400,
            detail={
                "code": "provider_api_key_export_disabled",
                "message": "Provider API key export is disabled.",
            },
        )
    providers = to_public_providers(
        await fetchall(public_provider_query("ORDER BY created_at"))
    )
```

Before inserting each imported provider, copy and filter response metadata:

```python
for original_provider in data.get("providers", []):
    provider = dict(original_provider)
    provider.pop("hasApiKey", None)
    provider.pop("has_api_key", None)
    old_provider_id = provider.get("id", "")
    new_provider_id = str(uuid.uuid4())
    if old_provider_id:
        provider_id_map[old_provider_id] = new_provider_id
    provider["id"] = new_provider_id
    provider["apiKey"] = provider.get("apiKey") or ""
    await _insert("provider_profiles", provider)
```

- [ ] **Step 4: Run focused and full Python tests**

Run:

```powershell
python -m unittest backend.tests.control_plane.test_provider_secret_responses -v
npm run test:control-plane:py
```

Expected: all provider tests and the complete deterministic Python suite PASS.

- [ ] **Step 5: Commit export/import protection**

```powershell
git add backend/routers/export.py backend/tests/control_plane/test_provider_secret_responses.py
git commit -m "fix(export): disable provider API key egress"
```

### Task 3: Frontend secret-free compatibility

**Files:**
- Create: `frontend/src/utils/providerSecurity.js`
- Create: `tools/control-plane-qa/tests/provider-security.test.mjs`
- Modify: `frontend/src/stores/providerStore.js:1-3,105-125`
- Modify: `frontend/src/components/settings/ProviderForm.vue:1-64,84-90`
- Modify: `frontend/src/components/writer/CompareModal.vue:1-27`
- Modify: `frontend/src/api/db/client.js:311-317`

- [ ] **Step 1: Write failing real-helper Node tests**

Create `tools/control-plane-qa/tests/provider-security.test.mjs` and import the production helper by file URL.

```javascript
import assert from 'node:assert/strict'
import test from 'node:test'

const production = await import(
  '../../../frontend/src/utils/providerSecurity.js'
).catch(() => Object.freeze({}))

test('omits a blank API key from provider updates', () => {
  assert.equal(typeof production.buildProviderUpdatePayload, 'function')
  const payload = production.buildProviderUpdatePayload({
    id: 'provider-1',
    name: 'Renamed',
    model: 'model-1',
    hasApiKey: true,
    apiKey: ''
  })
  assert.equal(Object.hasOwn(payload, 'apiKey'), false)
})

test('includes an exact non-empty replacement API key', () => {
  assert.equal(typeof production.buildProviderUpdatePayload, 'function')
  const payload = production.buildProviderUpdatePayload({
    name: 'Provider',
    model: 'model-1',
    apiKey: '  exact-key-bytes  '
  })
  assert.equal(payload.apiKey, '  exact-key-bytes  ')
})

test('provider eligibility uses hasApiKey and model', () => {
  assert.equal(typeof production.isProviderConfigured, 'function')
  assert.equal(production.isProviderConfigured({ hasApiKey: true, model: 'm' }), true)
  assert.equal(production.isProviderConfigured({ hasApiKey: false, model: 'm' }), false)
  assert.equal(production.isProviderConfigured({ apiKey: 'legacy-secret', model: 'm' }), false)
})

test('full export path cannot request API keys', () => {
  assert.equal(typeof production.buildSecretFreeExportPath, 'function')
  assert.equal(production.buildSecretFreeExportPath('project 1'), '/export/full?projectId=project+1')
  assert.equal(production.buildSecretFreeExportPath('', true), '/export/full')
})
```

- [ ] **Step 2: Run the focused Node test and verify RED**

Run:

```powershell
node --test tools/control-plane-qa/tests/provider-security.test.mjs
```

Expected: assertion FAIL because the dynamically imported production helper functions are absent; the test process itself must not stop with `ERR_MODULE_NOT_FOUND`.

- [ ] **Step 3: Implement pure frontend helpers**

Create `frontend/src/utils/providerSecurity.js`:

```javascript
const PROVIDER_UPDATE_FIELDS = [
  'name', 'providerType', 'baseURL', 'model', 'stream',
  'maxContextTokens', 'maxOutputTokens', 'temperature', 'topP',
  'supportsJSON', 'supportsStreaming', 'notes', 'thinking'
]

export function buildProviderUpdatePayload(provider = {}) {
  const payload = {}
  for (const field of PROVIDER_UPDATE_FIELDS) {
    if (provider[field] !== undefined) payload[field] = provider[field]
  }
  if (typeof provider.apiKey === 'string' && provider.apiKey.length > 0) {
    payload.apiKey = provider.apiKey
  }
  return payload
}

export function isProviderConfigured(provider) {
  return Boolean(provider?.hasApiKey && provider?.model)
}

export function buildSecretFreeExportPath(projectId = '') {
  const params = new URLSearchParams()
  if (projectId) params.set('projectId', projectId)
  const query = params.toString()
  return `/export/full${query ? `?${query}` : ''}`
}
```

- [ ] **Step 4: Wire the helpers into the product frontend**

In `providerStore.js`, import `buildProviderUpdatePayload` and replace the literal update object:

```javascript
const updated = await api.providers.update(
  provider.id,
  buildProviderUpdatePayload(provider)
)
```

In `CompareModal.vue`, import `isProviderConfigured` and use:

```javascript
const writableProviders = computed(() =>
  providerStore.providers.filter(isProviderConfigured)
)
```

In `ProviderForm.vue`, never hydrate a response key into the field:

```javascript
form.value = val
  ? { ...defaults, ...val, apiKey: '' }
  : { ...defaults }
```

Use a state-aware placeholder:

```vue
:placeholder="initial?.hasApiKey
  ? '已配置；留空则保留现有 API Key'
  : '输入 API Key'"
```

In `client.js`, import `buildSecretFreeExportPath` and replace the export method:

```javascript
exportFull: (projectId = '') => post(buildSecretFreeExportPath(projectId)),
```

- [ ] **Step 5: Run Node tests and frontend build**

Run:

```powershell
npm run test:control-plane:node
npm --prefix frontend run build
```

Expected: all Node tests PASS and the Vue production build exits 0. If frontend dependencies are absent, install only from the committed lockfile with `npm --prefix frontend ci`, rerun the build, and remove no user-owned files.

- [ ] **Step 6: Commit frontend compatibility**

```powershell
git add frontend/src/utils/providerSecurity.js tools/control-plane-qa/tests/provider-security.test.mjs frontend/src/stores/providerStore.js frontend/src/components/settings/ProviderForm.vue frontend/src/components/writer/CompareModal.vue frontend/src/api/db/client.js
git commit -m "fix(frontend): consume secret-free provider metadata"
```

### Task 4: Final verification and review

**Files:**
- Verify all files from Tasks 1-3

- [ ] **Step 1: Run the supported deterministic suite**

```powershell
npm test
```

Expected: Node and Python suites both PASS with zero failures and no provider, service, or database access.

- [ ] **Step 2: Run static secret-surface checks**

```powershell
rg -n "includeApiKeys|provider\.apiKey\s*&&|SELECT \* FROM provider_profiles" backend/routers frontend/src tools/control-plane-qa/tests
git diff --check HEAD~3..HEAD
git status --short
```

Expected:

- `includeApiKeys` remains only in the backend fail-closed request parameter/test/spec, not the frontend client.
- no configured-provider UI check depends on `provider.apiKey`;
- internal `SELECT * FROM provider_profiles` occurrences may remain only in backend-private provider resolution paths such as `ai_proxy.py` and default binding lookup, never public response construction;
- diff check is empty and worktree status is clean.

- [ ] **Step 3: Perform two-stage independent review**

Dispatch a specification reviewer first with the exact design requirements and commit range. Resolve every Critical or Important finding and request re-review. Only after specification approval, dispatch a code-quality reviewer focused on secret handling, update semantics, export fail-closed behavior, test realism, and scope control.

- [ ] **Step 4: Re-run verification after review fixes**

```powershell
npm test
npm --prefix frontend run build
git diff --check
git status --short --branch
```

Expected: all tests and build PASS, no whitespace errors, and no uncommitted files.

- [ ] **Step 5: Report readiness without broadening scope**

Report `Provider Secret Egress Ready` only. Do not infer Live, finalization, replacement, release, or canonical-main readiness. State explicitly that no DB, service, or provider was contacted during deterministic implementation and verification.
