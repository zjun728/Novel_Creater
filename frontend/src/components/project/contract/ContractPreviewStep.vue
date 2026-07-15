<script setup>
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NDescriptions, NDescriptionsItem, NResult, NSpin, NTag } from 'naive-ui'
import { useCreationContractStore } from '@/stores/creationContractStore'

const props = defineProps({ projectId: { type: String, required: true } })
const emit = defineEmits(['back', 'confirmed'])
const store = useCreationContractStore()
const loadError = ref('')
const confirmError = ref('')

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

function wordRange(value) {
  if (!Array.isArray(value) || value.length !== 2) return '—'
  return `${Number(value[0]).toLocaleString()} ～ ${Number(value[1]).toLocaleString()} 字`
}

async function loadPreview() {
  loadError.value = ''
  confirmError.value = ''
  try {
    await store.preview(props.projectId)
  } catch (error) {
    loadError.value = error?.message || '契约预览生成失败'
  }
}

async function confirmContract() {
  confirmError.value = ''
  try {
    const result = await store.confirm(props.projectId, { idempotencyKey })
    emit('confirmed', result)
  } catch (error) {
    confirmError.value = error?.message || '契约确认结果未知'
  }
}

watch(() => props.projectId, () => loadPreview(), { immediate: true })
</script>

<template>
  <article class="preview-step">
    <header class="step-heading">
      <div><span>STEP 05</span><h3>冻结并确认</h3></div>
      <n-tag :type="store.contractReady ? 'success' : 'warning'" round>
        {{ store.contractReady ? '可以签印' : '尚未就绪' }}
      </n-tag>
    </header>

    <div v-if="store.previewing" class="loading"><n-spin size="large" /><span>正在核对全部冻结引用…</span></div>
    <n-result v-else-if="loadError" status="error" title="无法形成契约预览" :description="loadError">
      <template #footer><n-button @click="loadPreview">重新核对</n-button></template>
    </n-result>

    <template v-else-if="preview">
      <n-alert v-if="store.readinessReasons.length" type="warning" title="签印前仍需处理">
        <ul><li v-for="reason in store.readinessReasons" :key="reason">{{ explain(reason) }}</li></ul>
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

      <section v-if="preview.creationContract && preview.styleContract" class="decision-sheet" aria-labelledby="contract-decisions-heading">
        <h4 id="contract-decisions-heading">作者即将确认的创作约定</h4>
        <div class="decision-grid">
          <article>
            <span>故事出发点</span>
            <h5>{{ preview.creationContract.selectedSeed?.title || '已选种子' }}</h5>
            <p>{{ preview.creationContract.selectedSeed?.logline }}</p>
          </article>
          <article>
            <span>长期故事承诺</span>
            <h5>{{ preview.creationContract.selectedEngine?.name || '已选发动机' }}</h5>
            <p>{{ preview.creationContract.selectedEngine?.storyPromise }}</p>
          </article>
          <article>
            <span>持续压力与冲突循环</span>
            <p>{{ preview.creationContract.selectedEngine?.sustainedPressure }}</p>
            <p>{{ preview.creationContract.selectedEngine?.conflictLoop }}</p>
          </article>
          <article>
            <span>整书阅读感受</span>
            <p>{{ preview.styleContract.readingExperience }}</p>
            <p>{{ preview.styleContract.dialogueAndSubtext }}</p>
          </article>
        </div>
        <n-descriptions :column="2" bordered label-placement="left" size="small" class="policy-table">
          <n-descriptions-item label="渠道 / 题材">{{ preview.creationContract.channelProfileKey }} / {{ preview.creationContract.genreProfileKey }}</n-descriptions-item>
          <n-descriptions-item label="目标篇幅">{{ wordRange(preview.creationContract.totalWordRange) }}</n-descriptions-item>
          <n-descriptions-item label="质量章程">{{ preview.creationContract.qualityCharterVersion }}</n-descriptions-item>
          <n-descriptions-item label="模型绑定修订">R{{ preview.creationContract.modelBindingRevision }}</n-descriptions-item>
          <n-descriptions-item label="章节容量策略" :span="2">{{ preview.creationContract.chapterCapacityPolicy }}</n-descriptions-item>
          <n-descriptions-item label="喜欢的表现" :span="2">{{ preview.likes?.join('；') || '未额外填写' }}</n-descriptions-item>
          <n-descriptions-item label="明确避开" :span="2">{{ preview.dislikes?.join('；') || '未额外填写' }}</n-descriptions-item>
        </n-descriptions>
      </section>

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

      <n-alert v-if="confirmError" type="error" title="确认没有得到明确结果">
        {{ confirmError }}。再次点击会使用同一幂等命令核对，不会创建重复修订。
      </n-alert>

      <footer class="step-actions">
        <n-button :disabled="store.confirming" @click="emit('back')">返回素材范围</n-button>
        <div class="seal-action">
          <span>签印成功后进入“等待滚动规划”，写作台仍保持关闭。</span>
          <n-button
            type="primary"
            size="large"
            :loading="store.confirming"
            :disabled="!store.contractReady"
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
.step-heading span { color: #9c3d2f; font: 700 10px Georgia, serif; letter-spacing: .15em; }
.step-heading h3 { margin: 4px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 25px; }
.loading { display: grid; place-items: center; gap: 12px; min-height: 260px; color: #7c7163; }
.snapshot, .decision-sheet, .binding-sheet, .reference-grid { margin-top: 24px; }
h4 { margin: 0 0 11px; color: #574c3e; font: 650 14px 'Noto Serif SC', serif; }
ul { margin: 7px 0 0; padding-left: 18px; }
.decision-sheet { padding: 18px; border: 1px solid #d8c9b1; border-radius: 9px; background: #fffdf8; }
.decision-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; border: 1px solid #e3d8c6; background: #e3d8c6; }
.decision-grid article { min-height: 126px; padding: 16px; background: #faf6ed; }
.decision-grid span { color: #9c3d2f; font-size: 10px; font-weight: 700; letter-spacing: .08em; }
.decision-grid h5 { margin: 7px 0 0; font-family: 'Noto Serif SC', serif; font-size: 15px; }
.decision-grid p { margin: 7px 0 0; color: #6f6456; font-size: 12px; line-height: 1.7; }
.policy-table { margin-top: 12px; }
.reference-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.reference-grid section { min-height: 108px; padding: 16px; border: 1px solid #e1d6c4; border-radius: 8px; background: #faf6ed; }
.reference-grid p, .reference-grid small { display: block; margin: 5px 0 0; color: #74695b; font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
.binding-sheet { border-top: 1px solid #ded2bf; }
.binding-sheet h4 { margin-top: 18px; }
.binding-line { padding: 9px 3px; border-bottom: 1px dashed #ded2bf; font-size: 12px; }
.binding-line span { flex: 1; color: #756a5d; }
.step-actions { align-items: flex-end; margin-top: 28px; padding-top: 22px; border-top: 1px solid #d9ccb7; }
.seal-action { display: grid; justify-items: end; gap: 8px; }
.seal-action span { color: #817668; font-size: 11px; }
@media (max-width: 760px) { .decision-grid, .reference-grid { grid-template-columns: 1fr; } .step-actions { align-items: stretch; flex-direction: column; } .seal-action { justify-items: stretch; } }
</style>
