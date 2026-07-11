import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildChildEnvironment,
  createDatabaseName,
  runMilestone1,
  validateTestEnvironment,
} from '../../frontend/e2e/run-milestone1.mjs'

const DATABASE = 'novel_creator_test_0123456789abcdef0123456789abcdef'
const TEST_ENVIRONMENT = {
  PATH: 'test-path',
  TEST_MYSQL_HOST: '127.0.0.1',
  TEST_MYSQL_PORT: '33060',
  TEST_MYSQL_USER: 'root',
  TEST_MYSQL_PASSWORD: 'test-only',
  MYSQL_HOST: 'product-host',
  MYSQL_PORT: '3306',
  MYSQL_USER: 'product-user',
  MYSQL_PASSWORD: 'product-password',
  MYSQL_DB: 'novel_creator',
}

test('requires every explicit disposable MySQL variable', () => {
  const environment = { ...TEST_ENVIRONMENT }
  delete environment.TEST_MYSQL_PASSWORD

  assert.throws(
    () => validateTestEnvironment(environment),
    /TEST_MYSQL_PASSWORD/,
  )
})

test('creates an exact disposable database name', () => {
  const databaseName = createDatabaseName(() => '01234567-89ab-cdef-0123-456789abcdef')

  assert.equal(databaseName, DATABASE)
})

test('maps only explicit test server values to the disposable backend database', () => {
  const childEnvironment = buildChildEnvironment(TEST_ENVIRONMENT, DATABASE)

  assert.equal(childEnvironment.MYSQL_HOST, TEST_ENVIRONMENT.TEST_MYSQL_HOST)
  assert.equal(childEnvironment.MYSQL_PORT, TEST_ENVIRONMENT.TEST_MYSQL_PORT)
  assert.equal(childEnvironment.MYSQL_USER, TEST_ENVIRONMENT.TEST_MYSQL_USER)
  assert.equal(childEnvironment.MYSQL_PASSWORD, TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD)
  assert.equal(childEnvironment.MYSQL_DB, DATABASE)
  assert.equal(childEnvironment.BROWSER_TEST_DATABASE, DATABASE)
  assert.equal(childEnvironment.PATH, 'test-path')
})

test('always drops the database and preserves browser plus cleanup failures', () => {
  const calls = []
  const spawnSyncImpl = (command, args, options) => {
    calls.push({ command, args, options })
    if (args.includes('--drop')) return { status: 9 }
    if (args.includes('test')) return { status: 7 }
    return { status: 0 }
  }

  assert.throws(
    () => runMilestone1({
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: () => DATABASE,
      spawnSyncImpl,
    }),
    error => {
      assert(error instanceof AggregateError)
      assert.equal(error.errors.length, 2)
      assert.match(error.errors[0].message, /browser.*7/i)
      assert.match(error.errors[1].message, /cleanup.*9/i)
      return true
    },
  )

  assert.equal(calls.length, 3)
  assert.equal(calls.every(call => call.options.shell === false), true)
  assert.equal(calls[0].args.includes('--database'), true)
  assert.equal(calls[1].args.includes('e2e/milestone1.spec.ts'), true)
  assert.equal(calls[2].args.includes('--drop'), true)
})
