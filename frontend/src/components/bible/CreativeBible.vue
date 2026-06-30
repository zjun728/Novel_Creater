<script setup>
import { computed, h, ref, onMounted, watch } from 'vue'
import { NButton, NCard, NInput, NSpace, NTag, NDynamicTags, NSelect } from 'naive-ui'
import { useDialog } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useResetConfirmation } from '@/composables/useResetConfirmation'
import { useNovelStore } from '@/stores/novelStore'
import { useSettingStore } from '@/stores/settingStore'
import { normalizeBiblePayload } from '@/prompts/bibleFromSeed'
import {
  createWritingProfileStandardSnapshots,
  getSelectableWritingStyleStandards,
  getSelectedWritingStyleStandards,
  getWritingStrategyDisplayCards,
  normalizeWritingProfile
} from '@/data/writingStyleStandards'
import { api } from '@/api/db/client'

const props = defineProps({
  projectId: { type: String, required: true }
})

const novelStore = useNovelStore()
const settingStore = useSettingStore()
const message = useAppMessage()
const dialog = useDialog()
const { confirmStageReset } = useResetConfirmation()

const editing = ref(false)
const backendWritingStandards = ref([])
const displayBible = computed(() => novelStore.bible ? normalizeBiblePayload(novelStore.bible) : null)
const bibleInitialized = computed(() => settingStore.hasBibleInitialization)
const settingInitializationProgress = computed(() => settingStore.bibleInitializationProgress || null)
const canRetryFailedSettingGroups = computed(() =>
  Boolean(displayBible.value && settingStore.failedGroups?.length && !settingStore.initializingFromBible)
)
const writingStyleOptions = computed(() => ({ backendStandards: backendWritingStandards.value }))
const writingStyleStandards = computed(() => getSelectableWritingStyleStandards(writingStyleOptions.value))
const standardOptions = computed(() => writingStyleStandards.value.map(item => ({
  label: `${item.name} · ${item.sourceKind === 'system' ? '系统内置标准' : '我的写作标准'}`,
  value: item.id
})))
const selectedStyleStandards = computed(() => getSelectedWritingStyleStandards(
  displayBible.value?.writingProfile,
  writingStyleOptions.value
))
const writingStrategyCards = computed(() => getWritingStrategyDisplayCards(
  displayBible.value?.writingProfile,
  writingStyleOptions.value
))

function emptyBibleForm() {
  return {
    premise: '',
    targetReader: '',
    styleBible: '',
    themeBible: '',
    worldRules: '',
    writingProfile: {
      selectedStandards: [],
      primaryStandard: '',
      secondaryFlavor: '',
      additionalStandards: [],
      customStyleNotes: ''
    },
    forbiddenDirections: []
  }
}

const formData = ref(emptyBibleForm())

const selectedWritingStandardValues = computed({
  get() {
    return Array.isArray(formData.value.writingProfile?.selectedStandards)
      ? formData.value.writingProfile.selectedStandards
      : [
          formData.value.writingProfile?.primaryStandard,
          formData.value.writingProfile?.secondaryFlavor,
          ...(Array.isArray(formData.value.writingProfile?.additionalStandards) ? formData.value.writingProfile.additionalStandards : [])
        ].filter(Boolean)
  },
  set(value) {
    const ids = Array.from(new Set((Array.isArray(value) ? value : []).filter(Boolean))).slice(0, 3)
    formData.value.writingProfile = {
      ...(formData.value.writingProfile || {}),
      selectedStandards: ids,
      primaryStandard: ids[0] || '',
      secondaryFlavor: ids[1] || '',
      additionalStandards: ids.slice(2)
    }
  }
})

function syncBibleToForm(bible = novelStore.bible) {
  if (!bible) {
    formData.value = emptyBibleForm()
    return
  }

  const normalized = normalizeBiblePayload(bible)
  const writingProfile = normalizeWritingProfile(normalized.writingProfile, {
    ...writingStyleOptions.value,
    preserveUnknown: true
  })
  formData.value = {
    premise: normalized.premise || '',
    targetReader: normalized.targetReader || '',
    styleBible: normalized.styleBible || '',
    themeBible: normalized.themeBible || '',
    worldRules: normalized.worldRules || '',
    writingProfile,
    forbiddenDirections: normalized.forbiddenDirections || []
  }
}

function toggleEditing() {
  if (!editing.value) syncBibleToForm()
  editing.value = !editing.value
}

async function loadPageData(projectId) {
  const [, , standardsResult] = await Promise.allSettled([
    novelStore.loadBible(projectId),
    settingStore.loadChangeEvents(projectId),
    api.experienceCards.standards.list()
  ])
  if (standardsResult.status === 'fulfilled') {
    backendWritingStandards.value = Array.isArray(standardsResult.value) ? standardsResult.value : []
  }
  settingStore.loadBibleInitializationProgress(projectId)
  syncBibleToForm()
}

onMounted(async () => {
  await loadPageData(props.projectId)
})

watch(() => props.projectId, async (newId) => {
  if (newId) await loadPageData(newId)
})

watch(() => novelStore.bible, (value) => {
  if (!editing.value) syncBibleToForm(value)
}, { deep: true })

async function handleSave() {
  const writingProfile = normalizeWritingProfile(formData.value.writingProfile, {
    ...writingStyleOptions.value,
    preserveUnknown: true
  })
  const standardSnapshots = createWritingProfileStandardSnapshots(writingProfile, writingStyleStandards.value)
  if (Object.keys(standardSnapshots).length) {
    writingProfile.standardSnapshots = standardSnapshots
  }
  const payload = {
    ...formData.value,
    writingProfile
  }

  const state = await api.projects.contentState(props.projectId)
  if (state.hasChapterContent) {
    const confirmed = await new Promise(resolve => {
      dialog.warning({
        title: '已进入写作阶段',
        content: () => h('div', { class: 'app-message-dialog-content' }, '当前项目已有正文内容。保存圣经修改只会影响后续写作上下文，不会自动改写既有章节；如果是大改主线，建议先通过纠偏任务或新草案方式处理。'),
        positiveText: '继续保存',
        negativeText: '取消',
        maskClosable: false,
        onPositiveClick: () => resolve(true),
        onNegativeClick: () => resolve(false),
        onClose: () => resolve(false)
      })
    })
    if (!confirmed) return
  }
  await novelStore.saveBible(props.projectId, payload)
  message.success('创作圣经已保存')
  editing.value = false
}

async function handleInitializeSettings() {
  if (!displayBible.value) {
    message.warning('请先生成或填写创作圣经')
    return
  }
  if (bibleInitialized.value) {
    message.warning('创作圣经已提取过设定库，后续请通过章节定稿提取或手动维护设定')
    return
  }
  try {
    const state = await api.projects.contentState(props.projectId)
    if (state.hasChapterContent) {
      message.warning('当前项目已经有正文内容，不能再从创作圣经做初始化提取。后续请通过章节定稿提取设定变更，避免覆盖已经写过的设定。')
      return
    }
  } catch (e) {
    message.error('检查项目写作状态失败：' + e.message)
    return
  }

  try {
    const created = await settingStore.initializeFromBible(props.projectId, displayBible.value)
    if (settingStore.failedGroups.length) {
      message.warning(`已提取 ${created.length} 条待确认设定，部分分组失败后可重试失败分组`)
    } else {
      message.success(`已提取 ${created.length} 条待确认设定，请到设定库确认入库`)
    }
  } catch (e) {
    message.error('提取设定失败：' + e.message + '。可重试失败分组。')
  }
}

async function handleRetryFailedSettingGroups() {
  if (!displayBible.value) return
  try {
    const created = await settingStore.retryFailedBibleInitializationGroups(props.projectId, displayBible.value)
    if (settingStore.failedGroups.length) {
      message.warning(`已继续提取 ${created.length} 条待确认设定，仍有分组失败后可重试`)
    } else {
      message.success(`失败分组已重试，新增 ${created.length} 条待确认设定`)
    }
  } catch (e) {
    message.error('重试失败分组失败：' + e.message)
  }
}

async function handleDeleteBible() {
  const { confirmed } = await confirmStageReset({
    projectId: props.projectId,
    title: '删除创作圣经',
    safeContent: '将删除当前创作圣经。因为还没有章节内容，删除后可以重新从种子生成圣经。',
    riskContent: '删除创作圣经不会删除已写章节，但会移除后续写作的重要蓝图依据。已有章节可能与重新生成的圣经不一致。',
    finalContent: '最终确认：删除创作圣经后，原有作品定位、风格要求、主题母题、世界规则和禁止方向都会被清空。',
    positiveText: '确认删除圣经',
    blockWhenChapterContent: true,
    blockedContent: '当前项目已有正文内容，不能删除创作圣经。后续如需调整，请使用局部编辑、纠偏任务或新草案迁移。'
  })
  if (!confirmed) return

  try {
    await novelStore.deleteBible(props.projectId)
    editing.value = false
    syncBibleToForm(null)
    message.success('创作圣经已删除，可以重新生成')
  } catch (e) {
    message.error('删除创作圣经失败：' + e.message)
  }
}
</script>

<template>
  <n-card title="创作圣经" size="small">
    <template #header-extra>
      <n-space size="small">
        <n-button
          v-if="!editing && displayBible"
          size="tiny"
          type="error"
          secondary
          :loading="novelStore.loading"
          @click="handleDeleteBible"
        >
          删除圣经
        </n-button>
        <n-button
          v-if="!editing"
          size="tiny"
          type="primary"
          :disabled="!displayBible || bibleInitialized || settingStore.initializingFromBible"
          :loading="settingStore.initializingFromBible"
          @click="handleInitializeSettings"
        >
          {{ bibleInitialized ? '已提取到设定库' : '提取到设定库' }}
        </n-button>
        <n-button
          v-if="canRetryFailedSettingGroups"
          size="tiny"
          type="warning"
          secondary
          :loading="settingStore.initializingFromBible"
          @click="handleRetryFailedSettingGroups"
        >
          继续提取/重试失败分组
        </n-button>
        <n-button size="tiny" @click="toggleEditing">{{ editing ? '取消' : '编辑' }}</n-button>
      </n-space>
    </template>

    <div v-if="!editing && displayBible" class="space-y-3 text-sm">
      <div
        v-if="settingInitializationProgress"
        class="rounded border border-blue-100 bg-blue-50/70 p-3 text-sm text-blue-900"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="font-medium">
            正在提取设定库：{{ settingStore.currentGroupLabel || '等待下一组' }}
          </span>
          <span class="text-xs">
            已完成 {{ settingInitializationProgress.completedGroups }}/{{ settingInitializationProgress.totalGroups }} 组，
            已生成 {{ settingInitializationProgress.generatedCandidates }} 个候选
          </span>
        </div>
        <div class="mt-2 grid grid-cols-1 md:grid-cols-5 gap-2 text-xs">
          <div
            v-for="group in Object.values(settingInitializationProgress.groups || {})"
            :key="group.key"
            class="rounded border border-blue-100 bg-white/80 px-2 py-1"
          >
            <div class="font-medium">{{ group.label }}</div>
            <div>
              {{
                group.status === 'success'
                  ? `完成，保存 ${group.savedCount || 0} 条`
                  : group.status === 'failed'
                    ? '失败，可重试失败分组'
                    : group.status === 'running'
                      ? '提取中'
                      : '等待'
              }}
            </div>
          </div>
        </div>
        <p v-if="settingStore.failedGroups.length" class="mt-2 text-xs text-orange-700">
          部分分组失败后可重试；已保存的待确认设定不会丢失，重试会去重。
        </p>
      </div>
      <div v-if="displayBible.premise">
        <span class="font-medium text-gray-500">作品定位：</span>
        <p class="text-gray-700">{{ displayBible.premise }}</p>
      </div>
      <div v-if="displayBible.targetReader">
        <span class="font-medium text-gray-500">目标读者：</span>
        <span>{{ displayBible.targetReader }}</span>
      </div>
      <div class="rounded border border-green-100 bg-green-50/60 p-3">
        <div class="flex items-center justify-between gap-2">
          <span class="font-medium text-gray-700">写作策略</span>
          <span class="text-xs text-gray-400">生成小纲、正文和审稿时读取</span>
        </div>
        <n-space v-if="selectedStyleStandards.length" size="small" class="mt-2">
          <n-tag
            v-for="item in selectedStyleStandards"
            :key="`${item.role}-${item.standard.id}`"
            size="small"
            type="success"
          >
            {{ item.role }}：{{ item.standard.name }}
          </n-tag>
        </n-space>
        <div v-else class="mt-2 text-sm text-gray-500">
          未选择正式写作标准。建议编辑创作圣经，为本书选择 1-3 条已激活标准，避免后续章节风格漂移。
        </div>
        <p class="mt-2 text-xs text-gray-500">
          正文生成只读取这里启用并保存的正式写作标准；经验卡和候选标准不会直接进入正文。
        </p>
        <div v-if="writingStrategyCards.length" class="mt-3 grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div
            v-for="card in writingStrategyCards"
            :key="`${card.role}-${card.id}`"
            class="rounded border border-green-100 bg-white/75 p-3"
          >
            <div class="flex items-center gap-2">
              <n-tag size="small" type="success">{{ card.role }}</n-tag>
              <span class="font-medium text-gray-800">{{ card.name }}</span>
              <span class="text-xs text-gray-400">{{ card.category }}</span>
            </div>
            <p class="mt-2 text-xs text-gray-500">{{ card.positioning }}</p>
            <div class="mt-2 space-y-1.5">
              <p
                v-for="section in card.sections"
                :key="`${card.id}-${section.key}`"
                class="text-xs leading-relaxed text-gray-600"
              >
                <span class="font-medium text-gray-700">{{ section.label }}：</span>{{ section.text }}
              </p>
            </div>
            <p v-if="card.note" class="mt-2 text-xs text-gray-600 whitespace-pre-wrap">
              <span class="font-medium text-gray-700">项目备注：</span>{{ card.note }}
            </p>
          </div>
        </div>
      </div>
      <div v-if="displayBible.styleBible">
        <span class="font-medium text-gray-500">风格要求：</span>
        <p class="text-gray-700 whitespace-pre-wrap">{{ displayBible.styleBible }}</p>
      </div>
      <div v-if="displayBible.themeBible">
        <span class="font-medium text-gray-500">主题与母题：</span>
        <p class="text-gray-700 whitespace-pre-wrap">{{ displayBible.themeBible }}</p>
      </div>
      <div v-if="displayBible.worldRules">
        <span class="font-medium text-gray-500">世界规则：</span>
        <p class="text-gray-700 whitespace-pre-wrap">{{ displayBible.worldRules }}</p>
      </div>
      <div v-if="displayBible.forbiddenDirections?.length">
        <span class="font-medium text-gray-500">禁止方向：</span>
        <n-space>
          <n-tag v-for="d in displayBible.forbiddenDirections" :key="d" size="small" type="error">{{ d }}</n-tag>
        </n-space>
      </div>
    </div>

    <div v-if="!editing && !novelStore.bible" class="text-sm text-gray-400 text-center py-4">
      尚未创建创作圣经。选择一个创作种子后可以快速创建。
    </div>

    <div v-if="editing" class="space-y-3">
      <div>
        <label class="text-xs text-gray-500 mb-1 block">作品定位（一句话）</label>
        <n-input v-model:value="formData.premise" type="textarea" rows="2" placeholder="用一句话说清这是一个什么故事" />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">目标读者</label>
        <n-input v-model:value="formData.targetReader" placeholder="如：男频 20-35 岁、喜欢节奏明快的读者" />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">正式写作标准（可选 1-3 条）</label>
        <n-select
          v-model:value="selectedWritingStandardValues"
          :options="standardOptions"
          multiple
          clearable
          :max-tag-count="3"
          placeholder="选择已激活的正式写作标准"
        />
        <p class="mt-1 text-xs text-gray-400">
          这里只显示激活的正式写作标准；取消激活后不会出现在项目选择和正文生成上下文里。
        </p>
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">项目风格备注</label>
        <n-input
          v-model:value="formData.writingProfile.customStyleNotes"
          type="textarea"
          rows="2"
          placeholder="可选：补充本书独有的叙述声音、章节结尾方式或需要特别避开的写法"
        />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">风格要求</label>
        <n-input v-model:value="formData.styleBible" type="textarea" rows="3" placeholder="描述期望的写作风格..." />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">主题与母题</label>
        <n-input v-model:value="formData.themeBible" type="textarea" rows="3" placeholder="作品探讨的主题、母题..." />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">世界规则（不可违背）</label>
        <n-input v-model:value="formData.worldRules" type="textarea" rows="4" placeholder="世界观的基本规则..." />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">禁止方向</label>
        <n-dynamic-tags v-model:value="formData.forbiddenDirections" />
      </div>
      <n-button type="primary" size="small" @click="handleSave">保存</n-button>
    </div>
  </n-card>
</template>
