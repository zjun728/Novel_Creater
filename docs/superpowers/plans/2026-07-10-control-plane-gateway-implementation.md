# Control Plane AI Proxy Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Node-compatible QA gateway that can call only the existing loopback FastAPI AI proxy with identifier-only payloads and fake-fetch contract tests.

**Architecture:** A repository-owned ESM module validates a closed request schema, rejects credential/adapter-shaped keys, normalizes a loopback `/api` URL, and performs one non-stream POST through an explicitly injected `fetchImpl`. Root scripts run Node's built-in test runner and Python `unittest`; the default suite never invokes the disposable-DB integration module.

**Tech Stack:** Node.js 24 ESM, `node:test`, `node:assert/strict`, npm scripts, Python 3.12 `unittest` discovery.

---

## File map

- Create `tools/control-plane-qa/ai-proxy-gateway.mjs`: closed-schema validation, loopback URL guard, request/response normalization.
- Create `tools/control-plane-qa/tests/ai-proxy-gateway.test.mjs`: fake-fetch-only gateway contract tests.
- Create `backend/tests/__init__.py`: backend test namespace marker.
- Create `backend/tests/control_plane/__init__.py`: deterministic control-plane test namespace marker.
- Modify `package.json`: supported deterministic and opt-in DB test commands.
- Do not modify `frontend/src/api/ai/index.js`; it is a compatibility reference only.

## Parallel execution ownership

Gateway Tasks 1-3 and the package-script edit in Task 4 may be developed in parallel with Transaction Core Tasks 1-5 because they own different files. During that parallel wave, workers run only their focused test files and do not stage or commit. The product-control thread waits for both workers, then performs complete verification and commits Gateway first, Transaction Core second. Disposable Integration starts only after the Core commit.

### Task 1: Establish red tests for the closed request contract

**Files:**
- Create: `tools/control-plane-qa/tests/ai-proxy-gateway.test.mjs`

- [ ] **Step 1: Write the missing-module and fixed-request test scaffold**

```js
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  AiProxyGatewayError,
  createAiProxyGateway
} from '../ai-proxy-gateway.mjs'

function fakeJsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async text() { return JSON.stringify(body) }
  }
}

function validInput() {
  return {
    backendBaseUrl: 'http://127.0.0.1:8000',
    taskName: 'draft_generation',
    projectId: 'project-1',
    messages: [{ role: 'user', content: 'hello' }],
    options: {}
  }
}

test('builds one fixed identifier-only non-stream request', async () => {
  const calls = []
  const gateway = createAiProxyGateway({
    fetchImpl: async (...args) => {
      calls.push(args)
      return fakeJsonResponse({
        choices: [{ message: { content: 'ok' } }],
        proxyDiagnostics: {}
      })
    }
  })

  const result = await gateway.chatCompletion({
    ...validInput(),
    providerId: 'provider-1',
    options: {
      temperature: 0,
      maxTokens: 512,
      topP: 0.8,
      responseFormat: 'json',
      includeUsage: true
    }
  })

  assert.equal(result.content, 'ok')
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'http://127.0.0.1:8000/api/ai/chat-completions')
  assert.equal(calls[0][1].redirect, 'error')
  assert.deepEqual(JSON.parse(calls[0][1].body), {
    messages: [{ role: 'user', content: 'hello' }],
    stream: false,
    taskName: 'draft_generation',
    projectId: 'project-1',
    providerId: 'provider-1',
    temperature: 0,
    maxTokens: 512,
    top_p: 0.8,
    response_format: { type: 'json_object' },
    includeUsage: true
  })
})
```

- [ ] **Step 2: Run the target file and record the red state**

Run:

```powershell
node --test tools/control-plane-qa/tests/ai-proxy-gateway.test.mjs
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `ai-proxy-gateway.mjs`.

- [ ] **Step 3: Add table-driven invalid-input tests before implementation**

Add cases that call a gateway whose `fetchImpl` invokes `assert.fail('fetch must not be called')`:

```js
const invalidCases = [
  ['missing taskName', input => { delete input.taskName }],
  ['missing project/provider identity', input => { delete input.projectId }],
  ['unknown envelope field', input => { input.model = 'forbidden' }],
  ['unknown option field', input => { input.options.thinking = {} }],
  ['message extra field', input => { input.messages[0].name = 'x' }],
  ['empty messages', input => { input.messages = [] }],
  ['invalid role', input => { input.messages[0].role = 'tool' }],
  ['non-string content', input => { input.messages[0].content = {} }],
  ['temperature too high', input => { input.options.temperature = 2.1 }],
  ['maxTokens not integer', input => { input.options.maxTokens = 1.5 }],
  ['topP zero', input => { input.options.topP = 0 }],
  ['responseFormat unsupported', input => { input.options.responseFormat = 'text' }],
  ['includeUsage not boolean', input => { input.options.includeUsage = 'yes' }]
]

for (const [name, mutate] of invalidCases) {
  test(`rejects ${name} before fetch`, async () => {
    const input = validInput()
    mutate(input)
    const gateway = createAiProxyGateway({
      fetchImpl: async () => assert.fail('fetch must not be called')
    })
    await assert.rejects(
      gateway.chatCompletion(input),
      error => error instanceof AiProxyGatewayError &&
        error.code === 'invalid_gateway_input'
    )
  })
}
```

Also add explicit boundary cases for 200/201 messages, 2 MiB UTF-8 content, 120/121-character IDs/task names, and every numeric endpoint specified by the design.

### Task 2: Implement closed validation, forbidden-key scanning, and URL fencing

**Files:**
- Create: `tools/control-plane-qa/ai-proxy-gateway.mjs`
- Test: `tools/control-plane-qa/tests/ai-proxy-gateway.test.mjs`

- [ ] **Step 1: Define the public error and factory**

```js
const FORBIDDEN_NORMALIZED_KEYS = new Set([
  'apikey', 'baseurl', 'authorization', 'headers',
  'provideradapter', 'applyadapter'
])
const DIAGNOSTIC_KEYS = [
  'requestId', 'taskId', 'taskKey', 'providerId', 'providerName',
  'modelName', 'httpStatus', 'upstreamStatus', 'elapsedMs',
  'retryable', 'retriesAttempted', 'retrySucceeded'
]

export class AiProxyGatewayError extends Error {
  constructor(message, { code, status = 0, diagnostics = {} } = {}) {
    super(message)
    this.name = 'AiProxyGatewayError'
    this.code = code
    this.status = status
    this.diagnostics = diagnostics
  }
}

export function createAiProxyGateway({ fetchImpl, timeoutMs = 20 * 60 * 1000 } = {}) {
  if (typeof fetchImpl !== 'function') {
    throw new AiProxyGatewayError('fetchImpl is required', { code: 'invalid_gateway_input' })
  }
  return {
    chatCompletion: input => chatCompletion({ input, fetchImpl, timeoutMs })
  }
}
```

- [ ] **Step 2: Implement recursive key scanning and exact schemas**

Implement private helpers with these signatures:

```js
function normalizeKey(key) {
  return String(key).toLowerCase().replace(/[_-]/g, '')
}

function scanForbiddenKeys(value, path = '$') {
  if (value === null || typeof value !== 'object') return
  if (Array.isArray(value)) {
    value.forEach((item, index) => scanForbiddenKeys(item, `${path}[${index}]`))
    return
  }
  for (const [key, child] of Object.entries(value)) {
    if (FORBIDDEN_NORMALIZED_KEYS.has(normalizeKey(key))) {
      throw new AiProxyGatewayError('Forbidden gateway configuration key', {
        code: 'forbidden_gateway_key'
      })
    }
    scanForbiddenKeys(child, `${path}.${key}`)
  }
}

function assertExactKeys(value, allowed, path) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new AiProxyGatewayError(`${path} must be an object`, {
      code: 'invalid_gateway_input'
    })
  }
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) {
      throw new AiProxyGatewayError('Unknown gateway input field', {
        code: 'invalid_gateway_input'
      })
    }
  }
}
```

Add `validateMessages(messages)`, `validateOptions(options)`, and `validateGatewayInput(input)` using `assertExactKeys()`. `validateGatewayInput()` must require `taskName`, require `projectId` or `providerId`, reject `model`/`thinking`, and preserve both IDs when both are supplied. `validateMessages()` enforces roles, exact keys, count, and UTF-8 byte total; `validateOptions()` enforces every type/range in the design.

- [ ] **Step 3: Add forbidden-key and URL tests**

```js
for (const key of ['apiKey', 'base_url', 'Authorization', 'headers', 'provider-adapter', 'apply_adapter']) {
  test(`rejects nested forbidden key ${key}`, async () => {
    const gateway = createAiProxyGateway({
      fetchImpl: async () => assert.fail('fetch must not be called')
    })
    await assert.rejects(
      gateway.chatCompletion({
        ...validInput(),
        options: { nested: { [key]: 'secret' } }
      }),
      error => error.code === 'forbidden_gateway_key'
    )
  })
}
```

Add a passing test proving message text containing `apiKey base_url Authorization` is not scanned as an object key. Add rejected URLs for HTTPS, remote hosts, `127.0.0.2`, credentials, query, hash, and paths other than root or `/api[/]`. Add accepted URLs for `localhost`, `127.0.0.1`, and `[::1]`.

- [ ] **Step 4: Implement strict loopback normalization**

```js
function normalizeBackendApiBase(raw) {
  let url
  try { url = new URL(raw) } catch {
    throw new AiProxyGatewayError('Invalid backend URL', {
      code: 'invalid_gateway_input'
    })
  }
  const allowedHosts = new Set(['localhost', '127.0.0.1', '::1'])
  const normalizedHostname = url.hostname === '[::1]' ? '::1' : url.hostname
  if (url.protocol !== 'http:' || url.username || url.password ||
      !allowedHosts.has(normalizedHostname) || url.search || url.hash ||
      !['/', '/api', '/api/'].includes(url.pathname)) {
    throw new AiProxyGatewayError('Backend URL is not allowed', {
      code: 'invalid_gateway_input'
    })
  }
  return `${url.origin}/api`
}
```

- [ ] **Step 5: Implement the identifier-only payload and one fetch**

```js
function buildProxyPayload({ taskName, projectId, providerId, messages, options = {} }) {
  return {
    messages,
    stream: false,
    taskName,
    ...(projectId !== undefined ? { projectId } : {}),
    ...(providerId !== undefined ? { providerId } : {}),
    ...(options.temperature !== undefined ? { temperature: options.temperature } : {}),
    ...(options.maxTokens !== undefined ? { maxTokens: options.maxTokens } : {}),
    ...(options.topP !== undefined ? { top_p: options.topP } : {}),
    ...(options.responseFormat === 'json'
      ? { response_format: { type: 'json_object' } }
      : {}),
    ...(options.includeUsage !== undefined ? { includeUsage: options.includeUsage } : {})
  }
}
```

Use `AbortController`, one `fetchImpl` call, `redirect: 'error'`, and `Content-Type: application/json`. Do not reference `globalThis.fetch`, adapters, provider presets, retries, model, or thinking.

- [ ] **Step 6: Run the focused suite**

Run:

```powershell
node --test tools/control-plane-qa/tests/ai-proxy-gateway.test.mjs
```

Expected: all request/validation/URL tests PASS; 0 failures and no real network access.

### Task 3: Add safe response, error, redirect, and timeout behavior

**Files:**
- Modify: `tools/control-plane-qa/ai-proxy-gateway.mjs`
- Modify: `tools/control-plane-qa/tests/ai-proxy-gateway.test.mjs`

- [ ] **Step 1: Write red tests for diagnostic allowlisting**

Return a fake response containing all allowed diagnostics plus `rawHead`, `rawTail`, `upstreamBodyHead`, `upstreamBodyTail`, `usage`, and an extra field. Assert output keys are exactly the allowed intersection:

```js
assert.deepEqual(result, {
  content: 'generated',
  diagnostics: {
    requestId: 'req-1',
    providerId: 'provider-1',
    elapsedMs: 31,
    retryable: false
  }
})
```

- [ ] **Step 2: Write red tests for safe HTTP errors and no retry**

Use a 502 fake response whose detail contains `requestId`, `upstreamStatus`, `retryable`, `rawHead: 'SECRET'`, and `upstreamBodyHead: 'PROMPT'`. Assert one fetch call, fixed safe error text, status 502, allowlisted diagnostics, and absence of `SECRET`/`PROMPT` from the error and serialized diagnostics.

- [ ] **Step 3: Write red tests for redirect and abort**

Use a fake 302 response and expect `code === 'ai_proxy_redirect_rejected'`. For timeout, use a fake fetch that waits for `signal.abort` and rejects with an `AbortError`; construct with a small `timeoutMs` and expect `ai_proxy_timeout`, retryable diagnostics, and exactly one call.

- [ ] **Step 4: Implement response parsing and allowlisting**

```js
function pickDiagnostics(value) {
  const output = {}
  if (!value || typeof value !== 'object') return output
  for (const key of DIAGNOSTIC_KEYS) {
    if (value[key] !== undefined) output[key] = value[key]
  }
  return output
}
```

Parse JSON from `response.text()`. On success, read content only from `choices[0].message.content`. On errors, inspect only `parsed.detail` through `pickDiagnostics()` and use fixed gateway-authored messages. Reject 3xx even if a fake fetch returns one. Always clear the timeout.

- [ ] **Step 5: Run the complete gateway test file**

Run:

```powershell
node --test tools/control-plane-qa/tests/ai-proxy-gateway.test.mjs
```

Expected: all subtests PASS, 0 fail, every fake reports exactly one or zero calls as asserted.

### Task 4: Wire supported root test scripts and commit the Gateway slice

**Files:**
- Modify: `package.json`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/control_plane/__init__.py`

- [ ] **Step 1: Add exact npm scripts**

```json
"scripts": {
  "test": "npm run test:control-plane",
  "test:control-plane": "npm run test:control-plane:node && npm run test:control-plane:py",
  "test:control-plane:node": "node --test \"tools/control-plane-qa/tests/*.test.mjs\"",
  "test:control-plane:py": "python -m unittest discover -s backend/tests/control_plane -p \"test_*.py\"",
  "test:control-plane:db": "python -m unittest discover -s backend/tests/control_plane -p \"mysql_integration_test.py\""
}
```

Do not change dependencies or create a lockfile.

- [ ] **Step 2: Add Python namespace markers**

```python
"""Backend tests."""
```

```python
"""Deterministic control-plane tests."""
```

- [ ] **Step 3: Run supported deterministic commands**

Run:

```powershell
npm run test:control-plane:node
npm run test:control-plane:py
npm test
```

Expected: gateway tests PASS; Python reports `Ran 0 tests ... OK` until the transaction plan lands; `npm test` does not run DB integration or scan `tmp/`.

- [ ] **Step 4: Audit scope and forbidden imports**

Run:

```powershell
git diff --check
rg -n "AnthropicAdapter|OpenaiCompatibleAdapter|globalThis\.fetch|apiKey|baseURL|providerAdapter|applyAdapter|tmp/" tools/control-plane-qa package.json
git status --short
```

Expected: no whitespace errors; no adapter/global fetch/tmp imports. Forbidden strings occur only inside rejection tests or deny-list constants and are reviewed in context.

- [ ] **Step 5: Commit the isolated slice**

```powershell
git add package.json `
  tools/control-plane-qa/ai-proxy-gateway.mjs `
  tools/control-plane-qa/tests/ai-proxy-gateway.test.mjs `
  backend/tests/__init__.py `
  backend/tests/control_plane/__init__.py
git commit -m "feat: add control-plane AI proxy gateway"
```

Expected: one commit containing only the approved Gateway files. This commit can claim `Gateway Contract Ready` only; it cannot claim AI Proxy, DB, or Live Ready.
