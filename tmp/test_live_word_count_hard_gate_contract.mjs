import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  assessChapterWordCount,
  buildChapterWordTarget
} from '../frontend/src/utils/chapterWordTarget.js'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

const target = buildChapterWordTarget({
  targetWords: 2400000,
  targetChapters: 480
})
assert.equal(target.target, 5000, '240w/480 chapters should target about 5000 chars per chapter')
assert.equal(target.hardMin, 4000, '240w/480 chapters should use frontend hardMin 4000, not 3500')
assert.equal(
  assessChapterWordCount('字'.repeat(3882), target).level,
  'hard_under',
  '3882 chars must be below the frontend hard floor'
)

assert.match(
  liveScript,
  /from ['"]\.\.\/frontend\/src\/utils\/chapterWordTarget\.js['"]/,
  'live script should import the same word target utilities as WriterView'
)
assert.doesNotMatch(
  liveScript,
  /const\s+hardMin\s*=\s*3500/,
  'live script must not keep a stale hardMin=3500'
)
assert.match(
  liveScript,
  /buildChapterWordTarget/,
  'live word policy should be derived from buildChapterWordTarget'
)
assert.match(
  liveScript,
  /assessChapterWordCount/,
  'live word policy should assess drafts with assessChapterWordCount'
)
assert.match(
  liveScript,
  /正文低于硬下限[\s\S]*chapter_below_hard_min/,
  'below-hard-min modal should be classified as chapter_below_hard_min'
)
assert.match(
  liveScript,
  /belowHardMinModal[\s\S]*finalizeApiEvents/,
  'finalize diagnostics should record below-hard-min modal beside finalizeApiEvents'
)
assert.match(
  liveScript,
  /regenerateAttempted[\s\S]*regenerateSucceeded/,
  'below-hard-min diagnostics should record regeneration attempt and result'
)
assert.match(
  liveScript,
  /第 \$\{entry\.chapterNum\} 章低于硬下限，未进入定稿/,
  'acceptance reason should state the chapter did not enter finalization'
)

console.log('live word count hard gate contract tests passed')
