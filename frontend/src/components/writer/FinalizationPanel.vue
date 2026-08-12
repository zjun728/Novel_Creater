<script setup>
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NCard, NInput, NTag } from 'naive-ui'


const props = defineProps({
  controller: { type: Object, required: true },
  candidates: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})

const selectedCandidateId = ref('')
const changeSetDraft = ref(null)
const review = computed(() => props.controller.review.value)
const busy = computed(() => props.disabled || props.controller.busy.value)
const currentCandidates = computed(() => props.candidates.filter(
  item => item.basisStatus === 'current',
))
const selectedCandidate = computed(() => currentCandidates.value.find(
  item => item.id === selectedCandidateId.value,
) || null)
const confirmed = computed(() => {
  const value = review.value
  return value?.confirmation?.revision === value?.changeSet?.revision
    && value?.confirmation?.contentHash === value?.changeSet?.contentHash
})
const editable = computed(() => (
  Boolean(changeSetDraft.value)
  && !confirmed.value
  && !props.controller.finalized.value
  && !busy.value
))
const changed = computed(() => {
  const current = review.value?.changeSet?.payload
  return Boolean(current && changeSetDraft.value)
    && JSON.stringify(current) !== JSON.stringify(changeSetDraft.value)
})
const findings = computed(() => review.value?.qualityReport?.findings || [])
const hardBlocks = computed(() => props.controller.hardBlocks.value)

watch(currentCandidates, values => {
  if (!values.some(item => item.id === selectedCandidateId.value)) {
    selectedCandidateId.value = values.at(-1)?.id || ''
  }
}, { immediate: true, flush: 'sync' })

watch(() => review.value?.changeSet, value => {
  changeSetDraft.value = value?.payload ? structuredClone(value.payload) : null
}, { immediate: true, deep: false, flush: 'sync' })

function evidenceText(evidence) {
  if (!evidence) return '无正文定位'
  return `正文字符 ${evidence.startScalar}–${evidence.endScalar}`
}

function displayValue(value) {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

async function prepareSelected() {
  if (!selectedCandidate.value) return
  try {
    await props.controller.prepareCandidate(selectedCandidate.value)
  } catch {
    // The controller owns the fixed public error.
  }
}

async function saveCorrection() {
  try {
    await props.controller.correctChangeSet(changeSetDraft.value)
  } catch {
    // The controller owns the fixed public error.
  }
}

async function confirmChangeSet() {
  try {
    await props.controller.confirmChangeSet()
  } catch {
    // The controller owns the fixed public error.
  }
}

async function commitChapter() {
  try {
    await props.controller.commitChapter()
  } catch {
    // The controller owns the fixed public error.
  }
}
</script>

<template>
  <n-card title="定稿审查" :bordered="false" class="finalization-panel">
    <p class="panel-intro">作者确认后，正文、Canon、进度与未来规划会在同一事务中提交。</p>

    <n-alert
      v-if="controller.error.value"
      type="error"
      title="定稿操作未完成"
      class="panel-alert"
    >{{ controller.error.value }}</n-alert>

    <n-alert
      v-if="controller.finalized.value"
      type="success"
      title="本章已定稿"
      class="panel-alert"
    >
      正文与对应小纲现为只读；后续修改请在未实现内容中承接。
    </n-alert>

    <template v-else-if="!review || controller.primaryAction.value === 'blocked'">
      <section v-if="hardBlocks.length" class="review-section" aria-label="确定性阻断">
        <h3>确定性阻断</h3>
        <ul class="review-list">
          <li v-for="item in hardBlocks" :key="item.code">
            <strong>{{ item.message }}</strong>
            <small>{{ evidenceText(item.evidence) }}</small>
          </li>
        </ul>
      </section>
      <label class="candidate-picker">
        <span>选择当前候选稿</span>
        <select v-model="selectedCandidateId" :disabled="busy || !currentCandidates.length">
          <option v-for="(item, index) in currentCandidates" :key="item.id" :value="item.id">
            候选 {{ candidates.indexOf(item) + 1 }} · {{ item.contentHash.slice(0, 8) }}
          </option>
        </select>
      </label>
      <p v-if="!currentCandidates.length" class="muted">请先保存一份依据当前小纲的候选稿。</p>
      <n-button
        type="primary"
        block
        :loading="controller.busy.value"
        :disabled="busy || !selectedCandidate"
        @click="prepareSelected"
      >审查并定稿</n-button>
    </template>

    <template v-else>
      <section class="review-section" aria-label="质量建议">
        <div class="section-heading">
          <h3>质量建议</h3>
          <n-tag size="small" :type="review.qualityReport?.status === 'completed' ? 'success' : 'warning'">
            {{ review.qualityReport?.status === 'completed' ? '已完成' : '未完成，不阻断' }}
          </n-tag>
        </div>
        <ul v-if="findings.length" class="review-list">
          <li v-for="item in findings" :key="item.id">
            <strong>{{ item.reason }}</strong>
            <span>{{ item.suggestedAction }}</span>
            <small>{{ evidenceText(item.evidence) }}</small>
          </li>
        </ul>
        <p v-else class="muted">没有质量建议；作者仍需核对下方事实变更。</p>
      </section>

      <section v-if="changeSetDraft" class="review-section change-set" aria-label="完整变更集">
        <div class="section-heading">
          <h3>本章变更集</h3>
          <n-tag size="small">修订 {{ review.changeSet.revision }}</n-tag>
        </div>
        <label><span>章节标题</span><n-input v-model:value="changeSetDraft.title" :disabled="!editable" /></label>
        <label><span>章节摘要</span><n-input v-model:value="changeSetDraft.summary" type="textarea" :disabled="!editable" /></label>

        <div v-if="changeSetDraft.entities.length || changeSetDraft.aliases.length" class="change-group">
          <h4>Canon 实体</h4>
          <label v-for="item in changeSetDraft.entities" :key="item.id">
            <span>{{ item.entityType }}</span>
            <n-input v-model:value="item.canonicalName" :disabled="!editable" />
          </label>
          <label v-for="item in changeSetDraft.aliases" :key="item.id">
            <span>别名</span>
            <n-input v-model:value="item.alias" :disabled="!editable" />
          </label>
        </div>

        <div v-if="changeSetDraft.canonEvents.length" class="change-group">
          <h4>Canon 事实</h4>
          <article v-for="item in changeSetDraft.canonEvents" :key="item.id" class="change-item">
            <strong>{{ item.fieldPath }}</strong>
            <pre>{{ displayValue(item.value) }}</pre>
            <small>{{ evidenceText(item.evidence) }}</small>
          </article>
        </div>

        <div v-if="changeSetDraft.storyProgressEvents.length" class="change-group">
          <h4>故事进度</h4>
          <label v-for="item in changeSetDraft.storyProgressEvents" :key="item.id">
            <span>{{ item.targetType }} · {{ item.targetId }}</span>
            <select v-model="item.status" :disabled="!editable">
              <option value="started">开始</option>
              <option value="advanced">推进</option>
              <option value="completed">完成</option>
            </select>
          </label>
        </div>

        <div v-if="changeSetDraft.planningPatches.length" class="change-group">
          <h4>未来规划调整</h4>
          <article v-for="item in changeSetDraft.planningPatches" :key="item.id" class="change-item">
            <strong>{{ item.targetType }} · {{ item.fieldPath }}</strong>
            <n-input
              v-if="typeof item.replacement === 'string'"
              v-model:value="item.replacement"
              :disabled="!editable"
            />
            <pre v-else>{{ displayValue(item.replacement) }}</pre>
            <small>{{ evidenceText(item.evidence) }}</small>
          </article>
        </div>

        <div v-if="changeSetDraft.planningSuggestions.length" class="change-group">
          <h4>非权威建议</h4>
          <p v-for="item in changeSetDraft.planningSuggestions" :key="item.id">{{ item.message }}</p>
        </div>
      </section>

      <n-button
        v-if="changed"
        type="primary"
        block
        :loading="controller.busy.value"
        :disabled="busy"
        @click="saveCorrection"
      >保存修正</n-button>
      <n-button
        v-else-if="controller.primaryAction.value === 'confirm'"
        type="primary"
        block
        :loading="controller.busy.value"
        :disabled="busy"
        @click="confirmChangeSet"
      >确认以上变更</n-button>
      <n-button
        v-else-if="controller.primaryAction.value === 'commit'"
        type="success"
        block
        :loading="controller.busy.value"
        :disabled="busy"
        @click="commitChapter"
      >定稿本章</n-button>
    </template>
  </n-card>
</template>

<style scoped>
.finalization-panel { border-top: 3px solid #9b6a32; }
.panel-intro { margin: 0 0 14px; color: #786f62; font-size: 12px; line-height: 1.7; }
.panel-alert { margin-bottom: 14px; }
.candidate-picker, .change-set label { display: grid; gap: 6px; margin-bottom: 12px; color: #675d51; font-size: 12px; font-weight: 700; }
select { width: 100%; border: 1px solid #d9cbb7; border-radius: 7px; padding: 8px 9px; color: #453b31; background: #fffdf8; }
.review-section { margin-bottom: 16px; border-bottom: 1px solid #e4d8c6; padding-bottom: 14px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
h3, h4 { margin: 0 0 10px; color: #4d4033; font-family: Georgia, 'Noto Serif SC', serif; }
h3 { font-size: 15px; } h4 { font-size: 13px; }
.review-list { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
.review-list li, .change-item { display: grid; gap: 4px; border-radius: 8px; padding: 9px; background: #f8f1e5; }
.review-list span, .review-list small, .change-item small { color: #817565; font-size: 11px; line-height: 1.55; }
.change-group { margin-top: 14px; }
.change-item { margin-bottom: 8px; }
pre { overflow: auto; max-height: 150px; margin: 0; color: #55493c; white-space: pre-wrap; overflow-wrap: anywhere; font: 11px/1.6 ui-monospace, monospace; }
.muted { color: #8a7d6d; font-size: 12px; line-height: 1.6; }
</style>
