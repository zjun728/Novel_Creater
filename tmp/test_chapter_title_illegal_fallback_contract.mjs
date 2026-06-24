import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  cleanGeneratedChapterTitle,
  deriveFallbackChapterTitle,
  evaluateChapterTitlePolicy,
  getChapterTitleQuality
} from '../frontend/src/prompts/chapter.js'

for (const title of ['{', '}', '——', '你——', '```', '"', '“']) {
  const policy = evaluateChapterTitlePolicy(title)
  assert.equal(policy.status, 'fail', `${title} must be hard rejected`)
  assert.equal(cleanGeneratedChapterTitle(title), '', `${title} must not be accepted as generated title`)
  const quality = getChapterTitleQuality(title)
  assert.equal(quality.titleValid, false, `${title} quality must be invalid`)
  assert.ok(quality.titleInvalidReason, `${title} invalid reason must be reported`)
}

const badAiOutput = JSON.stringify({
  candidates: [
    { title: '{', type: 'event', reason: 'json fragment' },
    { title: '你——', type: 'event', reason: 'dialogue fragment' },
    { title: '}', type: 'event', reason: 'json fragment' }
  ]
})

assert.equal(cleanGeneratedChapterTitle(badAiOutput), '')

const fallback = deriveFallbackChapterTitle({
  beatPlan: '陆沉舟抵达北境矿场，潜入三号矿道，寻找父亲账册，并躲避巡天司追兵。',
  content: '旧货市场的线索指向北境矿场。陆沉舟摸进三号矿道，终于找到父亲账册，身后巡天司追兵逼近。'
})

assert.ok(
  ['旧货市场', '北境矿场', '三号矿道', '父亲账册', '巡天司追兵'].includes(fallback),
  `fallback title should use a plain concrete term, got ${fallback}`
)
assert.equal(cleanGeneratedChapterTitle(fallback), fallback)

const liveSource = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
assert.match(liveSource, /titleQuality/, 'live report must include titleQuality')
assert.match(liveSource, /titleValid/, 'titleQuality must include titleValid')
assert.match(liveSource, /titleInvalidReason/, 'titleQuality must include titleInvalidReason')
assert.match(liveSource, /fallbackUsed/, 'titleQuality must include fallbackUsed')
assert.match(liveSource, /wordCountPolicy/, 'live report must include wordCountPolicy')
