<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NDescriptions, NDescriptionsItem, NResult, NSpin, NTag } from 'naive-ui'
import { useCreationContractStore } from '@/stores/creationContractStore'
import { createLatestRequestGuard } from '@/utils/latestRequest.js'
import ContractDecisionSummary from './ContractDecisionSummary.vue'

const props = defineProps({ projectId: { type: String, required: true } })
const emit = defineEmits(['back', 'confirmed', 'reload'])
const store = useCreationContractStore()
const loadError = ref('')
const confirmError = ref('')
const errorRegion = ref(null)
const previewLoadGuard = createLatestRequestGuard()

function commandKey() {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `contract-confirm-${suffix}`.slice(0, 64)
}

const idempotencyKey = commandKey()
const preview = computed(() => store.previewResult)

const reasonText = {
  contract_missing: '尚未建立完整契约草稿',
  binding_incomplete: '八项模型任务尚未全部绑定',
  binding_not_ready: '模型绑定当前不可用',
  binding_drift: '模型绑定已发生变化，请重新冻结',
  seed_drift: '选定种子已发生变化，请重新冻结',
  engine_drift: '故事发动机已发生变化，请重新冻结',
  style_drift: '风格模板已发生变化，请重新冻结',
  asset_drift: '经验卡或语料已发生变化，请重新冻结',
}

function shortHash(value) {
  const text = String(value || '')
  return text ? `${text.slice(0, 12)}…` : '—'
}

function explain(reason) {
  return reasonText[reason] || reason
}

async function loadPreview() {
  const generation = previewLoadGuard.begin()
  loadError.value = ''
  confirmError.value = ''
  try {
    await store.preview(props.projectId)
  } catch (error) {
    if (!previewLoadGuard.isCurrent(generation)) return
    loadError.value = error?.message || '契约预览生成失败'
    await nextTick()
    if (!previewLoadGuard.isCurrent(generation)) return
    errorRegion.value?.focus({ preventScroll: false })
  }
}

async function confirmContract() {
  confirmError.value = ''
  try {
    const result = await store.confirm(props.projectId, { idempotencyKey })
    emit('confirmed', result)
  } catch (error) {
    confirmError.value = error?.message || '契约确认结果未知'
    await nextTick()
    errorRegion.value?.focus({ preventScroll: false })
  }
}

watch(() => props.projectId, () => loadPreview(), { immediate: true })
onBeforeUnmount(() => previewLoadGuard.invalidate())
</script>

<template>
  <article class="preview-step">
    <header class="step-heading">
      <div><span>STEP 05 · COMPLETE REVIEW</span><h3>预览全部变化，再一次确认</h3><p>本页只读汇总五步决定；签印后当前修订不可覆盖。</p></div>
      <n-tag :type="store.contractReady ? 'success' : 'warning'" round>
        {{ store.contractReady ? '可以签印' : '尚未就绪' }}
      </n-tag>
    </header>

    <div v-if="store.previewing" class="loading"><n-spin size="large" /><span>正在核对全部冻结引用…</span></div>
    <n-result v-else-if="loadError" ref="errorRegion" tabindex="-1" status="error" title="无法形成契约预览" :description="loadError" aria-live="assertive">
      <template #footer><n-button @click="loadPreview">重新加载并核对</n-button></template>
    </n-result>

    <template v-else-if="preview">
      <n-alert v-if="store.readinessReasons.length" type="warning" title="签印前仍需处理">
        <ul><li v-for="reason in store.readinessReasons" :key="reason">{{ explain(reason) }}</li></ul>
        <template #action><n-button size="small" @click="emit('reload')">重新加载并核对</n-button></template>
      </n-alert>

      <section class="snapshot" aria-labelledby="frozen-snapshot-heading">
        <h4 id="frozen-snapshot-heading">冻结快照</h4>
        <n-descriptions :column="2" bordered label-placement="left" size="small">
          <n-descriptions-item label="种子修订">{{ preview.seedRef?.revisionId || '—' }}</n-descriptions-item>
          <n-descriptions-item label="种子摘要">{{ shortHash(preview.seedRef?.contentHash) }}</n-descriptions-item>
          <n-descriptions-item label="发动机批次">{{ preview.engineRef?.batchId || '—' }}</n-descriptions-item>
          <n-descriptions-item label="发动机摘要">{{ shortHash(preview.engineRef?.contentHash) }}</n-descriptions-item>
          <n-descriptions-item label="绑定修订">R{{ preview.bindingRef?.revision ?? '—' }}</n-descriptions-item>
          <n-descriptions-item label="绑定摘要">{{ shortHash(preview.bindingRef?.contentHash) }}</n-descriptions-item>
          <n-descriptions-item label="创作契约摘要">{{ shortHash(preview.creationHash) }}</n-descriptions-item>
          <n-descriptions-item label="风格契约摘要">{{ shortHash(preview.styleHash) }}</n-descriptions-item>
        </n-descriptions>
      </section>

      <ContractDecisionSummary
        v-if="preview.creationContract || preview.styleContract"
        :creation-contract="preview.creationContract"
        :style-contract="preview.styleContract"
        :likes="preview.likes"
        :dislikes="preview.dislikes"
        heading="作者即将确认的创作约定"
      />

      <div class="reference-grid">
        <section>
          <h4>风格模板</h4>
          <p v-if="!preview.styleRefs?.length">未选择</p>
          <p v-for="ref in preview.styleRefs" :key="ref.id">{{ ref.id }} · R{{ ref.revision }} · {{ shortHash(ref.contentHash) }}</p>
        </section>
        <section>
          <h4>经验卡</h4>
          <p>{{ preview.experienceCardRefs?.length || 0 }} 张已冻结</p>
          <small v-for="ref in preview.experienceCardRefs" :key="ref.id">{{ ref.id }} · R{{ ref.revision }} · {{ shortHash(ref.contentHash) }}</small>
        </section>
        <section>
          <h4>参考语料</h4>
          <p>{{ preview.corpusSourceRefs?.length || 0 }} 个来源已冻结</p>
          <small v-for="ref in preview.corpusSourceRefs" :key="ref.id">{{ ref.id }} · R{{ ref.revision }} · {{ ref.selectionMode }} · {{ shortHash(ref.contentHash) }}</small>
        </section>
      </div>

      <section class="binding-sheet">
        <h4>八项模型任务绑定</h4>
        <div v-for="item in preview.bindingRef?.items || []" :key="item.taskKey" class="binding-line">
          <strong>{{ item.taskKey }}</strong>
          <span>{{ item.providerNameSnapshot || '未绑定' }} / {{ item.modelNameSnapshot || '—' }}</span>
          <n-tag size="small" :type="item.resolutionStatus === 'ready' ? 'success' : 'warning'">{{ item.resolutionStatus }}</n-tag>
        </div>
      </section>

      <n-alert v-if="confirmError" ref="errorRegion" tabindex="-1" type="error" title="确认没有得到明确结果" aria-live="assertive">
        {{ confirmError }}。再次点击会使用同一幂等命令核对，不会创建重复修订。
      </n-alert>

      <footer class="step-actions">
        <n-button :disabled="store.confirming" @click="emit('back')">返回容量约定</n-button>
        <div class="seal-action">
          <span>签印成功后进入“等待滚动规划”，写作台仍保持关闭。</span>
          <n-button
            type="primary"
            size="large"
            :loading="store.confirming"
            :disabled="store.confirming || store.requiresReload || !store.contractReady"
            @click="confirmContract"
          >{{ confirmError ? '使用同一命令重试' : '一次确认完整契约' }}</n-button>
        </div>
      </footer>
    </template>
  </article>
</template>

<style scoped>
.preview-step { padding: 28px 30px 32px; }
.step-heading, .step-actions, .binding-line { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.step-heading span { color: var(--cinnabar, #9c3d2f); font: 700 10px Georgia, serif; letter-spacing: .15em; }
.step-heading h3 { margin: 4px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 25px; }
.loading { display: grid; place-items: center; gap: 12px; min-height: 260px; color: var(--muted, #7c7163); }
.snapshot, .binding-sheet, .reference-grid { margin-top: 24px; }
h4 { margin: 0 0 11px; color: var(--ink, #574c3e); font: 650 14px 'Noto Serif SC', serif; }
ul { margin: 7px 0 0; padding-left: 18px; }
.reference-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.reference-grid section { min-height: 108px; padding: 16px; border: 1px solid var(--rule, #e1d6c4); border-radius: 8px; background: var(--paper, #faf6ed); }
.reference-grid p, .reference-grid small { display: block; margin: 5px 0 0; color: var(--muted, #74695b); font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
.binding-sheet { border-top: 1px solid var(--rule, #ded2bf); }
.binding-sheet h4 { margin-top: 18px; }
.binding-line { padding: 9px 3px; border-bottom: 1px dashed var(--rule, #ded2bf); font-size: 12px; }
.binding-line span { flex: 1; color: var(--muted, #756a5d); }
.step-actions { align-items: flex-end; margin-top: 28px; padding-top: 22px; border-top: 1px solid var(--rule, #d9ccb7); }
.seal-action { display: grid; justify-items: end; gap: 8px; }
.seal-action span { color: var(--muted, #817668); font-size: 11px; }
@media (max-width: 760px) { .reference-grid { grid-template-columns: 1fr; } .step-actions { align-items: stretch; flex-direction: column; } .seal-action { justify-items: stretch; } }
</style>
