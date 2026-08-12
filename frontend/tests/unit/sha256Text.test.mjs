import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'

import { sha256Text } from '../../src/utils/sha256Text.js'

function expected(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

test('sha256Text hashes exact UTF-8 text to lowercase hex without normalization', async () => {
  for (const value of ['', '甲😀', 'e\u0301', 'é']) {
    assert.equal(await sha256Text(value), expected(value))
  }
  assert.notEqual(await sha256Text('e\u0301'), await sha256Text('é'))
})

test('sha256Text rejects malformed Unicode and missing Web Crypto with fixed local errors', async () => {
  await assert.rejects(sha256Text('\ud800'), error => (
    error instanceof TypeError && error.message === 'Unable to hash text'
  ))
  await assert.rejects(sha256Text(null), error => (
    error instanceof TypeError && error.message === 'Unable to hash text'
  ))

  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true,
    value: undefined,
  })
  try {
    await assert.rejects(sha256Text('MUST-NOT-APPEAR'), error => (
      error instanceof TypeError
      && error.message === 'Unable to hash text'
      && !error.message.includes('MUST-NOT-APPEAR')
    ))
  } finally {
    if (descriptor) Object.defineProperty(globalThis, 'crypto', descriptor)
    else delete globalThis.crypto
  }
})
