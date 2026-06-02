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
  WRITING_STYLE_STANDARDS,
  getSelectedWritingStyleStandards,
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
const displayBible = computed(() => novelStore.bible ? normalizeBiblePayload(novelStore.bible) : null)
const bibleInitialized = computed(() => settingStore.hasBibleInitialization)
const standardOptions = computed(() => WRITING_STYLE_STANDARDS.map(item => ({
  label: item.name,
  value: item.id
})))
const secondaryStandardOptions = computed(() => [
  { label: '不选择辅助风味', value: '' },
  ...WRITING_STYLE_STANDARDS
    .filter(item => item.id !== formData.value.writingProfile?.primaryStandard)
    .map(item => ({ label: item.name, value: item.id }))
])
const selectedStyleStandards = computed(() => getSelectedWritingStyleStandards(
  displayBible.value?.writingProfile
))

function emptyBibleForm() {
  return {
    premise: '',
    targetReader: '',
    styleBible: '',
    themeBible: '',
    worldRules: '',
    writingProfile: {
      primaryStandard: '',
      secondaryFlavor: '',
      customStyleNotes: ''
    },
    forbiddenDirections: []
  }
}

const formData = ref(emptyBibleForm())

function syncBibleToForm(bible = novelStore.bible) {
  if (!bible) {
    formData.value = emptyBibleForm()
    return
  }

  const normalized = normalizeBiblePayload(bible)
  const writingProfile = normalizeWritingProfile(normalized.writingProfile)
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
  await Promise.allSettled([
    novelStore.loadBible(projectId),
    settingStore.loadChangeEvents(projectId)
  ])
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
  const writingProfile = normalizeWritingProfile(formData.value.writingProfile)
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
    message.success(`已提取 ${created.length} 条待确认设定，请到设定库确认入库`)
  } catch (e) {
    message.error('提取设定失败：' + e.message)
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
          :disabled="!displayBible || bibleInitialized"
          :loading="settingStore.initializingFromBible"
          @click="handleInitializeSettings"
        >
          {{ bibleInitialized ? '已提取到设定库' : '提取到设定库' }}
        </n-button>
        <n-button size="tiny" @click="toggleEditing">{{ editing ? '取消' : '编辑' }}</n-button>
      </n-space>
    </template>

    <div v-if="!editing && displayBible" class="space-y-3 text-sm">
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
          未选择主写作标准。建议编辑创作圣经，为本书选择一套核心写法，避免后续章节风格漂移。
        </div>
        <p class="mt-2 text-xs text-gray-500">
          主写作标准决定核心写法，辅助风味只做局部气质补充，不会推翻主写作标准。
        </p>
        <p v-if="displayBible.writingProfile?.customStyleNotes" class="mt-2 text-xs text-gray-600 whitespace-pre-wrap">
          {{ displayBible.writingProfile.customStyleNotes }}
        </p>
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
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label class="text-xs text-gray-500 mb-1 block">主写作标准</label>
          <n-select
            v-model:value="formData.writingProfile.primaryStandard"
            :options="standardOptions"
            clearable
            placeholder="选择最贴近本书的核心写法"
          />
        </div>
        <div>
          <label class="text-xs text-gray-500 mb-1 block">辅助风味</label>
          <n-select
            v-model:value="formData.writingProfile.secondaryFlavor"
            :options="secondaryStandardOptions"
            placeholder="可选：补充一个局部气质"
          />
        </div>
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
