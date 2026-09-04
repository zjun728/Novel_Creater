<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import BibleEditor from './BibleEditor.vue'
import { createModalFocusManager } from '../common/modalFocusManager.js'
import { bibleHistoryStatusLabel, presentBibleReasons } from '../../application/bible/bibleStatusPresentation.js'

const props = defineProps({ history: { type: Array, default: () => [] }, historyNextBeforeRevision: { default: null }, historyDetail: { type: Object, default: null }, open: Boolean, busy: Boolean, error: { type: Object, default: null }, retryLabel: { type: String, default: '重试历史' } })
const emit = defineEmits(['close', 'detail', 'more', 'retry'])
const teleportEnabled = typeof document !== 'undefined'
const basisFields = [['selectionRevision', '选择版本'], ['seedId', '种子'], ['seedRevisionId', '种子修订'], ['seedHash', '种子哈希'], ['contractRevision', '契约版本'], ['creationContractId', '创作契约'], ['creationHash', '创作哈希'], ['styleContractId', '风格契约'], ['styleHash', '风格哈希'], ['bindingRevisionId', '绑定版本'], ['bindingHash', '绑定哈希'], ['policyVersion', '策略版本']]
const dialog = ref(null); const errorTarget = ref(null)
const detailReasonLabels = computed(() => presentBibleReasons(props.historyDetail?.reasons))
let pageScrollSnapshot = null
const focusManager = createModalFocusManager({ getDialog: () => dialog.value, getInitialFocus: () => dialog.value })
function capturePageScroll() {
  if (pageScrollSnapshot) return
  const target = globalThis.document?.querySelector?.('#main-content')
  if (!target) return
  pageScrollSnapshot = { target, top: target.scrollTop || 0, left: target.scrollLeft || 0 }
}
function restorePageScroll() {
  const snapshot = pageScrollSnapshot
  pageScrollSnapshot = null
  if (!snapshot || snapshot.target.isConnected === false) return
  if (typeof snapshot.target.scrollTo === 'function') {
    snapshot.target.scrollTo({ top: snapshot.top, left: snapshot.left, behavior: 'auto' })
    return
  }
  snapshot.target.scrollTop = snapshot.top
  snapshot.target.scrollLeft = snapshot.left
}
function unmountFocus() {
  focusManager.unmount()
  restorePageScroll()
}
watch(() => props.open, async open => {
  if (open) { capturePageScroll(); await nextTick(); if (props.open) focusManager.mount() }
  else unmountFocus()
}, { immediate: true })
watch(() => props.error, async error => { if (error && props.open) { await nextTick(); errorTarget.value?.focus?.() } })
function handleKeydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); if (!props.busy) emit('close'); return }
  if (event.key === 'Tab' && !focusManager.trapTab(event)) {
    event.preventDefault()
    dialog.value?.focus?.({ preventScroll: true })
  }
}
onBeforeUnmount(unmountFocus)
</script>
<template>
  <Teleport to="body" :disabled="!teleportEnabled">
    <aside v-if="open" ref="dialog" class="history-overlay" role="dialog" aria-modal="true" aria-label="创作圣经历史" tabindex="-1" :aria-busy="busy || undefined" @keydown="handleKeydown">
      <section class="history-sheet"><button aria-label="关闭历史" :disabled="busy" @click="emit('close')">×</button><h2>修订历史</h2><p class="history-note">权威修订记录仅供阅读与核对，不可恢复为草稿。</p>
        <section v-if="error" ref="errorTarget" class="modal-error-summary" tabindex="-1" role="alert"><strong>{{ error.message }}</strong><span v-if="error.correlationId">参考编号：{{ error.correlationId }}</span><button type="button" :disabled="busy" @click="emit('retry')">{{ retryLabel }}</button></section>
<article v-for="item in history" :key="item.bibleRevisionId || item.revision"><strong>Revision {{ item.revision }}</strong><p>{{ bibleHistoryStatusLabel(item.status) }} · {{ item.confirmedAt || '未确认' }}</p><button :disabled="busy" @click="emit('detail', item.revision)">查看详情</button><small>历史修订仅供查看与核对。</small></article>
        <section v-if="historyDetail" class="history-detail"><h3>Revision {{ historyDetail.revision }}</h3><bible-editor v-if="historyDetail.bible" :model-value="historyDetail.bible" read-only :disabled="busy" /><p v-for="reason in detailReasonLabels" :key="reason">{{ reason }}</p><dl><template v-for="[key, label] in basisFields" :key="key"><dt>{{ label }}</dt><dd>{{ historyDetail.basis?.[key] ?? '—' }}</dd></template></dl></section>
        <button v-if="historyNextBeforeRevision !== null" :disabled="busy" @click="emit('more')">加载更早修订</button>
      </section>
    </aside>
  </Teleport>
</template>
<style scoped>
.history-overlay { position:fixed; inset:0; z-index:20; display:flex; min-width:0; justify-content:flex-end; background:color-mix(in srgb,var(--nc-ink) 38%,transparent); }.history-sheet { box-sizing:border-box; width:min(460px,100%); max-height:100dvh; min-width:0; overflow-x:clip; overflow-y:auto; overscroll-behavior:contain; padding:28px; color:var(--nc-ink); background:var(--nc-paper); box-shadow:-16px 0 48px color-mix(in srgb,var(--nc-ink) 22%,transparent); }.history-note { color:var(--nc-muted); font-size:12px; line-height:1.65; }.history-sheet article { min-width:0; margin:14px 0; padding:14px; border:1px solid var(--nc-border); }.history-sheet button { margin:6px 0; color:var(--nc-vermilion); }.history-detail { min-width:0; color:var(--nc-muted); }.history-detail dd { min-width:0; overflow-wrap:anywhere; word-break:break-word; }.modal-error-summary { display:grid; min-width:0; gap:8px; margin:12px 0; padding:12px; border:1px solid var(--nc-vermilion); color:var(--nc-ink); background:color-mix(in srgb,var(--nc-paper) 92%,var(--nc-canvas)); }
@media (prefers-reduced-motion:reduce) { .history-sheet, .history-sheet * { scroll-behavior:auto !important; transition:none !important; animation:none !important; } }
</style>
