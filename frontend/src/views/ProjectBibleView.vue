<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { bibleReasonLabel, createBibleWorkspaceController } from '../application/bible/bibleWorkspaceController.js'
import BibleEditor from '../components/bible/BibleEditor.vue'
import BibleHistoryDrawer from '../components/bible/BibleHistoryDrawer.vue'
import { createModalFocusManager } from '../components/common/modalFocusManager.js'
import { useRouteProject } from '../composables/useRouteProject.js'
import { useBibleStore } from '../stores/bibleStore.js'
import NotFoundView from './NotFoundView.vue'

const routeProject = useRouteProject()
const store = useBibleStore()
const notice = ref('')
const errorTarget = ref(null)
const confirmTarget = ref(null)
const confirmDialog = ref(null)
const statusTarget = ref(null)
const teleportEnabled = typeof document !== 'undefined'
const projectId = computed(() => routeProject.project.value?.id || '')
const locked = computed(() => routeProject.state.value === 'archived' || store.readOnly)
const workspace = createBibleWorkspaceController({
  store,
  projectId: () => projectId.value,
  isArchived: () => routeProject.state.value === 'archived',
  focusError: () => errorTarget.value?.focus(),
  focusConfirm: () => confirmTarget.value?.focus(),
  focusStatus: () => statusTarget.value?.focus(),
  confirmLeave: () => window.confirm('存在未保存的创作圣经编辑。确定离开吗？'),
})
const { working, confirmOpen, historyOpen, errorSummary, busy, mode, activeStatus, editable, canSave, canConfirm, confirmPreview, reasonLabels, cloneSource } = workspace
const editorDisabled = computed(() => busy.value)
const hasConflict = computed(() => errorSummary.value?.status === 409)
const confirmFocus = createModalFocusManager({
  getDialog: () => confirmDialog.value,
  getInitialFocus: () => confirmTarget.value,
})

async function hydrate() {
  if (!projectId.value) return
  await workspace.hydrate()
}
watch(() => [projectId.value, routeProject.state.value], () => {
  notice.value = ''
  void hydrate().catch(() => {})
}, { immediate: true })
watch(confirmOpen, async open => {
  if (open) { await nextTick(); confirmFocus.mount() } else confirmFocus.unmount()
})

function edit(value) { workspace.edit(value) }
async function save() {
  try { if (await workspace.save()) notice.value = '草稿已保存' } catch {}
}
async function confirm() {
  try { if (await workspace.confirm()) notice.value = '已确认新的创作圣经修订' } catch {}
}
async function clone(source) {
  try { if (await workspace.clone(source)) { historyOpen.value = false; notice.value = '已创建未来设计草稿' } } catch {}
}
function openHistory() { void workspace.openHistory().catch(() => {}) }
function showHistoryDetail(revision) { void workspace.showHistoryDetail(revision).catch(() => {}) }
function loadMoreHistory() { void workspace.loadMoreHistory().catch(() => {}) }
async function retryHydrate() {
  try { await workspace.hydrate() } catch {}
}
async function reloadAuthoritative() {
  if (store.dirty && !window.confirm('重新加载将覆盖本地未保存内容。确定继续吗？')) return
  try {
    const result = await workspace.hydrate()
    if (result !== undefined) notice.value = '已重新加载权威版本'
  } catch {}
}
function handleConfirmKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    if (!busy.value) workspace.closeConfirm()
    return
  }
  confirmFocus.trapTab(event)
}

onBeforeRouteLeave(() => workspace.requestLeave())
onBeforeRouteUpdate(() => workspace.requestLeave())
onMounted(() => window.addEventListener('beforeunload', workspace.beforeUnload))
onBeforeUnmount(() => { window.removeEventListener('beforeunload', workspace.beforeUnload); confirmFocus.unmount() })
</script>

<template>
  <main class="bible-page">
    <section v-if="errorSummary" ref="errorTarget" class="error-summary" tabindex="-1" role="alert" aria-live="assertive">
      <strong>{{ errorSummary.message }}</strong>
      <span v-if="errorSummary.correlationId">参考编号：{{ errorSummary.correlationId }}</span>
      <button v-if="hasConflict" type="button" @click="reloadAuthoritative">重新加载权威版本</button>
      <button v-else type="button" @click="retryHydrate">重试</button>
    </section>
    <p v-if="notice" class="status-note" aria-live="polite">{{ notice }}</p>
    <section v-if="routeProject.state.value === 'loading'" class="sheet">正在装订创作圣经…</section>
    <not-found-view v-else-if="routeProject.state.value === 'missing'" title="项目不存在" description="无法打开创作圣经。" />
    <section v-else-if="routeProject.state.value === 'error'" class="sheet">项目加载失败。<button @click="routeProject.reload">重试</button></section>
    <section v-else class="sheet" :aria-busy="busy || undefined">
      <div class="workspace-content" :inert="busy || undefined">
        <header><p>CREATION BIBLE · {{ activeStatus || mode.toUpperCase() }}</p><h1 ref="statusTarget" tabindex="-1">{{ routeProject.project.value?.title }} 的创作圣经</h1><button :disabled="busy" @click="openHistory">修订历史</button></header>
        <aside class="ai-not-ready" aria-label="AI 辅助状态">AI 辅助：Not Ready（下一阶段接入，不影响手动保存与确认）</aside>
        <p v-for="reason in reasonLabels" :key="reason" class="status-note">{{ reason }}</p>
        <p v-if="mode === 'superseded'" class="status-note">此修订已被替代，内容仅供复制与查阅。</p>
        <p v-if="locked || mode === 'archived'" class="status-note">此项目或当前服务端状态为只读。</p>
        <bible-editor v-if="working" :model-value="working" :read-only="!editable" :disabled="editorDisabled" @update:model-value="edit" />
        <footer v-if="editable"><button :disabled="!canSave" @click="save">手动保存</button><span v-if="store.dirty">请先保存后再确认</span><button :disabled="!canConfirm" @click="workspace.openConfirm($event.currentTarget)">预览并确认</button></footer>
        <button v-if="cloneSource" :disabled="busy" @click="clone(cloneSource)">调整未来设计</button>
        <Teleport to="body" :disabled="!teleportEnabled">
          <div v-if="confirmOpen" class="confirm-overlay">
            <section ref="confirmDialog" class="confirm-panel" role="dialog" aria-modal="true" aria-label="确认新的未来设计" @keydown="handleConfirmKeydown"><h2>确认新的未来设计</h2><p>确认会创建不可变修订。请核对已保存的完整快照。</p><bible-editor v-if="confirmPreview" :model-value="confirmPreview" read-only :disabled="busy" /><button ref="confirmTarget" @click="confirm">确认签印</button><button :disabled="busy" @click="workspace.closeConfirm">返回编辑</button></section>
          </div>
        </Teleport>
      </div>
      <div v-if="busy" class="busy-overlay" role="status" aria-live="polite" aria-busy="true">正在处理创作圣经…</div>
    </section>
    <bible-history-drawer :history="store.history" :history-next-before-revision="store.historyNextBeforeRevision" :history-detail="store.historyDetail" :open="historyOpen" :read-only="locked" :busy="busy" :label-reason="bibleReasonLabel" @close="historyOpen = false" @clone="clone" @detail="showHistoryDetail" @more="loadMoreHistory" />
  </main>
</template>

<style scoped>
.bible-page { min-height:100%; padding:clamp(18px,4vw,54px); color:var(--nc-ink); background:var(--nc-canvas); }.sheet { position:relative; width:min(960px,100%); margin:auto; padding:clamp(22px,4vw,46px); border:1px solid var(--nc-border); background:repeating-linear-gradient(0deg,var(--nc-paper),var(--nc-paper) 27px,color-mix(in srgb,var(--nc-paper) 94%,var(--nc-canvas)) 28px); box-shadow:0 24px 64px color-mix(in srgb,var(--nc-ink) 11%,transparent); }.sheet header { display:flex; flex-wrap:wrap; align-items:end; gap:12px; border-bottom:2px solid var(--nc-vermilion); padding-bottom:16px; }.sheet header p { width:100%; margin:0; color:var(--nc-vermilion); font:700 11px Georgia,serif; letter-spacing:.16em; }.sheet h1 { flex:1; margin:0; font:600 clamp(30px,5vw,52px) Georgia,'Noto Serif SC',serif; }.sheet button { border:1px solid var(--nc-vermilion); padding:8px 12px; color:var(--nc-vermilion); background:var(--nc-paper); font:650 14px Georgia,'Noto Serif SC',serif; }.sheet footer { display:flex; gap:10px; margin-top:24px; }.status-note,.ai-not-ready { padding:10px; border-left:3px solid var(--nc-vermilion); color:var(--nc-muted); }.ai-not-ready { margin:14px 0; border-color:var(--nc-muted); background:color-mix(in srgb,var(--nc-paper) 92%,var(--nc-canvas)); }.confirm-overlay { position:fixed; z-index:30; inset:0; display:grid; padding:24px; place-items:center; background:color-mix(in srgb,var(--nc-ink) 38%,transparent); }.confirm-panel,.error-summary { padding:18px; border:1px solid var(--nc-vermilion); background:var(--nc-paper); }.confirm-panel { width:min(900px,100%); max-height:calc(100vh - 48px); overflow:auto; color:var(--nc-ink); box-shadow:0 24px 64px color-mix(in srgb,var(--nc-ink) 22%,transparent); }.error-summary { display:grid; gap:8px; width:min(960px,100%); margin:0 auto 12px; color:var(--nc-ink); }.busy-overlay { position:absolute; inset:0; display:grid; place-items:center; color:var(--nc-paper); background:color-mix(in srgb,var(--nc-ink) 55%,transparent); font-weight:700; } @media(max-width:620px){.bible-page{padding:12px}.sheet{padding:20px}.sheet footer{flex-direction:column}}
</style>
