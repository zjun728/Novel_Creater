import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  buildCleanupPlan,
  createServiceRecord,
  evaluateProcessForCleanup,
  runLiveServiceManagerCli,
  startServices,
  cleanupServices,
  readManifest
} from './live-qa/services/live-service-manager.mjs'
import {
  buildCleanupPlan as legacyBuildCleanupPlan,
  createServiceRecord as legacyCreateServiceRecord,
  evaluateProcessForCleanup as legacyEvaluateProcessForCleanup
} from './live_service_manager.mjs'

assert.equal(typeof createServiceRecord, 'function')
assert.equal(typeof evaluateProcessForCleanup, 'function')
assert.equal(typeof buildCleanupPlan, 'function')
assert.equal(typeof runLiveServiceManagerCli, 'function')
assert.equal(typeof startServices, 'function')
assert.equal(typeof cleanupServices, 'function')
assert.equal(typeof readManifest, 'function')
assert.equal(legacyCreateServiceRecord, createServiceRecord)
assert.equal(legacyEvaluateProcessForCleanup, evaluateProcessForCleanup)
assert.equal(legacyBuildCleanupPlan, buildCleanupPlan)

const workspaceRoot = 'D:\\Projects\\Novel_Creater'
const manifestRecord = createServiceRecord({
  pid: 1001,
  serviceName: 'backend',
  port: 8000,
  cwd: `${workspaceRoot}\\backend`,
  commandLine: 'python -m uvicorn main:app --host 127.0.0.1 --port 8000',
  startedAt: '2026-06-26T07:00:00.000Z'
})
const matchingDecision = evaluateProcessForCleanup({
  record: manifestRecord,
  processInfo: {
    pid: 1001,
    cwd: `${workspaceRoot}\\backend`,
    commandLine: 'python -m uvicorn main:app --host 127.0.0.1 --port 8000',
    executablePath: 'D:\\Software\\Python\\Python312\\python.exe',
    startedAt: '2026-06-26T07:00:01.000Z'
  },
  portOwners: new Map([[8000, new Set([1001])]]),
  workspaceRoot
})
assert.equal(matchingDecision.killAllowed, true)

const descendantRecord = createServiceRecord({
  ...manifestRecord,
  pid: 1002,
  parentPid: 1001,
  source: 'descendant'
})
const descendantPlan = buildCleanupPlan({
  records: [manifestRecord, descendantRecord],
  processTable: new Map([
    [1001, {
      pid: 1001,
      cwd: `${workspaceRoot}\\backend`,
      commandLine: 'python -m uvicorn main:app --host 127.0.0.1 --port 8000',
      executablePath: 'D:\\Software\\Python\\Python312\\python.exe',
      startedAt: '2026-06-26T07:00:01.000Z'
    }],
    [1002, {
      pid: 1002,
      parentPid: 1001,
      cwd: '',
      commandLine: 'worker child',
      executablePath: '',
      startedAt: '2026-06-26T07:00:02.000Z'
    }]
  ]),
  portOwners: new Map([[8000, new Set([1001])]]),
  workspaceRoot
})
assert.deepEqual(descendantPlan.killedPids, [1001, 1002])

const legacySource = fs.readFileSync('tmp/live_service_manager.mjs', 'utf8')
assert.doesNotMatch(legacySource, /function\s+buildCleanupPlan\b/)
assert.doesNotMatch(legacySource, /function\s+evaluateProcessForCleanup\b/)
assert.doesNotMatch(legacySource, /function\s+startServices\b/)
assert.doesNotMatch(legacySource, /function\s+cleanupServices\b/)
assert.doesNotMatch(legacySource, /\bspawn\s*\(/)
assert.doesNotMatch(legacySource, /\bexecFileSync\s*\(/)
assert.doesNotMatch(legacySource, /process\.kill\s*\(/)
assert.doesNotMatch(legacySource, /fs\.openSync\s*\(/)
assert.match(legacySource, /runLiveServiceManagerCli\s*\(\s*process\.argv\s*\)/)

const moduleSource = fs.readFileSync('tmp/live-qa/services/live-service-manager.mjs', 'utf8')
assert.match(moduleSource, /latest-live-service-manifest\.json/, 'start manifest latest path must be preserved')
assert.match(moduleSource, /latest-live-service-cleanup\.json/, 'cleanup latest path must be preserved')
assert.match(
  moduleSource,
  /const stopResults = dryRun \? \[\] : \[\.\.\.new Set\(plan\.killedPids\)\]\.reverse\(\)\.map\(stopPid\)/,
  'dry-run cleanup must not call stopPid while building the report'
)
assert.doesNotMatch(moduleSource, /mysql|aiomysql|SELECT\s+|chromium|playwright|chapter-title/i)

console.log('live service manager module contract passed')
