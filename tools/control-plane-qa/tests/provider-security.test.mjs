import assert from 'node:assert/strict'
import test from 'node:test'

const providerSecurity = await import('../../../frontend/src/utils/providerSecurity.js')
  .catch((error) => {
    if (error?.code === 'ERR_MODULE_NOT_FOUND') return {}
    throw error
  })

test('provider updates omit blank API keys and preserve nonempty keys exactly', () => {
  assert.equal(typeof providerSecurity.buildProviderUpdatePayload, 'function')

  const blankPayload = providerSecurity.buildProviderUpdatePayload({
    name: 'Provider',
    apiKey: '',
    model: undefined,
    ignored: 'not allowed'
  })
  assert.deepEqual(blankPayload, { name: 'Provider' })

  const spacedApiKey = '  sk-secret  '
  const configuredPayload = providerSecurity.buildProviderUpdatePayload({
    apiKey: spacedApiKey
  })
  assert.deepEqual(configuredPayload, { apiKey: spacedApiKey })
})

test('provider eligibility requires both hasApiKey metadata and a model', () => {
  assert.equal(typeof providerSecurity.isProviderConfigured, 'function')

  assert.equal(providerSecurity.isProviderConfigured({ hasApiKey: true, model: 'gpt-4o' }), true)
  assert.equal(providerSecurity.isProviderConfigured({ hasApiKey: false, model: 'gpt-4o' }), false)
  assert.equal(providerSecurity.isProviderConfigured({ hasApiKey: true, model: '' }), false)
  assert.equal(providerSecurity.isProviderConfigured({ apiKey: 'legacy-secret', model: 'gpt-4o' }), false)
})

test('secret-free export paths only encode the project ID', () => {
  assert.equal(typeof providerSecurity.buildSecretFreeExportPath, 'function')

  assert.equal(providerSecurity.buildSecretFreeExportPath(), '/export/full')
  assert.equal(providerSecurity.buildSecretFreeExportPath('project with spaces'), '/export/full?projectId=project+with+spaces')
  assert.equal(providerSecurity.buildSecretFreeExportPath('project', true), '/export/full?projectId=project')
})
