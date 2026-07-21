import assert from 'node:assert/strict'
import test from 'node:test'

import { runPhase2BLifecycle } from '../../frontend/e2e/phase2b-run-lifecycle.mjs'


test('Phase 2B lifecycle cleans every dynamically registered resource after body failure', async () => {
  const events = []
  const bodyFailure = new Error('body failed')

  await assert.rejects(
    runPhase2BLifecycle({
      async body(lifecycle) {
        lifecycle.setRoot('owned-root')
        lifecycle.setDatabase('disposable-db')
        lifecycle.registerReservation('backend-port')
        lifecycle.registerReservation('vite-port')
        lifecycle.registerServer('backend')
        lifecycle.registerServer('vite')
        throw bodyFailure
      },
      async stopServer(server) {
        events.push(`stop:${server}`)
      },
      async releaseReservation(reservation) {
        events.push(`release:${reservation}`)
      },
      async dropDatabase(database) {
        events.push(`drop:${database}`)
      },
      async removeRoot(root) {
        events.push(`remove:${root}`)
      },
    }),
    error => error === bodyFailure,
  )

  assert.deepEqual(events, [
    'stop:vite',
    'stop:backend',
    'release:backend-port',
    'release:vite-port',
    'drop:disposable-db',
    'remove:owned-root',
  ])
})


test('Phase 2B lifecycle continues cleanup and aggregates body plus cleanup failures', async () => {
  const events = []
  const bodyFailure = new Error('body failed')
  const stopFailure = new Error('stop failed')
  const dropFailure = new Error('drop failed')
  const removeFailure = new Error('remove failed')

  await assert.rejects(
    runPhase2BLifecycle({
      async body(lifecycle) {
        lifecycle.setRoot('owned-root')
        lifecycle.setDatabase('disposable-db')
        lifecycle.registerReservation('backend-port')
        lifecycle.registerReservation('vite-port')
        lifecycle.registerServer('backend')
        lifecycle.registerServer('vite')
        throw bodyFailure
      },
      async stopServer(server) {
        events.push(`stop:${server}`)
        if (server === 'vite') throw stopFailure
      },
      async releaseReservation(reservation) {
        events.push(`release:${reservation}`)
      },
      async dropDatabase(database) {
        events.push(`drop:${database}`)
        throw dropFailure
      },
      async removeRoot(root) {
        events.push(`remove:${root}`)
        throw removeFailure
      },
    }),
    error => {
      assert.ok(error instanceof AggregateError)
      assert.deepEqual(
        error.errors,
        [bodyFailure, stopFailure, dropFailure, removeFailure],
      )
      return true
    },
  )

  assert.deepEqual(events, [
    'stop:vite',
    'stop:backend',
    'release:backend-port',
    'release:vite-port',
    'drop:disposable-db',
    'remove:owned-root',
  ])
})
