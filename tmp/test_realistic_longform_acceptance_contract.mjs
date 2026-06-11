import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const flow = readFileSync('tmp/run_realistic_longform_flow_fixed.mjs', 'utf8')

assert.match(flow, /finalChapterWordCounts:\s*\[\]/, 'report should track final chapter word counts separately from candidate counts')
assert.match(flow, /multiChapterAcceptance:\s*null/, 'report should persist multi-chapter acceptance output')
assert.match(flow, /function assessChapterWordCount\(/, 'chapter generation should have explicit word-count assessment')
assert.match(flow, /function validateRevisionWordDrift\(/, 'audit-based revision should guard against large word-count drift')
assert.match(flow, /function runMultiChapterAcceptance\(/, 'flow should include a multi-chapter acceptance module')
assert.match(flow, /function normalizeGeneratedReport\(/, 'resume should normalize old reports that predate new QA fields')
assert.match(flow, /report\.generated\s*=\s*normalizeGeneratedReport\(previous\?\.generated\)/, 'resume should merge previous generated counters with current defaults')
assert.match(flow, /MAX_JSON_SCAN_CHARS/, 'malformed long JSON parsing should be bounded')
assert.match(flow, /MAX_JSON_CANDIDATES/, 'malformed JSON candidate collection should be bounded')
assert.match(flow, /async function syncProjectChapterStats\(/, 'resume reports should sync chapter counters from project state')
assert.match(flow, /多章一致性验收|multi-chapter acceptance/i, 'report should include a multi-chapter acceptance section')

const auditBlock = flow.match(/async function auditChapter\([\s\S]*?\n\}/)?.[0] || ''
assert.doesNotMatch(auditBlock, /继续进入后续流程/, 'audit JSON failures must not be silently treated as a clean audit')
assert.match(auditBlock, /auditFailed:\s*true/, 'audit JSON failures should be represented as a failed quality gate')

const acceptanceBlock = flow.match(/async function runMultiChapterAcceptance\([\s\S]*?async function runGlobalAudit/s)?.[0] || ''
assert.match(acceptanceBlock, /character_drift/, 'acceptance should check character drift')
assert.match(acceptanceBlock, /plot_contradiction/, 'acceptance should check plot contradictions')
assert.match(acceptanceBlock, /timeline/, 'acceptance should check timeline continuity')
assert.match(acceptanceBlock, /world_rule/, 'acceptance should check world rules')
assert.match(acceptanceBlock, /foreshadowing/, 'acceptance should check foreshadowing')
assert.match(acceptanceBlock, /style_drift/, 'acceptance should check style drift')
assert.match(acceptanceBlock, /state_carryover/, 'acceptance should check state carryover')

const continueBlock = flow.match(/async function continueWritingFlow\([\s\S]*?async function runGlobalAudit/s)?.[0] || ''
assert.match(continueBlock, /writeReport\(\)/, 'long-running resume should write progress report after each chapter')
assert.match(continueBlock, /syncProjectChapterStats\(project\)/, 'progress snapshots should reflect actual finalized chapter count')

console.log('realistic longform acceptance contract tests passed')
