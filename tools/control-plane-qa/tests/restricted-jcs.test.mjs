import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { canonicalize, canonicalSha256 } from '../restricted-jcs.mjs'


const vectorsUrl = new URL('../fixtures/rfc8785-restricted-vectors.json', import.meta.url)

test('matches every valid restricted RFC 8785 vector', async () => {
  const vectors = JSON.parse(await readFile(vectorsUrl, 'utf8'))
  for (const item of vectors.valid) {
    assert.equal(canonicalize(item.value), item.canonical, item.name)
    assert.match(canonicalSha256(item.value), /^[0-9a-f]{64}$/)
  }
})

test('rejects values outside the restricted profile', () => {
  const invalid = [
    null,
    true,
    false,
    1.5,
    Number.MAX_SAFE_INTEGER + 1,
    '\ud800',
    { '\udfff': 'value' },
    new Date(0),
    new Map(),
    Object.create(null)
  ]
  for (const value of invalid) {
    assert.throws(() => canonicalize(value), TypeError)
  }
})

test('does not normalize strings and uses UTF-16 key order', () => {
  assert.equal(canonicalize({ '\ue000': 1, '😀': 2 }), '{"😀":2,"":1}')
  assert.notEqual(canonicalize('é'), canonicalize('e\u0301'))
})

test('rejects sparse arrays instead of emitting non-JSON text', () => {
  assert.throws(() => canonicalize(new Array(1)), TypeError)
  assert.throws(() => canonicalize([1, , 2]), TypeError)
})
