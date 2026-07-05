import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import {
  buildNarrativeVoiceContractV2,
  formatNarrativeVoiceContractForPrompt
} from '../frontend/src/utils/narrativeVoiceContract.js'
import {
  buildSceneExecutionCard,
  formatSceneExecutionCardForPrompt
} from '../frontend/src/utils/sceneExecutionContract.js'
import {
  evaluateLiteraryQuality
} from '../frontend/src/utils/literaryQualityEvaluator.js'
import {
  buildDraftSystemPrompt
} from '../frontend/src/prompts/chapterDraftPrompt.js'

const OUT_DIR = path.resolve('tmp/realistic-flow-qa')
const OUT_JSON = path.join(OUT_DIR, 'offline-narrative-quality-regression-phase2-1.json')
const OUT_REPORT = path.join(OUT_DIR, 'offline-narrative-quality-regression-phase2-1-report.md')

export const PHASE21_SCENE_FIXTURES = [
  {
    id: 'interrogation-negotiation',
    category: 'interrogation_negotiation',
    title: '审讯/谈判',
    futureSecret: '顾闻舟是幕后账本的真正买家',
    futureLeakRiskTerms: ['顾闻舟', '账本', '买家'],
    futureLeakCriticalTerms: ['顾闻舟'],
    chapterGoal: {
      goal: '让林遥在审讯室里逼周岑承认港口账本仍在旧码头。',
      conflict: '林遥 vs 周岑',
      emotionalTurn: '林遥从压着怒意试探，转为意识到周岑是在保护另一个人。',
      stopPoint: '周岑只说出账本在旧码头三号仓，不说出买家。'
    },
    facts: ['林遥已经拿到旧码头的半张提货单。', '周岑知道港口账本的去向。'],
    sceneSeed: {
      protagonist: '林遥',
      opponent: '周岑',
      directQuestion: '你不是忘了账本，你是在替谁拖时间',
      deflection: '别再问了，再问下去你也会被拖进去',
      turnRecognition: '他不是挑衅，是在保护另一个人。',
      environmentalPressure: '审讯室的日光灯和录音笔红点'
    }
  },
  {
    id: 'conflict-dialogue',
    category: 'conflict_dialogue',
    title: '冲突对白',
    futureSecret: '夏弦已经把盟约原件交给敌方',
    futureLeakRiskTerms: ['夏弦', '盟约原件', '敌方'],
    futureLeakCriticalTerms: ['敌方', '外流'],
    chapterGoal: {
      goal: '让许砚在临时会议上逼夏弦承认她删掉了联盟名单的一页。',
      conflict: '许砚 vs 夏弦',
      emotionalTurn: '许砚从公开指控，转为意识到夏弦删页是在替队伍挡一次清洗。',
      stopPoint: '夏弦承认删页，但不说盟约原件已经外流。'
    },
    facts: ['会议桌上只剩半份联盟名单。', '许砚发现第七页被人为撕走。'],
    sceneSeed: {
      protagonist: '许砚',
      opponent: '夏弦',
      directQuestion: '第七页不是丢了，是你撕的，对不对',
      deflection: '你现在逼我，只会让所有人都死得更快',
      turnRecognition: '她不是背叛会议，是在替队伍挡下清洗名单。',
      environmentalPressure: '会议室玻璃墙外的警戒灯'
    }
  },
  {
    id: 'chase-action-burst',
    category: 'chase_action_burst',
    title: '追逐/动作爆发',
    futureSecret: '追逐者沈阙其实是内线保护人',
    futureLeakRiskTerms: ['沈阙', '内线', '保护人'],
    futureLeakCriticalTerms: ['沈阙', '内线', '保护人'],
    chapterGoal: {
      goal: '让白澈在雨夜天桥追上黑衣追逐者，夺回装着芯片的腕包。',
      conflict: '白澈 vs 黑衣追逐者',
      emotionalTurn: '白澈从把对方当敌人，转为发现对方故意把他引离爆炸路线。',
      stopPoint: '白澈夺回腕包，但不能知道追逐者真实身份。'
    },
    facts: ['腕包里有一枚烧焦边缘的芯片。', '天桥下方的货车油箱已经漏油。'],
    sceneSeed: {
      protagonist: '白澈',
      opponent: '黑衣追逐者',
      directQuestion: '你到底把我往哪儿引',
      deflection: '别停，想活就继续跑',
      turnRecognition: '对方不是逃，是把他从爆炸路线里拽出去。',
      environmentalPressure: '雨夜天桥、湿滑扶手和下方漏油货车'
    }
  },
  {
    id: 'intimate-relationship-crack',
    category: 'intimate_relationship裂隙',
    title: '亲密关系裂隙',
    futureSecret: '闻笙已经签下离开城市的调令',
    futureLeakRiskTerms: ['闻笙', '调令', '离开城市'],
    futureLeakCriticalTerms: ['调令'],
    chapterGoal: {
      goal: '让陆知白在清晨厨房里发现闻笙藏起了两人的合照。',
      conflict: '陆知白 vs 闻笙',
      emotionalTurn: '陆知白从质问她变心，转为意识到她在准备独自承担风险。',
      stopPoint: '闻笙承认要离开一段时间，但不说调令已经签好。'
    },
    facts: ['合照从冰箱门上消失，只留下褪色磁贴。', '闻笙昨夜没有回卧室。'],
    sceneSeed: {
      protagonist: '陆知白',
      opponent: '闻笙',
      directQuestion: '照片不是自己掉的，你为什么藏起来',
      deflection: '别问了，你知道得越少越安全',
      turnRecognition: '她不是想切断关系，是想把危险从他身边移开。',
      environmentalPressure: '清晨厨房、冷掉的粥和冰箱门上的空白磁贴'
    }
  },
  {
    id: 'pre-reveal-night',
    category: 'pre_reveal_night',
    title: '信息揭露前夜',
    futureSecret: '档案盒里的失踪者就是主角父亲',
    futureLeakRiskTerms: ['档案盒', '失踪者', '父亲'],
    futureLeakCriticalTerms: ['失踪者', '父亲'],
    chapterGoal: {
      goal: '让沈微在档案室前夜发现编号被调换，逼管理员承认有人来过。',
      conflict: '沈微 vs 档案管理员',
      emotionalTurn: '沈微从以为管理员失职，转为意识到管理员在替她拖延开盒时间。',
      stopPoint: '管理员承认有人调换编号，但不说档案盒真实身份。'
    },
    facts: ['档案室 4B 柜的编号贴被重新贴过。', '沈微手里有一枚缺角的旧钥匙。'],
    sceneSeed: {
      protagonist: '沈微',
      opponent: '档案管理员',
      directQuestion: '4B 的编号不是旧损，是昨晚刚换过',
      deflection: '你今晚不能打开那个盒子',
      turnRecognition: '管理员不是拦她查案，是怕她现在承受不了答案。',
      environmentalPressure: '午夜档案室、潮湿纸味和忽明忽暗的感应灯'
    }
  },
  {
    id: 'post-battle-failure-aftermath',
    category: 'post_battle_failure_aftermath',
    title: '战后/失败余波',
    futureSecret: '牺牲的副队长其实留下了撤退密码',
    futureLeakRiskTerms: ['副队长', '撤退密码'],
    futureLeakCriticalTerms: ['撤退密码'],
    chapterGoal: {
      goal: '让姜朔在废墟里面对失败清点，逼自己承认这次突袭是他判断错了。',
      conflict: '姜朔 vs 剩余队员秦澜',
      emotionalTurn: '姜朔从用命令压住愧疚，转为承认自己错判害队伍失去副队长。',
      stopPoint: '姜朔决定回收遗留装备，但不能发现撤退密码。'
    },
    facts: ['突袭失败后只剩三名队员返回。', '副队长的通讯器碎在废墟里。'],
    sceneSeed: {
      protagonist: '姜朔',
      opponent: '秦澜',
      directQuestion: '别再说整队，是你判断错了，对不对',
      deflection: '现在不是追责的时候',
      turnRecognition: '他不是没时间难过，是不敢承认命令害死了人。',
      environmentalPressure: '战后废墟、烧焦通讯器和远处未熄的火'
    }
  }
].map(fixture => ({
  ...fixture,
  chapterNum: 21,
  currentStageCreativeContext: {
    writableFacts: fixture.facts.map((text, index) => ({
      text,
      sourceChapterNum: 20,
      sourceVersionId: `fixture-final-${fixture.id}-${index + 1}`,
      commitStatus: 'committed'
    })),
    stageBoundary: {
      stopPoint: fixture.chapterGoal.stopPoint
    }
  },
  stateAuthority: {
    facts: fixture.facts.map((text, index) => ({
      text,
      sourceChapterNum: 20,
      sourceVersionId: `fixture-final-${fixture.id}-${index + 1}`,
      commitStatus: 'committed'
    }))
  },
  creativeStageContract: {
    allowedFacts: fixture.facts,
    stopPoint: fixture.chapterGoal.stopPoint,
    forbiddenDirections: ['不能公开后续未开放身份、真相或路线。']
  },
  guardSnapshot: {
    futureRoadmap: `后续章节才揭露：${fixture.futureSecret}。`
  },
  wordTarget: { target: 620, min: 480, max: 780, hardMin: 380, hardMax: 900 }
}))

const MODEL_PARAMS = {
  temperature: 0.7,
  top_p: 0.9,
  max_tokens: 850
}

function issueCodesBySeverity(issues, severity) {
  return issues
    .filter(issue => severity === 'blocking' ? issue.severity === 'blocking' : issue.severity !== 'blocking')
    .map(issue => issue.code)
}

export function detectFutureLeak(fixture, text) {
  const content = String(text || '')
  const riskTerms = Array.isArray(fixture.futureLeakRiskTerms)
    ? fixture.futureLeakRiskTerms.filter(Boolean)
    : []
  const criticalTerms = Array.isArray(fixture.futureLeakCriticalTerms)
    ? fixture.futureLeakCriticalTerms.filter(Boolean)
    : riskTerms
  const matchedRiskTerms = riskTerms.filter(term => content.includes(term))
  const matchedCriticalTerms = criticalTerms.filter(term => content.includes(term))
  const exactSecretLeak = content.includes(fixture.futureSecret)
  const futureLeakRisk = exactSecretLeak || matchedCriticalTerms.length > 0
  return {
    exactSecretLeak,
    futureLeakRisk,
    riskTerms,
    criticalTerms,
    matchedRiskTerms,
    matchedCriticalTerms,
    checkMode: 'exact-secret-or-risk-terms'
  }
}

function summarizeOutput(text, fixture) {
  const content = String(text || '')
  const quality = evaluateLiteraryQuality(content)
  const futureLeak = detectFutureLeak(fixture, content)
  const issues = quality.issues.map(issue => ({
    code: issue.code,
    severity: issue.severity,
    message: issue.message
  }))
  return {
    chars: content.length,
    exactFutureSecretLeak: futureLeak.exactSecretLeak,
    futureLeakRisk: futureLeak.futureLeakRisk,
    futureLeakRiskTerms: futureLeak.matchedCriticalTerms,
    futureLeakObservedTerms: futureLeak.matchedRiskTerms,
    futureLeakCheckMode: futureLeak.checkMode,
    leakedFutureSecret: futureLeak.exactSecretLeak || futureLeak.futureLeakRisk,
    qualityScore: quality.score,
    passedEvaluator: quality.passed,
    passRule: 'passedEvaluator is true only when qualityScore >= 70 and blockingIssueCodes is empty; warningIssueCodes may still be present.',
    issues,
    issueCodes: issues.map(issue => issue.code),
    blockingIssueCodes: issueCodesBySeverity(issues, 'blocking'),
    warningIssueCodes: issueCodesBySeverity(issues, 'warning'),
    signals: {
      dialogueLines: quality.metrics.dialogueLines,
      conflictDialogueLines: quality.metrics.conflictDialogueLines,
      hasEmotionalTurn: quality.metrics.hasEmotionalTurn,
      hasShortInteriority: quality.metrics.hasInnerThought,
      hasFaceVoice: quality.metrics.hasFaceVoice,
      hasEnvironmentalPressure: quality.metrics.hasEnvironment,
      hasActionExpression: quality.metrics.hasAction,
      documentaryHits: quality.metrics.documentaryHits,
      summaryHits: quality.metrics.summaryHits
    },
    excerpt: content.replace(/\s+/g, ' ').trim().slice(0, 320)
  }
}

function buildFixtureContext(fixture) {
  const context = {
    chapterNum: fixture.chapterNum,
    chapterGoal: fixture.chapterGoal,
    currentStageCreativeContext: fixture.currentStageCreativeContext,
    stateAuthority: fixture.stateAuthority,
    creativeStageContract: fixture.creativeStageContract,
    guardSnapshot: fixture.guardSnapshot,
    wordTarget: fixture.wordTarget
  }
  context.narrativeVoiceContract = buildNarrativeVoiceContractV2({
    styleBible: ['节奏快，场景短促，少描述多动作，对话简洁。']
  })
  context.sceneExecutionCard = buildSceneExecutionCard(context)
  return context
}

export function buildOldPromptForFixture(fixture) {
  return [
    '你是一位长篇小说正文生成作者。请直接输出正文。',
    '## 写作方法（AI 痕迹源头预防）',
    '- 避免机械句式、避免重复动作、避免说明书式设定。',
    '- 输出前静默自检，确保没有模板化痕迹。',
    '## 写作质量方向',
    '- 人物代入感优先；信息释放尽量落在证据、失败尝试、道具反应、关系变化或行动后果上。',
    '- 节奏快，场景短促，少描述多动作，对话简洁。',
    `## 场景类型\n${fixture.title}`,
    `## 本章目标\n${fixture.chapterGoal.goal}`,
    `## 冲突\n${fixture.chapterGoal.conflict}`,
    `## 停靠点\n${fixture.chapterGoal.stopPoint}`,
    '## guardSnapshot（错误示例：本段不应进入 creative context）',
    `未来路线：${fixture.guardSnapshot.futureRoadmap}`,
    '请写 450-650 字短场景，只输出正文，不要标题、解释、小纲或 Markdown。'
  ].join('\n\n')
}

export function buildSceneCardPromptForFixture(fixture) {
  const context = buildFixtureContext(fixture)
  const trustedFacts = fixture.currentStageCreativeContext.writableFacts
    .map(fact => `- ${fact.text}`)
    .join('\n')
  return [
    buildDraftSystemPrompt(),
    formatSceneExecutionCardForPrompt(context.sceneExecutionCard),
    formatNarrativeVoiceContractForPrompt(context.narrativeVoiceContract),
    `## 当前可信事实\n${trustedFacts}`,
    [
      '## 场景执行锚点（合成 QA）',
      `- 必写冲突对白之一：${fixture.sceneSeed.directQuestion}`,
      `- 对方回避/反击方向：${fixture.sceneSeed.deflection}`,
      `- 情绪转折落点：${fixture.sceneSeed.turnRecognition}`,
      `- 环境压力锚点：${fixture.sceneSeed.environmentalPressure}`
    ].join('\n'),
    `## 离线 QA 场景类型\n${fixture.title}`,
    '请写 450-650 字短场景，只输出正文，不要标题、解释、小纲或 Markdown。',
    '必须包含：至少两轮直接引号对白；一次情绪转折；一处短内心；面部/语气/环境压力；动作必须改变意图、关系或代价。',
    '不得越过 Scene Execution Card 的停靠点。'
  ].join('\n\n')
}

export function evaluateOfflineRegressionPair({ fixture, oldOutput, newOutput }) {
  const oldSummary = summarizeOutput(oldOutput, fixture)
  const newSummary = summarizeOutput(newOutput, fixture)
  const newPromptRegressed = Boolean(
    newSummary.leakedFutureSecret ||
    (oldSummary.passedEvaluator && !newSummary.passedEvaluator) ||
    (newSummary.qualityScore + 10 < oldSummary.qualityScore) ||
    (newSummary.blockingIssueCodes.length > oldSummary.blockingIssueCodes.length)
  )
  return {
    fixtureId: fixture.id,
    category: fixture.category,
    title: fixture.title,
    futureSecretLabel: fixture.futureSecret,
    oldPrompt: oldSummary,
    newPrompt: newSummary,
    comparison: {
      scoreDelta: newSummary.qualityScore - oldSummary.qualityScore,
      newPromptRegressed,
      newPromptAvoidedFutureSecret: !newSummary.leakedFutureSecret,
      oldPromptLeakedFutureSecret: oldSummary.leakedFutureSecret,
      newPromptHasNoBlockingIssues: newSummary.blockingIssueCodes.length === 0
    }
  }
}

function countWhere(items, predicate) {
  return items.filter(predicate).length
}

function buildSummary(results) {
  return {
    fixtureCount: results.length,
    oldPromptPasses: countWhere(results, item => item.oldPrompt.passedEvaluator),
    newPromptPasses: countWhere(results, item => item.newPrompt.passedEvaluator),
    oldPromptFutureLeaks: countWhere(results, item => item.oldPrompt.leakedFutureSecret),
    newPromptFutureLeaks: countWhere(results, item => item.newPrompt.leakedFutureSecret),
    newPromptRegressions: countWhere(results, item => item.comparison.newPromptRegressed),
    averageOldScore: results.length
      ? Math.round(results.reduce((sum, item) => sum + item.oldPrompt.qualityScore, 0) / results.length)
      : 0,
    averageNewScore: results.length
      ? Math.round(results.reduce((sum, item) => sum + item.newPrompt.qualityScore, 0) / results.length)
      : 0,
    newPromptOverallNonRegression: results.length > 0 &&
      countWhere(results, item => item.comparison.newPromptRegressed) === 0 &&
      countWhere(results, item => item.newPrompt.leakedFutureSecret) === 0
  }
}

export function buildPhase21RegressionPayload({
  provider,
  fixtureResults,
  status = 'completed',
  mode = 'offline-model'
}) {
  const results = fixtureResults || []
  return {
    schemaVersion: 'offline-narrative-quality-regression-phase2-1-v1',
    timestamp: new Date().toISOString(),
    status,
    mode,
    preferredModelRequested: '联通云-DeepSeek-V4-Flash',
    reasonForFallback: provider?.reasonForFallback || '',
    provider,
    fixtureCoverage: PHASE21_SCENE_FIXTURES.map(fixture => ({
      id: fixture.id,
      category: fixture.category,
      title: fixture.title,
      hasTrustedFacts: fixture.currentStageCreativeContext.writableFacts.every(fact => fact.commitStatus === 'committed'),
      conflict: fixture.chapterGoal.conflict,
      emotionalTurn: fixture.chapterGoal.emotionalTurn,
      stopPoint: fixture.chapterGoal.stopPoint,
      hasGuardOnlyFutureSecret: Boolean(fixture.guardSnapshot.futureRoadmap && fixture.futureSecret)
    })),
    summary: buildSummary(results),
    results
  }
}

function validateSummary(label, summary) {
  if (!Array.isArray(summary.blockingIssueCodes)) throw new Error(`${label}.blockingIssueCodes must be an array`)
  if (!Array.isArray(summary.warningIssueCodes)) throw new Error(`${label}.warningIssueCodes must be an array`)
  if (summary.exactFutureSecretLeak !== undefined && typeof summary.exactFutureSecretLeak !== 'boolean') {
    throw new Error(`${label}.exactFutureSecretLeak must be boolean when present`)
  }
  if (summary.futureLeakRisk !== undefined && typeof summary.futureLeakRisk !== 'boolean') {
    throw new Error(`${label}.futureLeakRisk must be boolean when present`)
  }
  if (summary.futureLeakRiskTerms !== undefined && !Array.isArray(summary.futureLeakRiskTerms)) {
    throw new Error(`${label}.futureLeakRiskTerms must be an array when present`)
  }
  if (
    summary.exactFutureSecretLeak !== undefined &&
    summary.futureLeakRisk !== undefined &&
    summary.leakedFutureSecret !== (summary.exactFutureSecretLeak || summary.futureLeakRisk)
  ) {
    throw new Error(`${label}.leakedFutureSecret must summarize exactFutureSecretLeak || futureLeakRisk`)
  }
  if (summary.passedEvaluator && summary.blockingIssueCodes.length) {
    throw new Error(`${label}.passedEvaluator cannot be true with blocking issues`)
  }
  const expectedPassed = Number(summary.qualityScore || 0) >= 70 && summary.blockingIssueCodes.length === 0
  if (summary.passedEvaluator !== expectedPassed) {
    throw new Error(`${label}.passedEvaluator must equal qualityScore>=70 && no blocking issues`)
  }
}

export function validateOfflineRegressionPayload(payload) {
  if (!payload || payload.schemaVersion !== 'offline-narrative-quality-regression-phase2-1-v1') {
    throw new Error('Invalid Phase 2.1 regression payload schemaVersion')
  }
  if (payload.status !== 'completed') return true
  if (payload.results.length !== 6) throw new Error('Phase 2.1 regression requires six fixture results')
  const categories = payload.results.map(item => item.category)
  for (const fixture of PHASE21_SCENE_FIXTURES) {
    if (!categories.includes(fixture.category)) throw new Error(`Missing fixture category ${fixture.category}`)
  }
  for (const result of payload.results) {
    validateSummary(`${result.fixtureId}.oldPrompt`, result.oldPrompt)
    validateSummary(`${result.fixtureId}.newPrompt`, result.newPrompt)
    const expectedRegressed = Boolean(
      result.newPrompt.leakedFutureSecret ||
      (result.oldPrompt.passedEvaluator && !result.newPrompt.passedEvaluator) ||
      (result.newPrompt.qualityScore + 10 < result.oldPrompt.qualityScore) ||
      (result.newPrompt.blockingIssueCodes.length > result.oldPrompt.blockingIssueCodes.length)
    )
    if (result.comparison.newPromptRegressed !== expectedRegressed) {
      throw new Error(`${result.fixtureId}.comparison.newPromptRegressed inconsistent with prompt summaries`)
    }
  }
  const summary = payload.summary
  const expectedSummary = buildSummary(payload.results)
  for (const [key, expectedValue] of Object.entries(expectedSummary)) {
    if (summary[key] !== expectedValue) {
      throw new Error(`summary.${key} mismatch`)
    }
  }
  return true
}

function issueText(codes) {
  return codes?.length ? codes.join(',') : 'none'
}

export function buildOfflineRegressionReport(payload) {
  validateOfflineRegressionPayload(payload)
  const lines = [
    '# Offline Narrative Quality Regression Phase 2.1 Report',
    '',
    'Status: offline regression completed with synthetic fixtures; no live chapter chain or DB writes.',
    '',
    '## Scope Guard',
    '- Did not start backend/frontend dev server, runner, or page.goto.',
    '- Did not run formal chapter generation/finalization chain.',
    '- Did not write real DB data or execute migrations/cleanup.',
    '- Did not restore LongformBrowser or run #98/#99/#50.',
    '- Did not save model output as project正文、小纲、beat plan, or DB state.',
    '- Did not enter Phase 3 provider adapter work.',
    '',
    '## Provider',
    `preferredModelRequested=${payload.preferredModelRequested}`,
    `providerName=${payload.provider?.name || 'unknown'}`,
    `providerModel=${payload.provider?.model || 'unknown'}`,
    `mode=${payload.mode}`,
    `reasonForFallback=${payload.reasonForFallback || 'none'}`,
    '',
    '## Summary',
    `fixtureCount=${payload.summary.fixtureCount}`,
    `averageOldScore=${payload.summary.averageOldScore}`,
    `averageNewScore=${payload.summary.averageNewScore}`,
    `oldPromptPasses=${payload.summary.oldPromptPasses}`,
    `newPromptPasses=${payload.summary.newPromptPasses}`,
    `oldPromptFutureLeaks=${payload.summary.oldPromptFutureLeaks}`,
    `newPromptFutureLeaks=${payload.summary.newPromptFutureLeaks}`,
    `newPromptRegressions=${payload.summary.newPromptRegressions}`,
    `newPromptOverallNonRegression=${payload.summary.newPromptOverallNonRegression}`,
    'futureLeakDefinition=exactFutureSecretLeak_or_futureLeakRiskTerms',
    '',
    '## Fixture Coverage',
    '| id | category | trusted facts | conflict | emotional turn | stop point | guard-only secret |',
    '| --- | --- | --- | --- | --- | --- | --- |',
    ...payload.fixtureCoverage.map(fixture => `| ${fixture.id} | ${fixture.category} | ${fixture.hasTrustedFacts} | ${fixture.conflict} | ${fixture.emotionalTurn} | ${fixture.stopPoint} | ${fixture.hasGuardOnlyFutureSecret} |`),
    '',
    '## A/B Results',
    '| fixture | old score/pass/issues/leak | new score/pass/issues/leak | delta | regressed |',
    '| --- | --- | --- | --- | --- |'
  ]
  for (const result of payload.results) {
    lines.push(`| ${result.category} | oldPrompt.qualityScore=${result.oldPrompt.qualityScore}; oldPrompt.passedEvaluator=${result.oldPrompt.passedEvaluator}; oldPrompt.blockingIssueCodes=${issueText(result.oldPrompt.blockingIssueCodes)}; oldPrompt.warningIssueCodes=${issueText(result.oldPrompt.warningIssueCodes)}; oldPrompt.exactFutureSecretLeak=${Boolean(result.oldPrompt.exactFutureSecretLeak)}; oldPrompt.futureLeakRisk=${Boolean(result.oldPrompt.futureLeakRisk)}; oldPrompt.futureLeakRiskTerms=${issueText(result.oldPrompt.futureLeakRiskTerms)}; oldPrompt.leakedFutureSecret=${result.oldPrompt.leakedFutureSecret} | newPrompt.qualityScore=${result.newPrompt.qualityScore}; newPrompt.passedEvaluator=${result.newPrompt.passedEvaluator}; newPrompt.blockingIssueCodes=${issueText(result.newPrompt.blockingIssueCodes)}; newPrompt.warningIssueCodes=${issueText(result.newPrompt.warningIssueCodes)}; newPrompt.exactFutureSecretLeak=${Boolean(result.newPrompt.exactFutureSecretLeak)}; newPrompt.futureLeakRisk=${Boolean(result.newPrompt.futureLeakRisk)}; newPrompt.futureLeakRiskTerms=${issueText(result.newPrompt.futureLeakRiskTerms)}; newPrompt.leakedFutureSecret=${result.newPrompt.leakedFutureSecret} | scoreDelta=${result.comparison.scoreDelta} | newPromptRegressed=${result.comparison.newPromptRegressed} |`)
  }
  const reviewLines = payload.review
    ? [
        `Fresh review subthread: ${payload.review.threadId}`,
        `Critical=${payload.review.critical || 'None'}`,
        `Important=${payload.review.important || 'None'}`,
        `Conclusion=${payload.review.conclusion || 'No additional conclusion recorded.'}`
      ]
    : ['Pending fresh read-only review.']
  const verificationLines = Array.isArray(payload.verification?.commands) && payload.verification.commands.length
    ? [
        '',
        '## Verification',
        ...payload.verification.commands.map(item => `- ${item.command}: ${item.result}`)
      ]
    : []
  lines.push(
    '',
    '## Interpretation',
    payload.summary.newPromptOverallNonRegression
      ? 'Current sample supports architecture usability: new Scene Card prompt did not regress overall, did not trigger exact/risk-term future leak checks, and stayed within current-stage boundaries.'
      : 'Current sample found at least one regression or leak; treat Phase 2.1 as not ready for clean-project/live canary until investigated.',
    '',
    '## Evidence Contract',
    '- `tmp/test_offline_narrative_quality_regression_phase2_1.mjs` checks fixture coverage, prompt boundary, payload validity, and label-qualified report/JSON alignment.',
    '- Report conclusions are derived from JSON fields; stale summary mutations are expected to fail the evidence matcher.',
    '- Future leak checks combine exact future-secret string matching with fixture-level risk-term matching; this is deterministic QA evidence, not a claim of full semantic leak detection.',
    '',
    '## Review',
    ...reviewLines
  )
  lines.push(...verificationLines)
  return `${lines.join('\n')}\n`
}

export function assertRegressionReportMatchesJson(reportText, payload) {
  validateOfflineRegressionPayload(payload)
  if (payload.status !== 'completed') return true
  const report = String(reportText || '')
  const summaryKeys = [
    'fixtureCount',
    'averageOldScore',
    'averageNewScore',
    'oldPromptPasses',
    'newPromptPasses',
    'oldPromptFutureLeaks',
    'newPromptFutureLeaks',
    'newPromptRegressions',
    'newPromptOverallNonRegression'
  ]
  for (const key of summaryKeys) {
    const actualValue = extractSingleLineValue(report, key)
    if (actualValue !== String(payload.summary[key])) {
      throw new Error(`Report does not match regression JSON: ${key}=${actualValue} expected ${payload.summary[key]}`)
    }
  }
  if (extractSingleLineValue(report, 'futureLeakDefinition') !== 'exactFutureSecretLeak_or_futureLeakRiskTerms') {
    throw new Error('Report does not match regression JSON: futureLeakDefinition mismatch')
  }
  const coverageHeader = '| id | category | trusted facts | conflict | emotional turn | stop point | guard-only secret |'
  if (!report.includes(coverageHeader)) {
    throw new Error('Report does not include emotional turn fixture coverage')
  }
  for (const fixture of payload.fixtureCoverage) {
    const coverageRow = findSingleMarkdownRow(report, fixture.id)
    assertRowCells(
      coverageRow,
      [
        fixture.id,
        fixture.category,
        String(fixture.hasTrustedFacts),
        fixture.conflict,
        fixture.emotionalTurn,
        fixture.stopPoint,
        String(fixture.hasGuardOnlyFutureSecret)
      ],
      `fixture coverage ${fixture.id}`
    )
  }
  for (const result of payload.results) {
    const row = findSingleMarkdownRow(report, result.category)
    const cells = parseMarkdownRow(row)
    if (cells.length !== 5) {
      throw new Error(`Report does not match regression JSON: ${result.category} row has ${cells.length} cells`)
    }
    if (cells[0] !== result.category) {
      throw new Error(`Report does not match regression JSON: ${result.category} row label mismatch`)
    }
    assertKeyValueCell(cells[1], {
      'oldPrompt.qualityScore': String(result.oldPrompt.qualityScore),
      'oldPrompt.passedEvaluator': String(result.oldPrompt.passedEvaluator),
      'oldPrompt.blockingIssueCodes': issueText(result.oldPrompt.blockingIssueCodes),
      'oldPrompt.warningIssueCodes': issueText(result.oldPrompt.warningIssueCodes),
      'oldPrompt.exactFutureSecretLeak': String(Boolean(result.oldPrompt.exactFutureSecretLeak)),
      'oldPrompt.futureLeakRisk': String(Boolean(result.oldPrompt.futureLeakRisk)),
      'oldPrompt.futureLeakRiskTerms': issueText(result.oldPrompt.futureLeakRiskTerms),
      'oldPrompt.leakedFutureSecret': String(result.oldPrompt.leakedFutureSecret)
    }, `${result.category}.oldPrompt`)
    assertKeyValueCell(cells[2], {
      'newPrompt.qualityScore': String(result.newPrompt.qualityScore),
      'newPrompt.passedEvaluator': String(result.newPrompt.passedEvaluator),
      'newPrompt.blockingIssueCodes': issueText(result.newPrompt.blockingIssueCodes),
      'newPrompt.warningIssueCodes': issueText(result.newPrompt.warningIssueCodes),
      'newPrompt.exactFutureSecretLeak': String(Boolean(result.newPrompt.exactFutureSecretLeak)),
      'newPrompt.futureLeakRisk': String(Boolean(result.newPrompt.futureLeakRisk)),
      'newPrompt.futureLeakRiskTerms': issueText(result.newPrompt.futureLeakRiskTerms),
      'newPrompt.leakedFutureSecret': String(result.newPrompt.leakedFutureSecret)
    }, `${result.category}.newPrompt`)
    assertKeyValueCell(cells[3], {
      scoreDelta: String(result.comparison.scoreDelta)
    }, `${result.category}.delta`)
    assertKeyValueCell(cells[4], {
      newPromptRegressed: String(result.comparison.newPromptRegressed)
    }, `${result.category}.regressed`)
  }
  return true
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function extractSingleLineValue(report, key) {
  const pattern = new RegExp(`^${escapeRegExp(key)}=(.*)$`, 'gm')
  const matches = [...report.matchAll(pattern)]
  if (matches.length !== 1) {
    throw new Error(`Report does not match regression JSON: ${key} appears ${matches.length} times`)
  }
  return matches[0][1].trim()
}

function findSingleMarkdownRow(report, firstCell) {
  const pattern = new RegExp(`^\\| ${escapeRegExp(firstCell)} \\|.*$`, 'gm')
  const matches = [...report.matchAll(pattern)]
  if (matches.length !== 1) {
    throw new Error(`Report does not match regression JSON: row ${firstCell} appears ${matches.length} times`)
  }
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

function assertRowCells(row, expectedCells, label) {
  const cells = parseMarkdownRow(row)
  if (cells.length !== expectedCells.length) {
    throw new Error(`Report does not match ${label}: expected ${expectedCells.length} cells, got ${cells.length}`)
  }
  expectedCells.forEach((expected, index) => {
    if (cells[index] !== String(expected)) {
      throw new Error(`Report does not match ${label}: cell ${index + 1}=${cells[index]} expected ${expected}`)
    }
  })
}

function assertKeyValueCell(cell, expectedValues, label) {
  const pairs = String(cell)
    .split(';')
    .map(part => part.trim())
    .filter(Boolean)
  const actual = new Map()
  for (const pair of pairs) {
    const separator = pair.indexOf('=')
    if (separator < 1) {
      throw new Error(`Report does not match regression JSON: ${label} contains malformed token ${pair}`)
    }
    const key = pair.slice(0, separator).trim()
    const value = pair.slice(separator + 1).trim()
    if (actual.has(key)) {
      throw new Error(`Report does not match regression JSON: ${label}.${key} appears more than once`)
    }
    actual.set(key, value)
  }
  const expectedKeys = Object.keys(expectedValues)
  if (actual.size !== expectedKeys.length) {
    throw new Error(`Report does not match regression JSON: ${label} expected ${expectedKeys.length} fields, got ${actual.size}`)
  }
  for (const [key, expected] of Object.entries(expectedValues)) {
    if (!actual.has(key)) {
      throw new Error(`Report does not match regression JSON: ${label}.${key} missing`)
    }
    if (actual.get(key) !== String(expected)) {
      throw new Error(`Report does not match regression JSON: ${label}.${key}=${actual.get(key)} expected ${expected}`)
    }
  }
}

async function callChat({ apiKey, baseURL, model, prompt }) {
  const url = `${baseURL.replace(/\/+$/, '')}/chat/completions`
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model,
      messages: [{ role: 'user', content: prompt }],
      ...MODEL_PARAMS
    })
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = json?.error?.message || json?.message || res.statusText
    throw new Error(`${res.status} ${detail}`)
  }
  return json?.choices?.[0]?.message?.content || ''
}

async function writeOutputs(payload) {
  await fs.mkdir(OUT_DIR, { recursive: true })
  const report = buildOfflineRegressionReport(payload)
  assertRegressionReportMatchesJson(report, payload)
  await fs.writeFile(OUT_JSON, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
  await fs.writeFile(OUT_REPORT, report, 'utf8')
}

async function runOfflineRegressionCli() {
  const unicomKey = process.env.UNICOM_DEEPSEEK_API_KEY || process.env.UNICOM_API_KEY || ''
  const unicomBaseURL = process.env.UNICOM_DEEPSEEK_BASE_URL || process.env.UNICOM_BASE_URL || ''
  const fallbackKey = process.env.DEEPSEEK_API_KEY || process.env.CRAZYCAP_PLANNING_PROVIDER_API_KEY || ''
  const fallbackBaseURL = process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com/v1'
  const useUnicom = Boolean(unicomKey && unicomBaseURL)
  const provider = useUnicom
    ? {
      name: '联通云-DeepSeek-V4-Flash',
      model: process.env.UNICOM_DEEPSEEK_MODEL || 'DeepSeek-V4-Flash',
      baseURL: unicomBaseURL,
      parameters: MODEL_PARAMS,
      reasonForFallback: ''
    }
    : {
      name: 'DeepSeek fallback',
      model: process.env.CRAZYCAP_PLANNING_PROVIDER_MODEL || process.env.OPENCLAW_MODEL_REF || 'deepseek-v4-pro',
      baseURL: fallbackBaseURL,
      parameters: MODEL_PARAMS,
      reasonForFallback: '当前线程未暴露可用的联通云未脱敏 baseURL/apiKey；使用环境中可见的 DeepSeek fallback key 做离线 QA。'
    }
  const apiKey = useUnicom ? unicomKey : fallbackKey

  if (!apiKey) {
    const skipped = buildPhase21RegressionPayload({
      provider,
      fixtureResults: [],
      status: 'skipped',
      mode: 'offline-model'
    })
    skipped.error = 'No usable model API key found.'
    await fs.mkdir(OUT_DIR, { recursive: true })
    await fs.writeFile(OUT_JSON, `${JSON.stringify(skipped, null, 2)}\n`, 'utf8')
    await fs.writeFile(OUT_REPORT, '# Offline Narrative Quality Regression Phase 2.1 Report\n\nStatus: skipped; no usable offline model key found.\n', 'utf8')
    console.log(`offline regression skipped: missing API key; wrote ${OUT_JSON}`)
    return
  }

  const fixtureResults = []
  for (const fixture of PHASE21_SCENE_FIXTURES) {
    const oldOutput = await callChat({
      apiKey,
      baseURL: provider.baseURL,
      model: provider.model,
      prompt: buildOldPromptForFixture(fixture)
    })
    const newOutput = await callChat({
      apiKey,
      baseURL: provider.baseURL,
      model: provider.model,
      prompt: buildSceneCardPromptForFixture(fixture)
    })
    fixtureResults.push(evaluateOfflineRegressionPair({ fixture, oldOutput, newOutput }))
  }

  const payload = buildPhase21RegressionPayload({
    provider,
    fixtureResults,
    status: 'completed',
    mode: 'offline-model'
  })
  validateOfflineRegressionPayload(payload)
  await writeOutputs(payload)
  console.log(`offline regression completed with ${provider.name} / ${provider.model}; wrote ${OUT_JSON} and ${OUT_REPORT}`)
}

const isCliRun = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href
if (isCliRun) {
  runOfflineRegressionCli().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
