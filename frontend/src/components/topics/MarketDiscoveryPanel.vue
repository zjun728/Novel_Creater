<script setup>
import { computed, ref } from 'vue'
import { NAlert, NButton, NEmpty, NSpin, NTag } from 'naive-ui'

import {
  marketCapabilityPresentation,
  marketFailureCopy,
  marketSnapshotDisplayName,
} from '@/application/market/marketSourcePresentation'
import { useMarketSourceStore } from '@/stores/marketSourceStore'
import MarketSnapshotWorks from './MarketSnapshotWorks.vue'

const props = defineProps({
  selectedEvidence: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:selectedEvidence'])
const market = useMarketSourceStore()
const fileInput = ref(null)
const importSource = ref(null)
const actionError = ref('')
const selectedSnapshot = ref(null)
const detailLoadingRequest = ref(null)
let selectionIntentGeneration = 0
let detailRequestGeneration = 0

const selectedSource = computed(() => (
  market.sources.find(source => source.id === selectedSnapshot.value?.sourceId) || null
))
const selectedDetailKey = computed(() => (
  selectedSnapshot.value
    ? JSON.stringify([selectedSnapshot.value.sourceId, selectedSnapshot.value.snapshotId])
    : ''
))
const selectedDetail = computed(() => market.snapshotDetails[selectedDetailKey.value] || null)
const selectedDetailFailure = computed(() => market.snapshotDetailFailures[selectedDetailKey.value] || null)
const detailLoading = computed(() => detailLoadingRequest.value?.key === selectedDetailKey.value)

const latestSnapshots = computed(() => market.sources.map(source => {
  const snapshot = latestSnapshot(source)
  return snapshot ? { ...snapshot, source } : null
}).filter(Boolean))

function latestSnapshot(source) {
  return market.sourceState(source.id).snapshots[0] || null
}

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
    { snapshotId: snapshot.id, contentHash: snapshot.contentHash, label: marketSnapshotDisplayName(snapshot, snapshot.source) },
  ].slice(-4))
}

async function viewLatestSnapshot(source) {
  const sourceId = source.id
  const latest = latestSnapshot(source)
  if (!latest) return
  selectionIntentGeneration += 1
  const requestGeneration = ++detailRequestGeneration
  const key = JSON.stringify([sourceId, latest.id])
  selectedSnapshot.value = { sourceId, snapshotId: latest.id }
  detailLoadingRequest.value = { key, generation: requestGeneration }
  try {
    await market.loadSnapshotDetail(sourceId, latest.id)
  } catch {
    // The reader owns the scoped failure state and keeps any cached success visible.
  } finally {
    if (detailLoadingRequest.value?.generation === requestGeneration) {
      detailLoadingRequest.value = null
    }
  }
}

async function refresh(source) {
  const sourceId = source.id
  const displayName = source.displayName
  const intentGeneration = ++selectionIntentGeneration
  actionError.value = ''
  try {
    const snapshot = await market.refreshSource(sourceId, commandKey())
    if (selectionIntentGeneration === intentGeneration) {
      selectedSnapshot.value = { sourceId, snapshotId: snapshot.id }
    }
  } catch (failure) {
    if (selectionIntentGeneration === intentGeneration) {
      actionError.value = failure?.message || `${displayName} 刷新失败`
    }
  }
}

function chooseImport(source) {
  importSource.value = {
    sourceId: source.id,
    displayName: source.displayName,
    intentGeneration: ++selectionIntentGeneration,
  }
  fileInput.value?.click()
}

async function importSnapshot(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  const selection = importSource.value
  importSource.value = null
  if (!file || !selection) return
  const { sourceId, intentGeneration } = selection
  actionError.value = ''
  try {
    const snapshot = await market.importManualSnapshot(sourceId, JSON.parse(await file.text()), commandKey())
    if (selectionIntentGeneration === intentGeneration) {
      selectedSnapshot.value = { sourceId, snapshotId: snapshot.id }
    }
  } catch (failure) {
    if (selectionIntentGeneration === intentGeneration) {
      actionError.value = failure instanceof SyntaxError ? '导入文件不是有效的 JSON 快照' : failure?.message || '快照导入失败'
    }
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
      <div v-if="market.sources.length" class="evidence-browser">
       <div class="source-list" tabindex="0" aria-label="市场来源列表">
        <article
          v-for="source in market.sources"
          :key="source.id"
          class="source-card"
          :class="{ active: selectedSnapshot?.sourceId === source.id }"
          :data-market-source-key="source.stableKey"
          :data-market-source-status="market.sourceState(source.id).freshness"
          :data-market-source-busy="String(market.isSourceBusy(source.id))"
          :data-market-latest-snapshot-id="latestSnapshot(source)?.id || ''"
          :data-market-latest-captured-at="latestSnapshot(source)?.capturedAt || ''"
          :data-market-latest-entry-count="latestSnapshot(source)?.entryCount || ''"
          :data-market-last-succeeded-at="latestSnapshot(source)?.capturedAt || ''"
        >
          <header>
            <div><span>{{ source.platform }} · {{ source.rankingName }}</span><h3>{{ source.displayName }}</h3></div>
            <n-tag size="small" :type="marketCapabilityPresentation(source).tagType">
              {{ marketCapabilityPresentation(source).label }}
            </n-tag>
          </header>
          <dl>
            <div><dt>数据状态</dt><dd>{{ freshness(source) }}</dd></div>
            <div><dt>上次成功</dt><dd>{{ timeLabel(latestSnapshot(source)?.capturedAt) }}</dd></div>
            <div v-if="source.publicErrorCode"><dt>本次失败</dt><dd>{{ marketFailureCopy(source, market.sourceState(source.id).snapshots) }}</dd></div>
          </dl>
          <div class="card-actions">
            <n-button size="small" :aria-label="`刷新${source.displayName}`" :disabled="!source.canRefresh" :loading="market.isSourceBusy(source.id)" @click="refresh(source)">刷新{{ source.displayName }}</n-button>
            <n-button size="small" :aria-label="`导入${source.displayName}`" :disabled="!source.canManualImport || market.isSourceBusy(source.id)" @click="chooseImport(source)">导入{{ source.displayName }}</n-button>
            <n-button size="small" :aria-label="`查看榜单作品：${source.displayName}`" :disabled="!latestSnapshot(source)" @click="viewLatestSnapshot(source)">查看榜单作品</n-button>
          </div>
        </article>
       </div>
       <MarketSnapshotWorks
         :snapshot="selectedDetail"
         :source="selectedSource"
         :loading="detailLoading"
         :error="selectedDetailFailure"
         :attached="selectedDetail ? isSelected(selectedDetail) : false"
         @toggle-attachment="selectedDetail && toggleEvidence({ ...selectedDetail, source: selectedSource })"
       />
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
.evidence-browser { display:grid; grid-template-columns:minmax(300px,.38fr) minmax(0,1fr); gap:12px; min-width:0; }
.source-list { display:grid; align-content:start; gap:8px; max-height:680px; overflow-y:auto; padding-right:5px; outline:none; scrollbar-gutter:stable; }
.source-list:focus-visible { outline:2px solid #9a4938; outline-offset:2px; }
.source-card { padding:12px 13px; border:1px solid #e1d6c5; background:#fbf7ef; }
.source-card.active { border-color:#ae7667; box-shadow:inset 3px 0 #9a4938; background:#fffdf8; }
.source-card h3 { margin:3px 0 0; font:650 15px 'Noto Serif SC','Songti SC',serif; }
.source-card dl { display:grid; gap:4px; margin:10px 0; }
.source-card dl div { display:grid; grid-template-columns:76px minmax(0,1fr); gap:10px; font-size:11px; }
.source-card dt { color:#92775c; }.source-card dd { margin:0; color:#514940; }
.card-actions { justify-content:flex-start; flex-wrap:wrap; }
.visually-hidden { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); }
@media(max-width:1080px){.evidence-browser{grid-template-columns:minmax(270px,.42fr) minmax(0,1fr)}}
@media(max-width:720px){.market-panel{padding:16px}.evidence-browser{grid-template-columns:1fr}.source-list{max-height:none;overflow-y:visible}.panel-heading{align-items:flex-start}}
</style>
