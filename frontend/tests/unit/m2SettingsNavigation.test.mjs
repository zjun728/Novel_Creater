import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const readSource = relativePath => readFile(new URL(`../../src/${relativePath}`, import.meta.url), 'utf8')

test('settings exposes provider bindings, creation assets, and local corpus as three formal tabs', async () => {
  const [settings, providers, bindings, assets, corpus] = await Promise.all([
    readSource('views/SettingsView.vue'),
    readSource('components/settings/ProviderSettings.vue'),
    readSource('components/settings/TaskModelBinding.vue'),
    readSource('components/settings/CreationAssetSettings.vue'),
    readSource('components/settings/CorpusSettings.vue'),
  ])
  const tree = [settings, providers, bindings, assets, corpus].join('\n')

  for (const component of ['ProviderSettings', 'CreationAssetSettings', 'CorpusSettings']) {
    assert.match(settings, new RegExp(component))
  }
  assert.match(settings, /Provider 与模型/)
  assert.match(settings, /创作资产/)
  assert.match(settings, /本机语料/)
  assert.equal(settings.match(/display-directive="show:lazy"/g)?.length, 3)
  assert.match(bindings, /一次保存八项绑定/)
  assert.match(providers, /停用并清除私密配置/)
  assert.doesNotMatch(providers, /clearApiKey|clearBaseURL|清除当前 API Key|清除当前 Base URL/)
  assert.doesNotMatch(tree, /\bfetch\s*\(|localStorage|createAdapter|chatCompletion|page\.request/)
  assert.doesNotMatch(tree, /absolutePath|absoluteRoot|完整哈希|全文导出|审核上架|marketplace/i)
})

test('corpus settings keeps browser previews bounded and paths relative', async () => {
  const corpus = await readSource('components/settings/CorpusSettings.vue')

  assert.match(corpus, /relativePath/)
  assert.match(corpus, /240/)
  assert.match(corpus, /4_?800/)
  assert.match(corpus, /20/)
  assert.doesNotMatch(corpus, /type=["']file["']/)
  assert.doesNotMatch(corpus, /webkitdirectory|showDirectoryPicker|showOpenFilePicker/)
})
