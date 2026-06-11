<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSpace,
  NTag,
  useDialog
} from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { auditIssueTypeLabel, auditSeverityLabel } from '@/utils/auditLabels'
import { useVolumeStore, VOLUME_STATUS_OPTIONS } from '@/stores/volumeStore'
import { useMemoryStore } from '@/stores/memoryStore'
import { useCorrectionTaskStore } from '@/stores/correctionTaskStore'
import RollingPlanningPanel from './RollingPlanningPanel.vue'

const props = defineProps({
  project: { type: Object, required: true },
  chapters: { type: Array, default: () => [] },
  activeVolumeId: { type: String, default: '' }
})

const emit = defineEmits(['select-volume'])

const volumeStore = useVolumeStore()
const memoryStore = useMemoryStore()
const correctionTaskStore = useCorrectionTaskStore()
const message = useAppMessage()
const dialog = useDialog()

const showEditor = ref(false)
const showAuditModal = ref(false)
const showSummaryModal = ref(false)
const saving = ref(false)
const auditingId = ref('')
const summarizingId = ref('')
const initializingSkeleton = ref(false)
const activeAuditVolume = ref(null)
const activeAuditReport = ref(null)
const activeSummaryVolume = ref(null)
const activeSummaryReport = ref(null)
const formValue = ref(emptyVolume())

const statusLabelMap = Object.fromEntries(VOLUME_STATUS_OPTIONS.map(item => [item.value, item.label]))
const statusTypeMap = {
  planned: 'default',
  active: 'info',
  completed: 'success',
  paused: 'warning'
}

const totalVolumeWords = computed(() =>
  volumeStore.volumes.reduce((sum, volume) => sum + Number(volume.targetWords || 0), 0)
)

onMounted(() => loadData())

watch(() => props.project.id, () => loadData())

async function loadData() {
  if (props.project?.id) {
    await volumeStore.loadVolumes(props.project.id)
  }
}

function emptyVolume() {
  return {
    id: '',
    volumeNum: 1,
    title: '',
    startChapter: 1,
    endChapter: 1,
    targetWords: 0,
    coreGoal: '',
    mainConflict: '',
    keyCharacters: '',
    summary: '',
    foreshadowingPlan: '',
    unresolvedItems: '',
    handoffPoint: '',
    status: 'planned'
  }
}

function openCreate() {
  const last = volumeStore.volumes[volumeStore.volumes.length - 1]
  const nextStart = last ? Number(last.endChapter || 0) + 1 : 1
  formValue.value = {
    ...emptyVolume(),
    volumeNum: (last?.volumeNum || volumeStore.volumes.length || 0) + 1,
    title: `第 ${(last?.volumeNum || volumeStore.volumes.length || 0) + 1} 卷`,
    startChapter: nextStart,
    endChapter: Math.min(nextStart + 59, props.project.targetChapters || nextStart + 59)
  }
  showEditor.value = true
}

function openEdit(volume) {
  formValue.value = {
    ...volume,
    keyCharacters: (volume.keyCharacters || []).join('、'),
    foreshadowingPlan: (volume.foreshadowingPlan || []).join('\n'),
    unresolvedItems: (volume.unresolvedItems || []).join('\n')
  }
  showEditor.value = true
}

async function handleSave() {
  if (!formValue.value.title.trim()) {
    message.warning('请输入分卷标题')
    return
  }
  if (formValue.value.endChapter < formValue.value.startChapter) {
    message.warning('结束章节不能小于起始章节')
    return
  }

  saving.value = true
  try {
    await volumeStore.saveVolume(props.project.id, formValue.value)
    message.success('分卷规划已保存')
    showEditor.value = false
  } catch (e) {
    message.error('保存分卷失败：' + e.message)
  } finally {
    saving.value = false
  }
}

async function ensureNoExistingVolumes() {
  if (volumeStore.volumes.length > 0) {
    message.warning('当前项目已经有分卷规划。如需重新规划，请先手动删除旧分卷。')
    return false
  }
  return true
}

async function handleGenerateVolumePlan() {
  if (!await ensureNoExistingVolumes()) return
  try {
    const created = await volumeStore.generateVolumePlanByAI(props.project)
    message.success(`AI 已生成 ${created.length} 个分卷规划`)
  } catch (e) {
    dialog.warning({
      title: 'AI 分卷规划失败',
      content: `没有创建空分卷。你可以重试 AI 规划，或使用“仅创建空分卷骨架”先建立章节范围。错误：${e.message}`,
      positiveText: '知道了'
    })
  }
}

async function handleCreateEmptySkeleton() {
  if (!await ensureNoExistingVolumes()) return
  initializingSkeleton.value = true
  try {
    const created = await volumeStore.initializeEmptyByProject(props.project)
    message.success(`已创建 ${created.length} 个空分卷骨架`)
  } catch (e) {
    message.error('创建空分卷骨架失败：' + e.message)
  } finally {
    initializingSkeleton.value = false
  }
}

async function handleAudit(volume) {
  auditingId.value = volume.id
  try {
    const report = await memoryStore.auditVolume(props.project.id, volume, props.project)
    const saved = await volumeStore.saveAudit(props.project.id, volume.id, report)
    activeAuditVolume.value = saved
    activeAuditReport.value = saved.auditReport || report
    showAuditModal.value = true
    message.success('分卷审稿已生成')
  } catch (e) {
    message.error('分卷审稿失败：' + e.message)
  } finally {
    auditingId.value = ''
  }
}

function handleViewAudit(volume) {
  if (!volume.auditReport) {
    message.warning('当前分卷还没有审稿报告')
    return
  }
  activeAuditVolume.value = volume
  activeAuditReport.value = volume.auditReport
  showAuditModal.value = true
}

async function handleCreateCorrectionTasksFromAudit() {
  if (!activeAuditReport.value || !activeAuditVolume.value) return
  const payloads = correctionTaskStore.buildTasksFromVolumeAudit(activeAuditVolume.value, activeAuditReport.value)
  if (!payloads.length) {
    message.warning('当前分卷审稿报告没有可转化的问题项')
    return
  }
  try {
    const created = await correctionTaskStore.bulkCreate(props.project.id, payloads)
    message.success(`已生成 ${created.length} 条分卷纠偏任务`)
  } catch (e) {
    message.error('生成纠偏任务失败：' + e.message)
  }
}

async function handleSummary(volume) {
  summarizingId.value = volume.id
  try {
    const report = await memoryStore.summarizeVolume(props.project.id, volume, props.project)
    const saved = await volumeStore.saveStageSummary(props.project.id, volume.id, report)
    activeSummaryVolume.value = saved
    activeSummaryReport.value = saved.stageSummaryReport || report
    showSummaryModal.value = true
    message.success('分卷阶段总结已生成')
  } catch (e) {
    message.error('分卷阶段总结失败：' + e.message)
  } finally {
    summarizingId.value = ''
  }
}

function handleViewSummary(volume) {
  if (!volume.stageSummaryReport) {
    message.warning('当前分卷还没有阶段总结')
    return
  }
  activeSummaryVolume.value = volume
  activeSummaryReport.value = volume.stageSummaryReport
  showSummaryModal.value = true
}

function handleDelete(volume) {
  const overlap = props.chapters.filter(ch =>
    ch.chapterNum >= volume.startChapter && ch.chapterNum <= volume.endChapter
  )
  if (overlap.length) {
    dialog.warning({
      title: '分卷内已有章节',
      content: `当前分卷范围内已有 ${overlap.length} 个章节，不能直接删除分卷。请先移动或删除这些章节，再删除分卷。`,
      positiveText: '知道了'
    })
    return
  }
  dialog.warning({
    title: '确认删除分卷',
    content: `确定删除「${volume.title}」吗？`,
    positiveText: '确认删除',
    negativeText: '取消',
    maskClosable: false,
    closeOnEsc: false,
    onPositiveClick: async () => {
      try {
        await volumeStore.deleteVolume(props.project.id, volume.id)
        message.success('分卷已删除')
      } catch (e) {
        message.error('删除分卷失败：' + e.message)
      }
    }
  })
}

function chapterCountIn(volume) {
  return props.chapters.filter(ch =>
    ch.chapterNum >= volume.startChapter && ch.chapterNum <= volume.endChapter
  ).length
}

function selectVolume(volume) {
  emit('select-volume', volume.id)
}

function formatSummaryItem(item) {
  if (typeof item === 'string') return item
  if (!item || typeof item !== 'object') return String(item || '')
  return [
    item.name || item.title || item.label || '',
    item.state ? `状态：${item.state}` : '',
    item.change ? `变化：${item.change}` : '',
    item.note ? `说明：${item.note}` : '',
    item.nextUse ? `接力：${item.nextUse}` : '',
    item.evidence ? `依据：${item.evidence}` : ''
  ].filter(Boolean).join('；')
}

function summaryList(report, key) {
  const value = report?.[key]
  return Array.isArray(value) ? value.filter(Boolean) : []
}
</script>

<template>
  <section class="volume-planner">
    <RollingPlanningPanel :project="project" :chapters="chapters" />

    <div class="volume-toolbar">
      <div>
        <h3>分卷规划</h3>
        <p>把长篇拆成可管理的阶段，后续章节生成、阶段总结和伏笔回收都以此为锚。</p>
      </div>
      <n-space>
        <n-button size="small" type="primary" :loading="volumeStore.generating" @click="handleGenerateVolumePlan">
          AI 生成分卷规划
        </n-button>
        <n-button size="small" secondary :loading="initializingSkeleton" @click="handleCreateEmptySkeleton">
          仅创建空分卷骨架
        </n-button>
        <n-button size="small" type="primary" @click="openCreate">新增分卷</n-button>
      </n-space>
    </div>

    <n-alert v-if="volumeStore.volumes.length" type="info" :bordered="false" class="mb-3">
      已规划 {{ volumeStore.volumes.length }} 卷，目标合计 {{ (totalVolumeWords / 10000).toFixed(1) }} 万字。分卷是创作阶段锚点，不会直接改动章节正文。
    </n-alert>

    <n-empty v-if="!volumeStore.volumes.length && !volumeStore.loading" description="暂无分卷规划">
      <template #action>
        <n-space>
          <n-button type="primary" :loading="volumeStore.generating" @click="handleGenerateVolumePlan">
            AI 生成分卷规划
          </n-button>
          <n-button secondary :loading="initializingSkeleton" @click="handleCreateEmptySkeleton">
            仅创建空分卷骨架
          </n-button>
        </n-space>
      </template>
    </n-empty>

    <div v-else class="volume-grid">
      <n-card
        v-for="volume in volumeStore.volumes"
        :key="volume.id"
        size="small"
        :class="['volume-card', { 'is-active': volume.id === activeVolumeId }]"
        @click="selectVolume(volume)"
      >
        <div class="volume-card-head">
          <div>
            <div class="volume-title">{{ volume.title || `第 ${volume.volumeNum} 卷` }}</div>
            <div class="volume-range">
              第 {{ volume.startChapter }}-{{ volume.endChapter }} 章 · {{ (volume.targetWords / 10000).toFixed(1) }} 万字
            </div>
          </div>
          <n-tag size="small" :type="statusTypeMap[volume.status] || 'default'" :bordered="false">
            {{ statusLabelMap[volume.status] || volume.status }}
          </n-tag>
          <n-tag v-if="volume.id === activeVolumeId" size="small" type="success" :bordered="false">
            当前卷
          </n-tag>
        </div>

        <div class="volume-meta">
          <span>已建章节 {{ chapterCountIn(volume) }} 个</span>
          <span>序号 {{ volume.volumeNum }}</span>
        </div>

        <div v-if="volume.auditUpdatedAt" class="volume-audit-tip">
          最近审稿：{{ new Date(volume.auditUpdatedAt).toLocaleString('zh-CN') }}
        </div>

        <div v-if="volume.summaryUpdatedAt" class="volume-summary-tip">
          最近总结：{{ new Date(volume.summaryUpdatedAt).toLocaleString('zh-CN') }}
        </div>

        <p v-if="volume.coreGoal" class="volume-text">
          <strong>阶段目标：</strong>{{ volume.coreGoal }}
        </p>
        <p v-if="volume.mainConflict" class="volume-text">
          <strong>核心冲突：</strong>{{ volume.mainConflict }}
        </p>
        <p v-if="volume.summary" class="volume-text">
          <strong>摘要：</strong>{{ volume.summary }}
        </p>
        <p v-if="volume.foreshadowingPlan?.length" class="volume-text">
          <strong>伏笔计划：</strong>{{ volume.foreshadowingPlan.join('；') }}
        </p>
        <p v-if="volume.unresolvedItems?.length" class="volume-text">
          <strong>暂不解决：</strong>{{ volume.unresolvedItems.join('；') }}
        </p>
        <p v-if="volume.handoffPoint" class="volume-text">
          <strong>卷尾交接：</strong>{{ volume.handoffPoint }}
        </p>

        <div v-if="volume.keyCharacters?.length" class="volume-tags">
          <n-tag v-for="name in volume.keyCharacters" :key="name" size="tiny">
            {{ name }}
          </n-tag>
        </div>

        <template #footer>
          <n-space justify="end">
            <n-button size="tiny" :loading="auditingId === volume.id" @click.stop="handleAudit(volume)">
              {{ volume.auditReport ? '重新审稿' : '分卷审稿' }}
            </n-button>
            <n-button size="tiny" :loading="summarizingId === volume.id" @click.stop="handleSummary(volume)">
              {{ volume.stageSummaryReport ? '更新总结' : '生成总结' }}
            </n-button>
            <n-button
              v-if="volume.auditReport"
              size="tiny"
              secondary
              @click.stop="handleViewAudit(volume)"
            >
              查看报告
            </n-button>
            <n-button
              v-if="volume.stageSummaryReport"
              size="tiny"
              secondary
              @click.stop="handleViewSummary(volume)"
            >
              查看总结
            </n-button>
            <n-button size="tiny" @click.stop="openEdit(volume)">编辑</n-button>
            <n-button size="tiny" type="error" secondary @click.stop="handleDelete(volume)">删除</n-button>
          </n-space>
        </template>
      </n-card>
    </div>

    <n-modal v-model:show="showEditor" title="编辑分卷规划" preset="card" style="width: 680px">
      <n-form :model="formValue" label-placement="left" label-width="96px">
        <div class="form-grid">
          <n-form-item label="卷序号">
            <n-input-number v-model:value="formValue.volumeNum" :min="1" :step="1" />
          </n-form-item>
          <n-form-item label="状态">
            <n-select v-model:value="formValue.status" :options="VOLUME_STATUS_OPTIONS" />
          </n-form-item>
        </div>
        <n-form-item label="卷标题" required>
          <n-input v-model:value="formValue.title" placeholder="如：第一卷 山门初燃" />
        </n-form-item>
        <div class="form-grid">
          <n-form-item label="起始章节">
            <n-input-number v-model:value="formValue.startChapter" :min="1" :step="1" />
          </n-form-item>
          <n-form-item label="结束章节">
            <n-input-number v-model:value="formValue.endChapter" :min="1" :step="1" />
          </n-form-item>
        </div>
        <n-form-item label="目标字数">
          <n-input-number v-model:value="formValue.targetWords" :min="0" :step="10000" />
        </n-form-item>
        <n-form-item label="阶段目标">
          <n-input v-model:value="formValue.coreGoal" type="textarea" rows="2" placeholder="这一卷主角必须完成什么变化或抵达什么位置" />
        </n-form-item>
        <n-form-item label="核心冲突">
          <n-input v-model:value="formValue.mainConflict" type="textarea" rows="2" placeholder="这一卷最重要的外部冲突、内心冲突或阵营冲突" />
        </n-form-item>
        <n-form-item label="关键人物">
          <n-input v-model:value="formValue.keyCharacters" placeholder="用逗号、顿号或换行分隔" />
        </n-form-item>
        <n-form-item label="阶段摘要">
          <n-input v-model:value="formValue.summary" type="textarea" rows="3" placeholder="这一卷的大致剧情走向、高潮和收束点" />
        </n-form-item>
        <n-form-item label="伏笔计划">
          <n-input v-model:value="formValue.foreshadowingPlan" type="textarea" rows="3" placeholder="每行一条：本卷要埋下或回收的伏笔" />
        </n-form-item>
        <n-form-item label="暂不解决">
          <n-input v-model:value="formValue.unresolvedItems" type="textarea" rows="2" placeholder="每行一条：本卷暂时不解决、留给后续卷的内容" />
        </n-form-item>
        <n-form-item label="卷尾交接">
          <n-input v-model:value="formValue.handoffPoint" type="textarea" rows="2" placeholder="本卷结束时交给下一卷的状态、压力或未完成选择" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEditor = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="handleSave">保存分卷</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showSummaryModal" preset="card" style="width: 760px" title="分卷阶段总结">
      <div v-if="activeSummaryReport" class="summary-report">
        <div class="audit-header">
          <div>
            <h4>{{ activeSummaryVolume?.title || '当前分卷' }}</h4>
            <p>
              第 {{ activeSummaryVolume?.startChapter }}-{{ activeSummaryVolume?.endChapter }} 章
              <span v-if="activeSummaryVolume?.summaryUpdatedAt">
                · {{ new Date(activeSummaryVolume.summaryUpdatedAt).toLocaleString('zh-CN') }}
              </span>
            </p>
          </div>
          <n-tag type="success" :bordered="false">已沉淀</n-tag>
        </div>

        <n-alert type="success" :bordered="false" class="mb-3">
          {{ activeSummaryReport.compactSummary || activeSummaryReport.stageSummary || '暂无总结' }}
        </n-alert>

        <div class="audit-section" v-if="activeSummaryReport.stageSummary">
          <h5>阶段总览</h5>
          <p>{{ activeSummaryReport.stageSummary }}</p>
        </div>

        <div
          v-for="section in [
            ['completedBeats', '已完成节点'],
            ['openQuestions', '未解问题'],
            ['characterChanges', '人物变化'],
            ['settingChanges', '设定变化'],
            ['foreshadowingState', '伏笔状态'],
            ['handoffToNext', '下一卷接力'],
            ['continuityNotes', '连续性约束'],
            ['nextVolumeSeeds', '下一卷种子']
          ]"
          :key="section[0]"
          class="audit-section"
          v-show="summaryList(activeSummaryReport, section[0]).length"
        >
          <h5>{{ section[1] }}</h5>
          <ul class="audit-list">
            <li v-for="(item, index) in summaryList(activeSummaryReport, section[0])" :key="`${section[0]}-${index}`">
              {{ formatSummaryItem(item) }}
            </li>
          </ul>
        </div>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showSummaryModal = false">关闭</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showAuditModal" preset="card" style="width: 760px" title="分卷审稿报告">
      <div v-if="activeAuditReport" class="audit-report">
        <div class="audit-header">
          <div>
            <h4>{{ activeAuditVolume?.title || '当前分卷' }}</h4>
            <p>
              第 {{ activeAuditVolume?.startChapter }}-{{ activeAuditVolume?.endChapter }} 章
              <span v-if="activeAuditVolume?.auditUpdatedAt">
                · {{ new Date(activeAuditVolume.auditUpdatedAt).toLocaleString('zh-CN') }}
              </span>
            </p>
          </div>
          <n-tag :type="activeAuditReport.suitableToContinue ? 'success' : 'warning'" :bordered="false">
            {{ activeAuditReport.suitableToContinue ? '可继续推进' : '建议先调整' }}
          </n-tag>
        </div>

        <n-alert type="info" :bordered="false" class="mb-3">
          {{ activeAuditReport.overallAssessment || '暂无总评' }}
        </n-alert>

        <div class="audit-section" v-if="activeAuditReport.stageSummary">
          <h5>阶段判断</h5>
          <p>{{ activeAuditReport.stageSummary }}</p>
        </div>

        <div class="audit-section" v-if="activeAuditReport.strengths?.length">
          <h5>当前优点</h5>
          <ul class="audit-list">
            <li v-for="item in activeAuditReport.strengths" :key="item">{{ item }}</li>
          </ul>
        </div>

        <div class="audit-section" v-if="activeAuditReport.issues?.length">
          <h5>主要问题</h5>
          <div v-for="(issue, index) in activeAuditReport.issues" :key="`${issue.type}-${index}`" class="issue-card">
            <div class="issue-head">
              <n-tag size="tiny" :type="issue.severity === 'critical' ? 'error' : issue.severity === 'major' ? 'warning' : 'default'" :bordered="false">
                {{ auditSeverityLabel(issue.severity) }}
              </n-tag>
              <span class="issue-type">{{ auditIssueTypeLabel(issue.type) }}</span>
              <span v-if="issue.chapterRefs?.length" class="issue-chapters">
                章节：{{ issue.chapterRefs.join('、') }}
              </span>
            </div>
            <p><strong>问题：</strong>{{ issue.description }}</p>
            <p v-if="issue.impact"><strong>影响：</strong>{{ issue.impact }}</p>
            <p v-if="issue.suggestion"><strong>建议：</strong>{{ issue.suggestion }}</p>
          </div>
        </div>

        <div class="audit-section" v-if="activeAuditReport.characterArcReview">
          <h5>人物弧光</h5>
          <p>{{ activeAuditReport.characterArcReview }}</p>
        </div>

        <div class="audit-section" v-if="activeAuditReport.settingConsistency">
          <h5>设定一致性</h5>
          <p>{{ activeAuditReport.settingConsistency }}</p>
        </div>

        <div class="audit-section" v-if="activeAuditReport.foreshadowingReview">
          <h5>伏笔状态</h5>
          <p>{{ activeAuditReport.foreshadowingReview }}</p>
        </div>

        <div class="audit-section" v-if="activeAuditReport.pacingReview">
          <h5>节奏判断</h5>
          <p>{{ activeAuditReport.pacingReview }}</p>
        </div>

        <div class="audit-section" v-if="activeAuditReport.nextActionPlan?.length">
          <h5>下一步建议</h5>
          <ul class="audit-list">
            <li v-for="item in activeAuditReport.nextActionPlan" :key="item">{{ item }}</li>
          </ul>
        </div>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button
            v-if="activeAuditReport?.issues?.length"
            type="primary"
            secondary
            @click="handleCreateCorrectionTasksFromAudit"
          >
            生成纠偏任务
          </n-button>
          <n-button @click="showAuditModal = false">关闭</n-button>
        </n-space>
      </template>
    </n-modal>
  </section>
</template>

<style scoped>
.volume-planner {
  margin-bottom: 18px;
}

.volume-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.volume-toolbar h3 {
  margin: 0;
  color: #1f2937;
  font-size: 18px;
  font-weight: 700;
}

.volume-toolbar p {
  margin: 4px 0 0;
  color: #8a94a6;
  font-size: 13px;
  line-height: 1.6;
}

.volume-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}

.volume-card {
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.volume-card.is-active {
  border-color: #18a058;
  box-shadow: 0 0 0 1px rgba(24, 160, 88, 0.22);
}

.volume-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.volume-title {
  color: #1f2937;
  font-size: 16px;
  font-weight: 700;
}

.volume-range,
.volume-meta {
  color: #8a94a6;
  font-size: 12px;
}

.volume-meta {
  display: flex;
  gap: 12px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #edf0f5;
}

.volume-audit-tip {
  margin-top: 8px;
  color: #10b981;
  font-size: 12px;
}

.volume-summary-tip {
  margin-top: 4px;
  color: #2563eb;
  font-size: 12px;
}

.volume-text {
  margin: 10px 0 0;
  color: #4b5563;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.volume-text strong {
  color: #374151;
}

.volume-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.audit-report {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.summary-report {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.audit-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.audit-header h4 {
  margin: 0;
  color: #1f2937;
  font-size: 18px;
  font-weight: 700;
}

.audit-header p {
  margin: 4px 0 0;
  color: #8a94a6;
  font-size: 13px;
}

.audit-section h5 {
  margin: 0 0 8px;
  color: #374151;
  font-size: 14px;
  font-weight: 700;
}

.audit-section p {
  margin: 0;
  color: #4b5563;
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.audit-list {
  margin: 0;
  padding-left: 18px;
  color: #4b5563;
  font-size: 13px;
  line-height: 1.7;
}

.issue-card {
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fafafa;
}

.issue-card + .issue-card {
  margin-top: 8px;
}

.issue-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.issue-type,
.issue-chapters {
  color: #8a94a6;
  font-size: 12px;
}

@media (max-width: 760px) {
  .volume-toolbar,
  .form-grid,
  .audit-header {
    flex-direction: column;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
