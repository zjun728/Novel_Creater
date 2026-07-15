import assert from 'node:assert/strict'
import test from 'node:test'

import {
  contractReady,
  nextAllowedStep,
  providerRetryAction,
} from '../../src/domain/creation-contract/wizard-state.js'

test('wizard advances only when each saved backend decision is complete', () => {
  assert.equal(nextAllowedStep({ selectedSeed: null }), 1)
  assert.equal(nextAllowedStep({ selectedSeed: { id: 's1' }, selectedEngine: null }), 2)
  assert.equal(nextAllowedStep({
    selectedSeed: { id: 's1' }, selectedEngine: { id: 'e1' }, primaryStyle: null,
  }), 3)
  assert.equal(nextAllowedStep({
    selectedSeed: { id: 's1' }, selectedEngine: { id: 'e1' }, primaryStyle: { id: 'st1' },
  }), 4)
  assert.equal(nextAllowedStep({
    selectedSeed: { id: 's1' }, selectedEngine: { id: 'e1' },
    primaryStyle: { id: 'st1' }, assetsLoaded: true,
  }), 5)
})

test('contract readiness accepts only an explicit ready result with no backend reasons', () => {
  assert.equal(contractReady(), false)
  assert.equal(contractReady({ readiness: { ready: true } }), false)
  assert.equal(contractReady({ readiness: { ready: true, reasons: ['seed_drift'] } }), false)
  assert.equal(contractReady({ readiness: { ready: false, reasons: [] } }), false)
  assert.equal(contractReady({ readiness: { ready: true, reasons: [] } }), true)
})

test('outcome-unknown provider batches require a new explicitly confirmed batch', () => {
  assert.equal(providerRetryAction(), 'none')
  assert.equal(providerRetryAction({ status: 'failed' }), 'none')
  assert.equal(
    providerRetryAction({ status: 'outcome_unknown' }),
    'create-new-batch-with-explicit-confirmation',
  )
})
