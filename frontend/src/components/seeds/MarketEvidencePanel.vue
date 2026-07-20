<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NSpin, NTag } from 'naive-ui'

import { useAppMessage } from '@/composables/useAppMessage'
import { useMarketSourceStore } from '@/stores/marketSourceStore'

const props = defineProps({
  projectId: { type: String, required: true },
  readOnly: { type: Boolean, default: false },
  commandKey: { type: Function, required: true },
})

const market = useMarketSourceStore()
const message = useAppMessage()
const fileInput = ref(null)
const importSourceId = ref('')
const intervalDrafts = reactive({})
const scheduleRevisions = reactive({})
const syncedConflictRevisions = reactive({})
const snapshotDetailLoading = ref([])

const selectedSnapshotManifest = computed(() => market.sources
  .map(source => {
    const snapshot = market.snapshotHistory[source.id]?.[0]
    return snapshot ? { ...snapshot, source } : null
  })
  .filter(Boolean)
  .slice(0, 4))
const latestSnapshotIds = computed(() => (
  selectedSnapshotManifest.value.map(snapshot => snapshot.id)
))
const analysisCoverageSnapshots = computed(() => {
  const ids = market.analysisState.result?.analysis?.sourceCoverage?.snapshotIds
  return Array.isArray(ids) ? ids.map(snapshotRecord).filter(Boolean) : []
})
const analysisSections = Object.freeze([
  ['currentHeat', '当前热度'],
  ['growthDirections', '增长方向'],
  ['crowding', '拥挤赛道'],
  ['opportunities', '可切入机会'],
  ['uncertainties', '不确定性'],
])
const analysisStatements = computed(() => analysisSections.flatMap(([key]) => (
  market.analysisState.result?.analysis?.[key] || []
)))
const hasUnresolvedAnalysisCitations = computed(() => (
  analysisStatements.value.some(statement => !statementIsVerifiable(statement))
))

watch(
  () => market.sources,
  rows => {
    for (const source of rows) {
      const revision = Number(source.scheduleRevision || 0)
      const revisionChanged = scheduleRevisions[source.id] !== revision
      const conflicted = market.scheduleConflictSourceId === source.id
        && syncedConflictRevisions[source.id] !== revision
      if (
        intervalDrafts[source.id] == null
        || revisionChanged
        || conflicted
      ) {
        intervalDrafts[source.id] = Number(source.scheduleIntervalMinutes || 360)
      }
      scheduleRevisions[source.id] = revision
      if (conflicted) syncedConflictRevisions[source.id] = revision
    }
  },
  { deep: true },
)

function dateTime(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return '尚无'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(number < 10_000_000_000 ? number * 1000 : number))
}

function policyLabel(source) {
  if (source.policyStatus === 'verified_public') return '公开来源已核验'
  if (source.policyStatus === 'manual_only') return '仅手动导入'
  return '来源已停用'
}

function freshnessLabel(source) {
  const state = market.sourceState(source.id).freshness
  if (state === 'available-with-later-failure') return '保留上次成功 · 最新刷新失败'
  if (state === 'available') return '快照可用'
  if (state === 'failed') return '尚无成功快照 · 刷新失败'
  return '尚无快照'
}

function snapshotRecord(snapshotId) {
  for (const source of market.sources) {
    const snapshot = (market.snapshotHistory[source.id] || [])
      .find(item => item.id === snapshotId)
    if (snapshot) return { ...snapshot, source }
  }
  return null
}

function statementCitations(statement) {
  return Array.isArray(statement?.snapshotIds)
    ? statement.snapshotIds.map(snapshotRecord).filter(Boolean)
    : []
}

function statementIsVerifiable(statement) {
  return Array.isArray(statement?.snapshotIds)
    && statement.snapshotIds.length > 0
    && statement.snapshotIds.every(snapshotId => snapshotRecord(snapshotId))
}

function snapshotSourceLabel(snapshot) {
  return snapshot.source.displayName
}

function shortSnapshotId(snapshotId) {
  const value = String(snapshotId)
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value
}

async function loadSnapshotEvidence(snapshot, event) {
  if (!event.currentTarget.open || !snapshot.sourceId) return
  if (
    market.snapshotDetails[snapshot.id]
    || snapshotDetailLoading.value.includes(snapshot.id)
  ) return
  snapshotDetailLoading.value = [...snapshotDetailLoading.value, snapshot.id]
  try {
    await market.loadSnapshotDetail(snapshot.sourceId, snapshot.id)
  } catch (error) {
    message.error(error?.message || '快照条目暂时无法加载')
  } finally {
    snapshotDetailLoading.value = snapshotDetailLoading.value
      .filter(id => id !== snapshot.id)
  }
}

async function refresh(source) {
  try {
    await market.refreshSource(source.id, props.commandKey())
    message.success(`${source.displayName} 已发布新快照`)
  } catch (error) {
    message.error(error?.message || '来源刷新失败')
  }
}

function chooseManualFile(sourceId) {
  importSourceId.value = sourceId
  fileInput.value?.click()
}

async function importFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !importSourceId.value) return
  try {
    const snapshot = JSON.parse(await file.text())
    await market.importManualSnapshot(
      importSourceId.value,
      snapshot,
      props.commandKey(),
    )
    message.success('手动快照已校验并发布')
  } catch (error) {
    message.error(error instanceof SyntaxError ? '文件不是有效的快照 JSON' : error?.message)
  } finally {
    importSourceId.value = ''
  }
}

async function updateSchedule(source, enabled) {
  try {
    await market.updateSchedule(source.id, {
      expectedRevision: source.scheduleRevision,
      enabled,
      intervalMinutes: Math.min(
        525_600,
        Math.max(1, Math.trunc(Number(intervalDrafts[source.id] || 360))),
      ),
      idempotencyKey: props.commandKey(),
    })
    message.success(enabled ? '自动刷新计划已启用' : '自动刷新计划已停用')
  } catch (error) {
    if (Number(error?.status) === 409) {
      message.warning('刷新计划已被其他操作修改，已载入最新状态，请重新确认。')
    } else {
      message.error(error?.message || '刷新计划更新失败')
    }
  }
}

async function analyze() {
  try {
    await market.analyze(props.projectId, {
      snapshotIds: latestSnapshotIds.value,
      idempotencyKey: props.commandKey(),
    })
  } catch (error) {
    if (Number(error?.status) !== 422) message.error(error?.message || '市场分析失败')
  }
}
</script>

<template>
  <section class="market-evidence" aria-labelledby="market-evidence-heading">
    <header class="market-evidence__heading">
      <div>
        <p>PUBLIC EVIDENCE / IMMUTABLE SNAPSHOTS</p>
        <h2 id="market-evidence-heading">市场证据</h2>
        <span>榜单只作为选题参考。每张来源卡可手动导入快照；页面明确展示新鲜度与失败，不把推断冒充事实。</span>
      </div>
      <n-tag :bordered="false">{{ latestSnapshotIds.length }} 份可用快照</n-tag>
    </header>

    <n-alert v-if="market.error && !market.loading" type="error" class="market-evidence__alert">
      市场证据暂时无法完整加载。手动创建种子仍可正常使用。
    </n-alert>

    <n-spin :show="market.loading">
      <div v-if="market.sources.length" class="source-grid">
        <article v-for="source in market.sources" :key="source.id" class="source-sheet">
          <header>
            <div>
              <span>{{ source.platform }} · {{ source.rankingName }}</span>
              <h3>{{ source.displayName }}</h3>
            </div>
            <n-tag
              :type="source.policyStatus === 'verified_public' ? 'success' : 'warning'"
              size="small"
            >
              {{ policyLabel(source) }}
            </n-tag>
          </header>
          <dl>
            <div><dt>快照状态</dt><dd>{{ freshnessLabel(source) }}</dd></div>
            <div><dt>上次成功</dt><dd>{{ dateTime(source.lastSucceededAt) }}</dd></div>
            <div><dt>最新快照</dt><dd>{{ source.lastSnapshotId || '尚无' }}</dd></div>
            <div v-if="source.publicErrorCode">
              <dt>后续失败</dt><dd>{{ source.publicErrorCode }}</dd>
            </div>
          </dl>
          <div class="source-sheet__actions">
            <n-button
              size="small"
              :loading="market.sourceOperationId === source.id"
              :disabled="readOnly || source.policyStatus !== 'verified_public'"
              @click="refresh(source)"
            >
              手动刷新
            </n-button>
            <n-button
              size="small"
              :disabled="readOnly || market.sourceOperationId === source.id"
              @click="chooseManualFile(source.id)"
            >
              手动导入快照
            </n-button>
          </div>
          <div class="schedule-strip">
            <label>
              <span>每隔</span>
              <input
                v-model.number="intervalDrafts[source.id]"
                type="number"
                min="1"
                max="525600"
                :disabled="readOnly || source.policyStatus !== 'verified_public'"
              >
              <span>分钟</span>
            </label>
            <n-button
              v-if="source.scheduleEnabled"
              size="tiny"
              :disabled="readOnly || market.sourceOperationId === source.id"
              @click="updateSchedule(source, false)"
            >
              停用定时
            </n-button>
            <n-button
              v-else
              size="tiny"
              :disabled="readOnly || source.policyStatus !== 'verified_public' || market.sourceOperationId === source.id"
              @click="updateSchedule(source, true)"
            >
              启用定时
            </n-button>
          </div>
          <p v-if="market.scheduleExplanation(source.id)" class="source-sheet__explanation">
            {{ market.scheduleExplanation(source.id) }}
          </p>
          <p v-if="market.scheduleConflictSourceId === source.id" class="source-sheet__conflict">
            计划版本发生冲突，已载入最新版本。
          </p>
        </article>
      </div>
      <n-empty v-else-if="!market.loading" description="尚未配置公开证据来源。你仍可直接手动创建种子。" />
    </n-spin>

    <input
      ref="fileInput"
      class="visually-hidden"
      type="file"
      accept="application/json,.json"
      @change="importFile"
    >

    <section
      v-if="selectedSnapshotManifest.length"
      class="snapshot-evidence-list"
      aria-labelledby="snapshot-evidence-heading"
    >
      <header>
        <div>
          <p>ANALYSIS INPUT MANIFEST</p>
          <h3 id="snapshot-evidence-heading">本次分析证据清单</h3>
        </div>
        <span>本次分析固定使用每个来源的最新快照，共 {{ selectedSnapshotManifest.length }} 份。</span>
      </header>
      <details
        v-for="snapshot in selectedSnapshotManifest"
        :key="snapshot.id"
        @toggle="loadSnapshotEvidence(snapshot, $event)"
      >
        <summary>
          <strong>{{ snapshotSourceLabel(snapshot) }}</strong>
          <span>{{ dateTime(snapshot.capturedAt) }}</span>
          <code :title="snapshot.id">{{ shortSnapshotId(snapshot.id) }}</code>
          <small>{{ snapshot.entryCount }} 条榜单记录 · 展开核验</small>
        </summary>
        <p v-if="snapshotDetailLoading.includes(snapshot.id)" role="status">
          正在读取这份冻结快照的公开榜单条目……
        </p>
        <ol
          v-else-if="market.snapshotDetails[snapshot.id]?.entries?.length"
          class="snapshot-entry-list"
        >
          <li
            v-for="entry in market.snapshotDetails[snapshot.id].entries"
            :key="`${snapshot.id}-${entry.rank}`"
          >
            <b>{{ entry.rank }}</b>
            <span>
              <strong>{{ entry.title }}</strong>
              <small>{{ entry.author }} · {{ entry.category }}</small>
            </span>
          </li>
        </ol>
        <p v-else>展开后仅加载后端已发布的标准化公开条目，不展示原始网页或隐藏字段。</p>
      </details>
    </section>

    <section class="analysis-sheet" aria-labelledby="market-analysis-heading">
      <header>
        <div>
          <p>FROZEN ANALYSIS</p>
          <h3 id="market-analysis-heading">冻结快照分析</h3>
        </div>
        <n-button
          type="primary"
          :loading="market.analysisLoading"
          :disabled="readOnly || !latestSnapshotIds.length"
          @click="analyze"
        >
          分析上述 {{ latestSnapshotIds.length }} 份证据
        </n-button>
      </header>

      <n-alert v-if="market.analysisState.status === 'not-ready'" type="warning" :bordered="false">
        市场分析尚未就绪；系统不会补写虚构结论。可继续手动创建种子。
      </n-alert>
      <n-alert v-else-if="market.analysisState.status === 'failed'" type="error" :bordered="false">
        本次分析失败（{{ market.analysisState.publicErrorCode }}），没有生成替代结果。
      </n-alert>
      <div
        v-else-if="market.analysisState.status === 'available'"
        class="analysis-result"
      >
        <n-alert
          v-if="hasUnresolvedAnalysisCitations"
          type="warning"
          :bordered="false"
        >
          部分结论的引用快照当前无法核验，已隐藏；请重新分析当前证据集。
        </n-alert>
        <aside class="analysis-coverage">
          <strong>覆盖说明</strong>
          <p>{{ market.analysisState.result.analysis.sourceCoverage.summary }}</p>
          <div>
            <code
              v-for="snapshot in analysisCoverageSnapshots"
              :key="snapshot.id"
              :title="snapshot.id"
            >
              {{ snapshotSourceLabel(snapshot) }} · {{ shortSnapshotId(snapshot.id) }}
            </code>
          </div>
        </aside>
        <div class="analysis-grid">
          <article v-for="[key, label] in analysisSections" :key="key">
            <h4>{{ label }}</h4>
            <ul v-if="market.analysisState.result.analysis[key]?.length">
              <template
                v-for="(statement, index) in market.analysisState.result.analysis[key]"
                :key="`${key}-${index}`"
              >
                <li v-if="statementIsVerifiable(statement)">
                  <p>
                    {{ statement.text }}
                    <span v-if="statement.inference">推断</span>
                  </p>
                  <div class="analysis-citations" aria-label="引用快照">
                    <code
                      v-for="snapshot in statementCitations(statement)"
                      :key="snapshot.id"
                      :title="snapshot.id"
                    >
                      {{ snapshotSourceLabel(snapshot) }} ·
                      {{ dateTime(snapshot.capturedAt) }} · {{ shortSnapshotId(snapshot.id) }}
                    </code>
                  </div>
                </li>
              </template>
            </ul>
            <p v-else>本批证据没有支持的结论。</p>
          </article>
        </div>
      </div>
      <p v-else class="analysis-sheet__empty">
        选择最新快照后再分析。分析结论必须逐条引用冻结快照。
      </p>
    </section>
  </section>
</template>

<style scoped>
.market-evidence { color: #302a23; }
.market-evidence__heading, .analysis-sheet > header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
}
.market-evidence__heading p, .analysis-sheet header p {
  margin: 0 0 6px;
  color: #963f32;
  font: 700 10px Georgia, serif;
  letter-spacing: .17em;
}
h2, h3 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; }
h2 { font-size: clamp(25px, 4vw, 36px); }
.market-evidence__heading span { display: block; margin-top: 9px; color: #786d60; font-size: 12px; line-height: 1.7; }
.market-evidence__alert { margin-top: 18px; }
.source-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 20px; }
.source-sheet { padding: 20px; border: 1px solid #d8cab3; border-radius: 10px; background: rgba(255, 253, 247, .88); }
.source-sheet > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.source-sheet header span { color: #9b8061; font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.source-sheet h3 { margin-top: 5px; font-size: 18px; }
.source-sheet dl { display: grid; gap: 7px; margin: 17px 0; padding: 13px 0; border-block: 1px solid #e6dccb; }
.source-sheet dl div { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 10px; }
.source-sheet dt { color: #8d7d68; font-size: 12px; }
.source-sheet dd { margin: 0; overflow: hidden; color: #4f473e; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.source-sheet__actions { display: flex; gap: 7px; }
.schedule-strip { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 13px; padding: 9px 10px; border-radius: 7px; background: #f3ecdf; }
.schedule-strip label { display: flex; align-items: center; gap: 6px; color: #746859; font-size: 12px; }
.schedule-strip input { width: 78px; padding: 5px 7px; border: 1px solid #cdbda4; border-radius: 4px; color: inherit; background: #fffdf8; }
.source-sheet__explanation, .source-sheet__conflict { margin: 9px 0 0; color: #8b6c42; font-size: 12px; line-height: 1.55; }
.source-sheet__conflict { color: #963f32; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
.snapshot-evidence-list { margin-top: 24px; padding: 20px; border: 1px solid #d6c7af; border-radius: 10px; background: #faf5eb; }
.snapshot-evidence-list > header { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 13px; }
.snapshot-evidence-list header p { margin: 0 0 5px; color: #963f32; font: 700 10px Georgia, serif; letter-spacing: .15em; }
.snapshot-evidence-list h3 { font-size: 20px; }
.snapshot-evidence-list > header > span { max-width: 48ch; color: #766a5b; font-size: 12px; line-height: 1.6; text-align: right; }
.snapshot-evidence-list details { border-top: 1px solid #ded2bf; }
.snapshot-evidence-list summary { display: grid; grid-template-columns: 1fr auto; gap: 5px 14px; padding: 13px 4px; color: #4e453b; cursor: pointer; }
.snapshot-evidence-list summary > span, .snapshot-evidence-list summary > small { color: #7c7062; font-size: 12px; }
.snapshot-evidence-list summary code { grid-column: 1 / -1; overflow-wrap: anywhere; color: #8a5a45; font-size: 11px; }
.snapshot-evidence-list details > p { margin: 0 4px 14px; color: #7a6e60; font-size: 12px; }
.snapshot-entry-list { display: grid; max-height: 300px; gap: 7px; margin: 0 4px 14px; padding: 0; overflow-y: auto; list-style: none; }
.snapshot-entry-list li { display: grid; grid-template-columns: 28px 1fr; gap: 8px; align-items: start; padding: 8px 10px; background: #fffdf8; }
.snapshot-entry-list li > b { color: #963f32; font: 700 12px Georgia, serif; }
.snapshot-entry-list li > span { display: grid; gap: 2px; }
.snapshot-entry-list li small { color: #7a6d5e; font-size: 12px; }
.analysis-sheet { margin-top: 24px; padding: 22px; border: 1px solid #cfc0a8; border-radius: 10px; background: linear-gradient(120deg, #fffaf0, #f6efe2); }
.analysis-sheet > header { margin-bottom: 17px; }
.analysis-sheet h3 { font-size: 20px; }
.analysis-result { display: grid; gap: 12px; }
.analysis-coverage { padding: 14px 16px; border: 1px solid #d9cbb5; background: rgba(255, 253, 248, .72); }
.analysis-coverage > strong { font-size: 13px; }
.analysis-coverage p { margin: 5px 0 9px; color: #6f6456; font-size: 13px; line-height: 1.65; }
.analysis-coverage div { display: flex; flex-wrap: wrap; gap: 5px; }
.analysis-coverage code, .analysis-citations code { padding: 3px 6px; border: 1px solid #d8cab2; border-radius: 4px; color: #765344; background: #fffdf8; font-size: 10px; overflow-wrap: anywhere; }
.analysis-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.analysis-grid article { padding: 13px 14px; border-left: 3px solid #ad9472; background: rgba(255, 253, 248, .72); }
.analysis-grid h4 { margin: 0 0 8px; font-size: 14px; }
.analysis-grid ul { display: grid; gap: 12px; margin: 0; padding-left: 17px; color: #5f5548; font-size: 13px; line-height: 1.65; }
.analysis-grid li > p { margin: 0; }
.analysis-grid li > p span { margin-left: 6px; padding: 2px 5px; border: 1px solid #cdbda4; border-radius: 99px; color: #8e643f; font-size: 10px; }
.analysis-citations { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.analysis-grid article > p, .analysis-sheet__empty { margin: 0; color: #887b6b; font-size: 13px; }
@media (max-width: 820px) {
  .source-grid, .analysis-grid { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .market-evidence__heading, .analysis-sheet > header, .snapshot-evidence-list > header { align-items: flex-start; flex-direction: column; }
  .snapshot-evidence-list > header > span { text-align: left; }
  .snapshot-evidence-list summary { grid-template-columns: 1fr; }
  .schedule-strip { align-items: flex-start; flex-direction: column; }
}
</style>
