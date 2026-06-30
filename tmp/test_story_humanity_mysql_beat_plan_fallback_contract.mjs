import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  analyzeChapter,
  extractBeatPlanFields,
  normalizeMysqlBeatPlanRow
} from './story_humanity_rerun_21_25.mjs'

const content = `### 本章事件
陆沉舟确认老张设局。

### 主角即时欲望
先救小九，再决定是否交出星账。

### 情绪锚点
他害怕自己为了父亲线索牺牲小九。

### 误解或恐惧
他误以为老张还可能回头帮忙。

### 关系轻微变化
陆沉舟对老张的信任彻底崩塌，对小九的亏欠加深。

### 给读者的阶段答案
缺指男人真正目标是星账，不是画像。`

const beat = normalizeMysqlBeatPlanRow({
  id: 'project_36',
  project_id: 'project',
  chapter_num: 36,
  story_block_id: 'block-1',
  block_stage_id: 'stage-4',
  block_stage_snapshot: '{"id":"stage-4"}',
  beat_plan_source: 'ai_generated',
  derived_from_story_block: 0,
  derived_reason: '',
  content
})

assert.equal(beat.chapterNum, 36)
assert.equal(beat.beatPlanSource, 'ai_generated')
assert.equal(beat.derivedFromStoryBlock, false)
assert.deepEqual(beat.blockStageSnapshot, { id: 'stage-4' })

const beatPlanFields = extractBeatPlanFields(beat)
const chapter = analyzeChapter({
  chapterNum: 36,
  reportEntry: { title: '更夫', finalized: true, wordCount: 5200 },
  beat,
  beatPlanFields,
  content: '陆沉舟包扎伤口，决定救小九。'
})

assert.equal(chapter.humanityFieldEvidence.emotionalAnchor.status, 'persisted')
assert.equal(chapter.humanityFieldEvidence.relationshipDelta.status, 'persisted')
assert.equal(chapter.humanityFieldEvidence.stageAnswerForReader.source, 'ai_generated')
assert.deepEqual(chapter.derivedHumanityFields, [])
assert.ok(chapter.persistedHumanityFields.includes('protagonistImmediateWant'))

const reportScript = fs.readFileSync('tmp/story_humanity_rerun_21_25.mjs', 'utf8')
assert.match(reportScript, /PYTHONIOENCODING:\s*'utf-8'/)

console.log('story humanity mysql beat plan fallback contract passed')
