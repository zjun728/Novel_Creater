import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, rmSync, writeFileSync, openSync, closeSync } from 'node:fs'
import { join, resolve } from 'node:path'

const ROOT = resolve('.')
const API_BASE = 'http://127.0.0.1:8000/api'
const APP_URL = 'http://127.0.0.1:5173'
const CHROME_PATH = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const REPORT_DIR = join(ROOT, 'tmp', 'browser-qa')
const PROFILE_DIR = join(REPORT_DIR, 'chrome-profile')
const KEEP_PROJECT = process.env.KEEP_QA_PROJECT === '1'

mkdirSync(REPORT_DIR, { recursive: true })

const started = []
const report = {
  startedAt: new Date().toISOString(),
  project: null,
  scale: {},
  checks: [],
  timings: {},
  browserConsole: [],
  screenshots: [],
  cleanup: null,
  notes: []
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function pass(name, detail = '') {
  report.checks.push({ name, status: 'pass', detail })
  console.log(`PASS ${name}${detail ? ` - ${detail}` : ''}`)
}

function fail(name, detail = '') {
  report.checks.push({ name, status: 'fail', detail })
  console.error(`FAIL ${name}${detail ? ` - ${detail}` : ''}`)
}

function assertCheck(condition, name, detail = '') {
  if (condition) pass(name, detail)
  else fail(name, detail)
}

async function request(method, path, body, expectedStatuses = [200]) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
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

async function waitForHttp(url, timeoutMs = 30000) {
  const startedAt = Date.now()
  let lastError = ''
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2500) })
      if (res.ok) return true
      lastError = `HTTP ${res.status}`
    } catch (e) {
      lastError = e.message
    }
    await sleep(500)
  }
  throw new Error(`等待服务超时：${url}；最后错误：${lastError}`)
}

async function ensureBackend() {
  try {
    await waitForHttp(`${API_BASE}/health`, 2500)
    pass('后端健康检查', '已有服务可用')
    return
  } catch {
    const out = openSync(join(REPORT_DIR, 'backend.log'), 'a')
    const err = openSync(join(REPORT_DIR, 'backend.err.log'), 'a')
    const proc = spawn('D:/Software/Python/Python312/python.exe', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], {
      cwd: join(ROOT, 'backend'),
      stdio: ['ignore', out, err],
      windowsHide: true
    })
    started.push({ proc, out, err, name: 'backend' })
    await waitForHttp(`${API_BASE}/health`, 45000)
    pass('后端健康检查', '脚本已启动服务')
  }
}

async function ensureFrontend() {
  try {
    await waitForHttp(APP_URL, 2500)
    pass('前端页面检查', '已有服务可用')
    return
  } catch {
    const out = openSync(join(REPORT_DIR, 'frontend.log'), 'a')
    const err = openSync(join(REPORT_DIR, 'frontend.err.log'), 'a')
    const proc = spawn('D:/Software/nodejs/node.exe', ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1'], {
      cwd: join(ROOT, 'frontend'),
      stdio: ['ignore', out, err],
      windowsHide: true
    })
    started.push({ proc, out, err, name: 'frontend' })
    await waitForHttp(APP_URL, 45000)
    pass('前端页面检查', '脚本已启动 Vite')
  }
}

function makeContent(chapterNum, target = 5000) {
  const paragraph = `第${chapterNum}章规模模拟正文。林逐在雨夜里推进线索，人物动机、设定变化和场景行动都保持清楚。这里用于浏览器与数据库压力验收，不调用大模型生成。`
  let content = ''
  while (content.length < target) content += `${paragraph}\n\n`
  return content.slice(0, target)
}

async function setupScaleProject() {
  const title = `QA百万级浏览器验收_${Date.now()}`
  const project = await request('POST', '/projects', {
    title,
    genre: '玄幻',
    description: '自动化浏览器全量验收项目，测试完成后删除。',
    targetWords: 1000000,
    targetChapters: 200
  })
  report.project = { id: project.id, title }

  const seed = await request('POST', `/projects/${project.id}/seeds`, {
    title: '逐愿师 QA 种子',
    genre: '玄幻',
    logline: '逐愿师在愿望与代价之间寻找人的真实选择。',
    protagonist: '林逐，逐愿师传承者，外冷内热。',
    desire: '寻找身世真相，并理解愿望背后的代价。',
    coreConflict: '愿望兑现与人性代价之间的矛盾。',
    openingHook: '雨夜古玩街，一枚愿环自行发热。',
    emotionalPromise: '悬疑推进、人物选择和软过渡纠偏。',
    styleTarget: '克制、具象、少 AI 腔。',
    riskNotes: '避免设定堆叠，避免数值混乱。',
    endingAnchor: '主角最终理解愿望不是捷径，而是承担。'
  })
  await request('PUT', `/projects/${project.id}/seeds/${seed.id}`, { status: 'selected' })

  await request('PUT', `/projects/${project.id}/bible`, {
    premise: '逐愿师通过愿望契约审视人性。',
    targetReader: '喜欢玄幻悬疑和人物选择的读者。',
    styleBible: '场景具体，动机清晰，少用“不是X，是Y”的机械句式。',
    themeBible: '愿望、代价、选择、承担。',
    worldRules: '愿望必须付出代价，设定变化通过章节定稿后确认入库。',
    forbiddenDirections: ['不要机械堆设定', '不要跳过人物动机']
  })

  for (let volumeNum = 1; volumeNum <= 4; volumeNum += 1) {
    const startChapter = (volumeNum - 1) * 50 + 1
    await request('POST', `/projects/${project.id}/volumes`, {
      volumeNum,
      title: `第 ${volumeNum} 卷`,
      startChapter,
      endChapter: startChapter + 49,
      targetWords: 250000,
      coreGoal: `第 ${volumeNum} 卷核心目标`,
      mainConflict: '愿望与代价冲突升级',
      keyCharacters: ['林逐'],
      summary: `第 ${volumeNum} 卷规模测试摘要`,
      status: 'planned'
    })
  }

  const chapterCount = 200
  let totalWords = 0
  const createdAt = Date.now()
  for (let chapterNum = 1; chapterNum <= chapterCount; chapterNum += 1) {
    const chapter = await request('POST', `/projects/${project.id}/chapters`, {
      chapterNum,
      title: `第 ${chapterNum} 章`
    })
    const content = makeContent(chapterNum, 5000)
    totalWords += content.length
    const version = await request('POST', `/projects/${project.id}/chapters/${chapter.id}/versions`, {
      title: `第 ${chapterNum} 章候选`,
      content,
      versionType: 'ai_candidate',
      promptBrief: 'QA 百万级规模模拟'
    })
    await request('POST', `/projects/${project.id}/chapters/${chapter.id}/versions/${version.id}/finalize`, {
      summary: `第 ${chapterNum} 章规模模拟摘要，保留连续性与设定变化。`,
      wordCount: content.length
    })
    if (chapterNum % 50 === 0) console.log(`created finalized chapters: ${chapterNum}/${chapterCount}`)
  }
  report.scale = {
    chapterCount,
    finalizedChapters: chapterCount,
    totalWords,
    setupMs: Date.now() - createdAt
  }
  assertCheck(totalWords >= 1000000, '百万级正文数据准备', `${chapterCount} 章，${totalWords} 字`)

  return project
}

async function expectApiFailure(name, fn, status = 409) {
  try {
    await fn()
    fail(name, `预期 HTTP ${status}，但请求成功`)
  } catch (e) {
    const matched = e.message.includes(`-> ${status}:`)
    assertCheck(matched, name, matched ? `按预期返回 ${status}` : e.message)
  }
}

async function verifyBackendLocks(project) {
  await expectApiFailure('已有正文后禁止新增种子', () => request('POST', `/projects/${project.id}/seeds`, {
    title: '不应写入的新种子',
    genre: '玄幻',
    logline: '锁定测试',
    protagonist: '测试',
    desire: '测试',
    coreConflict: '测试'
  }))
  await expectApiFailure('已有正文后禁止删除圣经', () => request('DELETE', `/projects/${project.id}/bible`))

  const entity = await request('POST', `/projects/${project.id}/settings/entities`, {
    entityType: 'character',
    name: 'QA锁定人物',
    category: '测试',
    summary: '用于验证已有正文后的设定删除锁。'
  })
  await expectApiFailure('已有正文后禁止删除设定实体', () => request('DELETE', `/projects/${project.id}/settings/entities/${entity.id}`))

  const chapters = await request('GET', `/projects/${project.id}/chapters`)
  const first = chapters.find(chapter => Number(chapter.chapterNum) === 1)
  await expectApiFailure('已定稿章节普通更新被锁定', () => request('PUT', `/projects/${project.id}/chapters/${first.id}`, {
    summary: '普通更新不应成功'
  }))
  const updated = await request('PUT', `/projects/${project.id}/chapters/${first.id}/summary`, {
    summary: 'QA 专用摘要写回成功'
  })
  assertCheck(updated.summary === 'QA 专用摘要写回成功', '已定稿章节允许专用摘要写回')
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl
    this.ws = null
    this.nextId = 1
    this.pending = new Map()
    this.listeners = new Map()
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl)
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('CDP WebSocket 连接超时')), 10000)
      this.ws.addEventListener('open', () => {
        clearTimeout(timer)
        resolve()
      }, { once: true })
      this.ws.addEventListener('error', reject, { once: true })
    })
    this.ws.addEventListener('message', event => {
      const message = JSON.parse(event.data)
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id)
        this.pending.delete(message.id)
        if (message.error) reject(new Error(JSON.stringify(message.error)))
        else resolve(message.result)
        return
      }
      const set = this.listeners.get(message.method)
      if (set) for (const listener of [...set]) listener(message.params)
    })
  }

  send(method, params = {}) {
    const id = this.nextId++
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id)
          reject(new Error(`CDP command timeout: ${method}`))
        }
      }, 20000)
    })
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
  if (existsSync(PROFILE_DIR)) rmSync(PROFILE_DIR, { recursive: true, force: true })
  mkdirSync(PROFILE_DIR, { recursive: true })
  const port = 9300 + Math.floor(Math.random() * 500)
  const proc = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${PROFILE_DIR}`,
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    'about:blank'
  ], {
    stdio: ['ignore', 'ignore', 'ignore'],
    windowsHide: true
  })
  started.push({ proc, name: 'chrome' })
  await waitForHttp(`http://127.0.0.1:${port}/json/version`, 15000)
  const tabs = await fetch(`http://127.0.0.1:${port}/json/list`).then(res => res.json())
  const page = tabs.find(item => item.type === 'page') || tabs[0]
  const client = new CdpClient(page.webSocketDebuggerUrl)
  await client.connect()
  await client.send('Page.enable')
  await client.send('Runtime.enable')
  await client.send('Log.enable')
  client.on('Runtime.exceptionThrown', params => {
    report.browserConsole.push({ type: 'exception', text: params?.exceptionDetails?.text || '', url: params?.exceptionDetails?.url || '' })
  })
  client.on('Runtime.consoleAPICalled', params => {
    if (params.type === 'error') {
      report.browserConsole.push({ type: 'console.error', text: (params.args || []).map(arg => arg.value || arg.description || '').join(' ') })
    }
  })
  client.on('Log.entryAdded', params => {
    if (params.entry?.level === 'error') {
      report.browserConsole.push({ type: 'log.error', text: params.entry.text, url: params.entry.url || '' })
    }
  })
  return client
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true
  })
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || 'Runtime.evaluate exception')
  }
  return result.result?.value
}

async function navigate(client, url, name) {
  const startedAt = Date.now()
  const load = client.waitEvent('Page.loadEventFired', 20000).catch(() => null)
  await client.send('Page.navigate', { url })
  await load
  await sleep(800)
  report.timings[name] = Date.now() - startedAt
}

async function bodyText(client) {
  return evaluate(client, 'document.body.innerText')
}

async function clickByText(client, text) {
  return evaluate(client, `(() => {
    const candidates = [...document.querySelectorAll('button,a,[role="button"],.n-tabs-tab,.n-menu-item-content')]
      .filter(el => (el.innerText || '').includes(${JSON.stringify(text)}));
    const el = candidates[0];
    if (!el) return false;
    el.scrollIntoView({ block: 'center', inline: 'center' });
    el.click();
    return true;
  })()`)
}

async function screenshot(client, name) {
  const result = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  const file = join(REPORT_DIR, `${name}.png`)
  writeFileSync(file, Buffer.from(result.data, 'base64'))
  report.screenshots.push(file)
}

async function verifyBrowser(project) {
  const client = await launchChrome()
  try {
    await navigate(client, `${APP_URL}/`, 'homeLoadMs')
    let text = await bodyText(client)
    assertCheck(text.includes('项目库'), '首页项目库可访问')
    assertCheck(text.includes(project.title), '首页能看到 QA 项目')
    await screenshot(client, 'home')

    await navigate(client, `${APP_URL}/settings`, 'settingsLoadMs')
    text = await bodyText(client)
    assertCheck(text.includes('任务模型映射'), '设置页任务模型映射可见')
    assertCheck(text.includes('Provider') || text.includes('模型'), '设置页模型配置区域可见')

    await navigate(client, `${APP_URL}/project/${project.id}`, 'projectLoadMs')
    text = await bodyText(client)
    for (const label of ['选题雷达', '创作种子', '创作圣经', '设定库', '章节管理', '纠偏任务', '人物弧光', '伏笔看板']) {
      assertCheck(text.includes(label), `项目页标签可见：${label}`)
    }
    await screenshot(client, 'project-overview')

    const clickedChapters = await clickByText(client, '章节管理')
    assertCheck(clickedChapters, '可切换到章节管理')
    await sleep(1000)
    text = await bodyText(client)
    assertCheck(text.includes('章节列表') && text.includes('200'), '章节管理显示 200 章规模')
    await screenshot(client, 'project-chapters')

    await navigate(client, `${APP_URL}/writer/${project.id}/1`, 'writerLoadMs')
    text = await bodyText(client)
    assertCheck(text.includes(project.title), '写字台显示项目名')
    assertCheck(text.includes('本章已定稿') || text.includes('正文只读'), '已定稿章节进入只读状态')
    assertCheck(text.includes('项目详情'), '写字台有返回项目详情入口')
    assertCheck(text.includes('本章审稿'), '写字台本章审稿入口可见')
    await screenshot(client, 'writer-finalized')

    const clickedDetail = await clickByText(client, '项目详情')
    assertCheck(clickedDetail, '写字台项目详情按钮可点击')
    await sleep(1000)
    const href = await evaluate(client, 'location.href')
    assertCheck(href.includes(`/project/${project.id}`), '写字台可返回项目详情页')

    const domStats = await evaluate(client, `({
      nodes: document.querySelectorAll('*').length,
      textLength: document.body.innerText.length,
      memory: performance.memory ? {
        usedJSHeapSize: performance.memory.usedJSHeapSize,
        totalJSHeapSize: performance.memory.totalJSHeapSize
      } : null
    })`)
    report.scale.domStats = domStats
  } finally {
    client.close()
  }
}

async function cleanup(project) {
  if (!project?.id || KEEP_PROJECT) {
    report.cleanup = KEEP_PROJECT ? '保留 QA 项目' : '无项目需要清理'
    return
  }
  try {
    await request('DELETE', `/projects/${project.id}`)
    report.cleanup = `已删除 QA 项目 ${project.id}`
    pass('QA 测试项目清理', report.cleanup)
  } catch (e) {
    report.cleanup = `清理失败：${e.message}`
    fail('QA 测试项目清理', report.cleanup)
  }
}

async function main() {
  await ensureBackend()
  await ensureFrontend()

  let project = null
  try {
    project = await setupScaleProject()
    await verifyBackendLocks(project)
    await verifyBrowser(project)
  } finally {
    await cleanup(project)
    for (const item of started.reverse()) {
      try { item.proc?.kill?.() } catch {}
      try { if (item.out) closeSync(item.out) } catch {}
      try { if (item.err) closeSync(item.err) } catch {}
    }
    report.finishedAt = new Date().toISOString()
    const failed = report.checks.filter(item => item.status === 'fail')
    report.summary = {
      totalChecks: report.checks.length,
      failedChecks: failed.length,
      passedChecks: report.checks.length - failed.length,
      browserConsoleErrors: report.browserConsole.length
    }
    const jsonFile = join(REPORT_DIR, 'latest-report.json')
    const mdFile = join(REPORT_DIR, 'latest-report.md')
    writeFileSync(jsonFile, JSON.stringify(report, null, 2), 'utf8')
    writeFileSync(mdFile, [
      '# Novel Creator 浏览器全量 QA',
      '',
      `- 时间：${report.startedAt} - ${report.finishedAt}`,
      `- 项目：${report.project?.title || ''}`,
      `- 规模：${report.scale.chapterCount || 0} 章 / ${report.scale.totalWords || 0} 字`,
      `- 检查：${report.summary.passedChecks}/${report.summary.totalChecks} 通过`,
      `- 浏览器控制台错误：${report.summary.browserConsoleErrors}`,
      `- 清理：${report.cleanup}`,
      '',
      '## 检查项',
      ...report.checks.map(item => `- ${item.status === 'pass' ? '[x]' : '[ ]'} ${item.name}${item.detail ? `：${item.detail}` : ''}`),
      '',
      '## 页面耗时',
      ...Object.entries(report.timings).map(([key, value]) => `- ${key}: ${value}ms`),
      '',
      '## 截图',
      ...report.screenshots.map(file => `- ${file}`),
      '',
      '## 控制台错误',
      ...(report.browserConsole.length ? report.browserConsole.map(item => `- ${item.type}: ${item.text}`) : ['- 无'])
    ].join('\n'), 'utf8')
    console.log(`REPORT_JSON ${jsonFile}`)
    console.log(`REPORT_MD ${mdFile}`)
    if (failed.length) process.exitCode = 1
  }
}

main().catch(error => {
  fail('QA 脚本执行失败', error.stack || error.message)
  throw error
})
