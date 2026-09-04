<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NDescriptions, NDescriptionsItem, NResult, NSpin, NTag } from 'naive-ui'
import FoundationConfirmationDialog from '@/components/foundation/FoundationConfirmationDialog.vue'
import { useCreationContractStore } from '@/stores/creationContractStore'
import { createLatestRequestGuard } from '@/utils/latestRequest.js'
import ContractDecisionSummary from './ContractDecisionSummary.vue'

const props = defineProps({
  projectId: { type: String, required: true },
  confirmation: {
    type: Object,
    default: () => ({ preview: null, draftVersion: null, contentHash: '', canConfirm: false }),
  },
  interactionLocked: { type: Boolean, default: false },
})
const emit = defineEmits(['confirmed', 'reload'])
const store = useCreationContractStore()
const loadError = ref('')
const confirmError = ref('')
const loadErrorRegion = ref(null)
const confirmErrorRegion = ref(null)
const confirmOpen = ref(false)
const previewLoadGuard = createLatestRequestGuard()

function commandKey() {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `contract-confirm-${suffix}`.slice(0, 64)
}

const idempotencyKey = commandKey()
const confirmation = computed(() => props.confirmation || {})
const preview = computed(() => confirmation.value.preview || null)
const previewReasons = computed(() => (
  Array.isArray(preview.value?.reasons) ? preview.value.reasons : []
))

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

function explain(reason) {
  return reasonText[reason] || '状态需要重新核对'
}

function focusControl(reference, options = { preventScroll: false }) {
  const target = typeof reference?.focus === 'function' ? reference : reference?.$el
  target?.focus?.(options)
}

const taskLabels = Object.freeze({
  market: '市场选题', seed: '种子与故事发动机', planning: '创作规划', writing: '正文写作',
  polish: '改写润色', audit: '质量审核', extraction: '定稿提取', summary: '上下文压缩',
})
const resolutionLabels = Object.freeze({
  bound: '已绑定', unbound: '未绑定',
})
const selectionModeLabels = Object.freeze({
  author: '作者选择', system: '系统推荐',
})

function authorReference(reference, fallback, index = 0) {
  if (!reference) return '未选择'
  const name = reference.name || reference.title || `${fallback}${index ? ` ${index}` : ''}`
  const revision = Number(reference.revision || 0)
  return `${name}${revision > 0 ? ` · 第 ${revision} 版` : ' · 已冻结'}`
}

function authorTask(item) {
  return taskLabels[item?.taskKey] || '模型任务'
}

function authorResolution(item) {
  return resolutionLabels[item?.resolutionStatus] || '状态待核对'
}

function diagnosticReference(reference) {
  if (!reference) return '—'
  const revision = reference.revision
  const revisionId = reference.revisionId
  const batch = reference.batchId ? ` · 批次 ${reference.batchId}` : ''
  const logicalRevision = revisionId ? ` · 修订 ${revisionId}` : ''
  const historical = Object.hasOwn(reference, 'pinnedHistoricalRevision')
    ? ` · 历史修订钉住 ${reference.pinnedHistoricalRevision === true ? '是' : '否'}`
    : ''
  const fragments = Array.isArray(reference.fragments) && reference.fragments.length
    ? ` · 片段 ${reference.fragments.map(fragment => (
        `${fragment.chapterId || '未标注章节'} · ${fragment.fragmentId || fragment.id || '—'} ${fragment.chapterCharStart ?? '—'}–${fragment.chapterCharEnd ?? '—'} ${fragment.referenceUse || ''} · ${fragment.fragmentHash || '—'}`.trim()
      )).join('；')}`
    : ''
  return `${reference.name || reference.title || reference.id || '—'}${revision !== undefined ? ` · R${revision}` : ''}${logicalRevision}${batch}${historical} · ${reference.selectionMode || '完整引用'} · ${reference.contentHash || '—'}${fragments}`
}

async function loadPreview() {
  const generation = previewLoadGuard.begin()
  loadError.value = ''
  confirmError.value = ''
  try {
    await store.preview(props.projectId)
  } catch (error) {
    if (!previewLoadGuard.isCurrent(generation)) return
    loadError.value = '服务器暂时无法形成契约预览，请稍后重试。'
    await nextTick()
    if (!previewLoadGuard.isCurrent(generation)) return
    focusControl(loadErrorRegion.value)
  }
}

async function confirmContract() {
  if (props.interactionLocked) return
  if (!confirmation.value.canConfirm || store.confirming || store.requiresReload) return
  confirmError.value = ''
  try {
    const result = await store.confirm(props.projectId, { idempotencyKey })
    confirmOpen.value = false
    emit('confirmed', result)
  } catch (error) {
    confirmError.value = '服务器尚未返回明确的契约确认结果'
    if (store.requiresReload) {
      confirmOpen.value = false
      return
    }
    await nextTick()
    focusControl(confirmErrorRegion.value)
  }
}

watch(() => [props.projectId, confirmation.value.draftVersion], ([projectId]) => {
  const currentDraftVersion = confirmation.value.draftVersion
  if (preview.value?.projectId === projectId
    && preview.value?.draftVersion === currentDraftVersion) return
  void loadPreview()
}, { immediate: true })
onBeforeUnmount(() => previewLoadGuard.invalidate())
</script>

<template>
  <article
    class="preview-step"
    :inert="props.interactionLocked ? '' : undefined"
    :aria-disabled="props.interactionLocked ? 'true' : undefined"
  >
    <header class="step-heading">
      <div><span>创作契约 · 完整核对</span><h3>预览全部变化，再一次确认</h3><p>本节只读汇总整份作者文档；签印后当前修订不可覆盖。</p></div>
      <n-tag :type="confirmation.canConfirm ? 'success' : 'warning'" round>
        {{ confirmation.canConfirm ? '服务器允许签印' : '服务器尚未允许签印' }}
      </n-tag>
    </header>

    <div v-if="store.previewing" class="loading"><n-spin size="large" /><span>正在核对全部冻结引用…</span></div>
    <n-result v-else-if="loadError" ref="loadErrorRegion" tabindex="-1" status="error" title="无法形成契约预览" :description="loadError" aria-live="assertive">
      <template #footer><n-button @click="loadPreview">重新加载并核对</n-button></template>
    </n-result>

    <template v-else-if="preview">
      <n-alert v-if="previewReasons.length" type="warning" title="签印前仍需处理">
        <ul><li v-for="reason in previewReasons" :key="reason">{{ explain(reason) }}</li></ul>
        <n-button size="small" @click="emit('reload')">重新加载并核对</n-button>
      </n-alert>

      <section class="snapshot" aria-labelledby="frozen-snapshot-heading">
        <h4 id="frozen-snapshot-heading">冻结快照</h4>
        <n-descriptions :column="2" bordered label-placement="left" size="small">
          <n-descriptions-item label="创作种子">{{ preview.seedRef ? '创作种子已冻结' : '尚未冻结' }}</n-descriptions-item>
          <n-descriptions-item label="故事发动机">{{ preview.engineRef ? '故事发动机已冻结' : '尚未冻结' }}</n-descriptions-item>
          <n-descriptions-item label="模型任务">{{ preview.bindingRef?.items?.length || 0 }} 项绑定已核对</n-descriptions-item>
          <n-descriptions-item label="创作约定">{{ preview.creationHash ? '内容完整性已核验' : '等待完整性核验' }}</n-descriptions-item>
          <n-descriptions-item label="风格约定">{{ preview.styleHash ? '内容完整性已核验' : '等待完整性核验' }}</n-descriptions-item>
          <n-descriptions-item label="目标版本">{{ preview.expectedRevision ? `第 ${preview.expectedRevision} 版` : '待服务器确认' }}</n-descriptions-item>
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
          <p v-for="(ref, index) in preview.styleRefs" :key="ref.id">{{ authorReference(ref, '风格模板', index + 1) }}</p>
        </section>
        <section>
          <h4>经验卡</h4>
          <p>{{ preview.experienceCardRefs?.length || 0 }} 张已冻结</p>
          <small v-for="(ref, index) in preview.experienceCardRefs" :key="ref.id">{{ authorReference(ref, '经验卡', index + 1) }}</small>
        </section>
        <section>
          <h4>参考语料</h4>
          <p>{{ preview.corpusSourceRefs?.length || 0 }} 个来源已冻结</p>
          <small v-for="(ref, index) in preview.corpusSourceRefs" :key="ref.id">{{ authorReference(ref, '参考语料', index + 1) }} · {{ selectionModeLabels[ref.selectionMode] || '引用方式待核对' }}</small>
        </section>
      </div>

      <section class="binding-sheet">
        <h4>八项模型任务绑定</h4>
        <div v-for="item in preview.bindingRef?.items || []" :key="item.taskKey" class="binding-line">
          <strong>{{ authorTask(item) }}</strong>
          <span>{{ item.providerNameSnapshot || '未绑定模型服务' }} / {{ item.modelNameSnapshot || '未选择模型' }}</span>
          <n-tag size="small" :type="item.resolutionStatus === 'bound' ? 'success' : 'warning'">{{ authorResolution(item) }}</n-tag>
        </div>
      </section>

      <details class="diagnostics">
        <summary>来源与诊断</summary>
        <dl>
          <div><dt>种子引用</dt><dd>{{ diagnosticReference(preview.seedRef) }}</dd></div>
          <div><dt>发动机引用</dt><dd>{{ diagnosticReference(preview.engineRef) }}</dd></div>
          <div><dt>绑定引用</dt><dd>{{ diagnosticReference(preview.bindingRef) }}</dd></div>
          <div><dt>创作约定校验值</dt><dd>{{ preview.creationHash || '—' }}</dd></div>
          <div><dt>风格约定校验值</dt><dd>{{ preview.styleHash || '—' }}</dd></div>
          <template v-for="item in preview.bindingRef?.items || []" :key="item.taskKey">
            <div><dt>任务代码</dt><dd>{{ item.taskKey || '—' }}</dd></div>
            <div><dt>模型提供方标识</dt><dd>{{ item.providerId || '—' }}</dd></div>
            <div><dt>状态代码</dt><dd>{{ item.resolutionStatus || '—' }}</dd></div>
          </template>
          <div v-for="ref in preview.corpusSourceRefs || []" :key="ref.id"><dt>参考语料引用</dt><dd>{{ diagnosticReference(ref) }}</dd></div>
          <div v-for="reason in previewReasons" :key="reason"><dt>诊断代码</dt><dd>{{ reason }}</dd></div>
        </dl>
      </details>

      <footer v-if="confirmation.canConfirm" class="step-actions">
        <div class="seal-action">
          <span>签印成功后进入“等待滚动规划”，写作台仍保持关闭。</span>
          <n-button
            type="primary"
            size="large"
            :loading="store.confirming"
            :disabled="props.interactionLocked || store.confirming || store.requiresReload || !confirmation.canConfirm"
            @click="confirmOpen = true"
          >核对并签印完整契约</n-button>
        </div>
      </footer>
    </template>

    <FoundationConfirmationDialog
      v-if="confirmOpen"
      :open="true"
      title="确认签印这份完整创作契约"
      :close-disabled="store.confirming"
      @close="confirmOpen = false"
    >
      <template #snapshot>
        <strong>服务器快照</strong>
        <dl class="confirmation-ledger">
          <div><dt>草稿版本</dt><dd>{{ confirmation.draftVersion ?? '—' }}</dd></div>
          <div><dt>基础版本</dt><dd>{{ preview?.baseHeadRevision !== undefined ? `第 ${preview.baseHeadRevision} 版` : '尚无基线' }}</dd></div>
          <div><dt>确认后版本</dt><dd>{{ preview?.expectedRevision ? `第 ${preview.expectedRevision} 版` : '待服务器确认' }}</dd></div>
          <div><dt>种子选择代次</dt><dd>{{ preview?.selectionRevision ? `第 ${preview.selectionRevision} 代` : '待服务器确认' }}</dd></div>
          <div><dt>服务器确认能力</dt><dd>{{ preview?.contractReady === true ? '允许签印' : '不允许签印' }}</dd></div>
          <div><dt>创作种子</dt><dd>{{ authorReference(preview?.seedRef, '创作种子') }}</dd></div>
          <div><dt>故事发动机</dt><dd>{{ authorReference(preview?.engineRef, '故事发动机') }}</dd></div>
          <div><dt>模型绑定</dt><dd>{{ preview?.bindingRef?.items?.length || 0 }} 项已核对</dd></div>
        </dl>
      </template>
      <template #source>
        <p>以下是服务器预览中将被完整冻结的作者内容；确认能力与阻断原因完全采用服务器当前响应。</p>
        <section class="confirmation-references" aria-label="即将冻结的精确引用">
          <div><strong>风格模板</strong><p v-if="!preview?.styleRefs?.length">未选择</p><p v-for="(ref, index) in preview?.styleRefs || []" :key="ref.id">{{ authorReference(ref, '风格模板', index + 1) }}</p></div>
          <div><strong>经验卡</strong><p v-if="!preview?.experienceCardRefs?.length">未选择</p><p v-for="(ref, index) in preview?.experienceCardRefs || []" :key="ref.id">{{ authorReference(ref, '经验卡', index + 1) }}</p></div>
          <div><strong>参考语料</strong><p v-if="!preview?.corpusSourceRefs?.length">未选择</p><p v-for="(ref, index) in preview?.corpusSourceRefs || []" :key="ref.id">{{ authorReference(ref, '参考语料', index + 1) }} · {{ selectionModeLabels[ref.selectionMode] || '引用方式待核对' }}</p></div>
        </section>
        <section class="confirmation-binding" aria-label="即将冻结的模型任务绑定">
          <strong>模型任务绑定明细</strong>
          <p v-if="!preview?.bindingRef?.items?.length">无绑定明细</p>
          <p v-for="item in preview?.bindingRef?.items || []" :key="item.taskKey">{{ authorTask(item) }} · {{ item.providerNameSnapshot || '未绑定模型服务' }} / {{ item.modelNameSnapshot || '未选择模型' }} · {{ authorResolution(item) }}</p>
        </section>
        <ContractDecisionSummary
          v-if="preview?.creationContract || preview?.styleContract"
          :creation-contract="preview?.creationContract"
          :style-contract="preview?.styleContract"
          :likes="preview?.likes"
          :dislikes="preview?.dislikes"
          heading="签印目标中的全部作者决定"
        />
        <ul v-if="previewReasons.length"><li v-for="reason in previewReasons" :key="reason">{{ explain(reason) }}</li></ul>
        <details class="diagnostics">
          <summary>来源与诊断</summary>
          <dl>
            <div><dt>草稿内容校验值</dt><dd>{{ confirmation.contentHash || '—' }}</dd></div>
            <div><dt>种子修订标识</dt><dd>{{ preview?.seedRef?.revisionId || '—' }}</dd></div>
            <div><dt>发动机批次标识</dt><dd>{{ preview?.engineRef?.batchId || '—' }}</dd></div>
            <div><dt>绑定引用</dt><dd>{{ diagnosticReference(preview?.bindingRef) }}</dd></div>
            <div><dt>创作约定校验值</dt><dd>{{ preview?.creationHash || '—' }}</dd></div>
            <div><dt>风格约定校验值</dt><dd>{{ preview?.styleHash || '—' }}</dd></div>
            <div v-for="ref in preview?.styleRefs || []" :key="`style-${ref.id}`"><dt>风格模板引用</dt><dd>{{ diagnosticReference(ref) }}</dd></div>
            <div v-for="ref in preview?.experienceCardRefs || []" :key="`card-${ref.id}`"><dt>经验卡引用</dt><dd>{{ diagnosticReference(ref) }}</dd></div>
            <div v-for="ref in preview?.corpusSourceRefs || []" :key="`corpus-${ref.id}`"><dt>参考语料引用</dt><dd>{{ diagnosticReference(ref) }}</dd></div>
            <template v-for="item in preview?.bindingRef?.items || []" :key="item.taskKey">
              <div><dt>任务代码</dt><dd>{{ item.taskKey || '—' }}</dd></div>
              <div><dt>模型提供方标识</dt><dd>{{ item.providerId || '—' }}</dd></div>
              <div><dt>状态代码</dt><dd>{{ item.resolutionStatus || '—' }}</dd></div>
            </template>
            <div v-for="reason in previewReasons" :key="reason"><dt>诊断代码</dt><dd>{{ reason }}</dd></div>
          </dl>
        </details>
        <n-alert v-if="confirmError" ref="confirmErrorRegion" tabindex="-1" type="error" title="确认没有得到明确结果" aria-live="assertive">
          {{ confirmError }}。再次点击会使用同一幂等命令核对，不会创建重复修订。
        </n-alert>
      </template>
      <template #action>
        <n-button :disabled="store.confirming" @click="confirmOpen = false">继续核对文档</n-button>
        <n-button type="primary" :loading="store.confirming" :disabled="props.interactionLocked || store.confirming || store.requiresReload || !confirmation.canConfirm" @click="confirmContract">
          {{ confirmError ? '使用同一命令重试' : '一次确认完整契约' }}
        </n-button>
      </template>
    </FoundationConfirmationDialog>
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
.confirmation-ledger { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 18px; margin:10px 0 0; }
.confirmation-ledger div { min-width:0; }
.confirmation-ledger dt { color:var(--muted,#817668); font-size:11px; }
.confirmation-ledger dd { margin:3px 0 0; overflow-wrap:anywhere; color:var(--ink,#574c3e); font-size:12px; }
.confirmation-references { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.confirmation-references > div { min-width:0; padding:10px; border:1px solid var(--rule,#ded2bf); background:var(--paper,#faf6ed); }
.confirmation-references p { margin:5px 0 0; overflow-wrap:anywhere; font-size:11px; line-height:1.55; }
.confirmation-binding { margin-top:10px; padding:10px; border:1px solid var(--rule,#ded2bf); background:var(--paper,#faf6ed); }
.confirmation-binding p { margin:5px 0 0; overflow-wrap:anywhere; font-size:11px; line-height:1.55; }
.diagnostics { margin-top:18px; padding:12px 14px; border:1px solid var(--rule,#ded2bf); background:var(--paper,#faf6ed); }
.diagnostics summary { cursor:pointer; color:var(--ink,#574c3e); font-weight:650; }
.diagnostics dl { display:grid; gap:8px; margin:12px 0 0; }
.diagnostics dt { color:var(--muted,#817668); font-size:11px; }
.diagnostics dd { margin:2px 0 0; overflow-wrap:anywhere; font-size:11px; line-height:1.55; }
@media (max-width: 760px) { .reference-grid,.confirmation-references,.confirmation-ledger { grid-template-columns: 1fr; } .step-actions { align-items: stretch; flex-direction: column; } .seal-action { justify-items: stretch; } }
</style>
