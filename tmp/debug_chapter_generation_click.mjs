import { chromium } from './playwright-run/node_modules/playwright/index.mjs'

const FRONTEND = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000/api'
const pid = process.argv[2] || 'ccbc6ece-bd07-447b-b71b-5f0e5b72d4a7'
const chapterNum = Number(process.argv[3] || 1)
let chapterId = process.argv[4] || ''

function exactButton(page, text) {
  return page.getByRole('button', { name: new RegExp(`^${text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`) })
}

async function api(path) {
  const response = await fetch(`${API}${path}`)
  return response.json()
}

async function visibleTexts(page) {
  return page.locator('.n-message, .n-notification, .n-alert, .app-message-dialog-content')
    .evaluateAll(nodes => nodes.map(node => node.innerText || node.textContent || '').filter(Boolean))
    .catch(() => [])
}

async function clickStartGenerationIfPrompted(page, timeoutMs = 20000) {
  const startButton = exactButton(page, '开始生成本章').last()
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    if (await startButton.isVisible().catch(() => false)) {
      await startButton.click()
      return 'confirmed_prompt'
    }
    const active = await page.getByText(/正在生成本章|AI 正在处理正文/).isVisible().catch(() => false)
    const generateButton = exactButton(page, '生成本章').last()
    const generateDisabled = await generateButton.isVisible().catch(() => false)
      && !await generateButton.isEnabled().catch(() => true)
    if (active || generateDisabled) return 'already_generating'
    await page.waitForTimeout(500)
  }
  return 'no_prompt_detected'
}

const browser = await chromium.launch({
  headless: false,
  executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
})
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
page.on('console', msg => console.log('[console]', msg.type(), msg.text().slice(0, 1200)))
page.on('pageerror', err => console.log('[pageerror]', err.message))
page.on('requestfailed', req => console.log('[requestfailed]', req.method(), req.url(), req.failure()?.errorText))
page.on('response', res => {
  if (res.url().includes('/chat/completions')) console.log('[ai response]', res.status(), res.url())
})

if (!chapterId) {
  const chapters = await api(`/projects/${pid}/chapters`)
  chapterId = chapters.find(chapter => Number(chapter.chapterNum) === chapterNum)?.id || ''
}

await page.goto(`${FRONTEND}/writer/${pid}/${chapterNum}`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(5000)
for (let i = 0; i < 3; i += 1) {
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(500)
}

console.log('buttons', await page.getByRole('button').evaluateAll(buttons =>
  buttons.map(button => ({ text: button.innerText, disabled: button.disabled })).filter(item => item.text)
))
console.log('messages-before', await visibleTexts(page))

await exactButton(page, '生成本章').last().click({ timeout: 60000 })
await page.waitForTimeout(2000)
console.log('buttons-after-generate', await page.getByRole('button').evaluateAll(buttons =>
  buttons.map(button => ({ text: button.innerText, disabled: button.disabled })).filter(item => item.text)
))
console.log('messages-after-generate', await visibleTexts(page))

console.log('start-mode', await clickStartGenerationIfPrompted(page))
for (let i = 0; i < 120; i += 1) {
  await page.waitForTimeout(1000)
  const versions = await api(`/projects/${pid}/chapters/${chapterId}/versions`).catch(() => [])
  const texts = await visibleTexts(page)
  const active = await page.getByText(/正在生成本章|AI 正在处理正文|按小纲生成失败|已按确认小纲生成章节/).allTextContents().catch(() => [])
  if (i % 5 === 0 || versions.length || texts.length || active.length) {
    console.log('tick', i, {
      versions: versions.length,
      lengths: versions.map(version => String(version.content || '').length),
      texts,
      active
    })
  }
  if (versions.length) break
}

await browser.close()
