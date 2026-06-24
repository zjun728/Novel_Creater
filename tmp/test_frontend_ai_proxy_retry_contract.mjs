import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const aiIndex = readFileSync('frontend/src/api/ai/index.js', 'utf8')

assert.match(
  aiIndex,
  /class AiProxyError extends Error/,
  'frontend AI layer must preserve structured proxy errors'
)
assert.match(
  aiIndex,
  /function isRetryableAiProxyError/,
  'frontend AI layer must identify retryable proxy failures'
)
assert.match(
  aiIndex,
  /MAX_AI_PROXY_RETRIES\s*=\s*[12]/,
  'retryable proxy failures should use only 1-2 retries'
)
assert.match(
  aiIndex,
  /await wait\(resolveAiProxyRetryDelayMs/,
  'retryable proxy failures should back off before retrying'
)
assert.match(
  aiIndex,
  /retriesAttempted/,
  'retry diagnostics must include retriesAttempted'
)
assert.match(
  aiIndex,
  /retrySucceeded/,
  'retry diagnostics must include retrySucceeded'
)
assert.match(
  aiIndex,
  /upstreamStatus/,
  'formatted proxy errors must preserve upstreamStatus'
)

console.log('frontend AI proxy retry contract passed')
