<script setup>
import { computed, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NEmpty,
  NInput,
  NModal,
  NResult,
  NSkeleton,
  NSpin,
  NTag,
} from 'naive-ui'

import MarketEvidencePanel from '@/components/seeds/MarketEvidencePanel.vue'
import SeedCard from '@/components/seeds/SeedCard.vue'
import SeedEditor from '@/components/seeds/SeedEditor.vue'
import { useAppMessage } from '@/composables/useAppMessage'
import { useRouteProject } from '@/composables/useRouteProject'
import { useMarketSourceStore } from '@/stores/marketSourceStore'
import { useSeedStore } from '@/stores/seedStore'

const props = defineProps({
  projectId: { type: String, required: true },
})

const routeProject = useRouteProject()
const seedStore = useSeedStore()
const marketStore = useMarketSourceStore()
const message = useAppMessage()

const activeSection = ref('evidence')
const loadError = ref('')
const transcript = ref([])
const chatInput = ref('')
const proposal = ref(null)
const editorOpen = ref(false)
const editingSeed = ref(null)
const editorInitialPayload = ref(null)
const editorProvenance = ref(null)
const deleteTarget = ref(null)
const selectionTarget = ref(null)
let workspaceProjectId = ''
let workspaceGeneration = 0

const sections = Object.freeze([
  { key: 'evidence', label: '市场证据', index: '01' },
  { key: 'inspiration', label: '灵感讨论', index: '02' },
  { key: 'saved', label: '已存种子', index: '03' },
])

const readOnly = computed(() => (
  routeProject.state.value === 'archived'
  || routeProject.project.value?.archivedAt != null
))
const latestSnapshotIds = computed(() => marketStore.sources
  .map(source => marketStore.snapshotHistory[source.id]?.[0]?.id)
  .filter(Boolean)
  .slice(0, 4))
const analysisResult = computed(() => marketStore.analysisState.result)
const inspirationReady = computed(() => Boolean(
  latestSnapshotIds.value.length
  && analysisResult.value?.status === 'succeeded'
  && analysisResult.value?.id,
))
const currentGeneration = computed(() => seedStore.selectionRevision)
const activeCandidates = computed(() => seedStore.seeds.filter(seed => seed.status === 'candidate'))
const archivedCandidates = computed(() => seedStore.seeds.filter(seed => seed.status === 'archived'))

function commandKey() {
  const uuid = globalThis.crypto?.randomUUID?.().replaceAll('-', '')
  if (uuid) return `${uuid}${uuid}`.slice(0, 64)
  const fallback = `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
  return `${fallback}${fallback}${'0'.repeat(64)}`.slice(0, 64)
}

function resetProjectWorkspace(projectId) {
  workspaceProjectId = String(projectId)
  workspaceGeneration += 1
  activeSection.value = 'evidence'
  loadError.value = ''
  transcript.value = []
  chatInput.value = ''
  proposal.value = null
  editorOpen.value = false
  editingSeed.value = null
  editorInitialPayload.value = null
  editorProvenance.value = null
  deleteTarget.value = null
  selectionTarget.value = null
  marketStore.activateProject(projectId)
  seedStore.activateProject(projectId)
}

function isCurrentWorkspace(projectId, generation) {
  return workspaceProjectId === String(projectId)
    && workspaceGeneration === generation
}

async function loadWorkspace(projectId = props.projectId) {
  const generation = workspaceGeneration
  if (isCurrentWorkspace(projectId, generation)) loadError.value = ''
  try {
    await Promise.all([
      seedStore.refresh(projectId),
      marketStore.loadSources(),
    ])
  } catch (error) {
    if (isCurrentWorkspace(projectId, generation)) {
      loadError.value = error?.message || '种子工作区加载失败'
    }
  }
}

watch(
  () => [props.projectId, routeProject.state.value],
  ([projectId, state]) => {
    if (!projectId) return
    if (workspaceProjectId !== String(projectId)) {
      resetProjectWorkspace(projectId)
    }
    if (['active', 'archived'].includes(state)) void loadWorkspace(projectId)
  },
  { immediate: true },
)

function openCreate(payload = null, provenance = null) {
  if (readOnly.value || seedStore.activeSelection || seedStore.mutationBusy) return
  editingSeed.value = null
  editorInitialPayload.value = payload
  editorProvenance.value = provenance
  editorOpen.value = true
  activeSection.value = 'saved'
}

function openEdit(seed) {
  if (readOnly.value || !seed.capabilities?.canEdit) return
  editingSeed.value = seed
  editorInitialPayload.value = null
  editorProvenance.value = null
  editorOpen.value = true
  activeSection.value = 'saved'
}

function closeEditor() {
  editorOpen.value = false
  editingSeed.value = null
  editorInitialPayload.value = null
  editorProvenance.value = null
}

async function saveEditor(result) {
  if (result.error) {
    message.warning(result.error)
    return
  }
  const projectId = props.projectId
  const generation = workspaceGeneration
  const editTarget = editingSeed.value
  const provenance = editorProvenance.value
  try {
    if (editTarget) {
      await seedStore.updateSeed(projectId, editTarget.id, {
        payload: result.payload,
        expectedSeedRevision: editTarget.revision,
        expectedSelectionRevision: currentGeneration.value,
      })
    } else {
      await seedStore.createSeed(projectId, result.payload, {
        provenance: provenance || undefined,
        idempotencyKey: commandKey(),
      })
    }
    if (!isCurrentWorkspace(projectId, generation)) return
    message.success(editTarget ? '种子修订已保存' : '候选种子已保存')
    closeEditor()
  } catch (error) {
    if (isCurrentWorkspace(projectId, generation)) {
      message.error(error?.message || '种子保存失败')
    }
  }
}

async function sendInspiration() {
  const content = chatInput.value.trim()
  if (!content || !inspirationReady.value || readOnly.value) return
  const projectId = props.projectId
  const generation = workspaceGeneration
  const userTurn = { role: 'user', content }
  const nextTranscript = [...transcript.value, userTurn].slice(-11)
  chatInput.value = ''
  transcript.value = nextTranscript
  proposal.value = null
  try {
    const result = await seedStore.requestInspiration(projectId, {
      transcript: nextTranscript,
      snapshotIds: latestSnapshotIds.value,
      analysisId: analysisResult.value.id,
      idempotencyKey: commandKey(),
    })
    if (!isCurrentWorkspace(projectId, generation)) return
    if (result.status !== 'succeeded' || !result.assistantTurn) {
      throw new Error(result.publicErrorCode || '灵感讨论未生成可用建议')
    }
    transcript.value = [...nextTranscript, result.assistantTurn].slice(-12)
    proposal.value = {
      content: result.assistantTurn.content,
      attemptId: result.attemptId,
    }
  } catch (error) {
    if (isCurrentWorkspace(projectId, generation)) {
      message.error(error?.message || '灵感讨论失败')
    }
  }
}

function saveProposal() {
  if (
    seedStore.inspirationBusy
    || !proposal.value
    || !analysisResult.value
  ) return
  openCreate({
    title: '',
    genre: '',
    logline: proposal.value.content.slice(0, 2000),
    protagonist: '',
    desire: '',
    coreConflict: '',
    worldPressure: '',
    openingHook: '',
    differentiation: '',
  }, {
    kind: 'ai_chat',
    snapshotIds: [...latestSnapshotIds.value],
    analysisId: analysisResult.value.id,
    inspirationAttemptId: proposal.value.attemptId,
    publicNotes: [],
  })
}

async function selectSeed(seed) {
  if (readOnly.value || !seed?.capabilities?.canSelect) return
  const projectId = props.projectId
  const generation = workspaceGeneration
  try {
    await seedStore.selectSeed(projectId, {
      seedId: seed.id,
      expectedSeedRevision: seed.revision,
      expectedSelectionRevision: currentGeneration.value,
    })
    if (!isCurrentWorkspace(projectId, generation)) return
    message.success(`已选定《${seed.payload?.title || '未命名种子'}》`)
  } catch (error) {
    if (isCurrentWorkspace(projectId, generation)) {
      message.error(error?.message || '种子选定失败')
    }
  }
}

async function changeArchive(seed, action) {
  if (readOnly.value || (action === 'archive' && !seed?.capabilities?.canArchive) || (action === 'restore' && !seed?.capabilities?.canRestore)) return
  const projectId = props.projectId
  const generation = workspaceGeneration
  try {
    const data = {
      expectedSeedRevision: seed.revision,
      expectedSelectionRevision: currentGeneration.value,
    }
    if (action === 'archive') {
      await seedStore.archiveSeed(projectId, seed.id, data)
    } else {
      await seedStore.restoreSeed(projectId, seed.id, data)
    }
    if (!isCurrentWorkspace(projectId, generation)) return
    message.success(action === 'archive' ? '种子已归档' : '种子已恢复为候选')
  } catch (error) {
    if (isCurrentWorkspace(projectId, generation)) {
      message.error(error?.message || '种子状态更新失败')
    }
  }
}

async function confirmPermanentDelete() {
  const seed = deleteTarget.value
  if (!seed?.capabilities?.canPermanentlyDelete) return
  const projectId = props.projectId
  const generation = workspaceGeneration
  try {
    await seedStore.permanentlyDeleteSeed(projectId, seed.id, {
      expectedSeedRevision: seed.revision,
      expectedSelectionRevision: currentGeneration.value,
    })
    if (!isCurrentWorkspace(projectId, generation)) return
    deleteTarget.value = null
    message.success('种子已永久删除')
  } catch (error) {
    if (isCurrentWorkspace(projectId, generation)) {
      message.error(error?.message || '永久删除失败')
    }
  }
}
</script>

<template>
  <section
    v-if="routeProject.state.value === 'loading'"
    class="seeds-page seeds-page--loading"
    aria-busy="true"
  >
    <n-skeleton text width="32%" />
    <n-skeleton text :repeat="4" />
  </section>

  <section v-else-if="routeProject.state.value === 'missing'" class="seeds-page">
    <n-result
      status="404"
      title="项目不存在或已被删除"
      description="系统不会打开另一个项目作为替代。"
    />
  </section>

  <section v-else-if="routeProject.state.value === 'error'" class="seeds-page">
    <n-result
      status="error"
      title="项目暂时无法加载"
      :description="routeProject.error.value?.message || '请稍后重试'"
    >
      <template #footer>
        <n-button type="primary" @click="routeProject.reload">重试</n-button>
      </template>
    </n-result>
  </section>

  <section v-else class="seeds-page">
    <header class="seeds-page__masthead">
      <div>
        <p>PROJECT SEEDS / EDITORIAL DESK</p>
        <h1>{{ routeProject.project.value?.title || '创作种子' }}</h1>
        <span>先收集证据与灵感，再由作者把想法写成候选。多个候选中始终只有一个当前选定。</span>
      </div>
      <div class="seeds-page__next">
        <small>当前下一步</small>
        <strong>{{ seedStore.nextAction.label }}</strong>
        <span v-if="seedStore.activeSelection">选定代次 {{ currentGeneration }}</span>
      </div>
    </header>

    <n-alert v-if="readOnly" type="warning" :bordered="false" class="seeds-page__notice">
      <strong>已归档 · 只读</strong>
      恢复项目后才能继续刷新证据、讨论灵感或修改种子。
    </n-alert>
    <n-alert v-if="loadError" type="error" class="seeds-page__notice">
      {{ loadError }}
      <template #action>
        <n-button text @click="loadWorkspace">重新加载</n-button>
      </template>
    </n-alert>

    <nav class="seed-sections" aria-label="创作种子工作区">
      <button
        v-for="section in sections"
        :key="section.key"
        type="button"
        :class="{ 'seed-sections__active': activeSection === section.key }"
        :aria-current="activeSection === section.key ? 'page' : undefined"
        @click="activeSection = section.key"
      >
        <span>{{ section.index }}</span>
        <strong>{{ section.label }}</strong>
      </button>
    </nav>

    <section class="seeds-page__sheet">
      <market-evidence-panel
        v-show="activeSection === 'evidence'"
        :project-id="props.projectId"
        :read-only="readOnly"
        :command-key="commandKey"
      />

      <section
        v-show="activeSection === 'inspiration'"
        class="inspiration-desk"
        aria-labelledby="inspiration-heading"
      >
        <header>
          <div>
            <p>WORKING CONVERSATION / NOT A SEED</p>
            <h2 id="inspiration-heading">灵感讨论</h2>
            <span>对话只存在于当前页面。AI 的建议不会自动落库，也不会自动改动当前种子。</span>
          </div>
          <n-tag :type="inspirationReady ? 'success' : 'warning'">
            {{ inspirationReady ? '证据已就绪' : '分析尚未就绪' }}
          </n-tag>
        </header>

        <n-alert v-if="!inspirationReady" type="warning" :bordered="false">
          先在“市场证据”中取得快照并完成分析；系统不会用虚构市场结论回答。你仍可直接新建手动种子。
        </n-alert>

        <div class="transcript" aria-live="polite">
          <div v-if="!transcript.length" class="transcript__empty">
            <strong>这里是一张临时讨论纸。</strong>
            <p>可以问情节切口、人物矛盾或差异化方向。满意后仍需由你编辑九个正式字段。</p>
          </div>
          <article
            v-for="(turn, index) in transcript"
            :key="`${turn.role}-${index}`"
            :class="`transcript__${turn.role}`"
          >
            <strong>{{ turn.role === 'user' ? '作者' : '灵感助手' }}</strong>
            <p>{{ turn.content }}</p>
          </article>
        </div>

        <div class="inspiration-composer">
          <n-input
            v-model:value="chatInput"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 7 }"
            maxlength="4000"
            show-count
            placeholder="例如：怎样让主角使用永乐大典知识时，每一次获利都带来新的政治代价？"
            :disabled="readOnly || !inspirationReady || seedStore.inspirationBusy"
          />
          <div>
            <span>发送后只得到一条临时建议。</span>
            <n-button
              type="primary"
              :loading="seedStore.inspirationBusy"
              :disabled="readOnly || !inspirationReady || !chatInput.trim()"
              @click="sendInspiration"
            >
              发送讨论
            </n-button>
          </div>
        </div>

        <aside class="proposal-slip">
          <div>
            <small>UNSAVED PROPOSAL</small>
            <strong>{{ proposal ? '建议尚未保存' : '还没有可保存的建议' }}</strong>
            <p>{{ proposal?.content || 'AI 回复出现后，你可以把它带入普通九字段编辑器，再决定是否保存。' }}</p>
          </div>
          <n-button
            :disabled="readOnly || seedStore.inspirationBusy || !proposal"
            @click="saveProposal"
          >
            保存为种子
          </n-button>
        </aside>
      </section>

      <section
        v-show="activeSection === 'saved'"
        class="saved-seeds"
        aria-labelledby="saved-seeds-heading"
      >
        <header>
          <div>
            <p>SAVED CANDIDATES / ONE ACTIVE SELECTION</p>
            <h2 id="saved-seeds-heading">已存种子</h2>
            <span>确认一个候选后，它会成为项目永久基线，后续不能更换。</span>
          </div>
          <n-button
            v-if="!seedStore.activeSelection"
            type="primary"
            :disabled="readOnly || seedStore.mutationBusy"
            @click="openCreate()"
          >
            新建种子
          </n-button>
        </header>

        <n-spin :show="seedStore.loading">
          <div class="saved-seeds__board">
            <div v-if="activeCandidates.length" class="seed-grid">
              <seed-card
                v-for="seed in activeCandidates"
                :key="seed.id"
                :seed="seed"
                :read-only="readOnly"
                :busy="seedStore.mutationBusy"
                @edit="openEdit"
                @select="selectionTarget = $event"
                @archive="changeArchive($event, 'archive')"
                @permanent-delete="deleteTarget = $event"
              />
            </div>
            <n-empty
              v-else-if="!seedStore.loading"
              description="还没有候选种子。可以手动登记，也可以先讨论灵感。"
            />

            <details v-if="archivedCandidates.length" class="archived-seeds">
              <summary>已归档种子（{{ archivedCandidates.length }}）</summary>
              <div class="seed-grid">
                <seed-card
                  v-for="seed in archivedCandidates"
                  :key="seed.id"
                  :seed="seed"
                  :read-only="readOnly"
                  :busy="seedStore.mutationBusy"
                  @restore="changeArchive($event, 'restore')"
                  @permanent-delete="deleteTarget = $event"
                />
              </div>
            </details>

            <aside
              v-if="seedStore.mutationBusy"
              class="seed-operation-veil"
              role="status"
              aria-live="assertive"
            >
              <div>
                <span aria-hidden="true">种</span>
                <strong>正在提交种子操作</strong>
                <p>完成前暂不切换或重复写入；页面其他区域仍可查看。</p>
              </div>
            </aside>
          </div>
        </n-spin>

        <seed-editor
          v-if="editorOpen"
          :seed="editingSeed"
          :initial-payload="editorInitialPayload"
          :busy="seedStore.mutationBusy"
          :read-only="readOnly"
          @save="saveEditor"
          @cancel="closeEditor"
        />
      </section>
    </section>

    <n-modal
      v-if="selectionTarget"
      :show="Boolean(selectionTarget)"
      preset="card"
      class="seed-confirm-dialog"
      title="确认创作种子"
      :mask-closable="false"
      :closable="false"
      style="width: min(480px, calc(100vw - 32px));"
    >
      <p>
        确认后不可更换：《{{ selectionTarget?.payload?.title || '未命名种子' }}》将作为项目的永久基线。
      </p>
      <template #footer>
        <div class="permanent-delete-dialog__actions">
          <n-button :disabled="seedStore.mutationBusy" @click="selectionTarget = null">取消</n-button>
          <n-button
            type="primary"
            :loading="seedStore.mutationBusy"
            @click="selectSeed(selectionTarget).then(() => { selectionTarget = null }).catch(() => {})"
          >
            确认这个种子并进入创作契约
          </n-button>
        </div>
      </template>
    </n-modal>

    <n-modal
      v-if="deleteTarget"
      :show="Boolean(deleteTarget)"
      preset="card"
      class="permanent-delete-dialog"
      title="永久删除种子"
      :mask-closable="false"
      :closable="false"
      style="width: min(480px, calc(100vw - 32px));"
    >
      <p>
        《{{ deleteTarget?.payload?.title || '未命名种子' }}》删除后无法恢复。
        只有后端确认从未被引用的种子才会出现此操作。
      </p>
      <template #footer>
        <div class="permanent-delete-dialog__actions">
          <n-button :disabled="seedStore.mutationBusy" @click="deleteTarget = null">
            取消
          </n-button>
          <n-button
            type="error"
            :loading="seedStore.mutationBusy"
            @click="confirmPermanentDelete"
          >
            确认永久删除
          </n-button>
        </div>
      </template>
    </n-modal>
  </section>
</template>

<style scoped>
.seeds-page {
  min-height: 100%;
  padding: clamp(22px, 4.5vw, 58px);
  color: #302a23;
  background:
    radial-gradient(circle at 85% 2%, rgba(145, 60, 47, .05), transparent 22%),
    #f4efe4;
}
.seeds-page--loading { display: grid; align-content: start; gap: 16px; }
.seeds-page__masthead {
  display: flex;
  width: min(1180px, 100%);
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
  margin-inline: auto;
}
.seeds-page__masthead > div:first-child { max-width: 760px; }
.seeds-page__masthead p, .inspiration-desk > header p, .saved-seeds > header p {
  margin: 0 0 7px;
  color: #963f32;
  font: 700 10px Georgia, serif;
  letter-spacing: .17em;
}
h1, h2 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; }
h1 { font-size: clamp(34px, 6vw, 58px); font-weight: 600; letter-spacing: -.025em; }
.seeds-page__masthead > div:first-child > span,
.inspiration-desk > header div > span,
.saved-seeds > header div > span {
  display: block;
  margin-top: 11px;
  color: #766c60;
  font-size: 12px;
  line-height: 1.75;
}
.seeds-page__next {
  display: grid;
  min-width: 206px;
  gap: 4px;
  padding: 15px 17px;
  border: 1px solid #ccbea8;
  border-radius: 8px;
  background: rgba(255, 252, 245, .72);
}
.seeds-page__next small { color: #957653; font-size: 12px; letter-spacing: .08em; }
.seeds-page__next strong { font-family: Georgia, 'Noto Serif SC', serif; font-size: 16px; }
.seeds-page__next span { color: #817568; font-size: 12px; }
.seeds-page__notice { width: min(1180px, 100%); margin: 18px auto 0; }
.seeds-page__notice strong { margin-right: 10px; }
.seed-sections {
  display: grid;
  width: min(1180px, 100%);
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 30px auto 0;
  border: 1px solid #d2c4ae;
  border-bottom: 0;
  border-radius: 12px 12px 0 0;
  overflow: hidden;
}
.seed-sections button {
  display: flex;
  min-height: 58px;
  align-items: center;
  gap: 11px;
  padding: 0 20px;
  border: 0;
  border-right: 1px solid #ded2bf;
  color: #75695b;
  text-align: left;
  background: #eee5d7;
  cursor: pointer;
}
.seed-sections button:last-child { border-right: 0; }
.seed-sections button span { color: #ae9675; font: 700 10px Georgia, serif; }
.seed-sections button strong { font-family: 'Noto Serif SC', serif; font-size: 13px; }
.seed-sections__active { color: #8d382e !important; background: #fffdf8 !important; box-shadow: inset 0 3px 0 #963f32; }
.seeds-page__sheet {
  width: min(1180px, 100%);
  min-height: 520px;
  margin-inline: auto;
  padding: clamp(20px, 4vw, 36px);
  border: 1px solid #d2c4ae;
  border-radius: 0 0 14px 14px;
  background:
    repeating-linear-gradient(0deg, transparent 0 34px, rgba(104, 78, 48, .018) 35px),
    #fffdf8;
  box-shadow: 0 24px 64px rgba(58, 43, 27, .07);
}
.inspiration-desk > header, .saved-seeds > header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
}
.inspiration-desk h2, .saved-seeds h2 { font-size: clamp(25px, 4vw, 36px); }
.transcript {
  display: grid;
  min-height: 230px;
  max-height: 460px;
  gap: 12px;
  margin-top: 18px;
  padding: 20px;
  overflow-y: auto;
  border: 1px solid #ded1bd;
  border-radius: 9px;
  background: #f7f1e6;
}
.transcript__empty { align-self: center; color: #867a6b; text-align: center; }
.transcript__empty p { margin: 7px auto 0; max-width: 54ch; font-size: 11px; line-height: 1.7; }
.transcript article { width: min(76%, 720px); padding: 13px 15px; border-radius: 4px 12px 12px 12px; background: #fffdf8; box-shadow: 0 6px 18px rgba(68, 50, 31, .05); }
.transcript__user { justify-self: end; border-right: 3px solid #963f32; }
.transcript__assistant { justify-self: start; border-left: 3px solid #56715d; }
.transcript article strong { color: #8f3d32; font-size: 12px; }
.transcript article p { margin: 5px 0 0; color: #50483f; font-size: 14px; line-height: 1.75; white-space: pre-wrap; }
.inspiration-composer { margin-top: 14px; }
.inspiration-composer > div { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 8px; }
.inspiration-composer span { color: #8a7e6e; font-size: 12px; }
.proposal-slip { display: flex; align-items: center; justify-content: space-between; gap: 22px; margin-top: 20px; padding: 18px 20px; border: 1px dashed #bba98d; background: rgba(244, 235, 218, .64); }
.proposal-slip div { display: grid; gap: 5px; }
.proposal-slip small { color: #977550; font: 700 9px Georgia, serif; letter-spacing: .15em; }
.proposal-slip strong { font-family: 'Noto Serif SC', serif; font-size: 14px; }
.proposal-slip p { max-width: 72ch; margin: 0; color: #74695b; font-size: 13px; line-height: 1.7; }
.saved-seeds__board { position: relative; min-height: 220px; }
.seed-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.archived-seeds { margin-top: 22px; padding-top: 16px; border-top: 1px solid #ded1bd; }
.archived-seeds summary { margin-bottom: 14px; color: #75695b; font-size: 12px; cursor: pointer; }
.seed-operation-veil {
  position: absolute;
  inset: 0;
  z-index: 3;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: rgba(255, 253, 248, .66);
  backdrop-filter: blur(1px);
}
.seed-operation-veil > div { display: grid; grid-template-columns: auto 1fr; gap: 3px 11px; padding: 15px 18px; border: 1px solid #cdbda5; border-radius: 8px; background: #fffdf8; box-shadow: 0 15px 38px rgba(54, 40, 25, .14); }
.seed-operation-veil span { display: grid; width: 34px; height: 34px; grid-row: span 2; place-items: center; border: 1px solid #963f32; color: #963f32; font-family: 'Noto Serif SC', serif; }
.seed-operation-veil strong { font-size: 12px; }
.seed-operation-veil p { margin: 0; color: #7f7364; font-size: 12px; }
.permanent-delete-dialog__actions { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 820px) {
  .seeds-page__masthead { align-items: flex-start; flex-direction: column; }
  .seeds-page__next { width: 100%; }
  .seed-grid { grid-template-columns: 1fr; }
}
@media (max-width: 590px) {
  .seeds-page { padding-inline: 12px; }
  .seed-sections { grid-template-columns: 1fr; }
  .seed-sections button { border-right: 0; border-bottom: 1px solid #ded2bf; }
  .seed-sections button:last-child { border-bottom: 0; }
  .inspiration-desk > header, .saved-seeds > header { align-items: flex-start; flex-direction: column; }
  .transcript article { width: 94%; }
  .proposal-slip { align-items: flex-start; flex-direction: column; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; }
}
</style>
