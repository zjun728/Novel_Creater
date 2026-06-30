import { execFileSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DEFAULT_WORKSPACE_ROOT = path.resolve(__dirname, '../../..')
const DEFAULT_OUT_DIR = path.join(DEFAULT_WORKSPACE_ROOT, 'tmp', 'realistic-flow-qa')
const START_TIME_REUSE_TOLERANCE_MS = 30000
const START_TIME_MATCH_TOLERANCE_MS = 10000

function normalizePathText(value = '') {
  return String(value || '')
    .replace(/\//g, '\\')
    .replace(/\\+$/g, '')
    .toLowerCase()
}

function normalizeCommandText(value = '') {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .replace(/"/g, '')
    .trim()
    .toLowerCase()
}

function parseDateMs(value) {
  if (!value) return 0
  const dotNetMatch = String(value).match(/\/Date\((\d+)\)\//)
  if (dotNetMatch) return Number(dotNetMatch[1]) || 0
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function isPathInside(child = '', parent = '') {
  const normalizedChild = normalizePathText(child)
  const normalizedParent = normalizePathText(parent)
  return Boolean(normalizedChild && normalizedParent && (
    normalizedChild === normalizedParent ||
    normalizedChild.startsWith(`${normalizedParent}\\`)
  ))
}

function readArg(name, fallback = '') {
  const prefix = `--${name}=`
  const inline = process.argv.find(arg => arg.startsWith(prefix))
  if (inline) return inline.slice(prefix.length)
  const index = process.argv.indexOf(`--${name}`)
  if (index >= 0 && process.argv[index + 1]) return process.argv[index + 1]
  return fallback
}

function serviceCommandFingerprint(serviceName = '', commandLine = '') {
  const command = normalizeCommandText(commandLine)
  if (serviceName.includes('runner')) return command.includes('run_longform_browser_240w_phase1.mjs')
  if (serviceName.includes('backend')) return command.includes('uvicorn') && command.includes('main:app') && command.includes('--port 8000')
  if (serviceName.includes('frontend')) return command.includes('npm --prefix frontend run dev') || command.includes('vite') && command.includes('127.0.0.1')
  return false
}

export function createServiceRecord({
  pid,
  serviceName,
  port,
  cwd,
  commandLine,
  startedAt = new Date().toISOString(),
  parentPid = null,
  source = 'manifest'
} = {}) {
  return {
    pid: Number(pid) || 0,
    serviceName: String(serviceName || ''),
    port: Number(port) || null,
    cwd: String(cwd || ''),
    commandLine: String(commandLine || ''),
    startedAt: String(startedAt || new Date().toISOString()),
    parentPid: parentPid === null || parentPid === undefined ? null : Number(parentPid),
    source
  }
}

export function evaluateProcessForCleanup({
  record = {},
  processInfo = null,
  portOwners = new Map(),
  workspaceRoot = DEFAULT_WORKSPACE_ROOT
} = {}) {
  const pid = Number(record.pid || 0)
  const expectedPort = Number(record.port || 0)
  const processStartedMs = parseDateMs(processInfo?.startedAt)
  const recordStartedMs = parseDateMs(record.startedAt)
  const staleByStartTime = Boolean(
    processStartedMs &&
    recordStartedMs &&
    processStartedMs > recordStartedMs + START_TIME_REUSE_TOLERANCE_MS
  )
  const startTimeMatchesRecord = Boolean(
    processStartedMs &&
    recordStartedMs &&
    Math.abs(processStartedMs - recordStartedMs) <= START_TIME_MATCH_TOLERANCE_MS
  )
  const owners = portOwners.get(expectedPort) || new Set()
  const processCwd = processInfo?.cwd || ''
  const processCommand = processInfo?.commandLine || ''
  const executablePath = processInfo?.executablePath || ''
  const commandLineWorkspaceMatch = isPathInside(processCommand, workspaceRoot) ||
    normalizeCommandText(processCommand).includes(normalizeCommandText(workspaceRoot))
  const recordedCommandMatch = Boolean(record.commandLine) &&
    normalizeCommandText(processCommand).includes(normalizeCommandText(record.commandLine))
  const executableWorkspaceMatch = isPathInside(executablePath, workspaceRoot)
  const cwdMatch = Boolean(processCwd && isPathInside(processCwd, workspaceRoot))
  const recordCwdHintMatch = Boolean(record.cwd && (
    normalizeCommandText(processCommand).includes(normalizeCommandText(record.cwd)) ||
    isPathInside(executablePath, record.cwd)
  ))
  const portMatch = Boolean(expectedPort && owners.has(pid))
  const commandMatchesThisLaunch = Boolean(
    recordedCommandMatch &&
    startTimeMatchesRecord &&
    serviceCommandFingerprint(record.serviceName, processCommand)
  )
  const serviceCommandMatch = (serviceCommandFingerprint(record.serviceName, processCommand) || recordedCommandMatch) &&
    (recordCwdHintMatch || commandLineWorkspaceMatch || executableWorkspaceMatch || cwdMatch || portMatch || commandMatchesThisLaunch)
  const runnerCommandMatch = record.serviceName?.includes('runner') && serviceCommandFingerprint(record.serviceName, processCommand)
  const pidExists = Boolean(processInfo)
  const ownershipMatch = Boolean(portMatch || cwdMatch || recordCwdHintMatch || commandLineWorkspaceMatch || executableWorkspaceMatch || serviceCommandMatch || runnerCommandMatch)

  let skippedReason = ''
  if (!pidExists) skippedReason = 'pid_not_running'
  else if (staleByStartTime) skippedReason = 'stale_pid_reused'
  else if (!ownershipMatch) skippedReason = 'ownership_mismatch'

  return {
    pid,
    serviceName: record.serviceName || '',
    killAllowed: Boolean(pidExists && !staleByStartTime && ownershipMatch),
    skippedReason,
    diagnostics: {
      pidExists,
      expectedPort: expectedPort || null,
      portMatch,
      cwdMatch,
      recordCwdHintMatch,
      commandLineWorkspaceMatch,
      recordedCommandMatch,
      executableWorkspaceMatch,
      serviceCommandMatch,
      runnerCommandMatch,
      staleByStartTime,
      startTimeMatchesRecord,
      commandMatchesThisLaunch,
      recordedStartedAt: record.startedAt || '',
      processStartedAt: processInfo?.startedAt || '',
      recordedCwd: record.cwd || '',
      processCwd,
      commandLine: processCommand,
      executablePath,
      owningPidsForPort: [...owners]
    }
  }
}

export function buildCleanupPlan({
  records = [],
  processTable = new Map(),
  portOwners = new Map(),
  workspaceRoot = DEFAULT_WORKSPACE_ROOT
} = {}) {
  let decisions = records.map(record => evaluateProcessForCleanup({
    record,
    processInfo: processTable.get(Number(record.pid || 0)) || null,
    portOwners,
    workspaceRoot
  }))
  const allowedParents = new Set(decisions.filter(item => item.killAllowed).map(item => item.pid))
  decisions = decisions.map(item => {
    const record = records.find(candidate => Number(candidate.pid) === Number(item.pid)) || {}
    if (item.killAllowed || record.source !== 'descendant' || !allowedParents.has(Number(record.parentPid))) return item
    return {
      ...item,
      killAllowed: true,
      skippedReason: '',
      diagnostics: {
        ...item.diagnostics,
        parentAllowed: true,
        parentPid: Number(record.parentPid)
      }
    }
  })
  return {
    createdAt: new Date().toISOString(),
    workspaceRoot,
    killedPids: decisions.filter(item => item.killAllowed).map(item => item.pid),
    skippedStalePids: decisions
      .filter(item => !item.killAllowed)
      .map(item => ({
        pid: item.pid,
        serviceName: item.serviceName,
        skippedReason: item.skippedReason,
        diagnostics: item.diagnostics
      })),
    decisions
  }
}

function powershellJson(script) {
  const output = execFileSync('powershell', ['-NoProfile', '-Command', script], {
    cwd: DEFAULT_WORKSPACE_ROOT,
    encoding: 'utf8',
    windowsHide: true
  }).trim()
  if (!output) return []
  const parsed = JSON.parse(output)
  return Array.isArray(parsed) ? parsed : [parsed]
}

function cimDateToIso(value) {
  if (!value) return ''
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : String(value)
}

function getProcessTable() {
  const rows = powershellJson(`
    Get-CimInstance Win32_Process |
      Select-Object ProcessId,ParentProcessId,CommandLine,ExecutablePath,CreationDate |
      ConvertTo-Json -Depth 3
  `)
  return new Map(rows
    .filter(row => Number(row.ProcessId))
    .map(row => [Number(row.ProcessId), {
      pid: Number(row.ProcessId),
      parentPid: Number(row.ParentProcessId) || null,
      commandLine: row.CommandLine || '',
      executablePath: row.ExecutablePath || '',
      startedAt: cimDateToIso(row.CreationDate),
      cwd: ''
    }]))
}

function getPortOwners(ports = []) {
  const numericPorts = [...new Set(ports.map(Number).filter(Boolean))]
  if (!numericPorts.length) return new Map()
  const rows = powershellJson(`
    Get-NetTCPConnection -State Listen -LocalPort ${numericPorts.join(',')} -ErrorAction SilentlyContinue |
      Select-Object LocalPort,OwningProcess |
      ConvertTo-Json -Depth 3
  `)
  const out = new Map()
  for (const port of numericPorts) out.set(port, new Set())
  for (const row of rows) {
    const port = Number(row.LocalPort)
    const pid = Number(row.OwningProcess)
    if (!out.has(port)) out.set(port, new Set())
    if (pid) out.get(port).add(pid)
  }
  return out
}

function descendantsOf(pid, processTable) {
  const out = []
  const queue = [Number(pid)]
  while (queue.length) {
    const parent = queue.shift()
    for (const info of processTable.values()) {
      if (Number(info.parentPid) !== Number(parent)) continue
      out.push(info.pid)
      queue.push(info.pid)
    }
  }
  return out
}

function expandRecordsWithDescendants(records, processTable) {
  const byPid = new Map(records.map(record => [Number(record.pid), record]))
  for (const record of records) {
    for (const childPid of descendantsOf(record.pid, processTable)) {
      if (byPid.has(childPid)) continue
      byPid.set(childPid, createServiceRecord({
        ...record,
        pid: childPid,
        parentPid: record.pid,
        source: 'descendant'
      }))
    }
  }
  return [...byPid.values()]
}

async function waitForPorts(ports, timeoutMs = 60000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const owners = getPortOwners(ports)
    if (ports.every(port => (owners.get(Number(port)) || new Set()).size > 0)) return owners
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  return getPortOwners(ports)
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
}

export async function startServices() {
  const workspaceRoot = path.resolve(readArg('workspace-root', DEFAULT_WORKSPACE_ROOT))
  const outDir = path.resolve(workspaceRoot, readArg('out-dir', path.relative(workspaceRoot, DEFAULT_OUT_DIR)))
  const label = readArg('label', 'live')
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/, '')
  fs.mkdirSync(outDir, { recursive: true })

  const backendOut = path.join(outDir, `live-backend-${label}.${stamp}.out.log`)
  const backendErr = path.join(outDir, `live-backend-${label}.${stamp}.err.log`)
  const frontendOut = path.join(outDir, `live-frontend-${label}.${stamp}.out.log`)
  const frontendErr = path.join(outDir, `live-frontend-${label}.${stamp}.err.log`)

  const backend = spawn('python', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], {
    cwd: path.join(workspaceRoot, 'backend'),
    detached: true,
    windowsHide: true,
    stdio: ['ignore', fs.openSync(backendOut, 'a'), fs.openSync(backendErr, 'a')]
  })
  backend.unref()

  const frontend = spawn('cmd.exe', ['/c', 'npm', '--prefix', 'frontend', 'run', 'dev', '--', '--host', '127.0.0.1'], {
    cwd: workspaceRoot,
    detached: true,
    windowsHide: true,
    stdio: ['ignore', fs.openSync(frontendOut, 'a'), fs.openSync(frontendErr, 'a')]
  })
  frontend.unref()

  const startedAt = new Date().toISOString()
  const portOwners = await waitForPorts([8000, 5173], 60000)
  const processTable = getProcessTable()
  const records = [
    createServiceRecord({
      pid: backend.pid,
      serviceName: 'backend',
      port: 8000,
      cwd: path.join(workspaceRoot, 'backend'),
      commandLine: 'python -m uvicorn main:app --host 127.0.0.1 --port 8000',
      startedAt
    }),
    createServiceRecord({
      pid: frontend.pid,
      serviceName: 'frontend-shell',
      port: 5173,
      cwd: workspaceRoot,
      commandLine: 'cmd.exe /c npm --prefix frontend run dev -- --host 127.0.0.1',
      startedAt
    })
  ]

  for (const [port, owners] of portOwners.entries()) {
    for (const pid of owners) {
      if (records.some(record => Number(record.pid) === Number(pid))) continue
      records.push(createServiceRecord({
        pid,
        serviceName: port === 8000 ? 'backend-port-owner' : 'frontend-port-owner',
        port,
        cwd: port === 8000 ? path.join(workspaceRoot, 'backend') : workspaceRoot,
        commandLine: processTable.get(pid)?.commandLine || '',
        startedAt
      }))
    }
  }

  const manifest = {
    createdAt: new Date().toISOString(),
    label,
    workspaceRoot,
    outDir,
    logs: { backendOut, backendErr, frontendOut, frontendErr },
    records
  }
  const manifestPath = path.join(outDir, `live-service-manifest-${label}.json`)
  writeJson(manifestPath, manifest)
  writeJson(path.join(outDir, `live-service-pids-${label}.json`), manifest)
  writeJson(path.join(outDir, 'latest-live-service-manifest.json'), manifest)
  console.log(JSON.stringify({ manifestPath, records }, null, 2))
}

export function readManifest(filePath) {
  const manifest = JSON.parse(fs.readFileSync(filePath, 'utf8'))
  return {
    ...manifest,
    records: (manifest.records || []).map(createServiceRecord)
  }
}

function stopPid(pid) {
  try {
    process.kill(Number(pid))
    return { pid: Number(pid), stopped: true }
  } catch (error) {
    return { pid: Number(pid), stopped: false, error: error.message }
  }
}

export function cleanupServices() {
  const manifestPath = path.resolve(readArg('manifest', path.join(DEFAULT_OUT_DIR, 'latest-live-service-manifest.json')))
  const outPath = path.resolve(readArg('out', path.join(DEFAULT_OUT_DIR, `live-service-cleanup-${Date.now()}.json`)))
  const manifest = readManifest(manifestPath)
  const workspaceRoot = path.resolve(readArg('workspace-root', manifest.workspaceRoot || DEFAULT_WORKSPACE_ROOT))
  const processTable = getProcessTable()
  const records = expandRecordsWithDescendants(manifest.records || [], processTable)
  const ports = records.map(record => record.port).filter(Boolean)
  const portOwners = getPortOwners(ports)
  const plan = buildCleanupPlan({ records, processTable, portOwners, workspaceRoot })
  const dryRun = readArg('dry-run', '') === '1' || process.argv.includes('--dry-run')
  const stopResults = dryRun ? [] : [...new Set(plan.killedPids)].reverse().map(stopPid)
  const report = {
    ...plan,
    manifestPath,
    dryRun,
    stopResults
  }
  writeJson(outPath, report)
  writeJson(path.join(path.dirname(outPath), 'latest-live-service-cleanup.json'), report)
  console.log(JSON.stringify({ outPath, killedPids: report.killedPids, skippedStalePids: report.skippedStalePids }, null, 2))
}

export function runLiveServiceManagerCli(argv = process.argv) {
  const command = argv[2] || ''
  if (command === 'start') {
    startServices().catch(error => {
      console.error(error)
      process.exitCode = 1
    })
  } else if (command === 'cleanup') {
    try {
      cleanupServices()
    } catch (error) {
      console.error(error)
      process.exitCode = 1
    }
  } else {
    console.error('Usage: node tmp/live_service_manager.mjs <start|cleanup> [--label X] [--manifest path] [--out path]')
    process.exitCode = 1
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  runLiveServiceManagerCli(process.argv)
}
