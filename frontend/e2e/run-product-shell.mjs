import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  assertDatabaseName as assertProductShellDatabaseName,
  createDatabaseName as createProductShellDatabaseName,
  REQUIRED_TEST_VARIABLES,
  reserveLocalPort,
  validateTestEnvironment,
  waitForOwnedUrl,
} from './run-milestone2.mjs'
import { createServerLogObserver } from './server-log-observer.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'


export {
  assertProductShellDatabaseName,
  createProductShellDatabaseName,
  REQUIRED_TEST_VARIABLES,
}

export const FORMAL_SPECS = Object.freeze([
  'e2e/product-shell-lifecycle.spec.ts',
])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
export const PRODUCT_SHELL_SECRET_SENTINEL = 'product-shell-browser-secret-sentinel'
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


export function validateSpecs(specs) {
  if (
    !Array.isArray(specs)
    || specs.length !== FORMAL_SPECS.length
    || specs.some((spec, index) => spec !== FORMAL_SPECS[index])
  ) {
    throw new Error('Product-shell browser requires the exact formal spec path')
  }
  return [...FORMAL_SPECS]
}


export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList)) {
    throw new TypeError('Product-shell browser CLI arguments must be an array')
  }
  if (argumentsList.length !== 0) {
    throw new Error('Product-shell browser runner does not accept spec paths')
  }
  return [...FORMAL_SPECS]
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


function childOptions(cwd, env) {
  return ownedChildOptions({
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}


function allowlistedBaseEnvironment(environment) {
  return Object.fromEntries(
    BASE_ENV_ALLOWLIST
      .filter(name => Object.hasOwn(environment, name))
      .map(name => [name, environment[name]]),
  )
}


function buildProcessEnvironments(environment, databaseName, backendUrl, viteUrl, nonce) {
  validateTestEnvironment(environment)
  assertProductShellDatabaseName(databaseName)
  const base = allowlistedBaseEnvironment(environment)
  const prepare = {
    ...base,
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
    TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
    TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
  }
  const backend = {
    ...base,
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName,
    M2_BROWSER_RUN_NONCE: nonce,
  }
  const vite = {
    ...base,
    M2_BROWSER_RUN_NONCE: nonce,
    VITE_API_BASE_URL: `${backendUrl}/api`,
  }
  const browser = {
    ...base,
    PLAYWRIGHT_BASE_URL: viteUrl,
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_SECRET_SENTINEL: PRODUCT_SHELL_SECRET_SENTINEL,
  }
  return {
    prepare,
    backend,
    vite,
    browser,
    sensitiveController: {
      MYSQL_HOST: environment.TEST_MYSQL_HOST,
      MYSQL_PORT: environment.TEST_MYSQL_PORT,
      MYSQL_USER: environment.TEST_MYSQL_USER,
      MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
      MYSQL_DB: databaseName,
      BROWSER_TEST_DATABASE: databaseName,
      BROWSER_SECRET_SENTINEL: PRODUCT_SHELL_SECRET_SENTINEL,
    },
  }
}


function processFailure(label, result, sensitiveValues) {
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


async function runOwnedCommand(command, args, options, {
  label = 'owned command',
  sensitiveValues = [],
  signal,
  stopTimeoutMs = DEFAULT_RUNNER_DEADLINES.stopMs,
} = {}) {
  let child
  try {
    child = spawnOwnedChild(command, args, options)
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
    stopPromise = terminateOwnedProcessTree(child, { timeoutMs: stopTimeoutMs })
    stopPromise.then(
      () => resolveStopOutcome({ kind: 'stopped' }),
      error => resolveStopOutcome({ kind: 'stop-error', error }),
    )
  }
  if (signal?.aborted) requestStop()
  else signal?.addEventListener('abort', requestStop, { once: true })
  const lifecycleErrors = []
  try {
    const outcome = await Promise.race([
      state.closePromise.then(() => ({ kind: 'closed' })),
      stopOutcome,
    ])
    if (outcome.kind === 'stop-error') lifecycleErrors.push(outcome.error)
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


const defaultProcessRunner = {
  run: runOwnedCommand,
  start(command, args, options, { label = 'owned' } = {}) {
    const child = spawnOwnedChild(command, args, options)
    trackOwnedChildLifecycle(child, label)
    return child
  },
  async stop(child) {
    if (!child) return
    await terminateOwnedProcessTree(child)
  },
}


function normalizedDeadlines(deadlines = {}) {
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


async function runBoundedOperation(label, timeoutMs, settleMs, operation, states = []) {
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


async function runOneSpec({
  spec,
  environment,
  databaseNameFactory,
  portReservationFactory,
  processRunner,
  waitForUrlImpl,
  serverLogObserverFactory,
  nonceFactory,
  deadlines,
}) {
  const databaseName = databaseNameFactory()
  assertProductShellDatabaseName(databaseName)
  const nonce = nonceFactory()
  if (
    typeof nonce !== 'string'
    || nonce.length === 0
    || !/^[A-Za-z0-9_-]+$/u.test(nonce)
  ) {
    throw new TypeError('Product-shell browser nonce must be a path-safe string')
  }

  const reservations = []
  const released = new Set()
  const bodyErrors = []
  const cleanupErrors = []
  const serverErrors = []
  const ownedServers = []
  let databaseLifecycleStarted = false
  let processEnvironments
  let sensitiveValues = []

  const releaseReservation = async reservation => {
    if (!reservation || released.has(reservation)) return
    released.add(reservation)
    await reservation.release()
  }

  try {
    const backendReservation = await portReservationFactory()
    reservations.push(backendReservation)
    const viteReservation = await portReservationFactory()
    reservations.push(viteReservation)
    for (const reservation of reservations) {
      if (
        !Number.isInteger(reservation?.port)
        || reservation.port < 1
        || reservation.port > 65535
        || typeof reservation.release !== 'function'
      ) {
        throw new TypeError('Product-shell browser port reservation is invalid')
      }
    }
    if (backendReservation.port === viteReservation.port) {
      throw new Error('Product-shell backend and Vite ports must be distinct')
    }

    const backendUrl = `http://127.0.0.1:${backendReservation.port}`
    const viteUrl = `http://127.0.0.1:${viteReservation.port}`
    processEnvironments = buildProcessEnvironments(
      environment,
      databaseName,
      backendUrl,
      viteUrl,
      nonce,
    )
    sensitiveValues = runtimeSensitiveValues(processEnvironments.sensitiveController)
    const python = environment.PYTHON || 'python'
    const prepareArgs = [
      '-m',
      'backend.scripts.prepare_product_shell_browser_db',
      '--database',
      databaseName,
    ]
    const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
    const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')

    databaseLifecycleStarted = true
    const preparation = await runBoundedOperation(
      'prepare',
      deadlines.prepareMs,
      deadlines.settleMs,
      signal => processRunner.run(
        python,
        prepareArgs,
        childOptions(repositoryRoot, processEnvironments.prepare),
        {
          label: 'database preparation',
          sensitiveValues,
          signal,
          stopTimeoutMs: deadlines.stopMs,
        },
      ),
    )
    const preparationError = processFailure(
      'database preparation',
      preparation,
      sensitiveValues,
    )
    if (preparationError) throw preparationError

    await releaseReservation(backendReservation)
    const backend = processRunner.start(
      python,
      [
        '-m',
        'uvicorn',
        'backend.main:app',
        '--host',
        '127.0.0.1',
        '--port',
        String(backendReservation.port),
      ],
      childOptions(repositoryRoot, processEnvironments.backend),
      { label: 'backend' },
    )
    const backendState = trackOwnedChildLifecycle(backend, 'backend')
    ownedServers.push({
      child: backend,
      state: backendState,
      observer: serverLogObserverFactory(backend, { sensitiveValues }),
    })

    await releaseReservation(viteReservation)
    const vite = processRunner.start(
      process.execPath,
      [
        viteCli,
        '--host',
        '127.0.0.1',
        '--port',
        String(viteReservation.port),
        '--strictPort',
      ],
      childOptions(frontendRoot, processEnvironments.vite),
      { label: 'vite' },
    )
    const viteState = trackOwnedChildLifecycle(vite, 'vite')
    ownedServers.push({
      child: vite,
      state: viteState,
      observer: serverLogObserverFactory(vite, { sensitiveValues }),
    })
    const serviceStates = ownedServers.map(server => server.state)

    await runBoundedOperation(
      'backend health',
      deadlines.healthMs,
      deadlines.settleMs,
      signal => waitForUrlImpl(`${backendUrl}/api/health`, {
        expectedNonce: nonce,
        signal,
      }),
      serviceStates,
    )
    await runBoundedOperation(
      'Vite health',
      deadlines.healthMs,
      deadlines.settleMs,
      signal => waitForUrlImpl(`${viteUrl}/__m2-browser-owner`, {
        expectedNonce: nonce,
        signal,
      }),
      serviceStates,
    )

    const browser = await runBoundedOperation(
      'browser',
      deadlines.browserMs,
      deadlines.settleMs,
      signal => processRunner.run(
        process.execPath,
        [
          playwrightCli,
          'test',
          spec,
          '--config',
          'playwright.product-shell.config.ts',
        ],
        childOptions(frontendRoot, processEnvironments.browser),
        {
          label: 'browser test',
          sensitiveValues,
          signal,
          stopTimeoutMs: deadlines.stopMs,
        },
      ),
      serviceStates,
    )
    const browserError = processFailure('browser test', browser, sensitiveValues)
    if (browserError) throw browserError
  } catch (error) {
    bodyErrors.push(error)
  } finally {
    for (const server of [...ownedServers].reverse()) {
      const earlyFailure = markStopRequested(server.state)
      if (earlyFailure && !server.state.earlyFailureObserved) {
        server.state.earlyFailureObserved = true
        serverErrors.push(earlyFailure)
      }
      try {
        await processRunner.stop(server.child)
      } catch (error) {
        serverErrors.push(error)
      }
      try {
        await waitForCloseAndDrain(server.state, deadlines.stopMs)
      } catch (error) {
        serverErrors.push(error)
      }
      try {
        const scan = server.observer.finish(sensitiveValues)
        if (scan.matchCount !== 0) {
          serverErrors.push(
            new Error('owned server log contained runtime-sensitive values'),
          )
        }
      } catch (error) {
        serverErrors.push(error)
      }
    }
    for (const reservation of reservations) {
      try {
        await releaseReservation(reservation)
      } catch (error) {
        serverErrors.push(error)
      }
    }
    if (databaseLifecycleStarted) {
      try {
        const python = environment.PYTHON || 'python'
        const cleanup = await runBoundedOperation(
          'cleanup',
          deadlines.cleanupMs,
          deadlines.settleMs,
          signal => processRunner.run(
            python,
            [
              '-m',
              'backend.scripts.prepare_product_shell_browser_db',
              '--database',
              databaseName,
              '--drop',
            ],
            childOptions(repositoryRoot, processEnvironments.prepare),
            {
              label: 'database cleanup',
              sensitiveValues,
              signal,
              stopTimeoutMs: deadlines.stopMs,
            },
          ),
        )
        const cleanupError = processFailure(
          'database cleanup',
          cleanup,
          sensitiveValues,
        )
        if (cleanupError) cleanupErrors.push(cleanupError)
      } catch (error) {
        cleanupErrors.push(error)
      }
    }
  }

  const errors = [...bodyErrors]
  if (serverErrors.length === 1) errors.push(serverErrors[0])
  if (serverErrors.length > 1) {
    errors.push(new AggregateError(serverErrors, 'owned server stop or log scan failed'))
  }
  errors.push(...cleanupErrors)
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(errors, 'Product-shell browser body and cleanup failed')
  }
}


export async function runProductShell({
  specs = FORMAL_SPECS,
  environment = process.env,
  databaseNameFactory = createProductShellDatabaseName,
  portReservationFactory = reserveLocalPort,
  processRunner = defaultProcessRunner,
  waitForUrlImpl = waitForOwnedUrl,
  serverLogObserverFactory = createServerLogObserver,
  nonceFactory = randomUUID,
  deadlines,
} = {}) {
  validateTestEnvironment(environment)
  const formalSpecs = validateSpecs(specs)
  const runnerDeadlines = normalizedDeadlines(deadlines)
  const usedDatabases = new Set()
  const independentDatabaseNameFactory = () => {
    const databaseName = databaseNameFactory()
    assertProductShellDatabaseName(databaseName)
    if (usedDatabases.has(databaseName)) {
      throw new Error('Every product-shell spec requires a fresh disposable database')
    }
    usedDatabases.add(databaseName)
    return databaseName
  }
  for (const spec of formalSpecs) {
    await runOneSpec({
      spec,
      environment,
      databaseNameFactory: independentDatabaseNameFactory,
      portReservationFactory,
      processRunner,
      waitForUrlImpl,
      serverLogObserverFactory,
      nonceFactory,
      deadlines: runnerDeadlines,
    })
  }
  return 0
}


const isMain = process.argv[1]
  && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  let specs
  try {
    specs = resolveCommandLineSpecs(process.argv.slice(2))
  } catch {
    console.error('Product-shell browser runner does not accept spec paths.')
    process.exitCode = 2
  }
  if (specs) {
    runProductShell({ specs }).then(
      status => { process.exitCode = status },
      () => {
        console.error('Product-shell browser runner failed.')
        process.exitCode = 1
      },
    )
  }
}
