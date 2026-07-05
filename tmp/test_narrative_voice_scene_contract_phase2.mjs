import assert from 'node:assert/strict'

import {
  buildNarrativeVoiceContractV2,
  formatNarrativeVoiceContractForPrompt,
  lintNarrativeVoiceContractV2,
  sanitizeNarrativeVoiceContractV2,
} from '../frontend/src/utils/narrativeVoiceContract.js'
import {
  buildSceneExecutionCard,
  formatSceneExecutionCardForPrompt,
} from '../frontend/src/utils/sceneExecutionContract.js'
import {
  evaluateLiteraryQuality,
  evaluatePromptQuality,
} from '../frontend/src/utils/literaryQualityEvaluator.js'
import {
  buildDraftPrompt,
  buildDraftSystemPrompt,
} from '../frontend/src/prompts/chapterDraftPrompt.js'

function assertNotIncludes(haystack, needle, message) {
  assert.equal(String(haystack).includes(needle), false, message)
}

function assertIncludes(haystack, needle, message) {
  assert.equal(String(haystack).includes(needle), true, message)
}

const riskyStyleBible = [
  '平台默认：节奏快，场景短促，少描述多动作，对话简洁。',
  '不要写成历史文献、报告或规则说明。',
]

const voiceContract = buildNarrativeVoiceContractV2({
  styleBible: riskyStyleBible,
  writingProfile: {
    tone: '紧张、贴近角色',
    rhythm: '短场景推进',
  },
})

assert.equal(voiceContract.schemaVersion, 'narrative-voice-contract-v2')
assert.equal(voiceContract.scope, 'expression_only')
assert.equal(voiceContract.dialogue.conflictAndSubtext, true)
assert.equal(voiceContract.emotion.mustTurn, true)
assert.equal(voiceContract.embodiment.facialVoiceEnvironment, true)
assert.equal(voiceContract.action.mustCarryIntentionAndRelationshipChange, true)

const voicePrompt = formatNarrativeVoiceContractForPrompt(voiceContract)
assertIncludes(voicePrompt, '情绪转折', 'voice prompt must turn risky fast pacing into emotional turn requirements')
assertIncludes(voicePrompt, '潜台词', 'voice prompt must preserve concise dialogue as conflict/subtext')
assertIncludes(voicePrompt, '表情', 'voice prompt must counterbalance less-description with embodied cues')
assertNotIncludes(voicePrompt, '少描述多动作', 'voice prompt must not repeat risky shorthand')
assertNotIncludes(voicePrompt, '对话简洁', 'voice prompt must not repeat risky shorthand')

const unsafeVoice = {
  ...voiceContract,
  factOverrides: ['主角其实已经知道未来秘密'],
  stageBoundary: { forceStopAfter: 'future reveal' },
  worldRules: ['改写世界观'],
  guardSnapshot: { futureRoadmap: '第九章公开真相' },
  rawStyle: '像历史文献和履约报告一样规则说明',
}
const unsafeLint = lintNarrativeVoiceContractV2(unsafeVoice)
assert.equal(unsafeLint.ok, false, 'unsafe voice contract must be rejected')
assert(unsafeLint.issues.some((issue) => issue.code === 'forbidden_fact_or_stage_field'))
assert(unsafeLint.issues.some((issue) => issue.code === 'documentary_or_rule_tone'))

const sanitizedVoice = sanitizeNarrativeVoiceContractV2(unsafeVoice)
assert.equal(sanitizedVoice.factOverrides, undefined)
assert.equal(sanitizedVoice.stageBoundary, undefined)
assert.equal(sanitizedVoice.worldRules, undefined)
assert.equal(sanitizedVoice.guardSnapshot, undefined)
assert.equal(sanitizedVoice.lint.ok, true)

const cleanCreativeContext = {
  chapterNum: 12,
  chapterGoal: {
    goal: '让林遥在审讯室里逼周岑承认他隐瞒了港口账本。',
    conflict: '林遥 vs 周岑',
    emotionalTurn: '林遥从压着怒意试探，转为意识到周岑是在保护另一个人。',
    stopPoint: '周岑只说出账本藏在旧码头，不说出幕后人。',
  },
  currentStageCreativeContext: {
    writableFacts: [
      { text: '林遥已经拿到旧码头的半张提货单。', sourceChapterNum: 11, commitStatus: 'committed' },
    ],
    stageBoundary: {
      stopPoint: '本章只能逼出旧码头线索，不能公开幕后人。',
    },
  },
  stateAuthority: {
    facts: [
      { text: '林遥已经拿到旧码头的半张提货单。', sourceChapterNum: 11, commitStatus: 'committed' },
    ],
  },
  creativeStageContract: {
    allowedFacts: ['林遥已经拿到旧码头的半张提货单。'],
    stopPoint: '本章只能逼出旧码头线索，不能公开幕后人。',
    forbiddenDirections: ['不能公开幕后人姓名。'],
  },
  guardSnapshot: {
    futureRoadmap: '未来第十五章才揭露幕后人是顾闻舟。',
    forbiddenFutureReveal: '顾闻舟是幕后人。',
  },
  savedBeatPlan: [
    '错误旧计划：林遥当场说出顾闻舟是幕后人。',
  ],
  beatPlan: [
    '当前场景：林遥用提货单逼周岑开口，但只获得旧码头线索。',
  ],
  narrativeVoiceContract: voiceContract,
}

const sceneCard = buildSceneExecutionCard(cleanCreativeContext)
assert.equal(sceneCard.schemaVersion, 'scene-execution-card-v1')
assert.equal(sceneCard.scope, 'current_stage_only')
assertIncludes(sceneCard.sceneObjective, '审讯室', 'scene objective should come from current creative goal')
assertIncludes(sceneCard.conflictPair, '林遥 vs 周岑', 'scene card should preserve conflict pair')
assertIncludes(sceneCard.emotionalTurn, '保护另一个人', 'scene card should keep the emotional turn')
assertIncludes(sceneCard.dialogueTask, '潜台词', 'scene card should force dialogue conflict/subtext')
assert(sceneCard.allowedFacts.some((fact) => fact.text.includes('半张提货单')))
assert.equal(sceneCard.stopPoint.includes('不能公开幕后人'), true)

const scenePrompt = formatSceneExecutionCardForPrompt(sceneCard)
assertIncludes(scenePrompt, 'Scene Execution Card', 'formatted prompt must expose the compact scene card')
assertIncludes(scenePrompt, '至少两轮直接引号对白', 'scene card must explicitly ask for direct dialogue exchange')
assertIncludes(scenePrompt, '本场必须出现一次情绪转折', 'scene card must explicitly require an emotional turn on page')
assertIncludes(scenePrompt, '一处短内心', 'scene card must explicitly require short interiority')
assertNotIncludes(scenePrompt, '顾闻舟', 'guard-only future roadmap must not enter scene card prompt')
assertNotIncludes(scenePrompt, '未来第十五章', 'guard-only roadmap timing must not enter scene card prompt')
assertNotIncludes(scenePrompt, '错误旧计划', 'saved beat plan must not become scene authority')
assertNotIncludes(scenePrompt, 'guardSnapshot', 'creative prompt must not mention guard implementation concepts')
assertNotIncludes(scenePrompt, 'guard-only', 'creative prompt must not mention guard implementation concepts')
assertNotIncludes(scenePrompt, 'roadmap', 'creative prompt must not mention roadmap implementation concepts')
assertNotIncludes(scenePrompt, '未来路线', 'creative prompt must not mention future-roadmap concepts')

const untrustedFactCard = buildSceneExecutionCard({
  chapterGoal: cleanCreativeContext.chapterGoal,
  currentStageCreativeContext: {
    writableFacts: [
      { text: '失败候选声称顾闻舟已经暴露。', commitStatus: 'failed' },
      { text: '候选小纲声称林遥已经知道幕后人。', commitStatus: 'candidate' },
      { text: '无来源旧记录声称账本已经公开。' },
    ],
  },
  stateAuthority: {
    facts: [
      { text: '可信事实：林遥只有半张提货单。', commitStatus: 'committed', sourceChapterNum: 11 },
      { text: '未知来源事实不应升为高可信。', trustLevel: 'unknown' },
      { text: '降级来源事实不应升为高可信。', trustLevel: 'degraded' },
    ],
  },
  creativeStageContract: cleanCreativeContext.creativeStageContract,
})
const untrustedFactText = untrustedFactCard.allowedFacts.map((fact) => fact.text).join('\n')
assertIncludes(untrustedFactText, '可信事实', 'committed facts should remain allowed')
assertNotIncludes(untrustedFactText, '失败候选', 'failed facts must not enter scene card authority')
assertNotIncludes(untrustedFactText, '候选小纲', 'candidate facts must not enter scene card authority')
assertNotIncludes(untrustedFactText, '无来源旧记录', 'missing-provenance facts must not enter scene card authority')
assertNotIncludes(untrustedFactText, '未知来源', 'unknown trust facts must not enter scene card authority')
assertNotIncludes(untrustedFactText, '降级来源', 'degraded trust facts must not enter scene card authority')

const draftSystemPrompt = buildDraftSystemPrompt()
assertNotIncludes(draftSystemPrompt, 'AI 痕迹源头预防', 'creative system prompt must not include the thick AI-trace checklist')
assertNotIncludes(draftSystemPrompt, '检测规避', 'creative system prompt must not sound like anti-detection compliance')

const draftPrompt = buildDraftPrompt({
  ...cleanCreativeContext,
  sceneExecutionCard: sceneCard,
  narrativeVoiceContract: voiceContract,
  wordTarget: 900,
})
assertIncludes(draftPrompt, 'Scene Execution Card', 'draft prompt must prioritize the scene card')
assertIncludes(draftPrompt, 'Narrative Voice Contract', 'draft prompt must include the expression-only voice contract')
assertIncludes(draftPrompt, '情绪转折', 'draft prompt must keep drama-oriented voice guidance')
assertNotIncludes(draftPrompt, '## 写作质量方向', 'draft prompt must not fall back to the old thick checklist heading')
assertNotIncludes(draftPrompt, '顾闻舟', 'guard-only future roadmap must not enter creative draft prompt')
assertNotIncludes(draftPrompt, '少描述多动作', 'draft prompt must not repeat risky style shorthand')

const badPromptQuality = evaluatePromptQuality('要求：节奏快，场景短促，少描述多动作，对话简洁。')
assert.equal(badPromptQuality.passed, false)
assert(badPromptQuality.issues.some((issue) => issue.code === 'unbalanced_less_description'))

const hardDocumentaryText = [
  '本章主要说明林遥根据提货单完成审讯任务。',
  '首先，她进行观察；其次，她按照规则推进问题；最后，周岑交代旧码头线索。',
  '这表明角色关系出现变化，也意味着后续剧情可以进入下一阶段。',
  '林遥握拳，周岑沉默。她再次握拳，他继续沉默。她的指节发白，他的指节也发白。',
].join('\n')

const badQuality = evaluateLiteraryQuality(hardDocumentaryText, {
  prompt: '要求：节奏快，场景短促，少描述多动作，对话简洁。',
})
assert.equal(badQuality.passed, false)
const badCodes = badQuality.issues.map((issue) => issue.code)
assert(badCodes.includes('documentary_tone'))
assert(badCodes.includes('summary_tone'))
assert(badCodes.includes('low_dialogue_conflict'))
assert(badCodes.includes('missing_emotional_turn'))
assert(badCodes.includes('repetitive_action_template'))
assert(badCodes.includes('prompt_unbalanced_less_description'))

const dramaticSceneText = [
  '雨水顺着审讯室的排风口滴下来，落在提货单缺失的边角上。',
  '林遥把纸推过去，声音压得很低：“周岑，你不是忘了账本，你是在替谁拖时间。”',
  '周岑的喉结动了一下，笑意没挂住：“你知道得太少，别把自己送进去。”',
  '“那就告诉我旧码头是谁的。”她盯着他的眼睛，指尖没有再敲桌面。',
  '他偏开脸，窗外警灯一闪，把他的脸照得发白。她忽然明白，那不是挑衅，是怕。',
  '周岑终于开口：“三号仓。只到三号仓为止。”',
].join('\n')

const goodQuality = evaluateLiteraryQuality(dramaticSceneText)
assert.equal(goodQuality.passed, true)
assert(goodQuality.score >= 75, `expected good dramatic scene score >= 75, got ${goodQuality.score}`)
assert.equal(goodQuality.issues.some((issue) => issue.severity === 'blocking'), false)

const singleDocumentaryCueScene = [
  '首先，林遥没有坐下，她把半张提货单推到周岑眼前。',
  '“你不是忘了账本，”她说，“你是在替谁拖时间。”',
  '周岑的笑意僵在嘴角：“别把自己送进去。”',
  '窗外警灯一闪，她忽然明白，他怕的不是她，是门外那个人。',
].join('\n')
const singleCueQuality = evaluateLiteraryQuality(singleDocumentaryCueScene)
assert(singleCueQuality.metrics.documentaryHits <= 1, 'single documentary cue should count as one hit')
assert.equal(singleCueQuality.issues.some((issue) => issue.code === 'documentary_tone'), false)

const repeatedSummaryText = [
  '他意识到这件事意味着关系变化。',
  '她意识到这意味着后续可以推进。',
  '他们明白这意味着任务完成。',
  '旁白继续说明这意味着剧情进入下一阶段。',
].join('\n')
const repeatedSummaryQuality = evaluateLiteraryQuality(repeatedSummaryText)
assert(repeatedSummaryQuality.metrics.summaryHits >= 4, 'repeated summary markers must be counted')
assert(repeatedSummaryQuality.issues.some((issue) => issue.code === 'summary_tone'))

const interrogationDenialScene = [
  '审讯室的灯压在周岑额角，冷汗顺着鬓边落下。',
  '林遥把提货单推过去：“旧码头十七号仓库，你签的字。”',
  '周岑看了一眼，立刻移开视线：“我不记得了。”',
  '“不记得？”她俯身逼近，“你刚才还没看日期，就知道这是去年的单子。”',
  '他喉结动了一下。她忽然明白，他不是忘了，是在替谁拖时间。',
].join('\n')
const denialQuality = evaluateLiteraryQuality(interrogationDenialScene)
assert.equal(denialQuality.issues.some((issue) => issue.code === 'low_dialogue_conflict'), false)
assert.equal(denialQuality.issues.some((issue) => issue.code === 'missing_emotional_turn'), false)

const nonDocumentaryConflictScene = [
  '四面窗全封着，空气闷得像被拧干了最后一丝风。',
  '许砚把名单推过去：“谁动的手？”',
  '夏弦指尖停在第七页残根上：“是我撕的。”',
  '他忽然明白，她不是挑衅，是在挡掉清洗名单。',
].join('\n')
const nonDocumentaryQuality = evaluateLiteraryQuality(nonDocumentaryConflictScene)
assert.equal(nonDocumentaryQuality.issues.some((issue) => issue.code === 'documentary_tone'), false)
assert.equal(nonDocumentaryQuality.issues.some((issue) => issue.code === 'summary_tone'), false)
assert.equal(nonDocumentaryQuality.issues.some((issue) => issue.code === 'low_dialogue_conflict'), false)

const chaseConflictScene = [
  '雨夜天桥在脚下震动，桥下货车的油味被风卷上来。',
  '白澈把短刃压低：“站住。”',
  '黑衣人回头，声音被雨切碎：“想活就继续跑。”',
  '他忽然明白，对方不是逃，是把他从爆炸路线里拽出去。',
].join('\n')
const chaseConflictQuality = evaluateLiteraryQuality(chaseConflictScene)
assert.equal(chaseConflictQuality.issues.some((issue) => issue.code === 'low_dialogue_conflict'), false)

console.log('NarrativeVoiceContract + SceneExecutionContract Phase 2 no-model fixtures passed')
