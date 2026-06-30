import { mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import path from 'node:path'
import {
  buildStoryBlockPlanningPrompt,
  buildStoryBlockPlanningSystemPrompt
} from '../frontend/src/prompts/storyBlockPrompt.js'
import {
  buildScenePlanPrompt,
  buildScenePlanSystemPrompt
} from '../frontend/src/prompts/chapterPlanPrompt.js'
import {
  cleanChapterBeatPlanText,
  parseStructuredBeatPlan,
  collectStructuredBeatPlanIssues
} from '../frontend/src/prompts/chapter.js'

const API_BASE = 'http://127.0.0.1:8000/api'
const PROJECT_ID = process.env.PROJECT_ID || '75d4fbb5-a3b1-4624-9de8-dbfda5714d84'
const EXPECTED_PROVIDER_NAME = '联通云-DeepSeek-V4-Flash'
const EXPECTED_MODEL_NAME = 'DeepSeek-V4-Flash'
const OUT_DIR = 'tmp/realistic-flow-qa'
const REPORT_JSON = path.join(OUT_DIR, 'model-vs-chain-diagnostics.json')
const REPORT_MD = path.join(OUT_DIR, 'model-vs-chain-diagnostics.md')

mkdirSync(OUT_DIR, { recursive: true })

async function api(pathname, options = {}) {
  const res = await fetch(`${API_BASE}${pathname}`, options)
  if (!res.ok) throw new Error(`API ${res.status} ${pathname}: ${await res.text()}`)
  const text = await res.text()
  return text ? JSON.parse(text) : null
}

function asList(value) {
  return Array.isArray(value) ? value : []
}

function pickProvider(providers, matcher) {
  return asList(providers).find(provider => matcher(`${provider.name || ''} ${provider.model || ''}`))
}

function pickExpectedProvider(providers) {
  return asList(providers).find(provider =>
    String(provider.name || '').trim().toLowerCase() === EXPECTED_PROVIDER_NAME &&
    String(provider.model || '').trim().toLowerCase() === EXPECTED_MODEL_NAME
  )
}

function compact(value, limit = 6000) {
  const text = typeof value === 'string' ? value : JSON.stringify(value || {}, null, 2)
  return text.length > limit ? `${text.slice(0, limit)}\n...[truncated ${text.length - limit}]` : text
}

function normalizeSeed(seed = {}) {
  return {
    title: seed.title || '',
    genre: seed.genre || '',
    logline: seed.logline || '',
    protagonist: seed.protagonist || '',
    desire: seed.desire || '',
    coreConflict: seed.coreConflict || seed.core_conflict || '',
    worldPressure: seed.worldPressure || seed.world_pressure || '',
    openingHook: seed.openingHook || seed.opening_hook || '',
    openingAnchor: seed.openingAnchor || seed.opening_anchor || seed.openingHook || seed.opening_hook || '',
    styleTarget: seed.styleTarget || seed.style_target || '',
    differentiation: seed.differentiation || '',
    endingAnchor: seed.endingAnchor || seed.ending_anchor || ''
  }
}

function normalizeStageSnapshot(block = {}) {
  const stage = asList(block.stagePlan || block.stage_plan).find(item => item.status !== 'completed')
    || asList(block.stagePlan || block.stage_plan)[0]
    || {}
  return {
    storyBlockId: block.id || '',
    stageId: stage.id || '',
    blockTitle: block.title || '',
    blockGoal: block.goal || '',
    entryState: block.entryState || block.entry_state || '',
    storyFunction: block.storyFunction || block.story_function || '',
    mainPressure: block.mainPressure || block.main_pressure || '',
    stagePurpose: stage.purpose || stage.stagePurpose || stage.goal || '',
    stageAction: stage.sceneOrAction || stage.action || stage.description || '',
    stageChoice: stage.choice || '',
    stageCostOrConsequence: stage.costOrConsequence || stage.consequence || stage.cost || '',
    capturedAt: Date.now()
  }
}

function buildOpeningHitText(seed = {}) {
  return [
    seed.openingHook,
    seed.openingAnchor,
    '雨夜当铺',
    '父亲名字',
    '新账',
    '星账首次异常'
  ].filter(Boolean)
}

function hitsOpeningHook(text, seed = {}) {
  const source = String(text || '')
  return buildOpeningHitText(seed).some(item => item && source.includes(item))
}

function hitsHandoff(text, currentVolume = {}) {
  const source = String(text || '')
  const handoff = String(currentVolume.handoffPoint || currentVolume.handoff_point || '')
  if (!handoff) return false
  return source.includes(handoff.slice(0, Math.min(18, handoff.length))) ||
    /档案库|旧地图|离开雨夜城|巡天司驻地外围/.test(source)
}

async function chatCompletion(provider, messages, options = {}) {
  const baseURL = String(provider.baseURL || provider.base_url || '').replace(/\/+$/, '')
  const url = baseURL.includes('/chat/completions') ? baseURL : `${baseURL}/chat/completions`
  const body = {
    model: provider.model,
    messages,
    max_tokens: options.maxTokens || 1800,
    temperature: options.temperature ?? 0.4,
    top_p: provider.topP || provider.top_p || 0.9,
    stream: false
  }
  if (options.responseFormat === 'json' && provider.supportsJSON !== false && provider.supports_json !== false) {
    body.response_format = { type: 'json_object' }
  }
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${provider.apiKey || provider.api_key || ''}`
    },
    body: JSON.stringify(body)
  })
  const raw = await res.text()
  if (!res.ok) throw new Error(`API ${res.status}: ${raw.slice(0, 1200)}`)
  const parsed = JSON.parse(raw)
  return {
    apiRaw: parsed,
    content: parsed.choices?.[0]?.message?.content || '',
    finishReason: parsed.choices?.[0]?.finish_reason || '',
    usage: parsed.usage || null
  }
}

function parseJsonObject(text = '') {
  const source = String(text || '').trim()
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/i, '')
    .trim()
  const start = source.indexOf('{')
  const end = source.lastIndexOf('}')
  if (start < 0 || end <= start) return null
  return JSON.parse(source.slice(start, end + 1))
}

async function diagnoseStoryBlock(provider, context, seed, currentVolume) {
  const messages = [
    { role: 'system', content: buildStoryBlockPlanningSystemPrompt() },
    { role: 'user', content: buildStoryBlockPlanningPrompt(context) }
  ]
  const promptChars = messages.reduce((sum, item) => sum + item.content.length, 0)
  const result = await chatCompletion(provider, messages, {
    maxTokens: 2600,
    temperature: 0.35,
    responseFormat: 'json'
  })
  let jsonParsed = false
  let parseError = ''
  let parsed = null
  try {
    parsed = parseJsonObject(result.content)
    jsonParsed = Boolean(parsed)
  } catch (error) {
    parseError = error.message
  }
  const combined = JSON.stringify(parsed || result.content)
  return {
    task: 'story_block_planning',
    providerId: provider.id,
    providerName: provider.name,
    modelName: provider.model,
    promptChars,
    rawHead: result.content.slice(0, 1500),
    rawTail: result.content.slice(-800),
    cleanedLength: result.content.trim().length,
    jsonParseSucceeded: jsonParsed,
    parseError,
    repairTriggered: false,
    repairSucceeded: false,
    finishReason: result.finishReason,
    usage: result.usage,
    openingHookHit: hitsOpeningHook(combined, seed),
    handoffPointHit: hitsHandoff(combined, currentVolume),
    plannedTitle: parsed?.title || '',
    plannedEntryState: parsed?.entryState || '',
    plannedStage1: parsed?.stagePlan?.[0] || null,
    savedChapterBeatPlan: false
  }
}

async function diagnoseBeatPlan(provider, context) {
  const messages = [
    { role: 'system', content: buildScenePlanSystemPrompt() },
    { role: 'user', content: buildScenePlanPrompt(context) }
  ]
  const promptChars = messages.reduce((sum, item) => sum + item.content.length, 0)
  const result = await chatCompletion(provider, messages, {
    maxTokens: 1800,
    temperature: 0.6
  })
  const extracted = result.content || ''
  const cleaned = cleanChapterBeatPlanText(extracted)
  const structured = parseStructuredBeatPlan(cleaned)
  const issues = collectStructuredBeatPlanIssues(structured, {})
  return {
    task: 'chapter_1_beat_plan',
    providerId: provider.id,
    providerName: provider.name,
    modelName: provider.model,
    promptChars,
    rawHead: result.content.slice(0, 1500),
    rawTail: result.content.slice(-800),
    extractedLength: extracted.length,
    cleanedLength: cleaned.length,
    jsonParseSucceeded: Boolean(cleaned.trim() && Object.values(structured).some(Boolean)),
    repairTriggered: false,
    repairSucceeded: false,
    qualityGatePassed: cleaned.trim().length > 0 && !issues.missingRequiredFields?.length,
    qualityIssues: issues,
    finishReason: result.finishReason,
    usage: result.usage,
    savedChapterBeatPlan: false
  }
}

async function main() {
  const [project, providers, seeds, bible, volumes, blocks, settings, facts] = await Promise.all([
    api(`/projects/${PROJECT_ID}`),
    api('/providers'),
    api(`/projects/${PROJECT_ID}/seeds`),
    api(`/projects/${PROJECT_ID}/bible`).catch(() => null),
    api(`/projects/${PROJECT_ID}/volumes`).catch(() => []),
    api(`/projects/${PROJECT_ID}/story-blocks`).catch(() => []),
    api(`/projects/${PROJECT_ID}/settings/entities`).catch(() => []),
    api(`/projects/${PROJECT_ID}/canon-facts`).catch(() => [])
  ])

  const flash = pickExpectedProvider(providers)
  const pro = pickProvider(providers, text => /deepseek[-_\s]*v4[-_\s]*pro/i.test(text))
  if (!flash) throw new Error(`未找到 ${EXPECTED_PROVIDER_NAME} / ${EXPECTED_MODEL_NAME} provider`)
  const selectedSeed = asList(seeds).find(seed => seed.status === 'selected') || asList(seeds)[0] || {}
  const seed = normalizeSeed(selectedSeed)
  const currentVolume = asList(volumes).find(volume => Number(volume.startChapter || volume.start_chapter || 0) <= 1 && Number(volume.endChapter || volume.end_chapter || 0) >= 1)
    || asList(volumes)[0]
    || {}
  const activeBlock = asList(blocks).find(block => block.status === 'active') || asList(blocks)[0] || {}
  const blockStageSnapshot = normalizeStageSnapshot(activeBlock)

  const commonContext = {
    chapterNum: 1,
    seed,
    openingHook: seed.openingHook,
    openingAnchor: seed.openingAnchor,
    bible,
    currentVolume,
    volumeStage: currentVolume,
    volumePlanning: volumes,
    settingLibrary: { entities: settings, relations: [] },
    stateLedger: { canonFacts: facts },
    recentFacts: facts,
    recentSummaries: [],
    recentChapterEndings: [],
    previousChapterEnding: '',
    newBlockSeed: null
  }
  const beatContext = {
    ...commonContext,
    storyBlock: activeBlock,
    blockStageSnapshot,
    wordTarget: { min: 4500, max: 6000 }
  }

  const candidates = [flash, pro].filter(Boolean)
  const diagnostics = []
  for (const provider of candidates) {
    diagnostics.push(await diagnoseStoryBlock(provider, commonContext, seed, currentVolume).catch(error => ({
      task: 'story_block_planning',
      providerId: provider.id,
      providerName: provider.name,
      modelName: provider.model,
      error: error.message
    })))
    diagnostics.push(await diagnoseBeatPlan(provider, beatContext).catch(error => ({
      task: 'chapter_1_beat_plan',
      providerId: provider.id,
      providerName: provider.name,
      modelName: provider.model,
      error: error.message
    })))
  }

  const flashBlock = diagnostics.find(item => item.task === 'story_block_planning' && item.providerId === flash.id)
  const proBlock = diagnostics.find(item => item.task === 'story_block_planning' && pro && item.providerId === pro.id)
  const flashBeat = diagnostics.find(item => item.task === 'chapter_1_beat_plan' && item.providerId === flash.id)
  const proBeat = diagnostics.find(item => item.task === 'chapter_1_beat_plan' && pro && item.providerId === pro.id)
  const assessment = {
    modelStabilityRisk: Boolean(pro && (proBlock?.openingHookHit || proBeat?.qualityGatePassed) && (!flashBlock?.openingHookHit || !flashBeat?.qualityGatePassed)),
    platformPromptContextRisk: Boolean((flashBlock && proBlock && !flashBlock.openingHookHit && !proBlock.openingHookHit) || (flashBeat && proBeat && !flashBeat.qualityGatePassed && !proBeat.qualityGatePassed)),
    v4ProAvailable: Boolean(pro)
  }

  const report = {
    mode: 'live_diagnostics',
    createdAt: new Date().toISOString(),
    usesArchivedReports: false,
    project: {
      id: PROJECT_ID,
      title: project?.title || project?.name || ''
    },
    inputSummary: {
      openingHook: seed.openingHook,
      openingAnchor: seed.openingAnchor,
      currentVolumeTitle: currentVolume.title || '',
      currentVolumeCoreGoal: currentVolume.coreGoal || currentVolume.core_goal || '',
      currentVolumeHandoffPoint: currentVolume.handoffPoint || currentVolume.handoff_point || '',
      activeStoryBlockTitle: activeBlock.title || '',
      activeStoryBlockEntryState: activeBlock.entryState || activeBlock.entry_state || '',
      activeStoryBlockStage1: asList(activeBlock.stagePlan || activeBlock.stage_plan)[0] || null,
      promptContextHead: compact(commonContext, 3000)
    },
    diagnostics,
    assessment
  }

  writeFileSync(REPORT_JSON, JSON.stringify(report, null, 2), 'utf8')
  const lines = [
    '# 模型与平台链路诊断',
    '',
    `- projectId: ${PROJECT_ID}`,
    `- usesArchivedReports: false`,
    `- V4 Pro 可用: ${assessment.v4ProAvailable}`,
    `- 模型稳定性风险: ${assessment.modelStabilityRisk}`,
    `- 平台 prompt/context 风险: ${assessment.platformPromptContextRisk}`,
    '',
    '## 输入摘要',
    `- openingHook: ${seed.openingHook || '无'}`,
    `- currentVolume.handoffPoint: ${currentVolume.handoffPoint || currentVolume.handoff_point || '无'}`,
    `- activeStoryBlock: ${activeBlock.title || '无'}`,
    '',
    '## 诊断',
    ...diagnostics.flatMap(item => [
      `### ${item.task} / ${item.providerName || item.providerId} / ${item.modelName}`,
      `- promptChars: ${item.promptChars || 0}`,
      `- cleanedLength: ${item.cleanedLength ?? item.extractedLength ?? 0}`,
      `- jsonParseSucceeded: ${item.jsonParseSucceeded ?? false}`,
      `- qualityGatePassed: ${item.qualityGatePassed ?? 'n/a'}`,
      `- openingHookHit: ${item.openingHookHit ?? 'n/a'}`,
      `- handoffPointHit: ${item.handoffPointHit ?? 'n/a'}`,
      `- savedChapterBeatPlan: ${item.savedChapterBeatPlan ?? false}`,
      item.error ? `- error: ${item.error}` : '',
      ''
    ].filter(Boolean))
  ]
  writeFileSync(REPORT_MD, lines.join('\n'), 'utf8')
  console.log(`WROTE ${REPORT_JSON}`)
  console.log(JSON.stringify(assessment, null, 2))
}

main().catch(error => {
  console.error(error)
  process.exit(1)
})
