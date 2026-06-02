import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

const chatStart = source.indexOf('async function chat(')
const retryLoopIndex = source.indexOf('for (let attempt = 1; attempt <= attempts; attempt += 1)', chatStart)
const retryableStatusIndex = source.indexOf('res.status === 429 || res.status >= 500', chatStart)
const fetchFailedIndex = source.indexOf("error.message.includes('fetch failed')", chatStart)
const backoffIndex = source.indexOf('await sleep(1000 * attempt)', chatStart)

assert.ok(chatStart > -1, 'chat function should exist')
assert.ok(retryLoopIndex > chatStart, 'chat should retry model requests')
assert.ok(retryableStatusIndex > retryLoopIndex, 'chat should retry rate-limit and server errors')
assert.ok(fetchFailedIndex > retryLoopIndex, 'chat should retry transient fetch failures')
assert.ok(backoffIndex > fetchFailedIndex, 'chat retry should back off before retrying')

console.log('realistic QA chat retry contract tests passed')
