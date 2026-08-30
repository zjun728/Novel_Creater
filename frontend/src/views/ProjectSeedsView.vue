<script setup>
import { computed, onServerPrefetch, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NModal, NResult, NSkeleton, NSpin } from 'naive-ui'

import SeedCard from '@/components/seeds/SeedCard.vue'
import SeedEditor from '@/components/seeds/SeedEditor.vue'
import { useAppMessage } from '@/composables/useAppMessage'
import { useRouteProject } from '@/composables/useRouteProject'
import { useSeedStore } from '@/stores/seedStore'

const props = defineProps({ projectId: { type: String, required: true } })
const routeProject = useRouteProject()
const seedStore = useSeedStore()
const message = useAppMessage()
const loadError = ref('')
const editorOpen = ref(false)
const editingSeed = ref(null)
const deleteTarget = ref(null)
const selectionTarget = ref(null)
let workspaceProjectId = ''
let workspaceGeneration = 0

const readOnly = computed(() => routeProject.state.value === 'archived'
  || routeProject.project.value?.archivedAt != null)
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
  loadError.value = ''
  editorOpen.value = false
  editingSeed.value = null
  deleteTarget.value = null
  selectionTarget.value = null
  seedStore.activateProject(projectId)
}

function isCurrentWorkspace(projectId, generation) {
  return workspaceProjectId === String(projectId) && workspaceGeneration === generation
}

async function loadWorkspace(projectId = props.projectId) {
  const generation = workspaceGeneration
  if (isCurrentWorkspace(projectId, generation)) loadError.value = ''
  try { await seedStore.refresh(projectId) } catch (failure) {
    if (isCurrentWorkspace(projectId, generation)) loadError.value = failure?.message || '项目种子加载失败'
  }
}

watch(() => [props.projectId, routeProject.state.value], ([projectId, state]) => {
  if (!projectId) return
  if (workspaceProjectId !== String(projectId)) resetProjectWorkspace(projectId)
  if (['active', 'archived'].includes(state)) void loadWorkspace(projectId)
}, { immediate: true })
onServerPrefetch(() => loadWorkspace(props.projectId))

function openCreate() {
  if (readOnly.value || seedStore.activeSelection || seedStore.mutationBusy) return
  editingSeed.value = null
  editorOpen.value = true
}

function openEdit(seed) {
  if (readOnly.value || !seed.capabilities?.canEdit) return
  editingSeed.value = seed
  editorOpen.value = true
}

function closeEditor() {
  editorOpen.value = false
  editingSeed.value = null
}

async function saveEditor(result) {
  if (result.error) return message.warning(result.error)
  const projectId = props.projectId
  const generation = workspaceGeneration
  const editTarget = editingSeed.value
  try {
    if (editTarget) {
      await seedStore.updateSeed(projectId, editTarget.id, {
        payload: result.payload,
        expectedSeedRevision: editTarget.revision,
        expectedSelectionRevision: currentGeneration.value,
      })
    } else {
      await seedStore.createSeed(projectId, result.payload, { idempotencyKey: commandKey() })
    }
    if (!isCurrentWorkspace(projectId, generation)) return
    message.success(editTarget ? '种子修订已保存' : '候选种子已保存')
    closeEditor()
  } catch (failure) {
    if (isCurrentWorkspace(projectId, generation)) message.error(failure?.message || '种子保存失败')
  }
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
    if (isCurrentWorkspace(projectId, generation)) message.success(`已确认《${seed.payload?.title || '未命名种子'}》`)
  } catch (failure) {
    if (isCurrentWorkspace(projectId, generation)) message.error(failure?.message || '种子确认失败')
  }
}

async function changeArchive(seed, action) {
  if (readOnly.value) return
  const projectId = props.projectId
  const generation = workspaceGeneration
  const data = { expectedSeedRevision: seed.revision, expectedSelectionRevision: currentGeneration.value }
  try {
    if (action === 'archive') await seedStore.archiveSeed(projectId, seed.id, data)
    else await seedStore.restoreSeed(projectId, seed.id, data)
    if (isCurrentWorkspace(projectId, generation)) message.success(action === 'archive' ? '种子已归档' : '种子已恢复')
  } catch (failure) {
    if (isCurrentWorkspace(projectId, generation)) message.error(failure?.message || '种子状态更新失败')
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
  } catch (failure) {
    if (isCurrentWorkspace(projectId, generation)) message.error(failure?.message || '永久删除失败')
  }
}
</script>

<template>
  <section v-if="routeProject.state.value === 'loading'" class="seeds-page seeds-page--loading" aria-busy="true">
    <n-skeleton text width="32%" /><n-skeleton text :repeat="4" />
  </section>
  <section v-else-if="routeProject.state.value === 'missing'" class="seeds-page">
    <n-result status="404" title="项目不存在或已被删除" description="系统不会打开另一个项目作为替代。" />
  </section>
  <section v-else-if="routeProject.state.value === 'error'" class="seeds-page">
    <n-result status="error" title="项目暂时无法加载" :description="routeProject.error.value?.message || '请稍后重试'">
      <template #footer><n-button type="primary" @click="routeProject.reload">重试</n-button></template>
    </n-result>
  </section>

  <section v-else class="seeds-page">
    <header class="seeds-page__masthead">
      <div><p>PROJECT FOUNDATION · AUTHOR CONFIRMATION</p><h1>创作种子</h1><span>检查项目真正要写的故事。确认前可以编辑；确认后，它会成为契约、圣经和后续创作的永久基线。</span></div>
      <div class="seeds-page__status"><small>当前状态</small><strong>{{ seedStore.activeSelection ? '已确认' : '待确认' }}</strong><span>{{ seedStore.nextAction.label }}</span></div>
    </header>

    <n-alert v-if="readOnly" type="warning" :bordered="false" class="seeds-page__notice"><strong>已归档 · 只读</strong>恢复项目后才能修改或确认种子。</n-alert>
    <n-alert v-if="loadError" type="error" class="seeds-page__notice">{{ loadError }}<template #action><n-button text @click="loadWorkspace">重新加载</n-button></template></n-alert>

    <section class="seed-sheet" aria-labelledby="project-seeds-title">
      <header>
        <div><p>SAVED PROJECT SEEDS</p><h2 id="project-seeds-title">项目种子</h2><span>来自选题中心的候选在这里已经是独立副本，仍需你检查、编辑并手动确认。</span></div>
        <n-button v-if="!seedStore.activeSelection" type="primary" :disabled="readOnly || seedStore.mutationBusy" @click="openCreate">新建种子</n-button>
      </header>
      <n-spin :show="seedStore.loading">
        <div class="seed-board">
          <div v-if="activeCandidates.length" class="seed-grid">
            <SeedCard v-for="seed in activeCandidates" :key="seed.id" :seed="seed" :read-only="readOnly" :busy="seedStore.mutationBusy" @edit="openEdit" @select="selectionTarget = $event" @archive="changeArchive($event, 'archive')" @permanent-delete="deleteTarget = $event" />
          </div>
          <n-empty v-else-if="!seedStore.loading" description="还没有项目种子。可以手动新建，或从选题中心候选创建项目。" />
          <details v-if="archivedCandidates.length" class="archived-seeds">
            <summary>已归档种子（{{ archivedCandidates.length }}）</summary>
            <div class="seed-grid"><SeedCard v-for="seed in archivedCandidates" :key="seed.id" :seed="seed" :read-only="readOnly" :busy="seedStore.mutationBusy" @restore="changeArchive($event, 'restore')" @permanent-delete="deleteTarget = $event" /></div>
          </details>
          <aside v-if="seedStore.mutationBusy" class="seed-operation-veil" role="status" aria-live="assertive"><div><span aria-hidden="true">种</span><strong>正在提交种子操作</strong><p>完成前暂不重复写入。</p></div></aside>
        </div>
      </n-spin>
      <SeedEditor v-if="editorOpen" :seed="editingSeed" :busy="seedStore.mutationBusy" :read-only="readOnly" @save="saveEditor" @cancel="closeEditor" />
    </section>

    <n-modal v-if="selectionTarget" :show="Boolean(selectionTarget)" preset="card" class="seed-confirm-dialog" title="确认创作种子" :mask-closable="false" :closable="false" style="width:min(520px,calc(100vw - 32px))">
      <p>请最后核对《{{ selectionTarget?.payload?.title || '未命名种子' }}》。确认后不可更换，它将成为项目的永久创作基线。</p>
      <template #footer><div class="dialog-actions"><n-button :disabled="seedStore.mutationBusy" @click="selectionTarget = null">取消</n-button><n-button type="primary" :loading="seedStore.mutationBusy" @click="selectSeed(selectionTarget).then(() => { selectionTarget = null }).catch(() => {})">确认这个种子并进入创作契约</n-button></div></template>
    </n-modal>

    <n-modal v-if="deleteTarget" :show="Boolean(deleteTarget)" preset="card" class="permanent-delete-dialog" title="永久删除种子" :mask-closable="false" :closable="false" style="width:min(480px,calc(100vw - 32px))">
      <p>《{{ deleteTarget?.payload?.title || '未命名种子' }}》删除后无法恢复。只有后端确认从未被引用的种子才会出现此操作。</p>
      <template #footer><div class="dialog-actions"><n-button :disabled="seedStore.mutationBusy" @click="deleteTarget = null">取消</n-button><n-button type="error" :loading="seedStore.mutationBusy" @click="confirmPermanentDelete">确认永久删除</n-button></div></template>
    </n-modal>
  </section>
</template>

<style scoped>
.seeds-page{min-height:100%;padding:clamp(22px,4.5vw,58px);color:#302a23;background:radial-gradient(circle at 85% 2%,rgba(145,60,47,.05),transparent 22%),#f4efe4}.seeds-page--loading{display:grid;align-content:start;gap:16px}.seeds-page__masthead,.seed-sheet>header{display:flex;width:min(1180px,100%);align-items:flex-end;justify-content:space-between;gap:28px;margin-inline:auto}.seeds-page__masthead>div:first-child{max-width:760px}.seeds-page__masthead p,.seed-sheet>header p{margin:0 0 7px;color:#963f32;font:700 10px Georgia,serif;letter-spacing:.17em}h1,h2{margin:0;font-family:Georgia,'Noto Serif SC',serif}h1{font-size:clamp(34px,6vw,58px);font-weight:600}.seeds-page__masthead>div:first-child>span,.seed-sheet>header div>span{display:block;margin-top:11px;color:#766c60;font-size:12px;line-height:1.75}.seeds-page__status{display:grid;min-width:206px;gap:4px;padding:15px 17px;border:1px solid #ccbea8;background:rgba(255,252,245,.72)}.seeds-page__status small{color:#957653}.seeds-page__status strong{color:#8d382e;font:650 18px 'Noto Serif SC',serif}.seeds-page__status span{color:#817568;font-size:11px}.seeds-page__notice{width:min(1180px,100%);margin:18px auto 0}.seed-sheet{width:min(1180px,100%);min-height:520px;margin:28px auto 0;padding:clamp(20px,4vw,36px);border:1px solid #d2c4ae;background:repeating-linear-gradient(0deg,transparent 0 34px,rgba(104,78,48,.018) 35px),#fffdf8;box-shadow:0 24px 64px rgba(58,43,27,.07)}.seed-sheet>header{width:100%;margin-bottom:20px}.seed-sheet h2{font-size:clamp(25px,4vw,36px)}.seed-board{position:relative;min-height:220px}.seed-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.archived-seeds{margin-top:22px;padding-top:16px;border-top:1px solid #ded1bd}.archived-seeds summary{margin-bottom:14px;color:#75695b;cursor:pointer}.seed-operation-veil{position:absolute;z-index:3;inset:0;display:grid;place-items:center;background:rgba(255,253,248,.7)}.seed-operation-veil>div{display:grid;grid-template-columns:auto 1fr;gap:3px 11px;padding:15px 18px;border:1px solid #cdbda5;background:#fffdf8}.seed-operation-veil span{display:grid;width:34px;height:34px;grid-row:span 2;place-items:center;border:1px solid #963f32;color:#963f32}.seed-operation-veil p{margin:0;color:#7f7364;font-size:12px}.dialog-actions{display:flex;justify-content:flex-end;gap:8px}
@media(max-width:820px){.seeds-page__masthead{align-items:flex-start;flex-direction:column}.seeds-page__status{width:100%}.seed-grid{grid-template-columns:1fr}}
@media(max-width:590px){.seeds-page{padding-inline:12px}.seed-sheet>header{align-items:flex-start;flex-direction:column}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important}}
</style>
