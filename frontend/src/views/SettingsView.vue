<script setup>
import { ref } from 'vue'
import { NTabPane, NTabs } from 'naive-ui'
import CorpusSettings from '@/components/settings/CorpusSettings.vue'
import CreationAssetSettings from '@/components/settings/CreationAssetSettings.vue'
import ProviderSettings from '@/components/settings/ProviderSettings.vue'

const activeTab = ref('providers')
</script>

<template>
  <main class="settings-shell">
    <header class="settings-hero">
      <div>
        <p>LOCAL AUTHORING CONTROL / M2</p>
        <h1>创作基础设置</h1>
        <span>管理模型、写作方法资产与本机参考语料。这里不执行正文生成。</span>
      </div>
      <i aria-hidden="true">设</i>
    </header>

    <n-tabs v-model:value="activeTab" type="line" animated class="settings-tabs">
      <n-tab-pane name="providers" tab="Provider 与模型" display-directive="show:lazy">
        <ProviderSettings />
      </n-tab-pane>
      <n-tab-pane name="assets" tab="创作资产" display-directive="show:lazy">
        <CreationAssetSettings />
      </n-tab-pane>
      <n-tab-pane name="corpus" tab="本机语料" display-directive="show:lazy">
        <CorpusSettings />
      </n-tab-pane>
    </n-tabs>
  </main>
</template>

<style scoped>
.settings-shell { --paper: #f4efe4; --ink: #302a23; min-height: 100%; padding: clamp(22px, 4vw, 48px); color: var(--ink); background: var(--paper); }
.settings-hero, .settings-tabs { width: min(1120px, 100%); margin-inline: auto; }
.settings-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 30px; padding-bottom: 25px; border-bottom: 1px solid #d4c7b2; }
.settings-hero p { margin: 0; color: #9a3f32; font: 750 10px Georgia, serif; letter-spacing: .17em; }
.settings-hero h1 { margin: 6px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(30px, 5vw, 48px); font-weight: 600; }
.settings-hero span { display: block; margin-top: 8px; color: #7a7063; font-size: 13px; }
.settings-hero i { display: grid; width: 58px; height: 58px; place-items: center; border: 2px solid #9a3f32; color: #9a3f32; font-family: 'Noto Serif SC', serif; font-size: 26px; font-style: normal; transform: rotate(-2deg); }
.settings-tabs { margin-top: 24px; padding: 6px 26px 30px; border: 1px solid #d9cdb9; border-radius: 13px; background: rgba(255, 253, 248, .8); box-shadow: 0 18px 48px rgba(65, 50, 31, .06); }
.settings-tabs :deep(.n-tabs-tab) { padding: 16px 2px 13px; font-family: 'Noto Serif SC', serif; font-weight: 650; }
.settings-tabs :deep(.n-tabs-bar) { background-color: #9a3f32; }
.settings-tabs :deep(.n-tab-pane) { padding-top: 22px; }
@media (max-width: 600px) { .settings-shell { padding: 18px 12px; } .settings-hero { align-items: flex-start; } .settings-hero i { display: none; } .settings-tabs { padding-inline: 14px; } }
</style>
