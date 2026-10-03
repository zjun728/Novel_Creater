<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NCard, NInput, NTag } from 'naive-ui'
import { evidenceExcerpt } from '../../application/writer/finalizationEvidence.js'
import { createFinalizationHistory } from '../../application/writer/finalizationHistory.js'
import { api } from '../../api/db/client.js'
import { effectiveReviewFindings, referenceFromReview } from '../../utils/reviewReference.js'
import FinalizationValueEditor from './FinalizationValueEditor.vue'
import AddCanonFactEditor from './AddCanonFactEditor.vue'
import ReviewResultsDialog from './ReviewResultsDialog.vue'


const props = defineProps({
  controller: { type: Object, required: true },
  projectId: { type: String, default: '' },
  sessionId: { type: String, default: '' },
  readHistory: { type: Function, default: api.chapterSessions.getFinalizationHistoryReference },
  candidates: { type: Array, default: () => [] },
  planningContent: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
  chapterNumber: { type: Number, default: 0 },
  draftStale: { type: Boolean, default: false },
  selectedFinding: { type: String, default: '' },
})
const emit = defineEmits(['read-finalized', 'dirty-change', 'locate-finding', 'adjust-review'])

const selectedCandidateId = ref('')
const resultsOpen = ref(false)
const changesSection = ref(null)
const changeSetDraft = ref(null)
const revokeConfirmation = ref(false)
const valueEditorPending = ref(new Map())
const addedFactPending = ref(false)
const factBuilderMounted = ref(false)
const review = computed(() => props.controller.review.value)
const history = createFinalizationHistory({
  getProjectId: () => props.projectId, getSessionId: () => props.sessionId,
  getReview: () => review.value, getCandidates: () => props.candidates,
  readHistory: (...args) => props.readHistory(...args),
})
onBeforeUnmount(() => history.dispose())
const postFinalization = computed(() => props.controller.postFinalization.value)
const busy = computed(() => props.disabled || props.controller.busy.value || props.controller.recoveryPending?.value)
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
  && review.value?.status === 'awaiting_author'
  && !confirmed.value
  && !props.controller.finalized.value
  && !busy.value
  && !props.draftStale
))
const changed = computed(() => {
  const current = review.value?.changeSet?.payload
  return Boolean(current && changeSetDraft.value)
    && JSON.stringify(current) !== JSON.stringify(changeSetDraft.value)
})
const pendingFields = computed(() => addedFactPending.value || [...valueEditorPending.value.values()].some(Boolean)
  || (changeSetDraft.value?.storyProgressEvents || []).some(item => progressRationaleError(item)))
const unsaved = computed(() => changed.value || pendingFields.value)
const reviewCandidateContent = computed(() => props.candidates.find(item => item.id === review.value?.candidateId
  && item.contentHash === review.value?.candidateHash)?.content || '')
const factEntities = computed(() => {
  const values = new Map((changeSetDraft.value?.existingEntityIds || []).map(id => [id, { id, label: id }]))
  for (const item of changeSetDraft.value?.entities || []) values.set(item.id, item)
  return [...values.values()]
})
const findings = computed(() => effectiveReviewFindings(review.value))
const requiredFindings = computed(() => findings.value.some(item => item.severity === 'required'))
async function decideFinding(id, ignored) {
  if (!editable.value || unsaved.value) return
  try { await props.controller.setFindingIgnored(id, ignored) } catch { /* controller owns error */ }
}
const hardBlocks = computed(() => props.controller.hardBlocks.value)
const resultsStale = computed(() => props.draftStale || ['invalidated', 'cancelled'].includes(review.value?.status) || props.controller.finalized.value)
watch(() => review.value?.attemptId, () => { resultsOpen.value = false }, { flush: 'sync' })
async function checkChanges() {
  await nextTick()
  changesSection.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  changesSection.value?.focus({ preventScroll: true })
}
let previousCandidateIds = new Set()

watch(unsaved, value => emit('dirty-change', value), { immediate: true, flush: 'sync' })
onBeforeUnmount(() => emit('dirty-change', false))

watch(currentCandidates, values => {
  const ids = new Set(values.map(item => item.id))
  const added = values.filter(item => !previousCandidateIds.has(item.id))
  if (added.length) {
    selectedCandidateId.value = added.at(-1).id
  } else if (!ids.has(selectedCandidateId.value)) {
    selectedCandidateId.value = values.at(-1)?.id || ''
  }
  previousCandidateIds = ids
}, { immediate: true, flush: 'sync' })

watch(() => [review.value?.attemptId, review.value?.candidateId, review.value?.candidateHash, review.value?.changeSet], (current, previous) => {
  const value = current[3]
  revokeConfirmation.value = false
  // A same-version reread must not discard unsaved fields, including incomplete editor input.
  if (changeSetDraft.value && value?.payload && previous
    && current.slice(0, 3).every((identity, index) => identity === previous[index])
    && value.revision === previous[3]?.revision
    && value.contentHash === previous[3]?.contentHash) return
  valueEditorPending.value.clear()
  addedFactPending.value = false
  factBuilderMounted.value = false
  changeSetDraft.value = value?.payload ? structuredClone(value.payload) : null
}, { immediate: true, deep: false, flush: 'sync' })

function evidenceText(evidence) {
  if (!evidence) return '无正文定位'
  const candidate = props.candidates.find(item => item.id === review.value?.candidateId
    && item.contentHash === review.value?.candidateHash)
  const excerpt = evidenceExcerpt(candidate?.content, evidence)
  return `正文字符 ${evidence.startScalar}–${evidence.endScalar}：${excerpt ? `“${excerpt}”` : '原文片段不可用，请重新读取候选稿。'}`
}

function displayValue(value) {
  const labels = {
    loom_modified_with_scrap: '已用废料完成织机改造',
    first_trial_failed: '首次试机失败',
    adjusted_guide_angle: '已调整经线导向角',
    became_collaborator: '已成为协作伙伴',
    at_risk_of_impressment: '面临被征役风险',
    identified_loom_faults: '已定位织机故障',
    bet_with_wang_laoda: '已与王老大立下赌约',
  }
  if (typeof value === 'string' && Object.hasOwn(labels, value)) return labels[value]
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

const nodeId = node => String(node?.id || node?.clientNodeKey || '')
const targetTypeLabel = value => ({
  volume: '分卷',
  plot: '情节线',
  story_block: '故事块',
  stage: '阶段',
  scene_task: '场景任务',
})[value] || '规划项'

function planningNodes() {
  const content = props.planningContent || {}
  const blocks = Array.isArray(content.storyBlocks) ? content.storyBlocks : []
  const stages = blocks.flatMap(block => Array.isArray(block.stages) ? block.stages : [])
  const tasks = stages.flatMap(stage => (
    Array.isArray(stage.sceneTasks) ? stage.sceneTasks : []
  ))
  return {
    volume: content.volumes || [],
    plot: content.plots || [],
    story_block: blocks,
    stage: stages,
    scene_task: tasks,
  }
}

function targetLabel(item) {
  const kind = targetTypeLabel(item?.targetType)
  const target = (planningNodes()[item?.targetType] || []).find(
    node => nodeId(node) === String(item?.targetId || ''),
  )
  const title = target?.title || target?.task
  return title ? `${kind} · ${title}` : `${kind} · 当前规划项`
}

const fieldLabel = value => ({
  'author.observation': '作者补录事实',
  status: '状态',
  skills: '技能',
  debts: '债务',
})[value] || value

async function prepareSelected() {
  if (!selectedCandidate.value) return
  try {
    await props.controller.prepareCandidate(selectedCandidate.value)
    if (review.value?.qualityReport || hardBlocks.value.length) resultsOpen.value = true
  } catch {
    // The controller owns the fixed public error.
  }
}

async function saveCorrection() {
  if (!editable.value || !changed.value || pendingFields.value) return
  try {
    await props.controller.correctChangeSet(changeSetDraft.value)
  } catch {
    // The controller owns the fixed public error.
  }
}

async function confirmChangeSet() {
  if (!editable.value || unsaved.value) return
  try {
    await props.controller.confirmChangeSet()
  } catch {
    // The controller owns the fixed public error.
  }
}

function removePlanningPatch(id) {
  if (!editable.value) return
  const patches = changeSetDraft.value.planningPatches
  const index = patches.findIndex(item => item.id === id)
  if (index !== -1) patches.splice(index, 1)
}

function excludeFact(id) {
  if (!editable.value) return
  const events = changeSetDraft.value.canonEvents
  const index = events.findIndex(item => item.id === id)
  if (index !== -1) {
    valueEditorPending.value.delete(id)
    events.splice(index, 1)
  }
}

function updateFactValue(id, value) {
  if (!editable.value) return
  const item = changeSetDraft.value.canonEvents.find(event => event.id === id)
  if (item) item.value = JSON.parse(JSON.stringify(value))
}

const referenceValue = value => JSON.stringify(value, null, 2)
function referenceMessage(item) {
  const value = history.lookup(item.entityId, item.fieldPath)
  if (value.state === 'absent') return '截至冻结版本未找到该字段的已确认状态值；历史说法不作为状态参考。'
  if (value.state === 'not_loaded') return '尚未读取此路径的历史参考，保存修正并正常重读后补齐。'
  if (value.state === 'loading') return '正在读取历史参考…'
  if (value.state === 'not_applicable') return value.reason === 'global'
    ? '本项未关联特定实体，不适用同实体字段对照。' : '本次新增实体，无既有同实体参考。'
  return '历史参考不可用；这不表示该字段不存在。'
}

const factKindLabels = {
  dynamic_event: '已发生的事件',
  claim: '人物说法或推测',
  stable_definition: '稳定设定',
}
const hasFactEntity = item => Boolean(item.entityId
  && factEntities.value.some(entity => entity.id === item.entityId))

function updateFactKind(id, kind) {
  if (!editable.value || !Object.hasOwn(factKindLabels, kind)) return
  const item = changeSetDraft.value.canonEvents.find(event => event.id === id)
  if (!item || (kind === 'stable_definition' && !hasFactEntity(item))) return
  item.factKind = kind
}

function excludeAlias(id) {
  if (!editable.value) return
  const aliases = changeSetDraft.value.aliases
  const index = aliases.findIndex(item => item.id === id)
  if (index !== -1) aliases.splice(index, 1)
}

function addFact(item) {
  if (!editable.value || changeSetDraft.value.canonEvents.some(event => event.id === item.id)) return
  changeSetDraft.value.canonEvents.push(item)
}

function excludeProgress(id) {
  if (!editable.value) return
  const events = changeSetDraft.value.storyProgressEvents
  const index = events.findIndex(item => item.id === id)
  if (index !== -1) events.splice(index, 1)
}

function progressRationaleError(item) {
  const value = item.evidence?.rationale
  if (typeof value !== 'string' || !value.trim()) return '请填写任务状态判断依据。'
  if (Array.from(value).length > 500) return '任务状态判断依据最多 500 个字符，请缩短后保存；输入不会自动截断。'
  return ''
}

function updateProgressRationale(id, value) {
  if (!editable.value || typeof value !== 'string') return
  const item = changeSetDraft.value.storyProgressEvents.find(event => event.id === id)
  if (item?.evidence) item.evidence.rationale = value
}

async function commitChapter() {
  if (props.draftStale) return
  try {
    await props.controller.commitChapter()
  } catch {
    // The controller owns the fixed public error.
  }
}

async function cancelReview() {
  try {
    await props.controller.cancelReview()
  } catch {
    // The controller owns the fixed public error.
  }
}

async function revokeReview() {
  if (!revokeConfirmation.value || busy.value || !props.controller.canRevoke?.value) return
  try {
    await props.controller.revokeReview()
    revokeConfirmation.value = false
  } catch {
    // Keep the review visible; the controller owns outcome reconciliation.
  }
}

async function refreshPostFinalization() {
  await props.controller.refreshPostFinalization()
}
</script>

<template>
  <n-card title="定稿审查" :bordered="false" class="finalization-panel">
    <p class="panel-intro">核对审稿意见与本章变更后，由你确认定稿。</p>
    <n-button v-if="review?.qualityReport || hardBlocks.length" block @click="resultsOpen = true">查看本章审查结果</n-button>
    <ReviewResultsDialog v-model:show="resultsOpen" :chapter-number="chapterNumber" :title="review?.changeSet?.payload?.title || ''"
      :report="review?.qualityReport" :blocks="hardBlocks" :content="reviewCandidateContent" :disabled="busy"
      :stale="resultsStale" :can-adjust="!!referenceFromReview(review) && !unsaved"
      :decisions="review?.findingDecisions" :can-decide="editable && !unsaved" :error="controller.error.value"
      :load-evidence="controller.loadDisputeEvidence" :save-dispute="controller.saveFindingDispute"
      @decide="decideFinding" @reload="controller.load().catch(() => {})"
      :can-check-changes="!!changeSetDraft" @locate="emit('locate-finding', $event)" @adjust="emit('adjust-review')" @check-changes="checkChanges" />
    <n-alert v-if="review?.status === 'invalidated'" type="warning" title="需要重新审稿">旧审稿已失效。请保存当前正文为候选稿，再重新审查。</n-alert>
    <n-alert v-else-if="draftStale && !controller.finalized.value" type="warning" title="正文或小纲已变化">旧审稿不能作为当前正文的定稿依据。请先放弃或撤销旧审查，保存当前稿后重新审查。</n-alert>

    <n-alert
      v-if="controller.error.value"
      type="error"
      title="定稿操作未完成"
      class="panel-alert"
    >{{ controller.error.value }}</n-alert>
    <n-button
      v-if="controller.recoveryPending?.value"
      :disabled="controller.busy.value"
      @click="controller.load().catch(() => {})"
    >{{ controller.correctionRecovery?.value ? '刷新核对修正' : '核对撤销结果' }}</n-button>

    <n-alert
      v-if="review?.status === 'failed' && !hardBlocks.length && !controller.busy.value"
      type="warning"
      title="本次审查未完成"
      class="panel-alert"
    >审查未完成，正文和候选稿未受影响。可稍后重新点击“审查并定稿”。</n-alert>

    <template v-if="controller.finalized.value">
      <n-alert
        type="success"
        title="本章已定稿"
        class="panel-alert"
      >
        正文与对应小纲已进入作品稿件。你可以继续当前创作步骤，也可以先回看本章定稿。
      </n-alert>
      <p v-if="postFinalization?.currentAction.state === 'unavailable' && postFinalization.currentAction.description" class="finalized-transition-status" role="status">{{ postFinalization.currentAction.description }}</p>
      <nav class="finalized-actions" aria-label="定稿后下一步">
        <p
          v-if="!postFinalization"
          class="finalized-transition-status"
          role="status"
        >正在读取定稿后的创作状态…</p>
        <router-link
          v-else-if="postFinalization.currentAction.state === 'available'"
          class="finalized-action finalized-action--primary"
          :to="postFinalization.currentAction.targetPath"
        >
          <small>{{ postFinalization.currentAction.eyebrow }}</small>
          <strong>{{ postFinalization.currentAction.label }}</strong>
          <span>{{ postFinalization.currentAction.description }}</span>
        </router-link>
        <n-button
          v-else-if="postFinalization.currentAction.state === 'unavailable'"
          type="primary"
          block
          :loading="controller.postBusy.value"
          :disabled="controller.postBusy.value"
          @click="refreshPostFinalization"
        >{{ controller.postBusy.value ? '正在读取创作状态…' : postFinalization.currentAction.label }}</n-button>
        <p
          v-else-if="postFinalization.currentAction.state === 'archived'"
          class="muted"
        >项目当前为只读状态。</p>
        <router-link
          v-if="postFinalization?.finalizedChapterReadable"
          class="finalized-action finalized-action--secondary"
          :to="postFinalization.finalizedChapterPath"
          @click="emit('read-finalized')"
        >查看本章定稿</router-link>
      </nav>
    </template>

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
      >{{ controller.busy.value ? '正在审查…' : '审查并定稿' }}</n-button>
    </template>

    <template v-else>
      <section class="review-section" aria-label="质量建议">
        <div class="section-heading">
          <h3>质量建议</h3>
          <n-tag size="small" :type="review.qualityReport?.status === 'completed' ? 'success' : 'warning'">
            {{ review.qualityReport?.status === 'completed' ? '已完成' : '未完成，不阻断' }}
          </n-tag>
        </div>
        <p v-if="findings.length" class="muted">共 {{ findings.length }} 条质量建议，打开审查结果查看分类、原文和调整建议。</p>
        <p v-else class="muted">没有质量建议；作者仍需核对下方事实变更。</p>
      </section>

      <section v-if="changeSetDraft" ref="changesSection" tabindex="-1" class="review-section change-set" aria-label="完整变更集">
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
            <n-button size="small" :disabled="!editable" @click="excludeAlias(item.id)">移除此别名</n-button>
          </label>
        </div>

        <div v-if="changeSetDraft.canonEvents.length" class="change-group">
          <div class="section-heading">
            <h4>Canon 事实</h4>
            <n-button size="small" :disabled="history.loading.value || !history.canRead.value" @click="history.refresh">刷新历史参考</n-button>
          </div>
          <p class="muted">对照原文核对内容和类型；人物说法或推测不等于已证实事实。修正事实时，也请核对上方摘要。保存修正并通过校验后，才可确认。</p>
          <p class="muted">历史参考按本次候选冻结的 Canon 版本查询，未复验整份冻结输入。请核对新内容是否仍描述同一对象和事项；值变化也可能是正常更新。</p>
          <article v-for="item in changeSetDraft.canonEvents" :key="item.id" class="change-item">
            <strong>{{ fieldLabel(item.fieldPath) }}</strong>
            <code class="fact-identity">实体 ID：{{ item.entityId ?? '全局记录' }} · 完整字段：{{ item.fieldPath }}</code>
            <n-tag class="fact-kind-tag" size="small" :type="item.factKind === 'claim' ? 'warning' : 'default'">{{ factKindLabels[item.factKind] || '未知类型' }}</n-tag>
            <div class="fact-comparison">
              <section aria-label="历史参考值">
                <strong>历史参考值<span v-if="history.reference.value"> · Canon R{{ history.reference.value.canonRevision }}</span></strong>
                <template v-if="history.lookup(item.entityId, item.fieldPath).state === 'present'">
                  <pre>{{ referenceValue(history.lookup(item.entityId, item.fieldPath).value) }}</pre>
                  <small>来源：R{{ history.lookup(item.entityId, item.fieldPath).source.revision }} · 事件顺序 {{ history.lookup(item.entityId, item.fieldPath).source.eventOrder }}</small>
                </template>
                <p v-else class="muted">{{ referenceMessage(item) }}</p>
              </section>
              <section aria-label="当前作者草稿值"><strong>当前作者草稿值</strong><pre>{{ referenceValue(item.value) }}</pre></section>
              <section aria-label="本次冻结候选正文依据"><strong>本次冻结候选正文依据</strong><small>{{ evidenceText(item.evidence) }}</small></section>
            </div>
            <details class="fact-correction">
              <summary>修正事实</summary>
              <p class="muted">可修正内容和类型；关联实体、原文引用沿用本条记录。记录说法或推测时，请在内容中保留是谁的判断和未确定之处。</p>
              <label><span>事实类型</span>
                <select :value="item.factKind" :disabled="!editable" :aria-label="`事实类型：${fieldLabel(item.fieldPath)}`" @change="updateFactKind(item.id, $event.target.value)">
                  <option value="dynamic_event">已发生的事件</option>
                  <option value="claim">人物说法或推测</option>
                  <option value="stable_definition" :disabled="!hasFactEntity(item)">稳定设定（须关联实体）</option>
                </select>
              </label>
              <FinalizationValueEditor :model-value="item.value" :disabled="!editable" @update:model-value="updateFactValue(item.id, $event)" @pending-change="valueEditorPending.set(item.id, $event)" />
            </details>
            <n-button size="small" :disabled="!editable" @click="excludeFact(item.id)">排除此项事实</n-button>
          </article>
        </div>

        <details :key="`add-fact-${review.changeSet.revision}`" class="fact-correction" @toggle="factBuilderMounted ||= $event.target.open">
          <summary>补录遗漏事实</summary>
          <AddCanonFactEditor v-if="factBuilderMounted" :key="review.changeSet.revision" :candidate-content="reviewCandidateContent" :chapter-number="chapterNumber" :entities="factEntities" :disabled="!editable" @add="addFact" @dirty-change="addedFactPending = $event" />
        </details>

        <div v-if="changeSetDraft.storyProgressEvents.length" class="change-group">
          <h4>故事进度</h4>
          <p class="muted">可排除正文没有完成的进度。保存时会重新核对父子任务的完成条件。</p>
          <p class="muted">任务状态判断依据用于说明本次正文支持的进度，不是新增世界事实。正文没展示某动作，表示本次正文不足以确认，不能据此断言世界中没有发生。可按需修正已有理由。</p>
          <article v-for="item in changeSetDraft.storyProgressEvents" :key="item.id" class="change-item">
            <label><span>{{ targetLabel(item) }}</span>
              <select v-model="item.status" :disabled="!editable">
                <option value="started">开始</option>
                <option value="advanced">推进</option>
                <option value="completed">完成</option>
              </select>
            </label>
            <small>{{ evidenceText(item.evidence) }}</small>
            <label>
              <span>任务状态判断依据</span>
              <n-input
                :value="item.evidence.rationale"
                type="textarea"
                :input-props="{ 'aria-label': `任务状态判断依据：${targetLabel(item)}` }"
                :disabled="!editable"
                :status="progressRationaleError(item) ? 'error' : undefined"
                @update:value="updateProgressRationale(item.id, $event)"
              />
              <small>1–500 个字符；沿用本条任务状态和原文定位。</small>
              <small v-if="progressRationaleError(item)" class="rationale-error" role="alert">{{ progressRationaleError(item) }}</small>
            </label>
            <n-button size="small" :disabled="!editable" @click="excludeProgress(item.id)">排除此项进度</n-button>
          </article>
        </div>

        <div v-if="changeSetDraft.planningPatches.length" class="change-group">
          <h4>未来规划调整</h4>
          <article v-for="item in changeSetDraft.planningPatches" :key="item.id" class="change-item">
            <strong>{{ targetLabel(item) }} · {{ fieldLabel(item.fieldPath) }}</strong>
            <n-input
              v-if="typeof item.replacement === 'string'"
              v-model:value="item.replacement"
              :disabled="!editable"
            />
            <pre v-else>{{ displayValue(item.replacement) }}</pre>
            <small>{{ evidenceText(item.evidence) }}</small>
            <n-button
              size="small"
              :disabled="!editable"
              @click="removePlanningPatch(item.id)"
            >移除此项调整</n-button>
          </article>
        </div>

        <div v-if="changeSetDraft.planningSuggestions.length" class="change-group">
          <h4>非权威建议</h4>
          <p class="muted">以下建议仅供作者参考，不会写入规划。</p>
          <article v-for="item in changeSetDraft.planningSuggestions" :key="item.id">
            <p>{{ item.message }}</p>
            <small>{{ evidenceText(item.evidence) }}</small>
          </article>
        </div>
      </section>

      <p v-if="pendingFields" class="muted" role="status">请先完成字段编辑或添加补录事实；清空尚未添加的内容也可取消本次输入。</p>
      <n-button
        v-if="changed"
        type="primary"
        block
        :loading="controller.busy.value"
        :disabled="!editable || pendingFields"
        @click="saveCorrection"
      >保存修正</n-button>
      <n-button
        v-if="controller.primaryAction.value === 'confirm'"
        block
        secondary
        :disabled="busy"
        @click="cancelReview"
      >放弃审查并返回修改</n-button>
      <n-button
        v-if="controller.primaryAction.value === 'confirm'"
        type="primary"
        block
        :loading="controller.busy.value"
        :disabled="!editable || unsaved || requiredFindings"
        @click="confirmChangeSet"
      >确认以上变更</n-button>
      <n-button
        v-else-if="controller.primaryAction.value === 'commit'"
        type="success"
        block
        :loading="controller.busy.value"
        :disabled="busy || draftStale || requiredFindings"
        @click="commitChapter"
      >定稿本章</n-button>
      <section v-if="controller.canRevoke?.value" class="review-section" aria-label="撤销已确认审查">
        <n-button :disabled="busy" @click="revokeConfirmation = !revokeConfirmation">撤销已确认审查</n-button>
        <template v-if="revokeConfirmation">
          <p>本章尚未定稿。撤销本次审查会保留正文、候选和已有审查记录；重新审查将再次调用模型。</p>
          <n-button :disabled="busy" @click="revokeReview">确认撤销本次审查</n-button>
        </template>
      </section>
    </template>
    <section v-if="referenceFromReview(review) && !controller.finalized.value" class="review-section" aria-label="按审稿意见调整">
      <n-button type="primary" color="#934735" block :disabled="busy || draftStale || unsaved" @click="emit('adjust-review')">基于审稿意见调整</n-button>
      <p v-if="unsaved" class="muted">先保存或放弃未保存的审稿修正，再调整正文。</p>
    </section>
  </n-card>
</template>

<style scoped>
.finalization-panel { border-top: 3px solid #9b6a32; }
.panel-intro { margin: 0 0 14px; color: #675d51; font-size: 12px; line-height: 1.7; }
.panel-alert { margin-bottom: 14px; }
.finalized-actions { display: grid; gap: 10px; }
.finalized-transition-status { min-height: 44px; margin: 0; color: #675d51; font-size: 12px; line-height: 1.7; }
.finalized-action { min-height: 44px; border-radius: 8px; color: #4d4033; text-decoration: none; }
.finalized-action:focus-visible { outline: 2px solid #8b5c25; outline-offset: 3px; }
.finalized-action--primary { display: grid; gap: 4px; border: 1px solid #b88955; padding: 13px 14px; background: #fbf2e3; }
.finalized-action--primary small { color: #8b5c25; font-size: 10px; font-weight: 800; letter-spacing: .12em; }
.finalized-action--primary strong { font-family: Georgia, 'Noto Serif SC', serif; font-size: 16px; }
.finalized-action--primary span { color: #675d51; font-size: 12px; line-height: 1.6; }
.finalized-action--secondary { display: flex; align-items: center; justify-content: center; border: 1px solid #d9cbb7; padding: 9px 12px; font-weight: 700; }
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
.change-item .rationale-error { color: #a33b2b; }
.fact-kind-tag { justify-self: start; }
.fact-identity { overflow-wrap: anywhere; color: #675d51; font-size: 11px; }
.fact-comparison { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 8px 0; }
.fact-comparison section { min-width: 0; padding: 10px; border: 1px solid #e4d8c6; border-radius: 6px; background: #fffdf8; }
.fact-comparison section > strong { display: block; margin-bottom: 8px; font-size: 12px; }
.fact-comparison small { display: block; overflow-wrap: anywhere; }
.fact-comparison pre { max-height: 220px; }
@media (max-width: 800px) { .fact-comparison { grid-template-columns: 1fr; } }
.fact-correction { min-width: 0; margin: 8px 0; border-top: 1px solid #dfd1bc; padding-top: 9px; }
.fact-correction summary { cursor: pointer; color: #835531; font-size: 12px; font-weight: 700; }
.fact-correction summary:focus-visible { outline: 2px solid #9b6a32; outline-offset: 3px; }
pre { overflow: auto; max-height: 150px; margin: 0; color: #55493c; white-space: pre-wrap; overflow-wrap: anywhere; font: 11px/1.6 ui-monospace, monospace; }
.muted { color: #6f6559; font-size: 12px; line-height: 1.6; }
.finding-selected { border-left:3px solid var(--nc-vermilion); padding-left:8px; }
</style>
