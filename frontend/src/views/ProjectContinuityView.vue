<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/db/client.js'
import FutureDesignPanel from '../components/continuity/FutureDesignPanel.vue'
import ContinuityRecordDetails from '../components/continuity/ContinuityRecordDetails.vue'
import ContinuityHistoryPanel from '../components/continuity/ContinuityHistoryPanel.vue'
import { recordLabel, CONTINUITY_KINDS, ENTITY_TYPES, createContinuityController } from '../application/continuity/continuityController.js'
import { continuityIssuesPath, finalChapterPath, projectOverviewPath, projectBiblePath, planningPlotsPath } from '../router/projectRoutes.js'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => String(route.params.projectId || ''))
const defaultKind = computed(() => ({ settings: 'facts', 'state-memory': 'state', arcs: 'arcs', clues: 'clues' }[route.params.section] || 'facts'))
const sectionInfo = computed(() => ({
  settings: { title: '设定库', description: '阅读已定稿的设定条目；创作意图与实际记录分别查看。', kinds: ['facts'] },
  'state-memory': { title: '当前状态与记忆', description: '查看正文中的实际状态与重要记忆，每项记录保留来源。', kinds: ['state', 'memory', 'progress'] },
  arcs: { title: '人物弧光', description: '查看人物已经发生的变化，并对照未来计划。', kinds: ['arcs'] },
  clues: { title: '线索与伏笔', description: '查看线索的实际推进与原文依据。', kinds: ['clues'] },
}[route.params.section] || { title: '设定库', description: '阅读已定稿的设定条目。', kinds: ['facts'] }))
const kind = computed(() => sectionInfo.value.kinds.includes(route.query.kind) ? route.query.kind : defaultKind.value)
const entityId = computed(() => typeof route.query.entity === 'string' ? route.query.entity : '')
const controller = createContinuityController({ api })
const state = controller.state
const offset = ref(0)
const query = ref('')
const entityType = ref('')
const entities = ref([])
const entityNext = ref(null)
const entityRevision = ref(null)
const entityOffset = ref(0)
const entityMessage = ref('')
const searchBusy = ref(false)
const evidence = ref(null)
const historyRecord = ref(null)
const evidenceBusy = ref(false)
const evidenceMessage = ref('')
let searchGeneration = 0
let evidenceGeneration = 0
let closed = false

async function searchEntities(nextOffset = 0) {
  const generation = ++searchGeneration
  const id = projectId.value
  searchBusy.value = true
  entityMessage.value = ''
  if (!nextOffset) { entities.value = []; entityRevision.value = null; entityNext.value = null }
  try {
    const page = await api.continuity.entities(id, { query: query.value, ...(entityType.value ? { entity_type: entityType.value } : {}), offset: nextOffset, ...(nextOffset ? { revision: entityRevision.value } : {}) })
    if (closed || generation !== searchGeneration || id !== projectId.value) return
    if (page.projectId !== id || !Array.isArray(page.items)
      || !Number.isSafeInteger(page.revision) || page.revision < 0
      || (nextOffset && page.revision !== entityRevision.value)
      || (page.nextOffset !== null && (!Number.isSafeInteger(page.nextOffset) || page.nextOffset <= nextOffset))) throw new Error('Invalid entity page')
    entities.value = page.items
    entityOffset.value = nextOffset
    entityNext.value = page.nextOffset
    entityRevision.value = page.revision
  } catch {
    if (closed || generation !== searchGeneration) return
    entities.value = []
    entityNext.value = null
    entityMessage.value = '设定列表暂时无法读取，请重新查找。'
  } finally { if (!closed && generation === searchGeneration) searchBusy.value = false }
}

function filters(nextOffset = 0) {
  return { kind: kind.value, ...(entityId.value ? { entity_id: entityId.value } : {}), offset: nextOffset,
    ...(nextOffset && state.value.data ? { revision: state.value.data.revision } : {}) }
}
async function load(nextOffset = 0) {
  historyRecord.value = null
  offset.value = nextOffset
  evidenceGeneration += 1
  evidence.value = null
  evidenceMessage.value = ''
  evidenceBusy.value = false
  await controller.load(projectId.value, filters(nextOffset))
}
function selectEntity(id) { void router.push({ query: { ...route.query, entity: id || undefined } }) }
function selectKind(value) { void router.push({ query: { ...route.query, kind: value } }) }
async function showEvidence(eventId) {
  const generation = ++evidenceGeneration
  evidence.value = null
  evidenceMessage.value = ''
  evidenceBusy.value = true
  try {
    const result = await api.continuity.evidence(projectId.value, eventId)
    if (closed || generation !== evidenceGeneration) return
    if (result.projectId !== projectId.value || result.eventId !== eventId) throw new Error('Invalid evidence')
    evidence.value = result
  } catch { if (!closed && generation === evidenceGeneration) evidenceMessage.value = '原文依据暂时无法读取，请重试。' }
  finally { if (!closed && generation === evidenceGeneration) evidenceBusy.value = false }
}
watch(projectId, () => { query.value = ''; entityType.value = ''; void searchEntities() }, { immediate: true })
watch(() => [projectId.value, kind.value, entityId.value], () => { void load() }, { immediate: true })
onBeforeUnmount(() => { closed = true; searchGeneration += 1; evidenceGeneration += 1; controller.dispose() })
</script>

<template>
  <section class="continuity-page">
    <header class="continuity-heading">

      <h1>{{ sectionInfo.title }}</h1>
      <p>{{ sectionInfo.description }}</p>
    </header>
    <div class="continuity-layout">
      <details class="entity-directory" aria-label="设定查找">
        <summary>按人物与设定查找{{ state.data?.entity?.name ? ` · ${state.data.entity.name}` : '' }}</summary>
        <form @submit.prevent="searchEntities()">
          <label for="continuity-entity-type">设定类别</label>
          <select id="continuity-entity-type" v-model="entityType" @change="searchEntities()"><option value="">全部类别</option><option v-for="(label, value) in ENTITY_TYPES" :key="value" :value="value">{{ label }}</option></select>
          <label for="continuity-search">按名称查找</label>
          <div class="search-row"><input id="continuity-search" v-model="query" maxlength="100" /><button :disabled="searchBusy">查找</button></div>
        </form>
        <button class="entity-choice" :aria-pressed="!entityId" @click="selectEntity('')">全书记录与世界规则</button>
        <p v-if="searchBusy" role="status">正在读取设定…</p>
        <p v-else-if="entityMessage" role="alert">{{ entityMessage }}</p>
        <p v-else-if="!entities.length" class="muted">{{ query ? '没有匹配的已定稿设定。' : '尚无已定稿实体。创作基础中的未来设定仍可查看。' }}</p>
        <ul>
          <li v-for="entity in entities" :key="entity.id"><button class="entity-choice" :aria-pressed="entityId === entity.id" @click="selectEntity(entity.id)"><span>{{ entity.name }}</span><small>{{ ENTITY_TYPES[entity.type] || '设定' }}</small></button></li>
        </ul>
        <button v-if="entityNext !== null" :disabled="searchBusy" @click="searchEntities(entityNext)">下一页设定</button>
        <button :disabled="searchBusy" @click="searchEntities()">{{ entityOffset ? '返回第一页设定' : '重新读取设定' }}</button>
      </details>
      <section class="continuity-content" aria-label="连续性详情">

        <nav v-if="sectionInfo.kinds.length > 1" class="record-tabs" aria-label="设定详情分类"><button v-for="key in sectionInfo.kinds" :key="key" :aria-pressed="kind === key" @click="selectKind(key)">{{ CONTINUITY_KINDS[key] }}</button></nav>
        <section aria-live="polite" :aria-busy="state.status === 'loading'">
          <p v-if="state.status === 'loading'" role="status">正在读取{{ CONTINUITY_KINDS[kind] }}…</p>
          <div v-else-if="state.status === 'error'" role="alert"><p>{{ state.message }}</p><button @click="load()">重新读取</button></div>
          <template v-else-if="state.data">
            <div class="records-heading"><h2>{{ state.data.entity?.name ? `${state.data.entity.name} · ` : '' }}{{ CONTINUITY_KINDS[kind] }}</h2><span class="muted">来自已定稿正文</span></div>
            <div v-if="!state.data.items.length" class="empty-records"><h3>暂时没有这类记录</h3><p>章节定稿后，经作者确认的事实将在这里显示。没有记录不代表人物弧光或故事线已经完成。</p></div>
            <article v-for="record in state.data.items" :key="record.id" class="continuity-record">
              <h3 v-if="kind === 'progress'">{{ record.targetTitle || '尚无法核对规划节点名称' }}</h3>
              <header><button v-if="record.entityId" class="text-button" @click="selectEntity(record.entityId)">{{ record.entityName || '关联设定' }}</button><strong v-else>全书记录</strong><small>{{ recordLabel(record.field) }}</small><small v-if="record.isClaim">人物说法 · 不等同客观事实</small></header>
              <div class="record-content"><ContinuityRecordDetails :record="record" :kind="kind" />
              <button v-if="['state', 'arcs', 'clues'].includes(kind)" @click="historyRecord = record">查看变化历史</button>
              <ContinuityHistoryPanel v-if="historyRecord?.id === record.id" :project-id="projectId" :record="historyRecord" :revision="state.data.revision" @close="historyRecord = null" @evidence="showEvidence" />
              </div><footer><router-link v-if="record.sourceChapter" :to="finalChapterPath(projectId, record.sourceChapter)">来源：第 {{ record.sourceChapter }} 章</router-link><span v-else class="muted">暂无定稿章节来源</span><button v-if="record.sourceEventId" :disabled="evidenceBusy" @click="showEvidence(record.sourceEventId)">查看原文依据</button></footer>
            </article>
            <div class="page-actions"><button v-if="offset" @click="load()">返回第一页</button><button v-if="state.data.nextOffset !== null" @click="load(state.data.nextOffset)">下一页记录</button></div>
          </template>
        </section>
        <details class="future-disclosure"><summary>查看创作设定与未来计划</summary>
        <FutureDesignPanel :project-id="projectId" :revision="state.data?.revision ?? null" :snapshot="state.data" :entity-id="state.data?.entity?.id || ''" :entity-name="state.data?.entity?.name || ''" />
        </details>
        <section v-if="evidenceBusy || evidence || evidenceMessage" class="evidence-sheet" aria-live="polite"><h2>原文依据</h2><p v-if="evidenceBusy">正在校验原文…</p><p v-else-if="evidenceMessage">{{ evidenceMessage }}</p><template v-else-if="evidence"><blockquote v-if="evidence.verified">{{ evidence.excerpt }}</blockquote><p v-else>无法核对这条记录的原文位置，请阅读来源章节。未将不匹配的文字当作证据展示。</p><div class="design-links"><router-link v-if="evidence.chapterNumber" :to="finalChapterPath(projectId, evidence.chapterNumber)">阅读第 {{ evidence.chapterNumber }} 章</router-link><router-link v-if="evidence.chapterNumber" :to="{ path: continuityIssuesPath(projectId), query: { sourceChapterNumber: evidence.chapterNumber } }">记录本章连续性问题</router-link></div></template></section>
      </section>
    </div>
    <footer class="continuity-actions">
      <p>实际记录来自已定稿章节；未来计划不直接改写事实。</p>
      <router-link :to="route.params.section === 'settings' ? projectBiblePath(projectId) : planningPlotsPath(projectId)">{{ route.params.section === 'settings' ? '查看创作圣经' : '查看故事规划' }}</router-link>
      <router-link class="continue-link" :to="projectOverviewPath(projectId)">返回继续创作</router-link>
    </footer>
  </section>
</template>

<style scoped>
.future-disclosure{margin-top:24px;border-top:1px solid var(--nc-border);padding-top:16px}.future-disclosure>summary{cursor:pointer;color:var(--nc-vermilion);font-size:13px;margin-bottom:16px}.continuity-actions{max-width:1320px;margin:24px auto 0;display:flex;gap:20px;align-items:center;padding:18px 24px;background:var(--nc-paper);border-top:1px solid var(--nc-border)}.continuity-actions p{margin-right:auto;color:var(--nc-muted);font-size:13px}.continue-link{background:var(--nc-vermilion);color:white;padding:12px 24px;border-radius:6px;text-decoration:none}@media(max-width:800px){.continuity-actions{flex-wrap:wrap}}

.entity-directory select{display:block;width:100%;margin-bottom:16px;padding:8px;border:1px solid var(--nc-border);background:var(--nc-paper);color:inherit;font:inherit;font-size:13px}.entity-directory select:focus-visible{outline:2px solid var(--nc-vermilion);outline-offset:3px}
.search-row button{flex-shrink:0;white-space:nowrap}
.continuity-page{min-height:100%;padding:clamp(20px,3vw,48px);background:var(--nc-canvas);color:var(--nc-ink)}
.continuity-heading{max-width:1320px;margin:0 auto 28px}.eyebrow{color:var(--nc-vermilion);letter-spacing:.14em;font-size:12px}h1{font-family:var(--nc-font-serif,serif);font-size:32px;margin:10px 0}h2{font-size:17px;margin:0 0 12px}h3{font-size:17px}.continuity-heading>p:last-child,.muted{color:var(--nc-muted);font-size:13px;line-height:1.8}
.continuity-layout{max-width:1320px;margin:auto;display:grid;grid-template-columns:240px minmax(0,1fr);gap:24px;align-items:start}.entity-directory,.continuity-content{padding:24px;background:var(--nc-paper);border:1px solid var(--nc-border);min-width:0}.entity-directory ul{list-style:none;padding:0;margin:12px 0}.entity-directory label{display:block;font-size:12px;margin-bottom:8px}.search-row{display:flex;gap:6px;margin-bottom:20px}.search-row input{width:100%;min-width:0;padding:8px;border:1px solid var(--nc-border);background:transparent;color:inherit}button{cursor:pointer;font:inherit;font-size:13px;padding:7px 10px;border:1px solid var(--nc-border);background:transparent;color:inherit}button:disabled{opacity:.5;cursor:wait}button:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid var(--nc-vermilion);outline-offset:3px}.entity-choice{display:flex;justify-content:space-between;gap:8px;width:100%;text-align:left;border:0;padding:12px 8px}.entity-choice small{color:var(--nc-muted);white-space:nowrap}.entity-choice[aria-pressed=true]{background:var(--nc-canvas);color:var(--nc-vermilion)}.future-design{padding-bottom:20px;border-bottom:1px solid var(--nc-border)}.future-design p{font-size:13px;color:var(--nc-muted);line-height:1.8}.design-links{display:flex;gap:20px}a{font-size:13px;color:var(--nc-vermilion);text-underline-offset:4px}.record-tabs{display:flex;flex-wrap:wrap;gap:4px;padding:20px 0}.record-tabs button{border-color:transparent}.record-tabs button[aria-pressed=true]{border-bottom-color:var(--nc-vermilion);color:var(--nc-vermilion)}.records-heading{display:flex;justify-content:space-between;gap:12px}.continuity-record{padding:20px 0;border-bottom:1px solid var(--nc-border);overflow-wrap:anywhere}.continuity-record header,.continuity-record footer{display:flex;gap:16px;align-items:center;flex-wrap:wrap}.continuity-record p{line-height:1.9;white-space:pre-wrap}.continuity-record header small{color:var(--nc-muted)}.text-button{border:0;padding:0;color:var(--nc-vermilion);font-weight:600}.empty-records{padding:32px 0;color:var(--nc-muted);line-height:1.8}.page-actions{display:flex;gap:12px;margin-top:20px}.evidence-sheet{margin-top:24px;padding:24px;background:var(--nc-canvas)}blockquote{margin:16px 0;white-space:pre-wrap;line-height:1.9;overflow-wrap:anywhere;border-left:2px solid var(--nc-vermilion);padding-left:18px}@media(max-width:900px){.continuity-layout{grid-template-columns:1fr}.entity-directory ul{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.continuity-content{padding:18px}}

.continuity-page{padding:24px 36px}.continuity-heading{margin-bottom:24px}.continuity-layout{grid-template-columns:minmax(0,1fr);gap:16px}.entity-directory{padding:14px 20px}.entity-directory>summary{cursor:pointer;font-size:13px;color:var(--nc-vermilion)}.entity-directory[open]>summary{margin-bottom:18px}.entity-directory form{display:grid;grid-template-columns:100px minmax(160px,1fr) 100px minmax(200px,2fr);align-items:center;gap:12px}.entity-directory form select,.search-row{margin-bottom:0}.entity-directory ul{display:flex;flex-wrap:wrap;gap:12px}.entity-directory li{min-width:160px}.continuity-record{display:grid;grid-template-columns:150px minmax(0,1fr) 160px;gap:20px}.continuity-record>header,.continuity-record>footer{flex-direction:column;align-items:flex-start;justify-content:flex-start;gap:10px}.record-content{min-width:0}.record-content :deep(h3){margin-top:0}.record-content :deep(p){margin-top:8px}.continuity-actions{position:sticky;bottom:0;z-index:2;margin-bottom:0}
@media(max-width:800px){.entity-directory form{grid-template-columns:1fr}.continuity-record{grid-template-columns:1fr}.continuity-record>header,.continuity-record>footer{flex-direction:row}.continuity-page{padding:20px 16px}}
</style>
