import { chromium, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'


export const VERIFIED_SOURCES = Object.freeze([
  Object.freeze(['qq-reading.male-popular', 'QQ 阅读男生人气榜']),
  Object.freeze(['qimao.public-catalog', '七猫男生更新榜']),
  Object.freeze(['zongheng.monthly', '纵横月票榜']),
  Object.freeze(['jjwxc.quarterly-score', '晋江季度作品积分榜']),
  Object.freeze(['heiyan.diamond', '黑岩钻石榜']),
])


export function parseBaseURL(argv) {
  if (argv.length !== 2 || argv[0] !== '--base-url') {
    throw new Error('Expected one exact loopback base URL')
  }
  let parsed
  try {
    parsed = new URL(argv[1])
  } catch {
    throw new Error('Expected one exact loopback base URL')
  }
  if (
    argv[1] !== parsed.origin
    || parsed.protocol !== 'http:'
    || parsed.hostname !== '127.0.0.1'
    || !parsed.port
    || parsed.username
    || parsed.password
    || parsed.pathname !== '/'
    || parsed.search
    || parsed.hash
  ) throw new Error('Expected one exact loopback base URL')
  return parsed.origin
}


async function readSnapshotEvidence(card) {
  const [snapshotId, capturedAt, entryCount, lastSucceededAt] = await Promise.all([
    card.getAttribute('data-market-latest-snapshot-id'),
    card.getAttribute('data-market-latest-captured-at'),
    card.getAttribute('data-market-latest-entry-count'),
    card.getAttribute('data-market-last-succeeded-at'),
  ])
  return {
    snapshotId: snapshotId || '',
    capturedAt: Number(capturedAt || 0),
    entryCount: Number(entryCount || 0),
    lastSucceededAt: Number(lastSucceededAt || 0),
  }
}


export function freshSnapshotEvidence(before, after) {
  if (
    !after.snapshotId
    || !Number.isSafeInteger(after.capturedAt)
    || after.capturedAt <= 0
    || !Number.isSafeInteger(after.entryCount)
    || after.entryCount < 10
    || !Number.isSafeInteger(after.lastSucceededAt)
    || after.lastSucceededAt <= before.lastSucceededAt
  ) return false
  if (!before.snapshotId) return true
  if (after.snapshotId === before.snapshotId) {
    return (
      after.capturedAt === before.capturedAt
      && after.entryCount === before.entryCount
    )
  }
  return after.capturedAt >= before.capturedAt
}


async function refreshVerifiedSource(page, key, name) {
  const card = page.locator(`[data-market-source-key="${key}"]`)
  await expect(card).toBeVisible()
  const button = card.getByRole('button', { name: `刷新${name}`, exact: true })
  await expect(button).toBeEnabled()
  const before = await readSnapshotEvidence(card)
  await button.click()
  await expect(card).toHaveAttribute('data-market-source-busy', 'true', { timeout: 10_000 })
  await expect(card).toHaveAttribute('data-market-source-busy', 'false', { timeout: 120_000 })
  await expect(button).toBeEnabled()
  await expect(card).toHaveAttribute('data-market-source-status', 'available')
  const after = await readSnapshotEvidence(card)
  if (!freshSnapshotEvidence(before, after)) {
    throw new Error('Market refresh did not publish fresh snapshot evidence')
  }
}


async function startDiscussion(page, { title, message }) {
  const panel = page.locator('.discussion-panel')
  await panel.getByLabel('新讨论标题').fill(title)
  await panel.getByRole('button', { name: '开始讨论', exact: true }).click()
  await expect(panel.getByText(title, { exact: true }).last()).toBeVisible()
  await panel.getByLabel('继续讨论').fill(message)
  await panel.getByRole('button', { name: '发送给 AI', exact: true }).click()
  return panel
}


async function saveDirection(panel) {
  const suggestion = panel.locator('.suggestion:not(.candidate)').last()
  const save = suggestion.getByRole('button', { name: '保存为方向', exact: true })
  await expect(save).toBeVisible({ timeout: 210_000 })
  await save.click()
  await expect(suggestion.getByRole('button', { name: '已保存为方向', exact: true })).toBeVisible()
}


async function saveCandidate(panel) {
  const suggestion = panel.locator('.suggestion.candidate').last()
  const save = suggestion.getByRole('button', { name: '保存为候选种子', exact: true })
  await expect(save).toBeVisible({ timeout: 210_000 })
  const title = (await suggestion.getByRole('heading').textContent())?.trim()
  if (!title) throw new Error('Candidate title is unavailable')
  await save.click()
  await expect(suggestion.getByRole('button', { name: '已保存为候选种子', exact: true })).toBeVisible()
  return title
}


export async function runTopicCenterLive({ baseURL, launch = options => chromium.launch(options) }) {
  const browser = await launch({ headless: true })
  const runId = randomUUID().replaceAll('-', '').slice(0, 12)
  try {
    const page = await browser.newPage()
    await page.goto(`${baseURL}/topics/market`)
    await expect(page.getByText('市场热门与公开证据', { exact: true })).toBeVisible()

    const blankPanel = await startDiscussion(page, {
      title: `无证据长篇方向-${runId}`,
      message: '不引用市场证据，先提出一个适合二百万字以上长篇小说的原创方向。',
    })
    await expect(blankPanel.getByLabel('已附加市场证据')).toHaveCount(0)
    await saveDirection(blankPanel)

    for (const [key, name] of VERIFIED_SOURCES) {
      await refreshVerifiedSource(page, key, name)
    }
    const [evidenceKey, evidenceName] = VERIFIED_SOURCES[0]
    const evidenceCard = page.locator(`[data-market-source-key="${evidenceKey}"]`)
    await evidenceCard.getByRole('button', { name: `查看榜单作品：${evidenceName}`, exact: true }).click()
    const rankedWorks = page.getByRole('list', { name: '榜单作品' })
    await expect(rankedWorks).toBeVisible()
    await expect.poll(
      () => rankedWorks.getByRole('listitem').count(),
      { timeout: 30_000 },
    ).toBeGreaterThanOrEqual(10)
    await page.getByRole('button', { name: '附加到讨论', exact: true }).click()

    const evidencePanel = await startDiscussion(page, {
      title: `市场证据长篇方向-${runId}`,
      message: '基于当前附加的真实市场榜单，给出适合二百万字以上长篇的原创方向和完整候选种子。',
    })
    await expect(evidencePanel.getByLabel('已附加市场证据')).toContainText(evidenceName)
    const candidateTitle = await saveCandidate(evidencePanel)

    await page.getByRole('link', { name: /候选种子库/u }).first().click()
    const candidateList = page.getByLabel('候选种子列表')
    const candidateRecord = candidateList.getByRole('button').filter({ hasText: candidateTitle })
    await expect(candidateRecord).toBeVisible()
    await candidateRecord.click()
    await expect(page.getByText('当前候选 · 版本 1', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '继续讨论', exact: true }).click()
    await expect(page.getByText(`正在继续讨论：${candidateTitle} · 版本 1`, { exact: true })).toBeVisible()
    const continuation = page.locator('.discussion-panel')
    await continuation.getByLabel('继续讨论').fill('深化人物代价、卷级递进和跨卷伏笔，生成候选种子的第二版。')
    await continuation.getByRole('button', { name: '发送给 AI', exact: true }).click()
    const versionTwoTitle = await saveCandidate(continuation)

    await page.getByRole('link', { name: /候选种子库/u }).first().click()
    const versionTwoRecord = page.getByLabel('候选种子列表')
      .getByRole('button').filter({ hasText: versionTwoTitle })
    await expect(versionTwoRecord).toBeVisible()
    await versionTwoRecord.click()
    await expect(page.getByText('当前候选 · 版本 2', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '创建项目', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '从指定版本创建项目' })
    await expect(dialog.getByText('候选版本 2', { exact: true })).toBeVisible()
    await dialog.getByLabel('项目名称').fill(`真实选题项目-${runId}`)
    await dialog.getByRole('button', { name: '创建项目并检查种子', exact: true }).click()
    await expect(page).toHaveURL(/\/projects\/[^/]+\/seeds$/u)
    await expect(page.getByText('待确认', { exact: true }).first()).toBeVisible()
    return 0
  } finally {
    await browser.close()
  }
}


const normalized = value => {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}
if (process.argv[1] && normalized(process.argv[1]) === normalized(fileURLToPath(import.meta.url))) {
  try {
    const baseURL = parseBaseURL(process.argv.slice(2))
    await runTopicCenterLive({ baseURL })
    console.log('topic_center_live=passed')
  } catch {
    console.error('topic center live acceptance failed')
    process.exitCode = 1
  }
}
