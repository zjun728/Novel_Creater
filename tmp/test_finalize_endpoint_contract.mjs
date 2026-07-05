import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const apiClient = readFileSync('frontend/src/api/db/client.js', 'utf8')
const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const chaptersRouter = readFileSync('backend/routers/chapters.py', 'utf8')

assert.match(apiClient, /finalize:\s*\(projectId,\s*chapterId,\s*versionId,\s*data\s*=\s*\{\}\)/)
assert.match(apiClient, /\/versions\/\$\{versionId\}\/finalize/)
assert.match(chaptersRouter, /@router\.post\("\/projects\/\{pid\}\/chapters\/\{cid\}\/versions\/\{vid\}\/finalize"\)/)
assert.match(chaptersRouter, /UPDATE chapters SET final_version_id=%s,\s*status='final'/)

const finalizeBlock = writerStore.match(/async function finalizeVersion\(version(?:,\s*options\s*=\s*\{\})?\) \{[\s\S]*?\n  \}/)?.[0] || ''
assert.match(finalizeBlock, /api\.versions\.finalize/)
assert.doesNotMatch(finalizeBlock, /await updateChapter\(chapter\)/)

console.log('finalize endpoint contract tests passed')
