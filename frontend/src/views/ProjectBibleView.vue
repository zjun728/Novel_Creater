<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import BibleEditor from '../components/bible/BibleEditor.vue'
import BibleHistoryDrawer from '../components/bible/BibleHistoryDrawer.vue'
import NotFoundView from './NotFoundView.vue'
import { useRouteProject } from '../composables/useRouteProject.js'
import { useBibleStore } from '../stores/bibleStore.js'

const routeProject = useRouteProject()
const store = useBibleStore()
const working = ref(null); const showHistory = ref(false); const confirmOpen = ref(false); const notice = ref(''); const errorSummary = ref(null); const attemptKeys = new Map()
const projectId = computed(() => routeProject.project.value?.id || '')
const locked = computed(() => routeProject.state.value === 'archived' || store.readOnly)
const status = computed(() => store.draft?.status || store.head?.status || '')
async function hydrate() { if (!projectId.value) return; await store.load(projectId.value, { readOnly: routeProject.state.value === 'archived' }); working.value = structuredClone(store.draft?.draft || store.head?.bible || null) }
watch(() => [projectId.value, routeProject.state.value], () => { void hydrate().catch(error => { notice.value = error.message || '创作圣经加载失败' }) }, { immediate:true })
function edit(value) { working.value = value; if (!locked.value) store.edit(value) }
async function save() { try { await store.save(projectId.value); notice.value = '草稿已保存' } catch (error) { errorSummary.value?.focus(); notice.value = store.error?.message || error.message } }
function attemptKey() { const identity = `${projectId.value}:${store.draft?.draftVersion}:${store.head?.revision || 0}`; if (!attemptKeys.has(identity)) attemptKeys.set(identity, `bible-confirm-${identity}-${crypto.randomUUID()}`); return attemptKeys.get(identity) }
async function confirm() { try { await store.confirm(projectId.value, { idempotencyKey: attemptKey() }); confirmOpen.value = false; notice.value = '已确认新的创作圣经修订' } catch (error) { errorSummary.value?.focus(); notice.value = store.error?.message || error.message; if (Number(error?.status) >= 400 && Number(error?.status) < 500) attemptKeys.delete(`${projectId.value}:${store.draft?.draftVersion}:${store.head?.revision || 0}`) } }
async function clone(revision) { await store.clone(projectId.value, { sourceRevision: revision }); working.value = structuredClone(store.draft?.draft || null); showHistory.value = false; notice.value = '已创建未来设计草稿' }
function preventLeave() { return !store.dirty || window.confirm('存在未保存的创作圣经编辑。确定离开吗？') }
onBeforeRouteLeave(preventLeave); onBeforeRouteUpdate(preventLeave)
function beforeUnload(event) { if (store.dirty) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => window.addEventListener('beforeunload', beforeUnload)); onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>
<template>
  <main class="bible-page"><p ref="errorSummary" class="sr-only" tabindex="-1" aria-live="assertive">{{ notice || store.error?.message || store.conflict?.message }}</p>
    <section v-if="routeProject.state.value === 'loading'" class="sheet">正在装订创作圣经…</section>
    <not-found-view v-else-if="routeProject.state.value === 'missing'" title="项目不存在" description="无法打开创作圣经。" />
    <section v-else-if="routeProject.state.value === 'error'" class="sheet">项目加载失败。<button @click="routeProject.reload">重试</button></section>
    <section v-else class="sheet"><header><p>CREATION BIBLE · {{ status || 'DRAFT' }}</p><h1>{{ routeProject.project.value?.title }} 的创作圣经</h1><button @click="showHistory = true">修订历史</button></header>
      <p v-if="store.reasons.length" class="status-note">{{ store.reasons.join('；') }}</p><p v-if="status === 'superseded'" class="status-note">此修订已被替代，内容仅供复制与查阅。</p><p v-if="locked" class="status-note">此项目或当前服务端状态为只读。</p>
      <bible-editor v-if="working" :model-value="working" :disabled="locked || status === 'superseded' || !store.draft" @update:model-value="edit" />
      <footer v-if="store.draft && !locked"><button :disabled="store.saving || !store.dirty" @click="save">手动保存</button><span v-if="store.dirty">请先保存后再确认</span><button :disabled="store.dirty || !store.canConfirm" @click="confirmOpen = true">预览并确认</button></footer>
      <section v-if="confirmOpen" class="confirm-panel" role="dialog" aria-modal="true"><h2>确认新的未来设计</h2><p>确认会创建不可变修订。请核对已保存的完整快照。</p><pre>{{ store.draft?.draft }}</pre><button autofocus @click="confirm">确认签印</button><button @click="confirmOpen = false">返回编辑</button></section>
    </section>
    <bible-history-drawer :store="store" :project-id="projectId" :open="showHistory" :read-only="locked" @close="showHistory = false" @clone="clone" />
  </main>
</template>
<style scoped>
.bible-page { min-height:100%; padding:clamp(18px,4vw,54px); color:#302a23; background:#eee6d7; }.sheet { width:min(960px,100%); margin:auto; padding:clamp(22px,4vw,46px); border:1px solid #cdbda5; background:repeating-linear-gradient(0deg,#fffaf0,#fffaf0 27px,#f8f0e2 28px); box-shadow:0 24px 64px rgba(55,39,25,.11); }.sheet header { display:flex; flex-wrap:wrap; align-items:end; gap:12px; border-bottom:2px solid #9b372b; padding-bottom:16px; }.sheet header p { width:100%; margin:0; color:#9b372b; font:700 11px Georgia,serif; letter-spacing:.16em; }.sheet h1 { flex:1; margin:0; font:600 clamp(30px,5vw,52px) Georgia,'Noto Serif SC',serif; }.sheet button { border:1px solid #9b372b; padding:8px 12px; color:#7e2a22; background:#fff9ed; font:650 14px Georgia,'Noto Serif SC',serif; }.sheet footer { display:flex; gap:10px; margin-top:24px; }.status-note { padding:10px; border-left:3px solid #9b372b; color:#6c5a49; }.confirm-panel { margin-top:18px; padding:18px; border:1px solid #9b372b; background:#f8ecd9; }.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); } @media(max-width:620px){.bible-page{padding:12px}.sheet{padding:20px}.sheet footer{flex-direction:column}}
</style>
