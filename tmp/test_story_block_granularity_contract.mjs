import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const promptSource = readFileSync('frontend/src/prompts/storyBlockPrompt.js', 'utf8')
const writerSource = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const liveSource = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(promptSource, /剧情任务单元/, '故事块规划 prompt 必须定义为剧情任务单元')
assert.match(promptSource, /不是章节容器/, '故事块规划 prompt 必须禁止把故事块当章节容器')
assert.match(promptSource, /不允许[\s\S]{0,80}每章[\s\S]{0,80}(新块|新故事块)/, '故事块规划 prompt 必须禁止每章新块')
assert.match(promptSource, /stagePlan[\s\S]{0,120}(3-6|3 到 6|3 至 6)/, 'stagePlan 应通常为 3-6 个推进阶段')
assert.match(promptSource, /大型任务[\s\S]{0,120}(更多|10 章以上|十章以上)/, '大型任务必须允许更长故事块')
assert.match(promptSource, /短(过渡|冲突|块)[\s\S]{0,120}(原因|说明)/, '短块必须要求说明原因')
assert.match(promptSource, /completionEvidence/, '回看输出必须包含 completionEvidence')
assert.match(promptSource, /singleChapterBlockReason/, '回看输出必须包含 singleChapterBlockReason')
assert.match(promptSource, /不能因为一章结束[\s\S]{0,120}(complete_current_block|open_new_block)/, '回看 prompt 必须禁止仅因一章结束而结束块')

assert.match(writerSource, /function normalizeStoryBlockReviewForGranularity/, 'WriterView 必须有故事块粒度归一函数')
assert.match(writerSource, /function hasStoryBlockCompletionEvidence/, 'WriterView 必须校验 completionEvidence')
assert.match(writerSource, /async function ensureActiveBlockHasForwardStages/, '阶段耗尽时必须优先滚动补充后续阶段')
assert.doesNotMatch(
  writerSource,
  /没有可用于新章节的小纲阶段，生成前自动完成并开启新故事块/,
  '阶段耗尽不能直接自动 complete 并开新块'
)
assert.match(writerSource, /closedBy:\s*'ai_review'/, '自动回看关闭/完成必须标记 closedBy=ai_review')
assert.match(writerSource, /singleChapterBlockReason/, '前端必须记录单章块原因')

assert.match(liveSource, /blocksCreated/, 'live 报告必须记录 blocksCreated')
assert.match(liveSource, /chaptersPerBlock/, 'live 报告必须记录 chaptersPerBlock')
assert.match(liveSource, /averageChaptersPerBlock/, 'live 报告必须记录 averageChaptersPerBlock')
assert.match(liveSource, /singleChapterBlockCount/, 'live 报告必须记录 singleChapterBlockCount')
assert.match(liveSource, /consecutiveSingleChapterBlocks/, 'live 报告必须记录 consecutiveSingleChapterBlocks')
assert.match(liveSource, /executedStageCountPerBlock/, 'live 报告必须记录 executedStageCountPerBlock')
assert.match(liveSource, /completedStageCountPerBlock/, 'live 报告必须记录 completedStageCountPerBlock')
assert.match(liveSource, /closedUnexecutedStageCountPerBlock/, 'live 报告必须区分未执行随块关闭阶段')
assert.match(liveSource, /invalidatedStageCountPerBlock/, 'live 报告必须区分失效阶段')
assert.match(liveSource, /blockCloseReasonType/, 'live 报告必须记录关闭原因类型')
assert.match(liveSource, /earlyCloseAllowed/, 'live 报告必须记录提前关闭是否被允许')
assert.match(liveSource, /story_block_too_fragmented/, '连续单章块必须触发 story_block_too_fragmented warning')
assert.match(liveSource, /story_block_stalled/, '长块无推进必须触发 story_block_stalled warning')
assert.match(liveSource, /story_block_fragmentation_quality_hold/, '连续弱单章块必须触发质量 hold')

assert.match(liveSource, /story_block_stage_reuse_detected/, '必须保留 stage reuse 防线')
assert.match(readFileSync('frontend/src/stores/writerStore.js', 'utf8'), /parseRetryTriggered/, '必须保留小纲 parse retry 恢复链路')
assert.match(readFileSync('frontend/src/api/ai/index.js', 'utf8'), /retryable/, '必须保留 AI proxy retryable 重试链路')
