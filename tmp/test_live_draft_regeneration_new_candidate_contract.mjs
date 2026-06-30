import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import {
  assessChapterWordCount,
  buildChapterWordTarget
} from '../frontend/src/utils/chapterWordTarget.js'

const source = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const waitMatch = source.match(/async function waitForGeneratedChapterVersion[\s\S]*?\n}\n\nasync function waitForStoryBlockReviewSaved/)
const ensureMatch = source.match(/async function ensureDraftAboveHardMinOrRegenerate[\s\S]*?\n}\n\nasync function runChapter/)

assert.ok(waitMatch, '必须存在 waitForGeneratedChapterVersion')
assert.ok(ensureMatch, '必须存在 ensureDraftAboveHardMinOrRegenerate')

const waitBody = waitMatch[0]
const ensureBody = ensureMatch[0]

const helperMatch = source.match(/function contentHash[\s\S]*?\n}\n\nfunction visibleDraftErrorMessages/)
assert.ok(helperMatch, '必须存在候选版本 fingerprint helper')
const helperSource = helperMatch[0].replace(/\nfunction visibleDraftErrorMessages[\s\S]*$/, '')
const sandbox = { createHash }
vm.runInNewContext(`${helperSource}
globalThis.__helpers = {
  candidateVersionFingerprints,
  hasNewGeneratedVersionCandidate,
  latestCandidateVersion
}`, sandbox)
const { candidateVersionFingerprints, hasNewGeneratedVersionCandidate, latestCandidateVersion } = sandbox.__helpers

const oldVersions = [{
  id: 'old-1',
  content: '旧'.repeat(3795),
  createdAt: '2026-06-25T00:00:00.000Z',
  updatedAt: '2026-06-25T00:00:00.000Z'
}]
const newVersion = {
  id: 'new-1',
  content: '新'.repeat(4300),
  createdAt: '2026-06-25T00:02:00.000Z',
  updatedAt: '2026-06-25T00:02:00.000Z'
}
const stillShortNewVersion = {
  id: 'new-short-1',
  content: '短'.repeat(3800),
  createdAt: '2026-06-25T00:02:00.000Z',
  updatedAt: '2026-06-25T00:02:00.000Z'
}
const oldFingerprints = candidateVersionFingerprints(oldVersions)
const liveWordTarget = buildChapterWordTarget({ targetWords: 2400000, targetChapters: 480 })
assert.equal(liveWordTarget.hardMin, 4000, '240w/480章 hardMin 必须保持 4000')
assert.notEqual(
  assessChapterWordCount(newVersion.content, liveWordTarget).level,
  'hard_under',
  '低字数重生后新版本 4300 字应越过硬下限，允许继续审稿/定稿'
)
assert.equal(
  assessChapterWordCount(stillShortNewVersion.content, liveWordTarget).level,
  'hard_under',
  '低字数重生后新版本 3800 字才应继续报告 chapter_below_hard_min'
)
assert.equal(
  hasNewGeneratedVersionCandidate(oldVersions, {
    expectNewVersion: true,
    minVersionCountAfter: 2,
    previousVersionIds: oldFingerprints.map(item => item.id),
    previousContentHashes: oldFingerprints.map(item => item.contentHash),
    previousVersionFingerprints: oldFingerprints,
    draftGenerationStartedAt: '2026-06-25T00:01:00.000Z'
  }).matched,
  false,
  '已有 1 个旧候选时 expectNewVersion=true 不得立即返回'
)
assert.equal(
  hasNewGeneratedVersionCandidate([...oldVersions, newVersion], {
    expectNewVersion: true,
    minVersionCountAfter: 2,
    previousVersionIds: oldFingerprints.map(item => item.id),
    previousContentHashes: oldFingerprints.map(item => item.contentHash),
    previousVersionFingerprints: oldFingerprints,
    draftGenerationStartedAt: '2026-06-25T00:01:00.000Z'
  }).matched,
  true,
  '新 versionId/hash 出现时应视为真正重生候选'
)
assert.equal(
  hasNewGeneratedVersionCandidate([newVersion, ...oldVersions], {
    expectNewVersion: true,
    minVersionCountAfter: 2,
    previousVersionIds: oldFingerprints.map(item => item.id),
    previousContentHashes: oldFingerprints.map(item => item.contentHash),
    previousVersionFingerprints: oldFingerprints,
    draftGenerationStartedAt: '2026-06-25T00:01:00.000Z'
  }).candidate.id,
  'new-1',
  'API 返回最新候选在前时，也必须把新候选写入诊断'
)
assert.equal(
  hasNewGeneratedVersionCandidate([...oldVersions, newVersion], {
    expectNewVersion: true,
    minVersionCountAfter: 2,
    previousVersionIds: oldFingerprints.map(item => item.id),
    previousContentHashes: oldFingerprints.map(item => item.contentHash),
    previousVersionFingerprints: oldFingerprints,
    draftGenerationStartedAt: '2026-06-25T00:01:00.000Z'
  }).candidate.id,
  'new-1',
  'API 返回最新候选在后时，也必须把新候选写入诊断'
)
assert.equal(
  latestCandidateVersion([newVersion, ...oldVersions]).id,
  'new-1',
  '章节草稿统计必须按时间选最新候选，而不是数组末尾旧候选'
)

for (const field of [
  'expectNewVersion',
  'minVersionCountAfter',
  'previousVersionIds',
  'previousContentHashes',
  'previousVersionFingerprints'
]) {
  assert.match(waitBody, new RegExp(field), `waitForGeneratedChapterVersion 必须支持 ${field}`)
}

assert.doesNotMatch(
  waitBody,
  /if\s*\(\s*versions\?\.[\s\S]{0,120}some\(version => String\(version\.content \|\| ''\)\.length > 500\)\s*\)\s*\{\s*return versions\s*\}/,
  'expectNewVersion=true 时不能因为旧候选 content>500 就立即返回'
)
assert.doesNotMatch(
  source,
  /candidateContent\s*=\s*String\(candidateVersions\.at\(-1\)/,
  '草稿统计不能用 candidateVersions.at(-1) 读取旧候选'
)
assert.match(
  source,
  /wordCountPolicyBasis:\s*candidateContent \? 'latest_candidate_content' : 'chapter\.wordCount'/,
  '候选正文存在时，字数硬门诊断必须以最新候选内容为准'
)
assert.match(
  waitBody,
  /hasNewGeneratedVersionCandidate/,
  '等待函数必须用候选新鲜度函数判断是否出现新候选'
)
assert.match(
  waitBody,
  /draft_regeneration_no_new_candidate/,
  '重生后无新候选必须使用 draft_regeneration_no_new_candidate'
)
assert.match(
  waitBody,
  /draft_regeneration_not_started/,
  '重生入口点击后无流请求/无版本变化必须使用 draft_regeneration_not_started'
)

for (const field of [
  'originalVersionCount',
  'newVersionCount',
  'originalVersionIds',
  'newVersionIds',
  'originalWordCount',
  'newWordCount',
  'originalContentHash',
  'newContentHash',
  'regenerateStartedAt',
  'regenerateEntryLabel',
  'regenerationFailureCode'
]) {
  assert.match(ensureBody, new RegExp(field), `低字数重生诊断必须记录 ${field}`)
}
assert.match(
  ensureBody,
  /expectNewVersion:\s*true/,
  '低字数自动重生必须要求 waitForGeneratedChapterVersion 等到新候选'
)
assert.match(
  ensureBody,
  /previousVersionIds/,
  '低字数自动重生前必须传入旧版本 id 集合'
)
assert.match(
  ensureBody,
  /previousContentHashes/,
  '低字数自动重生前必须传入旧候选 hash 集合'
)
assert.match(
  ensureBody,
  /draft_regeneration_no_new_candidate/,
  '低字数重生没有新版本/内容变化时必须报告 draft_regeneration_no_new_candidate'
)
assert.match(
  ensureBody,
  /below_hard_min_auto_regenerate_succeeded[\s\S]*newWordCount/,
  '新候选达到 hardMin 后才记录重生成功并继续'
)

console.log('live draft regeneration new candidate contract passed')
