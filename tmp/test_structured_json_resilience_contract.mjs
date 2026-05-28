import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = path => readFileSync(resolve(root, path), 'utf8')

const seedPrompt = read('frontend/src/prompts/seed.js')
const seedStore = read('frontend/src/stores/seedStore.js')
const marketStore = read('frontend/src/stores/marketStore.js')
const globalAuditPrompt = read('frontend/src/prompts/globalAudit.js')
const novelStore = read('frontend/src/stores/novelStore.js')

assert.match(seedPrompt, /buildCompactSeedRetryPrompt/, 'seed prompt should expose a compact seed retry prompt for truncated JSON')
assert.match(seedStore, /buildCompactSeedRetryPrompt/, 'seed generation should import/use the compact seed retry prompt')
assert.match(seedStore, /maxTokens:\s*6000/, 'seed generation should allow enough tokens for complete seed JSON')
assert.match(seedStore, /compactText/, 'seed generation should run a compact retry before failing')

assert.match(marketStore, /buildCompactSeedRetryPrompt/, 'market advisor should use compact seed retry for seed intents')
assert.match(marketStore, /maxTokens:\s*6000/, 'market advisor seed JSON flow should allow enough tokens')
assert.match(marketStore, /compactText/, 'market advisor should retry compact seed JSON before reporting no seed')

assert.match(globalAuditPrompt, /buildGlobalAuditRepairPrompt/, 'global audit prompt should expose JSON repair prompt')
assert.match(globalAuditPrompt, /buildCompactGlobalAuditPrompt/, 'global audit prompt should expose compact retry prompt')
assert.match(novelStore, /buildGlobalAuditRepairPrompt/, 'global audit should repair malformed JSON before failing')
assert.match(novelStore, /buildCompactGlobalAuditPrompt/, 'global audit should compact-retry truncated JSON before failing')
assert.match(novelStore, /globalAuditText/, 'global audit should preserve the best raw text for useful error snippets')

console.log('structured JSON resilience contract OK')
