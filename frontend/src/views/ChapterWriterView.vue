<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  onBeforeRouteLeave,
  onBeforeRouteUpdate,
  useRoute,
  useRouter,
} from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NInput,
  NResult,
  NSkeleton,
  NStatistic,
  NTag,
} from 'naive-ui'

import PlainTextDraftEditor from '@/components/writer/PlainTextDraftEditor.vue'
import { createWorkingDraftAutosave } from '@/application/writer/workingDraftAutosave'
import { createChapterWriterController } from '@/application/writer/chapterWriterController'
import { useChapterSessionStore } from '@/stores/chapterSessionStore'
import { createLatestRequestGuard } from '@/utils/latestRequest'
import {
  limitUnicodeScalarText,
  unicodeScalarLength,
} from '@/utils/unicodeScalarText'
import {
  planningStoryBlocksPath,
  projectOverviewPath,
} from '@/router/projectRoutes'

const route = useRoute()
const router = useRouter()
const chapterSessionStore = useChapterSessionStore()
const loadGuard = createLatestRequestGuard()

const loading = ref(true)
const pageError = ref('')
const actionError = ref('')
const outlineAuthority = ref(null)
const lastSavedAt = ref('')

const projectId = computed(() => String(route.params.projectId || ''))
const chapterNumber = computed(() => Number(route.params.chapterNumber))
const session = computed(() => chapterSessionStore.session)
const candidates = computed(() => chapterSessionStore.candidates)
const selectedCandidateIds = ref([])
const selectedCandidates = computed(() => candidates.value.filter(
  candidate => selectedCandidateIds.value.includes(candidate.id),
))
const confirmedOutline = computed(
  () => outlineAuthority.value?.confirmedOutline || null,
)
const outlineContent = computed(() => confirmedOutline.value?.content || null)
const chapterConflict = computed(() => (
  outlineAuthority.value !== null
  && outlineAuthority.value.authoritativeChapterNumber !== chapterNumber.value
))
const archived = computed(() => outlineAuthority.value?.lifecycle === 'archived')
const storyBlocksPath = computed(() => planningStoryBlocksPath(projectId.value))

const autosave = createWorkingDraftAutosave({
  persist: snapshot => chapterSessionStore.saveWorkingDraft(
    projectId.value,
    snapshot,
  ),
})
const controller = createChapterWriterController({
  autosave,
  writeBusy: () => chapterSessionStore.commandBusy,
  freezeCandidate: command => chapterSessionStore.saveCandidate(projectId.value, command),
  loadCandidate: (candidateId, command) => chapterSessionStore.loadCandidate(
    projectId.value,
    candidateId,
    command,
  ),
  createDraftOperation: command => chapterSessionStore.createDraftOperation(
    projectId.value,
    command,
  ),
  readDraftOperation: operationId => chapterSessionStore.readDraftOperation(
    projectId.value,
    operationId,
  ),
  listDraftOperationEvents: (operationId, afterSequence) => chapterSessionStore.listDraftOperationEvents(
    projectId.value,
    operationId,
    afterSequence,
  ),
  cancelDraftOperation: operationId => chapterSessionStore.cancelDraftOperation(
    projectId.value,
    operationId,
  ),
  undoLocalDraft: command => chapterSessionStore.undoLocalDraft(
    projectId.value,
    command,
  ),
  reloadWorkspace: () => chapterSessionStore.reloadCurrentWorkspace(projectId.value),
})
const validSelection = computed(() => {
  const value = controller.selection.value
  const startOffset = value?.startOffset
  const endOffset = value?.endOffset
  const selectedText = value?.selectedText
  const scalars = Array.from(controller.editorText.value)
  return Number.isInteger(startOffset)
    && startOffset >= 0
    && Number.isInteger(endOffset)
    && endOffset > startOffset
    && endOffset <= scalars.length
    && typeof selectedText === 'string'
    && selectedText.length > 0
    && scalars.slice(startOffset, endOffset).join('') === selectedText
})
const authorInstructionLimit = computed(() => validSelection.value ? 1_000 : 2_000)
const authorInstructionNotice = ref('')
const authorInstructionCount = computed(
  () => unicodeScalarLength(controller.authorInstruction.value),
)

function updateAuthorInstruction(nextInstruction) {
  try {
    const limit = authorInstructionLimit.value
    const limited = limitUnicodeScalarText(String(nextInstruction ?? ''), limit)
    controller.setAuthorInstruction(limited.value)
    authorInstructionNotice.value = limited.truncated
      ? `已截断超过 ${limit} 个 Unicode 字符的内容。`
      : ''
  } catch {
    authorInstructionNotice.value = '输入包含无效字符，未接受。'
  }
}

const editorDisabled = computed(() => !session.value)
const editorReadonly = computed(() => controller.actionBusy.value)
const commandDisabled = computed(() => (
  !session.value || controller.actionBusy.value || chapterSessionStore.commandBusy
))
const localCommandDisabled = computed(() => (
  commandDisabled.value
  || !validSelection.value
  || authorInstructionCount.value > 1_000
))

function candidateSelected(candidateId) {
  return selectedCandidateIds.value.includes(candidateId)
}

function candidateSelectionDisabled(candidateId) {
  return controller.actionBusy.value
    || chapterSessionStore.commandBusy
    || (!candidateSelected(candidateId) && selectedCandidateIds.value.length >= 2)
}

function toggleCandidateSelection(candidateId) {
  if (candidateSelectionDisabled(candidateId)) return
  if (candidateSelected(candidateId)) {
    selectedCandidateIds.value = selectedCandidateIds.value.filter(
      value => value !== candidateId,
    )
    return
  }
  if (selectedCandidateIds.value.length >= 2) return
  selectedCandidateIds.value = [...selectedCandidateIds.value, candidateId]
}

function candidateCharacterCount(candidate) {
  return unicodeScalarLength(String(candidate.content ?? ''))
}

function formatCandidateTime(createdAt) {
  const date = new Date(createdAt)
  if (!Number.isFinite(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

watch(candidates, nextCandidates => {
  const ids = new Set(nextCandidates.map(candidate => candidate.id))
  selectedCandidateIds.value = selectedCandidateIds.value.filter(
    candidateId => ids.has(candidateId),
  )
}, { flush: 'sync' })

function savedTime() {
  const now = new Date()
  return [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map(value => String(value).padStart(2, '0'))
    .join(':')
}

function updateLastSavedAt() {
  if (session.value && Number.isInteger(autosave.persistedRevision.value)) {
    lastSavedAt.value = savedTime()
  }
}

watch(() => autosave.persistedRevision.value, updateLastSavedAt, { flush: 'sync' })

async function loadWorkspace(nextProjectId, nextChapterNumber) {
  controller.resetContext()
  selectedCandidateIds.value = []
  lastSavedAt.value = ''
  const targetProjectId = String(nextProjectId || '')
  const targetChapterNumber = Number(nextChapterNumber)
  const generation = loadGuard.begin()
  loading.value = true
  pageError.value = ''
  actionError.value = ''
  outlineAuthority.value = null
  try {
    const current = await chapterSessionStore.openAuthoritative(
      targetProjectId,
      targetChapterNumber,
    )
    if (!loadGuard.isCurrent(generation) || current === null) return
    outlineAuthority.value = current
    if (chapterSessionStore.workspace?.workingDraft) {
      autosave.reset(chapterSessionStore.workspace)
      updateLastSavedAt()
      const activeDraftOperationId = chapterSessionStore.workspace?.activeDraftOperationId
      if (activeDraftOperationId) {
        void controller.resumeDraftOperation(activeDraftOperationId).catch(() => {
          if (!loadGuard.isCurrent(generation)) return
          actionError.value = '生成失败'
        })
      }
    }
  } catch {
    if (!loadGuard.isCurrent(generation)) return
    pageError.value = '章节工作台加载失败，请稍后重试。'
  } finally {
    if (loadGuard.isCurrent(generation)) loading.value = false
  }
}

async function generateWorkingDraft() {
  actionError.value = ''
  try {
    const result = await controller.generateWorkingDraft()
    if (!result && !controller.operationStatusText.value) {
      actionError.value = '当前工作稿未能安全暂存，请稍后重试。'
    }
  } catch {
    if (!controller.operationStatusText.value) {
      actionError.value = '当前工作稿未能完成生成，请检查作者要求后重试。'
    }
  }
}

async function retryUnknown() {
  actionError.value = ''
  try {
    await controller.retryUnknown()
  } catch {
    // Unknown retries retain the coordinator-owned key and fixed status text.
  }
}

async function stopGeneration() {
  actionError.value = ''
  try {
    await controller.cancelGeneration()
  } catch {
    if (!controller.operationStatusText.value) actionError.value = '生成失败'
  }
}

async function runSelectionOperation(operationType) {
  actionError.value = ''
  try {
    const result = await controller.runSelectionOperation(operationType)
    if (!result && !controller.operationStatusText.value) {
      actionError.value = '当前选区未能安全处理，请重新选择后重试。'
    }
  } catch {
    if (!controller.operationStatusText.value) {
      actionError.value = '当前选区 AI 操作未完成，请重新选择后重试。'
    }
  }
}

async function undoLastLocal() {
  actionError.value = ''
  try {
    const result = await controller.undoLastLocal()
    if (!result) actionError.value = '本次 AI 修改已不能安全撤销。'
  } catch {
    actionError.value = '本次 AI 修改已不能安全撤销。'
  }
}

async function saveCandidate() {
  actionError.value = ''
  try {
    const result = await controller.saveCandidate()
    if (!result) actionError.value = '当前工作稿未能安全暂存，请稍后重试。'
  } catch {
    actionError.value = '当前工作稿未能保存为候选，请稍后重试。'
  }
}

async function loadCandidate(candidate) {
  actionError.value = ''
  try {
    const result = await controller.loadCandidate(candidate)
    if (!result) actionError.value = '候选稿未能安全载入，请稍后重试。'
  } catch {
    actionError.value = '候选稿未能安全载入，请刷新后重试。'
  }
}

async function retryAutosave() {
  try {
    await autosave.retry()
  } catch {
    // The editor keeps the precise failed/conflict persistence status visible.
  }
}

function backToProject() {
  if (controller.actionBusy.value) return
  router.push(projectOverviewPath(projectId.value))
}

function guardBusyNavigation(event) {
  if (!controller.actionBusy.value) return
  event.preventDefault()
}

function beforeUnload(event) {
  event.preventDefault()
  event.returnValue = ''
  return ''
}

let beforeUnloadRegistered = false
function syncBeforeUnloadRisk(enabled) {
  if (typeof window === 'undefined' || enabled === beforeUnloadRegistered) return
  if (enabled) window.addEventListener('beforeunload', beforeUnload)
  else window.removeEventListener('beforeunload', beforeUnload)
  beforeUnloadRegistered = enabled
}
const stopBeforeUnloadRisk = watch(
  () => controller.beforeUnloadRisk.value,
  syncBeforeUnloadRisk,
  { immediate: true, flush: 'sync' },
)

watch(() => [route.params.projectId, route.params.chapterNumber], ([nextProjectId, nextChapterNumber]) => {
  void loadWorkspace(String(nextProjectId || ''), Number(nextChapterNumber))
}, { immediate: true })

onBeforeRouteUpdate(async () => await controller.canNavigate())
onBeforeRouteLeave(async () => await controller.canNavigate())

onBeforeUnmount(() => {
  stopBeforeUnloadRisk()
  syncBeforeUnloadRisk(false)
  loadGuard.invalidate()
  controller.dispose()
  autosave.dispose()
  chapterSessionStore.invalidate()
})
</script>

<template>
  <main class="writer-shell">
    <nav class="writer-navigation" aria-label="章节工作台导航">
      <router-link
        :to="storyBlocksPath"
        class="writer-outline-link"
        :aria-disabled="controller.actionBusy.value"
        :tabindex="controller.actionBusy.value ? -1 : 0"
        @click="guardBusyNavigation"
      >调整本章小纲</router-link>
    </nav>
    <section v-if="loading" class="writer-loading" aria-busy="true" aria-label="正在加载章节工作台">
      <n-skeleton text width="28%" />
      <n-skeleton height="420px" />
    </section>

    <n-result v-else-if="pageError" status="error" title="章节工作台未能加载" :description="pageError" class="writer-result">
      <template #footer>
        <n-button :disabled="controller.actionBusy.value" @click="backToProject">返回项目</n-button>
        <n-button type="primary" @click="loadWorkspace(projectId, chapterNumber)">重试</n-button>
      </template>
    </n-result>

    <n-result v-else-if="chapterConflict" status="warning" title="章节地址与服务端权威不一致" description="当前地址不是服务端确认的权威章节；系统不会自动跳转，也不会读取或创建错误章节的会话。" class="writer-result">
      <router-link :to="outlineAuthority.targetPath">前往第 {{ outlineAuthority.authoritativeChapterNumber }} 章</router-link>
    </n-result>

    <n-result v-else-if="archived" status="info" title="项目已归档" description="章节与小纲仅供查看，归档项目不会读取或创建写作会话。" class="writer-result">
      <template #footer><n-button @click="backToProject">返回项目</n-button></template>
    </n-result>

    <template v-else>
      <header class="writer-hero">
        <div>
          <p class="eyebrow">M5 / AI WORKING DRAFT</p>
          <h1>章节工作台</h1>
          <p>编辑会自动暂存；只有点击“保存为候选”才会冻结当前工作稿。</p>
        </div>
        <n-button :disabled="controller.actionBusy.value" @click="backToProject">返回项目</n-button>
      </header>

      <n-alert v-if="!confirmedOutline" type="warning" class="writer-alert" title="请先完成并确认本章小纲">
        本章没有可用于写作的当前确认小纲。<router-link :to="storyBlocksPath">前往故事块与章节小纲</router-link>
      </n-alert>

      <section class="workspace-grid">
        <n-card class="editor-card" :bordered="false">
          <template #header>
            <div class="card-header">
              <div>
                <strong>WorkingDraft</strong>
                <span v-if="session">第 {{ session.chapterNum }} 章 · revision {{ autosave.persistedRevision.value }}</span>
                <span v-else>第 {{ chapterNumber }} 章 · 尚未创建章节会话</span>
              </div>
              <n-tag :type="session ? 'success' : 'default'" :bordered="false">{{ session ? 'drafting' : 'not started' }}</n-tag>
            </div>
          </template>

          <div v-if="session" class="editor-surface" :aria-busy="controller.actionBusy.value">
            <plain-text-draft-editor
              :model-value="controller.editorText.value"
              :disabled="editorDisabled"
              :readonly="editorReadonly"
              :streaming="controller.streamingPreview.value !== null"
              :selection-range="controller.restoredSelection.value"
              :dirty="autosave.dirty.value"
              :status="autosave.status.value"
              :last-saved-at="lastSavedAt"
              placeholder="在这里手动输入、粘贴或继续编辑章节正文。AI 生成只会进入工作稿，不会自动保存候选。"
              @update:model-value="controller.edit"
              @selection-change="controller.setSelection"
              @retry="retryAutosave"
            />
            <div v-if="validSelection" class="selection-tools" aria-label="AI 选区工具">
              <span>已选择 {{ Array.from(controller.selection.value.selectedText).length }} 字</span>
              <n-button size="small" secondary :disabled="localCommandDisabled" :loading="controller.actionBusy.value" @click="runSelectionOperation('rewrite_selection')">AI 改写</n-button>
              <n-button size="small" secondary :disabled="localCommandDisabled" :loading="controller.actionBusy.value" @click="runSelectionOperation('polish_selection')">AI 润色</n-button>
              <n-button size="small" secondary :disabled="localCommandDisabled" :loading="controller.actionBusy.value" @click="runSelectionOperation('expand_selection')">AI 扩写</n-button>
              <n-button size="small" secondary :disabled="localCommandDisabled" :loading="controller.actionBusy.value" @click="runSelectionOperation('compress_selection')">AI 缩写</n-button>
            </div>
            <section
              v-if="controller.replacementPreview.value !== null"
              class="replacement-preview"
              aria-live="polite"
              aria-label="替换内容预览"
            >
              <strong>替换内容预览</strong>
              <pre>{{ controller.replacementPreview.value }}</pre>
            </section>
            <div
              v-if="controller.operationStatusText.value"
              class="draft-operation-layer"
              aria-live="polite"
              role="status"
            >
              <span>{{ controller.operationStatusText.value }}</span>
              <button
                v-if="controller.operationRetryAvailable.value"
                type="button"
                class="draft-operation-retry"
                @click="retryUnknown"
              >重试</button>
            </div>
          </div>
          <p v-else class="draft-empty">完成并确认本章小纲后，即可开始撰写正文。</p>

          <div class="generation-box">
            <label for="author-instruction">作者临时要求</label>
            <n-input id="author-instruction" :value="controller.authorInstruction.value" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" aria-describedby="author-instruction-count" placeholder="可选：例如“多一点市井对话”“情绪更压迫”“不要写成设定说明”。" :disabled="commandDisabled" @update:value="updateAuthorInstruction" />
            <p id="author-instruction-count" class="author-instruction-count" aria-live="polite">{{ authorInstructionCount }} / {{ authorInstructionLimit }}<span v-if="authorInstructionNotice"> · {{ authorInstructionNotice }}</span></p>
          </div>

          <div class="editor-actions">
            <n-button v-if="controller.operationCancellable.value" type="warning" @click="stopGeneration">停止生成</n-button>
            <template v-else>
              <n-button v-if="!session" type="primary" :disabled="true" :loading="chapterSessionStore.creating">请先完成并确认本章小纲</n-button>
              <n-button type="primary" secondary :disabled="commandDisabled" :loading="controller.actionBusy.value" @click="generateWorkingDraft">AI 生成工作稿</n-button>
              <n-button type="success" :disabled="commandDisabled" :loading="controller.actionBusy.value" @click="saveCandidate">保存为候选</n-button>
              <n-button v-if="controller.undoAvailable.value" secondary :disabled="commandDisabled" :loading="controller.actionBusy.value" @click="undoLastLocal">撤销本次 AI 修改</n-button>
            </template>
          </div>
          <n-alert v-if="actionError" type="error" class="writer-action-error" title="章节操作未完成">{{ actionError }}</n-alert>
        </n-card>

        <aside class="side-stack">
          <n-card v-if="outlineContent" title="已确认小纲（只读）" :bordered="false">
            <p class="outline-goal">{{ outlineContent.chapterGoal }}</p>
            <dl class="outline-summary">
              <div><dt>预计登场</dt><dd>{{ outlineContent.expectedCharacters?.join('、') || '—' }}</dd></div>
              <div><dt>承接线索</dt><dd>{{ outlineContent.continuation?.join('、') || '—' }}</dd></div>
              <div><dt>计划任务</dt><dd>{{ outlineContent.plannedTasks?.join('、') || '—' }}</dd></div>
              <div><dt>场景</dt><dd>{{ outlineContent.scenes?.join('、') || '—' }}</dd></div>
              <div><dt>禁止提前发生</dt><dd>{{ outlineContent.forbiddenEarlyEvents?.join('、') || '—' }}</dd></div>
            </dl>
          </n-card>

          <n-card title="本章权威基线" :bordered="false">
            <template v-if="session">
              <p class="muted">第 {{ session.chapterNum }} 章 · 状态：{{ session.status }}</p>
              <p class="muted">Planning R{{ session.planningRevision }}</p>
              <p class="small">Outline R{{ session.chapterOutlineRevision }} · StoryBlock R{{ session.storyBlockRevision }}</p>
            </template>
            <p v-else class="muted">确认本章小纲后，系统会在这里展示不可变的 Planning、StoryBlock 与 Outline 基线。</p>
          </n-card>

          <n-card title="候选稿" :bordered="false">
            <n-statistic label="已保存候选" :value="candidates.length" />
            <ol v-if="candidates.length" class="candidate-list">
              <li v-for="(candidate, index) in candidates" :key="candidate.id" class="candidate-item">
                <label class="candidate-select">
                  <input
                    type="checkbox"
                    :checked="candidateSelected(candidate.id)"
                    :disabled="candidateSelectionDisabled(candidate.id)"
                    :aria-label="`选择候选 ${index + 1} 进行比较`"
                    @change="toggleCandidateSelection(candidate.id)"
                  >
                  <strong>候选 {{ index + 1 }}</strong>
                </label>
                <span class="candidate-basis" :class="candidate.basisStatus === 'current' ? 'candidate-basis--current' : 'candidate-basis--stale'">{{ candidate.basisStatus === 'current' ? '依据当前小纲' : '依据旧小纲，不能定稿' }}</span>
                <span class="candidate-meta">{{ candidateCharacterCount(candidate) }} 字 · {{ candidate.contentHash.slice(0, 8) }} · {{ formatCandidateTime(candidate.createdAt) }}</span>
                <n-button size="tiny" secondary :disabled="commandDisabled" :loading="controller.actionBusy.value" @click="loadCandidate(candidate)">载入为工作稿</n-button>
              </li>
            </ol>
            <p v-else class="muted">暂无候选。工作稿会自动暂存，按需保存为候选。</p>
            <section
              v-if="selectedCandidates.length === 2"
              class="candidate-comparison"
              aria-label="候选稿只读比较"
            >
              <article
                v-for="candidate in selectedCandidates"
                :key="candidate.id"
                class="candidate-comparison-pane"
              >
                <strong>候选 {{ candidates.findIndex(item => item.id === candidate.id) + 1 }}</strong>
                <pre>{{ candidate.content }}</pre>
              </article>
            </section>
          </n-card>
        </aside>
      </section>
    </template>
  </main>
</template>

<style scoped>
.writer-shell { min-height: 100%; padding: clamp(22px, 4vw, 46px); color: #2d2923; background: #f4efe4; }
.writer-loading, .writer-result, .writer-hero, .writer-alert, .workspace-grid { width: min(1180px, 100%); margin-inline: auto; }
.writer-loading { display: grid; gap: 20px; padding: 34px; border: 1px solid #ddd3c0; border-radius: 16px; background: #fffdf8; }
.writer-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding-bottom: 24px; border-bottom: 1px solid #d7cbb8; }
.writer-navigation { display: flex; width: min(1180px, 100%); margin: 0 auto 16px; justify-content: flex-end; }
.writer-outline-link { color: #8b5c25; font-size: 13px; font-weight: 700; }
.eyebrow { margin: 0 0 8px; color: #967548; font-size: 10px; font-weight: 800; letter-spacing: .18em; }
h1 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(34px, 5vw, 54px); font-weight: 650; }
.writer-hero p:last-child { max-width: 64ch; margin: 12px 0 0; color: #786f62; line-height: 1.8; }
.writer-alert { margin-top: 20px; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 20px; margin-top: 24px; }
.editor-card, .side-stack :deep(.n-card) { background: #fffdf8; box-shadow: 0 18px 60px rgba(58, 48, 34, .08); }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.card-header strong { display: block; font-family: Georgia, 'Noto Serif SC', serif; font-size: 18px; }
.card-header span { color: #82786b; font-size: 12px; }
.editor-surface { position: relative; }
.editor-surface :deep(.plain-text-draft-editor) { overflow: auto; }
.draft-operation-layer { position: absolute; z-index: 2; top: 12px; right: 12px; display: flex; align-items: center; gap: 10px; max-width: calc(100% - 24px); max-height: 48px; overflow: auto; pointer-events: none; border: 1px solid rgba(150, 117, 72, .34); border-radius: 999px; padding: 8px 12px; color: #534535; background: rgba(255, 253, 248, .9); box-shadow: 0 8px 24px rgba(58, 48, 34, .1); font-size: 12px; font-weight: 700; }
.draft-operation-retry { pointer-events: auto; border: 0; padding: 0; color: #8b5c25; background: transparent; font: inherit; cursor: pointer; text-decoration: underline; }
.draft-operation-retry:focus-visible { outline: 2px solid #8b5c25; outline-offset: 3px; }
.selection-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; border-left: 3px solid #967548; padding: 8px 10px; background: #f8f1e5; }
.selection-tools > span { margin-right: 2px; color: #756858; font-size: 12px; font-weight: 700; }
.replacement-preview { margin-top: 10px; border: 1px solid #d8c7aa; border-radius: 8px; padding: 12px 14px; background: #f6efe2; box-shadow: inset 3px 0 0 #967548; }
.replacement-preview strong { color: #76552f; font-size: 12px; letter-spacing: .08em; }
.replacement-preview pre { overflow: auto; max-height: 220px; margin: 8px 0 0; color: #40372d; white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.8 Georgia, 'Noto Serif SC', serif; }
.draft-empty { min-height: 440px; display: grid; place-items: center; margin: 0; color: #81776a; border: 1px dashed #d7cbb8; border-radius: 10px; background: #fffefb; }
.generation-box { display: grid; gap: 8px; margin-top: 14px; }
.generation-box label { color: #70675c; font-size: 12px; font-weight: 700; }
.author-instruction-count { margin: 0; color: #81776a; font-size: 12px; text-align: right; }
.editor-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.writer-action-error { margin-top: 14px; }
.side-stack { display: grid; align-content: start; gap: 16px; }
.muted { margin: 0; color: #81776a; line-height: 1.7; }
.small { margin: 10px 0 0; color: #9a8d7c; font-size: 12px; }
.outline-goal { margin: 0 0 14px; color: #433b32; font-family: Georgia, 'Noto Serif SC', serif; line-height: 1.7; }
.outline-summary { display: grid; gap: 12px; margin: 0; }
.outline-summary div { display: grid; gap: 3px; }
.outline-summary dt { color: #967548; font-size: 11px; font-weight: 800; letter-spacing: .08em; }
.outline-summary dd { margin: 0; color: #6f6559; font-size: 13px; line-height: 1.65; }
.candidate-list { display: grid; gap: 10px; margin: 14px 0 0; padding: 0; color: #675d51; font-size: 13px; list-style: none; }
.candidate-item { display: grid; gap: 7px; border: 1px solid #e1d6c4; border-radius: 9px; padding: 10px; background: #fffaf1; }
.candidate-select { display: flex; align-items: center; gap: 8px; color: #453b31; cursor: pointer; }
.candidate-select input { accent-color: #8b5c25; }
.candidate-basis { display: block; margin-top: 4px; font-size: 12px; }
.candidate-basis--current { color: #487252; }
.candidate-basis--stale { color: #a35b42; }
.candidate-meta { color: #8a7d6d; font-size: 11px; line-height: 1.5; }
.candidate-comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 14px; border-top: 1px solid #ddd0bc; padding-top: 14px; }
.candidate-comparison-pane { min-width: 0; border-radius: 8px; padding: 9px; background: #f6efe2; }
.candidate-comparison-pane > strong { color: #76552f; font-size: 11px; }
.candidate-comparison-pane pre { overflow: auto; max-height: 260px; margin: 7px 0 0; color: #40372d; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.7 Georgia, 'Noto Serif SC', serif; }
@media (max-width: 900px) { .workspace-grid { grid-template-columns: 1fr; } .writer-hero { align-items: flex-start; flex-direction: column; } }
</style>
