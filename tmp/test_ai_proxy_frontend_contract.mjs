import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const aiIndex = readFileSync('frontend/src/api/ai/index.js', 'utf8')
const openaiAdapter = readFileSync('frontend/src/api/ai/openaiCompatibleAdapter.js', 'utf8')
const anthropicAdapter = readFileSync('frontend/src/api/ai/anthropicAdapter.js', 'utf8')
const providerSettings = readFileSync('frontend/src/components/settings/ProviderSettings.vue', 'utf8')

assert.match(aiIndex, /VITE_AI_DIRECT_PROVIDER/, 'AI direct provider mode must be an explicit Vite dev switch')
assert.match(aiIndex, /directProviderEnabled/, 'frontend AI entry should centralize the direct-provider gate')
assert.match(aiIndex, /\/ai\/chat-completions/, 'chatCompletion should call the backend AI proxy by default')
assert.match(aiIndex, /\/ai\/chat-completions\/stream/, 'chatCompletionStream should call the backend AI proxy by default')
assert.match(aiIndex, /后端 AI 代理请求失败/, 'frontend errors should identify backend AI proxy failures')
assert.match(aiIndex, /供应商返回失败/, 'frontend errors should identify upstream provider failures')
assert.match(aiIndex, /providerId/, 'proxy payload should identify the backend provider by providerId')
assert.match(aiIndex, /taskName/, 'proxy payload should preserve taskName diagnostics')
assert.doesNotMatch(aiIndex, /apiKey\s*:/, 'AI proxy payload must not send API keys from the browser')
assert.doesNotMatch(aiIndex, /baseURL\s*:/, 'AI proxy payload must not send provider baseURL from the browser')

assert.match(openaiAdapter, /validateDirectProviderAccess/, 'OpenAI-compatible direct calls must be guarded')
assert.match(anthropicAdapter, /validateDirectProviderAccess/, 'Anthropic direct calls must be guarded')

assert.match(providerSettings, /testConnection\(provider\)/, 'settings page should use the centralized AI testConnection entry')
assert.match(providerSettings, /后端代理/, 'settings page should tell users AI requests go through the backend proxy')
assert.doesNotMatch(providerSettings, /浏览器直连供应商/, 'settings page must not advertise browser direct provider calls')

console.log('AI_PROXY_FRONTEND_CONTRACT_OK')
