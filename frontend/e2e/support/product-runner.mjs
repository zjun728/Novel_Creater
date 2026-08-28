import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { lstatSync, mkdtempSync, realpathSync, rmSync } from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

import { createServerLogObserver } from '../server-log-observer.mjs'


export const REQUIRED_TEST_VARIABLES = Object.freeze([
  'TEST_MYSQL_HOST',
  'TEST_MYSQL_PORT',
  'TEST_MYSQL_USER',
  'TEST_MYSQL_PASSWORD',
])
export const DISPOSABLE_DATABASE = /^novel_creator_test_[a-f0-9]{32}$/u
export const BASE_ENV_ALLOWLIST = Object.freeze([
  'PATH',
  'Path',
  'PATHEXT',
  'SystemRoot',
  'SYSTEMROOT',
  'WINDIR',
  'COMSPEC',
  'ComSpec',
  'TEMP',
  'TMP',
  'TMPDIR',
  'HOME',
  'USERPROFILE',
  'LOCALAPPDATA',
  'APPDATA',
  'VIRTUAL_ENV',
  'PYTHONPATH',
  'PYTHONHOME',
  'PYTHONUTF8',
  'PYTHONIOENCODING',
  'PLAYWRIGHT_BROWSERS_PATH',
  'LANG',
  'LC_ALL',
  'TZ',
])
export const DEFAULT_RUNNER_DEADLINES = Object.freeze({
  prepareMs: 60_000,
  healthMs: 45_000,
  browserMs: 180_000,
  cleanupMs: 60_000,
  stopMs: 5_000,
  settleMs: 15_000,
})

const WINDOWS_JOB_SUPERVISOR_SOURCE = String.raw`
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$supervisorStage = 'compile'
try {
  $source = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class NovelCreatorOwnedJob
{
    private const uint CREATE_SUSPENDED = 0x00000004;
    private const uint CREATE_NO_WINDOW = 0x08000000;
    private const uint STARTF_USESTDHANDLES = 0x00000100;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const uint HANDLE_FLAG_INHERIT = 0x00000001;
    private const uint INFINITE = 0xffffffff;
    private const int STD_INPUT_HANDLE = -10;
    private const int STD_OUTPUT_HANDLE = -11;
    private const int STD_ERROR_HANDLE = -12;
    private const int JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess;
        public IntPtr hThread;
        public uint dwProcessId;
        public uint dwThreadId;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(
        IntPtr lpJobAttributes,
        string lpName
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr hJob,
        int JobObjectInfoClass,
        ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION lpJobObjectInfo,
        uint cbJobObjectInfoLength
    );

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateProcessW(
        string lpApplicationName,
        StringBuilder lpCommandLine,
        IntPtr lpProcessAttributes,
        IntPtr lpThreadAttributes,
        bool bInheritHandles,
        uint dwCreationFlags,
        IntPtr lpEnvironment,
        string lpCurrentDirectory,
        ref STARTUPINFO lpStartupInfo,
        out PROCESS_INFORMATION lpProcessInformation
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(
        IntPtr hJob,
        IntPtr hProcess
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr hThread);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(
        IntPtr hHandle,
        uint dwMilliseconds
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetExitCodeProcess(
        IntPtr hProcess,
        out uint lpExitCode
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateProcess(
        IntPtr hProcess,
        uint uExitCode
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetHandleInformation(
        IntPtr hObject,
        uint dwMask,
        uint dwFlags
    );

    private static string Quote(string value)
    {
        if (value.Length > 0 && value.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            return value;
        var result = new StringBuilder("\"");
        var slashes = 0;
        foreach (var character in value)
        {
            if (character == '\\')
            {
                slashes += 1;
                continue;
            }
            if (character == '"')
            {
                result.Append('\\', slashes * 2 + 1);
                result.Append('"');
                slashes = 0;
                continue;
            }
            result.Append('\\', slashes);
            slashes = 0;
            result.Append(character);
        }
        result.Append('\\', slashes * 2);
        result.Append('"');
        return result.ToString();
    }

    private static StringBuilder CommandLine(
        string application,
        string[] arguments
    )
    {
        var values = new List<string> { Quote(application) };
        foreach (var argument in arguments) values.Add(Quote(argument));
        return new StringBuilder(string.Join(" ", values));
    }

    private static IntPtr InheritableStandardHandle(int identifier)
    {
        var handle = GetStdHandle(identifier);
        if (handle == IntPtr.Zero || handle == new IntPtr(-1))
            throw new InvalidOperationException("standard handle unavailable");
        if (!SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT))
            throw new InvalidOperationException("standard handle inheritance failed");
        return handle;
    }

    public static int Run(
        string application,
        string[] arguments,
        string workingDirectory
    )
    {
        var job = IntPtr.Zero;
        var process = new PROCESS_INFORMATION();
        var processCreated = false;
        var assigned = false;
        try
        {
            job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero)
                throw new InvalidOperationException("job creation failed");
            var limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            limits.BasicLimitInformation.LimitFlags =
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if (!SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ref limits,
                (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION))
            ))
                throw new InvalidOperationException("job configuration failed");

            var startup = new STARTUPINFO();
            startup.cb = Marshal.SizeOf(typeof(STARTUPINFO));
            startup.dwFlags = (int)STARTF_USESTDHANDLES;
            startup.hStdInput = InheritableStandardHandle(STD_INPUT_HANDLE);
            startup.hStdOutput = InheritableStandardHandle(STD_OUTPUT_HANDLE);
            startup.hStdError = InheritableStandardHandle(STD_ERROR_HANDLE);
            if (!CreateProcessW(
                null,
                CommandLine(application, arguments),
                IntPtr.Zero,
                IntPtr.Zero,
                true,
                CREATE_SUSPENDED | CREATE_NO_WINDOW,
                IntPtr.Zero,
                workingDirectory,
                ref startup,
                out process
            ))
                throw new InvalidOperationException("owned process creation failed");
            processCreated = true;
            if (!AssignProcessToJobObject(job, process.hProcess))
                throw new InvalidOperationException("job assignment failed");
            assigned = true;
            if (ResumeThread(process.hThread) == 0xffffffff)
                throw new InvalidOperationException("owned process resume failed");
            if (WaitForSingleObject(process.hProcess, INFINITE) != 0)
                throw new InvalidOperationException("owned process wait failed");
            uint exitCode;
            if (!GetExitCodeProcess(process.hProcess, out exitCode))
                throw new InvalidOperationException("owned process exit unavailable");
            return unchecked((int)exitCode);
        }
        finally
        {
            if (processCreated && !assigned)
                TerminateProcess(process.hProcess, 125);
            if (process.hThread != IntPtr.Zero) CloseHandle(process.hThread);
            if (process.hProcess != IntPtr.Zero) CloseHandle(process.hProcess);
            if (job != IntPtr.Zero) CloseHandle(job);
        }
    }
}
'@
  Add-Type -TypeDefinition $source
  $supervisorStage = 'configuration read'
  $configurationJson = [Console]::In.ReadToEnd()
  $supervisorStage = 'configuration parse'
  $configuration = $configurationJson | ConvertFrom-Json
  $supervisorStage = 'configuration arguments'
  $arguments = @($configuration.arguments | ForEach-Object { [string]$_ })
  $supervisorStage = 'process'
  $status = [NovelCreatorOwnedJob]::Run(
    [string]$configuration.command,
    [string[]]$arguments,
    [string]$configuration.cwd
  )
  exit $status
} catch {
  $safeStage = if ($_.Exception.InnerException) {
    [string]$_.Exception.InnerException.Message
  } else {
    [string]$_.Exception.Message
  }
  if ($safeStage -notmatch '^(job|standard handle|owned process) ') {
    $safeStage = $supervisorStage + ' failed'
  }
  [Console]::Error.WriteLine('owned Windows job supervisor failed: ' + $safeStage)
  exit 125
}
`
const WINDOWS_JOB_SUPERVISOR_ENCODED = Buffer
  .from(WINDOWS_JOB_SUPERVISOR_SOURCE, 'utf16le')
  .toString('base64')


export function validateTestEnvironment(environment = process.env) {
  const missing = REQUIRED_TEST_VARIABLES.filter(name => !environment[name])
  if (missing.length) {
    throw new Error(`Browser MySQL requires explicit variables: ${missing.join(', ')}`)
  }
  const port = Number(environment.TEST_MYSQL_PORT)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('TEST_MYSQL_PORT must be an integer between 1 and 65535')
  }
}


export function assertDatabaseName(databaseName) {
  if (typeof databaseName !== 'string' || !DISPOSABLE_DATABASE.test(databaseName)) {
    throw new Error(`Refusing non-disposable browser database: ${String(databaseName)}`)
  }
}


export function createDatabaseName(uuidFactory = randomUUID) {
  const databaseName = `novel_creator_test_${uuidFactory().replaceAll('-', '').toLowerCase()}`
  assertDatabaseName(databaseName)
  return databaseName
}


function normalizedPathIdentity(value) {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}


export function assertOwnedRoot(ownedRoot, prefix) {
  if (typeof prefix !== 'string' || !/^novel-creator-[a-z0-9-]+-$/u.test(prefix)) {
    throw new TypeError('owned root prefix is invalid')
  }
  const root = path.resolve(ownedRoot)
  const stats = lstatSync(root)
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new Error('owned root is not a real directory')
  }
  if (
    !path.basename(root).startsWith(prefix)
    || normalizedPathIdentity(path.dirname(realpathSync(root)))
      !== normalizedPathIdentity(realpathSync(os.tmpdir()))
  ) {
    throw new Error('owned root is outside its temporary namespace')
  }
  return root
}


export function createOwnedRoot(prefix) {
  const root = mkdtempSync(path.join(os.tmpdir(), prefix))
  return assertOwnedRoot(root, prefix)
}


export function removeOwnedRoot(root, prefix) {
  rmSync(assertOwnedRoot(root, prefix), { recursive: true })
}


export function reserveLocalPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    const onError = error => reject(error)
    server.unref()
    server.once('error', onError)
    server.listen({ host: '127.0.0.1', port: 0, exclusive: true }, () => {
      server.off('error', onError)
      const address = server.address()
      if (!address || typeof address === 'string') {
        server.close()
        reject(new Error('local port reservation did not return a TCP port'))
        return
      }
      let released = false
      resolve({
        port: address.port,
        release() {
          if (released) return Promise.resolve()
          released = true
          return new Promise((releaseResolve, releaseReject) => {
            server.close(error => {
              if (error) releaseReject(error)
              else releaseResolve()
            })
          })
        },
      })
    })
  })
}


export async function waitForOwnedUrl(url, {
  expectedNonce,
  fetchImpl = fetch,
  timeoutMs = 30_000,
  intervalMs = 100,
  signal,
} = {}) {
  if (typeof expectedNonce !== 'string' || expectedNonce.length === 0) {
    throw new TypeError('owned browser health requires a non-empty nonce')
  }
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (signal?.aborted) throw abortReason(signal)
    const remainingMs = deadline - Date.now()
    const requestController = new AbortController()
    const forwardAbort = () => requestController.abort(abortReason(signal))
    signal?.addEventListener('abort', forwardAbort, { once: true })
    const requestTimer = setTimeout(
      () => requestController.abort(new Error('owned health request timed out')),
      Math.max(1, Math.min(remainingMs, 2_000)),
    )
    try {
      const response = await awaitAbortable(
        () => fetchImpl(url, { signal: requestController.signal }),
        requestController.signal,
      )
      if (response.ok) {
        const body = await awaitAbortable(
          () => response.json(),
          requestController.signal,
        )
        if (body?.browserRunNonce === expectedNonce) return
      }
    } catch {
      if (signal?.aborted) throw abortReason(signal)
      // A refused connection is expected while the owned process starts.
    } finally {
      clearTimeout(requestTimer)
      signal?.removeEventListener('abort', forwardAbort)
    }
    const sleepMs = Math.min(intervalMs, Math.max(0, deadline - Date.now()))
    if (sleepMs > 0) await sleepWithAbort(sleepMs, signal)
  }
  throw new Error('timed out waiting for runner-owned browser server to prove ownership')
}


function abortReason(signal) {
  if (signal?.reason instanceof Error) return signal.reason
  const error = new Error('operation aborted')
  error.name = 'AbortError'
  return error
}


function awaitAbortable(operation, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(abortReason(signal))
      return
    }
    let settled = false
    const finish = callback => value => {
      if (settled) return
      settled = true
      signal.removeEventListener('abort', onAbort)
      callback(value)
    }
    const onAbort = () => finish(reject)(abortReason(signal))
    signal.addEventListener('abort', onAbort, { once: true })
    Promise.resolve().then(operation).then(finish(resolve), finish(reject))
  })
}


function sleepWithAbort(timeoutMs, signal) {
  if (!signal) return new Promise(resolve => setTimeout(resolve, timeoutMs))
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(abortReason(signal))
      return
    }
    const onAbort = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', onAbort)
      reject(abortReason(signal))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, timeoutMs)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}


export function ownedChildOptions(options, platform = process.platform) {
  return {
    ...options,
    shell: false,
    windowsHide: true,
    detached: platform !== 'win32',
  }
}


export function spawnOwnedChild(command, args, options, {
  platform = process.platform,
  spawnImpl = spawn,
} = {}) {
  if (typeof command !== 'string' || command.length === 0) {
    throw new TypeError('runner-owned command must be a non-empty string')
  }
  if (!Array.isArray(args) || args.some(argument => typeof argument !== 'string')) {
    throw new TypeError('runner-owned arguments must be strings')
  }
  if (platform !== 'win32') {
    return spawnImpl(command, args, ownedChildOptions(options, platform))
  }

  const configuration = JSON.stringify({
    command,
    arguments: args,
    cwd: options?.cwd || process.cwd(),
  })
  const configuredStdio = Array.isArray(options?.stdio)
    ? options.stdio
    : ['ignore', 'pipe', 'pipe']
  const supervisor = spawnImpl(
    'powershell.exe',
    [
      '-NoLogo',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy',
      'Bypass',
      '-EncodedCommand',
      WINDOWS_JOB_SUPERVISOR_ENCODED,
    ],
    ownedChildOptions({
      ...options,
      stdio: ['pipe', configuredStdio[1], configuredStdio[2]],
    }, 'win32'),
  )
  supervisor.stdin?.on?.('error', () => {
    // Child lifecycle listeners own the corresponding supervisor failure.
  })
  supervisor.stdin?.end?.(configuration)
  return supervisor
}


export function processFailure(label, result, sensitiveValues) {
  const errors = []
  if (result?.error) {
    errors.push(new Error(`${label} process failed to start`, { cause: result.error }))
  } else if (result?.status !== 0) {
    errors.push(new Error(`${label} process exited with status ${String(result?.status)}`))
  }
  if (result?.logObserver) {
    try {
      const scan = result.logObserver.finish(sensitiveValues)
      if (scan.matchCount !== 0) {
        errors.push(new Error(`${label} process log contained runtime-sensitive values`))
      }
    } catch (error) {
      errors.push(new Error(`${label} process log scan failed`, { cause: error }))
    }
  }
  if (errors.length === 1) return errors[0]
  if (errors.length > 1) {
    return new AggregateError(errors, `${label} process and log scan failed`)
  }
  return null
}


function waitWithTimeout(promise, timeoutMs, message) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), timeoutMs)
    Promise.resolve(promise).then(
      value => {
        clearTimeout(timer)
        resolve(value)
      },
      error => {
        clearTimeout(timer)
        reject(error)
      },
    )
  })
}


const childLifecycles = new WeakMap()


function trackOwnedChildLifecycle(child, label = 'owned') {
  if (!child || (typeof child !== 'object' && typeof child !== 'function')) {
    throw new TypeError('runner-owned child must be an object')
  }
  const existing = childLifecycles.get(child)
  if (existing) return existing
  if (typeof child.once !== 'function') {
    const state = {
      child,
      label,
      supportsEvents: false,
      stopRequested: false,
      earlyFailure: null,
      earlyFailureObserved: false,
      closeSeen: true,
      closePromise: Promise.resolve(),
      failurePromise: new Promise(() => {}),
    }
    childLifecycles.set(child, state)
    return state
  }

  let resolveClose
  let resolveFailure
  const state = {
    child,
    label,
    supportsEvents: true,
    stopRequested: false,
    earlyFailure: null,
    earlyFailureObserved: false,
    childError: null,
    exitSeen: false,
    closeSeen: false,
    exitCode: null,
    signal: null,
    closePromise: new Promise(resolve => { resolveClose = resolve }),
    failurePromise: new Promise(resolve => { resolveFailure = resolve }),
  }
  let failureReported = false
  const reportFailure = error => {
    if (state.stopRequested || failureReported) return
    failureReported = true
    state.earlyFailure = error
    resolveFailure(error)
  }
  child.once('error', error => {
    state.childError = error
    reportFailure(new Error(`${label} process emitted an error before completion`))
  })
  child.once('exit', (code, signal) => {
    state.exitSeen = true
    state.exitCode = code
    state.signal = signal
    reportFailure(new Error(
      `${label} process exited before completion with status ${String(code)}`,
    ))
  })
  child.once('close', (code, signal) => {
    state.closeSeen = true
    state.exitCode ??= code
    state.signal ??= signal
    if (!state.exitSeen && !state.childError) {
      reportFailure(new Error(
        `${label} process closed before completion with status ${String(code)}`,
      ))
    }
    resolveClose()
  })
  childLifecycles.set(child, state)
  return state
}


function detectEarlyLifecycleFailure(state) {
  if (!state || state.stopRequested) return state?.earlyFailure || null
  if (!state.supportsEvents) return null
  if (state.earlyFailure) return state.earlyFailure
  if (state.childError) {
    state.earlyFailure = new Error(`${state.label} process emitted an error before completion`)
    return state.earlyFailure
  }
  const childExitCode = state.child?.exitCode
  if (
    !state.exitSeen
    && !state.closeSeen
    && (childExitCode === null || childExitCode === undefined)
  ) {
    return null
  }
  const status = state.exitCode ?? childExitCode
  state.earlyFailure = new Error(
    `${state.label} process exited before completion with status ${String(status)}`,
  )
  return state.earlyFailure
}


function markStopRequested(state) {
  const earlyFailure = detectEarlyLifecycleFailure(state)
  state.stopRequested = true
  return earlyFailure
}


function waitForCloseAndDrain(state, timeoutMs) {
  if (!state?.supportsEvents || state.closeSeen) return Promise.resolve()
  return waitWithTimeout(
    state.closePromise,
    timeoutMs,
    `${state.label} process close/stdout/stderr drain timed out`,
  )
}


function validateOwnedPid(child) {
  if (!Number.isSafeInteger(child?.pid) || child.pid <= 0) {
    throw new TypeError('runner-owned PID must be a positive integer')
  }
  return child.pid
}


function runWindowsTreeTerminator(pid, {
  spawnImpl,
  timeoutMs,
}) {
  return new Promise((resolve, reject) => {
    let terminator
    try {
      terminator = spawnImpl(
        'taskkill',
        ['/PID', String(pid), '/T', '/F'],
        {
          shell: false,
          windowsHide: true,
          stdio: 'ignore',
        },
      )
    } catch {
      reject(new Error('owned Windows process-tree terminator failed to start'))
      return
    }
    let settled = false
    const finish = callback => value => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      callback(value)
    }
    const timer = setTimeout(() => {
      try {
        terminator?.kill?.('SIGKILL')
      } catch {
        // The bounded timeout remains the primary, secret-safe failure.
      }
      finish(reject)(new Error('owned Windows process-tree terminator timed out'))
    }, timeoutMs)
    terminator.once('error', () => {
      finish(reject)(new Error('owned Windows process-tree terminator emitted an error'))
    })
    terminator.once('close', status => {
      if (status === 0) finish(resolve)()
      else finish(reject)(new Error('owned Windows process-tree terminator failed'))
    })
  })
}


export async function terminateOwnedProcessTree(child, {
  platform = process.platform,
  spawnImpl = spawn,
  killImpl = process.kill,
  timeoutMs = DEFAULT_RUNNER_DEADLINES.stopMs,
} = {}) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new TypeError('owned process-tree timeout must be a positive finite number')
  }
  const state = trackOwnedChildLifecycle(child, child?.label || 'owned')
  if (state.closeSeen) return
  const pid = validateOwnedPid(child)
  state.stopRequested = true

  if (platform === 'win32') {
    const errors = []
    try {
      await runWindowsTreeTerminator(pid, { spawnImpl, timeoutMs })
    } catch (error) {
      errors.push(error)
    }
    try {
      await waitForCloseAndDrain(state, timeoutMs)
    } catch (error) {
      errors.push(error)
    }
    if (errors.length === 1) throw errors[0]
    if (errors.length > 1) {
      throw new AggregateError(errors, 'owned Windows process-tree stop failed')
    }
    return
  }

  let gracefulError = null
  try {
    killImpl(-pid, 'SIGTERM')
    await waitForCloseAndDrain(state, timeoutMs)
    return
  } catch (error) {
    gracefulError = error
  }
  try {
    killImpl(-pid, 'SIGKILL')
    await waitForCloseAndDrain(state, timeoutMs)
  } catch (forcedError) {
    throw new AggregateError(
      [gracefulError, forcedError],
      'owned POSIX process-group graceful and forced stop failed',
    )
  }
}


export async function runOwnedCommand(command, args, options, {
  label = 'owned command',
  sensitiveValues = [],
  signal,
  stopTimeoutMs = DEFAULT_RUNNER_DEADLINES.stopMs,
  spawnOwnedChildImpl = spawnOwnedChild,
  terminateOwnedProcessTreeImpl = terminateOwnedProcessTree,
} = {}) {
  let child
  try {
    child = spawnOwnedChildImpl(command, args, options)
  } catch {
    return {
      status: null,
      error: new Error(`${label} process failed to start`),
      logObserver: null,
    }
  }
  const state = trackOwnedChildLifecycle(child, label)
  const logObserver = createServerLogObserver(child, { sensitiveValues })
  let stopPromise = null
  let resolveStopOutcome
  const stopOutcome = new Promise(resolve => { resolveStopOutcome = resolve })
  const requestStop = () => {
    if (stopPromise) return
    state.stopRequested = true
    stopPromise = terminateOwnedProcessTreeImpl(child, { timeoutMs: stopTimeoutMs })
    stopPromise.then(
      () => resolveStopOutcome({ kind: 'stopped' }),
      error => resolveStopOutcome({ kind: 'stop-error', error }),
    )
  }
  if (signal?.aborted) requestStop()
  else signal?.addEventListener('abort', requestStop, { once: true })
  const lifecycleErrors = []
  try {
    await Promise.race([
      state.closePromise.then(() => ({ kind: 'closed' })),
      stopOutcome,
    ])
  } finally {
    signal?.removeEventListener('abort', requestStop)
  }
  if (stopPromise) {
    try {
      await stopPromise
    } catch (error) {
      lifecycleErrors.push(error)
    }
  }
  if (state.childError) {
    lifecycleErrors.push(new Error(`${label} process failed to start`))
  }
  let error = null
  if (lifecycleErrors.length === 1) error = lifecycleErrors[0]
  if (lifecycleErrors.length > 1) {
    error = new AggregateError(lifecycleErrors, `${label} process lifecycle failed`)
  }
  return {
    status: state.exitCode ?? child.exitCode,
    error,
    logObserver: state.closeSeen ? logObserver : null,
  }
}


export const defaultProcessRunner = {
  run: runOwnedCommand,
  start(command, args, options, { label = 'owned' } = {}) {
    const child = spawnOwnedChild(command, args, options)
    trackOwnedChildLifecycle(child, label)
    return child
  },
  async stop(child, { timeoutMs = DEFAULT_RUNNER_DEADLINES.stopMs } = {}) {
    if (!child) return
    await terminateOwnedProcessTree(child, { timeoutMs })
  },
}


function requireProcessRunner(processRunner) {
  for (const name of ['run', 'start', 'stop']) {
    if (typeof processRunner?.[name] !== 'function') {
      throw new TypeError(`owned process runner requires ${name}`)
    }
  }
  return processRunner
}


function positiveDeadline(value, label) {
  if (!Number.isFinite(value) || value <= 0) {
    throw new TypeError(`${label} must be a positive finite number`)
  }
  return value
}


export async function runBoundedOwnedCommand(command, args, options, {
  label = 'owned command',
  sensitiveValues = [],
  timeoutMs = DEFAULT_RUNNER_DEADLINES.browserMs,
  settleMs = DEFAULT_RUNNER_DEADLINES.settleMs,
  stopTimeoutMs = DEFAULT_RUNNER_DEADLINES.stopMs,
  processRunner = defaultProcessRunner,
  states = [],
  signal,
} = {}) {
  positiveDeadline(timeoutMs, 'owned command timeout')
  positiveDeadline(settleMs, 'owned command settle timeout')
  positiveDeadline(stopTimeoutMs, 'owned command stop timeout')
  const runner = requireProcessRunner(processRunner)
  const lifecycleStates = states.map(state => state?.state || state)
  const result = await runBoundedOperation(
    label,
    timeoutMs,
    settleMs,
    signal => runner.run(command, args, options, {
      label,
      sensitiveValues,
      signal,
      stopTimeoutMs,
    }),
    lifecycleStates,
    signal,
  )
  const failure = processFailure(label, result, sensitiveValues)
  if (failure) throw failure
  return result
}


export function startOwnedServer(command, args, options, {
  label = 'owned server',
  sensitiveValues = [],
  processRunner = defaultProcessRunner,
  serverLogObserverFactory = createServerLogObserver,
} = {}) {
  const runner = requireProcessRunner(processRunner)
  if (typeof serverLogObserverFactory !== 'function') {
    throw new TypeError('owned server requires a log observer factory')
  }
  const child = runner.start(command, args, options, { label })
  const state = trackOwnedChildLifecycle(child, label)
  return {
    child,
    label,
    observer: serverLogObserverFactory(child, { sensitiveValues }),
    processRunner: runner,
    sensitiveValues: [...sensitiveValues],
    state,
  }
}


export async function waitForOwnedServer(server, url, {
  expectedNonce,
  timeoutMs = DEFAULT_RUNNER_DEADLINES.healthMs,
  settleMs = Math.min(DEFAULT_RUNNER_DEADLINES.settleMs, timeoutMs),
  waitForUrlImpl = waitForOwnedUrl,
  states = [server],
  signal,
} = {}) {
  positiveDeadline(timeoutMs, 'owned server health timeout')
  positiveDeadline(settleMs, 'owned server health settle timeout')
  if (typeof waitForUrlImpl !== 'function') {
    throw new TypeError('owned server requires a health waiter')
  }
  const lifecycleStates = states.map(item => (
    item?.state || trackOwnedChildLifecycle(item?.child, item?.label)
  ))
  return runBoundedOperation(
    `${server?.label || 'owned server'} health`,
    timeoutMs,
    settleMs,
    signal => waitForUrlImpl(url, {
      expectedNonce,
      timeoutMs,
      signal,
    }),
    lifecycleStates,
    signal,
  )
}


function ownedServerObservers(server) {
  const extras = [
    ...(Array.isArray(server?.auditors) ? server.auditors : []),
    server?.accessObserver,
  ].filter(Boolean)
  return {
    primary: server?.observer || null,
    extras: [...new Set(extras)],
  }
}


export function scanOwnedServer(server, {
  sensitiveValues = server?.sensitiveValues || [],
} = {}) {
  const errors = []
  const { primary, extras } = ownedServerObservers(server)
  if (primary) {
    try {
      const scan = primary.finish(sensitiveValues)
      if (scan?.matchCount !== 0) {
        errors.push(new Error(
          `${server?.label || 'owned server'} log contained runtime-sensitive values`,
        ))
      }
    } catch (error) {
      errors.push(error)
    }
  }
  for (const observer of extras) {
    try { observer.finish() } catch (error) { errors.push(error) }
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(
      errors,
      `${server?.label || 'owned server'} log audits failed`,
    )
  }
  return { matchCount: 0 }
}


export async function stopOwnedServer(server, {
  sensitiveValues = server?.sensitiveValues || [],
  timeoutMs = DEFAULT_RUNNER_DEADLINES.stopMs,
} = {}) {
  positiveDeadline(timeoutMs, 'owned server stop timeout')
  const errors = []
  const state = server?.state || trackOwnedChildLifecycle(server?.child, server?.label)
  const earlyFailure = markStopRequested(state)
  if (earlyFailure && !state.earlyFailureObserved) errors.push(earlyFailure)
  try {
    await server.processRunner.stop(server.child, { timeoutMs })
  } catch (error) {
    errors.push(error)
  }
  try {
    await waitForCloseAndDrain(state, timeoutMs)
  } catch (error) {
    errors.push(error)
  }
  try {
    scanOwnedServer(server, { sensitiveValues })
  } catch (error) {
    errors.push(error)
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(
      errors,
      `${server?.label || 'owned server'} stop, drain, or log audit failed`,
    )
  }
}


export function normalizedDeadlines(deadlines = {}) {
  const result = { ...DEFAULT_RUNNER_DEADLINES, ...deadlines }
  for (const [name, value] of Object.entries(result)) {
    if (!Number.isFinite(value) || value <= 0) {
      throw new TypeError(`${name} deadline must be a positive finite number`)
    }
  }
  return result
}


async function settleAfterAbort(operationOutcome, primaryError, settleMs) {
  let timer
  const settled = await Promise.race([
    operationOutcome,
    new Promise(resolve => {
      timer = setTimeout(() => resolve({ kind: 'settle-timeout' }), settleMs)
    }),
  ])
  clearTimeout(timer)
  if (
    settled.kind === 'operation'
    && settled.error
    && settled.error !== primaryError
    && settled.error?.name !== 'AbortError'
  ) {
    throw new AggregateError(
      [primaryError, settled.error],
      'runner operation and bounded abort both failed',
    )
  }
  throw primaryError
}


function findEarlyServiceFailure(states) {
  for (const state of states) {
    const error = detectEarlyLifecycleFailure(state)
    if (!error) continue
    state.earlyFailureObserved = true
    return error
  }
  return null
}


export async function runBoundedOperation(
  label, timeoutMs, settleMs, operation, states = [], externalSignal,
) {
  const controller = new AbortController()
  const operationOutcome = Promise.resolve()
    .then(() => operation(controller.signal))
    .then(
      value => ({ kind: 'operation', value }),
      error => ({ kind: 'operation', error }),
    )
  let deadlineTimer
  const deadlineOutcome = new Promise(resolve => {
    deadlineTimer = setTimeout(
      () => resolve({
        kind: 'deadline',
        error: new Error(`${label} deadline exceeded`),
      }),
      timeoutMs,
    )
  })
  const contenders = [operationOutcome, deadlineOutcome]
  let removeExternalAbort = () => {}
  if (externalSignal) {
    contenders.push(new Promise(resolve => {
      const onAbort = () => resolve({ kind: 'external', error: abortReason(externalSignal) })
      if (externalSignal.aborted) onAbort()
      else {
        externalSignal.addEventListener('abort', onAbort, { once: true })
        removeExternalAbort = () => externalSignal.removeEventListener('abort', onAbort)
      }
    }))
  }
  if (states.length > 0) {
    contenders.push(Promise.race(
      states.map(state => state.failurePromise.then(error => ({
        kind: 'service',
        state,
        error,
      }))),
    ))
  }
  const outcome = await Promise.race(contenders)
  clearTimeout(deadlineTimer)
  removeExternalAbort()
  if (outcome.kind === 'operation') {
    if (outcome.error) throw outcome.error
    const earlyFailure = findEarlyServiceFailure(states)
    if (earlyFailure) {
      controller.abort(earlyFailure)
      await settleAfterAbort(operationOutcome, earlyFailure, settleMs)
    }
    return outcome.value
  }
  if (outcome.kind === 'service') outcome.state.earlyFailureObserved = true
  controller.abort(outcome.error)
  await settleAfterAbort(operationOutcome, outcome.error, settleMs)
}



function requireHandler(name, handler) {
  if (typeof handler !== 'function') {
    throw new TypeError(`product lifecycle requires ${name}`)
  }
  return handler
}


export async function runOwnedProductLifecycle({
  body,
  stopServer,
  releaseReservation,
  dropDatabase,
  removeRoot,
}) {
  const runBody = requireHandler('body', body)
  const stop = requireHandler('stopServer', stopServer)
  const release = requireHandler('releaseReservation', releaseReservation)
  const drop = requireHandler('dropDatabase', dropDatabase)
  const remove = requireHandler('removeRoot', removeRoot)
  const servers = []
  const reservations = []
  const releasedReservations = new Set()
  let database
  let root
  let result
  const errors = []
  const lifecycle = Object.freeze({
    registerServer(server) {
      servers.push(server)
      return server
    },
    registerReservation(reservation) {
      reservations.push(reservation)
      return reservation
    },
    setDatabase(value) {
      database = value
      return value
    },
    setRoot(value) {
      root = value
      return value
    },
    async releaseReservation(reservation) {
      if (releasedReservations.has(reservation)) return
      await release(reservation)
      releasedReservations.add(reservation)
    },
  })
  try {
    result = await runBody(lifecycle)
  } catch (error) {
    errors.push(error)
  }
  for (const server of [...servers].reverse()) {
    try { await stop(server) } catch (error) { errors.push(error) }
  }
  for (const reservation of reservations) {
    try { await lifecycle.releaseReservation(reservation) } catch (error) { errors.push(error) }
  }
  if (database !== undefined) {
    try { await drop(database) } catch (error) { errors.push(error) }
  }
  if (root !== undefined) {
    try { await remove(root) } catch (error) { errors.push(error) }
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(errors, 'product body and cleanup failed')
  }
  return result
}


export const runPhase2BLifecycle = runOwnedProductLifecycle
