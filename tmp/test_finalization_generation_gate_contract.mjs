import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')

const ensureBlock = writerView.match(/async function ensureAiContextReady\([\s\S]*?\n\}/)?.[0] || ''
assert.match(ensureBlock, /findBlockingFinalizationPending/)
assert.match(ensureBlock, /定稿后/)
assert.match(ensureBlock, /未完成|失败/)

const helperBlock = writerView.match(/function findBlockingFinalizationPending\([\s\S]*?\n\}/)?.[0] || ''
assert.match(helperBlock, /writerStore\.chapters/)
assert.match(helperBlock, /chapterNum\.value/)
assert.match(helperBlock, /getChapterFinalizationPending\(projectId\.value/)

const processBlock = memoryStore.match(/async function processChapterFinalization\([\s\S]*?\n  \}/)?.[0] || ''
assert.match(processBlock, /results\.facts/)
assert.match(processBlock, /没有提取到可保存的记忆事实/)
assert.match(processBlock, /recordFinalizationStepError\(results,\s*'facts'/)

console.log('finalization generation gate contract tests passed')
