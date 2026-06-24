import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildLightweightScenePlanContext,
  buildScenePlanPrompt,
  buildScenePlanPromptWithDiagnostics
} from '../frontend/src/prompts/chapterPlanPrompt.js'

const hugeBible = 'FULL_BIBLE_SENTINEL '.repeat(900)
const hugeVolume = 'FULL_VOLUME_SENTINEL '.repeat(700)
const hugeSettings = 'FULL_SETTING_SENTINEL '.repeat(700)
const rawDiagnostics = 'PLANNING_DIAGNOSTICS_SENTINEL '.repeat(300)
const hugeReviewHistory = 'FULL_REVIEW_HISTORY_SENTINEL '.repeat(300)

const overloadedContext = {
  chapterNum: 3,
  bible: {
    premise: hugeBible,
    worldRules: hugeBible,
    protagonist: hugeBible
  },
  volumePlanning: [
    {
      title: '第一卷',
      coreGoal: '陆沉舟查明父亲旧案与星账异常的第一条因果线。',
      summary: hugeVolume,
      handoffPoint: '远端交接点不能直接进入本章。'
    }
  ],
  currentVolume: {
    title: '第一卷',
    startChapter: 1,
    endChapter: 80,
    coreGoal: '陆沉舟查明父亲旧案与星账异常的第一条因果线。',
    mainConflict: '巡天司封锁旧档案，商盟控制灵脉城。'
  },
  volumeStage: {
    title: '第一卷',
    coreGoal: '陆沉舟查明父亲旧案与星账异常的第一条因果线。',
    mainConflict: '巡天司封锁旧档案，商盟控制灵脉城。',
    handoffPoint: '远端交接点不能直接进入本章。',
    summary: hugeVolume
  },
  settingLibrary: hugeSettings,
  stateLedger: {
    characters: hugeSettings,
    locations: hugeSettings,
    items: hugeSettings
  },
  storyBlock: {
    id: 'block-night-city',
    title: '夜行灵脉城',
    status: 'active',
    goal: '陆沉舟在灵脉城夜行中确认旧档线索仍在流动，并付出一次可见代价。',
    storyFunction: '把追查从当铺推向灵脉城深处。',
    entryState: '陆沉舟带着残页入城，巡天司暗探已经封锁账房外线。',
    mainPressure: '巡天司追捕、商盟盘查、星账使用代价同时逼近。',
    nextStageSuggestion: 'stage-4 后续：潜入旧账房，确认残页所指柜位是否存在。',
    unresolvedQuestions: [
      '父亲名籍为何被封存',
      '星账为什么指向灵脉城',
      '纪九到底为谁递话'
    ],
    planningDiagnostics: {
      rawHead: rawDiagnostics,
      rawTail: rawDiagnostics
    },
    reviewHistory: [
      { rawTail: hugeReviewHistory }
    ],
    stagePlan: [
      {
        id: 'stage-1',
        purpose: '进入灵脉城。',
        sceneOrAction: '陆沉舟避开盘查入城。',
        status: 'completed'
      },
      {
        id: 'stage-4',
        purpose: '确认旧账房柜位。',
        sceneOrAction: '夜探旧账房，找到甲字柜痕迹。',
        choice: '冒险开启柜门，还是先救被拖走的线人。',
        costOrConsequence: '残页被星账灼去一角，巡天司获得他的气息。',
        status: 'planned'
      }
    ]
  },
  blockStageSnapshot: {
    storyBlockId: 'block-night-city',
    stageId: 'stage-4',
    blockGoal: '陆沉舟在灵脉城夜行中确认旧档线索仍在流动，并付出一次可见代价。',
    storyFunction: '把追查从当铺推向灵脉城深处。',
    entryState: '陆沉舟带着残页入城，巡天司暗探已经封锁账房外线。',
    mainPressure: '巡天司追捕、商盟盘查、星账使用代价同时逼近。',
    stagePurpose: '确认旧账房柜位。',
    stageAction: '夜探旧账房，找到甲字柜痕迹。',
    stageChoice: '冒险开启柜门，还是先救被拖走的线人。',
    stageCostOrConsequence: '残页被星账灼去一角，巡天司获得他的气息。',
    nextStageSuggestion: '带着损坏残页逃出旧账房。'
  },
  previousChapterEnding: '上一章结尾，陆沉舟听见旧账房后墙里有人敲出父亲名字。',
  recentSummaries: [
    '第 1 章：雨夜当铺的星账出现亡父名字。',
    '第 2 章：陆沉舟带着残页避开追捕，进入灵脉城边门。'
  ],
  recentFacts: [
    '陆沉舟持有破损残页。',
    '巡天司知道他查过旧账。',
    '纪九递过一次假路引。',
    '灵脉城旧账房有甲字柜传闻。',
    '星账每次使用都会索取代价。',
    '额外事实不应无限注入。'
  ],
  reviewHistory: hugeReviewHistory
}

const { prompt, diagnostics, lightweightContext } = buildScenePlanPromptWithDiagnostics(overloadedContext)

assert.equal(buildScenePlanPrompt(overloadedContext), prompt, 'default scene plan prompt must use the diagnosed lightweight prompt')
assert.ok(prompt.length <= 18000, `beat plan prompt should stay below hard cap, got ${prompt.length}`)
assert.ok(prompt.includes('夜行灵脉城'), 'prompt should keep the active story block title')
assert.ok(prompt.includes('stage-4'), 'prompt should keep the injected current stage id')
assert.ok(prompt.includes('上一章结尾'), 'prompt should keep previous chapter ending')
assert.ok(prompt.includes('陆沉舟持有破损残页'), 'prompt should keep recent key facts')
assert.doesNotMatch(prompt, /FULL_BIBLE_SENTINEL/, 'prompt must not inject full bible')
assert.doesNotMatch(prompt, /FULL_VOLUME_SENTINEL/, 'prompt must not inject full volume plan')
assert.doesNotMatch(prompt, /FULL_SETTING_SENTINEL/, 'prompt must not inject full setting library')
assert.doesNotMatch(prompt, /PLANNING_DIAGNOSTICS_SENTINEL/, 'prompt must not inject story block raw diagnostics')
assert.doesNotMatch(prompt, /FULL_REVIEW_HISTORY_SENTINEL/, 'prompt must not inject full review history')

assert.ok(diagnostics.promptCharsBeforeCompression > diagnostics.promptCharsAfterCompression)
assert.ok(diagnostics.contextCompressionApplied, 'overloaded prompt should be marked as compressed')
assert.ok(diagnostics.promptTokensApprox > 0)
assert.equal(diagnostics.storyBlockId, 'block-night-city')
assert.equal(diagnostics.blockStageId, 'stage-4')
assert.equal(diagnostics.activeStoryBlockExists, true)
assert.equal(diagnostics.activeStoryBlockStageCount, 2)
assert.match(diagnostics.activeStoryBlockNextStage, /stage-4/)
assert.equal(diagnostics.oversizedInputs.bible, true)
assert.equal(diagnostics.oversizedInputs.volumes, true)
assert.equal(diagnostics.oversizedInputs.settings, true)
assert.equal(diagnostics.oversizedInputs.diagnostics, true)

assert.equal(lightweightContext.storyBlock.id, 'block-night-city')
assert.equal(lightweightContext.storyBlock.stagePlan.length, 2)
assert.equal(lightweightContext.recentFacts.length, 5, 'only the latest 3-5 facts should be injected')
assert.equal(buildLightweightScenePlanContext(overloadedContext).storyBlock.planningDiagnostics, undefined)

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
assert.match(writerStore, /buildScenePlanPromptWithDiagnostics/, 'writer store should use prompt diagnostics builder')
assert.match(writerStore, /beat-plan-diagnostics:\$\{projectId\}:\$\{chapterNum\}/, 'writer store should persist beat plan diagnostics for live reports')
assert.match(writerStore, /forceMinimal/, 'empty response retry should use a more compressed prompt')
assert.match(writerStore, /localSafetyDraftGenerated/, 'second empty response should record local safety draft generation')

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
assert.match(liveScript, /readBeatPlanDiagnostics/, 'live script should read beat plan diagnostics from the browser')
assert.match(liveScript, /beatPlanPromptDiagnostics/, 'live failure diagnostics should include prompt diagnostics')
assert.match(liveScript, /chapter_1_too_short/, 'live report should carry the chapter 1 shortness backlog marker')
assert.match(liveScript, /chapter_2_bad_title/, 'live report should carry the chapter 2 weak-title backlog marker')
assert.match(liveScript, /story_block_prompt_overloaded/, 'live report should carry the story block prompt overload backlog marker')

console.log('chapter beat plan context diagnostics contract tests passed')
