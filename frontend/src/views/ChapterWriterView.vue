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

import { useChapterSessionStore } from '@/stores/chapterSessionStore'
import {
  createChapterEditorState,
  decideChapterNavigation,
} from '@/utils/chapterEditorState'
import { createLatestRequestGuard } from '@/utils/latestRequest'
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
const outlineAuthority = ref(null)
const authorInstruction = ref('')
const editorState = createChapterEditorState()
const editorContent = editorState.editorContent

const projectId = computed(() => String(route.params.projectId || ''))
const chapterNumber = computed(() => Number(route.params.chapterNumber))
const session = computed(() => chapterSessionStore.session)
const workingDraft = computed(() => chapterSessionStore.workingDraft)
const candidates = computed(() => chapterSessionStore.candidates)
const confirmedOutline = computed(
  () => outlineAuthority.value?.confirmedOutline || null,
)
const outlineContent = computed(() => confirmedOutline.value?.content || null)
const chapterConflict = computed(() => (
  outlineAuthority.value !== null
  && outlineAuthority.value.authoritativeChapterNumber !== chapterNumber.value
))
const archived = computed(
  () => outlineAuthority.value?.lifecycle === 'archived',
)
const storyBlocksPath = computed(
  () => planningStoryBlocksPath(projectId.value),
)
const canSaveDraft = computed(() => (
  chapterSessionStore.hasSession
  && !chapterSessionStore.busy
))
const canGenerateDraft = computed(() => (
  chapterSessionStore.hasSession
  && !chapterSessionStore.busy
  && workingDraft.value?.revision != null
))
const canSaveCandidate = computed(() => (
  chapterSessionStore.hasSession
  && !chapterSessionStore.busy
  && workingDraft.value?.revision != null
))

async function loadWorkspace(nextProjectId, nextChapterNumber) {
  const targetProjectId = String(nextProjectId || '')
  const targetChapterNumber = Number(nextChapterNumber)
  const generation = loadGuard.begin()
  loading.value = true
  pageError.value = ''
  outlineAuthority.value = null
  try {
    const current = await chapterSessionStore.openAuthoritative(
      targetProjectId,
      targetChapterNumber,
    )
    if (!loadGuard.isCurrent(generation)) return
    if (current === null) return
    outlineAuthority.value = current
    editorState.syncFromWorkspace(chapterSessionStore.workspace)
  } catch (error) {
    if (!loadGuard.isCurrent(generation)) return
    pageError.value = error.message || '章节工作台加载失败'
  } finally {
    if (loadGuard.isCurrent(generation)) loading.value = false
  }
}

async function saveWorkingDraft() {
  const saveToken = editorState.beginSave()
  const saved = await chapterSessionStore.saveWorkingDraft(
    projectId.value,
    editorContent.value,
  )
  editorState.finishSave(saved, saveToken)
}

async function generateWorkingDraft() {
  const generated = await chapterSessionStore.generateWorkingDraft(
    projectId.value,
    authorInstruction.value,
  )
  editorState.finishGeneration(generated)
}

async function saveCandidate() {
  await chapterSessionStore.saveCandidate(projectId.value)
}

function backToProject() {
  router.push(projectOverviewPath(projectId.value))
}

function canLeaveChapter() {
  return decideChapterNavigation({
    busy: chapterSessionStore.writeBusy,
    dirty: editorState.dirty.value,
    confirmDiscard: () => window.confirm('当前工作稿尚未保存，确认放弃这些修改吗？'),
  })
}

watch(() => [route.params.projectId, route.params.chapterNumber], ([nextProjectId, nextChapterNumber]) => {
  loadWorkspace(String(nextProjectId || ''), Number(nextChapterNumber))
}, { immediate: true })

onBeforeRouteUpdate(() => canLeaveChapter())
onBeforeRouteLeave(() => canLeaveChapter())

onBeforeUnmount(() => {
  loadGuard.invalidate()
  chapterSessionStore.invalidate()
})
</script>

<template>
  <main class="writer-shell">
    <section v-if="loading" class="writer-loading" aria-busy="true" aria-label="正在加载章节工作台">
      <n-skeleton text width="28%" />
      <n-skeleton height="420px" />
    </section>

    <n-result v-else-if="pageError" status="error" title="章节工作台未能加载" :description="pageError" class="writer-result">
      <template #footer>
        <n-button @click="backToProject">返回项目</n-button>
        <n-button type="primary" @click="loadWorkspace(projectId, chapterNumber)">重试</n-button>
      </template>
    </n-result>

    <n-result
      v-else-if="chapterConflict"
      status="warning"
      title="章节地址与服务端权威不一致"
      description="当前地址不是服务端确认的权威章节；系统不会自动跳转，也不会读取或创建错误章节的会话。"
      class="writer-result"
    >
      <router-link :to="outlineAuthority.targetPath">
        前往第 {{ outlineAuthority.authoritativeChapterNumber }} 章
      </router-link>
    </n-result>

    <n-result
      v-else-if="archived"
      status="info"
      title="项目已归档"
      description="章节与小纲仅供查看，归档项目不会读取或创建写作会话。"
      class="writer-result"
    >
      <template #footer>
        <n-button @click="backToProject">返回项目</n-button>
      </template>
    </n-result>

    <template v-else>
      <header class="writer-hero">
        <div>
          <p class="eyebrow">M5 / AI WORKING DRAFT</p>
          <h1>章节工作台</h1>
          <p>编辑不会自动生成候选；只有点击“保存为候选”才会冻结当前工作稿。</p>
        </div>
        <n-button @click="backToProject">返回项目</n-button>
      </header>

      <n-alert
        v-if="!confirmedOutline"
        type="warning"
        class="writer-alert"
        title="请先完成并确认本章小纲"
      >
        本章没有可用于写作的当前确认小纲。
        <router-link :to="storyBlocksPath">前往故事块与章节小纲</router-link>
      </n-alert>

      <section class="workspace-grid">
        <n-card class="editor-card" :bordered="false">
          <template #header>
            <div class="card-header">
              <div>
                <strong>WorkingDraft</strong>
                <span v-if="session">第 {{ session.chapterNum }} 章 · revision {{ workingDraft?.revision }}</span>
                <span v-else>第 {{ chapterNumber }} 章 · 尚未创建章节会话</span>
              </div>
              <n-tag :type="session ? 'success' : 'default'" :bordered="false">
                {{ session ? 'drafting' : 'not started' }}
              </n-tag>
            </div>
          </template>

          <n-input
            v-model:value="editorContent"
            type="textarea"
            :autosize="{ minRows: 22 }"
            placeholder="在这里手动输入、粘贴或继续编辑章节正文。AI 生成只会进入工作稿，不会自动保存候选。"
            :disabled="!session || chapterSessionStore.generatingDraft"
          />

          <div class="generation-box">
            <label for="author-instruction">作者临时要求</label>
            <n-input
              id="author-instruction"
              v-model:value="authorInstruction"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="可选：例如“多一点市井对话”“情绪更压迫”“不要写成设定说明”。"
              :disabled="!session || chapterSessionStore.generatingDraft"
            />
          </div>

          <div class="editor-actions">
            <n-button
              v-if="!session"
              type="primary"
              :disabled="true"
              :loading="chapterSessionStore.creating"
            >
              请先完成并确认本章小纲
            </n-button>
            <n-button
              type="primary"
              secondary
              :disabled="!canGenerateDraft"
              :loading="chapterSessionStore.generatingDraft"
              @click="generateWorkingDraft"
            >
              AI 生成工作稿
            </n-button>
            <n-button
              :disabled="!canSaveDraft"
              :loading="chapterSessionStore.savingDraft"
              @click="saveWorkingDraft"
            >
              保存工作稿
            </n-button>
            <n-button
              type="success"
              :disabled="!canSaveCandidate"
              :loading="chapterSessionStore.savingCandidate"
              @click="saveCandidate"
            >
              保存为候选
            </n-button>
          </div>
        </n-card>

        <aside class="side-stack">
          <n-card
            v-if="outlineContent"
            title="已确认小纲（只读）"
            :bordered="false"
          >
            <p class="outline-goal">{{ outlineContent.chapterGoal }}</p>
            <dl class="outline-summary">
              <div>
                <dt>预计登场</dt>
                <dd>{{ outlineContent.expectedCharacters?.join('、') || '—' }}</dd>
              </div>
              <div>
                <dt>承接线索</dt>
                <dd>{{ outlineContent.continuation?.join('、') || '—' }}</dd>
              </div>
              <div>
                <dt>计划任务</dt>
                <dd>{{ outlineContent.plannedTasks?.join('、') || '—' }}</dd>
              </div>
              <div>
                <dt>场景</dt>
                <dd>{{ outlineContent.scenes?.join('、') || '—' }}</dd>
              </div>
              <div>
                <dt>禁止提前发生</dt>
                <dd>{{ outlineContent.forbiddenEarlyEvents?.join('、') || '—' }}</dd>
              </div>
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
              <li v-for="candidate in candidates" :key="candidate.id">
                revision {{ candidate.workingDraftRevision }}
              </li>
            </ol>
            <p v-else class="muted">暂无候选。先保存工作稿，再按需保存为候选。</p>
          </n-card>

          <n-alert v-if="chapterSessionStore.error" type="error" title="章节写入失败">
            {{ chapterSessionStore.error.message }}
          </n-alert>
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
.eyebrow { margin: 0 0 8px; color: #967548; font-size: 10px; font-weight: 800; letter-spacing: .18em; }
h1 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(34px, 5vw, 54px); font-weight: 650; }
.writer-hero p:last-child { max-width: 64ch; margin: 12px 0 0; color: #786f62; line-height: 1.8; }
.writer-alert { margin-top: 20px; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 20px; margin-top: 24px; }
.editor-card, .side-stack :deep(.n-card) { background: #fffdf8; box-shadow: 0 18px 60px rgba(58, 48, 34, .08); }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.card-header strong { display: block; font-family: Georgia, 'Noto Serif SC', serif; font-size: 18px; }
.card-header span { color: #82786b; font-size: 12px; }
.generation-box { display: grid; gap: 8px; margin-top: 14px; }
.generation-box label { color: #70675c; font-size: 12px; font-weight: 700; }
.editor-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.side-stack { display: grid; align-content: start; gap: 16px; }
.muted { margin: 0; color: #81776a; line-height: 1.7; }
.small { margin: 10px 0 0; color: #9a8d7c; font-size: 12px; }
.outline-goal { margin: 0 0 14px; color: #433b32; font-family: Georgia, 'Noto Serif SC', serif; line-height: 1.7; }
.outline-summary { display: grid; gap: 12px; margin: 0; }
.outline-summary div { display: grid; gap: 3px; }
.outline-summary dt { color: #967548; font-size: 11px; font-weight: 800; letter-spacing: .08em; }
.outline-summary dd { margin: 0; color: #6f6559; font-size: 13px; line-height: 1.65; }
.candidate-list { margin: 14px 0 0; padding-left: 20px; color: #675d51; font-size: 13px; }
@media (max-width: 900px) { .workspace-grid { grid-template-columns: 1fr; } .writer-hero { align-items: flex-start; flex-direction: column; } }
</style>
