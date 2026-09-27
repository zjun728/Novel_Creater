import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { compile } from '@vue/compiler-dom'
import * as Vue from 'vue'
import { renderToString } from '@vue/server-renderer'
import NaiveUI from 'naive-ui'

const paths = [
  'views/ApplicationSettingsView.vue', 'views/ProjectSeedsView.vue',
  'components/assets/AssetDetailDrawer.vue', 'components/settings/ProviderSettings.vue',
  'components/project/settings/TaskModelBinding.vue', 'views/assets/CorpusLibraryView.vue',
  'views/assets/ExperienceLibraryView.vue', 'views/assets/StyleLibraryView.vue',
]
for (const path of paths) {
  test(`${path} renders its error recovery controls with the real alert component`, async () => {
    const source = await readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')
    const alerts = [...source.matchAll(/<n-alert\b[\s\S]*?<\/n-alert>/g)].map(match => match[0])
    assert.ok(alerts.some(alert => alert.includes('alert-actions')))
    for (const alert of alerts) {
      assert.doesNotMatch(alert, /<template #action>/)
      if (!alert.includes('alert-actions')) continue
      const render = new Function('Vue', compile(alert, { mode: 'function', prefixIdentifiers: true }).code)(Vue)
      const app = Vue.createSSRApp({
        setup: () => ({
          saveError: '配置冲突', requiresReload: true,
          loadError: '读取失败', error: '读取失败', listError: '读取失败', detailError: '读取失败',
          orphanedLocalDraft: true, reconciliationRequired: true, conflictMessage: '状态冲突',
          contextBusy: false, selected: { id: 'source' }, authoritativeDraftAvailable: true,
          store: { inventoryError: '清单失败', cardError: '列表失败', styleError: '列表失败' },
          loadSettings() {}, discardOrphanedWorkCopy() {}, loadWorkspace() {}, reloadAuthoritative() {},
          adoptAuthoritativeVersion() {}, emit() {}, loadProviders() {}, loadSnapshot() {},
          loadSources() {}, openDetail() {}, loadInventory() {}, retryList() {},
        }), render,
      })
      app.component('n-alert', NaiveUI.NAlert)
      app.component('n-button', NaiveUI.NButton)
      const html = await renderToString(app)
      assert.equal((html.match(/<button\b/g) || []).length, (alert.match(/<n-button\b/g) || []).length)
    }
  })
}
