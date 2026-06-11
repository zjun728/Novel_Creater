import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const qaScript = readFileSync('tmp/run_realistic_longform_flow_fixed.mjs', 'utf8')

assert.match(
  qaScript,
  /buildWritingContext/,
  'realistic QA flow should reuse the same writing-context builder as the frontend writer'
)

assert.match(
  qaScript,
  /buildChapterBeatPrompt/,
  'realistic QA flow should reuse the same chapter-beat prompt builder as the frontend writer'
)

assert.match(
  qaScript,
  /buildChapterPrompt/,
  'realistic QA flow should reuse the same chapter prompt builder as the frontend writer'
)

assert.ok(
  !qaScript.includes('创作种子：${JSON.stringify(selectedSeed)}'),
  'realistic QA flow must not inject full selected seed JSON into chapter context'
)

assert.ok(
  !qaScript.includes('创作圣经：${JSON.stringify(bible || {})}'),
  'realistic QA flow must not inject full bible JSON into chapter context'
)

const { buildWritingContext } = await import('../frontend/src/utils/contextBuilder.js')
const { buildChapterPrompt, buildChapterBeatPrompt } = await import('../frontend/src/prompts/chapter.js')

const context = buildWritingContext(
  {
    bible: {
      premise: '主角以考据破解异常规则。',
      styleBible: '冷静、具体、少解释。',
      worldRules: '代价必须有来源和后果。',
      writingProfile: { primaryStandard: 'rational-fantasy', secondaryFlavor: 'suspense-hook' }
    },
    outline: {
      nearChapters: [
        {
          chapterNum: 2,
          title: '镜纹',
          goal: '承接上一章异象，确认代价。',
          conflict: '主角必须在未知风险中验证线索。'
        }
      ]
    },
    characters: [],
    plotThreads: [],
    canonFacts: []
  },
  2,
  undefined,
  { entities: [], relations: [], changeEvents: [] },
  { volumes: [] },
  { tasks: [] }
).context

context.chapterNum = 2
context.previousChapterEnding = '铜镜裂开，镜面里露出第二张脸。'
context.wordTarget = { target: 5000, min: 4500, max: 6500, hardMin: 4000, hardMax: 7000 }

assert.ok(context.creativeBoundary || context.premise, 'writing context should expose a compact drafting boundary')
assert.ok(buildChapterBeatPrompt(context).includes('上一章结尾'), 'beat prompt should carry previous-chapter ending')
assert.ok(buildChapterPrompt({ ...context, beatPlan: '1. 承接镜面异象。' }).includes('已确认本章小纲'), 'chapter prompt should carry confirmed beat plan')

console.log('realistic QA frontend-context contract ok')
