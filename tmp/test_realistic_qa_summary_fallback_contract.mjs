import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const qaScript = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(qaScript, /function buildLocalChapterSummaryFallback\(chapterNum, content\)/)
assert.match(qaScript, /catch \(error\) \{\s*const fallback = buildLocalChapterSummaryFallback\(chapterNum, content\)/)
assert.match(qaScript, /report\.notes\.push\(`第 \$\{chapterNum\} 章摘要生成失败，已启用本地兜底摘要/)
assert.match(qaScript, /timeoutMs: 120000/)

console.log('realistic QA summary fallback contract tests passed')
