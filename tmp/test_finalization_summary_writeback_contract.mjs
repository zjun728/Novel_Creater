import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const apiClient = readFileSync('frontend/src/api/db/client.js', 'utf8')
const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')
const chaptersRouter = readFileSync('backend/routers/chapters.py', 'utf8')

assert.match(apiClient, /updateSummary:\s*\(projectId,\s*chapterId,\s*data\)/)
assert.match(apiClient, /\/chapters\/\$\{chapterId\}\/summary/)

assert.match(chaptersRouter, /class ChapterSummaryUpdate\(BaseModel\):/)
assert.match(chaptersRouter, /@router\.put\("\/projects\/\{pid\}\/chapters\/\{cid\}\/summary"\)/)
assert.match(chaptersRouter, /UPDATE chapters SET summary=%s,\s*updated_at=%s WHERE id=%s/)

const processBlock = memoryStore.match(/async function processChapterFinalization\([\s\S]*?\n  \}/)?.[0] || ''
assert.match(processBlock, /api\.chapters\.updateSummary/)
assert.doesNotMatch(processBlock, /writerStore\.updateChapter\(chapter\)/)

console.log('finalization summary writeback contract tests passed')
