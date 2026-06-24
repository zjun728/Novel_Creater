import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

const projectView = readFileSync('frontend/src/views/ProjectView.vue', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const legacyAdjust = ['adjust', 'current', 'block'].join('_')
const legacyChineseAdjust = ['调整', '当前', '块'].join('')
const legacyHint = ['block', 'Review', 'Hint'].join('')
const obsoleteStatus = ['super', 'seded'].join('')
const forbiddenRuntimePattern = new RegExp(`${legacyAdjust}|${legacyChineseAdjust}|${legacyHint}|${obsoleteStatus}`)

assert.ok(
  existsSync('frontend/src/components/story-block/StoryBlockList.vue'),
  'Project chapter management should have a StoryBlockList component'
)
assert.ok(
  existsSync('frontend/src/components/story-block/StoryBlockCard.vue'),
  'StoryBlockCard should render one story block summary'
)
assert.ok(
  existsSync('frontend/src/components/story-block/StoryBlockStageList.vue'),
  'StoryBlockStageList should render expandable stages'
)

const storyBlockList = readFileSync('frontend/src/components/story-block/StoryBlockList.vue', 'utf8')
const storyBlockCard = readFileSync('frontend/src/components/story-block/StoryBlockCard.vue', 'utf8')
const stageList = readFileSync('frontend/src/components/story-block/StoryBlockStageList.vue', 'utf8')
const allUiText = [projectView, writerView, storyBlockList, storyBlockCard, stageList].join('\n')

assert.match(projectView, /useStoryBlockStore/)
assert.match(projectView, /storyBlockStore\.loadBlocks\(id\)/)
assert.match(projectView, /StoryBlockList/)
assert.match(projectView, /currentVolumeStoryBlocks/)
assert.match(projectView, /handleConfirmStoryBlock/)
assert.match(projectView, /handleUpdateStoryBlockRemainingStages/)
assert.match(projectView, /handleCloseStoryBlock/)
assert.match(projectView, /handleOpenNewStoryBlock/)
assert.match(projectView, /handleSaveStoryBlockStageEdit/)
assert.match(projectView, /closeStoryBlockReason/)
assert.match(projectView, /closeReason/)

const volumeIndex = projectView.indexOf('<VolumePlanner')
const blockIndex = projectView.indexOf('<StoryBlockList')
const chapterHeadingIndex = projectView.indexOf('章节列表')
assert.ok(volumeIndex !== -1, 'chapter tab should render volume planning first')
assert.ok(blockIndex !== -1, 'chapter tab should render story block area')
assert.ok(chapterHeadingIndex !== -1, 'chapter tab should render chapter list')
assert.ok(volumeIndex < blockIndex, 'story block area should appear after volume planning')
assert.ok(blockIndex < chapterHeadingIndex, 'story block area should appear before chapter list')

assert.match(storyBlockList, /blocks/)
assert.match(storyBlockList, /activeVolume/)
assert.match(storyBlockList, /chapterRefs/)
assert.match(storyBlockList, /volumeId/)
assert.match(storyBlockList, /confirmBlock/)
assert.match(storyBlockList, /updateRemainingStages/)
assert.match(storyBlockList, /closeBlock/)
assert.match(storyBlockList, /openNewBlock/)
assert.match(storyBlockList, /saveStageEdit/)

assert.match(storyBlockCard, /active/)
assert.match(storyBlockCard, /需确认故事块/)
assert.match(storyBlockCard, /确认故事块/)
assert.match(storyBlockCard, /编辑未执行阶段/)
assert.match(storyBlockCard, /AI 更新后续阶段/)
assert.match(storyBlockCard, /提前结束当前块/)
assert.match(storyBlockCard, /结束并开启新块/)
assert.match(storyBlockCard, /基于未执行内容开启新块/)
assert.match(storyBlockCard, /当前块没有可更新的未执行阶段/)
assert.match(storyBlockCard, /覆盖章节/)
assert.match(storyBlockCard, /下一阶段/)
assert.match(storyBlockCard, /未解决/)
assert.doesNotMatch(storyBlockCard, /开启新故事块/)

assert.match(stageList, /completed|locked|chapterRefs/)
assert.match(stageList, /只读|locked/)
assert.match(stageList, /阶段不是章节/)
assert.doesNotMatch(stageList, /v-model|n-input|textarea/)

assert.match(storyBlockCard + storyBlockList + readFileSync('frontend/src/components/writer/StoryBlockPanel.vue', 'utf8'), /当前故事块快捷操作/)
assert.match(writerView, /当前故事块：/)
assert.match(writerView, /当前阶段：/)
assert.match(writerView, /block_stage_snapshot/)
assert.match(writerView, /生成小纲前会创建故事块/)

assert.doesNotMatch(allUiText, forbiddenRuntimePattern)

console.log('story block project UI contract tests passed')
