import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(source, /function isChapterWordCountInHardRange\(project, count\)/)
assert.match(source, /function buildChapterWordGateError\(project, chapterNum, count, stage = 'chapter'\)/)
assert.match(source, /function findFinalizedWordOutliers\(project, finalizedChapters = \[\]\)/)
assert.match(source, /function assertNoFinalizedWordOutliers\(project, finalizedChapters = \[\], scope = 'existing_finalized'\)/)
assert.match(source, /WORD_COUNT_GATE: chapter/)
assert.match(source, /hardMin: Math\.round\(target \* 0\.8\)/)
assert.match(source, /hardMax: Math\.round\(target \* 1\.4\)/)
assert.match(source, /4000-7000 字/)

const runChapterStart = source.indexOf('async function runChapter(')
const firstVersionIndex = source.indexOf('const firstVersion = await saveCandidate', runChapterStart)
const shortRetryIndex = source.indexOf('for (let expandAttempt = 1; expandAttempt <= 2; expandAttempt += 1)', runChapterStart)
const expandedVersionIndex = source.indexOf('const expandedVersion = await saveCandidate', runChapterStart)
const firstGateIndex = source.indexOf('if (!assessChapterWordCount(project, chapterNum, draftCount', runChapterStart)
const auditIndex = source.indexOf('const audit = await auditChapter', runChapterStart)
assert.ok(runChapterStart > -1, 'runChapter should exist')
assert.ok(firstVersionIndex > runChapterStart, 'candidate should be saved in runChapter')
assert.ok(shortRetryIndex > firstVersionIndex, 'too-short draft retry should run after saving the first candidate')
assert.ok(expandedVersionIndex > shortRetryIndex, 'expanded retry should be saved as a traceable candidate')
assert.ok(firstGateIndex > expandedVersionIndex, 'word gate should run after the short-draft retry chance')
assert.ok(auditIndex > firstGateIndex, 'word gate should run before audit/finalize work')

const finalizeStart = source.indexOf('async function finalizeChapter(')
const finalizeGateIndex = source.indexOf("if (!assessChapterWordCount(project, chapter.chapterNum, count, '定稿'))", finalizeStart)
const finalizeRequestIndex = source.indexOf("await request('POST', `/projects/${project.id}/chapters/${chapter.id}/versions/${version.id}/finalize`", finalizeStart)
assert.ok(finalizeStart > -1, 'finalizeChapter should exist')
assert.ok(finalizeGateIndex > finalizeStart, 'finalize should assess word count first')
assert.ok(finalizeRequestIndex > finalizeGateIndex, 'finalize request should happen only after the word gate')

const continueStart = source.indexOf('async function continueWritingFlow(')
const loadFinalizedForGateIndex = source.indexOf('const finalizedChapters = await loadFinalizedChapters(project, 1, maxFinalized)', continueStart)
const resumeGateIndex = source.indexOf("assertNoFinalizedWordOutliers(project, finalizedChapters, 'resume_before_continue')", continueStart)
const backfillIndex = source.indexOf('await backfillMissingFinalizedPostprocess(', continueStart)
assert.ok(continueStart > -1, 'continueWritingFlow should exist')
assert.ok(loadFinalizedForGateIndex > continueStart, 'continue flow should load finalized chapters before continuing')
assert.ok(resumeGateIndex > loadFinalizedForGateIndex, 'continue flow should gate existing finalized outliers')
assert.ok(backfillIndex > resumeGateIndex, 'existing outlier gate should happen before postprocess/next generation')

console.log('realistic QA word gate contract tests passed')
