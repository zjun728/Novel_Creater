import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const qaScript = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(writerStore, /chatCompletionStream\(provider, messages, \{ maxTokens: 8192, temperature: 0\.8 \}\)/)
assert.match(writerStore, /chatCompletion\(provider, messages, \{ maxTokens: 8192, temperature: 0\.8 \}\)/)
assert.match(qaScript, /\{ maxTokens: 8192, temperature: 0\.72, timeoutMs: 360000 \}/)

console.log('chapter generation token guard tests passed')
