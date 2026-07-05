import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

import realCorpusLibrary from '../frontend/src/data/realCorpusExperienceCards.v3.json' with { type: 'json' }
import {
  detectRealCorpusPromptLeakage,
  formatRealCorpusExperienceForPrompt,
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

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT = path.resolve(__dirname, '..')
const OUT_JSON = 'tmp/realistic-flow-qa/real-corpus-prompt-hookup-phase3-2.json'
const OUT_REPORT = 'tmp/realistic-flow-qa/real-corpus-prompt-hookup-phase3-2-report.md'
const DETERMINISTIC_GENERATED_AT = '2026-07-05T00:00:00.000Z'

const FORBIDDEN_PROMPT_PATTERN = /(sourceTitle|sourceFileHash|sourceWindowHashes|sourceAuditOnly|rawExcerpt|sourceText|sourceCardIds|guardSnapshot|futureRoadmap|stateAuthority|幕后人是|顾闻舟)/u

export const SYNTHETIC_PROMPT_HOOKUP_SCENES = [
  {
    id: 'interrogation_negotiation',
    title: '审讯/谈判',
    expectedTags: ['dialogue_conflict', 'emotion_variation', 'character_humanity'],
    futureSecret: '顾闻舟是幕后人',
    facts: ['林遥已经拿到旧码头的半张提货单。'],
    chapterGoal: {
      goal: '让林遥在审讯室里逼周岑承认他隐瞒了港口账本。',
      conflict: '林遥 vs 周岑',
      emotionalTurn: '林遥从压着怒意试探，转为意识到周岑是在保护另一个人。',
      physicalPressure: '桌上只有半张提货单和一盏忽明忽暗的灯。',
      environmentalPressure: '排风口滴水，门外脚步声越来越近。',
      stopPoint: '周岑只说出账本藏在旧码头，不说出幕后人。'
    }
  },
  {
    id: 'conflict_dialogue',
    title: '冲突对白',
    expectedTags: ['dialogue_conflict', 'character_humanity'],
    futureSecret: '旧盟友会在下一卷背叛',
    facts: ['许砚和夏弦刚从封锁线撤回，名单缺了第七页。'],
    chapterGoal: {
      goal: '让许砚逼夏弦解释为什么撕掉名单第七页。',
      conflict: '许砚 vs 夏弦',
      emotionalTurn: '许砚从认定夏弦背叛，转为发现她是在挡掉清洗名单。',
      physicalPressure: '名单残页被雨水泡软，墨迹正在散开。',
      environmentalPressure: '窗外巡逻灯扫过屋内，两人必须压低声音。',
      stopPoint: '夏弦承认撕页，但不说名单背后的清洗命令来源。'
    }
  },
  {
    id: 'chase_action_burst',
    title: '追逐/动作爆发',
    expectedTags: ['action_burst', 'aftermath', 'emotion_variation'],
    futureSecret: '追逐者其实在救主角',
    facts: ['白澈在雨夜天桥截住黑衣人，背包里有爆炸路线图。'],
    chapterGoal: {
      goal: '让白澈在追逐中夺回路线图，同时意识到对方不是单纯逃跑。',
      conflict: '白澈 vs 黑衣人',
      emotionalTurn: '白澈从追捕怒意，转为意识到黑衣人把他引离爆炸点。',
      physicalPressure: '天桥湿滑，货车灯光从脚下切过。',
      environmentalPressure: '雨声盖住倒计时蜂鸣，栏杆被撞得变形。',
      stopPoint: '白澈拿回路线图，但只知道爆炸点被改，不知道谁改的。'
    }
  },
  {
    id: 'intimate_fracture',
    title: '亲密关系裂隙',
    expectedTags: ['emotion_variation', 'character_humanity', 'scene_dwell'],
    futureSecret: '亲密对象未来会离队',
    facts: ['沈棠发现陆知远把唯一的通行章留在医馆。'],
    chapterGoal: {
      goal: '让沈棠质问陆知远为何留下通行章，两人关系出现裂痕。',
      conflict: '沈棠 vs 陆知远',
      emotionalTurn: '沈棠从被抛下的怒意，转为看见陆知远不敢说出口的亏欠。',
      physicalPressure: '通行章压在药碗旁，药汤已经凉透。',
      environmentalPressure: '医馆后门半掩，街上搜捕声靠近。',
      stopPoint: '陆知远承认留下通行章是为了让沈棠先走，但不说自己真正病情。'
    }
  },
  {
    id: 'before_reveal',
    title: '信息揭露前夜',
    expectedTags: ['setting_naturalization', 'longform_rhythm', 'scene_dwell'],
    futureSecret: '铜镜阵真正规则下章才公开',
    facts: ['铜镜阵已经连续两次让针弯折，影子方向与灯光不一致。'],
    chapterGoal: {
      goal: '让角色通过一次失败试探发现铜镜阵规则的一角。',
      conflict: '祁安 vs 铜镜阵规则',
      emotionalTurn: '祁安从想靠经验硬闯，转为承认旧办法会害死同伴。',
      physicalPressure: '第二根铜针一触门缝就弯，手背被冷光割开。',
      environmentalPressure: '屋内灯影逆着风晃，镜面里的人影慢半拍。',
      stopPoint: '祁安只确认不能碰影子，不解释完整阵法来源。'
    }
  },
  {
    id: 'failure_aftermath',
    title: '失败余波',
    expectedTags: ['aftermath', 'character_humanity', 'longform_rhythm'],
    futureSecret: '失败会引出下一卷清算',
    facts: ['小队没能救出账房，只带回烧焦的账页和一枚空印章。'],
    chapterGoal: {
      goal: '让众人在失败后处理损失、互相推责并决定下一步。',
      conflict: '林遥 vs 小队余波',
      emotionalTurn: '林遥从压住责任不谈，转为承认自己的判断让账房失踪。',
      physicalPressure: '烧焦账页一碰就碎，空印章滚到桌沿。',
      environmentalPressure: '安全屋外有人敲错三次暗号，屋内无人敢先开门。',
      stopPoint: '小队决定转查空印章来源，但不公开清算名单。'
    }
  }
]

function git(args) {
  const result = spawnSync('git', args, { cwd: ROOT, encoding: 'utf8' })
  return result.status === 0 ? result.stdout.trim() : ''
}

function hasText(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function contextForScene(scene, options = {}) {
  const context = {
    chapterNum: 31,
    chapterGoal: scene.chapterGoal,
    currentStageCreativeContext: {
      writableFacts: scene.facts.map((text, index) => ({
        text,
        sourceChapterNum: 30,
        sourceVersionId: `phase3-2-final-${scene.id}-${index + 1}`,
        commitStatus: 'committed'
      })),
      stageBoundary: {
        stopPoint: scene.chapterGoal.stopPoint
      }
    },
    stateAuthority: {
      facts: scene.facts.map((text, index) => ({
        text,
        sourceChapterNum: 30,
        sourceVersionId: `phase3-2-final-${scene.id}-${index + 1}`,
        commitStatus: 'committed'
      }))
    },
    creativeStageContract: {
      allowedFacts: scene.facts,
      stopPoint: scene.chapterGoal.stopPoint,
      forbiddenDirections: ['不能公开后续未开放身份、真相或路线。']
    },
    guardSnapshot: {
      futureRoadmap: `后续才揭露：${scene.futureSecret}`
    },
    savedBeatPlan: ['旧计划：公开后续未开放身份。'],
    wordTarget: { target: 680, min: 520, max: 860 },
    ...options
  }
  context.narrativeVoiceContract = buildNarrativeVoiceContractV2({
    styleBible: ['短场景但必须有压力、选择和情绪转折。']
  })
  context.sceneExecutionCard = buildSceneExecutionCard(context)
  return context
}

function countPattern(text, pattern) {
  return (String(text || '').match(pattern) || []).length
}

function promptSignals(prompt) {
  const source = String(prompt || '')
  return {
    dialogueConflict: countPattern(source, /对白|对话|冲突|逼问|质问|否认|潜台词/g),
    emotionalTurn: countPattern(source, /情绪转折|误判|迟疑|认定|意识到|转为/g),
    sceneDwell: countPattern(source, /环境压力|空间|灯|门|雨|窗|桌|气味|声音/g),
    characterHumanity: countPattern(source, /人物|关系|私心|顾虑|亏欠|嘴硬|害怕/g),
    settingNaturalization: countPattern(source, /设定|规则|证据|后果|试探|失败|代价/g),
    actionBurst: countPattern(source, /动作|身体|追逐|爆发|逃|撞|夺回/g),
    helperSections: countPattern(source, /Real Corpus Experience Helper/g)
  }
}

function signalScore(signals) {
  return signals.dialogueConflict +
    signals.emotionalTurn +
    signals.sceneDwell +
    signals.characterHumanity +
    signals.settingNaturalization +
    signals.actionBurst
}

function futureLeak(scene, prompt) {
  const source = String(prompt || '')
  return source.includes(scene.futureSecret) || FORBIDDEN_PROMPT_PATTERN.test(source)
}

function promptBudget(prompt, noSamplePrompt) {
  return String(prompt || '').length - String(noSamplePrompt || '').length
}

function rowForScene(scene) {
  const context = contextForScene(scene)
  const selectedCards = retrieveRealCorpusExperienceCards(context.sceneExecutionCard, realCorpusLibrary.cards, { limit: 2 })
  const helper = formatRealCorpusExperienceForPrompt(context.sceneExecutionCard, realCorpusLibrary.cards, {
    maxCards: 2,
    maxSectionChars: 900
  })
  const noSamplePrompt = buildDraftPrompt({
    ...context,
    realCorpusExperienceCards: realCorpusLibrary.cards,
    enableRealCorpusExperienceCards: false
  })
  const samplePrompt = buildDraftPrompt({
    ...context,
    realCorpusExperienceCards: realCorpusLibrary.cards,
    enableRealCorpusExperienceCards: true,
    realCorpusExperienceOptions: { maxCards: 2, maxSectionChars: 900 }
  })
  const noSampleSignals = promptSignals(noSamplePrompt)
  const sampleSignals = promptSignals(samplePrompt)
  const noSampleScore = signalScore(noSampleSignals)
  const sampleScore = signalScore(sampleSignals)
  const leakage = detectRealCorpusPromptLeakage(samplePrompt, selectedCards)
  const exactFutureLeak = futureLeak(scene, samplePrompt)
  const budgetDelta = promptBudget(samplePrompt, noSamplePrompt)
  const promptBudgetViolation = budgetDelta > 1300 || helper.length > 900
  const expectedTagHit = selectedCards.some(card => scene.expectedTags.some(tag => card.sceneFunctionTags.includes(tag)))
  const regressed = Boolean(
    leakage.detected ||
    exactFutureLeak ||
    promptBudgetViolation ||
    !expectedTagHit ||
    sampleScore < noSampleScore
  )
  return {
    id: scene.id,
    title: scene.title,
    expectedTags: scene.expectedTags,
    selectedCardCount: selectedCards.length,
    selectedCardPromptReadiness: selectedCards.map(card => card.promptReadiness),
    selectedSceneFunctionTags: [...new Set(selectedCards.flatMap(card => card.sceneFunctionTags))],
    expectedTagHit,
    helperChars: helper.length,
    promptBudgetDelta: budgetDelta,
    promptBudgetViolation,
    noSampleSignals,
    sampleSignals,
    noSampleScore,
    sampleScore,
    signalLift: sampleScore - noSampleScore,
    sourceLeak: leakage.detected,
    leakageEvidence: {
      detected: leakage.detected,
      auditFieldToken: leakage.forbiddenToken,
      nameTokenDetected: Boolean(leakage.sourceNameToken || leakage.sourceTitle)
    },
    futureLeak: exactFutureLeak,
    regressed,
    promptEvidence: {
      noSampleHasHelper: noSamplePrompt.includes('Real Corpus Experience Helper'),
      sampleHasHelper: samplePrompt.includes('Real Corpus Experience Helper'),
      sampleHasSceneExecutionCard: samplePrompt.includes('Scene Execution Card'),
      sampleHasNarrativeVoiceContract: samplePrompt.includes('Narrative Voice Contract'),
      sampleHasStopPoint: samplePrompt.includes(context.sceneExecutionCard.stopPoint)
    }
  }
}

export function buildPhase32Payload(options = {}) {
  const scenes = SYNTHETIC_PROMPT_HOOKUP_SCENES.map(rowForScene)
  const lowSignalSelectedCards = retrieveRealCorpusExperienceCards({}, realCorpusLibrary.cards, { limit: 2 }).length
  const summary = {
    sceneCount: scenes.length,
    helperScenes: scenes.filter(scene => scene.promptEvidence.sampleHasHelper).length,
    futureLeaks: scenes.filter(scene => scene.futureLeak).length,
    sourceLeaks: scenes.filter(scene => scene.sourceLeak).length,
    lowSignalSelectedCards,
    promptBudgetViolations: scenes.filter(scene => scene.promptBudgetViolation).length,
    sampleV3PromptRegressions: scenes.filter(scene => scene.regressed).length,
    averageNoSampleScore: Number((scenes.reduce((sum, scene) => sum + scene.noSampleScore, 0) / scenes.length).toFixed(2)),
    averageSampleScore: Number((scenes.reduce((sum, scene) => sum + scene.sampleScore, 0) / scenes.length).toFixed(2)),
    averageSignalLift: Number((scenes.reduce((sum, scene) => sum + scene.signalLift, 0) / scenes.length).toFixed(2))
  }
  return {
    schemaVersion: 'real-corpus-prompt-hookup-phase3-2-v1',
    status: 'completed',
    generatedAt: options.generatedAt || DETERMINISTIC_GENERATED_AT,
    branch: {
      current: git(['branch', '--show-current']),
      baseCommit: 'a326c7d',
      headCommit: git(['rev-parse', '--short', 'HEAD'])
    },
    boundary: {
      serviceStarted: false,
      realDbConnection: false,
      realProjectTouched: false,
      liveGenerationRun: false,
      projectStateWritten: false,
      modelRun: false,
      providerAdapterEntered: false,
      pushOrPrCreated: false,
      productionPromptDefaultEnabled: false
    },
    hookupDesign: {
      promptEntryPoint: 'frontend/src/prompts/chapterDraftPrompt.js buildDraftPrompt -> frontend/src/prompts/chapter.js buildChapterPrompt',
      insertionPoint: 'after Scene Execution Card and Narrative Voice Contract, before state/fact-heavy prompt sections',
      formatter: 'frontend/src/data/realCorpusExperienceCardsV3.js formatRealCorpusExperienceForPrompt',
      optInFlag: 'enableRealCorpusExperienceCards',
      cardInput: 'context.realCorpusExperienceCards',
      expressionOnly: true,
      doesNotEnterStateAuthority: true,
      defaultProductionEnabled: false
    },
    formatterBudget: {
      maxSections: 1,
      maxCardsWithoutFormalStandard: 2,
      maxCardsWithFormalStandard: 1,
      defaultMaxSectionChars: 1000,
      formalStandardMaxSectionChars: 760,
      hardMaxSectionChars: 1400
    },
    scenes,
    summary,
    modelAssistedValidation: {
      used: false,
      reason: 'Phase 3.2 request forbids model runs; deterministic no-model prompt assembly evidence is the hard gate.',
      model: null,
      temperature: null,
      top_p: null
    }
  }
}

export function validatePhase32Payload(payload) {
  if (payload.schemaVersion !== 'real-corpus-prompt-hookup-phase3-2-v1') throw new Error('invalid Phase 3.2 schemaVersion')
  for (const key of ['serviceStarted', 'realDbConnection', 'realProjectTouched', 'liveGenerationRun', 'projectStateWritten', 'modelRun', 'providerAdapterEntered', 'pushOrPrCreated']) {
    if (payload.boundary?.[key] !== false) throw new Error(`boundary.${key} must be false`)
  }
  if (payload.boundary?.productionPromptDefaultEnabled !== false) throw new Error('V3 prompt helper must not be default-enabled in production')
  if (payload.summary?.sceneCount !== 6) throw new Error('Phase 3.2 must cover six synthetic scenes')
  if (payload.summary?.helperScenes !== 6) throw new Error('all six scenes must get helper prompts')
  if (payload.summary?.futureLeaks !== 0) throw new Error('future leaks must be zero')
  if (payload.summary?.sourceLeaks !== 0) throw new Error('source leaks must be zero')
  if (payload.summary?.lowSignalSelectedCards !== 0) throw new Error('low-signal scenes must not retrieve cards')
  if (payload.summary?.promptBudgetViolations !== 0) throw new Error('prompt budget violations must be zero')
  if (payload.summary?.sampleV3PromptRegressions !== 0) throw new Error('sample V3 prompt regressions must be zero')
  if (!(payload.summary?.averageSignalLift > 0)) throw new Error('average signal lift must be positive')
  return true
}

export function buildPhase32Report(payload) {
  validatePhase32Payload(payload)
  const lines = [
    '# Real Corpus Prompt Hookup Phase 3.2 Report',
    '',
    'Status: deterministic no-live prompt assembly gate. This report does not claim live generation, real DB migration, real project regression, model validation, or production prompt default rollout.',
    '',
    '## Scope Guard',
    '- Did not start backend/frontend dev server, runner, or page.goto.',
    '- Did not run formal chapter generation/finalization chain.',
    '- Did not connect to or write a real DB.',
    '- Did not touch real project data, restore LongformBrowser, or run #98/#99/#50.',
    '- Did not run a model or enter provider/model adapter code.',
    '- Did not save model output as project body, outline, beat plan, or DB state.',
    '- Did not push or create PR.',
    '',
    '## Branch',
    `branch.current=${payload.branch.current}`,
    `branch.baseCommit=${payload.branch.baseCommit}`,
    `branch.headCommit=${payload.branch.headCommit}`,
    '',
    '## Hookup Design Audit',
    `promptEntryPoint=${payload.hookupDesign.promptEntryPoint}`,
    `insertionPoint=${payload.hookupDesign.insertionPoint}`,
    `formatter=${payload.hookupDesign.formatter}`,
    `optInFlag=${payload.hookupDesign.optInFlag}`,
    `cardInput=${payload.hookupDesign.cardInput}`,
    `expressionOnly=${payload.hookupDesign.expressionOnly}`,
    `doesNotEnterStateAuthority=${payload.hookupDesign.doesNotEnterStateAuthority}`,
    `defaultProductionEnabled=${payload.hookupDesign.defaultProductionEnabled}`,
    '',
    '## Formatter Budget',
    `budget.maxSections=${payload.formatterBudget.maxSections}`,
    `budget.maxCardsWithoutFormalStandard=${payload.formatterBudget.maxCardsWithoutFormalStandard}`,
    `budget.maxCardsWithFormalStandard=${payload.formatterBudget.maxCardsWithFormalStandard}`,
    `budget.defaultMaxSectionChars=${payload.formatterBudget.defaultMaxSectionChars}`,
    `budget.formalStandardMaxSectionChars=${payload.formatterBudget.formalStandardMaxSectionChars}`,
    '',
    '## Six-Scene Prompt Evidence',
    '| scene | selected_cards | expected_tag_hit | helper_chars | signal_lift | source_leak | future_leak | budget_violation |',
    '| --- | ---: | --- | ---: | ---: | --- | --- | --- |',
    ...payload.scenes.map(scene => `| ${scene.id} | ${scene.selectedCardCount} | ${scene.expectedTagHit} | ${scene.helperChars} | ${scene.signalLift} | ${scene.sourceLeak} | ${scene.futureLeak} | ${scene.promptBudgetViolation} |`),
    '',
    '## Summary',
    `summary.sceneCount=${payload.summary.sceneCount}`,
    `summary.helperScenes=${payload.summary.helperScenes}`,
    `summary.futureLeaks=${payload.summary.futureLeaks}`,
    `summary.sourceLeaks=${payload.summary.sourceLeaks}`,
    `summary.lowSignalSelectedCards=${payload.summary.lowSignalSelectedCards}`,
    `summary.promptBudgetViolations=${payload.summary.promptBudgetViolations}`,
    `summary.sampleV3PromptRegressions=${payload.summary.sampleV3PromptRegressions}`,
    `summary.averageNoSampleScore=${payload.summary.averageNoSampleScore}`,
    `summary.averageSampleScore=${payload.summary.averageSampleScore}`,
    `summary.averageSignalLift=${payload.summary.averageSignalLift}`,
    '',
    '## Model Assisted Validation',
    `model.used=${payload.modelAssistedValidation.used}`,
    `model.reason=${payload.modelAssistedValidation.reason}`,
    '',
    '## Remaining Risks',
    '- V3 helper is opt-in and no-live only in this phase; production rollout still needs a later gate.',
    '- No model prose sample was generated; this phase proves prompt assembly boundaries and prompt-level signals only.',
    '- Human editorial review remains recommended before default enablement.'
  ]
  return `${lines.join('\n')}\n`
}

function extractSingleLineValue(report, key) {
  const pattern = new RegExp(`^${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}=(.*)$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report key ${key} appears ${matches.length} times`)
  return matches[0][1].trim()
}

function findSingleMarkdownRow(report, firstCell) {
  const pattern = new RegExp(`^\\| ${String(firstCell).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\|.*$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report row ${firstCell} appears ${matches.length} times`)
  return matches[0][0]
}

function parseMarkdownRow(row) {
  return String(row)
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map(cell => cell.trim())
}

export function assertRealCorpusPromptHookupReportMatchesJson(reportText, payload) {
  validatePhase32Payload(payload)
  const report = String(reportText || '')
  const checks = {
    'branch.current': payload.branch.current,
    'branch.baseCommit': payload.branch.baseCommit,
    'branch.headCommit': payload.branch.headCommit,
    'promptEntryPoint': payload.hookupDesign.promptEntryPoint,
    'insertionPoint': payload.hookupDesign.insertionPoint,
    'formatter': payload.hookupDesign.formatter,
    'optInFlag': payload.hookupDesign.optInFlag,
    'cardInput': payload.hookupDesign.cardInput,
    'expressionOnly': payload.hookupDesign.expressionOnly,
    'doesNotEnterStateAuthority': payload.hookupDesign.doesNotEnterStateAuthority,
    'defaultProductionEnabled': payload.hookupDesign.defaultProductionEnabled,
    'budget.maxSections': payload.formatterBudget.maxSections,
    'budget.maxCardsWithoutFormalStandard': payload.formatterBudget.maxCardsWithoutFormalStandard,
    'budget.maxCardsWithFormalStandard': payload.formatterBudget.maxCardsWithFormalStandard,
    'budget.defaultMaxSectionChars': payload.formatterBudget.defaultMaxSectionChars,
    'budget.formalStandardMaxSectionChars': payload.formatterBudget.formalStandardMaxSectionChars,
    'summary.sceneCount': payload.summary.sceneCount,
    'summary.helperScenes': payload.summary.helperScenes,
    'summary.futureLeaks': payload.summary.futureLeaks,
    'summary.sourceLeaks': payload.summary.sourceLeaks,
    'summary.lowSignalSelectedCards': payload.summary.lowSignalSelectedCards,
    'summary.promptBudgetViolations': payload.summary.promptBudgetViolations,
    'summary.sampleV3PromptRegressions': payload.summary.sampleV3PromptRegressions,
    'summary.averageNoSampleScore': payload.summary.averageNoSampleScore,
    'summary.averageSampleScore': payload.summary.averageSampleScore,
    'summary.averageSignalLift': payload.summary.averageSignalLift,
    'model.used': payload.modelAssistedValidation.used,
    'model.reason': payload.modelAssistedValidation.reason
  }
  for (const [key, expected] of Object.entries(checks)) {
    const actual = extractSingleLineValue(report, key)
    if (actual !== String(expected)) throw new Error(`Report/JSON mismatch for ${key}: ${actual} expected ${expected}`)
  }
  for (const scene of payload.scenes) {
    const row = findSingleMarkdownRow(report, scene.id)
    const cells = parseMarkdownRow(row)
    const expected = [
      scene.id,
      scene.selectedCardCount,
      scene.expectedTagHit,
      scene.helperChars,
      scene.signalLift,
      scene.sourceLeak,
      scene.futureLeak,
      scene.promptBudgetViolation
    ].map(String)
    expected.forEach((value, index) => {
      if (cells[index] !== value) throw new Error(`Report/JSON mismatch for ${scene.id}[${index}]: ${cells[index]} expected ${value}`)
    })
  }
  return true
}

export async function runRealCorpusPromptHookupPhase32(options = {}) {
  const writeArtifacts = options.writeArtifacts === true
  const payload = buildPhase32Payload(options)
  const report = buildPhase32Report(payload)
  assertRealCorpusPromptHookupReportMatchesJson(report, payload)
  if (writeArtifacts) {
    await fs.mkdir(path.join(ROOT, 'tmp/realistic-flow-qa'), { recursive: true })
    await fs.writeFile(path.join(ROOT, OUT_JSON), `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
    await fs.writeFile(path.join(ROOT, OUT_REPORT), report, 'utf8')
  }
  return payload
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const payload = await runRealCorpusPromptHookupPhase32({ writeArtifacts: true })
  console.log(`real corpus prompt hookup phase3.2 wrote ${OUT_JSON} and ${OUT_REPORT}`)
  console.log(`sceneCount=${payload.summary.sceneCount} futureLeaks=${payload.summary.futureLeaks} sourceLeaks=${payload.summary.sourceLeaks}`)
}
