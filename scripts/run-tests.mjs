import { spawnSync } from 'node:child_process'
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  realpathSync,
  rmSync,
  rmdirSync,
} from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const suiteNames = [
  'unit',
  'frontend-unit',
  'integration',
  'browser',
  'm1-regression',
  'browser-product-shell',
  'browser-phase2a',
  'browser-phase2b',
  'browser-phase2c',
  'browser-phase3b',
  'browser-phase3c',
  'browser-phase2',
]
const integrationEnvironmentNames = [
  'TEST_MYSQL_HOST',
  'TEST_MYSQL_PORT',
  'TEST_MYSQL_USER',
  'TEST_MYSQL_PASSWORD',
]
const mysqlSuites = new Set([
  'integration',
  'browser',
  'browser-product-shell',
  'browser-phase2a',
  'browser-phase2b',
  'browser-phase2c',
  'browser-phase3b',
  'browser-phase3c',
  'browser-phase2',
])
export const pytestTempStages = Object.freeze({
  m1Regression: path.join('.codex-test-artifacts', 'pytest', 'm1-regression'),
  unitApi: path.join('.codex-test-artifacts', 'pytest', 'unit-api'),
  integration: path.join('.codex-test-artifacts', 'pytest', 'integration'),
})
const approvedPytestTempStages = new Set(Object.values(pytestTempStages))
const m1RegressionPythonFiles = [
  'backend/tests/unit/test_schema_manifest.py',
  'backend/tests/unit/test_schema_version.py',
  'backend/tests/unit/test_initialize_database.py',
  'backend/tests/unit/test_database_transaction.py',
  'backend/tests/unit/test_backend_launcher.py',
  'backend/tests/unit/test_main_lifespan.py',
  'backend/tests/unit/test_no_runtime_ddl.py',
  'backend/tests/unit/test_canon_identity.py',
  'backend/tests/unit/test_canon_conflicts.py',
  'backend/tests/unit/test_canon_revision.py',
  'backend/tests/unit/test_canon_idempotency.py',
  'backend/tests/unit/test_canon_rollback.py',
  'backend/tests/unit/test_canon_repository.py',
  'backend/tests/unit/test_projections.py',
  'backend/tests/unit/test_project_creation.py',
  'backend/tests/api/test_canon_routes.py',
  'backend/tests/api/test_product_routes.py',
  'backend/tests/api/test_provider_redaction.py',
  'backend/tests/api/test_public_domain_errors.py',
  'backend/tests/api/test_secret_error_redaction.py',
]
const m1RegressionNodeFiles = [
  'frontend/tests/unit/latestRequest.test.mjs',
  'frontend/tests/unit/m1Navigation.test.mjs',
  'frontend/tests/unit/providerRedaction.test.mjs',
  'frontend/tests/unit/testEntrypoint.test.mjs',
  'frontend/tests/unit/writerCoreApi.test.mjs',
]
const productShellBrowserFiles = [
  'frontend/e2e/product-shell-lifecycle.spec.ts',
]
const phase2aBrowserFiles = [
  'frontend/e2e/phase2a-assets-settings.spec.ts',
]
const phase2bBrowserFiles = [
  'frontend/e2e/phase2b-market-seeds.spec.ts',
]
const phase2cBrowserFiles = [
  'frontend/e2e/phase2c-contract.spec.ts',
]
const phase3bBrowserFiles = [
  'frontend/e2e/phase3b-volumes-plots.spec.ts',
]
const phase3cBrowserFiles = [
  'frontend/e2e/phase3c-story-blocks-outlines.spec.ts',
]
const phase2BrowserFiles = [
  'frontend/e2e/phase2-creative-foundation.spec.ts',
]

export function discoverTestFiles(directory) {
  return readdirSync(directory, { withFileTypes: true })
    .filter(entry => entry.isFile() && entry.name.endsWith('.test.mjs'))
    .map(entry => entry.name)
    .sort()
    .map(name => path.join(directory, name))
}

function createSuites(rootDirectory, environment) {
  const python = environment.PYTHON || 'python'
  const node = process.execPath
  const scriptTestDirectory = path.join(rootDirectory, 'scripts', 'tests')
  const frontendTestDirectory = path.join(rootDirectory, 'frontend', 'tests', 'unit')
  const scriptTests = discoverTestFiles(scriptTestDirectory)
  const frontendTests = discoverTestFiles(frontendTestDirectory)
  const absolute = files => files.map(file => path.join(rootDirectory, file))
  const m1PythonTests = absolute(m1RegressionPythonFiles)
  const m1NodeTests = absolute(m1RegressionNodeFiles)
  const productShellBrowserTests = absolute(productShellBrowserFiles)
  const phase2aBrowserTests = absolute(phase2aBrowserFiles)
  const phase2bBrowserTests = absolute(phase2bBrowserFiles)
  const phase2cBrowserTests = absolute(phase2cBrowserFiles)
  const phase3bBrowserTests = absolute(phase3bBrowserFiles)
  const phase3cBrowserTests = absolute(phase3cBrowserFiles)
  const phase2BrowserTests = absolute(phase2BrowserFiles)
  const retainedM1 = [
    [
      python,
      ['-m', 'pytest', ...m1RegressionPythonFiles, '-q', '--basetemp', pytestTempStages.m1Regression],
      pytestTempStages.m1Regression,
    ],
    [node, ['--test', ...m1RegressionNodeFiles]],
  ]
  const unit = [
    [
      python,
      [
        '-m',
        'pytest',
        'backend/tests/unit',
        'backend/tests/api',
        '-q',
        '--basetemp',
        pytestTempStages.unitApi,
      ],
      pytestTempStages.unitApi,
    ],
    [node, ['--test', ...scriptTests]],
    [node, ['--test', ...frontendTests]],
  ]
  const integration = [
    [
      python,
      [
        '-m',
        'pytest',
        'backend/tests/integration',
        '-m',
        'mysql',
        '-q',
        '--basetemp',
        pytestTempStages.integration,
      ],
      pytestTempStages.integration,
    ],
  ]
  const browserProductShell = [[node, ['frontend/e2e/run-product-shell.mjs']]]
  const browserPhase2A = [[node, ['frontend/e2e/run-phase2a.mjs']]]
  const browserPhase2B = [[node, ['frontend/e2e/run-phase2b.mjs']]]
  const browserPhase2C = [[node, ['frontend/e2e/run-phase2c.mjs']]]
  const browserPhase3B = [[node, ['frontend/e2e/run-phase3b.mjs']]]
  const browserPhase3C = [[node, ['frontend/e2e/run-phase3c.mjs']]]
  const browserPhase2 = [[node, ['frontend/e2e/run-phase2.mjs']]]

  return {
    commands: {
      unit,
      'frontend-unit': [[node, ['--test', ...frontendTests]]],
      integration,
      browser: [[node, ['frontend/e2e/run-milestone1.mjs']]],
      'm1-regression': retainedM1,
      'browser-product-shell': browserProductShell,
      'browser-phase2a': browserPhase2A,
      'browser-phase2b': browserPhase2B,
      'browser-phase2c': browserPhase2C,
      'browser-phase3b': browserPhase3B,
      'browser-phase3c': browserPhase3C,
      'browser-phase2': browserPhase2,
    },
    formalTests: {
      unit: [
        [scriptTestDirectory, scriptTests],
        [frontendTestDirectory, frontendTests],
      ],
      'frontend-unit': [[frontendTestDirectory, frontendTests]],
      'm1-regression': [
        ['M1 v1.1 Python regression', m1PythonTests],
        ['M1 v1.1 frontend regression', m1NodeTests],
      ],
      'browser-product-shell': [
        ['Product-shell Playwright spec', productShellBrowserTests],
      ],
      'browser-phase2a': [
        ['Phase 2A Playwright spec', phase2aBrowserTests],
      ],
      'browser-phase2b': [
        ['Phase 2B Playwright spec', phase2bBrowserTests],
      ],
      'browser-phase2c': [
        ['Phase 2C Playwright spec', phase2cBrowserTests],
      ],
      'browser-phase3b': [
        ['Phase 3B Playwright spec', phase3bBrowserTests],
      ],
      'browser-phase3c': [
        ['Phase 3C Playwright spec', phase3cBrowserTests],
      ],
      'browser-phase2': [
        ['Phase 2 Playwright spec', phase2BrowserTests],
      ],
    },
  }
}

export function usage() {
  return `usage: node scripts/run-tests.mjs <${suiteNames.join('|')}> [suite-name]\n`
}

function resolvePytestTemp(rootDirectory, stage) {
  if (!approvedPytestTempStages.has(stage)) {
    throw new Error('unapproved pytest temp stage')
  }

  const namespace = path.resolve(rootDirectory, '.codex-test-artifacts', 'pytest')
  const target = path.resolve(rootDirectory, stage)
  if (path.dirname(target) !== namespace) {
    throw new Error('pytest temp stage is outside its namespace')
  }
  return {
    artifactRoot: path.resolve(rootDirectory, '.codex-test-artifacts'),
    namespace,
    rootDirectory: path.resolve(rootDirectory),
    target,
  }
}

function lstatExisting(entry) {
  try {
    return lstatSync(entry)
  } catch (error) {
    if (error?.code === 'ENOENT') return null
    throw error
  }
}

function normalizedPathIdentity(entry) {
  const normalized = path.resolve(entry)
  return process.platform === 'win32' ? normalized.toLowerCase() : normalized
}

function assertDirectRealChild(entry, parentRealPath, stats, { requireDirectory = false } = {}) {
  if (stats.isSymbolicLink()) throw new Error('pytest temp path is a reparse point')
  if (requireDirectory && !stats.isDirectory()) {
    throw new Error('pytest temp path is not a directory')
  }

  const realEntry = realpathSync(entry)
  const expectedEntry = path.join(parentRealPath, path.basename(entry))
  if (normalizedPathIdentity(realEntry) !== normalizedPathIdentity(expectedEntry)) {
    throw new Error('pytest temp path does not belong to its real parent')
  }
  return realEntry
}

function inspectPytestTemp(rootDirectory, stage, { allowNamespaceFile = false } = {}) {
  const resolved = resolvePytestTemp(rootDirectory, stage)
  const rootRealPath = realpathSync(resolved.rootDirectory)
  const artifactStats = lstatExisting(resolved.artifactRoot)
  if (!artifactStats) return { ...resolved, artifactStats, rootRealPath }

  const artifactRealPath = assertDirectRealChild(
    resolved.artifactRoot,
    rootRealPath,
    artifactStats,
    { requireDirectory: true },
  )
  const namespaceStats = lstatExisting(resolved.namespace)
  if (!namespaceStats) {
    return { ...resolved, artifactRealPath, artifactStats, namespaceStats, rootRealPath }
  }

  const namespaceRealPath = assertDirectRealChild(
    resolved.namespace,
    artifactRealPath,
    namespaceStats,
    { requireDirectory: !allowNamespaceFile },
  )
  if (!namespaceStats.isDirectory() && !namespaceStats.isFile()) {
    throw new Error('pytest temp namespace is not a regular entry')
  }
  if (!namespaceStats.isDirectory()) {
    return {
      ...resolved,
      artifactRealPath,
      artifactStats,
      namespaceRealPath,
      namespaceStats,
      rootRealPath,
    }
  }

  const targetStats = lstatExisting(resolved.target)
  if (!targetStats) {
    return {
      ...resolved,
      artifactRealPath,
      artifactStats,
      namespaceRealPath,
      namespaceStats,
      rootRealPath,
      targetStats,
    }
  }
  if (!targetStats.isDirectory() && !targetStats.isFile()) {
    throw new Error('pytest temp stage is not a regular entry')
  }
  const targetRealPath = assertDirectRealChild(
    resolved.target,
    namespaceRealPath,
    targetStats,
  )
  return {
    ...resolved,
    artifactRealPath,
    artifactStats,
    namespaceRealPath,
    namespaceStats,
    rootRealPath,
    targetRealPath,
    targetStats,
  }
}

function cleanupPytestStage(rootDirectory, stage, {
  platform = process.platform,
  rmSyncImpl = rmSync,
} = {}) {
  const inspected = inspectPytestTemp(rootDirectory, stage, { allowNamespaceFile: true })
  if (!inspected.namespaceStats?.isDirectory() || !inspected.targetStats) return

  inspectPytestTemp(rootDirectory, stage)
  const removeOptions = { recursive: true, force: true }
  if (platform === 'win32') {
    removeOptions.maxRetries = 5
    removeOptions.retryDelay = 200
  }
  rmSyncImpl(inspected.target, removeOptions)
}

function cleanupPytestNamespace(rootDirectory) {
  const inspected = inspectPytestTemp(rootDirectory, pytestTempStages.unitApi, {
    allowNamespaceFile: true,
  })
  if (!inspected.namespaceStats) return

  const verified = inspectPytestTemp(rootDirectory, pytestTempStages.unitApi, {
    allowNamespaceFile: true,
  })
  if (verified.namespaceStats.isDirectory()) {
    rmdirSync(verified.namespace)
  } else {
    rmSync(verified.namespace, { force: true })
  }
}

function cleanupArtifactRoot(rootDirectory) {
  const inspected = inspectPytestTemp(rootDirectory, pytestTempStages.unitApi, {
    allowNamespaceFile: true,
  })
  if (!inspected.artifactStats) return

  const verified = inspectPytestTemp(rootDirectory, pytestTempStages.unitApi, {
    allowNamespaceFile: true,
  })
  try {
    rmdirSync(verified.artifactRoot)
  } catch (error) {
    if (error?.code === 'ENOTEMPTY' || error?.code === 'EEXIST') return
    throw error
  }
}

export function createPytestTempLifecycle({
  platform = process.platform,
  rmSyncImpl = rmSync,
} = {}) {
  return Object.freeze({
    prepare(rootDirectory, stage) {
      const beforeCreate = inspectPytestTemp(rootDirectory, stage)
      mkdirSync(beforeCreate.namespace, { recursive: true })
      inspectPytestTemp(rootDirectory, stage)
      cleanupPytestStage(rootDirectory, stage, { platform, rmSyncImpl })
    },
    cleanupStage(rootDirectory, stage) {
      cleanupPytestStage(rootDirectory, stage, { platform, rmSyncImpl })
    },
    cleanupAll(rootDirectory) {
      let firstError
      for (const stage of Object.values(pytestTempStages)) {
        try {
          cleanupPytestStage(rootDirectory, stage, { platform, rmSyncImpl })
        } catch (error) {
          firstError ??= error
        }
      }

      try {
        cleanupPytestNamespace(rootDirectory)
      } catch (error) {
        firstError ??= error
      }

      try {
        cleanupArtifactRoot(rootDirectory)
      } catch (error) {
        firstError ??= error
      }

      if (firstError) throw firstError
    },
  })
}

export const defaultPytestTempLifecycle = createPytestTempLifecycle()

function safeErrorCode(error) {
  const code = typeof error?.code === 'string' ? error.code : ''
  return /^[A-Z0-9_-]+$/u.test(code) ? code : 'UNKNOWN'
}

function pytestStageLabel(stage) {
  return path.basename(stage)
}

function writePytestDiagnostic(stderr, code, stage, detail = '') {
  stderr.write(`[${code}] stage=${pytestStageLabel(stage)}${detail}\n`)
}

export function runSuites(requested, {
  rootDirectory = root,
  spawnSyncImpl = spawnSync,
  stderr = process.stderr,
  environment = process.env,
  pytestTempLifecycle = defaultPytestTempLifecycle,
} = {}) {
  let exitCode = 0
  let lastPytestStage = pytestTempStages.unitApi

  try {
    if (requested.length === 0 || requested.some(name => !suiteNames.includes(name))) {
      stderr.write(usage())
      exitCode = 2
    } else if (requested.some(name => mysqlSuites.has(name))) {
      const missing = integrationEnvironmentNames.filter(name => !(name in environment))
      if (missing.length > 0) {
        stderr.write(`Integration/browser requires explicit variables: ${missing.join(', ')}\n`)
        exitCode = 2
      }
    }

    if (exitCode === 0) {
      const { commands, formalTests } = createSuites(rootDirectory, environment)
      for (const suite of requested) {
        for (const [directory, files] of formalTests[suite] ?? []) {
          if (files.length === 0) {
            stderr.write(`No formal tests found in ${directory}\n`)
            exitCode = 2
            break
          }
          const missing = files.find(file => !existsSync(file))
          if (missing) {
            stderr.write(`Missing formal test: ${missing}\n`)
            exitCode = 2
            break
          }
        }
        if (exitCode !== 0) break

        for (const [command, args, pytestTempStage] of commands[suite]) {
          if (pytestTempStage) {
            lastPytestStage = pytestTempStage
            try {
              pytestTempLifecycle.prepare(rootDirectory, pytestTempStage)
            } catch {
              writePytestDiagnostic(
                stderr,
                'PYTEST_TEMP_PREPARE_FAILED',
                pytestTempStage,
              )
              exitCode = 1
              break
            }
          }

          let result
          try {
            result = spawnSyncImpl(command, args, {
              cwd: rootDirectory,
              stdio: 'inherit',
              shell: false,
            })
          } catch (error) {
            result = { status: null, error }
          }

          let commandExitCode = 0
          if (result.error) {
            const errorCode = safeErrorCode(result.error)
            if (pytestTempStage) {
              writePytestDiagnostic(
                stderr,
                'PYTEST_CHILD_START_FAILED',
                pytestTempStage,
                ` code=${errorCode}`,
              )
              if (spawnSyncImpl === spawnSync) {
                stderr.write(`Failed to start ${command} (${errorCode})\n`)
              }
            } else {
              stderr.write(`Failed to start ${command} (${errorCode})\n`)
            }
            commandExitCode = result.status ?? 1
          } else if (result.status !== 0) {
            commandExitCode = result.status ?? 1
            if (pytestTempStage) {
              writePytestDiagnostic(
                stderr,
                'PYTEST_CHILD_FAILED',
                pytestTempStage,
                ` status=${commandExitCode}`,
              )
            }
          }

          if (pytestTempStage) {
            try {
              pytestTempLifecycle.cleanupStage(rootDirectory, pytestTempStage)
            } catch {
              writePytestDiagnostic(
                stderr,
                'PYTEST_TEMP_CLEANUP_FAILED',
                pytestTempStage,
              )
              if (commandExitCode === 0) commandExitCode = 1
            }
          }

          if (commandExitCode !== 0) {
            exitCode = commandExitCode
            break
          }
        }
        if (exitCode !== 0) break
      }
    }
  } finally {
    try {
      pytestTempLifecycle.cleanupAll(rootDirectory)
    } catch {
      writePytestDiagnostic(
        stderr,
        'PYTEST_TEMP_CLEANUP_ALL_FAILED',
        lastPytestStage,
      )
      if (exitCode === 0) exitCode = 1
    }
  }

  return exitCode
}

export function isCommandLineEntrypoint(argumentPath, modulePath) {
  if (!argumentPath || !modulePath) return false
  try {
    const argumentIdentity = normalizedPathIdentity(realpathSync(argumentPath))
    const moduleFile = modulePath.startsWith('file:')
      ? fileURLToPath(modulePath)
      : modulePath
    return argumentIdentity === normalizedPathIdentity(realpathSync(moduleFile))
  } catch {
    return false
  }
}

const isCommandLineEntrypointCall = isCommandLineEntrypoint(
  process.argv[1],
  import.meta.url,
)

if (isCommandLineEntrypointCall) {
  process.exitCode = runSuites(process.argv.slice(2))
}
