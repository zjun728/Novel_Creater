import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

function walk(dir) {
  const entries = []
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name)
    const stat = statSync(full)
    if (stat.isDirectory()) entries.push(...walk(full))
    else if (/\.(js|vue)$/.test(name)) entries.push(full)
  }
  return entries
}

for (const file of walk('frontend/src')) {
  const source = readFileSync(file, 'utf8')
  const normalized = file.replaceAll(path.sep, '/')
  if (normalized === 'frontend/src/api/ai/openaiCompatibleAdapter.js') continue
  if (normalized === 'frontend/src/api/ai/anthropicAdapter.js') continue

  assert.doesNotMatch(
    source,
    /fetch\([^)]*(baseURL|getBaseURL|provider\.baseURL|config\.baseURL)/,
    `${normalized} must not fetch provider baseURL outside guarded direct adapters`
  )
}

const indexSource = readFileSync('frontend/src/api/ai/index.js', 'utf8')
assert.doesNotMatch(
  indexSource,
  /new OpenaiCompatibleAdapter\(providerConfig\)\.chatCompletion|new AnthropicAdapter\(providerConfig\)\.chatCompletion/,
  'normal AI entry must not instantiate direct adapters inline without the direct-provider gate'
)

console.log('AI_PROXY_NO_DIRECT_FETCH_CONTRACT_OK')
