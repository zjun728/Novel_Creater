import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  buildCleanupPlan,
  createServiceRecord,
  evaluateProcessForCleanup
} from './live_service_manager.mjs'

const workspaceRoot = 'D:\\Projects\\Novel_Creater'

const staleRecord = createServiceRecord({
  pid: 43340,
  serviceName: 'frontend',
  port: 5173,
  cwd: workspaceRoot,
  commandLine: 'cmd.exe /c npm --prefix frontend run dev -- --host 127.0.0.1',
  startedAt: '2026-06-26T07:00:00.000Z'
})

const reusedByOtherProject = {
  pid: 43340,
  parentPid: 1000,
  cwd: 'D:\\Projects\\Quantization_Stock\\frontend',
  commandLine: 'D:\\Projects\\Quantization_Stock\\frontend\\node_modules\\@esbuild\\win32-x64\\esbuild.exe --service',
  executablePath: 'D:\\Projects\\Quantization_Stock\\frontend\\node_modules\\@esbuild\\win32-x64\\esbuild.exe',
  startedAt: '2026-06-26T08:30:00.000Z'
}

const staleDecision = evaluateProcessForCleanup({
  record: staleRecord,
  processInfo: reusedByOtherProject,
  portOwners: new Map([[5173, new Set([12824])]]),
  workspaceRoot
})

assert.equal(staleDecision.killAllowed, false)
assert.equal(staleDecision.skippedReason, 'stale_pid_reused')
assert.equal(staleDecision.diagnostics.portMatch, false)
assert.equal(staleDecision.diagnostics.cwdMatch, false)
assert.equal(staleDecision.diagnostics.commandLineWorkspaceMatch, false)

const stalePlan = buildCleanupPlan({
  records: [staleRecord],
  processTable: new Map([[43340, reusedByOtherProject]]),
  portOwners: new Map([[5173, new Set([12824])]]),
  workspaceRoot
})

assert.deepEqual(stalePlan.killedPids, [])
assert.deepEqual(stalePlan.skippedStalePids.map(item => item.pid), [43340])
assert.match(stalePlan.skippedStalePids[0].skippedReason, /stale_pid_reused/)

const matchingBackend = createServiceRecord({
  pid: 40204,
  serviceName: 'backend',
  port: 8000,
  cwd: `${workspaceRoot}\\backend`,
  commandLine: 'python -m uvicorn main:app --host 127.0.0.1 --port 8000',
  startedAt: '2026-06-26T07:00:00.000Z'
})

const backendDecision = evaluateProcessForCleanup({
  record: matchingBackend,
  processInfo: {
    pid: 40204,
    parentPid: 1,
    cwd: `${workspaceRoot}\\backend`,
    commandLine: 'python -m uvicorn main:app --host 127.0.0.1 --port 8000',
    executablePath: 'D:\\Software\\Python\\Python312\\python.exe',
    startedAt: '2026-06-26T07:00:01.000Z'
  },
  portOwners: new Map([[8000, new Set([40204])]]),
  workspaceRoot
})

assert.equal(backendDecision.killAllowed, true)
assert.equal(backendDecision.diagnostics.portMatch, true)
assert.equal(backendDecision.diagnostics.cwdMatch, true)

const matchingFrontendShell = createServiceRecord({
  pid: 33228,
  serviceName: 'frontend-shell',
  port: 5173,
  cwd: workspaceRoot,
  commandLine: 'cmd.exe /c npm --prefix frontend run dev -- --host 127.0.0.1',
  startedAt: '2026-06-26T08:10:55.186Z'
})

const frontendShellDecision = evaluateProcessForCleanup({
  record: matchingFrontendShell,
  processInfo: {
    pid: 33228,
    parentPid: 1,
    cwd: '',
    commandLine: 'cmd.exe /c npm --prefix frontend run dev -- --host 127.0.0.1',
    executablePath: 'C:\\Windows\\system32\\cmd.exe',
    startedAt: '/Date(1782461455173)/'
  },
  portOwners: new Map([[5173, new Set([37948])]]),
  workspaceRoot
})

assert.equal(frontendShellDecision.killAllowed, true)
assert.equal(frontendShellDecision.diagnostics.portMatch, false)
assert.equal(frontendShellDecision.diagnostics.commandMatchesThisLaunch, true)

assert.ok(staleRecord.pid)
assert.ok(staleRecord.port)
assert.ok(staleRecord.cwd)
assert.ok(staleRecord.commandLine)
assert.ok(staleRecord.startedAt)
assert.equal(staleRecord.serviceName, 'frontend')

const managerSource = fs.readFileSync('tmp/live-qa/services/live-service-manager.mjs', 'utf8')
assert.match(
  managerSource,
  /const stopResults = dryRun \? \[\] : \[\.\.\.new Set\(plan\.killedPids\)\]\.reverse\(\)\.map\(stopPid\)/,
  'dry-run cleanup must not call stopPid while building the report'
)

console.log('live service cleanup safety contract passed')
