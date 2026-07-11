import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const readSource = relativePath => readFile(new URL(`../../src/${relativePath}`, import.meta.url), 'utf8')

async function readActiveDependencyTree(entry, visited = new Set()) {
  if (visited.has(entry)) return ''
  visited.add(entry)
  const source = await readSource(entry)
  const imports = [...source.matchAll(/from\s+['"](@\/[^'"]+|\.\.?\/[^'"]+)['"]/g)]
  const directory = entry.split('/').slice(0, -1)
  const children = []
  for (const [, specifier] of imports) {
    const rawParts = specifier.startsWith('@/')
      ? specifier.slice(2).split('/')
      : [...directory, ...specifier.split('/')]
    const normalized = []
    for (const part of rawParts) {
      if (part === '.' || !part) continue
      if (part === '..') normalized.pop()
      else normalized.push(part)
    }
    const path = normalized.join('/')
    for (const candidate of /\.[a-z]+$/i.test(path) ? [path] : [`${path}.js`, `${path}.vue`]) {
      try {
        children.push(await readActiveDependencyTree(candidate, visited))
        break
      } catch (error) {
        if (error?.code !== 'ENOENT') throw error
      }
    }
  }
  return `${entry}\n${source}\n${children.join('\n')}`
}

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
  assert.match(projectView, /watch\(\s*\(\)\s*=>\s*route\.params\.id/)
  assert.match(projectView, /createLatestRequestGuard/)
  assert.match(projectView, /onBeforeUnmount/)
  assert.match(projectView, /派生写作数据.*重置/s)
  assert.match(projectView, /进入写作台/)
})

test('active navigation exposes no retired import export backup or provider call', async () => {
  const [home, app, providerSettings, seedStore, projectStore, binding, router, sidebarTree] = await Promise.all([
    readSource('views/HomeView.vue'),
    readSource('App.vue'),
    readSource('components/settings/ProviderSettings.vue'),
    readSource('stores/seedStore.js'),
    readSource('stores/projectStore.js'),
    readSource('components/settings/TaskModelBinding.vue'),
    readSource('router/index.js'),
    readActiveDependencyTree('components/layout/Sidebar.vue'),
  ])

  assert.doesNotMatch(home, /导入项目|导出|exportFull|importFull/)
  assert.match(home, /@click=.*handleOpen/)
  assert.doesNotMatch(home, /@dblclick/)
  assert.match(home, /class="card-open-area"/)
  assert.match(home, /删除失败/)
  assert.doesNotMatch(app, /BackupReminder/)
  assert.doesNotMatch(providerSettings, /testConnection|测试连接/)
  assert.doesNotMatch(seedStore, /createSeed|updateSeed|deleteSeed|clearSeeds|selectSeed|generateSeeds/)
  assert.match(seedStore, /createLatestRequestGuard/)
  assert.match(seedStore, /seeds\.value = \[\]/)
  assert.match(seedStore, /invalidateLoadSeeds/)
  assert.match(projectStore, /createLatestRequestGuard/)
  assert.match(projectStore, /currentProject\.value = null/)
  assert.match(projectStore, /invalidateOpenProject/)
  assert.doesNotMatch(binding, /saveBindings|保存模型映射|@click=.*save/)
  assert.match(binding, /createLatestRequestGuard/)
  assert.match(binding, /项目列表加载失败/)
  assert.match(binding, /没有可查看的项目/)
  assert.doesNotMatch(binding, /@click="loadStatus"/)
  assert.doesNotMatch(binding, /@click="loadProjectsAndSelect"/)
  assert.match(providerSettings, /删除失败/)
  assert.doesNotMatch(router, /ExperienceCards|experience-cards/)
  assert.match(router, /path:\s*['"]\/:pathMatch\(\.\*\)\*['"].*redirect:\s*['"]\/['"]/s)
  assert.doesNotMatch(sidebarTree, /写作台|\/writer\/|ExperienceCards|experience-cards|创作经验卡/)
})
