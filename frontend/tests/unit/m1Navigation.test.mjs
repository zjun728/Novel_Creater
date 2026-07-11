import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const readSource = relativePath => readFile(new URL(`../../src/${relativePath}`, import.meta.url), 'utf8')

test('the writer route mounts only the unavailable foundation view', async () => {
  const router = await readSource('router/index.js')
  const unavailable = await readSource('views/WriterUnavailableView.vue')

  assert.match(router, /WriterUnavailableView\.vue/)
  assert.doesNotMatch(router, /WriterView\.vue/)
  assert.match(unavailable, /写作内核尚未开放/)
  assert.match(unavailable, /旧章节、临时草稿和版本定稿链已停用/)
  assert.match(unavailable, /返回项目/)
})

test('the M1 project page depends only on project seed and writer core reads', async () => {
  const projectView = await readSource('views/ProjectView.vue')
  for (const forbidden of [
    'useWriterStore', 'useNovelStore', 'useSettingStore', 'useVolumeStore',
    'useStoryBlockStore', 'useCorrectionTaskStore', 'WriterView',
  ]) {
    assert.equal(projectView.includes(forbidden), false, `legacy project dependency remains: ${forbidden}`)
  }
  assert.equal((projectView.match(/projectStore\.openProject\(/g) || []).length, 1)
  assert.equal((projectView.match(/seedStore\.loadSeeds\(/g) || []).length, 1)
  assert.equal((projectView.match(/api\.writerCore\.state\(/g) || []).length, 1)
  assert.match(projectView, /派生写作数据.*重置/s)
  assert.match(projectView, /进入写作台/)
})

test('active navigation exposes no retired import export backup or provider call', async () => {
  const [home, app, providerSettings, seedStore, binding] = await Promise.all([
    readSource('views/HomeView.vue'),
    readSource('App.vue'),
    readSource('components/settings/ProviderSettings.vue'),
    readSource('stores/seedStore.js'),
    readSource('components/settings/TaskModelBinding.vue'),
  ])

  assert.doesNotMatch(home, /导入项目|导出|exportFull|importFull/)
  assert.match(home, /@click=.*handleOpen/)
  assert.match(home, /@dblclick=.*handleOpen/)
  assert.doesNotMatch(app, /BackupReminder/)
  assert.doesNotMatch(providerSettings, /testConnection|测试连接/)
  assert.doesNotMatch(seedStore, /createSeed|updateSeed|deleteSeed|clearSeeds|selectSeed|generateSeeds/)
  assert.doesNotMatch(binding, /saveBindings|保存模型映射|@click=.*save/)
})

