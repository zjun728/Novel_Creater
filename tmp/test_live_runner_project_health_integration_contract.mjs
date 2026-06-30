import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const runnerSource = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const runnerSourceWithoutImports = runnerSource
  .split('\n')
  .filter(line => !line.trim().startsWith('import '))
  .join('\n')

assert.match(runnerSource, /project-health-api-snapshot\.mjs/, 'runner should import the API snapshot adapter')
assert.match(runnerSource, /project-health-audit\.mjs/, 'runner should import the pure project health evaluator')
assert.match(runnerSource, /collectProjectHealthSnapshotFromApi/, 'runner should call collectProjectHealthSnapshotFromApi')
assert.match(runnerSource, /summarizeProjectHealthSnapshot/, 'runner should call summarizeProjectHealthSnapshot')
assert.match(runnerSource, /async function refreshProjectHealthAuditForFreezeGuard\s*\(/, 'runner should expose a thin async refresh function')
assert.match(runnerSource, /async function runFreezeGuards\s*\(/, 'runFreezeGuards should be async')

const awaitedCalls = [...runnerSource.matchAll(/await\s+runFreezeGuards\s*\(/g)]
assert.equal(awaitedCalls.length, 3, 'all three runner call sites should await runFreezeGuards')
assert.equal([...runnerSourceWithoutImports.matchAll(/(?<!await\s+)runFreezeGuards\s*\(/g)].length, 1, 'only the function declaration should be a non-awaited runFreezeGuards occurrence')

assert.match(runnerSource, /report\.projectHealthAudit\s*=/, 'runner should write report.projectHealthAudit')
assert.match(runnerSource, /report\.relationshipAudit\s*=/, 'runner should write report.relationshipAudit')
assert.match(runnerSource, /report\.pendingSettingsCount\s*=\s*health\.pendingSettingsCount/, 'runner should sync pendingSettingsCount from health audit')
assert.match(runnerSource, /await\s+refreshProjectHealthAuditForFreezeGuard\s*\(/, 'runFreezeGuards should refresh health audit before assertions')
assert.match(runnerSource, /assertSettingsAndRelationHealth\s*\(\s*\{[\s\S]*?expectedRelationRisk[\s\S]*?\}\s*\)/, 'assertSettingsAndRelationHealth should receive expected relation risk after refresh')
assert.doesNotMatch(runnerSource, /expectedRelationRisk:\s*report\.relationshipAudit\s*\?\s*expectedRelationRisk\s*:\s*null/, 'runner should not skip relation risk after project health audit refresh')

assert.doesNotMatch(runnerSource, /mysql|aiomysql|SELECT\s+/i, 'runner must not add DB dependency or SQL')
assert.doesNotMatch(runnerSource, /chapter-title|domain\/chapter-title|prompts\/chapter\.js.*chapter-title/i, 'runner integration should not touch chapter-title module')
assert.doesNotMatch(runnerSourceWithoutImports, /['"`][^'"`]*(\/settings\/project-health|\/project-health-audit)/, 'runner must not call new backend endpoints')

console.log('live runner project health integration contract passed')
