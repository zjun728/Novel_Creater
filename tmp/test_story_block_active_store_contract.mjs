import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const store = readFileSync('frontend/src/stores/storyBlockStore.js', 'utf8')

assert.match(store, /function resolveSingleActiveBlock/)
assert.match(store, /const activeBlocks = blocksToCheck\.filter/)
assert.match(store, /activeBlocks\.length > 1[\s\S]*throw new Error/)
assert.match(store, /async function loadBlocks[\s\S]*resolveSingleActiveBlock/)
assert.match(store, /async function loadActiveBlock[\s\S]*loadBlocks\(projectId\)/)
assert.doesNotMatch(store, /blocks\.value\.find\(block => block\.status === 'active'\)/)

console.log('story block active store contract tests passed')
