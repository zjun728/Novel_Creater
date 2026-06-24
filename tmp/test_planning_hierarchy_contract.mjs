import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const rollingPanel = readFileSync('frontend/src/components/chapter/RollingPlanningPanel.vue', 'utf8')
const outlinePrompt = readFileSync('frontend/src/prompts/outline.js', 'utf8')
const chapterPlanPrompt = readFileSync('frontend/src/prompts/chapterPlanPrompt.js', 'utf8')
const chapterDraftPrompt = readFileSync('frontend/src/prompts/chapterDraftPrompt.js', 'utf8')
const legacyChapterPrompt = readFileSync('frontend/src/prompts/chapter.js', 'utf8')
const contextBuilder = readFileSync('frontend/src/utils/contextBuilder.js', 'utf8')
const projectView = readFileSync('frontend/src/views/ProjectView.vue', 'utf8')

const productionText = [
  rollingPanel,
  outlinePrompt,
  chapterPlanPrompt,
  chapterDraftPrompt,
  legacyChapterPrompt,
  contextBuilder,
  projectView
].join('\n')

for (const phrase of [
  '未来 3-5 章近景规划',
  '未来 3-5 章规划',
  '先按分卷建立粗结构',
  '近景滚动规划进入章节上下文',
  '进入章节生成上下文',
  '分卷后直接生成未来章节规划'
]) {
  assert.doesNotMatch(productionText, new RegExp(phrase), `legacy planning phrase should be removed: ${phrase}`)
}

assert.match(rollingPanel, /先建立分卷规划，再创建当前卷故事块/)
assert.match(rollingPanel, /当前章小纲从故事块阶段生成/)
assert.match(rollingPanel, /长线蓝图只保留卷级方向/)
assert.match(rollingPanel, /卷级蓝图/)
assert.match(rollingPanel, /方向参考/)
assert.doesNotMatch(rollingPanel, /近景滚动规划<\/span>\s*[\s\S]{0,260}进入章节生成/)

assert.match(chapterPlanPrompt, /block_stage_snapshot/)
assert.match(chapterPlanPrompt, /小纲必须从.*故事块.*阶段/)
assert.match(chapterPlanPrompt, /当前章可写内容/)

assert.match(chapterDraftPrompt, /block_stage_snapshot/)
assert.match(chapterDraftPrompt, /本章只执行 block_stage_snapshot/)
assert.match(chapterDraftPrompt, /不读取后续滚动后的 live stage/)

assert.match(legacyChapterPrompt, /故事块.*优先/)
assert.match(legacyChapterPrompt, /nearOutline.*参考/)
assert.doesNotMatch(legacyChapterPrompt, /近景滚动规划（参考，不要逐条照抄）/)

assert.match(contextBuilder, /blockStageSnapshot/)
assert.match(contextBuilder, /priority:\s*1/)
assert.match(contextBuilder, /nearOutline[\s\S]{0,160}priority:\s*[6-9]/)

const volumeIndex = projectView.indexOf('<VolumePlanner')
const blockIndex = projectView.indexOf('<StoryBlockList')
const chapterIndex = projectView.indexOf('章节列表') !== -1
  ? projectView.indexOf('章节列表')
  : projectView.indexOf('绔犺妭鍒楄〃')
assert.ok(volumeIndex !== -1 && blockIndex !== -1 && chapterIndex !== -1)
assert.ok(volumeIndex < blockIndex)
assert.ok(blockIndex < chapterIndex)

console.log('planning hierarchy contract tests passed')
