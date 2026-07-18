import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'


const formSource = () => readFile(
  new URL('../../src/components/settings/ProviderForm.vue', import.meta.url),
  'utf8',
)
const settingsSource = () => readFile(
  new URL('../../src/components/settings/ProviderSettings.vue', import.meta.url),
  'utf8',
)

test('ProviderForm owns blank edit secrets and clears them on submit finally, close, and unmount', async () => {
  const source = await formSource()

  assert.match(source, /apiKey:\s*['"]['"]/)
  assert.match(source, /baseURL:\s*['"]['"]/)
  assert.match(source, /clearSensitiveFields/)
  assert.match(source, /finally\s*\{[\s\S]*clearSensitiveFields\(\)/)
  assert.match(source, /onBeforeUnmount\(clearSensitiveFields\)/)
  assert.match(source, /function handleCancel\([\s\S]*clearSensitiveFields\(\)/)
  assert.doesNotMatch(source, /initial\.(apiKey|api_key|baseURL|base_url)/)
})

test('Provider settings uses exactly one red danger confirmation and only for clear API key', async () => {
  const source = await settingsSource()

  assert.match(source, /useDangerousConfirmation/)
  assert.match(source, /handleClearApiKey/)
  assert.match(source, /清除 API Key/)
  assert.equal((source.match(/confirmation\.confirm\(/g) || []).length, 1)
  assert.match(source, /positiveText:\s*['"]清除密钥['"]/)
  assert.doesNotMatch(source, /handleDelete[\s\S]{0,800}confirmation\.confirm/)
})

test('connection test renders only fixed feedback and never echoes Provider configuration', async () => {
  const source = await settingsSource()

  assert.match(source, /handleTestConnection/)
  assert.match(source, /connectionFeedback/)
  assert.match(source, /publicMessage/)
  assert.match(source, /latencyMs/)
  assert.doesNotMatch(
    source,
    /connectionFeedback[^;\n]*(apiKey|api_key|baseURL|base_url|authorization|token|password)/i,
  )
})

test('parent clears emitted secret copies in request finally and on form close/unmount', async () => {
  const source = await settingsSource()

  assert.match(source, /clearSubmittedSecrets/)
  assert.match(source, /finally\s*\{[\s\S]*clearSubmittedSecrets\(formData\)/)
  assert.match(source, /setFormVisibility[\s\S]*editingProvider\.value\s*=\s*null/)
  assert.match(source, /onBeforeUnmount\([\s\S]*editingProvider\.value\s*=\s*null/)
})
