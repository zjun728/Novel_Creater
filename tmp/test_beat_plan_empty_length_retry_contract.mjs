import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const aiProxy = readFileSync('backend/routers/ai_proxy.py', 'utf8')

assert.match(
  writerStore,
  /const\s+BEAT_PLAN_INITIAL_MAX_TOKENS\s*=\s*1800/,
  'initial beat plan max tokens should remain explicit'
)
assert.match(
  writerStore,
  /const\s+BEAT_PLAN_EMPTY_LENGTH_RETRY_MAX_TOKENS\s*=\s*(3000|4096)/,
  'empty length retry should raise maxTokens'
)
assert.match(
  writerStore,
  /isEmptyLengthAiResponse\(/,
  'writer store should detect empty content caused by finishReason=length'
)
assert.match(
  writerStore,
  /maxTokens:\s*retryMaxTokens/,
  'retry call should use adaptive retryMaxTokens'
)
assert.match(
  writerStore,
  /thinking:\s*retryThinking/,
  'retry call should pass task-local thinking override'
)
assert.match(
  writerStore,
  /reasoningTokens/,
  'diagnostics should expose reasoningTokens'
)
assert.match(
  writerStore,
  /completionTokens/,
  'diagnostics should expose completionTokens'
)
assert.match(
  writerStore,
  /contentLength/,
  'diagnostics should expose contentLength'
)

assert.match(aiProxy, /reasoningTokens/, 'backend proxy diagnostics should expose reasoningTokens')
assert.match(aiProxy, /completionTokens/, 'backend proxy diagnostics should expose completionTokens')

console.log('beat plan empty length retry contract tests passed')
