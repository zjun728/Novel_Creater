import { spawn } from 'node:child_process'
import {
  existsSync,
  mkdirSync,
  rmSync,
  writeFileSync,
  openSync,
  closeSync,
  appendFileSync
} from 'node:fs'
import { join, resolve } from 'node:path'

const ROOT = resolve('.')
const API_BASE = 'http://127.0.0.1:8000/api'
const APP_URL = 'http://127.0.0.1:5173'
const CHROME_PATH = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const REPORT_DIR = join(ROOT, 'tmp', 'realistic-flow-qa')
const PROFILE_DIR = join(REPORT_DIR, 'chrome-profile')
const LOG_FILE = join(REPORT_DIR, 'run.log')
const KEEP_PROJECT = process.env.DELETE_REALISTIC_QA_PROJECT !== '1'
const CONTINUE_TO_CHAPTER = Number(process.env.CONTINUE_REALISTIC_QA_TO_CHAPTER || 0)

mkdirSync(REPORT_DIR, { recursive: true })
writeFileSync(LOG_FILE, '', 'utf8')

const started = []
const report = {
  startedAt: new Date().toISOString(),
  project: null,
  provider: null,
  phases: [],
  checks: [],
  timings: {},
  generated: {
    marketItems: 0,
    directions: 0,
    seeds: 0,
    settingEvents: 0,
    acceptedSettings: 0,
    chaptersCreated: 0,
    finalizedChapters: 0,
    canonFacts: 0,
    chapterSettingChanges: 0,
    correctionTasks: 0,
    chapterWordCounts: [],
    finalChapterWordCounts: [],
    auditFailures: 0,
    multiChapterAcceptance: null
  },
  browserConsole: [],
  screenshots: [],
  cleanup: KEEP_PROJECT ? '保留测试项目' : null,
  notes: []
}

function now() {
  return new Date().toISOString().replace('T', ' ').slice(0, 19)
}

function log(message) {
  const line = `[${now()}] ${message}`
  console.log(line)
  appendFileSync(LOG_FILE, `${line}\n`, 'utf8')
}

function pass(name, detail = '') {
  report.checks.push({ name, status: 'pass', detail })
  log(`PASS ${name}${detail ? ` - ${detail}` : ''}`)
}

function fail(name, detail = '') {
  report.checks.push({ name, status: 'fail', detail })
  log(`FAIL ${name}${detail ? ` - ${detail}` : ''}`)
}

function assertCheck(condition, name, detail = '') {
  if (condition) pass(name, detail)
  else fail(name, detail)
}

function maskKey(key = '') {
  if (!key) return '未配置'
  return `${String(key).slice(0, 6)}...${String(key).slice(-4)}`
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function waitForHttp(url, timeoutMs = 30000) {
  const startedAt = Date.now()
  let lastError = ''
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(3000) })
      if (res.ok) return true
      lastError = `HTTP ${res.status}`
    } catch (error) {
      lastError = error.message
    }
    await sleep(500)
  }
  throw new Error(`等待服务超时：${url}；最后错误：${lastError}`)
}

async function request(method, path, body, expectedStatuses = [200]) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(120000)
  })
  const text = await res.text()
  let data = null
  if (text) {
    try { data = JSON.parse(text) } catch { data = text }
  }
  if (!expectedStatuses.includes(res.status)) {
    throw new Error(`${method} ${path} -> ${res.status}: ${typeof data === 'string' ? data : JSON.stringify(data)}`)
  }
  return data
}

async function ensureBackend() {
  try {
    await waitForHttp(`${API_BASE}/health`, 2500)
    pass('后端服务可用')
    return
  } catch {
    log('后端未启动，尝试启动 uvicorn')
    const out = openSync(join(REPORT_DIR, 'backend.log'), 'a')
    const err = openSync(join(REPORT_DIR, 'backend.err.log'), 'a')
    const proc = spawn('D:/Software/Python/Python312/python.exe', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], {
      cwd: join(ROOT, 'backend'),
      stdio: ['ignore', out, err],
      windowsHide: true
    })
    started.push({ proc, out, err, name: 'backend' })
    await waitForHttp(`${API_BASE}/health`, 45000)
    pass('后端服务已由脚本启动')
  }
}

async function ensureFrontend() {
  try {
    await waitForHttp(APP_URL, 2500)
    pass('前端服务可用')
    return
  } catch {
    log('前端未启动，尝试启动 Vite')
    const out = openSync(join(REPORT_DIR, 'frontend.log'), 'a')
    const err = openSync(join(REPORT_DIR, 'frontend.err.log'), 'a')
    const proc = spawn('D:/Software/nodejs/node.exe', ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5173'], {
      cwd: join(ROOT, 'frontend'),
      stdio: ['ignore', out, err],
      windowsHide: true
    })
    started.push({ proc, out, err, name: 'frontend' })
    await waitForHttp(APP_URL, 45000)
    pass('前端服务已由脚本启动')
  }
}

async function getPreferredProvider() {
  const providers = await request('GET', '/providers')
  const preferred = providers.find(item => item.name === '联通云-DeepSeek-V4-Flash')
    || providers.find(item => /DeepSeek-V4-Flash/i.test(item.model || ''))
    || providers[0]
  if (!preferred) throw new Error('没有可用 Provider')
  report.provider = {
    name: preferred.name,
    model: preferred.model,
    baseURL: preferred.baseURL,
    apiKey: maskKey(preferred.apiKey),
    maxContextTokens: preferred.maxContextTokens,
    maxOutputTokens: preferred.maxOutputTokens
  }
  pass('模型配置已读取', `${preferred.name} / ${preferred.model} / ${maskKey(preferred.apiKey)}`)
  return preferred
}

function jsonResponseFormat(provider) {
  return provider?.supportsJSON === false ? undefined : { type: 'json_object' }
}

async function chat(provider, messages, options = {}) {
  const body = {
    model: provider.model,
    messages,
    temperature: options.temperature ?? provider.temperature ?? 0.75,
    top_p: options.topP ?? provider.topP ?? 0.9,
    max_tokens: options.maxTokens ?? 4096,
    stream: false
  }
  if (options.json) body.response_format = jsonResponseFormat(provider)

  const res = await fetch(`${provider.baseURL.replace(/\/$/, '')}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${provider.apiKey}`
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(options.timeoutMs || 240000)
  })
  const text = await res.text()
  if (!res.ok) {
    throw new Error(`LLM ${res.status}: ${text.slice(0, 500)}`)
  }
  const data = JSON.parse(text)
  return data?.choices?.[0]?.message?.content || ''
}

async function chatJson(provider, messages, options = {}, repairHint = '请把上一次内容整理成合法 JSON。') {
  const first = await chat(provider, messages, { ...options, json: true })
  try {
    return { payload: parseJsonPayload(first), raw: first, repaired: false }
  } catch (firstError) {
    const repair = await chat(provider, [
      { role: 'system', content: '你是 JSON 修复器。只能输出合法 JSON，不要解释，不要 Markdown。' },
      { role: 'user', content: `${repairHint}\n\n原始内容：\n${first.slice(0, 12000)}` }
    ], {
      json: true,
      maxTokens: options.repairMaxTokens || options.maxTokens || 4096,
      temperature: 0,
      timeoutMs: options.timeoutMs || 240000
    })
    try {
      return { payload: parseJsonPayload(repair), raw: repair, repaired: true }
    } catch {
      const retry = await chat(provider, messages, {
        ...options,
        json: true,
        temperature: Math.min(options.temperature ?? 0.5, 0.35),
        maxTokens: Math.max(options.maxTokens || 4096, options.retryMaxTokens || 6000)
      })
      return { payload: parseJsonPayload(retry), raw: retry, repaired: true, firstError: firstError.message }
    }
  }
}

function cleanJsonCandidate(candidate) {
  return candidate
    .trim()
    .replace(/^\uFEFF/, '')
    .replace(/^```(?:json)?/i, '')
    .replace(/```$/i, '')
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/,\s*([}\]])/g, '$1')
    .trim()
}

function collectBalanced(text, openChar, closeChar) {
  const out = []
  let cursor = 0
  while (cursor < text.length) {
    const start = text.indexOf(openChar, cursor)
    if (start === -1) break
    let depth = 0
    let inString = false
    let escaped = false
    for (let i = start; i < text.length; i += 1) {
      const ch = text[i]
      if (inString) {
        if (escaped) escaped = false
        else if (ch === '\\') escaped = true
        else if (ch === '"') inString = false
        continue
      }
      if (ch === '"') inString = true
      else if (ch === openChar) depth += 1
      else if (ch === closeChar) {
        depth -= 1
        if (depth === 0) {
          out.push(text.slice(start, i + 1))
          cursor = i + 1
          break
        }
      }
      if (i === text.length - 1) cursor = start + 1
    }
  }
  return out
}

function parseJsonPayload(text) {
  const candidates = [
    text,
    ...collectBalanced(text, '{', '}'),
    ...collectBalanced(text, '[', ']')
  ]
  for (const item of candidates) {
    try {
      return JSON.parse(cleanJsonCandidate(item))
    } catch {
      // continue
    }
  }
  throw new Error(`没有解析到 JSON：${text.slice(0, 260)}`)
}

function normalizeSeed(raw) {
  return {
    title: String(raw.title || raw.name || '未命名测试种子').trim(),
    genre: String(raw.genre || raw.category || '玄幻悬疑').trim(),
    logline: String(raw.logline || raw.premise || '').trim(),
    protagonist: String(raw.protagonist || '').trim(),
    desire: String(raw.desire || '').trim(),
    coreConflict: String(raw.coreConflict || raw.core_conflict || '').trim(),
    worldPressure: String(raw.worldPressure || raw.world_pressure || '').trim(),
    openingHook: String(raw.openingHook || raw.opening_hook || '').trim(),
    emotionalPromise: String(raw.emotionalPromise || raw.emotional_promise || '').trim(),
    differentiation: String(raw.differentiation || '').trim(),
    styleTarget: String(raw.styleTarget || raw.style_target || '').trim(),
    riskNotes: String(raw.riskNotes || raw.risk_notes || '').trim(),
    endingAnchor: String(raw.endingAnchor || raw.ending_anchor || '').trim(),
    source: 'ai'
  }
}

function stringifyList(value) {
  if (Array.isArray(value)) return value.filter(Boolean).map(String).join('\n')
  if (value && typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value || '')
}

function normalizeBible(raw) {
  return {
    premise: stringifyList(raw.premise),
    targetReader: stringifyList(raw.targetReader || raw.target_reader),
    styleBible: stringifyList(raw.styleBible || raw.style_bible || raw.style),
    themeBible: stringifyList(raw.themeBible || raw.theme_bible || raw.theme),
    worldRules: stringifyList(raw.worldRules || raw.world_rules),
    forbiddenDirections: Array.isArray(raw.forbiddenDirections)
      ? raw.forbiddenDirections.filter(Boolean).map(String)
      : stringifyList(raw.forbiddenDirections || raw.forbidden_directions).split(/\n+/).filter(Boolean)
  }
}

function wordCount(text) {
  return String(text || '').replace(/\s+/g, '').length
}

function trimText(text, max = 1600) {
  const value = String(text || '').trim()
  if (value.length <= max) return value
  return `${value.slice(0, max)}...`
}

function expectedChapterWordRange(project) {
  const targetWords = Number(project?.targetWords || 0)
  const targetChapters = Number(project?.targetChapters || 0)
  const target = targetWords > 0 && targetChapters > 0
    ? Math.max(1200, Math.round(targetWords / targetChapters))
    : 5000
  return {
    target,
    softMin: Math.round(target * 0.9),
    softMax: Math.round(target * 1.1),
    hardMin: Math.round(target * 0.8),
    hardMax: Math.round(target * 1.2)
  }
}

function upsertCount(list, chapterNum, patch) {
  const existing = list.find(item => Number(item.chapterNum) === Number(chapterNum))
  if (existing) Object.assign(existing, patch)
  else list.push({ chapterNum, ...patch })
}

function assessChapterWordCount(project, chapterNum, count, stage = '正文') {
  const range = expectedChapterWordRange(project)
  const detail = `${count} 字；目标 ${range.target}，建议 ${range.softMin}-${range.softMax}，硬范围 ${range.hardMin}-${range.hardMax}`
  if (count < range.hardMin || count > range.hardMax) {
    fail(`第 ${chapterNum} 章${stage}字数越界`, detail)
    return false
  }
  if (count < range.softMin || count > range.softMax) {
    report.notes.push(`第 ${chapterNum} 章${stage}字数略偏离建议范围：${detail}`)
  }
  pass(`第 ${chapterNum} 章${stage}字数在可接受范围`, detail)
  return true
}

function validateRevisionWordDrift(project, chapterNum, originalContent, revisedContent) {
  const originalCount = wordCount(originalContent)
  const revisedCount = wordCount(revisedContent)
  if (!revisedContent || revisedContent === originalContent) {
    return { ok: true, originalCount, revisedCount, reason: 'unchanged' }
  }
  const ratio = originalCount > 0 ? revisedCount / originalCount : 1
  const range = expectedChapterWordRange(project)
  const tooMuchDrift = ratio < 0.85 || ratio > 1.15
  const outsideHardRange = revisedCount < range.hardMin || revisedCount > range.hardMax
  if (tooMuchDrift || outsideHardRange) {
    fail(
      `第 ${chapterNum} 章审稿修订字数漂移过大`,
      `原 ${originalCount} 字，修订 ${revisedCount} 字，比例 ${ratio.toFixed(2)}；已回退到修订前正文`
    )
    return { ok: false, originalCount, revisedCount, reason: tooMuchDrift ? 'drift' : 'word_range' }
  }
  return { ok: true, originalCount, revisedCount, reason: 'accepted' }
}

function recordFinalChapterWordCount(chapterNum, count) {
  upsertCount(report.generated.finalChapterWordCounts, chapterNum, { count })
}

function chapterTitle(chapterNum, name = '') {
  return name ? `第 ${chapterNum} 章 · ${name}` : `第 ${chapterNum} 章`
}

async function createProject(provider) {
  const stamp = new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14)
  const project = await request('POST', '/projects', {
    title: `真实流程测试200万_${stamp}`,
    genre: '玄幻悬疑 / 人性选择',
    description: '自动化真实流程测试项目：按 200 万字、400 章规模规划，真实调用网络抓取和大模型生成前几章内容。',
    targetWords: 2000000,
    targetChapters: 400
  })
  report.project = {
    id: project.id,
    title: project.title,
    targetWords: project.targetWords,
    targetChapters: project.targetChapters,
    url: `${APP_URL}/project/${project.id}`
  }
  await request('PUT', `/projects/${project.id}/bindings`, {
    writingModelId: provider.id,
    brainstormModelId: provider.id,
    outlineModelId: provider.id,
    auditModelId: provider.id,
    summaryModelId: provider.id,
    extractionModelId: provider.id,
    marketModelId: provider.id,
    polishModelId: provider.id
  })
  pass('已新建 200 万字规模项目', `${project.title} / 400 章`)
  return project
}

async function runMarketAndSeed(project, provider) {
  log('开始选题雷达：网络抓取热门题材')
  let scrapeResult = null
  try {
    scrapeResult = await request('POST', '/market/scrape', {
      projectId: project.id,
      keywords: '玄幻 悬疑 人性 热门小说'
    })
  } catch (error) {
    report.notes.push(`网络抓取失败：${error.message}`)
    fail('网络抓取热门小说', error.message)
  }
  const marketItems = await request('GET', `/market/items?projectId=${project.id}`)
  report.generated.marketItems = marketItems.length
  assertCheck(marketItems.length > 0, '选题雷达有热点数据', `items=${marketItems.length}${scrapeResult?.fallback ? ' / fallback' : ''}`)

  log('开始 AI 方向建议')
  const marketBrief = marketItems.slice(0, 12).map((item, index) =>
    `${index + 1}. ${item.title}｜${item.platform || ''}｜${item.category || ''}｜${item.intro || ''}`
  ).join('\n')
  const directionResult = await chatJson(provider, [
    { role: 'system', content: '你是网文选题策划编辑。必须输出合法 JSON，不要 Markdown。' },
    { role: 'user', content: `基于这些热点数据，给出 4 个适合长篇原创小说的方向。输出 {"directions":[{"title":"","genre":"","readerExpectation":"","whyNow":"","seedAngle":"","risks":"","discussionPrompt":""}]}。\n\n热点数据：\n${marketBrief}` }
  ], { maxTokens: 3500, temperature: 0.6 }, '修复为 {"directions":[...]} 格式。')
  const directionsPayload = directionResult.payload
  const directions = Array.isArray(directionsPayload.directions) ? directionsPayload.directions : []
  report.generated.directions = directions.length
  await request('POST', '/market/directions', {
    projectId: project.id,
    keywords: '玄幻 悬疑 人性 热门小说',
    directions,
    sourceItems: marketItems.slice(0, 20)
  })
  assertCheck(directions.length >= 2, 'AI 方向建议可解析', `directions=${directions.length}`)

  const userQuestion = `我想选一个适合 200 万字长篇、重点写人性选择和代价的题材，请基于方向建议生成一个完整创作种子，并保留结局锚点。`
  await request('POST', '/market/chat', { projectId: project.id, role: 'user', content: userQuestion, metadata: {} })
  log('开始 AI 选题顾问生成种子')
  const seedResult = await chatJson(provider, [
    { role: 'system', content: '你是资深网文选题顾问。只输出合法 JSON。只生成 1 个种子，每个字段不超过 120 个中文字符，避免 JSON 过长被截断。' },
    { role: 'user', content: `${userQuestion}\n\n方向建议：\n${JSON.stringify(directions, null, 2)}\n\n必须输出 {"seeds":[{"title":"","genre":"","logline":"","protagonist":"","desire":"","coreConflict":"","worldPressure":"","openingHook":"","emotionalPromise":"","differentiation":"","styleTarget":"","riskNotes":"","endingAnchor":""}]}。只输出 JSON。` }
  ], { maxTokens: 6000, retryMaxTokens: 7000, repairMaxTokens: 6000, temperature: 0.65 }, '修复为 {"seeds":[{...}]} 格式；只保留 1 个完整种子。')
  const seedPayload = seedResult.payload
  const seeds = (Array.isArray(seedPayload.seeds) ? seedPayload.seeds : Array.isArray(seedPayload) ? seedPayload : [seedPayload])
    .map(normalizeSeed)
    .filter(seed => seed.logline && seed.protagonist && seed.coreConflict)
  report.generated.seeds = seeds.length
  await request('POST', '/market/chat', {
    projectId: project.id,
    role: 'assistant',
    content: seedResult.raw,
    metadata: { seeds }
  })
  assertCheck(seeds.length >= 1, 'AI 选题顾问生成可保存种子', `seeds=${seeds.length}`)

  const seed = await request('POST', `/projects/${project.id}/seeds`, seeds[0])
  const selectedSeed = await request('PUT', `/projects/${project.id}/seeds/${seed.id}`, { status: 'selected' })
  pass('种子已保存并设为当前种子', selectedSeed.title)

  return { marketItems, directions, seed: selectedSeed }
}

async function runBibleAndSettings(project, provider, seed) {
  log('开始从种子生成创作圣经')
  const bibleText = await chat(provider, [
    { role: 'system', content: '你是长篇小说总编。必须输出合法 JSON，不要 Markdown。创作圣经是后续大纲、设定和正文必须遵守的蓝图。' },
    { role: 'user', content: `根据种子生成创作圣经。输出 {"premise":"","targetReader":"","styleBible":[],"themeBible":[],"worldRules":[],"forbiddenDirections":[]}。\n要求：保留想象力，但把硬规则写清楚；明确避免 AI 腔，少用“不是X，是Y”句式；长期目标是 200 万字。\n\n种子：\n${JSON.stringify(seed, null, 2)}` }
  ], { json: true, maxTokens: 4096, temperature: 0.55 })
  const bible = normalizeBible(parseJsonPayload(bibleText))
  await request('PUT', `/projects/${project.id}/bible`, bible)
  assertCheck(Boolean(bible.premise && bible.styleBible && bible.worldRules), '创作圣经已生成并保存', bible.premise.slice(0, 60))

  log('开始从圣经提取设定候选')
  const settingsText = await chat(provider, [
    { role: 'system', content: '你是长篇小说设定库整理员。只输出合法 JSON。不要重复同名同类型实体；关系变化用独立事件表达。' },
    { role: 'user', content: `从创作种子和圣经中提取 8-12 个初始设定候选，输出 {"settings":[{"entityType":"character|faction|location|power_system|technique|item","entityName":"","changeType":"new_entity|update|relation_change","fieldPath":"summary","newValue":"","evidence":"","confidence":0.9}]}。\n\n种子：${JSON.stringify(seed)}\n\n圣经：${JSON.stringify(bible)}` }
  ], { json: true, maxTokens: 4096, temperature: 0.2 })
  const settingsPayload = parseJsonPayload(settingsText)
  const settings = Array.isArray(settingsPayload.settings) ? settingsPayload.settings : []
  const seen = new Set()
  const createdEvents = []
  for (const item of settings) {
    const entityType = item.entityType || 'character'
    const entityName = item.entityName || item.name || ''
    const fieldPath = item.fieldPath || 'summary'
    const key = `${entityType}:${entityName}:${fieldPath}:${item.newValue || item.summary || ''}`
    if (!entityName || seen.has(key)) continue
    seen.add(key)
    const saved = await request('POST', `/projects/${project.id}/settings/change-events`, {
      entityType,
      entityName,
      changeType: item.changeType || 'new_entity',
      fieldPath,
      oldValue: '',
      newValue: item.newValue || item.summary || '',
      chapterNum: null,
      evidence: `创作圣经初始化：${item.evidence || bible.premise}`,
      confidence: Number(item.confidence || 0.9),
      status: 'pending_review'
    })
    createdEvents.push(saved)
  }
  report.generated.settingEvents = createdEvents.length
  assertCheck(createdEvents.length >= 4, '圣经提取到设定候选', `events=${createdEvents.length}`)

  for (const event of createdEvents) {
    await request('POST', `/projects/${project.id}/settings/change-events/${event.id}/accept`)
    report.generated.acceptedSettings += 1
  }
  pass('初始设定候选已全部确认入库', `accepted=${report.generated.acceptedSettings}`)

  const entities = await request('GET', `/projects/${project.id}/settings/entities`)
  assertCheck(entities.length >= 4, '设定库实体已生成', `entities=${entities.length}`)
  return { bible, entities }
}

async function createVolumesAndChapters(project) {
  log('开始创建 200 万字分卷与章节骨架')
  const volumes = []
  for (let i = 1; i <= 8; i += 1) {
    const start = (i - 1) * 50 + 1
    const volume = await request('POST', `/projects/${project.id}/volumes`, {
      volumeNum: i,
      title: `第 ${i} 卷`,
      startChapter: start,
      endChapter: start + 49,
      targetWords: 250000,
      coreGoal: `第 ${i} 卷推动主角对愿望代价的理解升级`,
      mainConflict: '个人愿望、家族真相与逐愿规则之间的冲突',
      keyCharacters: [],
      summary: '自动化测试创建的长篇分卷规划。',
      status: 'planned'
    })
    volumes.push(volume)
  }

  let chaptersCreated = 0
  for (let i = 1; i <= 400; i += 1) {
    await request('POST', `/projects/${project.id}/chapters`, {
      chapterNum: i,
      title: `第 ${i} 章`
    })
    chaptersCreated += 1
  }
  report.generated.chaptersCreated = chaptersCreated
  assertCheck(volumes.length === 8 && chaptersCreated === 400, '200 万字章节骨架已创建', `volumes=${volumes.length}, chapters=${chaptersCreated}`)

  const chapter4 = (await request('GET', `/projects/${project.id}/chapters`)).find(item => Number(item.chapterNum) === 4)
  await request('DELETE', `/projects/${project.id}/chapters/${chapter4.id}`)
  await request('POST', `/projects/${project.id}/chapters`, { chapterNum: 4, title: '第 4 章' })
  pass('空章节删除后可重新创建', '第 4 章')

  return { volumes }
}

async function saveBeatPlan(project, chapterNum, content) {
  await request('PUT', `/projects/${project.id}/chapter-beat-plan/${chapterNum}`, { content })
}

async function generateBeatPlan(project, provider, chapterNum, context) {
  log(`开始生成第 ${chapterNum} 章小纲`)
  const text = await chat(provider, [
    { role: 'system', content: '你是长篇小说分章小纲编辑。只输出正文小纲，不要 JSON。' },
    { role: 'user', content: `为第 ${chapterNum} 章生成小纲。按 5000 字体量设计，建议 4500-5500 字，尽量不要规划成超过 6000 字的一章，更不得规划成两章内容。必须先自查是否偏离设定；如果上一章结尾未收束，要自然承接。小纲要包含：本章目标、情绪推进、关键场景、结尾钩子、写作约束。\n\n上下文：\n${context}` }
  ], { maxTokens: 3000, temperature: 0.55 })
  await saveBeatPlan(project, chapterNum, text)
  assertCheck(text.length > 200, `第 ${chapterNum} 章小纲已生成`, `${text.length} chars`)
  return text
}

async function generateChapterContent(project, provider, chapterNum, context, beatPlan) {
  log(`开始生成第 ${chapterNum} 章正文`)
  const content = await chat(provider, [
    {
      role: 'system',
      content: [
        '你是成熟的长篇网文作者。写作目标是有代入感的人性选择，不是堆设定。',
        '正文要具体、可感、有行动和欲望；少用抽象总结。',
        '严格减少“不是X，是Y”句式；本章出现次数不得超过 3 次。',
        '目标字数 5000 字，建议 4500-5500 字；如情节需要可自然延展，但优先控制在 4000-6000 字，不能为了字数强行收尾或砍掉关键细节。',
        '如果内容超量，优先压缩解释性设定和重复心理描写，不压缩关键动作、选择和代价；如一章装不下，保留自然钩子交给下一章。'
      ].join('\n')
    },
    { role: 'user', content: `根据上下文和小纲生成第 ${chapterNum} 章正文。不要输出标题，不要解释。\n\n上下文：\n${context}\n\n本章小纲：\n${beatPlan}` }
  ], { maxTokens: 9000, temperature: 0.78, timeoutMs: 360000 })
  const count = wordCount(content)
  report.generated.chapterWordCounts.push({ chapterNum, count, stage: 'first_draft' })
  assertCheck(count >= 3000, `第 ${chapterNum} 章正文已生成`, `${count} 字`)
  assessChapterWordCount(project, chapterNum, count, '初稿')
  return content.trim()
}

function auditChapterPayload(payload) {
  const issues = Array.isArray(payload?.issues)
    ? payload.issues
    : Array.isArray(payload)
      ? payload
      : []
  return {
    summary: String(payload?.summary || payload?.overall || '').trim(),
    issues: issues
      .filter(issue => issue && (issue.issue || issue.description || issue.suggestion || issue.location))
      .slice(0, 6)
      .map(issue => ({
        severity: issue.severity || 'minor',
        type: issue.type || 'quality',
        location: trimText(issue.location || issue.evidence || issue.quote || '', 100),
        issue: trimText(issue.issue || issue.description || issue.problem || '', 180),
        suggestion: trimText(issue.suggestion || issue.fix || issue.advice || '', 180),
        replacement: trimText(issue.replacement || issue.rewrite || issue.fixedText || '', 260)
      }))
  }
}

async function auditChapter(provider, chapterNum, content, context) {
  log(`开始审稿第 ${chapterNum} 章`)
  let audit = { summary: '', issues: [] }
  try {
    const result = await chatJson(provider, [
      { role: 'system', content: '你是小说一致性审稿人。只输出合法 JSON。问题要具体，location 尽量引用原文中真实存在的短片段。' },
      { role: 'user', content: `审查第 ${chapterNum} 章，重点看：设定矛盾、人物动机、人性代入、数值计算、章节衔接、AI 腔句式。输出 {"summary":"","issues":[{"severity":"critical|major|minor|suggestion","type":"contradiction|logic|motivation|pacing|ai_tone|continuity","location":"","issue":"","suggestion":"","replacement":""}]}。\n\n上下文：${context}\n\n正文：\n${content}` }
    ], {
      maxTokens: 6000,
      repairMaxTokens: 6000,
      retryMaxTokens: 6000,
      temperature: 0.2,
      timeoutMs: 300000
    }, '请修复为 {"summary":"","issues":[...]} 格式；最多保留 6 个最重要的问题；所有字段必须完整。')
    audit = auditChapterPayload(result.payload)
  } catch (error) {
    report.notes.push(`第 ${chapterNum} 章审稿首次失败，已启用审稿紧凑重试：${trimText(error.message, 180)}`)
    try {
      const compact = await chatJson(provider, [
        { role: 'system', content: '你是小说一致性审稿人。只输出合法 JSON，不要解释。' },
        { role: 'user', content: `审稿紧凑重试：审查第 ${chapterNum} 章，只保留 0-3 个最关键问题。每个字段必须短，location 必须是原文中真实存在的短片段。输出 {"summary":"","issues":[{"severity":"critical|major|minor|suggestion","type":"contradiction|logic|motivation|pacing|ai_tone|continuity","location":"","issue":"","suggestion":"","replacement":""}]}。\n\n上下文摘要：${trimText(context, 2200)}\n\n正文节选：\n${content.slice(0, 7000)}` }
      ], {
        maxTokens: 2600,
        repairMaxTokens: 2600,
        retryMaxTokens: 3000,
        temperature: 0.15,
        timeoutMs: 240000
      }, '审稿紧凑重试修复为 {"summary":"","issues":[...]} 格式；最多保留 3 个短问题。')
      audit = auditChapterPayload(compact.payload)
    } catch (retryError) {
      fail(`第 ${chapterNum} 章审稿结构化失败`, trimText(retryError.message, 240))
      report.generated.auditFailures += 1
      return {
        summary: '审稿结构化失败，已作为质量门禁失败记录。',
        issues: [],
        auditFailed: true,
        error: trimText(retryError.message, 240)
      }
    }
  }
  pass(`第 ${chapterNum} 章审稿完成`, `issues=${audit.issues.length}`)
  return audit
}

async function reviseChapter(project, provider, chapterNum, content, audit) {
  if (!audit.issues.length) return content
  log(`开始基于审稿局部修订第 ${chapterNum} 章`)
  const issueBrief = audit.issues.slice(0, 5).map((item, index) =>
    `${index + 1}. [${item.severity || ''}/${item.type || ''}] ${item.issue || ''}\n位置：${item.location || ''}\n建议：${item.suggestion || ''}`
  ).join('\n\n')
  const text = await chat(provider, [
    { role: 'system', content: '你是小说局部修订助手。尽量只修有问题的段落，保留其他内容。只输出修订后的完整正文，不要解释。' },
    { role: 'user', content: `请根据审稿问题修订第 ${chapterNum} 章。不要大幅重写；保留原文结构和绝大多数段落。修正逻辑、动机、数值、AI腔问题。\n\n审稿问题：\n${issueBrief}\n\n原文：\n${content}` }
  ], { maxTokens: 9000, temperature: 0.45, timeoutMs: 360000 })
  const revised = text.trim() || content
  const drift = validateRevisionWordDrift(project, chapterNum, content, revised)
  return drift.ok ? revised : content
}

async function summarizeChapter(provider, chapterNum, content) {
  const text = await chat(provider, [
    { role: 'system', content: '你是长篇小说记忆压缩助手。输出 120-180 字中文摘要，不要 JSON。' },
    { role: 'user', content: `总结第 ${chapterNum} 章，保留人物选择、设定变化、结尾状态。\n\n正文：\n${content.slice(0, 9000)}` }
  ], { maxTokens: 600, temperature: 0.25 })
  return text.trim()
}

function extractCanonFactsPayload(payload) {
  const list = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.facts)
      ? payload.facts
      : []
  return list
    .filter(fact => fact && String(fact.content || '').trim())
    .slice(0, 4)
    .map(fact => ({
      factType: fact.factType || fact.type || 'plot',
      content: trimText(fact.content || fact.summary || '', 120),
      relatedCharacters: Array.isArray(fact.relatedCharacters) ? fact.relatedCharacters : [],
      evidence: trimText(fact.evidence || fact.quote || '', 120),
      confidence: Number(fact.confidence || 0.8)
    }))
}

async function extractCanonFacts(provider, project, chapterNum, content) {
  let facts = []
  try {
    const result = await chatJson(provider, [
      { role: 'system', content: '你是小说事实记忆提取器。只输出合法 JSON。' },
      { role: 'user', content: `从第 ${chapterNum} 章提取 2-4 条后续必须记住的事实，输出 {"facts":[{"factType":"plot|character|setting|relationship","content":"","relatedCharacters":[],"evidence":"","confidence":0.9}]}。\n\n正文：\n${content.slice(0, 10000)}` }
    ], {
      maxTokens: 2400,
      repairMaxTokens: 2400,
      retryMaxTokens: 3000,
      temperature: 0.2
    }, '请修复为 {"facts":[...]} 格式；最多保留 4 条事实。')
    facts = extractCanonFactsPayload(result.payload)
  } catch (error) {
    report.notes.push(`第 ${chapterNum} 章事实提取首次失败，已启用紧凑重试：${trimText(error.message, 180)}`)
    try {
      const compact = await chatJson(provider, [
        { role: 'system', content: '你是小说事实记忆提取器。只输出合法 JSON，不要解释。' },
        { role: 'user', content: `紧凑重试：从第 ${chapterNum} 章只提取 0-2 条最重要事实。每条 content 和 evidence 都必须少于 80 字。输出 {"facts":[{"factType":"plot|character|setting|relationship","content":"","relatedCharacters":[],"evidence":"","confidence":0.9}]}。如果没有必要事实，输出 {"facts":[]}。\n\n正文节选：\n${content.slice(0, 8000)}` }
      ], {
        maxTokens: 1400,
        repairMaxTokens: 1400,
        retryMaxTokens: 1800,
        temperature: 0.1
      }, '紧凑重试修复为 {"facts":[...]} 格式；最多保留 2 条短事实。')
      facts = extractCanonFactsPayload(compact.payload)
    } catch (retryError) {
      fail(`第 ${chapterNum} 章事实提取失败`, trimText(retryError.message, 240))
      return []
    }
  }

  for (const fact of facts) {
    await request('POST', `/projects/${project.id}/canon-facts`, {
      chapterNum,
      factType: fact.factType || 'plot',
      content: fact.content || '',
      relatedCharacters: fact.relatedCharacters || [],
      relatedPlotThreads: [],
      evidence: fact.evidence || '',
      confidence: Number(fact.confidence || 0.8),
      status: 'accepted'
    })
    report.generated.canonFacts += 1
  }
  return facts
}

function extractSettingChangesPayloadForQa(payload) {
  const list = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.changes)
      ? payload.changes
      : []
  return list
    .filter(change => change && String(change.entityName || '').trim() && String(change.newValue || '').trim())
    .slice(0, 4)
    .map(change => ({
      entityType: change.entityType || 'character',
      entityName: String(change.entityName || '').trim(),
      changeType: change.changeType || 'update',
      fieldPath: change.fieldPath || 'summary',
      newValue: trimText(change.newValue || change.summary || '', 160),
      evidence: trimText(change.evidence || '', 120),
      confidence: Number(change.confidence || 0.8)
    }))
}

async function extractChapterSettingChanges(provider, project, chapterNum, content) {
  let changes = []
  try {
    const result = await chatJson(provider, [
      { role: 'system', content: '你是设定变更提取器。只输出合法 JSON。仅提取本章之后仍会影响后文的变化，不要把普通描写当设定。' },
      { role: 'user', content: `从第 ${chapterNum} 章提取 0-4 条待确认设定变更，输出 {"changes":[{"entityType":"character|faction|location|power_system|technique|item","entityName":"","changeType":"new_entity|update|relation_change","fieldPath":"summary","newValue":"","evidence":"","confidence":0.8}]}。\n\n正文：\n${content.slice(0, 10000)}` }
    ], {
      maxTokens: 3000,
      repairMaxTokens: 3000,
      retryMaxTokens: 3600,
      temperature: 0.2
    }, '请修复为 {"changes":[...]} 格式；最多保留 4 条真正影响后文的设定变更。')
    changes = extractSettingChangesPayloadForQa(result.payload)
  } catch (error) {
    report.notes.push(`第 ${chapterNum} 章设定变更提取首次失败，已启用紧凑重试：${trimText(error.message, 180)}`)
    try {
      const compact = await chatJson(provider, [
        { role: 'system', content: '你是设定变更提取器。只输出合法 JSON，不要解释。' },
        { role: 'user', content: `紧凑重试：从第 ${chapterNum} 章提取 0-2 条后续必须同步的设定变更。每条 newValue 和 evidence 少于 100 字。输出 {"changes":[{"entityType":"character|faction|location|power_system|technique|item","entityName":"","changeType":"new_entity|update|relation_change","fieldPath":"summary","newValue":"","evidence":"","confidence":0.8}]}。没有则输出 {"changes":[]}。\n\n正文节选：\n${content.slice(0, 8000)}` }
      ], {
        maxTokens: 1600,
        repairMaxTokens: 1600,
        retryMaxTokens: 1800,
        temperature: 0.1
      }, '紧凑重试修复为 {"changes":[...]} 格式；最多保留 2 条短设定变更。')
      changes = extractSettingChangesPayloadForQa(compact.payload)
    } catch (retryError) {
      fail(`第 ${chapterNum} 章设定变更提取失败`, trimText(retryError.message, 240))
      return []
    }
  }

  for (const change of changes) {
    if (!change.entityName || !change.newValue) continue
    await request('POST', `/projects/${project.id}/settings/change-events`, {
      entityType: change.entityType || 'character',
      entityName: change.entityName,
      changeType: change.changeType || 'update',
      fieldPath: change.fieldPath || 'summary',
      oldValue: '',
      newValue: change.newValue,
      chapterNum,
      evidence: change.evidence || `第 ${chapterNum} 章自动提取`,
      confidence: Number(change.confidence || 0.8),
      status: 'pending_review'
    })
    report.generated.chapterSettingChanges += 1
  }
  return changes
}

async function createOrGetChapter(project, chapterNum) {
  const chapters = await request('GET', `/projects/${project.id}/chapters`)
  return chapters.find(item => Number(item.chapterNum) === chapterNum)
    || request('POST', `/projects/${project.id}/chapters`, { chapterNum, title: `第 ${chapterNum} 章` })
}

async function saveCandidate(project, chapter, title, content, type = 'ai_candidate', promptBrief = '真实流程测试') {
  return request('POST', `/projects/${project.id}/chapters/${chapter.id}/versions`, {
    title,
    content,
    versionType: type,
    promptBrief
  })
}

async function finalizeChapter(project, chapter, version, summary) {
  const count = wordCount(version.content)
  await request('POST', `/projects/${project.id}/chapters/${chapter.id}/versions/${version.id}/finalize`, {
    summary,
    wordCount: count
  })
  report.generated.finalizedChapters += 1
  recordFinalChapterWordCount(chapter.chapterNum, count)
  assessChapterWordCount(project, chapter.chapterNum, count, '定稿')
}

async function runChapter(project, provider, chapterNum, context) {
  const chapter = await createOrGetChapter(project, chapterNum)
  const beatPlan = await generateBeatPlan(project, provider, chapterNum, context)
  const firstContent = await generateChapterContent(project, provider, chapterNum, context, beatPlan)
  const firstVersion = await saveCandidate(project, chapter, `第 ${chapterNum} 章候选稿`, firstContent, 'ai_candidate', '按小纲生成章节')
  const audit = await auditChapter(provider, chapterNum, firstContent, context)
  if (audit.auditFailed) {
    const task = await request('POST', `/projects/${project.id}/correction-tasks`, {
      sourceType: 'chapter_audit',
      targetModule: 'chapter',
      title: `第 ${chapterNum} 章审稿结构化失败`,
      description: audit.error || 'AI 审稿没有返回可解析结构，不能视为本章无问题。',
      severity: 'major',
      issueType: 'audit_json_failed',
      chapterRefs: [chapterNum],
      relatedItems: [],
      suggestedAction: '重新审稿或人工检查本章后再继续判断质量。',
      status: 'pending',
      metadata: { auditFailed: true }
    })
    report.generated.correctionTasks += 1
    await request('PUT', `/projects/${project.id}/correction-tasks/${task.id}`, { status: 'ignored' })
    fail(`第 ${chapterNum} 章审稿质量门禁未通过`, '审稿结构化失败，已记录纠偏任务，不能当作零问题章节。')
  }

  for (const issue of audit.issues.slice(0, 5)) {
    const task = await request('POST', `/projects/${project.id}/correction-tasks`, {
      sourceType: 'chapter_audit',
      targetModule: 'chapter',
      title: issue.issue || `第 ${chapterNum} 章审稿问题`,
      description: issue.suggestion || '',
      severity: issue.severity || 'minor',
      issueType: issue.type || 'general',
      chapterRefs: [chapterNum],
      relatedItems: [],
      suggestedAction: issue.replacement || issue.suggestion || '',
      status: 'pending',
      metadata: { location: issue.location || '', replacement: issue.replacement || '' }
    })
    report.generated.correctionTasks += 1
    await request('PUT', `/projects/${project.id}/correction-tasks/${task.id}`, { status: 'ignored' })
  }

  const revisedContent = await reviseChapter(project, provider, chapterNum, firstContent, audit)
  let finalVersion = firstVersion
  if (revisedContent && revisedContent !== firstContent) {
    finalVersion = await saveCandidate(project, chapter, `第 ${chapterNum} 章审稿修订候选`, revisedContent, 'ai_candidate', '审稿后局部修订')
  }
  const summary = await summarizeChapter(provider, chapterNum, finalVersion.content)
  await finalizeChapter(project, chapter, finalVersion, summary)
  await request('PUT', `/projects/${project.id}/chapters/${chapter.id}/summary`, { summary })
  await extractCanonFacts(provider, project, chapterNum, finalVersion.content)
  await extractChapterSettingChanges(provider, project, chapterNum, finalVersion.content)
  pass(`第 ${chapterNum} 章已定稿并完成记忆/设定提取`, `${wordCount(finalVersion.content)} 字`)

  return {
    chapter,
    finalVersion,
    summary,
    ending: finalVersion.content.slice(-500),
    auditIssues: audit.issues.length
  }
}

async function runWritingFlow(project, provider, seed, bible) {
  const baseContext = [
    `项目目标：200 万字 / 400 章，单章约 5000 字。`,
    `种子：${seed.title}｜${seed.logline}`,
    `主角：${seed.protagonist}`,
    `核心矛盾：${seed.coreConflict}`,
    `圣经定位：${bible.premise}`,
    `风格规则：${bible.styleBible}`,
    `世界规则：${bible.worldRules}`,
    `禁止方向：${(bible.forbiddenDirections || []).join('；')}`
  ].join('\n')

  const ch1 = await runChapter(project, provider, 1, baseContext)

  const pendingAfterCh1 = await request('GET', `/projects/${project.id}/settings/change-events?status=pending_review`)
  assertCheck(pendingAfterCh1.length > 0, '第 1 章定稿后产生待确认设定变更', `pending=${pendingAfterCh1.length}`)
  for (const event of pendingAfterCh1.slice(0, 3)) {
    await request('POST', `/projects/${project.id}/settings/change-events/${event.id}/accept`)
  }
  if (pendingAfterCh1.length > 3) {
    await request('POST', `/projects/${project.id}/settings/change-events/${pendingAfterCh1[3].id}/reject`)
  }
  pass('章节设定变更已人工确认/拒绝一部分', `handled=${Math.min(4, pendingAfterCh1.length)}`)

  const ch2Context = `${baseContext}\n\n上一章摘要：${ch1.summary}\n上一章结尾：${ch1.ending}`
  const ch2 = await runChapter(project, provider, 2, ch2Context)

  const chapter2 = await createOrGetChapter(project, 2)
  await request('POST', `/projects/${project.id}/chapters/${chapter2.id}/versions/${ch2.finalVersion.id}/finalize`, {
    summary: ch2.summary,
    wordCount: wordCount(ch2.finalVersion.content)
  }, [200])
  pass('重复点击同一定稿版本具备幂等性', '同 finalVersionId 再次定稿成功')

  const chapter3 = await createOrGetChapter(project, 3)
  const tempVersion = await saveCandidate(project, chapter3, '第 3 章临时候选', '这是一段用于测试候选删除的临时内容。', 'ai_candidate', '删除测试')
  await request('DELETE', `/projects/${project.id}/chapters/${chapter3.id}/versions/${tempVersion.id}`)
  pass('未定稿章节候选版本可删除', '第 3 章临时候选')

  await request('DELETE', `/projects/${project.id}/chapters/${chapter3.id}`)
  pass('未定稿且无资产章节可删除', '第 3 章')

  return { ch1, ch2 }
}

async function loadFinalizedChapter(project, chapterNum) {
  const chapters = await request('GET', `/projects/${project.id}/chapters`)
  const chapter = chapters.find(item => Number(item.chapterNum) === chapterNum)
  if (!chapter) return null
  const versions = await request('GET', `/projects/${project.id}/chapters/${chapter.id}/versions`)
  const finalVersion = versions.find(item => item.id === chapter.finalVersionId)
    || versions.find(item => item.versionType === 'final')
  if (!finalVersion) return null
  return {
    chapter,
    finalVersion,
    summary: chapter.summary || finalVersion.content?.slice(0, 300) || '',
    ending: finalVersion.content?.slice(-500) || '',
    auditIssues: 0
  }
}

async function handlePendingSettingChanges(project, reason = '') {
  const pending = await request('GET', `/projects/${project.id}/settings/change-events?status=pending_review`)
  if (!pending.length) return { accepted: 0, rejected: 0 }

  let accepted = 0
  let rejected = 0
  for (const event of pending) {
    const shouldAccept = Boolean(event.entityName && event.newValue && Number(event.confidence ?? 0.8) >= 0.65)
    if (shouldAccept) {
      await request('POST', `/projects/${project.id}/settings/change-events/${event.id}/accept`)
      accepted += 1
      report.generated.acceptedSettings += 1
    } else {
      await request('POST', `/projects/${project.id}/settings/change-events/${event.id}/reject`)
      rejected += 1
    }
  }
  pass('待确认设定变更已模拟人工处理', `${reason} accepted=${accepted}, rejected=${rejected}`)
  return { accepted, rejected }
}

async function backfillMissingFinalizedPostprocess(project, provider, finalizedNums) {
  const facts = await request('GET', `/projects/${project.id}/canon-facts`)
  const factChapters = new Set(facts.map(item => Number(item.chapterNum || 0)).filter(Boolean))

  for (const chapterNum of finalizedNums) {
    const finalized = await loadFinalizedChapter(project, chapterNum)
    if (!finalized?.finalVersion?.content) continue

    if (!factChapters.has(chapterNum)) {
      log(`第 ${chapterNum} 章已定稿但缺少事实记忆，开始补提取`)
      const extractedFacts = await extractCanonFacts(provider, project, chapterNum, finalized.finalVersion.content)
      if (extractedFacts.length) {
        pass('补齐已定稿章节事实记忆', `第 ${chapterNum} 章 facts=${extractedFacts.length}`)
      } else {
        fail('补齐已定稿章节事实记忆', `第 ${chapterNum} 章没有提取到事实`)
      }
    }

    const events = await request('GET', `/projects/${project.id}/settings/change-events?chapterNum=${chapterNum}`)
    if (!events.length) {
      log(`第 ${chapterNum} 章已定稿但缺少设定变更记录，开始补提取`)
      const changes = await extractChapterSettingChanges(provider, project, chapterNum, finalized.finalVersion.content)
      if (changes.length) {
        pass('补齐已定稿章节设定变更', `第 ${chapterNum} 章 changes=${changes.length}`)
        await handlePendingSettingChanges(project, `补齐第 ${chapterNum} 章定稿后处理`)
      } else {
        pass('补齐已定稿章节设定变更', `第 ${chapterNum} 章无必要设定变更`)
      }
    }
  }
}

async function buildContinuationContext(project, chapterNum) {
  const [seeds, bible, chapters, entities, facts, settingEvents] = await Promise.all([
    request('GET', `/projects/${project.id}/seeds`).catch(() => []),
    request('GET', `/projects/${project.id}/bible`).catch(() => null),
    request('GET', `/projects/${project.id}/chapters`),
    request('GET', `/projects/${project.id}/settings/entities`).catch(() => []),
    request('GET', `/projects/${project.id}/canon-facts`).catch(() => []),
    request('GET', `/projects/${project.id}/settings/change-events`).catch(() => [])
  ])

  const selectedSeed = seeds.find(seed => seed.status === 'selected') || seeds[0] || {}
  const previousChapters = chapters
    .filter(item => Number(item.chapterNum) < chapterNum && item.finalVersionId)
    .sort((a, b) => Number(b.chapterNum) - Number(a.chapterNum))
    .slice(0, 4)

  const previousDetails = []
  for (const chapter of previousChapters) {
    const versions = await request('GET', `/projects/${project.id}/chapters/${chapter.id}/versions`)
    const finalVersion = versions.find(item => item.id === chapter.finalVersionId)
      || versions.find(item => item.versionType === 'final')
    previousDetails.push([
      `第 ${chapter.chapterNum} 章摘要：${chapter.summary || '暂无摘要'}`,
      `第 ${chapter.chapterNum} 章结尾：${trimText(finalVersion?.content?.slice(-420) || '', 420)}`
    ].join('\n'))
  }

  const settingSummary = entities.slice(0, 30).map(item =>
    `${item.entityType || item.type}｜${item.entityName || item.name}｜${item.category || ''}｜${trimText(item.summary || '', 120)}`
  ).join('\n')

  const factSummary = facts.slice(0, 25).map(item =>
    `第${item.chapterNum || '?'}章｜${item.factType || 'plot'}｜${trimText(item.content || '', 120)}`
  ).join('\n')

  const acceptedChanges = settingEvents
    .filter(item => item.status === 'accepted')
    .slice(0, 20)
    .map(item => `${item.entityName} ${item.fieldPath}: ${trimText(item.newValue || '', 120)}`)
    .join('\n')

  return [
    `项目目标：${project.targetWords || 2000000} 字 / ${project.targetChapters || 400} 章，单章约 5000 字。`,
    `当前任务：生成第 ${chapterNum} 章，必须自然承接上一章结尾，避免跳场和断层。`,
    `创作种子：${JSON.stringify(selectedSeed)}`,
    `创作圣经：${JSON.stringify(bible || {})}`,
    `最近章节：\n${previousDetails.join('\n\n')}`,
    `设定库：\n${settingSummary || '暂无'}`,
    `已确认记忆事实：\n${factSummary || '暂无'}`,
    `已确认设定变更：\n${acceptedChanges || '暂无'}`
  ].join('\n\n')
}

async function loadFinalizedChapters(project, startChapter = 1, endChapter = Number.MAX_SAFE_INTEGER) {
  const chapters = await request('GET', `/projects/${project.id}/chapters`)
  const targets = chapters
    .filter(item => item.finalVersionId)
    .filter(item => Number(item.chapterNum) >= startChapter && Number(item.chapterNum) <= endChapter)
    .sort((a, b) => Number(a.chapterNum) - Number(b.chapterNum))

  const out = []
  for (const chapter of targets) {
    const versions = await request('GET', `/projects/${project.id}/chapters/${chapter.id}/versions`)
    const finalVersion = versions.find(item => item.id === chapter.finalVersionId)
      || versions.find(item => item.versionType === 'final')
    if (!finalVersion?.content) continue
    const count = wordCount(finalVersion.content)
    recordFinalChapterWordCount(chapter.chapterNum, count)
    out.push({
      chapter,
      finalVersion,
      chapterNum: Number(chapter.chapterNum),
      summary: chapter.summary || trimText(finalVersion.content, 260),
      wordCount: count,
      opening: trimText(finalVersion.content.slice(0, 520), 520),
      ending: trimText(finalVersion.content.slice(-520), 520)
    })
  }
  return out
}

function normalizeAcceptancePayload(payload) {
  const issues = Array.isArray(payload?.issues) ? payload.issues : []
  return {
    overall: trimText(payload?.overall || payload?.summary || '', 800),
    safeToContinue: payload?.safeToContinue !== false,
    checks: payload?.checks && typeof payload.checks === 'object' ? payload.checks : {},
    issues: issues.slice(0, 10).map(item => ({
      severity: item.severity || 'minor',
      type: item.type || 'quality',
      chapters: Array.isArray(item.chapters) ? item.chapters : [],
      title: trimText(item.title || item.issue || '', 140),
      detail: trimText(item.detail || item.description || '', 400),
      suggestedAction: trimText(item.suggestedAction || item.suggestion || '', 360)
    }))
  }
}

async function runMultiChapterAcceptance(project, provider, startChapter = 1, endChapter = 20) {
  log(`开始多章一致性验收：第 ${startChapter}-${endChapter} 章`)
  const finalized = await loadFinalizedChapters(project, startChapter, endChapter)
  if (finalized.length < 2) {
    report.generated.multiChapterAcceptance = {
      skipped: true,
      reason: '少于 2 个已定稿章节',
      chapters: finalized.length
    }
    pass('多章一致性验收跳过', `finalized=${finalized.length}`)
    return report.generated.multiChapterAcceptance
  }

  const [entities, facts, pendingEvents] = await Promise.all([
    request('GET', `/projects/${project.id}/settings/entities`).catch(() => []),
    request('GET', `/projects/${project.id}/canon-facts`).catch(() => []),
    request('GET', `/projects/${project.id}/settings/change-events?status=pending_review`).catch(() => [])
  ])
  const finalizedNums = finalized.map(item => item.chapterNum)
  const factChapters = new Set(facts.map(item => Number(item.chapterNum || 0)).filter(Boolean))
  const missingFactChapters = finalizedNums.filter(num => !factChapters.has(num))
  const range = expectedChapterWordRange(project)
  const wordOutliers = finalized
    .filter(item => item.wordCount < range.hardMin || item.wordCount > range.hardMax)
    .map(item => ({ chapterNum: item.chapterNum, count: item.wordCount }))

  assertCheck(missingFactChapters.length === 0, '多章验收：定稿章节均有记忆事实', missingFactChapters.length ? `missing=${missingFactChapters.join(',')}` : `chapters=${finalized.length}`)
  assertCheck(pendingEvents.length === 0, '多章验收：无待确认设定变更阻塞后续生成', `pending=${pendingEvents.length}`)
  assertCheck(wordOutliers.length === 0, '多章验收：定稿章节字数未硬性越界', wordOutliers.length ? JSON.stringify(wordOutliers) : `range=${range.hardMin}-${range.hardMax}`)

  const chapterBrief = finalized.slice(-20).map(item => [
    `第 ${item.chapterNum} 章，${item.wordCount} 字`,
    `摘要：${item.summary || '暂无'}`,
    `开头：${item.opening}`,
    `结尾：${item.ending}`
  ].join('\n')).join('\n\n')
  const settingBrief = entities.slice(0, 40).map(item =>
    `${item.entityType || item.type}:${item.entityName || item.name}｜${item.category || ''}｜${trimText(item.summary || '', 140)}`
  ).join('\n')
  const factBrief = facts.slice(-80).map(item =>
    `第${item.chapterNum || '?'}章 ${item.factType || 'plot'}：${trimText(item.content || '', 140)}`
  ).join('\n')

  try {
    const result = await chatJson(provider, [
      {
        role: 'system',
        content: [
          '你是长篇小说多章验收编辑。只输出合法 JSON，不要 Markdown。',
          '必须检查 character_drift、plot_contradiction、timeline、world_rule、foreshadowing、repetition、style_drift、state_carryover、boundary_continuity、setting_sync。',
          '只记录会影响后续 20 章继续生成的问题，不要泛泛评价。'
        ].join('\n')
      },
      {
        role: 'user',
        content: `请验收第 ${startChapter}-${endChapter} 章是否适合继续写下去。输出 {"overall":"","safeToContinue":true,"checks":{"character_drift":"pass|warn|fail","plot_contradiction":"pass|warn|fail","timeline":"pass|warn|fail","world_rule":"pass|warn|fail","foreshadowing":"pass|warn|fail","repetition":"pass|warn|fail","style_drift":"pass|warn|fail","state_carryover":"pass|warn|fail","boundary_continuity":"pass|warn|fail","setting_sync":"pass|warn|fail"},"issues":[{"severity":"critical|major|minor|suggestion","type":"character_drift|plot_contradiction|timeline|world_rule|foreshadowing|repetition|style_drift|state_carryover|boundary_continuity|setting_sync","chapters":[1,2],"title":"","detail":"","suggestedAction":""}]}。\n\n章节材料：\n${chapterBrief}\n\n设定库：\n${settingBrief || '暂无'}\n\n记忆事实：\n${factBrief || '暂无'}`
      }
    ], {
      maxTokens: 5000,
      repairMaxTokens: 4200,
      retryMaxTokens: 5000,
      temperature: 0.2,
      timeoutMs: 300000
    }, '修复为 {"overall":"","safeToContinue":true,"checks":{},"issues":[...]} 格式；最多 10 个问题。')

    const acceptance = normalizeAcceptancePayload(result.payload)
    const hardIssues = acceptance.issues.filter(item => ['critical', 'major'].includes(item.severity))
    report.generated.multiChapterAcceptance = {
      startChapter,
      endChapter,
      finalizedChapters: finalized.length,
      wordRange: range,
      missingFactChapters,
      pendingSettingEvents: pendingEvents.length,
      wordOutliers,
      ...acceptance
    }
    assertCheck(acceptance.safeToContinue && hardIssues.length === 0, '多章一致性验收通过', `issues=${acceptance.issues.length}, hard=${hardIssues.length}`)
    return report.generated.multiChapterAcceptance
  } catch (error) {
    report.generated.multiChapterAcceptance = {
      startChapter,
      endChapter,
      finalizedChapters: finalized.length,
      failed: true,
      error: trimText(error.message, 400),
      wordRange: range,
      missingFactChapters,
      pendingSettingEvents: pendingEvents.length,
      wordOutliers
    }
    fail('多章一致性验收结构化失败', trimText(error.message, 260))
    return report.generated.multiChapterAcceptance
  }
}

async function continueWritingFlow(project, provider, toChapter) {
  const chapters = await request('GET', `/projects/${project.id}/chapters`)
  const finalizedNums = new Set(chapters.filter(item => item.finalVersionId).map(item => Number(item.chapterNum)))
  const maxFinalized = Math.max(0, ...finalizedNums)
  const startChapter = Math.max(1, maxFinalized + 1)
  await backfillMissingFinalizedPostprocess(
    project,
    provider,
    Array.from(finalizedNums).sort((a, b) => a - b)
  )

  if (toChapter < startChapter) {
    pass('续写章节无需执行', `已定稿到第 ${maxFinalized} 章，目标第 ${toChapter} 章`)
    return {
      ch1: await loadFinalizedChapter(project, 1),
      ch2: await loadFinalizedChapter(project, 2)
    }
  }

  await handlePendingSettingChanges(project, `续写前，第 ${startChapter} 章之前`)

  let lastResult = null
  for (let chapterNum = startChapter; chapterNum <= toChapter; chapterNum += 1) {
    const context = await buildContinuationContext(project, chapterNum)
    lastResult = await runChapter(project, provider, chapterNum, context)
    await handlePendingSettingChanges(project, `第 ${chapterNum} 章定稿后`)
  }

  pass('真实流程续写到目标章数', `第 ${startChapter}-${toChapter} 章，最后一章 ${wordCount(lastResult?.finalVersion?.content || '')} 字`)
  return {
    ch1: await loadFinalizedChapter(project, 1),
    ch2: await loadFinalizedChapter(project, 2),
    last: lastResult
  }
}

async function runGlobalAudit(project, provider, chapters) {
  log('开始项目级审稿')
  const result = await chatJson(provider, [
    { role: 'system', content: '你是长篇小说全局审稿人。只输出合法 JSON。' },
    { role: 'user', content: `基于当前前两章，做一次项目级审稿。输出 {"overall":"","issues":[{"severity":"major|minor|suggestion","type":"continuity|setting|pacing|motivation|ai_tone","title":"","description":"","suggestedAction":""}]}。\n\n第1章摘要：${chapters.ch1.summary}\n\n第2章摘要：${chapters.ch2.summary}` }
  ], { maxTokens: 4000, repairMaxTokens: 4000, temperature: 0.25 }, '修复为 {"overall":"","issues":[...]} 格式；保留最多 5 个问题。')
  const payload = result.payload
  await request('POST', `/projects/${project.id}/global-audits`, {
    reportType: 'global',
    title: '真实流程测试项目级审稿',
    report: payload
  })
  const issues = Array.isArray(payload.issues) ? payload.issues : []
  for (const issue of issues.slice(0, 5)) {
    await request('POST', `/projects/${project.id}/correction-tasks`, {
      sourceType: 'global_audit',
      targetModule: 'global',
      title: issue.title || issue.description || '项目级审稿问题',
      description: issue.description || '',
      severity: issue.severity || 'minor',
      issueType: issue.type || 'general',
      chapterRefs: [],
      relatedItems: [],
      suggestedAction: issue.suggestedAction || '',
      status: 'pending',
      metadata: {}
    })
    report.generated.correctionTasks += 1
  }
  pass('项目级审稿已保存', `issues=${issues.length}`)
}

async function loadResumeChapters(project) {
  const chapters = await request('GET', `/projects/${project.id}/chapters`)
  const out = {}
  for (const chapterNum of [1, 2]) {
    const chapter = chapters.find(item => Number(item.chapterNum) === chapterNum)
    if (!chapter) throw new Error(`续跑找不到第 ${chapterNum} 章`)
    const versions = await request('GET', `/projects/${project.id}/chapters/${chapter.id}/versions`)
    const finalVersion = versions.find(item => item.id === chapter.finalVersionId)
      || versions.find(item => item.versionType === 'final')
      || versions[0]
    out[`ch${chapterNum}`] = {
      chapter,
      finalVersion,
      summary: chapter.summary || finalVersion?.content?.slice(0, 300) || ''
    }
  }
  return out
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl
    this.nextId = 1
    this.pending = new Map()
    this.listeners = new Map()
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl)
    this.ws.onmessage = event => {
      const msg = JSON.parse(event.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        if (msg.error) reject(new Error(msg.error.message))
        else resolve(msg.result)
        return
      }
      if (msg.method && this.listeners.has(msg.method)) {
        for (const listener of this.listeners.get(msg.method)) listener(msg.params)
      }
    }
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve
      this.ws.onerror = reject
    })
  }

  send(method, params = {}) {
    const id = this.nextId++
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }))
  }

  on(method, listener) {
    if (!this.listeners.has(method)) this.listeners.set(method, new Set())
    this.listeners.get(method).add(listener)
    return () => this.listeners.get(method)?.delete(listener)
  }

  waitEvent(method, timeoutMs = 15000) {
    return new Promise((resolve, reject) => {
      const off = this.on(method, params => {
        clearTimeout(timer)
        off()
        resolve(params)
      })
      const timer = setTimeout(() => {
        off()
        reject(new Error(`等待 CDP 事件超时：${method}`))
      }, timeoutMs)
    })
  }

  close() {
    this.ws?.close()
  }
}

async function launchChrome() {
  if (!existsSync(CHROME_PATH)) throw new Error(`未找到 Chrome：${CHROME_PATH}`)
  if (existsSync(PROFILE_DIR)) {
    try { rmSync(PROFILE_DIR, { recursive: true, force: true }) } catch {}
  }
  mkdirSync(PROFILE_DIR, { recursive: true })
  const port = 9400 + Math.floor(Math.random() * 400)
  const proc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${PROFILE_DIR}`,
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--no-sandbox',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    'about:blank'
  ], { stdio: ['ignore', 'ignore', 'ignore'], windowsHide: true })
  started.push({ proc, name: 'chrome' })
  await waitForHttp(`http://127.0.0.1:${port}/json/version`, 20000)
  const tabs = await fetch(`http://127.0.0.1:${port}/json/list`).then(res => res.json())
  const page = tabs.find(item => item.type === 'page') || tabs[0]
  const client = new CdpClient(page.webSocketDebuggerUrl)
  await client.connect()
  await client.send('Page.enable')
  await client.send('Runtime.enable')
  await client.send('Log.enable')
  client.on('Runtime.exceptionThrown', params => {
    report.browserConsole.push({ type: 'exception', text: params?.exceptionDetails?.text || '' })
  })
  client.on('Runtime.consoleAPICalled', params => {
    if (params.type === 'error') {
      report.browserConsole.push({ type: 'console.error', text: (params.args || []).map(arg => arg.value || arg.description || '').join(' ') })
    }
  })
  return client
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'Runtime.evaluate failed')
  return result.result?.value
}

async function navigate(client, url, key) {
  const startedAt = Date.now()
  const load = client.waitEvent('Page.loadEventFired', 25000).catch(() => null)
  await client.send('Page.navigate', { url })
  await load
  await sleep(1200)
  report.timings[key] = Date.now() - startedAt
}

async function screenshot(client, name) {
  const result = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  const file = join(REPORT_DIR, `${name}.png`)
  writeFileSync(file, Buffer.from(result.data, 'base64'))
  report.screenshots.push(file)
}

async function browserSmoke(project) {
  log('开始浏览器 UI 验收')
  const client = await launchChrome()
  try {
    await navigate(client, `${APP_URL}/project/${project.id}`, 'projectLoadMs')
    let text = await evaluate(client, 'document.body.innerText')
    assertCheck(text.includes(project.title), '项目详情页可打开', project.title)
    for (const label of ['选题雷达', '创作种子', '创作圣经', '设定库', '章节管理', '纠偏任务']) {
      assertCheck(text.includes(label), `项目详情页显示模块：${label}`)
    }
    await screenshot(client, 'project-detail')

    await navigate(client, `${APP_URL}/writer/${project.id}/1`, 'writerChapter1LoadMs')
    text = await evaluate(client, 'document.body.innerText')
    assertCheck(text.includes(project.title), '写字台可打开')
    assertCheck(text.includes('本章审稿') || text.includes('审稿'), '写字台审稿入口可见')
    assertCheck(text.includes('项目详情'), '写字台返回项目详情入口可见')
    await screenshot(client, 'writer-chapter-1')

    const domStats = await evaluate(client, `({
      nodes: document.querySelectorAll('*').length,
      textLength: document.body.innerText.length,
      memory: performance.memory ? {
        usedJSHeapSize: performance.memory.usedJSHeapSize,
        totalJSHeapSize: performance.memory.totalJSHeapSize
      } : null
    })`)
    report.generated.domStats = domStats
    pass('浏览器 UI 基础验收完成', `nodes=${domStats.nodes}, text=${domStats.textLength}`)
  } finally {
    client.close()
  }
}

async function cleanupProject(project) {
  if (!project?.id || KEEP_PROJECT) return
  await request('DELETE', `/projects/${project.id}`)
  report.cleanup = `已删除测试项目 ${project.id}`
}

function formatChapterWordCountReport() {
  const finalCounts = report.generated.finalChapterWordCounts || []
  const counts = finalCounts.length ? finalCounts : (report.generated.chapterWordCounts || [])
  return counts
    .slice()
    .sort((a, b) => Number(a.chapterNum) - Number(b.chapterNum))
    .map(item => `第${item.chapterNum}章 ${item.count}字`)
    .join('；')
}

function formatMultiChapterAcceptanceReport() {
  const acceptance = report.generated.multiChapterAcceptance
  if (!acceptance) return ['- 尚未执行']
  if (acceptance.skipped) return [`- 已跳过：${acceptance.reason}`]
  if (acceptance.failed) return [
    `- 结构化失败：${acceptance.error || ''}`,
    `- 已定稿章节：${acceptance.finalizedChapters || 0}`,
    `- 待确认设定：${acceptance.pendingSettingEvents ?? 0}`,
    `- 字数越界：${JSON.stringify(acceptance.wordOutliers || [])}`
  ]
  const issueLines = (acceptance.issues || []).length
    ? acceptance.issues.map(item => `- [${item.severity}/${item.type}] 第${(item.chapters || []).join(',')}章：${item.title || item.detail || ''}；建议：${item.suggestedAction || ''}`)
    : ['- 未发现阻塞继续生成的多章问题']
  return [
    `- 范围：第 ${acceptance.startChapter}-${acceptance.endChapter} 章`,
    `- 是否适合继续：${acceptance.safeToContinue ? '是' : '否'}`,
    `- 总评：${acceptance.overall || '暂无'}`,
    `- 待确认设定：${acceptance.pendingSettingEvents ?? 0}`,
    `- 缺少记忆章节：${(acceptance.missingFactChapters || []).join(',') || '无'}`,
    `- 字数越界：${JSON.stringify(acceptance.wordOutliers || [])}`,
    ...issueLines
  ]
}

function writeReport() {
  report.finishedAt = new Date().toISOString()
  const failed = report.checks.filter(item => item.status === 'fail')
  report.summary = {
    totalChecks: report.checks.length,
    passedChecks: report.checks.length - failed.length,
    failedChecks: failed.length,
    browserConsoleErrors: report.browserConsole.length
  }
  const jsonFile = join(REPORT_DIR, 'latest-realistic-report.json')
  const mdFile = join(REPORT_DIR, 'latest-realistic-report.md')
  writeFileSync(jsonFile, JSON.stringify(report, null, 2), 'utf8')
  const md = [
    '# Novel Creator 真实流程长篇测试报告',
    '',
    `- 时间：${report.startedAt} - ${report.finishedAt}`,
    `- 项目：${report.project?.title || ''}`,
    `- 项目地址：${report.project?.url || ''}`,
    `- 目标规模：${report.project?.targetWords || 0} 字 / ${report.project?.targetChapters || 0} 章`,
    `- 使用模型：${report.provider?.name || ''} / ${report.provider?.model || ''} / ${report.provider?.apiKey || ''}`,
    `- 检查：${report.summary.passedChecks}/${report.summary.totalChecks} 通过`,
    `- 浏览器控制台错误：${report.summary.browserConsoleErrors}`,
    `- 项目处理：${report.cleanup}`,
    '',
    '## 生成与数据量',
    `- 热点数据：${report.generated.marketItems}`,
    `- 方向建议：${report.generated.directions}`,
    `- 种子：${report.generated.seeds}`,
    `- 初始设定候选：${report.generated.settingEvents}`,
    `- 已确认设定：${report.generated.acceptedSettings}`,
    `- 章节骨架：${report.generated.chaptersCreated}`,
    `- 已定稿章节：${report.generated.finalizedChapters}`,
    `- 记忆事实：${report.generated.canonFacts}`,
    `- 章节设定变更：${report.generated.chapterSettingChanges}`,
    `- 纠偏任务：${report.generated.correctionTasks}`,
    `- 章节字数：${formatChapterWordCountReport()}`,
    `- 审稿结构化失败：${report.generated.auditFailures}`,
    '',
    '## 多章一致性验收',
    ...formatMultiChapterAcceptanceReport(),
    '',
    '## 检查项',
    ...report.checks.map(item => `- ${item.status === 'pass' ? '[x]' : '[ ]'} ${item.name}${item.detail ? `：${item.detail}` : ''}`),
    '',
    '## 主要观察',
    ...(
      report.notes.length
        ? report.notes.map(item => `- ${item}`)
        : ['- 本轮重点验证真实流程可跑通，完整 200 万字正文没有一次性生成，避免不必要的 API 成本。']
    ),
    '',
    '## 页面耗时',
    ...Object.entries(report.timings).map(([key, value]) => `- ${key}: ${value}ms`),
    '',
    '## 截图',
    ...report.screenshots.map(file => `- ${file}`),
    '',
    '## 浏览器控制台错误',
    ...(report.browserConsole.length ? report.browserConsole.map(item => `- ${item.type}: ${item.text}`) : ['- 无'])
  ].join('\n')
  writeFileSync(mdFile, md, 'utf8')
  log(`REPORT_JSON ${jsonFile}`)
  log(`REPORT_MD ${mdFile}`)
  return { jsonFile, mdFile }
}

async function main() {
  await ensureBackend()
  await ensureFrontend()
  const provider = await getPreferredProvider()
  let project = null
  try {
    const resumeProjectId = process.env.RESUME_REALISTIC_QA_PROJECT_ID || ''
    let chapters = null
    if (resumeProjectId) {
      const previousReportPath = join(REPORT_DIR, 'latest-realistic-report.json')
      if (existsSync(previousReportPath)) {
        try {
          const previous = JSON.parse(await import('node:fs').then(fs => fs.readFileSync(previousReportPath, 'utf8')))
          if (previous?.project?.id === resumeProjectId) {
            report.generated = previous.generated || report.generated
            report.notes = previous.notes || report.notes
          }
        } catch {
          // Resume can continue without previous report metadata.
        }
      }
      project = await request('GET', `/projects/${resumeProjectId}`)
      report.project = {
        id: project.id,
        title: project.title,
        targetWords: project.targetWords,
        targetChapters: project.targetChapters,
        url: `${APP_URL}/project/${project.id}`
      }
      pass('续跑已有测试项目', project.title)
      chapters = await loadResumeChapters(project)
      if (CONTINUE_TO_CHAPTER > 0) {
        chapters = await continueWritingFlow(project, provider, CONTINUE_TO_CHAPTER)
      }
    } else {
      project = await createProject(provider)
      const { seed } = await runMarketAndSeed(project, provider)
      const { bible } = await runBibleAndSettings(project, provider, seed)
      await createVolumesAndChapters(project)
      chapters = await runWritingFlow(project, provider, seed, bible)
    }
    const finalizedForAcceptance = await loadFinalizedChapters(project, 1, CONTINUE_TO_CHAPTER || 9999)
    const acceptanceEnd = Math.max(0, ...finalizedForAcceptance.map(item => item.chapterNum))
    if (acceptanceEnd > 0) {
      const acceptanceStart = Math.max(1, acceptanceEnd - 19)
      await runMultiChapterAcceptance(project, provider, acceptanceStart, acceptanceEnd)
    }
    await runGlobalAudit(project, provider, chapters)
    await browserSmoke(project)
    await cleanupProject(project)
  } catch (error) {
    fail('真实流程测试执行失败', error.stack || error.message)
    throw error
  } finally {
    const files = writeReport()
    for (const item of started.reverse()) {
      try { item.proc?.kill?.() } catch {}
      try { if (item.out) closeSync(item.out) } catch {}
      try { if (item.err) closeSync(item.err) } catch {}
    }
    try {
      rmSync(PROFILE_DIR, { recursive: true, force: true, maxRetries: 3, retryDelay: 300 })
    } catch {}
    const failed = report.checks.filter(item => item.status === 'fail')
    if (failed.length) process.exitCode = 1
    console.log(`REPORT_FILES ${files.jsonFile} ${files.mdFile}`)
  }
}

main().catch(() => {})
