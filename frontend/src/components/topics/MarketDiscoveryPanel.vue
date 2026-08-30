<script setup>
import { computed, ref } from 'vue'
import { NAlert, NButton, NEmpty, NSpin, NTag } from 'naive-ui'

import { useMarketSourceStore } from '@/stores/marketSourceStore'

const props = defineProps({
  selectedEvidence: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:selectedEvidence'])
const market = useMarketSourceStore()
const fileInput = ref(null)
const importSource = ref(null)
const actionError = ref('')

const latestSnapshots = computed(() => market.sources.map(source => {
  const snapshot = market.snapshotHistory[source.id]?.[0]
  return snapshot ? { ...snapshot, source } : null
}).filter(Boolean))

function commandKey() {
  const bytes = new Uint8Array(32)
  globalThis.crypto.getRandomValues(bytes)
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
}

function timeLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return '尚无成功记录'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
    .format(new Date(number < 10_000_000_000 ? number * 1000 : number))
}

function freshness(source) {
  const state = market.sourceState(source.id).freshness
  if (state === 'available-with-later-failure') return '保留上次成功 · 最新刷新失败'
  if (state === 'available') return '快照可用'
  if (state === 'failed') return '最新刷新失败 · 尚无可用快照'
  return '等待首次快照'
}

function isSelected(snapshot) {
  return props.selectedEvidence.some(item => item.snapshotId === snapshot.id)
}

function toggleEvidence(snapshot) {
  const remaining = props.selectedEvidence.filter(item => item.snapshotId !== snapshot.id)
  emit('update:selectedEvidence', isSelected(snapshot) ? remaining : [
    ...remaining,
    { snapshotId: snapshot.id, contentHash: snapshot.contentHash, label: snapshot.source.displayName },
  ].slice(-4))
}

async function refresh(source) {
  actionError.value = ''
  try {
    await market.refreshSource(source.id, commandKey())
  } catch (failure) {
    actionError.value = failure?.message || `${source.displayName} 刷新失败`
  }
}

function chooseImport(source) {
  importSource.value = source
  fileInput.value?.click()
}

async function importSnapshot(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !importSource.value) return
  actionError.value = ''
  try {
    await market.importManualSnapshot(importSource.value.id, JSON.parse(await file.text()), commandKey())
  } catch (failure) {
    actionError.value = failure instanceof SyntaxError ? '导入文件不是有效的 JSON 快照' : failure?.message || '快照导入失败'
  } finally {
    importSource.value = null
  }
}
</script>

<template>
  <section class="market-panel" aria-labelledby="market-panel-title">
    <header class="panel-heading">
      <div><p>PUBLIC EVIDENCE</p><h2 id="market-panel-title">市场热门与公开证据</h2></div>
      <n-tag :bordered="false">{{ latestSnapshots.length }} 份可用快照</n-tag>
    </header>
    <p class="panel-intro">查看各平台公开榜单的新鲜度，按需手动刷新或导入；不采集正文，也不把旧数据冒充最新结果。</p>

    <n-alert v-if="actionError || market.error" type="error" aria-live="assertive" class="panel-alert">
      {{ actionError || '市场来源暂时无法完整加载，你仍可从空白想法开始讨论。' }}
    </n-alert>
    <n-spin :show="market.loading">
      <div v-if="market.sources.length" class="source-list" tabindex="0" aria-label="市场来源列表">
        <article v-for="source in market.sources" :key="source.id" class="source-card">
          <header>
            <div><span>{{ source.platform }} · {{ source.rankingName }}</span><h3>{{ source.displayName }}</h3></div>
            <n-tag size="small" :type="source.policyStatus === 'verified_public' ? 'success' : 'warning'">
              {{ source.policyStatus === 'verified_public' ? '支持手动刷新' : '仅支持导入' }}
            </n-tag>
          </header>
          <dl>
            <div><dt>数据状态</dt><dd>{{ freshness(source) }}</dd></div>
            <div><dt>上次成功</dt><dd>{{ timeLabel(source.lastSucceededAt) }}</dd></div>
            <div v-if="source.publicErrorCode"><dt>本次失败</dt><dd>来源暂不可用，历史快照仍保留</dd></div>
          </dl>
          <div class="card-actions">
            <n-button size="small" :disabled="source.policyStatus !== 'verified_public'" :loading="market.sourceOperationId === source.id" @click="refresh(source)">手动刷新</n-button>
            <n-button size="small" :disabled="market.sourceOperationId === source.id" @click="chooseImport(source)">手动导入快照</n-button>
          </div>
          <button
            v-if="market.snapshotHistory[source.id]?.[0]"
            type="button"
            class="evidence-toggle"
            :class="{ selected: isSelected(market.snapshotHistory[source.id][0]) }"
            :aria-pressed="isSelected(market.snapshotHistory[source.id][0])"
            @click="toggleEvidence({ ...market.snapshotHistory[source.id][0], source })"
          >
            {{ isSelected(market.snapshotHistory[source.id][0]) ? '已附加到讨论' : '附加最新快照到讨论' }}
          </button>
        </article>
      </div>
      <n-empty v-else-if="!market.loading" description="暂无已登记的市场来源；AI 讨论仍可从空白想法开始。" />
    </n-spin>
    <input ref="fileInput" class="visually-hidden" type="file" accept="application/json,.json" @change="importSnapshot">
  </section>
</template>

<style scoped>
.market-panel { min-width:0; padding:22px; border:1px solid #d8c9b5; background:rgba(255,253,248,.92); }
.panel-heading,.source-card header,.card-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.panel-heading p,.source-card header span { margin:0; color:#9a4938; font:750 9px Georgia,serif; letter-spacing:.14em; }
.panel-heading h2 { margin:5px 0 0; font:650 25px 'Noto Serif SC','Songti SC',serif; }
.panel-intro { margin:11px 0 18px; color:#786c5e; font-size:12px; line-height:1.7; }
.panel-alert { margin-bottom:12px; }
.source-list { display:grid; gap:11px; max-height:590px; overflow-y:auto; padding-right:5px; outline:none; scrollbar-gutter:stable; }
.source-card { padding:16px; border:1px solid #e1d6c5; background:#fbf7ef; }
.source-card h3 { margin:4px 0 0; font:650 17px 'Noto Serif SC','Songti SC',serif; }
.source-card dl { display:grid; gap:6px; margin:14px 0; }
.source-card dl div { display:grid; grid-template-columns:76px minmax(0,1fr); gap:10px; font-size:11px; }
.source-card dt { color:#92775c; }.source-card dd { margin:0; color:#514940; }
.card-actions { justify-content:flex-start; flex-wrap:wrap; }
.evidence-toggle { width:100%; min-height:38px; margin-top:12px; border:1px dashed #baa88f; color:#65594d; background:transparent; cursor:pointer; }
.evidence-toggle.selected { border-style:solid; border-color:#426a52; color:#31553f; background:#eef3eb; }
.visually-hidden { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); }
@media(max-width:720px){.market-panel{padding:16px}.source-list{max-height:none;overflow-y:visible}.panel-heading{align-items:flex-start}}
</style>
