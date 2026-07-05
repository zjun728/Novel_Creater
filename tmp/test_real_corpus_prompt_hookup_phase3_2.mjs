import assert from 'node:assert/strict'
import fs from 'node:fs/promises'

import realCorpusLibrary from '../frontend/src/data/realCorpusExperienceCards.v3.json' with { type: 'json' }
import {
  formatRealCorpusExperienceForPrompt,
  detectRealCorpusPromptLeakage,
  retrieveRealCorpusExperienceCards,
} from '../frontend/src/data/realCorpusExperienceCardsV3.js'
import {
  buildSceneExecutionCard,
} from '../frontend/src/utils/sceneExecutionContract.js'
import {
  buildNarrativeVoiceContractV2,
} from '../frontend/src/utils/narrativeVoiceContract.js'
import {
  buildDraftPrompt,
} from '../frontend/src/prompts/chapterDraftPrompt.js'
import {
  assertRealCorpusPromptHookupReportMatchesJson,
  buildPhase32Report,
  runRealCorpusPromptHookupPhase32,
  SYNTHETIC_PROMPT_HOOKUP_SCENES,
} from './run_real_corpus_prompt_hookup_phase3_2.mjs'

const FORBIDDEN_PROMPT_TOKENS = [
  'sourceTitle',
  'sourceFileHash',
  'sourceWindowHashes',
  'sourceAuditOnly',
  'rawExcerpt',
  'sourceText',
  'sourceCardIds',
  'guardSnapshot',
  'futureRoadmap',
  'stateAuthority',
  '顾闻舟',
  '幕后人是',
]

function assertNotContainsForbiddenPromptTokens(text, label) {
  for (const token of FORBIDDEN_PROMPT_TOKENS) {
    assert.equal(String(text).includes(token), false, `${label} leaked forbidden token: ${token}`)
  }
}

function contextForScene(scene) {
  const context = {
    chapterNum: 31,
    chapterGoal: scene.chapterGoal,
    currentStageCreativeContext: {
      writableFacts: scene.facts.map((text, index) => ({
        text,
        sourceChapterNum: 30,
        sourceVersionId: `phase3-2-final-${scene.id}-${index + 1}`,
        commitStatus: 'committed',
      })),
      stageBoundary: {
        stopPoint: scene.chapterGoal.stopPoint,
      },
    },
    stateAuthority: {
      facts: scene.facts.map((text, index) => ({
        text,
        sourceChapterNum: 30,
        sourceVersionId: `phase3-2-final-${scene.id}-${index + 1}`,
        commitStatus: 'committed',
      })),
    },
    creativeStageContract: {
      allowedFacts: scene.facts,
      stopPoint: scene.chapterGoal.stopPoint,
      forbiddenDirections: ['不能公开 guard-only future roadmap。'],
    },
    guardSnapshot: {
      futureRoadmap: `后续才揭露：${scene.futureSecret}`,
    },
    savedBeatPlan: ['旧计划：当场公开顾闻舟是幕后人。'],
    wordTarget: { target: 680, min: 520, max: 860 },
  }
  context.narrativeVoiceContract = buildNarrativeVoiceContractV2({
    styleBible: ['短场景但必须有压力、选择和情绪转折。'],
  })
  context.sceneExecutionCard = buildSceneExecutionCard(context)
  return context
}

assert.equal(SYNTHETIC_PROMPT_HOOKUP_SCENES.length, 6)

for (const scene of SYNTHETIC_PROMPT_HOOKUP_SCENES) {
  const context = contextForScene(scene)
  const selected = retrieveRealCorpusExperienceCards(
    context.sceneExecutionCard,
    realCorpusLibrary.cards,
    { limit: 2 },
  )
  assert.ok(selected.length >= 1 && selected.length <= 2, `${scene.id} should select one or two V3 cards`)
  assert.ok(
    selected.some(card => scene.expectedTags.some(tag => card.sceneFunctionTags.includes(tag))),
    `${scene.id} should select a card matching expected scene function tags`,
  )
  const helper = formatRealCorpusExperienceForPrompt(context.sceneExecutionCard, realCorpusLibrary.cards, {
    maxCards: 2,
    maxSectionChars: 900,
  })
  assert.match(helper, /Real Corpus Experience Helper/, `${scene.id} should produce helper section`)
  assert.match(helper, /表达手法参考/, `${scene.id} helper must state expression-only purpose`)
  assert.ok(helper.length <= 900, `${scene.id} helper must stay low-dose`)
  assertNotContainsForbiddenPromptTokens(helper, `${scene.id} helper`)
  assert.equal(detectRealCorpusPromptLeakage(helper, selected).detected, false)
}

const emptyHelper = formatRealCorpusExperienceForPrompt({}, realCorpusLibrary.cards)
assert.equal(emptyHelper, '', 'empty or low-signal scene must not fallback-select real corpus cards')

const dialogueContext = contextForScene(SYNTHETIC_PROMPT_HOOKUP_SCENES.find(scene => scene.id === 'interrogation_negotiation'))
const backendReferenceOnlyCard = {
  ...realCorpusLibrary.cards[0],
  promptReadiness: 'backend-reference-only',
  promptInjectionSafeVersion: 'BACKEND_ONLY_SHOULD_NOT_ENTER_PROMPT',
  writingMethod: 'BACKEND_ONLY_METHOD_SHOULD_NOT_ENTER_PROMPT',
  originalMicroDemo: 'BACKEND_ONLY_DEMO_SHOULD_NOT_ENTER_PROMPT',
  antiAiReminder: 'BACKEND_ONLY_REMINDER_SHOULD_NOT_ENTER_PROMPT',
}
const backendReferenceOnlyHelper = formatRealCorpusExperienceForPrompt(
  dialogueContext.sceneExecutionCard,
  [backendReferenceOnlyCard],
)
assert.equal(backendReferenceOnlyHelper, '', 'formatter must not promote backend-reference-only cards into prompt text')

const noSamplePrompt = buildDraftPrompt({
  ...dialogueContext,
  realCorpusExperienceCards: realCorpusLibrary.cards,
  enableRealCorpusExperienceCards: false,
})
assert.equal(noSamplePrompt.includes('Real Corpus Experience Helper'), false, 'V3 helper must be opt-in')

const v3Prompt = buildDraftPrompt({
  ...dialogueContext,
  realCorpusExperienceCards: realCorpusLibrary.cards,
  enableRealCorpusExperienceCards: true,
})
assert.match(v3Prompt, /Real Corpus Experience Helper/, 'opt-in draft prompt should include V3 helper')
assert.match(v3Prompt, /Scene Execution Card/, 'draft prompt should retain Scene Execution Card')
assert.match(v3Prompt, /Narrative Voice Contract/, 'draft prompt should retain Narrative Voice Contract')
assertNotContainsForbiddenPromptTokens(v3Prompt, 'V3 draft prompt')
assert.equal(v3Prompt.includes(dialogueContext.sceneExecutionCard.stopPoint), true, 'stopPoint should remain intact')
assert.equal(JSON.stringify(dialogueContext.sceneExecutionCard.allowedFacts), JSON.stringify(buildSceneExecutionCard(dialogueContext).allowedFacts), 'helper must not mutate allowedFacts')

const formalAndV3Prompt = buildDraftPrompt({
  ...dialogueContext,
  activeWritingStandards: [{
    id: 'system-dialogue-realism',
    name: '对话真实感增强',
    status: 'active',
    sourceKind: 'system',
    principles: ['先让角色带着自己的算盘说话，不要句句替剧情服务。'],
    originalMicroDemo: '他把药放到桌边，说你爱用不用。人却没走。',
    antiAiReminder: '不要把关心写成说明书。',
  }],
  realCorpusExperienceCards: realCorpusLibrary.cards,
  enableRealCorpusExperienceCards: true,
})
assert.equal((formalAndV3Prompt.match(/正式写作标准低量调用/g) || []).length, 1)
assert.equal((formalAndV3Prompt.match(/Real Corpus Experience Helper/g) || []).length, 1)
assert.ok(
  (formalAndV3Prompt.match(/Helper [12]/g) || []).length <= 1,
  'formal standard + V3 budget should cap real corpus helper to one card',
)
assert.ok(formalAndV3Prompt.length - noSamplePrompt.length < 1300, 'V3 helper should not turn draft prompt into a thick rule list')

async function fileStat(path) {
  try {
    const stat = await fs.stat(path)
    return { size: stat.size, mtimeMs: stat.mtimeMs }
  } catch {
    return null
  }
}

const artifactPaths = [
  'tmp/realistic-flow-qa/real-corpus-prompt-hookup-phase3-2.json',
  'tmp/realistic-flow-qa/real-corpus-prompt-hookup-phase3-2-report.md',
]
const beforeStats = await Promise.all(artifactPaths.map(fileStat))
const payload = await runRealCorpusPromptHookupPhase32({ writeArtifacts: false })
const afterStats = await Promise.all(artifactPaths.map(fileStat))
assert.deepEqual(afterStats, beforeStats, 'Phase 3.2 contract test must be read-only and not rewrite QA artifacts')
const defaultPayload = await runRealCorpusPromptHookupPhase32()
const defaultAfterStats = await Promise.all(artifactPaths.map(fileStat))
assert.deepEqual(defaultAfterStats, beforeStats, 'Phase 3.2 runner API must be read-only by default; only CLI should write artifacts')
assert.equal(defaultPayload.generatedAt, payload.generatedAt)
assert.equal(payload.status, 'completed')
assert.equal(payload.generatedAt, '2026-07-05T00:00:00.000Z', 'Phase 3.2 payload timestamp must be deterministic')
assert.equal(payload.boundary.serviceStarted, false)
assert.equal(payload.boundary.realDbConnection, false)
assert.equal(payload.boundary.liveGenerationRun, false)
assert.equal(payload.boundary.modelRun, false)
assert.equal(payload.scenes.length, 6)
assert.equal(payload.summary.futureLeaks, 0)
assert.equal(payload.summary.sourceLeaks, 0)
assert.equal(payload.summary.lowSignalSelectedCards, 0)
assert.equal(payload.summary.promptBudgetViolations, 0)
assert.equal(payload.summary.sampleV3PromptRegressions, 0)
assert.ok(payload.summary.averageSignalLift > 0)

const report = buildPhase32Report(payload)
assertRealCorpusPromptHookupReportMatchesJson(report, payload)

if (afterStats.every(Boolean)) {
  const persistedPayload = JSON.parse(await fs.readFile(artifactPaths[0], 'utf8'))
  const persistedReport = await fs.readFile(artifactPaths[1], 'utf8')
  assertRealCorpusPromptHookupReportMatchesJson(persistedReport, persistedPayload)
}

console.log('real corpus prompt hookup phase3.2 contract passed')
