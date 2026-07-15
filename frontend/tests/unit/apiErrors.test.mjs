import assert from 'node:assert/strict'
import test from 'node:test'

import { ApiError, parseApiError } from '../../src/api/db/api-error.js'

test('public api errors keep stable metadata and discard raw secret text', async () => {
  const response = new Response(JSON.stringify({
    code: 'contract_conflict',
    message: '项目状态已更新',
    correlationId: 'cid-1',
    debug: 'browser-secret-must-not-leak',
  }), { status: 409, headers: { 'content-type': 'application/json' } })

  const error = await parseApiError(response)

  assert.ok(error instanceof ApiError)
  assert.deepEqual(
    {
      status: error.status,
      code: error.code,
      message: error.message,
      correlationId: error.correlationId,
    },
    {
      status: 409,
      code: 'contract_conflict',
      message: '项目状态已更新',
      correlationId: 'cid-1',
    },
  )
  assert.equal(JSON.stringify(error).includes('browser-secret-must-not-leak'), false)
  assert.equal('debug' in error, false)
  assert.equal('body' in error, false)
})

test('nested public error metadata is normalized without retaining its raw body', async () => {
  const response = new Response(JSON.stringify({
    detail: {
      code: 'SeedConflict',
      message: '种子已经变化',
      correlationId: 'cid-nested',
      apiKey: 'provider-secret-must-not-leak',
    },
  }), { status: 409, headers: { 'content-type': 'application/json' } })

  const error = await parseApiError(response)

  assert.deepEqual(error.toJSON(), {
    name: 'ApiError',
    status: 409,
    code: 'SeedConflict',
    message: '种子已经变化',
    correlationId: 'cid-nested',
  })
  assert.equal(JSON.stringify(error).includes('provider-secret-must-not-leak'), false)
})

test('non-json api errors use a safe fallback without echoing response text', async () => {
  const response = new Response('private-debug-secret', {
    status: 502,
    headers: { 'content-type': 'text/plain' },
  })

  const error = await parseApiError(response)

  assert.deepEqual(error.toJSON(), {
    name: 'ApiError',
    status: 502,
    code: 'request_failed',
    message: '请求失败 (502)',
    correlationId: '',
  })
  assert.equal(JSON.stringify(error).includes('private-debug-secret'), false)
})

test('the client request path normalizes unsafe error and invalid response bodies', async () => {
  const originalFetch = global.fetch
  const { api } = await import('../../src/api/db/client.js')
  try {
    global.fetch = async () => new Response(JSON.stringify({
      code: 'BindingConflict', message: '绑定已变化', correlationId: 'cid-request',
      debug: 'request-secret-must-not-leak',
    }), { status: 409, headers: { 'content-type': 'application/json' } })
    await assert.rejects(api.health(), error => {
      assert.ok(error instanceof ApiError)
      assert.deepEqual(error.toJSON(), {
        name: 'ApiError', status: 409, code: 'BindingConflict',
        message: '绑定已变化', correlationId: 'cid-request',
      })
      return !JSON.stringify(error).includes('request-secret-must-not-leak')
    })

    global.fetch = async () => new Response('invalid-success-secret', { status: 200 })
    await assert.rejects(api.health(), error => (
      error instanceof ApiError
      && error.code === 'invalid_response'
      && !JSON.stringify(error).includes('invalid-success-secret')
    ))

    global.fetch = async () => { throw new Error('network-secret-must-not-leak') }
    await assert.rejects(api.health(), error => (
      error instanceof ApiError
      && error.code === 'request_failed'
      && !JSON.stringify(error).includes('network-secret-must-not-leak')
    ))
  } finally {
    global.fetch = originalFetch
  }
})
