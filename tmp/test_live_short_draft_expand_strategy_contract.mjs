import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'

const runnerPath = path.resolve('tmp/run_longform_browser_240w_phase1.mjs')
const source = fs.readFileSync(runnerPath, 'utf8')

const ensureMatch = source.match(
  /async function ensureDraftAboveHardMinOrRegenerate[\s\S]*?\n}\n\nasync function /
)

assert.ok(ensureMatch, 'runner should expose ensureDraftAboveHardMinOrRegenerate')
const ensureBody = ensureMatch[0]
const shortDraftSection = source.slice(
  source.indexOf('const SHORT_DRAFT_EXPANSION_MIN'),
  source.indexOf('function hasNewGeneratedVersionCandidate')
)

assert.match(
  source,
  /async function expandShortDraftCandidate/,
  'runner should have an expandShortDraftCandidate repair path'
)

assert.match(
  source,
  /function isCompleteBeatPlanForShortDraftExpansion/,
  'short draft expansion should only run when the beat plan has enough persisted planning context'
)

assert.match(
  shortDraftSection,
  /function buildShortDraftEndingGuard/,
  'short draft expansion should build an explicit ending guard from the original draft ending'
)

assert.match(
  shortDraftSection,
  /必须保留的结尾交接/,
  'short draft expansion prompt should isolate the ending handoff so expansion does not drift at the final beat'
)

assert.match(
  ensureBody,
  /originalWordCount\s*>=\s*SHORT_DRAFT_EXPANSION_MIN[\s\S]*originalWordCount\s*<\s*4000/,
  'drafts in the configured short draft band should try expansion before full regeneration'
)

assert.match(
  source,
  /const\s+SHORT_DRAFT_EXPANSION_MIN\s*=\s*2500/,
  'drafts in the 2500-3999 band should try expansion before full regeneration when beat plan is complete'
)

assert.match(
  shortDraftSection,
  /const\s+SHORT_DRAFT_EXPANSION_TARGET\s*=\s*'4500-5200'/,
  'short draft expansion should explicitly target 4500-5200 while accepting hardMin separately'
)

assert.doesNotMatch(
  shortDraftSection,
  /4500-6000/,
  'short draft expansion should not use the old loose 4500-6000 target'
)

assert.match(
  source,
  /const\s+SHORT_DRAFT_TOP_UP_MIN\s*=\s*3500/,
  'first expansions in the 3500-3999 band should be eligible for a top-up pass'
)

assert.match(
  source,
  /async function topUpShortDraftExpansion/,
  'runner should have a top_up_expand_short_draft recovery pass after a safe but still-short expansion'
)

assert.match(
  source,
  /taskName:\s*'top_up_expand_short_draft'/,
  'top-up pass should use its own taskName for diagnostics'
)

assert.match(
  source,
  /firstExpandedWordCount/,
  'live diagnostics should keep the first expansion word count'
)

assert.match(
  source,
  /topUpExpandedWordCount/,
  'live diagnostics should keep the top-up expansion word count'
)

assert.match(
  source,
  /expansionPasses/,
  'live diagnostics should record each expansion pass'
)

assert.match(
  ensureBody,
  /shortDraftStrategy:\s*'expand_existing'/,
  'live diagnostics should record expand_existing when the short draft expansion path is used'
)

assert.match(
  ensureBody,
  /expandedWordCount/,
  'live diagnostics should record the expanded candidate word count'
)

assert.match(
  ensureBody,
  /factDriftCheck/,
  'expanded drafts should be checked for core fact drift'
)

assert.match(
  ensureBody,
  /endingPreserved/,
  'expanded drafts should check that the original ending is preserved'
)

assert.match(
  source,
  /expandedWordCount\s*>=\s*SHORT_DRAFT_TOP_UP_MIN[\s\S]*expandedWordCount\s*<=\s*SHORT_DRAFT_TOP_UP_MAX[\s\S]*factDriftCheck\.passed[\s\S]*endingPreserved\.passed/,
  'a safe first expansion in the 3500-3999 band should top up instead of failing or regenerating'
)

assert.match(
  ensureBody,
  /clickDraftRegenerationEntry/,
  'full regeneration fallback should remain available after expansion fails'
)

assert.match(
  ensureBody,
  /shortDraftStrategy:\s*'full_regenerate'/,
  'live diagnostics should record full_regenerate when expansion cannot be accepted'
)

const blockerMatch = source.match(/function throwIfChapterBelowHardMin[\s\S]*?\n}\n\n/)
assert.ok(blockerMatch, 'runner should expose throwIfChapterBelowHardMin')
assert.match(
  blockerMatch[0],
  /shortDraftStrategy/,
  'hard-min blockers should preserve short draft recovery diagnostics'
)

const runChapterMatch = source.match(/async function runChapter[\s\S]*?\n}\n\nasync function /)
assert.ok(runChapterMatch, 'runner should expose runChapter')
assert.match(
  runChapterMatch[0],
  /existing_short_draft_recovered/,
  'resume runs should recover an existing short candidate before clicking the normal draft entry again'
)

console.log('OK live short draft expansion strategy contract')
