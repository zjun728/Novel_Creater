<script setup>
import { computed, ref } from 'vue'
import {
  NButton,
  NCard,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSpace,
  NTag
} from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useNovelStore } from '@/stores/novelStore'
import { useSeedStore } from '@/stores/seedStore'
import { useSettingStore } from '@/stores/settingStore'
import { useVolumeStore } from '@/stores/volumeStore'

const props = defineProps({
  project: { type: Object, required: true },
  chapters: { type: Array, default: () => [] }
})

const novelStore = useNovelStore()
const seedStore = useSeedStore()
const settingStore = useSettingStore()
const volumeStore = useVolumeStore()
const message = useAppMessage()

const showEditor = ref(false)
const saving = ref(false)
const formValue = ref(createEmptyForm())

const sortedChapters = computed(() =>
  [...props.chapters].sort((a, b) => Number(a.chapterNum || 0) - Number(b.chapterNum || 0))
)

const outline = computed(() => novelStore.outline || {})
const hasOutline = computed(() =>
  Boolean(
    outline.value.farVision?.theme ||
    outline.value.currentVolume?.goal ||
    outline.value.nearChapters?.length
  )
)

const farVision = computed(() => outline.value.farVision || {})
const currentVolumePlan = computed(() => outline.value.currentVolume || {})
const nearChapters = computed(() => Array.isArray(outline.value.nearChapters) ? outline.value.nearChapters : [])

function createEmptyForm() {
  return {
    theme: '',
    finalPressure: '',
    futureVolumesText: '',
    possibleEndingsText: '',
    unresolvedBigQuestionsText: '',
    currentTitle: '',
    currentGoal: '',
    currentConflict: '',
    currentEmotionalArc: '',
    rangeStart: 1,
    rangeEnd: 60,
    mustKeepText: '',
    mustNotAdvanceYetText: '',
    nearChaptersText: ''
  }
}

function openEditor() {
  const currentVolume = currentVolumePlan.value
  const range = Array.isArray(currentVolume.expectedChapterRange)
    ? currentVolume.expectedChapterRange
    : [currentVolume.rangeStart || 1, currentVolume.rangeEnd || 60]

  formValue.value = {
    theme: farVision.value.theme || '',
    finalPressure: farVision.value.finalPressure || '',
    futureVolumesText: listToLines(farVision.value.futureVolumes),
    possibleEndingsText: listToLines(farVision.value.possibleEndings),
    unresolvedBigQuestionsText: listToLines(farVision.value.unresolvedBigQuestions),
    currentTitle: currentVolume.title || '',
    currentGoal: currentVolume.goal || '',
    currentConflict: currentVolume.mainConflict || currentVolume.conflict || '',
    currentEmotionalArc: currentVolume.emotionalArc || '',
    rangeStart: Number(range[0] || 1),
    rangeEnd: Number(range[1] || range[0] || 60),
    mustKeepText: listToLines(currentVolume.mustKeep),
    mustNotAdvanceYetText: listToLines(currentVolume.mustNotAdvanceYet),
    nearChaptersText: formatNearChapters(nearChapters.value)
  }
  showEditor.value = true
}

async function handleManualSave() {
  saving.value = true
  try {
    const payload = formToOutline(formValue.value)
    await novelStore.saveOutline(props.project.id, payload)
    message.success('规划蓝图已保存')
    showEditor.value = false
  } catch (e) {
    message.error('保存规划蓝图失败：' + e.message)
  } finally {
    saving.value = false
  }
}

async function handleGenerate() {
  if (!props.project?.id) return
  try {
    await novelStore.generateOutline(props.project.id, buildGenerateContext())
    message.success('滚动规划已生成，请在分卷规划页确认')
  } catch (e) {
    message.error('生成滚动规划失败：' + e.message)
  }
}

function buildGenerateContext() {
  const focusChapterNum = inferFocusChapterNum()
  const activeVolume = findVolumeForChapter(focusChapterNum)
  const selectedSeed = seedStore.seeds.find(seed => seed.status === 'selected') || seedStore.seeds[0] || null
  const recentChapters = sortedChapters.value
    .filter(ch => Number(ch.chapterNum || 0) < focusChapterNum)
    .slice(-12)
    .map(ch => ({
      chapterNum: ch.chapterNum,
      title: ch.title || '',
      status: ch.status,
      summary: ch.summary || '',
      wordCount: ch.wordCount || 0
    }))

  return {
    projectInfo: {
      title: props.project.title,
      genre: props.project.genre,
      description: props.project.description,
      targetWords: props.project.targetWords,
      targetChapters: props.project.targetChapters
    },
    currentChapterNum: focusChapterNum,
    seedInfo: selectedSeed,
    bibleInfo: novelStore.bible,
    currentVolumeInfo: activeVolume,
    volumeInfo: volumeStore.volumes,
    chapterInfo: recentChapters,
    settingInfo: settingStore.entities.slice(0, 80).map(entity => ({
      type: entity.entityType,
      name: entity.name,
      category: entity.category,
      summary: entity.summary,
      importance: entity.importance
    })),
    factInfo: novelStore.canonFacts.slice(0, 60),
    existingOutlineInfo: outline.value
  }
}

function inferFocusChapterNum() {
  const unfinished = sortedChapters.value.find(ch =>
    ch.status !== 'final' &&
    !ch.finalVersionId &&
    Number(ch.chapterNum || 0) > 0
  )
  if (unfinished) return Number(unfinished.chapterNum)
  const maxChapter = sortedChapters.value.reduce((max, ch) => Math.max(max, Number(ch.chapterNum || 0)), 0)
  return maxChapter ? maxChapter + 1 : 1
}

function findVolumeForChapter(chapterNum) {
  return volumeStore.volumes.find(volume =>
    chapterNum >= Number(volume.startChapter || 1) &&
    chapterNum <= Number(volume.endChapter || volume.startChapter || chapterNum)
  ) || volumeStore.volumes[0] || null
}

function formToOutline(form) {
  return {
    farVision: {
      theme: form.theme.trim(),
      finalPressure: form.finalPressure.trim(),
      futureVolumes: splitLines(form.futureVolumesText),
      possibleEndings: splitLines(form.possibleEndingsText),
      unresolvedBigQuestions: splitLines(form.unresolvedBigQuestionsText)
    },
    currentVolume: {
      title: form.currentTitle.trim(),
      goal: form.currentGoal.trim(),
      mainConflict: form.currentConflict.trim(),
      emotionalArc: form.currentEmotionalArc.trim(),
      expectedChapterRange: [Number(form.rangeStart || 1), Number(form.rangeEnd || form.rangeStart || 1)],
      mustKeep: splitLines(form.mustKeepText),
      mustNotAdvanceYet: splitLines(form.mustNotAdvanceYetText)
    },
    nearChapters: parseNearChapters(form.nearChaptersText)
  }
}

function splitLines(text) {
  return String(text || '')
    .split(/\n+/)
    .map(item => item.trim())
    .filter(Boolean)
}

function listToLines(value) {
  if (Array.isArray(value)) {
    return value.map(item => typeof item === 'string' ? item : JSON.stringify(item)).join('\n')
  }
  return value ? String(value) : ''
}

function formatNearChapters(items) {
  return (items || []).map(item => [
    item.chapterNum || '',
    item.title || '',
    item.goal || '',
    item.conflict || '',
    item.turn || '',
    item.emotionalBeat || '',
    item.handoff || ''
  ].join('｜')).join('\n')
}

function parseNearChapters(text) {
  return splitLines(text).map(line => {
    const parts = line.split(/[|｜]/).map(item => item.trim())
    const [chapterNum, title, goal, conflict, turn, emotionalBeat, handoff] = parts
    return {
      chapterNum: Number(chapterNum || 0),
      title: title || '',
      goal: goal || '',
      conflict: conflict || '',
      turn: turn || '',
      emotionalBeat: emotionalBeat || '',
      requiredFacts: [],
      doNotResolveYet: [],
      optionalSurprises: [],
      handoff: handoff || ''
    }
  }).filter(item => item.chapterNum > 0 || item.goal || item.title)
}

function renderListItem(item) {
  if (typeof item === 'string') return item
  if (!item || typeof item !== 'object') return String(item || '')
  return [
    item.volume || item.title || '',
    item.direction || item.summary || '',
    item.pressure ? `压力：${item.pressure}` : '',
    item.handoff ? `接力：${item.handoff}` : ''
  ].filter(Boolean).join('；')
}
</script>

<template>
  <n-card size="small" class="rolling-planning-panel">
    <div class="panel-header">
      <div>
        <h3>规划蓝图</h3>
        <p>
          先建立分卷规划，再创建当前卷故事块。当前章小纲从故事块阶段生成；长线蓝图只保留卷级方向，不直接进入正文生成。
        </p>
      </div>
      <n-space>
        <n-button size="small" :loading="novelStore.outlineGenerating" @click="handleGenerate">
          AI 更新规划
        </n-button>
        <n-button size="small" type="primary" secondary @click="openEditor">
          编辑规划
        </n-button>
      </n-space>
    </div>

    <n-empty v-if="!hasOutline" description="暂无滚动规划">
      <template #extra>
        先建立分卷规划，再创建当前卷故事块。这里仅保留卷级蓝图和方向参考，不作为章节生成主入口。
      </template>
    </n-empty>

    <div v-else class="planning-grid">
      <section class="planning-block planning-block-wide">
        <div class="block-title">
          <span>远景粗纲 / 长线蓝图</span>
          <n-tag size="tiny" type="warning" :bordered="false">不进入单章上下文</n-tag>
        </div>
        <p v-if="farVision.theme"><strong>主题压力：</strong>{{ farVision.theme }}</p>
        <p v-if="farVision.finalPressure"><strong>终局压力：</strong>{{ farVision.finalPressure }}</p>
        <div v-if="farVision.futureVolumes?.length" class="line-list">
          <strong>后续卷方向：</strong>
          <span v-for="(item, index) in farVision.futureVolumes" :key="index">{{ renderListItem(item) }}</span>
        </div>
        <div v-if="farVision.unresolvedBigQuestions?.length" class="line-list">
          <strong>暂不解答的大问题：</strong>
          <span v-for="(item, index) in farVision.unresolvedBigQuestions" :key="index">{{ renderListItem(item) }}</span>
        </div>
        <div v-if="farVision.possibleEndings?.length" class="line-list">
          <strong>可能收束：</strong>
          <span v-for="(item, index) in farVision.possibleEndings" :key="index">{{ renderListItem(item) }}</span>
        </div>
      </section>

      <section class="planning-block">
        <div class="block-title">
          <span>当前卷规划</span>
          <n-tag size="tiny" type="info" :bordered="false">卷级约束</n-tag>
        </div>
        <p v-if="currentVolumePlan.title"><strong>卷名：</strong>{{ currentVolumePlan.title }}</p>
        <p v-if="currentVolumePlan.goal"><strong>阶段目标：</strong>{{ currentVolumePlan.goal }}</p>
        <p v-if="currentVolumePlan.mainConflict || currentVolumePlan.conflict">
          <strong>主冲突：</strong>{{ currentVolumePlan.mainConflict || currentVolumePlan.conflict }}
        </p>
        <p v-if="currentVolumePlan.emotionalArc"><strong>情绪弧：</strong>{{ currentVolumePlan.emotionalArc }}</p>
      </section>

      <section class="planning-block">
        <div class="block-title">
          <span>方向参考</span>
          <n-tag size="tiny" type="success" :bordered="false">仅作参考</n-tag>
        </div>
        <div v-if="nearChapters.length" class="near-list">
          <div v-for="item in nearChapters" :key="`${item.chapterNum}-${item.title}`" class="near-item">
            <div class="near-title">
              <n-tag size="tiny" type="success" :bordered="false">第 {{ item.chapterNum }} 章</n-tag>
              <strong>{{ item.title || '未命名' }}</strong>
            </div>
            <p v-if="item.goal">{{ item.goal }}</p>
            <p v-if="item.handoff" class="handoff">接力：{{ item.handoff }}</p>
          </div>
        </div>
        <n-empty v-else description="暂无方向参考" size="small" />
      </section>
    </div>
  </n-card>

  <n-modal v-model:show="showEditor" title="编辑规划蓝图" preset="card" style="width: 860px">
    <n-form :model="formValue" label-placement="top">
      <div class="form-grid">
        <n-form-item label="长线主题压力">
          <n-input v-model:value="formValue.theme" type="textarea" rows="2" />
        </n-form-item>
        <n-form-item label="终局压力">
          <n-input v-model:value="formValue.finalPressure" type="textarea" rows="2" />
        </n-form-item>
      </div>
      <n-form-item label="后续卷方向（每行一条，不细化到章节）">
        <n-input v-model:value="formValue.futureVolumesText" type="textarea" rows="3" />
      </n-form-item>
      <n-form-item label="可能结局 / 未解大问题">
        <div class="form-grid">
          <n-input v-model:value="formValue.possibleEndingsText" type="textarea" rows="3" placeholder="可能结局，每行一条" />
          <n-input v-model:value="formValue.unresolvedBigQuestionsText" type="textarea" rows="3" placeholder="未解大问题，每行一条" />
        </div>
      </n-form-item>
      <div class="form-grid">
        <n-form-item label="当前卷名称">
          <n-input v-model:value="formValue.currentTitle" />
        </n-form-item>
        <n-form-item label="当前卷章节范围">
          <n-space>
            <n-input-number v-model:value="formValue.rangeStart" :min="1" :step="1" />
            <n-input-number v-model:value="formValue.rangeEnd" :min="1" :step="1" />
          </n-space>
        </n-form-item>
      </div>
      <n-form-item label="当前卷目标">
        <n-input v-model:value="formValue.currentGoal" type="textarea" rows="2" />
      </n-form-item>
      <n-form-item label="当前卷主冲突与情绪弧">
        <div class="form-grid">
          <n-input v-model:value="formValue.currentConflict" type="textarea" rows="3" placeholder="主冲突" />
          <n-input v-model:value="formValue.currentEmotionalArc" type="textarea" rows="3" placeholder="情绪弧" />
        </div>
      </n-form-item>
      <n-form-item label="必须保留 / 暂不推进">
        <div class="form-grid">
          <n-input v-model:value="formValue.mustKeepText" type="textarea" rows="3" placeholder="必须保留，每行一条" />
          <n-input v-model:value="formValue.mustNotAdvanceYetText" type="textarea" rows="3" placeholder="暂不推进，每行一条" />
        </div>
      </n-form-item>
      <n-form-item label="方向参考（每行：章号｜标题｜目标｜冲突｜转折｜情绪｜接力；不作为章节生成主依据）">
        <n-input v-model:value="formValue.nearChaptersText" type="textarea" rows="6" />
      </n-form-item>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="showEditor = false">取消</n-button>
        <n-button type="primary" :loading="saving" @click="handleManualSave">保存规划</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<style scoped>
.rolling-planning-panel {
  margin-bottom: 16px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.panel-header h3 {
  margin: 0;
  color: #1f2937;
  font-size: 18px;
  font-weight: 700;
}

.panel-header p {
  margin: 4px 0 0;
  color: #8a94a6;
  font-size: 13px;
  line-height: 1.6;
}

.planning-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.planning-block {
  min-width: 0;
  border: 1px solid #edf0f5;
  border-radius: 8px;
  padding: 12px;
  background: #fbfcfe;
}

.planning-block-wide {
  grid-column: 1 / -1;
}

.block-title,
.near-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.block-title {
  justify-content: space-between;
  margin-bottom: 8px;
  color: #1f2937;
  font-weight: 700;
}

.planning-block p {
  margin: 6px 0;
  color: #4b5563;
  line-height: 1.7;
}

.line-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  color: #4b5563;
}

.line-list span {
  padding: 3px 8px;
  border-radius: 6px;
  background: #f3f4f6;
}

.near-list {
  display: grid;
  gap: 8px;
}

.near-item {
  padding: 10px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #edf0f5;
}

.near-item p {
  margin: 6px 0 0;
}

.handoff {
  color: #6b7280;
  font-size: 13px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
}

@media (max-width: 860px) {
  .panel-header,
  .planning-grid,
  .form-grid {
    grid-template-columns: 1fr;
    flex-direction: column;
  }
}
</style>
