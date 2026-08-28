import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const COMPLETE = process.env.BROWSER_COMPLETE_PROJECT_ID
const AWAITING = process.env.BROWSER_AWAITING_PROJECT_ID
const CORRUPT = process.env.BROWSER_CORRUPT_PROJECT_ID
const DOWNLOAD_ROOT = process.env.BROWSER_DOWNLOAD_ROOT
const WIDE_MATRIX = '1440×900 prefers-reduced-motion'
const TITLES = ['泔水醒来，三日织机赌局', '废料改机', '复验定局']
const PROSE = [
  '泔水桶的酸气先醒了过来。林砚睁眼时，三日后的织机赌局已经写在墙上。',
  '他把废铜齿轮磨薄半分，让报废的织机重新咬住经线。众人第一次听见机器平稳的回声。',
  '复验钟响过三遍，新织机没有断线。林砚交出账册，赌局至此有了无可争辩的定局。',
]
const SENTINELS = ['PHASE8A_WORKING_SENTINEL', 'PHASE8A_CANDIDATE_SENTINEL', 'CORRUPT_BODY_MUST_NEVER_ESCAPE']
async function geometry(page) {
  return page.evaluate(() => ({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
}

async function assertWidePoint(page) {
  const size = await geometry(page)
  expect(size.innerWidth).toBeGreaterThan(800)
  expect(size.scrollWidth).toBeLessThanOrEqual(size.clientWidth)
  const targets = page.locator('#manuscript-index-current-action, #manuscript-chapter-1, #manuscript-chapter-1-download, summary:visible')
  const count = await targets.count()
  expect(count).toBeGreaterThan(0)
  for (let index = 0; index < count; index += 1) {
    const box = await targets.nth(index).boundingBox()
    if (box) expect(box.width >= 44 && box.height >= 44).toBeTruthy()
  }
  await page.keyboard.press('Tab')
  const first = page.locator(':focus')
  await expect(first).toBeVisible()
  const firstIdentity = `${await first.getAttribute('id') || ''}:${await first.getAttribute('href') || ''}:${await first.getAttribute('aria-label') || ''}`
  await page.keyboard.press('Tab')
  const second = page.locator(':focus')
  await expect(second).toBeVisible()
  const secondIdentity = `${await second.getAttribute('id') || ''}:${await second.getAttribute('href') || ''}:${await second.getAttribute('aria-label') || ''}`
  expect(secondIdentity).not.toEqual(firstIdentity)
  const motion = await page.evaluate(() => {
    const element = document.querySelector('main, section, body')
    const style = getComputedStyle(element)
    return { animationDuration: style.animationDuration, transitionDuration: style.transitionDuration, scrollBehavior: style.scrollBehavior }
  })
  expect(['0s', '0s, 0s', 'auto'].includes(motion.animationDuration) || motion.animationDuration.startsWith('0s')).toBeTruthy()
  expect(['0s', '0s, 0s', 'auto'].includes(motion.transitionDuration) || motion.transitionDuration.startsWith('0s')).toBeTruthy()
  expect(motion.scrollBehavior).not.toBe('smooth')
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

function assertFinalOnly(text, expectedTitles = TITLES) {
  let prior = -1
  for (const title of expectedTitles) {
    const at = text.indexOf(title)
    expect(at).toBeGreaterThan(prior)
    prior = at
  }
  for (const sentinel of SENTINELS) expect(text).not.toContain(sentinel)
}

async function openDownloadMenu(page) {
  const summary = page.getByText('下载定稿', { exact: true })
  await summary.click()
  await expect(page.getByRole('button', { name: '下载整本定稿 TXT' })).toBeVisible()
}

async function acceptComplete(page) {
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
  await page.getByRole('button', { name: '本章小纲' }).click()
  await expect(page.getByText('在三日织机赌局中取得一次可验证的喘息')).toBeVisible()
  await page.locator('#final-reader-next').click()
  await expect(page.getByRole('heading', { name: `第 2 章 · ${TITLES[1]}` })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: `第 1 章 · ${TITLES[0]}` })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: '本章小纲' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('link', { name: '进入第 4 章写作' })).toBeVisible()
  await page.getByRole('link', { name: '返回作品目录' }).click()

  await page.locator('#manuscript-chapter-1-download').click()
  const chapterText = await saveDownload(page, page.locator('#manuscript-chapter-1-download-txt'), 'complete-chapter-1.txt')
  expect(chapterText).toContain(TITLES[0])
  expect(chapterText).toContain(PROSE[0])
  assertFinalOnly(chapterText, [TITLES[0]])
  await openDownloadMenu(page)
  const volumeText = await saveDownload(page, page.getByRole('button', { name: '下载第1卷 TXT' }), 'complete-volume-1.txt')
  assertFinalOnly(volumeText)
  for (const prose of PROSE) expect(volumeText).toContain(prose)
  const bookText = await saveDownload(page, page.getByRole('button', { name: '下载整本定稿 TXT' }), 'complete-book.txt')
  assertFinalOnly(bookText)

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
  assertFinalOnly(archived)
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
  await expect(page.getByRole('link', { name: '准备第 5 章小纲' })).toBeVisible()
  await page.getByRole('link', { name: '返回作品目录' }).click()
  await expect(page.getByText('旧账浮出水面', { exact: true })).toBeVisible()
  await page.locator('#manuscript-chapter-4').click()
  await expect(page.getByLabel('定稿正文')).toContainText('第四章只用于待作者确认的可见审查')
}

async function expectSafeFailure(page, action) {
  await action()
  await expect(page.getByRole('alert')).toContainText(/暂时无法|下载失败|保护/)
  const visible = await page.locator('body').innerText()
  for (const forbidden of [
    'CORRUPT_BODY_MUST_NEVER_ESCAPE', 'content_hash', 'final_chapters', 'SELECT ', 'UPDATE ',
    'Traceback', 'Exception', 'chapter_outline_hash', '8a000000-0000-4000-8000-',
  ]) expect(visible).not.toContain(forbidden)
}

async function acceptCorrupt(page) {
  await page.goto(`/projects/${CORRUPT}/manuscript`)
  for (const title of TITLES) await expect(page.getByText(title, { exact: true })).toBeVisible()
  await page.locator('#manuscript-chapter-1').click()
  await expect(page.getByLabel('定稿正文')).toContainText(PROSE[0])
  await page.getByRole('link', { name: '返回作品目录' }).click()
  await page.locator('#manuscript-chapter-1-download').click()
  const chapterOne = await saveDownload(page, page.locator('#manuscript-chapter-1-download-txt'), 'corrupt-chapter-1.txt')
  expect(chapterOne).toContain(PROSE[0])
  await page.locator('#manuscript-chapter-3').click()
  await expect(page.getByText('章节定稿暂时不可用')).toBeVisible()
  const visible = await page.locator('body').innerText()
  expect(visible).not.toContain('CORRUPT_BODY_MUST_NEVER_ESCAPE')
  await page.getByRole('link', { name: '返回作品目录' }).click()
  await page.locator('#manuscript-chapter-3-download').click()
  await page.locator('#manuscript-chapter-3-download-txt').click()
  await expect(page.getByRole('alert')).toBeVisible()
  await openDownloadMenu(page)
  await expectSafeFailure(page, () => page.getByRole('button', { name: '下载第1卷 TXT' }).click())
  await expectSafeFailure(page, () => page.getByRole('button', { name: '下载整本定稿 TXT' }).click())
}

test('@phase8a accepts the complete awaiting-author and corrupt manuscript workflows at wide desktop sizes', async ({ page }, testInfo) => {
  expect(WIDE_MATRIX).toContain('1440×900')
  expect(testInfo.project.name).toBe('chromium-wide-100')
  await acceptComplete(page)
  await acceptAwaitingAuthor(page)
  await acceptCorrupt(page)
})
