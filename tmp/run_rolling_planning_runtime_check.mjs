import { spawn } from 'node:child_process'
import { appendFileSync, closeSync, mkdirSync, openSync } from 'node:fs'
import { join, resolve } from 'node:path'

const ROOT = resolve('.')
const API_BASE = 'http://127.0.0.1:8000/api'
const REPORT_DIR = join(ROOT, 'tmp', 'realistic-flow-qa')
const PROJECT_ID = process.env.ROLLING_PLAN_PROJECT_ID || '167da423-1c06-4ab2-a8d2-4008d0b7c2c7'

mkdirSync(REPORT_DIR, { recursive: true })

const started = []

function log(message) {
  const line = `[${new Date().toISOString().replace('T', ' ').slice(0, 19)}] ${message}`
  console.log(line)
  appendFileSync(join(REPORT_DIR, 'rolling-planning-runtime.log'), `${line}\n`, 'utf8')
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
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  throw new Error(`等待服务超时：${url}；最后错误：${lastError}`)
}

async function ensureBackend() {
  try {
    await waitForHttp(`${API_BASE}/health`, 2500)
    log('后端服务已可用')
    return
  } catch {
    log('后端未启动，启动 uvicorn')
  }
  const out = openSync(join(REPORT_DIR, 'rolling-backend.log'), 'a')
  const err = openSync(join(REPORT_DIR, 'rolling-backend.err.log'), 'a')
  const proc = spawn('D:/Software/Python/Python312/python.exe', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], {
    cwd: join(ROOT, 'backend'),
    stdio: ['ignore', out, err],
    windowsHide: true
  })
  started.push({ proc, out, err })
  await waitForHttp(`${API_BASE}/health`, 45000)
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

function maskKey(key = '') {
  return key ? `${String(key).slice(0, 6)}...${String(key).slice(-4)}` : '未配置'
}

async function getPreferredProvider() {
  const providers = await request('GET', '/providers')
  const preferred = providers.find(item => item.name === '联通云-DeepSeek-V4-Flash')
    || providers.find(item => /DeepSeek-V4-Flash/i.test(item.model || ''))
    || providers[0]
  if (!preferred) throw new Error('没有可用 Provider')
  log(`模型：${preferred.name} / ${preferred.model} / ${maskKey(preferred.apiKey)}`)
  return preferred
}

async function chatJson(provider, messages) {
  const res = await fetch(`${provider.baseURL.replace(/\/$/, '')}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${provider.apiKey}`
    },
    body: JSON.stringify({
      model: provider.model,
      messages,
      temperature: 0.28,
      top_p: provider.topP || 0.9,
      max_tokens: 3000,
      response_format: provider.supportsJSON === false ? undefined : { type: 'json_object' }
    }),
    signal: AbortSignal.timeout(240000)
  })
  const text = await res.text()
  if (!res.ok) throw new Error(`LLM ${res.status}: ${text.slice(0, 500)}`)
  const content = JSON.parse(text)?.choices?.[0]?.message?.content || ''
  try {
    return JSON.parse(content)
  } catch {
    const start = content.indexOf('{')
    const end = content.lastIndexOf('}')
    if (start >= 0 && end > start) return JSON.parse(content.slice(start, end + 1))
    throw new Error(`没有解析到规划 JSON：${content.slice(0, 300)}`)
  }
}

function normalizeOutline(data = {}) {
  return {
    farVision: data.farVision && typeof data.farVision === 'object' ? data.farVision : {},
    currentVolume: data.currentVolume && typeof data.currentVolume === 'object' ? data.currentVolume : {},
    nearChapters: Array.isArray(data.nearChapters) ? data.nearChapters.slice(0, 5) : []
  }
}

function isFinalizedChapter(item = {}) {
  return Boolean(item.finalVersionId || item.final_version_id || item.status === 'final')
}

async function main() {
  await ensureBackend()
  const provider = await getPreferredProvider()
  const project = await request('GET', `/projects/${PROJECT_ID}`)
  const bible = await request('GET', `/projects/${PROJECT_ID}/bible`)
  const chapters = await request('GET', `/projects/${PROJECT_ID}/chapters`)
  const finalizedChapters = chapters.filter(isFinalizedChapter)
  const maxFinalizedChapterNum = finalizedChapters.reduce((max, item) => {
    const chapterNum = Number(item.chapterNum || item.chapter_num || 0)
    return Number.isFinite(chapterNum) ? Math.max(max, chapterNum) : max
  }, 0)
  const nextChapterNum = Math.max(1, maxFinalizedChapterNum + 1)
  const finalized = finalizedChapters
    .sort((a, b) => Number(a.chapterNum || a.chapter_num) - Number(b.chapterNum || b.chapter_num))
    .slice(-8)
  const context = finalized.map(item => `第 ${item.chapterNum || item.chapter_num} 章：${item.summary || '无摘要'}`).join('\n')
  const progressLock = [
    `当前待写章节：第 ${nextChapterNum} 章。`,
    `进度锁：前 ${maxFinalizedChapterNum} 章已经定稿，不得回退、重排、重写或撤销。`,
    'nearChapters 的 chapterNum 必须从当前待写章节开始递增，只规划未来 3-5 章。',
    '不能重新规划已经发生过的“首次”事件，例如首次获得系统、首次加点、首次突破、首次进入宗门、首次发现核心秘密等；已经发生的事件只能承接后果。',
    '如当前卷规划或长线蓝图与已写正文冲突，必须以已写正文、设定库和已确认事实为准。'
  ].join('\n')
  const prompt = [
    `项目：${project.title}`,
    `目标：${project.targetWords || project.target_words} 字 / ${project.targetChapters || project.target_chapters} 章`,
    `当前已定稿：${finalizedChapters.length} 章`,
    progressLock,
    `圣经定位：${bible?.premise || ''}`,
    `近期章节摘要：\n${context}`,
    '请生成滚动规划 JSON，结构必须为：',
    `{"farVision":{"theme":"","futureVolumes":[],"risks":[],"updateTrigger":""},"currentVolume":{"title":"","goal":"","mainConflict":"","mustResolve":[],"mustAvoid":[]},"nearChapters":[{"chapterNum":${nextChapterNum},"title":"","goal":"","conflict":"","turningPoint":"","emotionalBeat":"","handoff":""}]}`,
    'nearChapters 必须是未来 3-5 章；farVision 只写粗粒度长线蓝图，不细化到每章。只输出 JSON。'
  ].join('\n\n')

  const generated = normalizeOutline(await chatJson(provider, [
    { role: 'system', content: '你是长篇小说滚动规划编辑。只输出合法 JSON。' },
    { role: 'user', content: prompt }
  ]))

  if (!generated.farVision?.theme) throw new Error('farVision.theme 缺失')
  if (!Array.isArray(generated.nearChapters) || generated.nearChapters.length < 3 || generated.nearChapters.length > 5) {
    throw new Error(`nearChapters 数量异常：${generated.nearChapters?.length || 0}`)
  }
  const regressedChapterNums = generated.nearChapters
    .map(item => Number(item.chapterNum || item.chapter_num || 0))
    .filter(chapterNum => Number.isFinite(chapterNum) && chapterNum < nextChapterNum)
  if (regressedChapterNums.length) {
    throw new Error(`nearChapters 回退到已写章节：${regressedChapterNums.join(', ')}；当前待写章节应从 ${nextChapterNum} 开始`)
  }

  const saved = await request('PUT', `/projects/${PROJECT_ID}/outline`, generated)
  const loaded = await request('GET', `/projects/${PROJECT_ID}/outline`)
  if (!loaded?.farVision?.theme || !Array.isArray(loaded.nearChapters) || loaded.nearChapters.length < 3) {
    throw new Error('规划保存后读回失败')
  }
  log(`滚动规划保存并读回：near=${loaded.nearChapters.length}，theme=${loaded.farVision.theme}`)
  console.log(JSON.stringify({ projectId: PROJECT_ID, outline: saved }, null, 2))
}

main()
  .catch(error => {
    log(`FAIL ${error.stack || error.message}`)
    process.exitCode = 1
  })
  .finally(() => {
    for (const item of started) {
      try { item.proc.kill() } catch {}
      try { closeSync(item.out) } catch {}
      try { closeSync(item.err) } catch {}
    }
  })
