import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import {
  buildNarrativeVoiceContractV2
} from '../frontend/src/utils/narrativeVoiceContract.js'
import {
  buildSceneExecutionCard
} from '../frontend/src/utils/sceneExecutionContract.js'
import {
  evaluateLiteraryQuality
} from '../frontend/src/utils/literaryQualityEvaluator.js'
import {
  buildDraftPrompt,
  buildDraftSystemPrompt
} from '../frontend/src/prompts/chapterDraftPrompt.js'

const OUT_DIR = path.resolve('tmp/realistic-flow-qa')
const OUT_FILE = path.join(OUT_DIR, 'narrative-voice-phase2-model-validation.json')

const params = {
  temperature: 0.7,
  top_p: 0.9,
  max_tokens: 900
}

const futureSecret = '顾闻舟是幕后人'
const syntheticContext = {
  chapterNum: 12,
  chapterGoal: {
    goal: '让林遥在审讯室里逼周岑承认他隐瞒了港口账本。',
    conflict: '林遥 vs 周岑',
    emotionalTurn: '林遥从压着怒意试探，转为意识到周岑是在保护另一个人。',
    stopPoint: '周岑只说出账本藏在旧码头，不说出幕后人。'
  },
  currentStageCreativeContext: {
    writableFacts: [
      { text: '林遥已经拿到旧码头的半张提货单。', sourceChapterNum: 11, commitStatus: 'committed' }
    ],
    stageBoundary: {
      stopPoint: '本章只能逼出旧码头线索，不能公开幕后人。'
    }
  },
  stateAuthority: {
    facts: [
      { text: '林遥已经拿到旧码头的半张提货单。', sourceChapterNum: 11, commitStatus: 'committed' }
    ]
  },
  creativeStageContract: {
    allowedFacts: ['林遥已经拿到旧码头的半张提货单。'],
    stopPoint: '本章只能逼出旧码头线索，不能公开幕后人。',
    forbiddenDirections: ['不能公开幕后人姓名。']
  },
  guardSnapshot: {
    futureRoadmap: `未来第十五章才揭露${futureSecret}。`
  },
  wordTarget: { target: 700, min: 550, max: 850, hardMin: 450, hardMax: 1000 }
}

syntheticContext.narrativeVoiceContract = buildNarrativeVoiceContractV2({
  styleBible: ['节奏快，场景短促，少描述多动作，对话简洁。']
})
syntheticContext.sceneExecutionCard = buildSceneExecutionCard(syntheticContext)

const oldPrompt = [
  '你是一位长篇小说正文生成作者。请直接输出正文。',
  '## 写作方法（AI 痕迹源头预防）',
  '- 避免机械句式、避免重复动作、避免说明书式设定。',
  '## 写作质量方向',
  '- 人物代入感优先；信息释放尽量落在证据、失败尝试、道具反应、关系变化或行动后果上。',
  '- 输出前静默自检：结尾模板、工具人、信息倾倒和段首重复点名如果明显出现，先自然调整。',
  '## 项目风格备注',
  '节奏快，场景短促，少描述多动作，对话简洁。',
  '## 本章目标',
  syntheticContext.chapterGoal.goal,
  '## guardSnapshot（错误示例：本段不应进入 creative context）',
  `未来路线：未来第十五章才揭露${futureSecret}。`,
  '请写 500-700 字审讯室场景，只输出正文，不要解释。'
].join('\n\n')

const newPrompt = [
  buildDraftSystemPrompt(),
  buildDraftPrompt(syntheticContext),
  '请写 500-700 字审讯室场景，只输出正文，不要解释。'
].join('\n\n')

export function summarizeModelOutputForQa(text, options = {}) {
  const quality = evaluateLiteraryQuality(text)
  const futureSecretForCheck = options.futureSecret || futureSecret
  const issues = quality.issues.map(issue => ({
    code: issue.code,
    severity: issue.severity,
    message: issue.message
  }))
  const blockingIssueCodes = issues
    .filter(issue => issue.severity === 'blocking')
    .map(issue => issue.code)
  const warningIssueCodes = issues
    .filter(issue => issue.severity !== 'blocking')
    .map(issue => issue.code)
  return {
    chars: text.length,
    leakedFutureSecret: text.includes(futureSecretForCheck) || text.includes('顾闻舟'),
    qualityScore: quality.score,
    passedEvaluator: quality.passed,
    passRule: 'passedEvaluator is true only when qualityScore >= 70 and blockingIssueCodes is empty; warningIssueCodes may still be present.',
    issues,
    issueCodes: issues.map(issue => issue.code),
    blockingIssueCodes,
    warningIssueCodes,
    excerpt: text.replace(/\s+/g, ' ').trim().slice(0, 320)
  }
}

export function buildModelValidationConclusion(oldSummary, newSummary) {
  return {
    guardLeakReduced: oldSummary.leakedFutureSecret && !newSummary.leakedFutureSecret,
    newPromptAvoidedFutureSecret: !newSummary.leakedFutureSecret,
    newPromptQualityAtLeastOld: newSummary.qualityScore >= oldSummary.qualityScore,
    newPromptPassedEvaluator: Boolean(newSummary.passedEvaluator),
    oldPromptPassedEvaluator: Boolean(oldSummary.passedEvaluator),
    newPromptHasNoBlockingIssues: newSummary.blockingIssueCodes.length === 0
  }
}

function validateSummary(label, summary = {}) {
  if (!Array.isArray(summary.blockingIssueCodes)) {
    throw new Error(`${label}.blockingIssueCodes must be an array`)
  }
  if (!Array.isArray(summary.warningIssueCodes)) {
    throw new Error(`${label}.warningIssueCodes must be an array`)
  }
  if (summary.passedEvaluator && summary.blockingIssueCodes.length) {
    throw new Error(`${label}.passedEvaluator cannot be true with blocking issues`)
  }
  const expectedPassed = Number(summary.qualityScore || 0) >= 70 && summary.blockingIssueCodes.length === 0
  if (summary.passedEvaluator !== expectedPassed) {
    throw new Error(`${label}.passedEvaluator must equal qualityScore>=70 && no blocking issues`)
  }
}

export function validateModelValidationPayload(payload = {}) {
  if (payload.status !== 'completed') return true
  const oldSummary = payload.results?.oldPrompt
  const newSummary = payload.results?.newPrompt
  validateSummary('oldPrompt', oldSummary)
  validateSummary('newPrompt', newSummary)
  const conclusion = payload.results?.conclusion || {}
  if (conclusion.newPromptQualityAtLeastOld !== (newSummary.qualityScore >= oldSummary.qualityScore)) {
    throw new Error('conclusion.newPromptQualityAtLeastOld is inconsistent with qualityScore values')
  }
  if (conclusion.newPromptAvoidedFutureSecret !== !newSummary.leakedFutureSecret) {
    throw new Error('conclusion.newPromptAvoidedFutureSecret is inconsistent with newPrompt.leakedFutureSecret')
  }
  return true
}

export function assertReportMatchesModelValidation(reportText = '', payload = {}) {
  validateModelValidationPayload(payload)
  if (payload.status !== 'completed') return true
  const report = String(reportText || '')
  const requiredTokens = []
  for (const label of ['oldPrompt', 'newPrompt']) {
    const summary = payload.results[label]
    const blockingText = summary.blockingIssueCodes.length ? summary.blockingIssueCodes.join(',') : 'none'
    const warningText = summary.warningIssueCodes.length ? summary.warningIssueCodes.join(',') : 'none'
    requiredTokens.push(`${label}.qualityScore=${summary.qualityScore}`)
    requiredTokens.push(`${label}.passedEvaluator=${summary.passedEvaluator}`)
    requiredTokens.push(`${label}.blockingIssueCodes=${blockingText}`)
    requiredTokens.push(`${label}.warningIssueCodes=${warningText}`)
    requiredTokens.push(`${label}.leakedFutureSecret=${summary.leakedFutureSecret}`)
  }
  requiredTokens.push(`newPromptQualityAtLeastOld=${payload.results.conclusion.newPromptQualityAtLeastOld}`)
  requiredTokens.push(`newPromptAvoidedFutureSecret=${payload.results.conclusion.newPromptAvoidedFutureSecret}`)
  requiredTokens.push(`newPromptPassedEvaluator=${payload.results.conclusion.newPromptPassedEvaluator}`)
  requiredTokens.push(`oldPromptPassedEvaluator=${payload.results.conclusion.oldPromptPassedEvaluator}`)
  requiredTokens.push(`newPromptHasNoBlockingIssues=${payload.results.conclusion.newPromptHasNoBlockingIssues}`)

  for (const token of requiredTokens) {
    if (!report.includes(token)) {
      throw new Error(`Report does not match model validation JSON: missing ${token}`)
    }
  }
  return true
}

async function writeReport(payload) {
  await fs.mkdir(OUT_DIR, { recursive: true })
  await fs.writeFile(OUT_FILE, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
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
      messages: [
        {
          role: 'user',
          content: prompt
        }
      ],
      temperature: params.temperature,
      top_p: params.top_p,
      max_tokens: params.max_tokens
    })
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = json?.error?.message || json?.message || res.statusText
    throw new Error(`${res.status} ${detail}`)
  }
  return json?.choices?.[0]?.message?.content || ''
}

const apiKey = process.env.DEEPSEEK_API_KEY || process.env.CRAZYCAP_PLANNING_PROVIDER_API_KEY || ''
const baseURL = process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com/v1'
const initialModel = process.env.CRAZYCAP_PLANNING_PROVIDER_MODEL || process.env.OPENCLAW_MODEL_REF || 'deepseek-v4-pro'

const basePayload = {
  schemaVersion: 'narrative-voice-phase2-model-validation-v1',
  timestamp: new Date().toISOString(),
  preferredModelRequested: '联通云-DeepSeek-V4-Flash',
  status: 'pending',
  reasonForFallback: '当前线程未暴露可用的联通云未脱敏 baseURL/apiKey；只使用环境中可见的 DeepSeek fallback key 做离线 QA。',
  provider: {
    name: 'DeepSeek fallback',
    baseURL,
    model: initialModel,
    parameters: params
  },
  inputSummary: {
    oldPrompt: '代表旧创作入口：厚 AI-trace/写作质量清单 + 未配重风格短语 + 错误混入 guardSnapshot 未来路线。',
    newPrompt: 'Phase 2 创作入口：Scene Execution Card + Narrative Voice Contract；guardSnapshot 不进入 creative prompt。',
    futureSecret
  }
}

async function runModelValidation() {
  if (!apiKey) {
    await writeReport({
      ...basePayload,
      status: 'skipped',
      error: 'No DEEPSEEK_API_KEY or CRAZYCAP_PLANNING_PROVIDER_API_KEY found.'
    })
    console.log(`model validation skipped: missing API key; wrote ${OUT_FILE}`)
    return
  }

  let usedModel = initialModel
  let oldOutput = ''
  let newOutput = ''
  const attempts = []

  try {
    oldOutput = await callChat({ apiKey, baseURL, model: usedModel, prompt: oldPrompt })
    newOutput = await callChat({ apiKey, baseURL, model: usedModel, prompt: newPrompt })
  } catch (error) {
    attempts.push({ model: usedModel, error: error.message })
    if (usedModel !== 'deepseek-chat') {
      usedModel = 'deepseek-chat'
      oldOutput = await callChat({ apiKey, baseURL, model: usedModel, prompt: oldPrompt })
      newOutput = await callChat({ apiKey, baseURL, model: usedModel, prompt: newPrompt })
    } else {
      throw error
    }
  }

  const oldSummary = summarizeModelOutputForQa(oldOutput, { futureSecret })
  const newSummary = summarizeModelOutputForQa(newOutput, { futureSecret })
  const result = {
    ...basePayload,
    status: 'completed',
    provider: {
      ...basePayload.provider,
      model: usedModel
    },
    attempts,
    results: {
      oldPrompt: oldSummary,
      newPrompt: newSummary,
      conclusion: buildModelValidationConclusion(oldSummary, newSummary)
    }
  }
  validateModelValidationPayload(result)
  await writeReport(result)
  console.log(`model validation completed with ${usedModel}; wrote ${OUT_FILE}`)
}

const isCliRun = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href
if (isCliRun) {
  runModelValidation().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
