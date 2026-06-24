import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const legacyAdjust = ['adjust', 'current', 'block'].join('_')
const obsoleteStatus = ['super', 'seded'].join('')
const legacyChineseAdjust = ['调整', '当前', '块'].join('')
const forbiddenRuntimePattern = new RegExp(`${legacyChineseAdjust}|${legacyAdjust}|${obsoleteStatus}`)

assert.ok(existsSync('frontend/src/components/writer/StoryBlockPanel.vue'), 'StoryBlockPanel should exist')
const storyBlockPanel = readFileSync('frontend/src/components/writer/StoryBlockPanel.vue', 'utf8')

assert.match(writerView, /StoryBlockPanel/)
assert.match(writerView, /showBeatPlanModal/)
assert.match(writerView, /handleAuditModalVisibleChange/)
assert.match(writerView, /ensureStoryBlockReady/)
assert.match(writerView, /当前故事块：/)
assert.match(writerView, /当前阶段来源：/)
assert.match(writerView, /block_stage_snapshot/)
assert.doesNotMatch(writerView, forbiddenRuntimePattern)

assert.match(storyBlockPanel, /当前故事块快捷操作/)
assert.match(storyBlockPanel, /更新后续阶段/)
assert.match(storyBlockPanel, /拆分未定稿内容/)
assert.match(storyBlockPanel, /提前结束当前块/)
assert.match(storyBlockPanel, /开启新故事块/)
assert.match(storyBlockPanel, /锁定信息/)
assert.match(storyBlockPanel, /滚动信息/)
assert.doesNotMatch(storyBlockPanel, forbiddenRuntimePattern)

console.log('story block writer UI contract tests passed')
