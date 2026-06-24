import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writer = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const panel = readFileSync('frontend/src/components/writer/StoryBlockPanel.vue', 'utf8')

assert.match(writer, /storyBlockPlanningBusy/)
assert.match(writer, /storyBlockStore\.loading\s*\|\|\s*storyBlockStore\.aiPlanning/)
assert.match(writer, /:loading="storyBlockPlanningBusy"/)
assert.match(panel, /正在生成故事块规划，请稍候/)
assert.match(panel, /:disabled="disabled \|\| loading/)

assert.match(writer, /canCreateNextChapter/)
assert.match(writer, /newChapterDisabledReason/)
assert.match(writer, /上一章未定稿，不能新建下一章/)
assert.match(writer, /:disabled="!canCreateNextChapter"/)
assert.match(writer, /:title="newChapterDisabledReason"/)

console.log('story block loading and new chapter contract tests passed')
