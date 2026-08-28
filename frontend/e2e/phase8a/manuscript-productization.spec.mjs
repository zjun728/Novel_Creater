import { expect, test } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { parseIterationCount } from './accessibility.mjs'

const COMPLETE = process.env.BROWSER_COMPLETE_PROJECT_ID
const AWAITING = process.env.BROWSER_AWAITING_PROJECT_ID
const CORRUPT = process.env.BROWSER_CORRUPT_PROJECT_ID
const DOWNLOAD_ROOT = process.env.BROWSER_DOWNLOAD_ROOT
const PAGE_EVENT_LEDGER_PATH = process.env.BROWSER_PAGE_EVENT_LEDGER_PATH
const WIDE_MATRIX = '1440×900 prefers-reduced-motion'
const TITLES = ['泔水醒来，三日织机赌局', '废料改机', '复验定局']
const PROSE = [
  '泔水桶的酸气先醒了过来。林砚睁眼时，三日后的织机赌局已经写在墙上。',
  '他把废铜齿轮磨薄半分，让报废的织机重新咬住经线。众人第一次听见机器平稳的回声。',
  '复验钟响过三遍，新织机没有断线。林砚交出账册，赌局至此有了无可争辩的定局。',
]
const SENTINELS = ['PHASE8A_WORKING_SENTINEL', 'PHASE8A_CANDIDATE_SENTINEL', 'CORRUPT_BODY_MUST_NEVER_ESCAPE']
const WRITER_CONFLICT_TEXT = [
  '章节地址与服务端权威不一致',
  '当前地址不是服务端确认的权威章节',
]
const FOCUSABLE_SELECTOR = [
  'a[href]:visible:not([tabindex="-1"])',
  'button:visible:not([disabled]):not([tabindex="-1"])',
  'summary:visible:not([tabindex="-1"])',
  'input:visible:not([disabled]):not([tabindex="-1"])',
  'select:visible:not([disabled]):not([tabindex="-1"])',
  'textarea:visible:not([disabled]):not([tabindex="-1"])',
  '[role="button"]:visible:not([aria-disabled="true"]):not([tabindex="-1"])',
  '[role="link"]:visible:not([aria-disabled="true"]):not([tabindex="-1"])',
].join(', ')

function installPageEventLedger(page) {
  const ledger = { consoleErrors: 0, pageErrors: 0, requestFailures: 0, summaries: [], responses: [] }
  let stage = 'setup'
  const record = (field, summary) => {
    ledger[field] += 1
    ledger.summaries.push(summary)
  }
  page.on('console', message => {
    if (message.type() !== 'error') return
    const status = message.text().match(/status (?:code )?of (\d{3})|status (\d{3})/iu)
    let source = 'other'
    try {
      const pathname = new URL(message.location().url).pathname
      if (pathname.includes('/novel-download')) {
        const scope = new URL(message.location().url).searchParams.get('scope')
        source = `novel-download-${['chapter', 'volume', 'book'].includes(scope) ? scope : 'unknown'}`
      }
      else if (pathname.includes('/manuscript/chapters/')) source = 'manuscript-chapter'
      else if (pathname.includes('/manuscript')) source = 'manuscript-index'
      else if (pathname.includes('/lifecycle')) source = 'lifecycle'
      else if (pathname.startsWith('/api/')) source = 'other-api'
      else if (pathname.startsWith('/src/') || pathname.startsWith('/assets/')) source = 'frontend-asset'
    } catch {}
    record('consoleErrors', status
      ? { kind: 'console-error', category: 'resource-status', source, status: Number(status[1] || status[2]) }
      : { kind: 'console-error', category: 'other', source, status: null })
  })
  page.on('pageerror', () => record('pageErrors', { kind: 'page-error' }))
  page.on('requestfailed', () => record('requestFailures', { kind: 'request-failed' }))
  page.on('response', response => {
    if (response.status() < 400) return
    let route = 'other'
    try {
      const parsed = new URL(response.url())
      if (parsed.pathname.includes('/manuscript/chapters/')) route = 'manuscript-chapter'
      else if (parsed.pathname.includes('/novel-download')) route = `novel-download-${parsed.searchParams.get('scope') || 'unknown'}`
      else if (parsed.pathname.startsWith('/api/')) route = 'other-api'
    } catch {}
    ledger.responses.push({ method: response.request().method(), route, stage, status: response.status() })
  })
  return {
    setStage(value) { stage = value },
    assertPageEventsZero(stage = 'workflow') {
      if (ledger.consoleErrors || ledger.pageErrors || ledger.requestFailures || ledger.responses.length) {
        const consoleSummary = ledger.summaries.find(item => item.kind === 'console-error')
        const category = consoleSummary
          ? `${consoleSummary.source}-${consoleSummary.category}-${consoleSummary.status || 0}` : 'none-other-0'
        const response = ledger.responses[0]
        const responseMarker = response
          ? `${response.stage}-${response.method.toLowerCase()}-${response.route}-${response.status}` : 'none-get-other-0'
        throw new Error(`phase8a-page-events-${stage}-console-${ledger.consoleErrors}-page-${ledger.pageErrors}-request-${ledger.requestFailures}-first-${category}-response-${responseMarker}`)
      }
      expect(ledger.pageErrors).toBe(0)
      expect(ledger.requestFailures).toBe(0)
    },
    assertExpectedCorruptPageEvents() {
      const routes = ['manuscript-chapter', 'novel-download-chapter', 'novel-download-volume', 'novel-download-book']
      expect(ledger.responses).toEqual(routes.map(route => ({
        method: 'GET', route, stage: 'corrupt', status: 500,
      })))
      expect(ledger.summaries).toEqual(routes.map(source => ({
        kind: 'console-error', category: 'resource-status', source, status: 500,
      })))
      expect(ledger.consoleErrors).toBe(4)
      expect(ledger.pageErrors).toBe(0)
      expect(ledger.requestFailures).toBe(0)
    },
    write() {
      writeFileSync(PAGE_EVENT_LEDGER_PATH, JSON.stringify(ledger), { encoding: 'utf8', flag: 'wx' })
    },
  }
}

async function settleAndAssertPageEvents(page, pageEvents, stage) {
  await page.waitForTimeout(0)
  pageEvents.assertPageEventsZero(stage)
}
async function geometry(page) {
  return page.evaluate(() => ({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
}

async function assertKeyboardDomOrder(page) {
  const controls = page.locator(FOCUSABLE_SELECTOR)
  const count = await controls.count()
  expect(count).toBeGreaterThan(1)
  const sequence = []
  for (let step = 0; step < count + 2 && sequence.length < count; step += 1) {
    await page.keyboard.press('Tab')
    let focused = -1
    for (let index = 0; index < count; index += 1) {
      if (await controls.nth(index).evaluate(element => element === document.activeElement)) {
        focused = index
        break
      }
    }
    if (focused >= 0) sequence.push(focused)
  }
  expect(sequence).toHaveLength(count)
  expect(new Set(sequence).size).toBe(count)
  for (let index = 1; index < count; index += 1) {
    expect(sequence[index]).toBe((sequence[0] + index) % count)
  }
}

async function assertReducedMotion(page) {
  const infiniteIteration = parseIterationCount('infinite')
  const motion = await page.locator('.product-app-shell, .product-app-shell *').evaluateAll((elements, infinite) => {
    const seconds = value => {
      const parsed = value.split(',').map(part => {
        const item = part.trim()
        return Number.parseFloat(item) * (item.endsWith('ms') ? 0.001 : 1)
      }).filter(Number.isFinite)
      return parsed.length ? Math.max(...parsed) : 0
    }
    let maximumAnimation = 0
    let maximumTransition = 0
    let transitionOwner = 'none'
    let maximumIterations = 0
    let smoothScrolls = 0
    for (const element of elements) {
      for (const [pseudo, style] of [['element', getComputedStyle(element)], ['before', getComputedStyle(element, '::before')], ['after', getComputedStyle(element, '::after')]]) {
        maximumAnimation = Math.max(maximumAnimation, seconds(style.animationDuration))
        const transition = seconds(style.transitionDuration)
        if (transition > maximumTransition) {
          maximumTransition = transition
          transitionOwner = `${element.tagName.toLowerCase()}-${String(element.className).split(/\s+/u)[0] || 'plain'}-${pseudo}-${String(style.content).replaceAll(/[^a-z]/giu, '') || 'empty'}`
        }
        maximumIterations = Math.max(maximumIterations, ...style.animationIterationCount.split(',').map(value => (
          value.trim().toLowerCase() === 'infinite' ? infinite : Number.parseFloat(value) || 0
        )))
        if (style.scrollBehavior === 'smooth') smoothScrolls += 1
      }
    }
    return { maximumAnimation, maximumTransition, maximumIterations, smoothScrolls, transitionOwner }
  }, infiniteIteration)
  expect(motion.maximumAnimation).toBeLessThanOrEqual(0.001)
  if (motion.maximumTransition > 0.001) throw new Error(`phase8a-motion-transition-${Math.round(motion.maximumTransition * 1_000_000)}-${motion.transitionOwner}`)
  expect(motion.maximumTransition).toBeLessThanOrEqual(0.001)
  expect(motion.maximumIterations).toBeLessThanOrEqual(1)
  expect(motion.smoothScrolls).toBe(0)
}

async function assertWidePoint(page) {
  const size = await geometry(page)
  expect(size.innerWidth).toBeGreaterThan(800)
  expect(size.scrollWidth).toBeLessThanOrEqual(size.clientWidth)
  const targets = page.locator('main button:visible, main summary:visible, main [role="button"]:visible, main [class*="__action"]:visible, main [id^="manuscript-chapter-"]:visible')
  const count = await targets.count()
  expect(count).toBeGreaterThan(0)
  for (let index = 0; index < count; index += 1) {
    const box = await targets.nth(index).boundingBox()
    expect(box).not.toBeNull()
    expect(box.width >= 44 && box.height >= 44).toBeTruthy()
  }
  await assertKeyboardDomOrder(page)
  await assertReducedMotion(page)
  return size
}

async function saveDownload(page, control, filename) {
  const event = page.waitForEvent('download')
  await control.click()
  const download = await event
  const target = path.join(DOWNLOAD_ROOT, filename)
  await download.saveAs(target)
  return readFileSync(target, 'utf8')
}

function assertFinalSequence(text, chapters) {
  let prior = -1
  for (const chapter of chapters) {
    const titleAt = text.indexOf(TITLES[chapter])
    const proseAt = text.indexOf(PROSE[chapter])
    expect(titleAt).toBeGreaterThan(prior)
    expect(proseAt).toBeGreaterThan(titleAt)
    prior = proseAt
  }
  for (const sentinel of SENTINELS) expect(text).not.toContain(sentinel)
}

async function openDownloadMenu(page) {
  const summary = page.getByText('下载定稿', { exact: true })
  await summary.click()
  await expect(page.getByRole('button', { name: '下载整本定稿 TXT' })).toBeVisible()
}

async function assertNoWriterConflict(page) {
  for (const message of WRITER_CONFLICT_TEXT) await expect(page.locator('body')).not.toContainText(message)
}

async function acceptComplete(page, pageEvents) {
  await page.goto(`/projects/${COMPLETE}/overview`)
  await expect(page.getByRole('heading', { name: '织机赌局 · 完整稿件' })).toBeVisible()
  await expect(page.getByRole('link', { name: '作品稿件 · 已定稿 3 章' })).toBeVisible()
  await page.getByRole('link', { name: '作品稿件', exact: true }).click()
  await expect(page.getByRole('heading', { name: '作品稿件' })).toBeVisible()
  await expect(page.getByText('第1卷 · 第一卷')).toBeVisible()
  for (const title of TITLES) await expect(page.getByText(title, { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '进入第 4 章写作' })).toBeVisible()
  await assertWidePoint(page)

  await page.locator('#manuscript-chapter-1').click()
  await expect(page.getByRole('heading', { name: `第 1 章 · ${TITLES[0]}` })).toBeVisible()
  await expect(page.getByLabel('定稿正文')).toContainText(PROSE[0])
  await assertNoWriterConflict(page)
  await page.getByRole('button', { name: '本章小纲' }).click()
  await expect(page.getByText('在三日织机赌局中取得一次可验证的喘息')).toBeVisible()
  await assertNoWriterConflict(page)
  await page.locator('#final-reader-next').click()
  await expect(page.getByRole('heading', { name: `第 2 章 · ${TITLES[1]}` })).toBeVisible()
  await assertNoWriterConflict(page)
  await page.goBack()
  await expect(page.getByRole('heading', { name: `第 1 章 · ${TITLES[0]}` })).toBeVisible()
  await assertNoWriterConflict(page)
  await page.reload()
  await expect(page.getByRole('button', { name: '本章小纲' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('link', { name: '进入第 4 章写作' })).toBeVisible()
  await assertNoWriterConflict(page)
  await page.getByRole('link', { name: '返回作品目录' }).click()
  await settleAndAssertPageEvents(page, pageEvents, 'complete-reader')

  await page.locator('#manuscript-chapter-1-download').click()
  const chapterText = await saveDownload(page, page.locator('#manuscript-chapter-1-download-txt'), 'complete-chapter-1.txt')
  expect(chapterText).toContain(TITLES[0])
  expect(chapterText).toContain(PROSE[0])
  assertFinalSequence(chapterText, [0])
  await openDownloadMenu(page)
  const volumeText = await saveDownload(page, page.getByRole('button', { name: '下载第1卷 TXT' }), 'complete-volume-1.txt')
  assertFinalSequence(volumeText, [0, 1, 2])
  const bookText = await saveDownload(page, page.getByRole('button', { name: '下载整本定稿 TXT' }), 'complete-book.txt')
  assertFinalSequence(bookText, [0, 1, 2])
  await settleAndAssertPageEvents(page, pageEvents, 'complete-downloads')

  await page.getByRole('link', { name: 'Novel Creator 项目库', exact: true }).click()
  const card = page.locator('.project-card').filter({ hasText: '织机赌局 · 完整稿件' })
  await card.getByText('更多', { exact: true }).click()
  await card.getByRole('button', { name: '归档' }).click()
  await expect(page.getByText('项目已归档', { exact: true }).last()).toBeVisible()
  await page.goBack()
  await expect(page.getByText('项目已归档，稿件仅供阅读与下载。')).toBeVisible()
  await expect(page.locator('#manuscript-index-current-action')).toHaveCount(0)
  await expect(page.getByText('AI 生成工作稿')).toHaveCount(0)
  await page.locator('#manuscript-chapter-1').click()
  await expect(page.getByLabel('定稿正文')).toContainText(PROSE[0])
  await page.getByRole('button', { name: '本章小纲' }).click()
  await expect(page.getByText(PINNED_GOAL)).toBeVisible()
  await expect(page.locator('#final-reader-current-action')).toHaveCount(0)
  await page.getByRole('link', { name: '返回作品目录' }).click()
  await openDownloadMenu(page)
  const archived = await saveDownload(page, page.getByRole('button', { name: '下载整本定稿 TXT' }), 'archived-complete-book.txt')
  assertFinalSequence(archived, [0, 1, 2])
  await settleAndAssertPageEvents(page, pageEvents, 'complete-archive')
}

const PINNED_GOAL = '在三日织机赌局中取得一次可验证的喘息'

async function acceptAwaitingAuthor(page) {
  await page.goto(`/projects/${AWAITING}/overview`)
  await page.getByRole('link', { name: '作品稿件 · 已定稿 3 章' }).click()
  await expect(page.getByRole('link', { name: '继续创作第 4 章' })).toBeVisible()
  await page.getByRole('link', { name: '继续创作第 4 章' }).click()
  await expect(page.getByRole('heading', { name: '章节工作台' })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认以上变更' })).toBeVisible()
  await page.getByRole('button', { name: '确认以上变更' }).click()
  await expect(page.getByRole('button', { name: '定稿本章' })).toBeVisible()
  await page.getByRole('button', { name: '定稿本章' }).click()
  await expect(page.getByText('本章已定稿')).toBeVisible()
  await expect(page.getByRole('link', { name: /准备第 5 章小纲/ })).toBeVisible()
  await page.getByRole('link', { name: '查看本章定稿' }).click()
  await expect(page.getByRole('heading', { name: '第 4 章 · 旧账浮出水面' })).toBeVisible()
  const mappedChapterFiveAction = page.getByRole('link', { name: '准备第 5 章小纲' })
  await expect(mappedChapterFiveAction).toBeVisible()
  await mappedChapterFiveAction.click()
  await expect(page).toHaveURL(new RegExp(`/projects/${AWAITING}/planning/story-blocks$`, 'u'))
  await expect(page.getByRole('heading', { name: '故事规划工作台' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '第 5 章小纲' })).toBeVisible()
  await page.getByRole('link', { name: '作品稿件', exact: true }).click()
  await expect(page.getByText('旧账浮出水面', { exact: true })).toBeVisible()
  await page.locator('#manuscript-chapter-4').click()
  await expect(page.getByLabel('定稿正文')).toContainText('第四章只用于待作者确认的可见审查')
}

async function expectSafeFailure(page, action) {
  await action()
  await expect(page.locator('body')).toContainText(/暂时无法|下载失败|保护/)
  const visible = await page.locator('body').innerText()
  for (const forbidden of [
    'CORRUPT_BODY_MUST_NEVER_ESCAPE', PROSE[2], 'content_hash', 'contentHash', 'final_chapters',
    'payload_json', 'SELECT ', 'UPDATE ', 'Traceback', 'Exception', 'Error:',
    'chapter_outline_hash', '/api/', '$.',
  ]) expect(visible).not.toContain(forbidden)
  expect(visible).not.toMatch(/\b[0-9a-f]{64}\b/iu)
  expect(visible).not.toMatch(/\b[0-9a-f]{8}-[0-9a-f-]{27,}\b/iu)
}

async function acceptCorrupt(page) {
  await page.goto(`/projects/${CORRUPT}/manuscript`)
  for (const title of TITLES) await expect(page.getByText(title, { exact: true })).toBeVisible()
  await page.locator('#manuscript-chapter-1').click()
  await expect(page.getByLabel('定稿正文')).toContainText(PROSE[0])
  await page.getByRole('link', { name: '返回作品目录' }).click()
  await page.locator('#manuscript-chapter-1-download').click()
  const chapterOne = await saveDownload(page, page.locator('#manuscript-chapter-1-download-txt'), 'corrupt-chapter-1.txt')
  assertFinalSequence(chapterOne, [0])
  await expectSafeFailure(page, () => page.locator('#manuscript-chapter-3').click())
  await page.getByRole('link', { name: '作品稿件', exact: true }).click()
  await page.locator('#manuscript-chapter-3-download').click()
  await expectSafeFailure(page, () => page.locator('#manuscript-chapter-3-download-txt').click())
  await openDownloadMenu(page)
  await expectSafeFailure(page, () => page.getByRole('button', { name: '下载第1卷 TXT' }).click())
  await expectSafeFailure(page, () => page.getByRole('button', { name: '下载整本定稿 TXT' }).click())
}

test('@phase8a accepts the complete awaiting-author and corrupt manuscript workflows at wide desktop sizes', async ({ page }, testInfo) => {
  expect(WIDE_MATRIX).toContain('1440×900')
  expect(testInfo.project.name).toBe('chromium-wide-100')
  const pageEvents = installPageEventLedger(page)
  pageEvents.setStage('complete')
  await acceptComplete(page, pageEvents)
  pageEvents.assertPageEventsZero()
  pageEvents.setStage('awaiting')
  await acceptAwaitingAuthor(page)
  pageEvents.assertPageEventsZero()
  pageEvents.setStage('corrupt')
  await acceptCorrupt(page)
  await page.waitForTimeout(0)
  pageEvents.assertExpectedCorruptPageEvents()
  pageEvents.write()
})
