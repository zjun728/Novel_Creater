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
import {
  applyLocalRevisionPatches,
  extractLocalRevisionPatches
} from '../frontend/src/utils/localRevisionPatch.js'
import {
  analyzeProseRhythm,
  countCjkChars,
  formatProseRhythmAnalysis,
  shouldRepairProseRhythm
} from '../frontend/src/utils/proseRhythmGuard.js'
import { buildChapterStateLedger } from '../frontend/src/utils/chapterStateLedger.js'
import { buildWritingContext } from '../frontend/src/utils/contextBuilder.js'
import { buildChapterWordTarget } from '../frontend/src/utils/chapterWordTarget.js'
import {
  buildChapterBeatPrompt,
  buildChapterBeatSystemPrompt,
  buildChapterPrompt,
  buildChapterSystemPrompt,
  buildChapterTitlePrompt,
  buildChapterTitleSystemPrompt,
  cleanChapterBeatPlanText,
  cleanGeneratedChapterText,
  cleanGeneratedChapterTitle,
  isDefaultChapterTitle
} from '../frontend/src/prompts/chapter.js'

const ROOT = resolve('.')
const API_BASE = 'http://127.0.0.1:8000/api'
const APP_URL = 'http://127.0.0.1:5173'
const CHROME_PATH = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const REPORT_DIR = join(ROOT, 'tmp', 'realistic-flow-qa')
const PROFILE_DIR = join(REPORT_DIR, 'chrome-profile')
const LOG_FILE = join(REPORT_DIR, 'run.log')
const KEEP_PROJECT = process.env.DELETE_REALISTIC_QA_PROJECT !== '1'
const CONTINUE_TO_CHAPTER = Number(process.env.CONTINUE_REALISTIC_QA_TO_CHAPTER || 0)
const INITIAL_TO_CHAPTER = Number(process.env.REALISTIC_QA_INITIAL_TO_CHAPTER || 0)
const QA_PROJECT_PREFIX = process.env.REALISTIC_QA_PROJECT_PREFIX || 'RealisticQAFlow'
const QA_PRIMARY_STANDARD = process.env.REALISTIC_QA_PRIMARY_STANDARD || 'rational-fantasy'
const QA_SECONDARY_FLAVOR = process.env.REALISTIC_QA_SECONDARY_FLAVOR || 'suspense-hook'
const QA_STYLE_NOTES = process.env.REALISTIC_QA_STYLE_NOTES || 'Keep scene control, emotional realism, and narrative momentum balanced. Avoid rigid templated sentence patterns.'
const MAX_JSON_SCAN_CHARS = 30000
const MAX_JSON_CANDIDATES = 8
const IGNORE_WORD_COUNT_GATE = process.env.IGNORE_WORD_COUNT_GATE === '1' || process.env.IGNORE_WORD_COUNT_GATE === 'true'

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
  cleanup: KEEP_PROJECT ? '淇濈暀娴嬭瘯椤圭洰' : null,
  notes: []
}

function normalizeGeneratedReport(generated = {}) {
  const base = {
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
  }
  const merged = { ...base, ...(generated || {}) }
  merged.chapterWordCounts = Array.isArray(merged.chapterWordCounts) ? merged.chapterWordCounts : []
  merged.finalChapterWordCounts = Array.isArray(merged.finalChapterWordCounts) ? merged.finalChapterWordCounts : []
  merged.auditFailures = Number(merged.auditFailures || 0)
  if (merged.multiChapterAcceptance === undefined) merged.multiChapterAcceptance = null
  return merged
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
  if (!key) return '鏈厤缃?
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
  throw new Error(`绛夊緟鏈嶅姟瓒呮椂锛?{url}锛涙渶鍚庨敊璇細${lastError}`)
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
    pass('鍚庣鏈嶅姟鍙敤')
    return
  } catch {
    log('鍚庣鏈惎鍔紝灏濊瘯鍚姩 uvicorn')
    const out = openSync(join(REPORT_DIR, 'backend.log'), 'a')
    const err = openSync(join(REPORT_DIR, 'backend.err.log'), 'a')
    const proc = spawn('D:/Software/Python/Python312/python.exe', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], {
      cwd: join(ROOT, 'backend'),
      stdio: ['ignore', out, err],
      windowsHide: true
    })
    started.push({ proc, out, err, name: 'backend' })
    await waitForHttp(`${API_BASE}/health`, 45000)
    pass('鍚庣鏈嶅姟宸茬敱鑴氭湰鍚姩')
  }
}

async function ensureFrontend() {
  try {
    await waitForHttp(APP_URL, 2500)
    pass('鍓嶇鏈嶅姟鍙敤')
    return
  } catch {
    log('鍓嶇鏈惎鍔紝灏濊瘯鍚姩 Vite')
    const out = openSync(join(REPORT_DIR, 'frontend.log'), 'a')
    const err = openSync(join(REPORT_DIR, 'frontend.err.log'), 'a')
    const proc = spawn('D:/Software/nodejs/node.exe', ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5173'], {
      cwd: join(ROOT, 'frontend'),
      stdio: ['ignore', out, err],
      windowsHide: true
    })
    started.push({ proc, out, err, name: 'frontend' })
    await waitForHttp(APP_URL, 45000)
    pass('鍓嶇鏈嶅姟宸茬敱鑴氭湰鍚姩')
  }
}

async function getPreferredProvider() {
  const providers = await request('GET', '/providers')
  const preferred = providers.find(item => item.name === '鑱旈€氫簯-DeepSeek-V4-Flash')
    || providers.find(item => /DeepSeek-V4-Flash/i.test(item.model || ''))
    || providers[0]
  if (!preferred) throw new Error('娌℃湁鍙敤 Provider')
  report.provider = {
    name: preferred.name,
    model: preferred.model,
    baseURL: preferred.baseURL,
    apiKey: maskKey(preferred.apiKey),
    maxContextTokens: preferred.maxContextTokens,
    maxOutputTokens: preferred.maxOutputTokens
  }
  pass('妯″瀷閰嶇疆宸茶鍙?, `${preferred.name} / ${preferred.model} / ${maskKey(preferred.apiKey)}`)
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

  const attempts = options.attempts ?? 3
  let lastError = null
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
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
        const error = new Error(`LLM ${res.status}: ${text.slice(0, 500)}`)
        error.retryable = res.status === 429 || res.status >= 500
        throw error
      }
      const data = JSON.parse(text)
      return data?.choices?.[0]?.message?.content || ''
    } catch (error) {
      lastError = error
      const retryable = Boolean(error.retryable)
        || error.name === 'TimeoutError'
        || error.name === 'AbortError'
        || error.message.includes('fetch failed')
      if (!retryable || attempt >= attempts) throw error
      report.notes.push(`LLM 璇锋眰澶辫触锛岀 ${attempt}/${attempts} 娆″悗閲嶈瘯锛?{trimText(error.message, 160)}`)
      await sleep(1000 * attempt)
    }
  }
  throw lastError || new Error('LLM request failed')
}

async function chatJson(provider, messages, options = {}, repairHint = '璇锋妸涓婁竴娆″唴瀹规暣鐞嗘垚鍚堟硶 JSON銆?) {
  const first = await chat(provider, messages, { ...options, json: true })
  try {
    return { payload: parseJsonPayload(first), raw: first, repaired: false }
  } catch (firstError) {
    const repair = await chat(provider, [
      { role: 'system', content: '浣犳槸 JSON 淇鍣ㄣ€傚彧鑳借緭鍑哄悎娉?JSON锛屼笉瑕佽В閲婏紝涓嶈 Markdown銆? },
      { role: 'user', content: `${repairHint}\n\n鍘熷鍐呭锛歕n${first.slice(0, 12000)}` }
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
    .replace(/[鈥溾€漖/g, '"')
    .replace(/[鈥樷€橾/g, "'")
    .replace(/,\s*([}\]])/g, '$1')
    .trim()
}

function collectBalanced(text, openChar, closeChar) {
  const source = String(text || '').slice(0, MAX_JSON_SCAN_CHARS)
  const out = []
  const startedAt = Date.now()
  let cursor = 0
  while (cursor < source.length && out.length < MAX_JSON_CANDIDATES) {
    if (Date.now() - startedAt > 1500) break
    const start = source.indexOf(openChar, cursor)
    if (start === -1) break
    let depth = 0
    let inString = false
    let escaped = false
    let balanced = false
    for (let i = start; i < source.length; i += 1) {
      const ch = source[i]
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
          out.push(source.slice(start, i + 1))
          cursor = i + 1
          balanced = true
          break
        }
      }
    }
    if (!balanced) cursor = start + 1
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
  throw new Error(`娌℃湁瑙ｆ瀽鍒?JSON锛?{text.slice(0, 260)}`)
}

function normalizeSeed(raw) {
  return {
    title: String(raw.title || raw.name || '鏈懡鍚嶆祴璇曠瀛?).trim(),
    genre: String(raw.genre || raw.category || '鐜勫够鎮枒').trim(),
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
    writingProfile: raw.writingProfile || raw.writing_profile || {},
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

function normalizeApiList(value) {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.items)) return value.items
  if (Array.isArray(value?.data)) return value.data
  return []
}

function serializeBrief(value, max = 900) {
  if (!value) return ''
  if (typeof value === 'string') return trimText(value, max)
  try {
    return trimText(JSON.stringify(value, null, 2), max)
  } catch {
    return trimText(String(value), max)
  }
}

function formatQaContextForPrompt(context, max = 3200) {
  if (!context) return ''
  if (typeof context === 'string') return trimText(context, max)

  const sections = [
    ['chapterGoal', context.chapterGoal],
    ['creativeBoundary', context.creativeBoundary],
    ['volumeStage', context.volumeStage],
    ['stateLedger', context.stateLedger],
    ['settingLibrary', context.settingLibrary],
    ['recentSettingChanges', context.recentSettingChanges],
    ['threadFacts', context.threadFacts],
    ['recentFacts', context.recentFacts],
    ['softCorrectionAims', context.softCorrectionAims],
    ['previousChapterEnding', context.previousChapterEnding],
    ['recentChapterEndings', context.recentChapterEndings],
    ['nearOutline', context.nearOutline],
    ['wordTarget', context.wordTarget],
    ['seed', context.seed]
  ]
    .map(([label, value]) => {
      const brief = serializeBrief(value, label === 'settingLibrary' ? 1200 : 700)
      return brief ? `## ${label}\n${brief}` : ''
    })
    .filter(Boolean)

  return trimText(sections.join('\n\n'), max)
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
    softMax: Math.round(target * 1.3),
    hardMin: Math.round(target * 0.8),
    hardMax: Math.round(target * 1.4)
  }
}

function upsertCount(list, chapterNum, patch) {
  const existing = list.find(item => Number(item.chapterNum) === Number(chapterNum))
  if (existing) Object.assign(existing, patch)
  else list.push({ chapterNum, ...patch })
}

function assessChapterWordCount(project, chapterNum, count, stage = '姝ｆ枃') {
  const range = expectedChapterWordRange(project)
  const detail = `${count} 瀛楋紱鐩爣 ${range.target}锛屽缓璁?${range.softMin}-${range.softMax}锛岀‖鑼冨洿 ${range.hardMin}-${range.hardMax}`
  if (isChapterWordCountTooFarForQaStop(project, count)) {
    fail(`绗?${chapterNum} 绔?{stage}瀛楁暟瓒婄晫`, detail)
    return false
  }
  if (!isChapterWordCountInHardRange(project, count)) {
    report.notes.push(`绗?${chapterNum} 绔?{stage}瀛楁暟杩涘叆璐ㄩ噺淇濈暀瀹瑰繊鍖猴細${detail}`)
    pass(`绗?${chapterNum} 绔?{stage}瀛楁暟杩涘叆璐ㄩ噺淇濈暀瀹瑰繊鍖篳, detail)
    return true
  }
  if (count < range.softMin || count > range.softMax) {
    report.notes.push(`绗?${chapterNum} 绔?{stage}瀛楁暟鐣ュ亸绂诲缓璁寖鍥达細${detail}`)
  }
  pass(`绗?${chapterNum} 绔?{stage}瀛楁暟鍦ㄥ彲鎺ュ彈鑼冨洿`, detail)
  return true
}

function isChapterWordCountInHardRange(project, count) {
  const range = expectedChapterWordRange(project)
  return count >= range.hardMin && count <= range.hardMax
}

function isChapterWordCountTooFarForQaStop(project, count) {
  const range = expectedChapterWordRange(project)
  const qaStopMin = Math.round(range.target * 0.65)
  const qaStopMax = Math.round(range.target * 1.4)
  return count < qaStopMin || count > qaStopMax
}

function isChapterWordCountWithinQualityGrace(project, count) {
  const range = expectedChapterWordRange(project)
  return Number(count) >= range.hardMin && !isChapterWordCountTooFarForQaStop(project, count)
}

function chooseBestChapterCandidate(project, candidates = []) {
  const range = expectedChapterWordRange(project)
  const valid = candidates
    .filter(candidate => candidate && candidate.content && Number(candidate.count) > 0)
    .map(candidate => ({
      ...candidate,
      count: Number(candidate.count),
      distance: Math.abs(Number(candidate.count) - range.target)
    }))

  const bestByDistance = list => list
    .slice()
    .sort((left, right) => left.distance - right.distance || left.count - right.count)[0] || null

  const inHardRange = valid.filter(candidate => isChapterWordCountInHardRange(project, candidate.count))
  if (inHardRange.length) return { ...bestByDistance(inHardRange), selectionReason: 'hard_range' }

  const qualityGrace = valid.filter(candidate => isChapterWordCountWithinQualityGrace(project, candidate.count))
  if (qualityGrace.length) return { ...bestByDistance(qualityGrace), selectionReason: 'quality_grace' }

  return null
}

function buildChapterWordGateError(project, chapterNum, count, stage = 'chapter') {
  const range = expectedChapterWordRange(project)
  const direction = count < range.hardMin ? 'too_short' : 'too_long'
  const error = new Error(
    `WORD_COUNT_GATE: chapter ${chapterNum} ${stage} is ${direction}; ` +
      `${count} chars, hard range ${range.hardMin}-${range.hardMax}. ` +
      'Candidate was saved, but QA stopped before audit/finalize.'
  )
  error.code = 'WORD_COUNT_GATE'
  error.chapterNum = chapterNum
  error.count = count
  error.range = range
  return error
}

function enforceWordCountGate(project, chapterNum, count, stage = 'chapter') {
  const ok = assessChapterWordCount(project, chapterNum, count, stage)
  if (ok) return true
  if (IGNORE_WORD_COUNT_GATE) {
    report.notes.push(`IGNORED_WORD_COUNT_GATE: chapter ${chapterNum} ${stage} count ${count} outside hard range.`)
    return false
  }
  throw buildChapterWordGateError(project, chapterNum, count, stage)
}

function findFinalizedWordOutliers(project, finalizedChapters = []) {
  return finalizedChapters
    .filter(item => isChapterWordCountTooFarForQaStop(project, item?.wordCount))
    .map(item => ({ chapterNum: item.chapterNum, count: item.wordCount }))
}

function assertNoFinalizedWordOutliers(project, finalizedChapters = [], scope = 'existing_finalized') {
  const outliers = findFinalizedWordOutliers(project, finalizedChapters)
  if (!outliers.length) return
  const range = expectedChapterWordRange(project)
  fail(
    '缁啓鍓嶅彂鐜板凡瀹氱绔犺妭瀛楁暟纭€ц秺鐣?,
    `range=${range.hardMin}-${range.hardMax}, outliers=${JSON.stringify(outliers)}`
  )
  const error = new Error(
    `WORD_COUNT_GATE: ${scope} contains finalized word outliers; ` +
      `range ${range.hardMin}-${range.hardMax}; outliers=${JSON.stringify(outliers)}`
  )
  error.code = 'WORD_COUNT_GATE'
  error.outliers = outliers
  error.range = range
  throw error
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
      `绗?${chapterNum} 绔犲绋夸慨璁㈠瓧鏁版紓绉昏繃澶,
      `鍘?${originalCount} 瀛楋紝淇 ${revisedCount} 瀛楋紝姣斾緥 ${ratio.toFixed(2)}锛涘凡鍥為€€鍒颁慨璁㈠墠姝ｆ枃`
    )
    return { ok: false, originalCount, revisedCount, reason: tooMuchDrift ? 'drift' : 'word_range' }
  }
  return { ok: true, originalCount, revisedCount, reason: 'accepted' }
}

function recordFinalChapterWordCount(chapterNum, count) {
  if (!Array.isArray(report.generated.finalChapterWordCounts)) {
    report.generated.finalChapterWordCounts = []
  }
  upsertCount(report.generated.finalChapterWordCounts, chapterNum, { count })
}

function chapterTitle(chapterNum, name = '') {
  return name ? `绗?${chapterNum} 绔?路 ${name}` : `绗?${chapterNum} 绔燻
}

async function createProject(provider) {
  const stamp = new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14)
  const project = await request('POST', '/projects', {
    title: `${QA_PROJECT_PREFIX}_${stamp}`,
    genre: '鐜勫够鎮枒 / 浜烘€ч€夋嫨',
    description: '鑷姩鍖栫湡瀹炴祦绋嬫祴璇曢」鐩細鎸?200 涓囧瓧銆?00 绔犺妯¤鍒掞紝鐪熷疄璋冪敤缃戠粶鎶撳彇鍜屽ぇ妯″瀷鐢熸垚鍓嶅嚑绔犲唴瀹广€?,
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
  pass('宸叉柊寤?200 涓囧瓧瑙勬ā椤圭洰', `${project.title} / 400 绔燻)
  return project
}

async function runMarketAndSeed(project, provider) {
  log('寮€濮嬮€夐闆疯揪锛氱綉缁滄姄鍙栫儹闂ㄩ鏉?)
  let scrapeResult = null
  try {
    scrapeResult = await request('POST', '/market/scrape', {
      projectId: project.id,
      keywords: '鐜勫够 鎮枒 浜烘€?鐑棬灏忚'
    })
  } catch (error) {
    report.notes.push(`缃戠粶鎶撳彇澶辫触锛?{error.message}`)
    fail('缃戠粶鎶撳彇鐑棬灏忚', error.message)
  }
  const marketItems = await request('GET', `/market/items?projectId=${project.id}`)
  report.generated.marketItems = marketItems.length
  assertCheck(marketItems.length > 0, '閫夐闆疯揪鏈夌儹鐐规暟鎹?, `items=${marketItems.length}${scrapeResult?.fallback ? ' / fallback' : ''}`)

  log('寮€濮?AI 鏂瑰悜寤鸿')
  const marketBrief = marketItems.slice(0, 12).map((item, index) =>
    `${index + 1}. ${item.title}锝?{item.platform || ''}锝?{item.category || ''}锝?{item.intro || ''}`
  ).join('\n')
  const directionResult = await chatJson(provider, [
    { role: 'system', content: '浣犳槸缃戞枃閫夐绛栧垝缂栬緫銆傚繀椤昏緭鍑哄悎娉?JSON锛屼笉瑕?Markdown銆? },
    { role: 'user', content: `鍩轰簬杩欎簺鐑偣鏁版嵁锛岀粰鍑?4 涓€傚悎闀跨瘒鍘熷垱灏忚鐨勬柟鍚戙€傝緭鍑?{"directions":[{"title":"","genre":"","readerExpectation":"","whyNow":"","seedAngle":"","risks":"","discussionPrompt":""}]}銆俓n\n鐑偣鏁版嵁锛歕n${marketBrief}` }
  ], { maxTokens: 3500, temperature: 0.6 }, '淇涓?{"directions":[...]} 鏍煎紡銆?)
  const directionsPayload = directionResult.payload
  const directions = Array.isArray(directionsPayload.directions) ? directionsPayload.directions : []
  report.generated.directions = directions.length
  await request('POST', '/market/directions', {
    projectId: project.id,
    keywords: '鐜勫够 鎮枒 浜烘€?鐑棬灏忚',
    directions,
    sourceItems: marketItems.slice(0, 20)
  })
  assertCheck(directions.length >= 2, 'AI 鏂瑰悜寤鸿鍙В鏋?, `directions=${directions.length}`)

  const userQuestion = `鎴戞兂閫変竴涓€傚悎 200 涓囧瓧闀跨瘒銆侀噸鐐瑰啓浜烘€ч€夋嫨鍜屼唬浠风殑棰樻潗锛岃鍩轰簬鏂瑰悜寤鸿鐢熸垚涓€涓畬鏁村垱浣滅瀛愶紝骞朵繚鐣欑粨灞€閿氱偣銆俙
  await request('POST', '/market/chat', { projectId: project.id, role: 'user', content: userQuestion, metadata: {} })
  log('寮€濮?AI 閫夐椤鹃棶鐢熸垚绉嶅瓙')
  const seedResult = await chatJson(provider, [
    { role: 'system', content: '浣犳槸璧勬繁缃戞枃閫夐椤鹃棶銆傚彧杈撳嚭鍚堟硶 JSON銆傚彧鐢熸垚 1 涓瀛愶紝姣忎釜瀛楁涓嶈秴杩?120 涓腑鏂囧瓧绗︼紝閬垮厤 JSON 杩囬暱琚埅鏂€? },
    { role: 'user', content: `${userQuestion}\n\n鏂瑰悜寤鸿锛歕n${JSON.stringify(directions, null, 2)}\n\n蹇呴』杈撳嚭 {"seeds":[{"title":"","genre":"","logline":"","protagonist":"","desire":"","coreConflict":"","worldPressure":"","openingHook":"","emotionalPromise":"","differentiation":"","styleTarget":"","riskNotes":"","endingAnchor":""}]}銆傚彧杈撳嚭 JSON銆俙 }
  ], { maxTokens: 6000, retryMaxTokens: 7000, repairMaxTokens: 6000, temperature: 0.65 }, '淇涓?{"seeds":[{...}]} 鏍煎紡锛涘彧淇濈暀 1 涓畬鏁寸瀛愩€?)
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
  assertCheck(seeds.length >= 1, 'AI 閫夐椤鹃棶鐢熸垚鍙繚瀛樼瀛?, `seeds=${seeds.length}`)

  const seed = await request('POST', `/projects/${project.id}/seeds`, seeds[0])
  const selectedSeed = await request('PUT', `/projects/${project.id}/seeds/${seed.id}`, { status: 'selected' })
  pass('绉嶅瓙宸蹭繚瀛樺苟璁句负褰撳墠绉嶅瓙', selectedSeed.title)

  return { marketItems, directions, seed: selectedSeed }
}

async function runBibleAndSettings(project, provider, seed) {
  log('寮€濮嬩粠绉嶅瓙鐢熸垚鍒涗綔鍦ｇ粡')
  const bibleText = await chat(provider, [
    { role: 'system', content: '浣犳槸闀跨瘒灏忚鎬荤紪銆傚繀椤昏緭鍑哄悎娉?JSON锛屼笉瑕?Markdown銆傚垱浣滃湥缁忔槸鍚庣画澶х翰銆佽瀹氬拰姝ｆ枃蹇呴』閬靛畧鐨勮摑鍥俱€? },
    { role: 'user', content: `鏍规嵁绉嶅瓙鐢熸垚鍒涗綔鍦ｇ粡銆傝緭鍑?{"premise":"","targetReader":"","styleBible":[],"themeBible":[],"worldRules":[],"forbiddenDirections":[]}銆俓n瑕佹眰锛氫繚鐣欐兂璞″姏锛屼絾鎶婄‖瑙勫垯鍐欐竻妤氾紱鏄庣‘閬垮厤 AI 鑵旓紝灏戠敤鈥滀笉鏄疿锛屾槸Y鈥濆彞寮忥紱闀挎湡鐩爣鏄?200 涓囧瓧銆俓n\n绉嶅瓙锛歕n${JSON.stringify(seed, null, 2)}` }
  ], { json: true, maxTokens: 4096, temperature: 0.55 })
  const bible = normalizeBible(parseJsonPayload(bibleText))
  bible.writingProfile = {
    primaryStandard: QA_PRIMARY_STANDARD,
    secondaryFlavor: QA_SECONDARY_FLAVOR,
    customStyleNotes: QA_STYLE_NOTES
  }
  bible.styleBible = [
    bible.styleBible,
    `鍐欎綔绛栫暐鏍囧噯锛氫富鍐欎綔鏍囧噯=${QA_PRIMARY_STANDARD}锛涜緟鍔╅鍛?${QA_SECONDARY_FLAVOR}锛?{QA_STYLE_NOTES}`
  ].filter(Boolean).join('\n')
  await request('PUT', `/projects/${project.id}/bible`, bible)
  assertCheck(Boolean(bible.premise && bible.styleBible && bible.worldRules), '鍒涗綔鍦ｇ粡宸茬敓鎴愬苟淇濆瓨', bible.premise.slice(0, 60))

  log('寮€濮嬩粠鍦ｇ粡鎻愬彇璁惧畾鍊欓€?)
  const settingsText = await chat(provider, [
    { role: 'system', content: '浣犳槸闀跨瘒灏忚璁惧畾搴撴暣鐞嗗憳銆傚彧杈撳嚭鍚堟硶 JSON銆備笉瑕侀噸澶嶅悓鍚嶅悓绫诲瀷瀹炰綋锛涘叧绯诲彉鍖栫敤鐙珛浜嬩欢琛ㄨ揪銆? },
    { role: 'user', content: `浠庡垱浣滅瀛愬拰鍦ｇ粡涓彁鍙?8-12 涓垵濮嬭瀹氬€欓€夛紝杈撳嚭 {"settings":[{"entityType":"character|faction|location|power_system|technique|item","entityName":"","changeType":"new_entity|update|relation_change","fieldPath":"summary","newValue":"","evidence":"","confidence":0.9}]}銆俓n\n绉嶅瓙锛?{JSON.stringify(seed)}\n\n鍦ｇ粡锛?{JSON.stringify(bible)}` }
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
      evidence: `鍒涗綔鍦ｇ粡鍒濆鍖栵細${item.evidence || bible.premise}`,
      confidence: Number(item.confidence || 0.9),
      status: 'pending_review'
    })
    createdEvents.push(saved)
  }
  report.generated.settingEvents = createdEvents.length
  assertCheck(createdEvents.length >= 4, '鍦ｇ粡鎻愬彇鍒拌瀹氬€欓€?, `events=${createdEvents.length}`)

  for (const event of createdEvents) {
    await request('POST', `/projects/${project.id}/settings/change-events/${event.id}/accept`)
    report.generated.acceptedSettings += 1
  }
  pass('鍒濆璁惧畾鍊欓€夊凡鍏ㄩ儴纭鍏ュ簱', `accepted=${report.generated.acceptedSettings}`)

  const entities = await request('GET', `/projects/${project.id}/settings/entities`)
  assertCheck(entities.length >= 4, '璁惧畾搴撳疄浣撳凡鐢熸垚', `entities=${entities.length}`)
  return { bible, entities }
}

async function createVolumesAndChapters(project) {
  log('寮€濮嬪垱寤?200 涓囧瓧鍒嗗嵎涓庣珷鑺傞鏋?)
  const volumes = []
  for (let i = 1; i <= 8; i += 1) {
    const start = (i - 1) * 50 + 1
    const volume = await request('POST', `/projects/${project.id}/volumes`, {
      volumeNum: i,
      title: `绗?${i} 鍗穈,
      startChapter: start,
      endChapter: start + 49,
      targetWords: 250000,
      coreGoal: `绗?${i} 鍗锋帹鍔ㄤ富瑙掑鎰挎湜浠ｄ环鐨勭悊瑙ｅ崌绾,
      mainConflict: '涓汉鎰挎湜銆佸鏃忕湡鐩镐笌閫愭効瑙勫垯涔嬮棿鐨勫啿绐?,
      keyCharacters: [],
      summary: '鑷姩鍖栨祴璇曞垱寤虹殑闀跨瘒鍒嗗嵎瑙勫垝銆?,
      status: 'planned'
    })
    volumes.push(volume)
  }

  let chaptersCreated = 0
  for (let i = 1; i <= 400; i += 1) {
    await request('POST', `/projects/${project.id}/chapters`, {
      chapterNum: i,
      title: `绗?${i} 绔燻
    })
    chaptersCreated += 1
  }
  report.generated.chaptersCreated = chaptersCreated
  assertCheck(volumes.length === 8 && chaptersCreated === 400, '200 涓囧瓧绔犺妭楠ㄦ灦宸插垱寤?, `volumes=${volumes.length}, chapters=${chaptersCreated}`)

  const chapter4 = (await request('GET', `/projects/${project.id}/chapters`)).find(item => Number(item.chapterNum) === 4)
  await request('DELETE', `/projects/${project.id}/chapters/${chapter4.id}`)
  await request('POST', `/projects/${project.id}/chapters`, { chapterNum: 4, title: '绗?4 绔? })
  pass('绌虹珷鑺傚垹闄ゅ悗鍙噸鏂板垱寤?, '绗?4 绔?)

  return { volumes }
}

async function saveBeatPlan(project, chapterNum, content) {
  await request('PUT', `/projects/${project.id}/chapter-beat-plan/${chapterNum}`, { content })
}

async function compactBeatPlanIfNeeded(provider, chapterNum, text, context) {
  text = String(text || '').trim()
  if (text.length <= 1300) return text

  log(`绗?${chapterNum} 绔犲皬绾茶繃闀匡紝寮€濮嬪帇缂ー)
  let best = text
  const contextBrief = formatQaContextForPrompt(context, 2400)
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const compacted = await chat(provider, [
      { role: 'system', content: '浣犳槸闀跨瘒灏忚鍒嗙珷灏忕翰缂栬緫銆傚彧璐熻矗鍘嬬缉灏忕翰锛屼笉鍐欐鏂囷紝涓嶈В閲娿€? },
      {
        role: 'user',
        content: [
          `璇锋妸绗?${chapterNum} 绔犲皬绾插帇缂╀负 700-1100 瀛楋紝缁濅笉鑳借秴杩?1300 瀛椼€俙,
          '鑺傛媿鎺у埗鍦?4-6 鏉★紝淇濈暀鏈珷鏍稿績鐩殑銆佷汉鐗╁姩鏈恒€佸叧閿€夋嫨銆佷唬浠枫€佺粨灏鹃挬瀛愩€佽繛缁€ц嚜妫€鍜屽啓浣滅害鏉熴€?,
          '蹇呴』淇濈暀鏃堕棿绾胯繛缁€с€佺姸鎬佸欢缁€侀亾鍏锋潵婧愩€佷汉鐗╅摵鍨拰浼忕瑪閾哄灚鐨勫叧閿彁閱掞紝浣嗙敤鐭彞鍚堝苟琛ㄨ揪銆?,
          '涓嶈鏂板鍓ф儏锛屼笉瑕佹敼鍙樺洜鏋滈『搴忥紝涓嶈鎶婁袱绔犲閲忓杩涗竴绔犮€?,
          attempt > 1 ? `涓婁竴娆″帇缂╀粛杩囬暱锛?{best.length} 瀛楃锛夛紝璇风户缁帇缂┿€俙 : '',
          `涓婁笅鏂囷細\n${contextBrief}`,
          `鍘熷皬绾诧細\n${best}`
        ].filter(Boolean).join('\n\n')
      }
    ], { maxTokens: 1400, temperature: 0.3, timeoutMs: 240000 })
    const cleaned = compacted.trim()
    if (cleaned.length >= 600 && cleaned.length < best.length) best = cleaned
    if (best.length <= 1300) {
      pass(`绗?${chapterNum} 绔犲皬绾插凡鑷姩鍘嬬缉`, `${text.length} -> ${best.length} chars`)
      return best
    }
  }

  report.notes.push(`绗?${chapterNum} 绔犲皬绾插帇缂╁悗浠嶅亸闀匡細${text.length} -> ${best.length}`)
  assertCheck(best.length <= 1300, `绗?${chapterNum} 绔犲皬绾插帇缂╁埌寤鸿涓婇檺鍐卄, `${text.length} -> ${best.length} chars`)
  return best.length < text.length ? best : text
}

async function generateBeatPlan(project, provider, chapterNum, context) {
  log(`寮€濮嬬敓鎴愮 ${chapterNum} 绔犲皬绾瞏)
  const rawText = await chat(provider, [
    { role: 'system', content: buildChapterBeatSystemPrompt() },
    { role: 'user', content: buildChapterBeatPrompt({ ...context, chapterNum }) }
  ], { maxTokens: 1800, temperature: 0.5 })
  const text = cleanChapterBeatPlanText(await compactBeatPlanIfNeeded(provider, chapterNum, rawText, context))
  await saveBeatPlan(project, chapterNum, text)
  assertCheck(text.length > 200, `绗?${chapterNum} 绔犲皬绾插凡鐢熸垚`, `${text.length} chars`)
  return text
}

async function generateChapterContent(project, provider, chapterNum, context, beatPlan) {
  log(`寮€濮嬬敓鎴愮 ${chapterNum} 绔犳鏂嘸)
  const promptContext = { ...context, chapterNum, beatPlan }
  const content = await chat(provider, [
    { role: 'system', content: buildChapterSystemPrompt() },
    { role: 'user', content: buildChapterPrompt(promptContext) }
  ], { maxTokens: 8192, temperature: 0.72, timeoutMs: 360000 })
  const cleaned = cleanGeneratedChapterText(content)
  const count = wordCount(cleaned)
  report.generated.chapterWordCounts.push({ chapterNum, count, stage: 'first_draft' })
  assertCheck(count >= 3000, `绗?${chapterNum} 绔犳鏂囧凡鐢熸垚`, `${count} 瀛梎)
  return cleaned
}

function cleanQaGeneratedText(text) {
  const isOpeningMetaLine = (line) => {
    const trimmed = line.trim()
    if (!trimmed) return true
    const withoutMarkdown = trimmed.replace(/^#{1,6}\s*/, '').trim()
    if (/^(浠ヤ笅鏄瘄涓嬮潰鏄瘄姝ｆ枃濡備笅|鍊欓€夌|绔犺妭姝ｆ枃)[锛?]/.test(withoutMarkdown)) return true
    if (/^(?:姝ｆ枃|绔犺妭姝ｆ枃|鍊欓€夋鏂?\s*[锛?]\s*$/.test(withoutMarkdown)) return true
    return /^绗琝s*[\d涓€浜屼笁鍥涗簲鍏竷鍏節鍗佺櫨鍗冧竾闆躲€囦袱]+\s*绔??:\s*[锛?銆?\-鈥斅穄\s*.*|\s+\S{1,16})?$/.test(withoutMarkdown)
  }

  const lines = String(text || '')
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .split(/\r?\n/)

  let hasProseStarted = false
  return lines
    .filter(line => {
      const trimmed = line.trim()
      if (!hasProseStarted && isOpeningMetaLine(line)) return false
      if (trimmed) hasProseStarted = true
      return true
    })
    .join('\n')
    .replace(/\n{4,}/g, '\n\n\n')
    .trim()
}

async function repairProseRhythmForQa(project, provider, chapterNum, context, beatPlan, content) {
  const original = String(content || '').trim()
  const analysis = analyzeProseRhythm(original)
  if (!shouldRepairProseRhythm(analysis)) return original
  const contextBrief = formatQaContextForPrompt(context, 2600)

  log(`绗?${chapterNum} 绔犺Е鍙戝彞寮忚妭濂忎慨璁細${analysis.reasons.join('锛?)}`)
  const repaired = cleanQaGeneratedText(await chat(provider, [
    {
      role: 'system',
      content: [
        '浣犳槸闀跨瘒灏忚姝ｆ枃鑺傚淇缂栬緫銆傚彧淇鏂囩涓繃瀵嗙殑鐭彞鐙珛娈佃惤銆佹満姊板寲 AI 鑵斿彞寮忓拰纰庣墖鍖栧垎闀滄劅銆?,
        '涓嶈鏂板鍓ф儏銆佷汉鐗┿€佽瀹氭垨缁撹锛涗繚鐣欎簨浠堕『搴忋€佷汉鐗╅€夋嫨銆佸鐧藉惈涔夈€佺粨灏鹃挬瀛愬拰宸茬‘璁よ瀹氥€?,
        '甯歌鍙欎簨娈佃惤鑷劧鍚堝苟涓?2-5 鍙ワ紱鐭彞鍙兘淇濈暀鍦ㄥ眬閮ㄧ垎鐐广€佹亹鎯с€佹柇瑁傘€佸弽杞垨鍋滈】銆?,
        '杈撳嚭瀹屾暣姝ｆ枃锛屼笉瑕佹爣棰橈紝涓嶈瑙ｉ噴锛屼笉瑕?JSON銆?
      ].join('\n')
    },
    {
      role: 'user',
      content: [
        `璇蜂慨璁㈢ ${chapterNum} 绔犵殑鍙ュ紡鑺傚銆俙,
        `鑺傚鎶ュ憡锛歕n${formatProseRhythmAnalysis(analysis)}`,
        '鐩爣锛氬噺灏戣繛缁煭鍙ョ嫭绔嬫钀斤紝鍘绘帀鏈烘鈥滀笉鏄疿锛屾槸Y鈥濇ā鏉匡紝淇濇寔鍓ф儏浜嬪疄鍜屽瓧鏁颁綋閲忓熀鏈笉鍙樸€?,
        `涓婁笅鏂囷細\n${contextBrief}`,
        `灏忕翰锛歕n${trimText(beatPlan, 1600)}`,
        `姝ｆ枃锛歕n${original}`
      ].join('\n\n')
    }
  ], { maxTokens: 5200, temperature: 0.28, timeoutMs: 300000 }))

  const repairedAnalysis = analyzeProseRhythm(repaired)
  const drift = countCjkChars(repaired) / Math.max(countCjkChars(original), 1)
  const improved =
    repaired &&
    repaired !== original &&
    drift >= 0.78 &&
    drift <= 1.22 &&
    (
      repairedAnalysis.shortParagraphRate < analysis.shortParagraphRate ||
      repairedAnalysis.maxShortStreak < analysis.maxShortStreak ||
      repairedAnalysis.aiContrastCount < analysis.aiContrastCount ||
      repairedAnalysis.maxSameLeadingSubjectCount < analysis.maxSameLeadingSubjectCount
    )

  if (!improved) {
    report.notes.push(`绗?${chapterNum} 绔犲彞寮忚妭濂忎慨璁㈡湭閲囩敤锛歞rift=${drift.toFixed(2)}锛沚efore=${analysis.shortParagraphRate.toFixed(2)}/${analysis.maxShortStreak}/lead${analysis.maxSameLeadingSubjectCount || 0}锛沘fter=${repairedAnalysis.shortParagraphRate.toFixed(2)}/${repairedAnalysis.maxShortStreak}/lead${repairedAnalysis.maxSameLeadingSubjectCount || 0}`)
    return original
  }

  pass(`绗?${chapterNum} 绔犺妭濂忎慨璁㈠凡閲囩敤`, `鐭彞鐜?${analysis.shortParagraphRate.toFixed(2)} -> ${repairedAnalysis.shortParagraphRate.toFixed(2)}锛岃繛缁?${analysis.maxShortStreak} -> ${repairedAnalysis.maxShortStreak}锛屾棣栭噸澶?${analysis.maxSameLeadingSubjectCount || 0} -> ${repairedAnalysis.maxSameLeadingSubjectCount || 0}`)
  return repaired
}

async function expandShortChapterContent(project, provider, chapterNum, context, beatPlan, shortContent) {
  const range = expectedChapterWordRange(project)
  const currentCount = wordCount(shortContent)
  const contextBrief = formatQaContextForPrompt(context, 3200)
  log(`绗?${chapterNum} 绔犲垵绋垮亸鐭紝寮€濮嬭ˉ瓒抽噸璇曪細${currentCount} 瀛梎)
  const expanded = await chat(provider, [
    {
      role: 'system',
      content: [
        '浣犳槸闀跨瘒缃戞枃琛ョ缂栬緫銆備换鍔℃槸淇濈暀鍘熸枃涓讳綋锛屽彧琛ヨ冻缂哄け鐨勫満鏅€佽鍔ㄣ€佸姩鏈恒€佽繃娓″拰鎰熷畼缁嗚妭銆?,
        '涓嶈鎺ㄧ炕鍘熷墽鎯咃紝涓嶈鍙﹁捣鐐夌伓锛屼笉瑕佹€荤粨寮忔墿鍐欙紱琛ヨ冻鍚庤緭鍑哄畬鏁存鏂囥€?,
        '濡傛灉褰撳墠绋夸粛鏄庢樉鍋忕煭锛岃嚦灏戞柊澧炰竴鍒颁袱涓畬鏁村満鏅垨瀹屾暣琛屽姩娈碉紝涓嶈鍙ˉ鍑犲彞璇存槑銆?,
        '鐩爣瀛楁暟 5000 瀛楋紝寤鸿 4500-6500 瀛楋紱蹇呴』鑷冲皯杈惧埌纭笅闄愶紝浣嗕笉鑳戒负浜嗗噾瀛楅噸澶嶈В閲婃垨鐏屾按銆?,
        '濡傛灉灏忕翰鍐呭涓嶈冻锛屼紭鍏堝睍寮€浜虹墿閫夋嫨銆侀樆鍔涖€佷唬浠枫€佸満鏅帹杩涘拰绔犳湯閽╁瓙銆?
      ].join('\n')
    },
    {
      role: 'user',
      content: [
        `绗?${chapterNum} 绔犲垵绋垮彧鏈?${currentCount} 瀛楋紝浣庝簬纭笅闄?${range.hardMin} 瀛椼€俙,
        `璇峰湪涓嶆敼鍙樻牳蹇冩儏鑺傜殑鍓嶆彁涓嬭ˉ瓒充负瀹屾暣绔犺妭锛屽敖閲忛潬杩?${range.target} 瀛楋紝鍏佽 ${range.hardMin}-${range.hardMax} 瀛椼€俙,
        `杩欐杈撳嚭蹇呴』鏄庢樉闀夸簬褰撳墠绋匡紝鑷冲皯琛ヨ冻鍒?${range.hardMin + 200} 瀛椾互涓娿€俙,
        '鍙緭鍑鸿ˉ瓒冲悗鐨勫畬鏁存鏂囷紝涓嶈鏍囬锛屼笉瑕佽В閲娿€?,
        '',
        `涓婁笅鏂囷細\n${contextBrief}`,
        '',
        `鏈珷灏忕翰锛歕n${beatPlan}`,
        '',
        `褰撳墠鍒濈锛歕n${shortContent}`
      ].join('\n')
    }
  ], { maxTokens: 6500, temperature: 0.66, timeoutMs: 360000 })
  return expanded.trim()
}

async function compressLongChapterContent(project, provider, chapterNum, context, beatPlan, longContent, compressAttempt = 1) {
  const range = expectedChapterWordRange(project)
  const currentCount = wordCount(longContent)
  const contextBrief = formatQaContextForPrompt(context, 3200)
  log(`绗?${chapterNum} 绔犵浠惰繃闀匡紝寮€濮嬪帇缂╅噸璇曪細${currentCount} 瀛梎)
  const strictHint = compressAttempt > 1
    ? `杩欐槸绗?${compressAttempt} 娆″帇缂╋紝涓婁竴鐗堜粛杩囬暱銆傝繖娆″繀椤诲帇鍒?${range.softMin}-${range.softMax} 瀛楋紝瀹佸彲鎶婁綑娉㈠拰瑙ｉ噴鐣欏埌涓嬩竴绔犮€俙
    : `璇峰帇缂╁埌 ${range.softMin}-${range.softMax} 瀛楅檮杩戯紝鏈€澶氫笉瑕佽秴杩?${range.hardMax} 瀛椼€俙
  const compressed = await chat(provider, [
    {
      role: 'system',
      content: [
        '浣犳槸闀跨瘒缃戞枃鍘嬬缉缂栬緫銆備换鍔℃槸鎶婅秴闀跨珷鑺傚帇鍥炵洰鏍囧尯闂达紝鍚屾椂淇濈暀鍏抽敭浜嬩欢銆佷汉鐗╅€夋嫨銆佷唬浠枫€佽浆鎶樺拰绔犳湯閽╁瓙銆?,
        '浼樺厛鍒犻櫎閲嶅瑙ｉ噴銆侀噸澶嶅績鐞嗐€佽繃闀胯瀹氳鏄庛€侀噸澶嶇幆澧冩弿鍐欙紱涓嶈鍒犳帀閫犳垚涓嬩竴绔犺鎺ユ墍闇€鐨勫洜鏋滀俊鎭€?,
        '濡傛灉淇℃伅閲忚繃澶э紝蹇呴』鐢ㄨ嚜鐒堕挬瀛愭妸閮ㄥ垎瑙ｉ噴銆佷綑娉㈡垨鏀嚎鎺ㄨ繜鍒颁笅涓€绔犮€?,
        '杈撳嚭蹇呴』鏄畬鏁存鏂囷紝涓嶈鏍囬锛屼笉瑕佽В閲婏紝涓嶈鍒楁彁绾层€?
      ].join('\n')
    },
    {
      role: 'user',
      content: [
        `绗?${chapterNum} 绔犲綋鍓?${currentCount} 瀛楋紝瓒呰繃纭笂闄?${range.hardMax} 瀛椼€俙,
        strictHint,
        '濡傛灉蹇呴』鍙栬垗锛屼繚鐣欏姩浣滃拰鍥犳灉锛屽垹鍑忚В閲婂拰閲嶅鍙ュ紡銆?,
        '',
        `涓婁笅鏂囷細\n${contextBrief}`,
        '',
        `鏈珷灏忕翰锛歕n${beatPlan}`,
        '',
        `褰撳墠瓒呴暱姝ｆ枃锛歕n${longContent}`
      ].join('\n')
    }
  ], { maxTokens: compressAttempt > 1 ? 4300 : 5000, temperature: compressAttempt > 1 ? 0.18 : 0.28, timeoutMs: 360000 })
  return compressed.trim()
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
  log(`寮€濮嬪绋跨 ${chapterNum} 绔燻)
  const contextBrief = formatQaContextForPrompt(context, 3600)
  let audit = { summary: '', issues: [] }
  try {
    const result = await chatJson(provider, [
      { role: 'system', content: '浣犳槸灏忚涓€鑷存€у绋夸汉銆傚彧杈撳嚭鍚堟硶 JSON銆傞棶棰樿鍏蜂綋锛宭ocation 灏介噺寮曠敤鍘熸枃涓湡瀹炲瓨鍦ㄧ殑鐭墖娈点€? },
      { role: 'user', content: `瀹℃煡绗?${chapterNum} 绔狅紝閲嶇偣鐪嬶細璁惧畾鐭涚浘銆佷汉鐗╁姩鏈恒€佷汉鎬т唬鍏ャ€佹暟鍊艰绠椼€佺珷鑺傝鎺ャ€丄I 鑵斿彞寮忋€傝緭鍑?{"summary":"","issues":[{"severity":"critical|major|minor|suggestion","type":"contradiction|logic|motivation|pacing|ai_tone|continuity","location":"","issue":"","suggestion":"","replacement":""}]}銆俓n\n涓婁笅鏂囷細${contextBrief}\n\n姝ｆ枃锛歕n${content}` }
    ], {
      maxTokens: 6000,
      repairMaxTokens: 6000,
      retryMaxTokens: 6000,
      temperature: 0.2,
      timeoutMs: 300000
    }, '璇蜂慨澶嶄负 {"summary":"","issues":[...]} 鏍煎紡锛涙渶澶氫繚鐣?6 涓渶閲嶈鐨勯棶棰橈紱鎵€鏈夊瓧娈靛繀椤诲畬鏁淬€?)
    audit = auditChapterPayload(result.payload)
  } catch (error) {
    report.notes.push(`绗?${chapterNum} 绔犲绋块娆″け璐ワ紝宸插惎鐢ㄥ绋跨揣鍑戦噸璇曪細${trimText(error.message, 180)}`)
    try {
      const compact = await chatJson(provider, [
        { role: 'system', content: '浣犳槸灏忚涓€鑷存€у绋夸汉銆傚彧杈撳嚭鍚堟硶 JSON锛屼笉瑕佽В閲娿€? },
        { role: 'user', content: `瀹＄绱у噾閲嶈瘯锛氬鏌ョ ${chapterNum} 绔狅紝鍙繚鐣?0-3 涓渶鍏抽敭闂銆傛瘡涓瓧娈靛繀椤荤煭锛宭ocation 蹇呴』鏄師鏂囦腑鐪熷疄瀛樺湪鐨勭煭鐗囨銆傝緭鍑?{"summary":"","issues":[{"severity":"critical|major|minor|suggestion","type":"contradiction|logic|motivation|pacing|ai_tone|continuity","location":"","issue":"","suggestion":"","replacement":""}]}銆俓n\n涓婁笅鏂囨憳瑕侊細${trimText(contextBrief, 2200)}\n\n姝ｆ枃鑺傞€夛細\n${content.slice(0, 7000)}` }
      ], {
        maxTokens: 2600,
        repairMaxTokens: 2600,
        retryMaxTokens: 3000,
        temperature: 0.15,
        timeoutMs: 240000
      }, '瀹＄绱у噾閲嶈瘯淇涓?{"summary":"","issues":[...]} 鏍煎紡锛涙渶澶氫繚鐣?3 涓煭闂銆?)
      audit = auditChapterPayload(compact.payload)
    } catch (retryError) {
      report.notes.push(`绗?${chapterNum} 绔犲绋跨揣鍑戦噸璇曞け璐ワ紝宸插惎鐢ㄦ渶缁堟瀬绠€閲嶈瘯锛?{trimText(retryError.message, 180)}`)
      try {
        const ultraCompact = await chatJson(provider, [
          { role: 'system', content: '浣犳槸灏忚涓€鑷存€у绋夸汉銆傚彧杈撳嚭鍚堟硶 JSON锛屼笉瑕佽В閲娿€傚瓧娈靛繀椤荤煭銆? },
          { role: 'user', content: `瀹＄鏈€缁堟瀬绠€閲嶈瘯锛氬鏌ョ ${chapterNum} 绔狅紝鍙繚鐣?0-1 涓渶闃诲鐨勯棶棰橈紱濡傛灉娌℃湁纭畾闂锛岃緭鍑虹┖鏁扮粍銆傛瘡涓瓧娈靛皯浜?50 瀛楋紝replacement 鍙负绌猴紝绂佹闀垮紩鐢ㄥ師鏂囥€傝緭鍑?{"summary":"","issues":[{"severity":"critical|major|minor|suggestion","type":"contradiction|logic|motivation|pacing|ai_tone|continuity","location":"","issue":"","suggestion":"","replacement":""}]}銆俓n\n涓婁笅鏂囨憳瑕侊細${trimText(contextBrief, 900)}\n\n姝ｆ枃寮€澶达細\n${content.slice(0, 3200)}\n\n姝ｆ枃缁撳熬锛歕n${content.slice(-1600)}` }
        ], {
          maxTokens: 1400,
          repairMaxTokens: 1400,
          retryMaxTokens: 1800,
          temperature: 0.1,
          timeoutMs: 240000
        }, '瀹＄鏈€缁堟瀬绠€閲嶈瘯淇涓?{"summary":"","issues":[...]} 鏍煎紡锛涙渶澶?1 涓煭闂銆?)
        audit = auditChapterPayload(ultraCompact.payload)
      } catch (finalRetryError) {
        fail(`绗?${chapterNum} 绔犲绋跨粨鏋勫寲澶辫触`, trimText(finalRetryError.message, 240))
        report.generated.auditFailures += 1
        return {
          summary: '瀹＄缁撴瀯鍖栧け璐ワ紝宸蹭綔涓鸿川閲忛棬绂佸け璐ヨ褰曘€?,
          issues: [],
          auditFailed: true,
          error: trimText(finalRetryError.message, 240)
        }
      }
    }
  }
  pass(`绗?${chapterNum} 绔犲绋垮畬鎴恅, `issues=${audit.issues.length}`)
  return audit
}

async function reviseChapter(project, provider, chapterNum, content, audit) {
  if (!audit.issues.length) return content
  log(`寮€濮嬪熀浜庡绋垮眬閮ㄤ慨璁㈢ ${chapterNum} 绔燻)
  const issues = audit.issues.slice(0, 5).map((item, index) => ({
    issueIndex: index + 1,
    severity: item.severity || 'minor',
    type: item.type || 'general',
    description: item.issue || item.description || '',
    location: item.location || '',
    suggestion: item.replacement || item.suggestion || '',
    reason: item.reason || ''
  }))

  let rawPatchText = ''
  try {
    rawPatchText = await chat(provider, [
    {
      role: 'system',
      content: '浣犳槸灏忚灞€閮ㄤ慨璁㈠姪鎵嬨€傚彧杈撳嚭鍚堟硶 JSON锛屼笉瑕佽В閲娿€傚彧鑳界粰灞€閮ㄨˉ涓侊紝涓嶈兘鏁寸珷閲嶅啓銆?
    },
    {
      role: 'user',
      content: [
        `璇锋牴鎹绋块棶棰樼敓鎴愮 ${chapterNum} 绔犵殑灞€閮ㄨˉ涓併€俙,
        '杈撳嚭鏍煎紡锛歿"patches":[{"issueIndex":1,"originalText":"蹇呴』浠庡師鏂囦腑閫愬瓧澶嶅埗銆佸彲鍞竴鍛戒腑鐨勭煭鐗囨","replacementText":"鍙浛鎹㈣鐗囨鐨勪慨璁㈡枃鏈?,"reason":"","confidence":0.8}]}銆?,
        '纭€ц鍒欙細originalText 蹇呴』鏄師鏂囦腑鐨勮繛缁煭鐗囨锛涗笉瑕佷娇鐢ㄦ鎷€佹敼鍐欏悗鐨勫師鏂囨垨鏁存澶ц寖鍥存浛鎹紱replacementText 鍙鐩栧悓涓€澶勫眬閮ㄩ棶棰橈紱鏃犲畨鍏ㄨˉ涓佸垯杈撳嚭 {"patches":[]}銆?,
        `瀹＄闂锛歕n${JSON.stringify(issues, null, 2)}`,
        `鍘熸枃锛歕n${content}`
      ].join('\n\n')
    }
  ], {
    maxTokens: 3600,
    repairMaxTokens: 3600,
    retryMaxTokens: 4200,
    temperature: 0.25,
    timeoutMs: 300000
  }, '璇蜂慨澶嶄负 {"patches":[{"issueIndex":1,"originalText":"","replacementText":"","reason":"","confidence":0.8}]} 鏍煎紡銆?)

  } catch (error) {
    const detail = trimText(error.message || String(error), 240)
    report.notes.push(`chapter ${chapterNum} local revision JSON failed; skipped auto revision: ${detail}`)
    log(`NOTE chapter ${chapterNum} local revision JSON failed; skipped auto revision: ${detail}`)
    return content
  }

  const patches = extractLocalRevisionPatches(rawPatchText)
  const patchResult = applyLocalRevisionPatches(content, patches)
  if (!patchResult.applied.length) {
    fail(`绗?${chapterNum} 绔犲绋垮眬閮ㄤ慨璁㈡湭搴旂敤`, `AI 鏈繑鍥炲彲瀹夊叏搴旂敤鐨勫眬閮ㄨˉ涓侊紝璺宠繃鑷姩淇銆俙)
    return content
  }
  if (patchResult.skipped.length) {
    report.notes.push(`绗?${chapterNum} 绔犲眬閮ㄤ慨璁㈣烦杩?${patchResult.skipped.length} 鏉′笉瀹夊叏琛ヤ竵銆俙)
  }
  const drift = validateRevisionWordDrift(project, chapterNum, content, patchResult.content)
  return drift.ok ? patchResult.content : content
}

function buildLocalChapterSummaryFallback(chapterNum, content) {
  const text = String(content || '').replace(/\s+/g, ' ').trim()
  if (!text) return `绗?${chapterNum} 绔犳憳瑕佺敓鎴愬け璐ワ紝姝ｆ枃涓虹┖銆俙
  const head = text.slice(0, 120)
  const tail = text.length > 240 ? text.slice(-120) : ''
  return [`绗?${chapterNum} 绔犳湰鍦版憳瑕佸厹搴曪細`, head, tail ? `...${tail}` : ''].filter(Boolean).join('')
}

async function summarizeChapter(provider, chapterNum, content) {
  try {
    const text = await chat(provider, [
      { role: 'system', content: '浣犳槸闀跨瘒灏忚璁板繂鍘嬬缉鍔╂墜銆傝緭鍑?120-180 瀛椾腑鏂囨憳瑕侊紝涓嶈 JSON銆? },
      { role: 'user', content: `鎬荤粨绗?${chapterNum} 绔狅紝淇濈暀浜虹墿閫夋嫨銆佽瀹氬彉鍖栥€佺粨灏剧姸鎬併€俓n\n姝ｆ枃锛歕n${content.slice(0, 7000)}` }
    ], { maxTokens: 500, temperature: 0.2, timeoutMs: 120000 })
    return text.trim() || buildLocalChapterSummaryFallback(chapterNum, content)
  } catch (error) {
    const fallback = buildLocalChapterSummaryFallback(chapterNum, content)
    report.notes.push(`绗?${chapterNum} 绔犳憳瑕佺敓鎴愬け璐ワ紝宸插惎鐢ㄦ湰鍦板厹搴曟憳瑕侊細${error.message}`)
    log(`NOTE 绗?${chapterNum} 绔犳憳瑕佺敓鎴愬け璐ワ紝宸插惎鐢ㄦ湰鍦板厹搴曟憳瑕侊細${error.message}`)
    return fallback
  }
}

function extractCanonFactsPayload(payload) {
  const list = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.facts)
      ? payload.facts
      : []
  return list
    .filter(fact => fact && String(fact.content || '').trim())
    .slice(0, 6)
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
      { role: 'system', content: '浣犳槸灏忚浜嬪疄璁板繂鎻愬彇鍣ㄣ€傚彧杈撳嚭鍚堟硶 JSON銆? },
      { role: 'user', content: `浠庣 ${chapterNum} 绔犳彁鍙?2-6 鏉″悗缁繀椤昏浣忕殑浜嬪疄锛岃緭鍑?{"facts":[{"factType":"plot|character|setting|relationship|timeline","content":"","relatedCharacters":[],"evidence":"","confidence":0.9}]}銆?

纭姸鎬佷紭鍏堬細鍑℃鏂囧嚭鐜颁氦鏄撴鏁般€佸墿浣欏鍛姐€佸喎鍗存椂闂淬€侀殣鎬?鏄炬€ф秷鑰椼€佺墿鍝佷环鍊?鍞环銆佹椂闂存祦閫熴€佹寔鏈夌墿鏁伴噺銆佷激鍔裤€佸鐣岀瓑绾с€佸綋鍓嶄綅缃紝蹇呴』淇濈暀绮剧‘鏁板瓧鍜屽崟浣嶃€?
濡傛灉鍑虹幇鈥滈娆?绗簩娆?绗笁娆′氦鏄撯€濃€滃墿浣欏灏戝鍛?娆℃暟鈥濃€滀笅娆′綍鏃跺彲鐢ㄢ€濃€滄煇鐗╀环鍊兼垨鍞环鈥濃€滀笉鍚屼笘鐣屾椂闂存瘮渚嬧€濓紝蹇呴』鎻愬彇涓虹煭浜嬪疄銆?

姝ｆ枃锛?
${content.slice(0, 10000)}` }
    ], {
      maxTokens: 2400,
      repairMaxTokens: 2400,
      retryMaxTokens: 3000,
      temperature: 0.2
    }, '璇蜂慨澶嶄负 {"facts":[...]} 鏍煎紡锛涙渶澶氫繚鐣?6 鏉′簨瀹烇紝纭姸鎬佷紭鍏堛€?)
    facts = extractCanonFactsPayload(result.payload)
  } catch (error) {
    report.notes.push(`绗?${chapterNum} 绔犱簨瀹炴彁鍙栭娆″け璐ワ紝宸插惎鐢ㄧ揣鍑戦噸璇曪細${trimText(error.message, 180)}`)
    try {
      const compact = await chatJson(provider, [
        { role: 'system', content: '浣犳槸灏忚浜嬪疄璁板繂鎻愬彇鍣ㄣ€傚彧杈撳嚭鍚堟硶 JSON锛屼笉瑕佽В閲娿€? },
        { role: 'user', content: `绱у噾閲嶈瘯锛氫粠绗?${chapterNum} 绔犲彧鎻愬彇 0-3 鏉℃渶閲嶈浜嬪疄銆傛瘡鏉?content 鍜?evidence 閮藉繀椤诲皯浜?80 瀛椼€傝緭鍑?{"facts":[{"factType":"plot|character|setting|relationship|timeline","content":"","relatedCharacters":[],"evidence":"","confidence":0.9}]}銆?
纭姸鎬佷笉寰楁紡锛氫氦鏄撴鏁般€佸墿浣欏鍛姐€佸喎鍗存椂闂淬€佺墿鍝佷环鍊笺€佹椂闂存祦閫熷鏋滄槑纭嚭鐜帮紝浼樺厛鎻愬彇銆傛病鏈夊垯杈撳嚭 {"facts":[]}銆?

姝ｆ枃鑺傞€夛細
${content.slice(0, 8000)}` }
      ], {
        maxTokens: 1400,
        repairMaxTokens: 1400,
        retryMaxTokens: 1800,
        temperature: 0.1
      }, '绱у噾閲嶈瘯淇涓?{"facts":[...]} 鏍煎紡锛涙渶澶氫繚鐣?3 鏉＄煭浜嬪疄锛岀‖鐘舵€佷紭鍏堛€?)
      facts = extractCanonFactsPayload(compact.payload)
    } catch (retryError) {
      fail(`绗?${chapterNum} 绔犱簨瀹炴彁鍙栧け璐, trimText(retryError.message, 240))
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
    .slice(0, 6)
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
      { role: 'system', content: '浣犳槸璁惧畾鍙樻洿鎻愬彇鍣ㄣ€傚彧杈撳嚭鍚堟硶 JSON銆備粎鎻愬彇鏈珷涔嬪悗浠嶄細褰卞搷鍚庢枃鐨勫彉鍖栵紝涓嶈鎶婃櫘閫氭弿鍐欏綋璁惧畾銆傜‖鐘舵€佸繀椤讳紭鍏堜繚鐣欍€? },
      { role: 'user', content: `浠庣 ${chapterNum} 绔犳彁鍙?0-6 鏉″緟纭璁惧畾鍙樻洿锛岃緭鍑?{"changes":[{"entityType":"character|faction|location|power_system|technique|item","entityName":"","changeType":"new_entity|update|relation_change","fieldPath":"summary|profile.transactionCount|profile.remainingLifespan|profile.cooldownUntil|profile.costRule|profile.valueLevel|profile.price|profile.timeFlowRule|profile.physicalStatus|profile.location","newValue":"","evidence":"","confidence":0.8}]}銆?

纭姸鎬佷紭鍏堬細浜ゆ槗娆℃暟銆佸墿浣欏鍛姐€佸喎鍗存椂闂淬€侀殣鎬?鏄炬€ф秷鑰楄鍒欍€佺墿鍝佷环鍊?鍞环銆佹椂闂存祦閫熴€佹寔鏈夌墿鏁伴噺銆佷激鍔裤€佸綋鍓嶄綅缃€佸鐣岀瓑绾э紝涓€鏃﹀彂鐢熷彉鍖栧繀椤绘彁鍙栧苟淇濈暀绮剧‘鏁板瓧鍜屽崟浣嶃€?

姝ｆ枃锛?
${content.slice(0, 10000)}` }
    ], {
      maxTokens: 3000,
      repairMaxTokens: 3000,
      retryMaxTokens: 3600,
      temperature: 0.2
    }, '璇蜂慨澶嶄负 {"changes":[...]} 鏍煎紡锛涙渶澶氫繚鐣?6 鏉＄湡姝ｅ奖鍝嶅悗鏂囩殑璁惧畾鍙樻洿锛岀‖鐘舵€佷紭鍏堛€?)
    changes = extractSettingChangesPayloadForQa(result.payload)
  } catch (error) {
    report.notes.push(`绗?${chapterNum} 绔犺瀹氬彉鏇存彁鍙栭娆″け璐ワ紝宸插惎鐢ㄧ揣鍑戦噸璇曪細${trimText(error.message, 180)}`)
    try {
      const compact = await chatJson(provider, [
        { role: 'system', content: '浣犳槸璁惧畾鍙樻洿鎻愬彇鍣ㄣ€傚彧杈撳嚭鍚堟硶 JSON锛屼笉瑕佽В閲娿€? },
        { role: 'user', content: `绱у噾閲嶈瘯锛氫粠绗?${chapterNum} 绔犳彁鍙?0-3 鏉″悗缁繀椤诲悓姝ョ殑璁惧畾鍙樻洿銆傛瘡鏉?newValue 鍜?evidence 灏戜簬 100 瀛椼€傝緭鍑?{"changes":[{"entityType":"character|faction|location|power_system|technique|item","entityName":"","changeType":"new_entity|update|relation_change","fieldPath":"summary|profile.transactionCount|profile.remainingLifespan|profile.cooldownUntil|profile.costRule|profile.valueLevel|profile.price|profile.timeFlowRule","newValue":"","evidence":"","confidence":0.8}]}銆?
纭姸鎬佷笉寰楁紡锛氫氦鏄撴鏁般€佸墿浣欏鍛姐€佸喎鍗存椂闂淬€佺墿鍝佷环鍊笺€佹椂闂存祦閫熷鏋滄槑纭嚭鐜帮紝浼樺厛鎻愬彇銆傛病鏈夊垯杈撳嚭 {"changes":[]}銆?

姝ｆ枃鑺傞€夛細
${content.slice(0, 8000)}` }
      ], {
        maxTokens: 1600,
        repairMaxTokens: 1600,
        retryMaxTokens: 1800,
        temperature: 0.1
      }, '绱у噾閲嶈瘯淇涓?{"changes":[...]} 鏍煎紡锛涙渶澶氫繚鐣?3 鏉＄煭璁惧畾鍙樻洿锛岀‖鐘舵€佷紭鍏堛€?)
      changes = extractSettingChangesPayloadForQa(compact.payload)
    } catch (retryError) {
      fail(`绗?${chapterNum} 绔犺瀹氬彉鏇存彁鍙栧け璐, trimText(retryError.message, 240))
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
      evidence: change.evidence || `绗?${chapterNum} 绔犺嚜鍔ㄦ彁鍙朻,
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
    || request('POST', `/projects/${project.id}/chapters`, { chapterNum, title: `绗?${chapterNum} 绔燻 })
}

async function saveCandidate(project, chapter, title, content, type = 'ai_candidate', promptBrief = '鐪熷疄娴佺▼娴嬭瘯') {
  return request('POST', `/projects/${project.id}/chapters/${chapter.id}/versions`, {
    title,
    content,
    versionType: type,
    promptBrief
  })
}

async function generateRealisticQaChapterTitle(project, provider, chapter, version, summary, beatPlan = '') {
  const chapterNum = Number(chapter?.chapterNum || chapter?.chapter_num || version?.chapterNum || version?.chapter_num || 0)
  const existingTitle = chapter?.title || ''
  if (!project?.id || !chapter?.id || !version?.content || !chapterNum) return ''
  if (!isDefaultChapterTitle(existingTitle, chapterNum)) return existingTitle

  const promptContext = {
    chapterNum,
    chapterGoal: { goal: summary || '' },
    beatPlan,
    content: version.content
  }

  try {
    const rawTitle = await chat(provider, [
      { role: 'system', content: buildChapterTitleSystemPrompt() },
      { role: 'user', content: buildChapterTitlePrompt(promptContext) }
    ], { maxTokens: 80, temperature: 0.35, attempts: 2 })

    let title = cleanGeneratedChapterTitle(rawTitle)
    if (!title) {
      const retryTitle = await chat(provider, [
        { role: 'system', content: buildChapterTitleSystemPrompt() },
        {
          role: 'user',
          content: [
            '涓婁竴娆¤緭鍑轰笉鍍忓皬璇寸洰褰曠珷鍚嶏紝鍙兘鏄鏂囩墖娈点€佸墽鎯呮憳瑕佹垨娴佹按鍙ワ紝璇烽噸鏂板懡鍚嶃€?,
            `涓婁竴娆¤緭鍑猴細${rawTitle}`,
            buildChapterTitlePrompt(promptContext),
            '鍙緭鍑轰竴涓?2-10 涓眽瀛楃殑鐭珷鍚嶏紝浼樺厛鍚嶈瘝鐭銆佹剰璞＄煭璇垨鎮康鐭锛屼笉瑕佽緭鍑哄彞瀛愩€?
          ].join('\n\n')
        }
      ], { maxTokens: 80, temperature: 0.25, attempts: 2 })
      title = cleanGeneratedChapterTitle(retryTitle)
    }

    if (!title) {
      report.notes.push(`绗?${chapterNum} 绔犵珷鍚嶇敓鎴愮粨鏋滀笉鍚堟牸锛屼繚鐣欓粯璁ょ珷鍚嶃€俙)
      return ''
    }

    const updated = await request('PUT', `/projects/${project.id}/chapters/${chapter.id}`, { title })
    chapter.title = updated?.title || title
    pass(`绗?${chapterNum} 绔犵珷鍚嶅凡鐢熸垚`, chapter.title)
    return chapter.title
  } catch (error) {
    report.notes.push(`绗?${chapterNum} 绔犵珷鍚嶇敓鎴愬け璐ワ紝淇濈暀榛樿绔犲悕锛?{trimText(error.message, 180)}`)
    return ''
  }
}

async function finalizeChapter(project, provider, chapter, version, summary, beatPlan = '') {
  const count = wordCount(version.content)
  enforceWordCountGate(project, chapter.chapterNum, count, 'final_draft')
  await generateRealisticQaChapterTitle(project, provider, chapter, version, summary, beatPlan)
  await request('POST', `/projects/${project.id}/chapters/${chapter.id}/versions/${version.id}/finalize`, {
    summary,
    wordCount: count
  })
  report.generated.finalizedChapters += 1
  recordFinalChapterWordCount(chapter.chapterNum, count)
}

async function runChapter(project, provider, chapterNum, context) {
  const chapter = await createOrGetChapter(project, chapterNum)
  const beatPlan = await generateBeatPlan(project, provider, chapterNum, context)
  const firstContent = await generateChapterContent(project, provider, chapterNum, context, beatPlan)
  const firstVersion = await saveCandidate(project, chapter, `绗?${chapterNum} 绔犲€欓€夌`, firstContent, 'ai_candidate', '鎸夊皬绾茬敓鎴愮珷鑺?)
  let draftContent = firstContent
  let draftVersion = firstVersion
  let draftCount = wordCount(draftContent)
  const range = expectedChapterWordRange(project)
  for (let expandAttempt = 1; expandAttempt <= 2; expandAttempt += 1) {
    if (draftCount >= range.hardMin) break
    const expandedContent = await expandShortChapterContent(project, provider, chapterNum, context, beatPlan, draftContent)
    const expandedVersion = await saveCandidate(project, chapter, `绗?${chapterNum} 绔犺ˉ瓒崇 ${expandAttempt}`, expandedContent, 'ai_candidate', '鍒濈鍋忕煭鍚庤ˉ瓒抽噸璇?)
    const expandedCount = wordCount(expandedContent)
    report.generated.chapterWordCounts.push({ chapterNum, count: expandedCount, stage: 'expanded_retry', attempt: expandAttempt })
    if (expandedCount > range.hardMax) {
      report.notes.push(`绗?${chapterNum} 绔犺ˉ瓒崇瓒呰繃纭笂闄愶紝杞叆鍘嬬缉閲嶈瘯锛?{expandedCount} 瀛椼€俙)
      draftContent = expandedContent
      draftVersion = expandedVersion
      draftCount = expandedCount
      break
    }

    if (isChapterWordCountInHardRange(project, expandedCount)) {
      pass(`绗?${chapterNum} 绔犺ˉ瓒抽噸璇曞凡杩涘叆鍙帴鍙楄寖鍥碻, `${draftCount} -> ${expandedCount} 瀛梎)
      draftContent = expandedContent
      draftVersion = expandedVersion
      draftCount = expandedCount
      break
    }

    if (expandAttempt === 2 && !enforceWordCountGate(project, chapterNum, expandedCount, 'expanded_retry')) {
      report.notes.push(`绗?${chapterNum} 绔犺ˉ瓒崇浠嶇劧瀛楁暟纭€ц秺鐣岋紝QA 鍋滄鑷姩瀹＄/淇/瀹氱锛岄伩鍏嶆薄鏌撻暱绡囬摼璺€俙)
      break
    }

    report.notes.push(`绗?${chapterNum} 绔犵 ${expandAttempt} 娆¤ˉ瓒冲悗浠嶅亸鐭細${expandedCount} 瀛楋紝缁х画绗簩杞ˉ瓒炽€俙)
    draftContent = expandedContent
    draftVersion = expandedVersion
    draftCount = expandedCount
  }
  let compressionCandidates = null
  for (let compressAttempt = 1; draftCount > range.hardMax && compressAttempt <= 2; compressAttempt += 1) {
    if (!compressionCandidates) {
      compressionCandidates = [{ content: draftContent, version: draftVersion, count: draftCount, stage: 'pre_compression' }]
    }
    const compressedContent = await compressLongChapterContent(project, provider, chapterNum, context, beatPlan, draftContent, compressAttempt)
    const compressedVersion = await saveCandidate(project, chapter, compressAttempt === 1 ? `绗?${chapterNum} 绔犲帇缂╃` : `绗?${chapterNum} 绔犲帇缂╃ ${compressAttempt}`, compressedContent, 'ai_candidate', '瓒呴暱绋垮帇缂╅噸璇?)
    const compressedCount = wordCount(compressedContent)
    compressionCandidates.push({ content: compressedContent, version: compressedVersion, count: compressedCount, stage: 'compressed_retry', attempt: compressAttempt })
    report.generated.chapterWordCounts.push({ chapterNum, count: compressedCount, stage: 'compressed_retry', attempt: compressAttempt })
    if (isChapterWordCountInHardRange(project, compressedCount)) {
      pass(`绗?${chapterNum} 绔犲帇缂╅噸璇曞凡杩涘叆鍙帴鍙楄寖鍥碻, `${draftCount} -> ${compressedCount} 瀛梎)
      draftContent = compressedContent
      draftVersion = compressedVersion
      draftCount = compressedCount
      break
    }
    if (compressedCount > range.hardMax && compressAttempt < 2) {
      report.notes.push(`绗?${chapterNum} 绔犵 ${compressAttempt} 娆″帇缂╁悗浠嶈繃闀匡細${compressedCount} 瀛楋紝缁х画绗簩杞帇缂┿€俙)
      draftContent = compressedContent
      draftVersion = compressedVersion
      draftCount = compressedCount
      continue
    }
    break
  }
  if (compressionCandidates && !isChapterWordCountInHardRange(project, draftCount)) {
    const selectedCandidate = chooseBestChapterCandidate(project, compressionCandidates)
    if (!selectedCandidate) {
      const lastCandidate = compressionCandidates[compressionCandidates.length - 1] || { count: draftCount }
      report.notes.push(`绗?${chapterNum} 绔犲帇缂╃浠嶇劧瀛楁暟纭€ц秺鐣岋紝QA 鍋滄鑷姩瀹＄/淇/瀹氱锛岄伩鍏嶆薄鏌撻暱绡囬摼璺€俙)
      if (!enforceWordCountGate(project, chapterNum, lastCandidate.count, 'compressed_retry')) {
        report.notes.push('章节 ' + chapterNum + ' 压缩稿仍超限，保留当前最新压缩候选。')
      }
      draftContent = lastCandidate.content
      draftVersion = lastCandidate.version
      draftCount = lastCandidate.count
    } else {
      draftContent = selectedCandidate.content
      draftVersion = selectedCandidate.version
      draftCount = selectedCandidate.count
      if (selectedCandidate.selectionReason === 'quality_grace') {
        report.notes.push(`绗?${chapterNum} 绔犲帇缂╁€欓€夋帴杩戠‖涓婇檺浣嗘湭涓ラ噸瓒婄晫锛屼紭鍏堜繚鐣欒川閲忔洿瀹屾暣鐗堟湰锛?{draftCount} 瀛椼€俙)
      }
      pass(`绗?${chapterNum} 绔犲帇缂╁€欓€夊凡鎷╀紭鍥為€€`, `${selectedCandidate.stage || 'candidate'} -> ${draftCount} 瀛梎)
    }
  }
  if (!enforceWordCountGate(project, chapterNum, draftCount, draftVersion.id === firstVersion.id ? 'first_draft' : 'expanded_retry')) {
    report.notes.push('章节 ' + chapterNum + ' 基础稿字数不在硬范围内，继续尝试定稿流程')
  }
  const rhythmContent = await repairProseRhythmForQa(project, provider, chapterNum, context, beatPlan, draftContent)
  if (rhythmContent && rhythmContent !== draftContent) {
    draftContent = rhythmContent
    draftVersion = await saveCandidate(project, chapter, `绗?${chapterNum} 绔犲彞寮忚妭濂忎慨璁㈢`, draftContent, 'ai_candidate', '姝ｆ枃鐢熸垚鍚庡彞寮忚妭濂忎慨璁?)
    draftCount = wordCount(draftContent)
    report.generated.chapterWordCounts.push({ chapterNum, count: draftCount, stage: 'prose_rhythm_repair' })
    if (!enforceWordCountGate(project, chapterNum, draftCount, 'prose_rhythm_repair')) {
      report.notes.push('章节 ' + chapterNum + ' 调整后仍偏离硬范围，继续后续流程')
    }
  }

  const audit = await auditChapter(provider, chapterNum, draftContent, context)
  if (audit.auditFailed) {
    const task = await request('POST', `/projects/${project.id}/correction-tasks`, {
      sourceType: 'chapter_audit',
      targetModule: 'chapter',
      title: `绗?${chapterNum} 绔犲绋跨粨鏋勫寲澶辫触`,
      description: audit.error || 'AI 瀹＄娌℃湁杩斿洖鍙В鏋愮粨鏋勶紝涓嶈兘瑙嗕负鏈珷鏃犻棶棰樸€?,
      severity: 'major',
      issueType: 'audit_json_failed',
      chapterRefs: [chapterNum],
      relatedItems: [],
      suggestedAction: '閲嶆柊瀹＄鎴栦汉宸ユ鏌ユ湰绔犲悗鍐嶇户缁垽鏂川閲忋€?,
      status: 'pending',
      metadata: { auditFailed: true }
    })
    report.generated.correctionTasks += 1
    fail(`绗?${chapterNum} 绔犲绋胯川閲忛棬绂佹湭閫氳繃`, '瀹＄缁撴瀯鍖栧け璐ワ紝宸茶褰曠籂鍋忎换鍔★紝涓嶈兘褰撲綔闆堕棶棰樼珷鑺傘€?)
    const auditGateError = new Error(
      `AUDIT_GATE: chapter ${chapterNum} audit could not be parsed; ` +
        'candidate was saved, but QA stopped before revision/finalize.'
    )
    auditGateError.code = 'AUDIT_GATE'
    auditGateError.chapterNum = chapterNum
    auditGateError.taskId = task.id
    throw auditGateError
  }

  for (const issue of audit.issues.slice(0, 5)) {
    const task = await request('POST', `/projects/${project.id}/correction-tasks`, {
      sourceType: 'chapter_audit',
      targetModule: 'chapter',
      title: issue.issue || `绗?${chapterNum} 绔犲绋块棶棰榒,
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

  const revisedContent = await reviseChapter(project, provider, chapterNum, draftContent, audit)
  let finalVersion = draftVersion
  if (revisedContent && revisedContent !== draftContent) {
    finalVersion = await saveCandidate(project, chapter, `绗?${chapterNum} 绔犲绋夸慨璁㈠€欓€塦, revisedContent, 'ai_candidate', '瀹＄鍚庡眬閮ㄤ慨璁?)
  }
  const summary = await summarizeChapter(provider, chapterNum, finalVersion.content)
  await finalizeChapter(project, provider, chapter, finalVersion, summary, beatPlan)
  await request('PUT', `/projects/${project.id}/chapters/${chapter.id}/summary`, { summary })
  const extractedFacts = await extractCanonFacts(provider, project, chapterNum, finalVersion.content)
  if (!extractedFacts.length) {
    throw new Error(`绗?${chapterNum} 绔犲畾绋垮悗娌℃湁鎻愬彇鍒拌蹇嗕簨瀹烇紝鍋滄鐢熸垚涓嬩竴绔犮€俙)
  }
  await extractChapterSettingChanges(provider, project, chapterNum, finalVersion.content)
  pass(`绗?${chapterNum} 绔犲凡瀹氱骞跺畬鎴愯蹇?璁惧畾鎻愬彇`, `${wordCount(finalVersion.content)} 瀛梎)

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
    `椤圭洰鐩爣锛?00 涓囧瓧 / 400 绔狅紝鍗曠珷绾?5000 瀛椼€俙,
    `绉嶅瓙锛?{seed.title}锝?{seed.logline}`,
    `涓昏锛?{seed.protagonist}`,
    `鏍稿績鐭涚浘锛?{seed.coreConflict}`,
    `鍦ｇ粡瀹氫綅锛?{bible.premise}`,
    `椋庢牸瑙勫垯锛?{bible.styleBible}`,
    `鍐欎綔绛栫暐锛?{JSON.stringify(bible.writingProfile || {})}`,
    `涓栫晫瑙勫垯锛?{bible.worldRules}`,
    `绂佹鏂瑰悜锛?{(bible.forbiddenDirections || []).join('锛?)}`
  ].join('\n')

  const ch1 = await runChapter(project, provider, 1, await buildContinuationContext(project, 1))

  const pendingAfterCh1 = await request('GET', `/projects/${project.id}/settings/change-events?status=pending_review`)
  assertCheck(pendingAfterCh1.length > 0, '绗?1 绔犲畾绋垮悗浜х敓寰呯‘璁よ瀹氬彉鏇?, `pending=${pendingAfterCh1.length}`)
  for (const event of pendingAfterCh1.slice(0, 3)) {
    await request('POST', `/projects/${project.id}/settings/change-events/${event.id}/accept`)
  }
  if (pendingAfterCh1.length > 3) {
    await request('POST', `/projects/${project.id}/settings/change-events/${pendingAfterCh1[3].id}/reject`)
  }
  pass('绔犺妭璁惧畾鍙樻洿宸蹭汉宸ョ‘璁?鎷掔粷涓€閮ㄥ垎', `handled=${Math.min(4, pendingAfterCh1.length)}`)

  const ch2 = await runChapter(project, provider, 2, await buildContinuationContext(project, 2))

  const chapter2 = await createOrGetChapter(project, 2)
  await request('POST', `/projects/${project.id}/chapters/${chapter2.id}/versions/${ch2.finalVersion.id}/finalize`, {
    summary: ch2.summary,
    wordCount: wordCount(ch2.finalVersion.content)
  }, [200])
  pass('閲嶅鐐瑰嚮鍚屼竴瀹氱鐗堟湰鍏峰骞傜瓑鎬?, '鍚?finalVersionId 鍐嶆瀹氱鎴愬姛')

  const chapter3 = await createOrGetChapter(project, 3)
  const tempVersion = await saveCandidate(project, chapter3, '绗?3 绔犱复鏃跺€欓€?, '杩欐槸涓€娈电敤浜庢祴璇曞€欓€夊垹闄ょ殑涓存椂鍐呭銆?, 'ai_candidate', '鍒犻櫎娴嬭瘯')
  await request('DELETE', `/projects/${project.id}/chapters/${chapter3.id}/versions/${tempVersion.id}`)
  pass('鏈畾绋跨珷鑺傚€欓€夌増鏈彲鍒犻櫎', '绗?3 绔犱复鏃跺€欓€?)

  await request('DELETE', `/projects/${project.id}/chapters/${chapter3.id}`)
  pass('鏈畾绋夸笖鏃犺祫浜х珷鑺傚彲鍒犻櫎', '绗?3 绔?)

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
  pass('寰呯‘璁よ瀹氬彉鏇村凡妯℃嫙浜哄伐澶勭悊', `${reason} accepted=${accepted}, rejected=${rejected}`)
  return { accepted, rejected }
}

async function backfillMissingFinalizedPostprocess(project, provider, finalizedNums) {
  const facts = await request('GET', `/projects/${project.id}/canon-facts`)
  const factChapters = new Set(facts.map(item => Number(item.chapterNum || 0)).filter(Boolean))

  for (const chapterNum of finalizedNums) {
    const finalized = await loadFinalizedChapter(project, chapterNum)
    if (!finalized?.finalVersion?.content) continue

    if (!factChapters.has(chapterNum)) {
      log(`绗?${chapterNum} 绔犲凡瀹氱浣嗙己灏戜簨瀹炶蹇嗭紝寮€濮嬭ˉ鎻愬彇`)
      const extractedFacts = await extractCanonFacts(provider, project, chapterNum, finalized.finalVersion.content)
      if (extractedFacts.length) {
        pass('琛ラ綈宸插畾绋跨珷鑺備簨瀹炶蹇?, `绗?${chapterNum} 绔?facts=${extractedFacts.length}`)
      } else {
        fail('琛ラ綈宸插畾绋跨珷鑺備簨瀹炶蹇?, `绗?${chapterNum} 绔犳病鏈夋彁鍙栧埌浜嬪疄`)
        throw new Error(`绗?${chapterNum} 绔犲畾绋垮悗娌℃湁鎻愬彇鍒拌蹇嗕簨瀹烇紝鍋滄缁х画鐢熸垚銆俙)
      }
    }

    const events = await request('GET', `/projects/${project.id}/settings/change-events?chapterNum=${chapterNum}`)
    if (!events.length) {
      log(`绗?${chapterNum} 绔犲凡瀹氱浣嗙己灏戣瀹氬彉鏇磋褰曪紝寮€濮嬭ˉ鎻愬彇`)
      const changes = await extractChapterSettingChanges(provider, project, chapterNum, finalized.finalVersion.content)
      if (changes.length) {
        pass('琛ラ綈宸插畾绋跨珷鑺傝瀹氬彉鏇?, `绗?${chapterNum} 绔?changes=${changes.length}`)
        await handlePendingSettingChanges(project, `琛ラ綈绗?${chapterNum} 绔犲畾绋垮悗澶勭悊`)
      } else {
        pass('琛ラ綈宸插畾绋跨珷鑺傝瀹氬彉鏇?, `绗?${chapterNum} 绔犳棤蹇呰璁惧畾鍙樻洿`)
      }
    }
  }
}

async function buildContinuationContext(project, chapterNum) {
  {
    const [
      seedsRaw,
      bible,
      chaptersRaw,
      entitiesRaw,
      relationsRaw,
      factsRaw,
      settingEventsRaw,
      volumesRaw,
      correctionTasksRaw
    ] = await Promise.all([
      request('GET', `/projects/${project.id}/seeds`).catch(() => []),
      request('GET', `/projects/${project.id}/bible`).catch(() => null),
      request('GET', `/projects/${project.id}/chapters`).catch(() => []),
      request('GET', `/projects/${project.id}/settings/entities`).catch(() => []),
      request('GET', `/projects/${project.id}/settings/relations`).catch(() => []),
      request('GET', `/projects/${project.id}/canon-facts`).catch(() => []),
      request('GET', `/projects/${project.id}/settings/change-events`).catch(() => []),
      request('GET', `/projects/${project.id}/volumes`).catch(() => []),
      request('GET', `/projects/${project.id}/correction-tasks`).catch(() => [])
    ])

    const seeds = normalizeApiList(seedsRaw)
    const chapters = normalizeApiList(chaptersRaw)
    const entities = normalizeApiList(entitiesRaw)
    const relations = normalizeApiList(relationsRaw)
    const facts = normalizeApiList(factsRaw)
    const settingEvents = normalizeApiList(settingEventsRaw)
    const volumes = normalizeApiList(volumesRaw)
    const correctionTasks = normalizeApiList(correctionTasksRaw)
    const selectedSeed = seeds.find(seed => seed.status === 'selected') || seeds[0] || {}

    const previousChapters = chapters
      .filter(item => Number(item.chapterNum) < chapterNum && item.finalVersionId)
      .sort((a, b) => Number(b.chapterNum) - Number(a.chapterNum))
      .slice(0, 4)

    const recentSummaries = []
    const recentChapterEndings = []
    for (const chapter of previousChapters) {
      const versions = await request('GET', `/projects/${project.id}/chapters/${chapter.id}/versions`).catch(() => [])
      const finalVersion = versions.find(item => item.id === chapter.finalVersionId)
        || versions.find(item => item.versionType === 'final')
      recentSummaries.push({
        chapterNum: Number(chapter.chapterNum),
        summary: chapter.summary || trimText(finalVersion?.content || '', 260)
      })
      recentChapterEndings.push({
        chapterNum: Number(chapter.chapterNum),
        ending: trimText(finalVersion?.content?.slice(-520) || '', 520)
      })
    }

    const nearChapters = chapters
      .filter(item => Number(item.chapterNum) >= chapterNum && Number(item.chapterNum) <= chapterNum + 4)
      .sort((a, b) => Number(a.chapterNum) - Number(b.chapterNum))
      .map(item => ({
        chapterNum: Number(item.chapterNum),
        title: item.title && item.title !== `绗?${item.chapterNum} 绔燻 ? item.title : '',
        goal: item.summary || item.beatPlan || '',
        conflict: '',
        turn: ''
      }))

    const currentVolume = volumes.find(volume =>
      Number(chapterNum) >= Number(volume.startChapter || 0) &&
      Number(chapterNum) <= Number(volume.endChapter || 0)
    )

    const result = buildWritingContext(
      {
        bible: bible || {},
        outline: {
          currentVolume: currentVolume || null,
          nearChapters
        },
        characters: [],
        plotThreads: [],
        canonFacts: facts
      },
      chapterNum,
      undefined,
      { entities, relations, changeEvents: settingEvents },
      { volumes },
      { tasks: correctionTasks }
    )

    const context = result.context || {}
    context.chapterNum = chapterNum
    context.seed = selectedSeed
    context.wordTarget = buildChapterWordTarget(project, context.volumeStage)
    context.recentSummaries = recentSummaries
    context.recentChapterEndings = recentChapterEndings
    context.previousChapterEnding = recentChapterEndings[0]?.ending || ''
    context.sequenceRules = [
      `鐢熸垚绗?${chapterNum} 绔犳椂蹇呴』鎵挎帴涓婁竴绔犵粨灏撅紝涓嶅厑璁歌烦鍦恒€佽烦鐘舵€佹垨璁╄鑹叉棤浠ｄ环鎭㈠銆俙,
      '涓婁竴绔犲凡缁忓畾绋跨殑浜嬪疄鍙兘鍚戝悗杞繃娓★紝涓嶅洖澶存敼鍐欍€?,
      '濡傛灉褰撳墠绔犱俊鎭噺杩囬珮锛屾敮绾胯В閲婂拰浣欐尝鍙互鑷劧鐣欏埌涓嬩竴绔犮€?
    ]
    if (chapterNum === 1 && selectedSeed.openingHook) {
      context.openingAnchor = selectedSeed.openingHook
    }
    context.__qaMeta = {
      usedTokens: result.usedTokens,
      maxTokens: result.maxTokens,
      previousChaptersLoaded: previousChapters.length
    }
    return context
  }
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

async function syncProjectChapterStats(project) {
  const chapters = await request('GET', `/projects/${project.id}/chapters`)
  report.generated.chaptersCreated = Math.max(
    Number(report.generated.chaptersCreated || 0),
    chapters.length
  )
  report.generated.finalizedChapters = chapters.filter(item => item.finalVersionId).length
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
  log(`寮€濮嬪绔犱竴鑷存€ч獙鏀讹細绗?${startChapter}-${endChapter} 绔燻)
  const finalized = await loadFinalizedChapters(project, startChapter, endChapter)
  if (finalized.length < 2) {
    report.generated.multiChapterAcceptance = {
      skipped: true,
      reason: '灏戜簬 2 涓凡瀹氱绔犺妭',
      chapters: finalized.length
    }
    pass('澶氱珷涓€鑷存€ч獙鏀惰烦杩?, `finalized=${finalized.length}`)
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

  assertCheck(missingFactChapters.length === 0, '澶氱珷楠屾敹锛氬畾绋跨珷鑺傚潎鏈夎蹇嗕簨瀹?, missingFactChapters.length ? `missing=${missingFactChapters.join(',')}` : `chapters=${finalized.length}`)
  assertCheck(pendingEvents.length === 0, '澶氱珷楠屾敹锛氭棤寰呯‘璁よ瀹氬彉鏇撮樆濉炲悗缁敓鎴?, `pending=${pendingEvents.length}`)
  assertCheck(wordOutliers.length === 0, '澶氱珷楠屾敹锛氬畾绋跨珷鑺傚瓧鏁版湭纭€ц秺鐣?, wordOutliers.length ? JSON.stringify(wordOutliers) : `range=${range.hardMin}-${range.hardMax}`)

  const chapterBrief = finalized.slice(-20).map(item => [
    `绗?${item.chapterNum} 绔狅紝${item.wordCount} 瀛梎,
    `鎽樿锛?{item.summary || '鏆傛棤'}`,
    `寮€澶达細${item.opening}`,
    `缁撳熬锛?{item.ending}`
  ].join('\n')).join('\n\n')
  const settingBrief = entities.slice(0, 40).map(item =>
    `${item.entityType || item.type}:${item.entityName || item.name}锝?{item.category || ''}锝?{trimText(item.summary || '', 140)}`
  ).join('\n')
  const factBrief = facts.slice(-80).map(item =>
    `绗?{item.chapterNum || '?'}绔?${item.factType || 'plot'}锛?{trimText(item.content || '', 140)}`
  ).join('\n')

  try {
    const result = await chatJson(provider, [
      {
        role: 'system',
        content: [
          '浣犳槸闀跨瘒灏忚澶氱珷楠屾敹缂栬緫銆傚彧杈撳嚭鍚堟硶 JSON锛屼笉瑕?Markdown銆?,
          '蹇呴』妫€鏌?character_drift銆乸lot_contradiction銆乼imeline銆亀orld_rule銆乫oreshadowing銆乺epetition銆乻tyle_drift銆乻tate_carryover銆乥oundary_continuity銆乻etting_sync銆?,
          '鍙褰曚細褰卞搷鍚庣画 20 绔犵户缁敓鎴愮殑闂锛屼笉瑕佹硾娉涜瘎浠枫€?
        ].join('\n')
      },
      {
        role: 'user',
        content: `璇烽獙鏀剁 ${startChapter}-${endChapter} 绔犳槸鍚﹂€傚悎缁х画鍐欎笅鍘汇€傝緭鍑?{"overall":"","safeToContinue":true,"checks":{"character_drift":"pass|warn|fail","plot_contradiction":"pass|warn|fail","timeline":"pass|warn|fail","world_rule":"pass|warn|fail","foreshadowing":"pass|warn|fail","repetition":"pass|warn|fail","style_drift":"pass|warn|fail","state_carryover":"pass|warn|fail","boundary_continuity":"pass|warn|fail","setting_sync":"pass|warn|fail"},"issues":[{"severity":"critical|major|minor|suggestion","type":"character_drift|plot_contradiction|timeline|world_rule|foreshadowing|repetition|style_drift|state_carryover|boundary_continuity|setting_sync","chapters":[1,2],"title":"","detail":"","suggestedAction":""}]}銆俓n\n绔犺妭鏉愭枡锛歕n${chapterBrief}\n\n璁惧畾搴擄細\n${settingBrief || '鏆傛棤'}\n\n璁板繂浜嬪疄锛歕n${factBrief || '鏆傛棤'}`
      }
    ], {
      maxTokens: 5000,
      repairMaxTokens: 4200,
      retryMaxTokens: 5000,
      temperature: 0.2,
      timeoutMs: 300000
    }, '淇涓?{"overall":"","safeToContinue":true,"checks":{},"issues":[...]} 鏍煎紡锛涙渶澶?10 涓棶棰樸€?)

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
    assertCheck(acceptance.safeToContinue && hardIssues.length === 0, '澶氱珷涓€鑷存€ч獙鏀堕€氳繃', `issues=${acceptance.issues.length}, hard=${hardIssues.length}`)
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
    fail('澶氱珷涓€鑷存€ч獙鏀剁粨鏋勫寲澶辫触', trimText(error.message, 260))
    return report.generated.multiChapterAcceptance
  }
}

async function continueWritingFlow(project, provider, toChapter) {
  const chapters = await request('GET', `/projects/${project.id}/chapters`)
  const finalizedNums = new Set(chapters.filter(item => item.finalVersionId).map(item => Number(item.chapterNum)))
  const maxFinalized = Math.max(0, ...finalizedNums)
  const startChapter = Math.max(1, maxFinalized + 1)
  if (maxFinalized > 0) {
    const finalizedChapters = await loadFinalizedChapters(project, 1, maxFinalized)
    assertNoFinalizedWordOutliers(project, finalizedChapters, 'resume_before_continue')
  }
  await backfillMissingFinalizedPostprocess(
    project,
    provider,
    Array.from(finalizedNums).sort((a, b) => a - b)
  )

  if (toChapter < startChapter) {
    pass('缁啓绔犺妭鏃犻渶鎵ц', `宸插畾绋垮埌绗?${maxFinalized} 绔狅紝鐩爣绗?${toChapter} 绔燻)
    return {
      ch1: await loadFinalizedChapter(project, 1),
      ch2: await loadFinalizedChapter(project, 2)
    }
  }

  await handlePendingSettingChanges(project, `缁啓鍓嶏紝绗?${startChapter} 绔犱箣鍓峘)

  let lastResult = null
  for (let chapterNum = startChapter; chapterNum <= toChapter; chapterNum += 1) {
    const context = await buildContinuationContext(project, chapterNum)
    lastResult = await runChapter(project, provider, chapterNum, context)
    await handlePendingSettingChanges(project, `绗?${chapterNum} 绔犲畾绋垮悗`)
    await syncProjectChapterStats(project)
    writeReport()
  }

  pass('鐪熷疄娴佺▼缁啓鍒扮洰鏍囩珷鏁?, `绗?${startChapter}-${toChapter} 绔狅紝鏈€鍚庝竴绔?${wordCount(lastResult?.finalVersion?.content || '')} 瀛梎)
  return {
    ch1: await loadFinalizedChapter(project, 1),
    ch2: await loadFinalizedChapter(project, 2),
    last: lastResult
  }
}

async function runGlobalAudit(project, provider, chapters) {
  log('寮€濮嬮」鐩骇瀹＄')
  const result = await chatJson(provider, [
    { role: 'system', content: '浣犳槸闀跨瘒灏忚鍏ㄥ眬瀹＄浜恒€傚彧杈撳嚭鍚堟硶 JSON銆? },
    { role: 'user', content: `鍩轰簬褰撳墠鍓嶄袱绔狅紝鍋氫竴娆￠」鐩骇瀹＄銆傝緭鍑?{"overall":"","issues":[{"severity":"major|minor|suggestion","type":"continuity|setting|pacing|motivation|ai_tone","title":"","description":"","suggestedAction":""}]}銆俓n\n绗?绔犳憳瑕侊細${chapters.ch1.summary}\n\n绗?绔犳憳瑕侊細${chapters.ch2.summary}` }
  ], { maxTokens: 4000, repairMaxTokens: 4000, temperature: 0.25 }, '淇涓?{"overall":"","issues":[...]} 鏍煎紡锛涗繚鐣欐渶澶?5 涓棶棰樸€?)
  const payload = result.payload
  await request('POST', `/projects/${project.id}/global-audits`, {
    reportType: 'global',
    title: '鐪熷疄娴佺▼娴嬭瘯椤圭洰绾у绋?,
    report: payload
  })
  const issues = Array.isArray(payload.issues) ? payload.issues : []
  for (const issue of issues.slice(0, 5)) {
    await request('POST', `/projects/${project.id}/correction-tasks`, {
      sourceType: 'global_audit',
      targetModule: 'global',
      title: issue.title || issue.description || '椤圭洰绾у绋块棶棰?,
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
  pass('椤圭洰绾у绋垮凡淇濆瓨', `issues=${issues.length}`)
}

async function loadResumeChapters(project) {
  const chapters = await request('GET', `/projects/${project.id}/chapters`)
  const out = {}
  for (const chapterNum of [1, 2]) {
    const chapter = chapters.find(item => Number(item.chapterNum) === chapterNum)
    if (!chapter) throw new Error(`缁窇鎵句笉鍒扮 ${chapterNum} 绔燻)
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
        reject(new Error(`绛夊緟 CDP 浜嬩欢瓒呮椂锛?{method}`))
      }, timeoutMs)
    })
  }

  close() {
    this.ws?.close()
  }
}

async function launchChrome() {
  if (!existsSync(CHROME_PATH)) throw new Error(`鏈壘鍒?Chrome锛?{CHROME_PATH}`)
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
  log('寮€濮嬫祻瑙堝櫒 UI 楠屾敹')
  const client = await launchChrome()
  try {
    await navigate(client, `${APP_URL}/project/${project.id}`, 'projectLoadMs')
    let text = await evaluate(client, 'document.body.innerText')
    assertCheck(text.includes(project.title), '椤圭洰璇︽儏椤靛彲鎵撳紑', project.title)
    for (const label of ['閫夐闆疯揪', '鍒涗綔绉嶅瓙', '鍒涗綔鍦ｇ粡', '璁惧畾搴?, '绔犺妭绠＄悊', '绾犲亸浠诲姟']) {
      assertCheck(text.includes(label), `椤圭洰璇︽儏椤垫樉绀烘ā鍧楋細${label}`)
    }
    await screenshot(client, 'project-detail')

    await navigate(client, `${APP_URL}/writer/${project.id}/1`, 'writerChapter1LoadMs')
    text = await evaluate(client, 'document.body.innerText')
    assertCheck(text.includes(project.title), '鍐欏瓧鍙板彲鎵撳紑')
    assertCheck(text.includes('鏈珷瀹＄') || text.includes('瀹＄'), '鍐欏瓧鍙板绋垮叆鍙ｅ彲瑙?)
    assertCheck(text.includes('椤圭洰璇︽儏'), '鍐欏瓧鍙拌繑鍥為」鐩鎯呭叆鍙ｅ彲瑙?)
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
    pass('娴忚鍣?UI 鍩虹楠屾敹瀹屾垚', `nodes=${domStats.nodes}, text=${domStats.textLength}`)
  } finally {
    client.close()
  }
}

async function cleanupProject(project) {
  if (!project?.id || KEEP_PROJECT) return
  await request('DELETE', `/projects/${project.id}`)
  report.cleanup = `宸插垹闄ゆ祴璇曢」鐩?${project.id}`
}

function formatChapterWordCountReport() {
  const finalCounts = report.generated.finalChapterWordCounts || []
  const counts = finalCounts.length ? finalCounts : (report.generated.chapterWordCounts || [])
  return counts
    .slice()
    .sort((a, b) => Number(a.chapterNum) - Number(b.chapterNum))
    .map(item => `绗?{item.chapterNum}绔?${item.count}瀛梎)
    .join('锛?)
}

function formatMultiChapterAcceptanceReport() {
  const acceptance = report.generated.multiChapterAcceptance
  if (!acceptance) return ['- 灏氭湭鎵ц']
  if (acceptance.skipped) return [`- 宸茶烦杩囷細${acceptance.reason}`]
  if (acceptance.failed) return [
    `- 缁撴瀯鍖栧け璐ワ細${acceptance.error || ''}`,
    `- 宸插畾绋跨珷鑺傦細${acceptance.finalizedChapters || 0}`,
    `- 寰呯‘璁よ瀹氾細${acceptance.pendingSettingEvents ?? 0}`,
    `- 瀛楁暟瓒婄晫锛?{JSON.stringify(acceptance.wordOutliers || [])}`
  ]
  const issueLines = (acceptance.issues || []).length
    ? acceptance.issues.map(item => `- [${item.severity}/${item.type}] 绗?{(item.chapters || []).join(',')}绔狅細${item.title || item.detail || ''}锛涘缓璁細${item.suggestedAction || ''}`)
    : ['- 鏈彂鐜伴樆濉炵户缁敓鎴愮殑澶氱珷闂']
  return [
    `- 鑼冨洿锛氱 ${acceptance.startChapter}-${acceptance.endChapter} 绔燻,
    `- 鏄惁閫傚悎缁х画锛?{acceptance.safeToContinue ? '鏄? : '鍚?}`,
    `- 鎬昏瘎锛?{acceptance.overall || '鏆傛棤'}`,
    `- 寰呯‘璁よ瀹氾細${acceptance.pendingSettingEvents ?? 0}`,
    `- 缂哄皯璁板繂绔犺妭锛?{(acceptance.missingFactChapters || []).join(',') || '鏃?}`,
    `- 瀛楁暟瓒婄晫锛?{JSON.stringify(acceptance.wordOutliers || [])}`,
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
    '# Novel Creator 鐪熷疄娴佺▼闀跨瘒娴嬭瘯鎶ュ憡',
    '',
    `- 鏃堕棿锛?{report.startedAt} - ${report.finishedAt}`,
    `- 椤圭洰锛?{report.project?.title || ''}`,
    `- 椤圭洰鍦板潃锛?{report.project?.url || ''}`,
    `- 鐩爣瑙勬ā锛?{report.project?.targetWords || 0} 瀛?/ ${report.project?.targetChapters || 0} 绔燻,
    `- 浣跨敤妯″瀷锛?{report.provider?.name || ''} / ${report.provider?.model || ''} / ${report.provider?.apiKey || ''}`,
    `- 妫€鏌ワ細${report.summary.passedChecks}/${report.summary.totalChecks} 閫氳繃`,
    `- 娴忚鍣ㄦ帶鍒跺彴閿欒锛?{report.summary.browserConsoleErrors}`,
    `- 椤圭洰澶勭悊锛?{report.cleanup}`,
    '',
    '## 鐢熸垚涓庢暟鎹噺',
    `- 鐑偣鏁版嵁锛?{report.generated.marketItems}`,
    `- 鏂瑰悜寤鸿锛?{report.generated.directions}`,
    `- 绉嶅瓙锛?{report.generated.seeds}`,
    `- 鍒濆璁惧畾鍊欓€夛細${report.generated.settingEvents}`,
    `- 宸茬‘璁よ瀹氾細${report.generated.acceptedSettings}`,
    `- 绔犺妭楠ㄦ灦锛?{report.generated.chaptersCreated}`,
    `- 宸插畾绋跨珷鑺傦細${report.generated.finalizedChapters}`,
    `- 璁板繂浜嬪疄锛?{report.generated.canonFacts}`,
    `- 绔犺妭璁惧畾鍙樻洿锛?{report.generated.chapterSettingChanges}`,
    `- 绾犲亸浠诲姟锛?{report.generated.correctionTasks}`,
    `- 绔犺妭瀛楁暟锛?{formatChapterWordCountReport()}`,
    `- 瀹＄缁撴瀯鍖栧け璐ワ細${report.generated.auditFailures}`,
    '',
    '## 澶氱珷涓€鑷存€ч獙鏀?,
    ...formatMultiChapterAcceptanceReport(),
    '',
    '## 妫€鏌ラ」',
    ...report.checks.map(item => `- ${item.status === 'pass' ? '[x]' : '[ ]'} ${item.name}${item.detail ? `锛?{item.detail}` : ''}`),
    '',
    '## 涓昏瑙傚療',
    ...(
      report.notes.length
        ? report.notes.map(item => `- ${item}`)
        : ['- 鏈疆閲嶇偣楠岃瘉鐪熷疄娴佺▼鍙窇閫氾紝瀹屾暣 200 涓囧瓧姝ｆ枃娌℃湁涓€娆℃€х敓鎴愶紝閬垮厤涓嶅繀瑕佺殑 API 鎴愭湰銆?]
    ),
    '',
    '## 椤甸潰鑰楁椂',
    ...Object.entries(report.timings).map(([key, value]) => `- ${key}: ${value}ms`),
    '',
    '## 鎴浘',
    ...report.screenshots.map(file => `- ${file}`),
    '',
    '## 娴忚鍣ㄦ帶鍒跺彴閿欒',
    ...(report.browserConsole.length ? report.browserConsole.map(item => `- ${item.type}: ${item.text}`) : ['- 鏃?])
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
            report.generated = normalizeGeneratedReport(previous?.generated)
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
      pass('缁窇宸叉湁娴嬭瘯椤圭洰', project.title)
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
      if (INITIAL_TO_CHAPTER > 2) {
        chapters = await continueWritingFlow(project, provider, INITIAL_TO_CHAPTER)
      }
    }
    const finalizedForAcceptance = await loadFinalizedChapters(project, 1, CONTINUE_TO_CHAPTER || 9999)
    report.generated.finalizedChapters = finalizedForAcceptance.length
    const acceptanceEnd = Math.max(0, ...finalizedForAcceptance.map(item => item.chapterNum))
    if (acceptanceEnd > 0) {
      const acceptanceStart = Math.max(1, acceptanceEnd - 19)
      await runMultiChapterAcceptance(project, provider, acceptanceStart, acceptanceEnd)
    }
    await runGlobalAudit(project, provider, chapters)
    await browserSmoke(project)
    await cleanupProject(project)
  } catch (error) {
    fail('鐪熷疄娴佺▼娴嬭瘯鎵ц澶辫触', error.stack || error.message)
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


