import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

const helperMatch = source.match(/function contentHash[\s\S]*?\n}\n\nfunction visibleDraftErrorMessages/)
assert.ok(helperMatch, 'live script must keep candidate fingerprint helpers near contentHash')
const modalMatch = source.match(/function modalCandidateWordCount[\s\S]*?\n}\n\nasync function collectPostDraftDiagnostics/)
assert.ok(modalMatch, 'live script must expose stale below-hard-min modal helpers before diagnostics')
const finalizeMatch = source.match(/async function ensureLatestHardPassCandidateSelectedForFinalize[\s\S]*?\n}\n\nasync function runChapter/)
assert.ok(finalizeMatch, 'live script must preflight selected/latest candidate before finalization')

const helperSource = helperMatch[0].replace(/\nfunction visibleDraftErrorMessages[\s\S]*$/, '')
const modalSource = modalMatch[0].replace(/\nasync function collectPostDraftDiagnostics[\s\S]*$/, '')
const sandbox = {
  createHash,
  console,
  buildLiveChapterWordTarget: () => ({
    target: 5000,
    min: 4500,
    max: 6500,
    hardMin: 4000,
    hardMax: 7000
  }),
  wordCountPolicy: wordCount => ({
    status: Number(wordCount || 0) < 4000 ? 'below_hard_min' : 'soft_floor_warning',
    hardPass: Number(wordCount || 0) >= 4000,
    hardMin: 4000,
    liveHardMin: 4000,
    appHardMin: 4000
  })
}
vm.runInNewContext(`${helperSource}
${modalSource}
globalThis.__helpers = {
  contentHash,
  latestCandidateVersion,
  latestHardPassCandidateVersion,
  modalCandidateWordCount,
  buildFinalizeVersionStateDiagnostics
}`, sandbox)

const {
  contentHash,
  latestCandidateVersion,
  latestHardPassCandidateVersion,
  modalCandidateWordCount,
  buildFinalizeVersionStateDiagnostics
} = sandbox.__helpers

const oldVersion = {
  id: 'old-3461',
  content: '旧'.repeat(3461),
  createdAt: '2026-06-25T07:00:00.000Z',
  updatedAt: '2026-06-25T07:00:00.000Z'
}
const newVersion = {
  id: 'new-4251',
  content: '新'.repeat(4251),
  createdAt: '2026-06-25T07:04:06.000Z',
  updatedAt: '2026-06-25T07:04:06.000Z'
}

assert.equal(modalCandidateWordCount('正文低于硬下限，本章约 3461 字，硬下限 4000 字。'), 3461)
assert.equal(latestCandidateVersion([oldVersion, newVersion]).id, 'new-4251')
assert.equal(latestHardPassCandidateVersion([oldVersion, newVersion]).id, 'new-4251')

const staleModalDiagnostics = buildFinalizeVersionStateDiagnostics({
  selectedVersion: newVersion,
  latestCandidate: newVersion,
  modalText: '正文低于硬下限，本章约 3461 字，硬下限 4000 字。',
  wordTarget: { hardMin: 4000 }
})
assert.equal(staleModalDiagnostics.selectedVersionId, 'new-4251')
assert.equal(staleModalDiagnostics.selectedVersionWordCount, 4251)
assert.equal(staleModalDiagnostics.selectedVersionHash, contentHash(newVersion.content))
assert.equal(staleModalDiagnostics.latestCandidateVersionId, 'new-4251')
assert.equal(staleModalDiagnostics.latestCandidateWordCount, 4251)
assert.equal(staleModalDiagnostics.modalCandidateWordCount, 3461)
assert.equal(staleModalDiagnostics.modalStale, true)
assert.equal(staleModalDiagnostics.blockerSource, 'stale_modal')

const staleSelectionDiagnostics = buildFinalizeVersionStateDiagnostics({
  selectedVersion: oldVersion,
  latestCandidate: newVersion,
  modalText: '',
  wordTarget: { hardMin: 4000 }
})
assert.equal(staleSelectionDiagnostics.selectedVersionId, 'old-3461')
assert.equal(staleSelectionDiagnostics.latestCandidateVersionId, 'new-4251')
assert.equal(staleSelectionDiagnostics.selectedVersionStale, true)
assert.equal(staleSelectionDiagnostics.blockerSource, 'selected_version_stale')

const scriptChecks = [
  /data-version-id/,
  /data-current-version/,
  /ensureLatestHardPassCandidateSelectedForFinalize/,
  /clickFinalizeForLatestHardPassCandidate/,
  /dismissStaleBelowHardMinModalIfSafe/,
  /stale_below_hard_min_modal/,
  /selected_version_stale/,
  /closeBelowHardMinModalAttempted/,
  /closeBelowHardMinModalSucceeded/,
  /maskCountBeforeDismiss/,
  /maskCountAfterDismiss/
]
for (const pattern of scriptChecks) {
  assert.match(source, pattern, `live/finalize stale-modal chain must include ${pattern}`)
}

const runChapterFinalizeBlock = source.match(/markChapterFlowEvent\(chapterNum, 'finalize_click_started'[\s\S]*?try \{\s*markChapterFlowEvent\(chapterNum, 'finalize_started'/)?.[0] || ''
assert.doesNotMatch(
  runChapterFinalizeBlock,
  /clickButton\(page,\s*['"]定稿['"]/,
  'finalization flow must not use generic last 定稿 button, which can click the old low-word version'
)
assert.match(
  runChapterFinalizeBlock,
  /clickFinalizeForLatestHardPassCandidate/,
  'finalization flow must click the latest hard-pass candidate version'
)

console.log('live stale below-hard-min modal contract passed')
