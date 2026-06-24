import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const router = readFileSync('backend/routers/ai_proxy.py', 'utf8')
const main = readFileSync('backend/main.py', 'utf8')

assert.match(router, /@router\.post\("\/ai\/chat-completions"\)/, 'backend must expose non-stream AI proxy endpoint')
assert.match(router, /@router\.post\("\/ai\/chat-completions\/stream"\)/, 'backend must expose stream AI proxy endpoint')
assert.match(main, /ai_proxy/, 'main.py must register the AI proxy router')

assert.match(router, /provider_profiles/, 'AI proxy must read existing provider configuration from backend storage')
assert.match(router, /task_model_bindings/, 'AI proxy must support project task model mapping resolution')
assert.match(router, /Authorization.*Bearer/, 'OpenAI-compatible proxy must add Authorization on the server side')
assert.match(router, /api_key/, 'OpenAI-compatible proxy must use backend api_key field')
assert.doesNotMatch(router, /payload\.get\(["']apiKey["']\)|payload\.get\(["']api_key["']\)/, 'AI proxy must not accept API keys from browser payload')

for (const field of ['providerId', 'providerName', 'modelName', 'taskName', 'httpStatus', 'elapsedMs', 'rawHead', 'rawTail']) {
  assert.match(router, new RegExp(field), `safe diagnostic response should include ${field}`)
}
assert.match(router, /redact_sensitive_text/, 'AI proxy diagnostics must redact secrets')
assert.match(router, /anthropic/i, 'Anthropic providers should return a clear unsupported error or be explicitly handled')

console.log('AI_PROXY_BACKEND_CONTRACT_OK')
