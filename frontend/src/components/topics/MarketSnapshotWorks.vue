<script setup>
import { computed } from 'vue'
import { NButton, NEmpty, NSpin, NTag } from 'naive-ui'

const props = defineProps({
  snapshot: { type: Object, default: null },
  source: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: [Error, Object, String], default: null },
  attached: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle-attachment'])

const metricLabels = Object.freeze({
  status: '连载状态',
  wordCount: '字数',
  score: '作品积分',
  publishedAt: '更新时间',
  weeklyRecommendations: '周推荐',
  recommendations: '推荐数',
  clicks: '点击数',
  readers: '阅读人数',
  popularity: '热度',
  intro: '简介',
  description: '简介',
  tags: '标签',
  numbers: '公开数据',
  counters: '公开数据',
})

const failureMessage = computed(() => {
  if (!props.error) return ''
  if (typeof props.error === 'string') return props.error
  return props.error.message || '榜单作品暂时无法读取，请稍后手动重试。'
})
const loadAnnouncement = computed(() => {
  if (props.loading) return `正在读取${props.source?.displayName || ''}榜单作品`
  if (props.error) return `${props.source?.displayName || ''}榜单作品读取失败`
  if (props.snapshot) return `已读取${props.source?.displayName || ''}，共${props.snapshot.entryCount}部作品`
  return ''
})

function timeLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
    .format(new Date(number < 10_000_000_000 ? number * 1000 : number))
}

function metricLabel(key) {
  return metricLabels[key] || key.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
}

function metricValue(value) {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return new Intl.NumberFormat('zh-CN').format(value)
  return value
}

function visibleMetrics(metrics) {
  return Object.entries(metrics || {})
}
</script>

<template>
  <section class="snapshot-reader" aria-labelledby="snapshot-reader-title" :aria-busy="loading">
    <p class="visually-hidden" role="status" aria-live="polite" aria-atomic="true">{{ loadAnnouncement }}</p>
    <n-spin :show="loading">
      <div v-if="snapshot && source" class="snapshot-content">
        <header class="reader-heading">
          <div>
            <p class="eyebrow">RANKED PUBLIC EVIDENCE</p>
            <h2 id="snapshot-reader-title">{{ source.displayName }}</h2>
            <p class="snapshot-meta">
              <span>{{ snapshot.captureMode === 'network' ? '网络刷新' : '人工导入' }}</span>
              <span>{{ timeLabel(snapshot.capturedAt) }}</span>
              <span>{{ snapshot.entryCount }} 部作品</span>
            </p>
          </div>
          <div class="reader-actions">
            <n-tag size="small" :bordered="false">{{ snapshot.adapterVersion }}</n-tag>
            <n-button
              size="small"
              :type="attached ? 'success' : 'default'"
              :aria-pressed="attached"
              @click="emit('toggle-attachment')"
            >
              {{ attached ? '已附加到讨论' : '附加到讨论' }}
            </n-button>
          </div>
        </header>

        <p v-if="failureMessage" class="reader-warning" role="alert">{{ failureMessage }} 已保留上次成功读取的榜单。</p>

        <div class="column-labels" aria-hidden="true">
          <span>排名</span><span>书名 / 作者 / 题材</span><span>公开指标</span><span>原始来源</span>
        </div>
        <ol class="ranked-works" aria-label="榜单作品">
          <li v-for="entry in snapshot.entries" :key="entry.rank" class="ranked-work">
            <span class="rank">{{ String(entry.rank).padStart(2, '0') }}</span>
            <div class="work-identity">
              <h3>{{ entry.title }}</h3>
              <p><span>{{ entry.author }}</span><span>{{ entry.category }}</span></p>
            </div>
            <dl class="work-metrics">
              <div v-for="([key, value]) in visibleMetrics(entry.publicMetrics)" :key="key">
                <dt>{{ metricLabel(key) }}</dt><dd>{{ metricValue(value) }}</dd>
              </div>
              <div v-if="!visibleMetrics(entry.publicMetrics).length" class="metric-empty">
                <dt>公开指标</dt><dd>榜单未公开</dd>
              </div>
            </dl>
            <a :href="entry.workURL" target="_blank" rel="noopener noreferrer">查看原页面<span aria-hidden="true"> ↗</span></a>
          </li>
        </ol>
      </div>
      <div v-else class="reader-empty">
        <p class="eyebrow">RANKED PUBLIC EVIDENCE</p>
        <h2 id="snapshot-reader-title">榜单作品</h2>
        <p v-if="failureMessage" class="reader-warning" role="alert">{{ failureMessage }}</p>
        <n-empty v-else description="从左侧来源选择一份最新快照，查看真实榜单作品。" />
      </div>
    </n-spin>
  </section>
</template>

<style scoped>
.snapshot-reader { min-width:0; border:1px solid #d8c9b5; background:#fffdf8; }
.snapshot-content,.reader-empty { padding:20px 22px; }
.reader-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; padding-bottom:16px; border-bottom:1px solid #ded2c1; }
.eyebrow { margin:0; color:#9a4938; font:750 9px Georgia,serif; letter-spacing:.14em; }
.reader-heading h2,.reader-empty h2 { margin:5px 0 0; font:650 25px 'Noto Serif SC','Songti SC',serif; }
.snapshot-meta { display:flex; flex-wrap:wrap; gap:0; margin:8px 0 0; color:#76695b; font-size:11px; }
.snapshot-meta span+span::before { content:'·'; margin:0 7px; color:#b7a48c; }
.reader-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.reader-warning { margin:12px 0 0; padding:9px 11px; border-left:3px solid #a74a39; color:#70392f; background:#fff3ed; font-size:11px; line-height:1.6; }
.column-labels,.ranked-work { display:grid; grid-template-columns:54px minmax(180px,.85fr) minmax(240px,1.3fr) 92px; gap:14px; align-items:start; }
.column-labels { padding:12px 10px 8px; color:#9b856b; font-size:9px; font-weight:750; letter-spacing:.08em; }
.ranked-works { margin:0; padding:0; list-style:none; border-top:1px solid #e6dccd; }
.ranked-work { padding:15px 10px; border-bottom:1px solid #e6dccd; }
.rank { color:#a8604f; font:650 20px Georgia,serif; }
.work-identity h3 { margin:0; color:#332b25; font:650 17px 'Noto Serif SC','Songti SC',serif; line-height:1.35; }
.work-identity p { display:flex; flex-wrap:wrap; gap:0; margin:6px 0 0; color:#716557; font-size:11px; }
.work-identity p span+span::before { content:'·'; margin:0 6px; color:#b6a58f; }
.work-metrics { display:flex; flex-wrap:wrap; gap:7px 14px; margin:0; }
.work-metrics div { min-width:76px; }
.work-metrics dt { color:#9b856b; font-size:9px; font-weight:700; }
.work-metrics dd { margin:3px 0 0; overflow-wrap:anywhere; color:#554b41; font-size:11px; line-height:1.45; }
.metric-empty dd { color:#9c9184; }
.ranked-work>a { justify-self:end; color:#884333; font-size:11px; text-underline-offset:3px; }
.reader-empty { min-height:270px; }
.reader-empty :deep(.n-empty) { margin-top:54px; }
.visually-hidden { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); }
@media(max-width:900px){
  .column-labels { display:none; }
  .ranked-work { grid-template-columns:42px minmax(0,1fr) 90px; }
  .work-metrics { grid-column:2/-1; }
}
@media(max-width:720px){
  .snapshot-content,.reader-empty { padding:16px; }
  .reader-heading { flex-direction:column; gap:12px; }
  .reader-actions { justify-content:flex-start; }
  .ranked-work { grid-template-columns:36px minmax(0,1fr); gap:10px; padding:14px 4px; }
  .work-metrics,.ranked-work>a { grid-column:2; justify-self:start; }
}
</style>
