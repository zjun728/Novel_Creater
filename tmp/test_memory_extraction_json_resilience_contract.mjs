import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const extractionPrompt = readFileSync('frontend/src/prompts/extraction.js', 'utf8')
const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')
const realisticFlow = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(extractionPrompt, /buildExtractionRepairPrompt/, 'memory extraction should expose a JSON repair prompt')
assert.match(extractionPrompt, /buildCompactExtractionPrompt/, 'memory extraction should expose a compact fallback prompt')

assert.match(memoryStore, /buildExtractionRepairPrompt/, 'memory extraction store should import/use the repair prompt')
assert.match(memoryStore, /buildCompactExtractionPrompt/, 'memory extraction store should import/use the compact retry prompt')
assert.match(memoryStore, /parseFactExtractionText/, 'memory extraction should parse and normalize fact payloads through one helper')
assert.match(memoryStore, /repairText/, 'memory extraction should repair malformed fact JSON before failing')
assert.match(memoryStore, /compactText/, 'memory extraction should compact-retry truncated fact JSON before failing')
assert.match(memoryStore, /maxTokens:\s*3000/, 'memory extraction should have enough output budget for fact JSON')

assert.match(realisticFlow, /extractCanonFactsPayload/, 'realistic flow should normalize canon fact extraction payloads')
assert.match(realisticFlow, /紧凑重试/, 'realistic flow should compact-retry fact extraction during longform QA')
assert.match(realisticFlow, /backfillMissingFinalizedPostprocess/, 'realistic flow should backfill missing post-finalization memory before continuing')
assert.match(realisticFlow, /auditChapterPayload/, 'realistic flow should normalize chapter audit payloads')
assert.match(realisticFlow, /审稿紧凑重试/, 'realistic flow should compact-retry chapter audit JSON before stopping')

console.log('memory extraction JSON resilience contract OK')
