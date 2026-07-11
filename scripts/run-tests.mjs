import { spawnSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const suiteNames = ['unit', 'frontend-unit', 'integration', 'browser']
const integrationEnvironmentNames = [
  'TEST_MYSQL_HOST',
  'TEST_MYSQL_PORT',
  'TEST_MYSQL_USER',
  'TEST_MYSQL_PASSWORD',
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

  return {
    commands: {
      unit: [
        [python, ['-m', 'pytest', 'backend/tests/unit', 'backend/tests/api', '-q']],
        [node, ['--test', ...scriptTests]],
        [node, ['--test', ...frontendTests]],
      ],
      'frontend-unit': [[node, ['--test', ...frontendTests]]],
      integration: [[python, ['-m', 'pytest', 'backend/tests/integration', '-m', 'mysql', '-q']]],
      browser: [[node, ['frontend/e2e/run-milestone1.mjs']]],
    },
    formalTests: {
      unit: [
        [scriptTestDirectory, scriptTests],
        [frontendTestDirectory, frontendTests],
      ],
      'frontend-unit': [[frontendTestDirectory, frontendTests]],
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

  if (requested.includes('integration')) {
    const missing = integrationEnvironmentNames.filter(name => !(name in environment))
    if (missing.length > 0) {
      stderr.write(`Integration requires explicit variables: ${missing.join(', ')}\n`)
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
