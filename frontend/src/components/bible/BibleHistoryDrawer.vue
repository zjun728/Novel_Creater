<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import BibleEditor from './BibleEditor.vue'
import { createModalFocusManager } from '../common/modalFocusManager.js'

const props = defineProps({ history: { type: Array, default: () => [] }, historyNextBeforeRevision: { default: null }, historyDetail: { type: Object, default: null }, open: Boolean, busy: Boolean, error: { type: Object, default: null }, retryLabel: { type: String, default: '重试历史' }, labelReason: { type: Function, default: value => `状态需重新核对（${value}）` } })
const emit = defineEmits(['close', 'detail', 'more', 'retry'])
const teleportEnabled = typeof document !== 'undefined'
const basisFields = [['selectionRevision', '选择版本'], ['seedId', '种子'], ['seedRevisionId', '种子修订'], ['seedHash', '种子哈希'], ['contractRevision', '契约版本'], ['creationContractId', '创作契约'], ['creationHash', '创作哈希'], ['styleContractId', '风格契约'], ['styleHash', '风格哈希'], ['bindingRevisionId', '绑定版本'], ['bindingHash', '绑定哈希'], ['policyVersion', '策略版本']]
const dialog = ref(null); const errorTarget = ref(null)
const focusManager = createModalFocusManager({ getDialog: () => dialog.value, getInitialFocus: () => dialog.value })
watch(() => props.open, async open => { if (open) { await nextTick(); focusManager.mount() } else focusManager.unmount() }, { immediate: true })
watch(() => props.error, async error => { if (error && props.open) { await nextTick(); errorTarget.value?.focus?.() } })
function handleKeydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); if (!props.busy) emit('close'); return }
  focusManager.trapTab(event)
}
onBeforeUnmount(focusManager.unmount)
</script>
<template>
  <Teleport to="body" :disabled="!teleportEnabled">
    <aside v-if="open" ref="dialog" class="history-overlay" role="dialog" aria-modal="true" aria-label="创作圣经历史" tabindex="-1" :aria-busy="busy || undefined" @keydown="handleKeydown">
      <section class="history-sheet"><button aria-label="关闭历史" :disabled="busy" @click="emit('close')">×</button><h2>修订历史</h2>
        <section v-if="error" ref="errorTarget" class="modal-error-summary" tabindex="-1" role="alert" aria-live="assertive"><strong>{{ error.message }}</strong><span v-if="error.correlationId">参考编号：{{ error.correlationId }}</span><button type="button" :disabled="busy" @click="emit('retry')">{{ retryLabel }}</button></section>
<article v-for="item in history" :key="item.bibleRevisionId || item.revision"><strong>Revision {{ item.revision }}</strong><p>{{ item.status }} · {{ item.confirmedAt || '未确认' }}</p><button :disabled="busy" @click="emit('detail', item.revision)">查看详情</button><small>历史修订仅供查看与核对。</small></article>
        <section v-if="historyDetail" class="history-detail"><h3>Revision {{ historyDetail.revision }}</h3><bible-editor v-if="historyDetail.bible" :model-value="historyDetail.bible" read-only :disabled="busy" /><p v-for="reason in historyDetail.reasons || []" :key="reason">{{ labelReason(reason) }}</p><dl><template v-for="[key, label] in basisFields" :key="key"><dt>{{ label }}</dt><dd>{{ historyDetail.basis?.[key] ?? '—' }}</dd></template></dl></section>
        <button v-if="historyNextBeforeRevision !== null" :disabled="busy" @click="emit('more')">加载更早修订</button>
      </section>
    </aside>
  </Teleport>
</template>
<style scoped>
.history-overlay { position:fixed; inset:0; z-index:20; display:flex; justify-content:flex-end; background:color-mix(in srgb,var(--nc-ink) 38%,transparent); }.history-sheet { width:min(460px,100%); overflow:auto; padding:28px; color:var(--nc-ink); background:var(--nc-paper); box-shadow:-16px 0 48px color-mix(in srgb,var(--nc-ink) 22%,transparent); }.history-sheet article { margin:14px 0; padding:14px; border:1px solid var(--nc-border); }.history-sheet button { margin:6px 0; color:var(--nc-vermilion); }.history-detail { color:var(--nc-muted); }.modal-error-summary { display:grid; gap:8px; margin:12px 0; padding:12px; border:1px solid var(--nc-vermilion); color:var(--nc-ink); background:color-mix(in srgb,var(--nc-paper) 92%,var(--nc-canvas)); }
</style>
