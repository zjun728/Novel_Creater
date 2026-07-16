import { spawnSync } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
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
    [python, ['-m', 'pytest', ...m1RegressionPythonFiles, '-q']],
    [node, ['--test', ...m1RegressionNodeFiles]],
  ]
  const unit = [
    [python, ['-m', 'pytest', 'backend/tests/unit', 'backend/tests/api', '-q']],
    [node, ['--test', ...scriptTests]],
    [node, ['--test', ...frontendTests]],
  ]
  const integration = [
    [python, ['-m', 'pytest', 'backend/tests/integration', '-m', 'mysql', '-q']],
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

export function runSuites(requested, {
  rootDirectory = root,
  spawnSyncImpl = spawnSync,
  stderr = process.stderr,
  environment = process.env,
} = {}) {
  if (requested.length === 0 || requested.some(name => !suiteNames.includes(name))) {
    stderr.write(usage())
    return 2
  }

  if (requested.some(name => mysqlSuites.has(name))) {
    const missing = integrationEnvironmentNames.filter(name => !(name in environment))
    if (missing.length > 0) {
      stderr.write(`Integration/browser requires explicit variables: ${missing.join(', ')}\n`)
      return 2
    }
  }

  const { commands, formalTests } = createSuites(rootDirectory, environment)
  for (const suite of requested) {
    for (const [directory, files] of formalTests[suite] ?? []) {
      if (files.length === 0) {
        stderr.write(`No formal tests found in ${directory}\n`)
        return 2
      }
      const missing = files.find(file => !existsSync(file))
      if (missing) {
        stderr.write(`Missing formal test: ${missing}\n`)
        return 2
      }
    }

    for (const [command, args] of commands[suite]) {
      const result = spawnSyncImpl(command, args, {
        cwd: rootDirectory,
        stdio: 'inherit',
        shell: false,
      })
      if (result.error) {
        const errorCode = result.error.code ? ` (${result.error.code})` : ''
        stderr.write(`Failed to start ${command}${errorCode}: ${result.error.message}\n`)
        return result.status ?? 1
      }
      if (result.status !== 0) return result.status ?? 1
    }
  }

  return 0
}

const isCommandLineEntrypoint = process.argv[1]
  && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url

if (isCommandLineEntrypoint) {
  process.exitCode = runSuites(process.argv.slice(2))
}
