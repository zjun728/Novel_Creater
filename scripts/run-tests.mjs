import { spawnSync } from 'node:child_process'
import { existsSync, lstatSync, mkdirSync, readdirSync, rmSync, rmdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const suiteNames = [
  'unit',
  'frontend-unit',
  'integration',
  'browser',
  'm1-regression',
  'browser-m2',
  'milestone2',
]
const integrationEnvironmentNames = [
  'TEST_MYSQL_HOST',
  'TEST_MYSQL_PORT',
  'TEST_MYSQL_USER',
  'TEST_MYSQL_PASSWORD',
]
const mysqlSuites = new Set(['integration', 'browser', 'browser-m2', 'milestone2'])
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
const milestone2BrowserFiles = [
  'frontend/e2e/m2-foundation-regression.spec.ts',
  'frontend/e2e/m2-wizard-manual.spec.ts',
  'frontend/e2e/m2-wizard-recovery.spec.ts',
  'frontend/e2e/m2-settings-assets-corpus.spec.ts',
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
  const m2BrowserTests = absolute(milestone2BrowserFiles)
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
  const browserM2 = [[node, ['frontend/e2e/run-milestone2.mjs']]]

  return {
    commands: {
      unit,
      'frontend-unit': [[node, ['--test', ...frontendTests]]],
      integration,
      browser: [[node, ['frontend/e2e/run-milestone1.mjs']]],
      'm1-regression': retainedM1,
      'browser-m2': browserM2,
      milestone2: [
        ...retainedM1,
        ...unit,
        ...integration,
        ...browserM2,
      ],
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
      'browser-m2': [['M2 Playwright specs', m2BrowserTests]],
      milestone2: [
        [scriptTestDirectory, scriptTests],
        [frontendTestDirectory, frontendTests],
        ['M1 v1.1 Python regression', m1PythonTests],
        ['M1 v1.1 frontend regression', m1NodeTests],
        ['M2 Playwright specs', m2BrowserTests],
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
  return { namespace, target }
}

function removeEmptyDirectory(directory, { ignoreNotEmpty = false } = {}) {
  try {
    const entry = lstatSync(directory)
    if (entry.isDirectory()) {
      rmdirSync(directory)
    } else {
      rmSync(directory, { force: true })
    }
  } catch (error) {
    if (error?.code === 'ENOENT') return
    if (ignoreNotEmpty && (error?.code === 'ENOTEMPTY' || error?.code === 'EEXIST')) return
    throw error
  }
}

export const defaultPytestTempLifecycle = Object.freeze({
  prepare(rootDirectory, stage) {
    const { namespace, target } = resolvePytestTemp(rootDirectory, stage)
    mkdirSync(namespace, { recursive: true })
    rmSync(target, { recursive: true, force: true })
  },
  cleanupStage(rootDirectory, stage) {
    const { target } = resolvePytestTemp(rootDirectory, stage)
    rmSync(target, { recursive: true, force: true })
  },
  cleanupAll(rootDirectory) {
    let firstError
    for (const stage of Object.values(pytestTempStages)) {
      try {
        this.cleanupStage(rootDirectory, stage)
      } catch (error) {
        firstError ??= error
      }
    }

    const namespace = path.resolve(rootDirectory, '.codex-test-artifacts', 'pytest')
    try {
      removeEmptyDirectory(namespace)
    } catch (error) {
      firstError ??= error
    }

    const artifactRoot = path.resolve(rootDirectory, '.codex-test-artifacts')
    try {
      removeEmptyDirectory(artifactRoot, { ignoreNotEmpty: true })
    } catch (error) {
      firstError ??= error
    }

    if (firstError) throw firstError
  },
})

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

const isCommandLineEntrypoint = process.argv[1]
  && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url

if (isCommandLineEntrypoint) {
  process.exitCode = runSuites(process.argv.slice(2))
}
