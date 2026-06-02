import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const prompt = readFileSync('frontend/src/prompts/outline.js', 'utf8')

assert.match(prompt, /进度锁/)
assert.match(prompt, /currentChapterNum/)
assert.match(prompt, /不得回退到已写章节之前/)
assert.match(prompt, /不能重新规划已经发生过的“首次”事件/)
assert.match(prompt, /nearChapters 的 chapterNum 必须从当前待写章节开始递增/)

console.log('rolling planning progress lock contract tests passed')
