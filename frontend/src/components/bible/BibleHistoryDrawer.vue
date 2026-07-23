<script setup>
import BibleEditor from './BibleEditor.vue'

defineProps({ history: { type: Array, default: () => [] }, historyNextBeforeRevision: { default: null }, historyDetail: { type: Object, default: null }, open: Boolean, readOnly: Boolean, busy: Boolean, labelReason: { type: Function, default: value => `状态需重新核对（${value}）` } })
const emit = defineEmits(['close', 'clone', 'detail', 'more'])
const basisFields = [['selectionRevision', '选择版本'], ['seedId', '种子'], ['seedRevisionId', '种子修订'], ['seedHash', '种子哈希'], ['contractRevision', '契约版本'], ['creationContractId', '创作契约'], ['creationHash', '创作哈希'], ['styleContractId', '风格契约'], ['styleHash', '风格哈希'], ['bindingRevisionId', '绑定版本'], ['bindingHash', '绑定哈希'], ['policyVersion', '策略版本']]
</script>
<template>
  <aside v-if="open" class="history-overlay" role="dialog" aria-modal="true" aria-label="创作圣经历史" :aria-busy="busy || undefined">
    <section class="history-sheet"><button aria-label="关闭历史" @click="emit('close')">×</button><h2>修订历史</h2>
      <article v-for="item in history" :key="item.bibleRevisionId || item.revision"><strong>Revision {{ item.revision }}</strong><p>{{ item.status }} · {{ item.confirmedAt || '未确认' }}</p><button :disabled="busy" @click="emit('detail', item.revision)">查看详情</button><button v-if="!readOnly && item.canClone" :disabled="busy" @click="emit('clone', item)">Adjust Future Design</button></article>
      <section v-if="historyDetail" class="history-detail"><h3>Revision {{ historyDetail.revision }}</h3><bible-editor v-if="historyDetail.bible" :model-value="historyDetail.bible" disabled /><p v-for="reason in historyDetail.reasons || []" :key="reason">{{ labelReason(reason) }}</p><dl><template v-for="[key, label] in basisFields" :key="key"><dt>{{ label }}</dt><dd>{{ historyDetail.basis?.[key] ?? '—' }}</dd></template></dl></section>
      <button v-if="historyNextBeforeRevision !== null" :disabled="busy" @click="emit('more')">加载更早修订</button>
    </section>
  </aside>
</template>
<style scoped>
.history-overlay { position:fixed; inset:0; z-index:20; display:flex; justify-content:flex-end; background:rgba(39,28,20,.38); }.history-sheet { width:min(460px,100%); overflow:auto; padding:28px; color:#302a23; background:#fffaf0; box-shadow:-16px 0 48px rgba(38,25,15,.22); }.history-sheet article { margin:14px 0; padding:14px; border:1px solid #d8cbb7; }.history-sheet button { margin:6px 0; }
</style>
