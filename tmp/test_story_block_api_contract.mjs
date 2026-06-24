import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

const schema = readFileSync('backend/schema.sql', 'utf8')
const apiClient = readFileSync('frontend/src/api/db/client.js', 'utf8')
const main = readFileSync('backend/main.py', 'utf8')
const legacyAdjust = ['adjust', 'current', 'block'].join('_')
const obsoleteStatus = ['super', 'seded'].join('')
const forbiddenRuntimePattern = new RegExp(`${legacyAdjust}|${obsoleteStatus}`)

assert.match(schema, /CREATE TABLE IF NOT EXISTS story_blocks/)
assert.match(schema, /status VARCHAR\(30\) DEFAULT 'active'/)
assert.match(schema, /CHECK \(status IN \('active','completed','paused','closed'\)\)/)
assert.doesNotMatch(schema, new RegExp(obsoleteStatus))

assert.match(schema, /story_block_id CHAR\(36\) DEFAULT NULL/)
assert.match(schema, /block_stage_id VARCHAR\(80\) DEFAULT NULL/)
assert.match(schema, /block_stage_snapshot JSON DEFAULT NULL/)

assert.ok(existsSync('backend/routers/story_blocks.py'), 'story_blocks backend router should exist')
const storyBlocksRouter = readFileSync('backend/routers/story_blocks.py', 'utf8')

assert.match(storyBlocksRouter, /@router\.get\("\/projects\/\{pid\}\/story-blocks"\)/)
assert.match(storyBlocksRouter, /@router\.get\("\/projects\/\{pid\}\/story-blocks\/active"\)/)
assert.match(storyBlocksRouter, /@router\.post\("\/projects\/\{pid\}\/story-blocks"\)/)
assert.match(storyBlocksRouter, /@router\.put\("\/projects\/\{pid\}\/story-blocks\/\{bid\}\/remaining-stages"\)/)
assert.match(storyBlocksRouter, /@router\.post\("\/projects\/\{pid\}\/story-blocks\/\{bid\}\/close"\)/)
assert.match(storyBlocksRouter, /@router\.post\("\/projects\/\{pid\}\/story-blocks\/\{bid\}\/complete"\)/)
assert.match(storyBlocksRouter, /@router\.post\("\/projects\/\{pid\}\/story-blocks\/\{bid\}\/reviews"\)/)
assert.doesNotMatch(storyBlocksRouter, forbiddenRuntimePattern)

assert.match(main, /story_blocks/)
assert.match(apiClient, /storyBlocks:\s*\{/)
assert.match(apiClient, /\/projects\/\$\{projectId\}\/story-blocks\/active/)
assert.match(apiClient, /remaining-stages/)
assert.doesNotMatch(apiClient, forbiddenRuntimePattern)

console.log('story block API contract tests passed')
