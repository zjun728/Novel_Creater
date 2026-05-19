<script setup>
import { ref, onMounted, computed } from 'vue'
import { NButton, NCard, NModal, NForm, NFormItem, NInput, NSpace, NEmpty, NSpin } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useResetConfirmation } from '@/composables/useResetConfirmation'
import { useSeedStore } from '@/stores/seedStore'
import { useNovelStore } from '@/stores/novelStore'
import { useWriterStore } from '@/stores/writerStore'
import { useSettingStore } from '@/stores/settingStore'
import { extractSeedsFromText } from '@/utils/seedParser'
import SeedCard from './SeedCard.vue'
import StyleTrialPanel from './StyleTrialPanel.vue'

const props = defineProps({
  projectId: { type: String, required: true }
})

const emit = defineEmits(['seedSelected'])

const seedStore = useSeedStore()
const novelStore = useNovelStore()
const writerStore = useWriterStore()
const settingStore = useSettingStore()
const message = useAppMessage()
const { confirmStageReset } = useResetConfirmation()

const showCreateModal = ref(false)
const showGenModal = ref(false)
const showDetailModal = ref(false)
const detailSeed = ref(null)
const selectedStyleBible = ref('')
const detailForm = ref(null)
const detailSaving = ref(false)

function emptySeedForm() {
  return {
  title: '',
  genre: '',
  logline: '',
  protagonist: '',
  desire: '',
  coreConflict: '',
  worldPressure: '',
  openingHook: '',
  emotionalPromise: '',
  differentiation: '',
  styleTarget: '',
  riskNotes: '',
  endingAnchor: ''
  }
}

function toSeedForm(seed = {}) {
  return {
    title: seed.title || '',
    genre: seed.genre || '',
    logline: seed.logline || '',
    protagonist: seed.protagonist || '',
    desire: seed.desire || '',
    coreConflict: seed.coreConflict || '',
    worldPressure: seed.worldPressure || '',
    openingHook: seed.openingHook || '',
    emotionalPromise: seed.emotionalPromise || '',
    differentiation: seed.differentiation || '',
    styleTarget: seed.styleTarget || '',
    riskNotes: seed.riskNotes || '',
    endingAnchor: seed.endingAnchor || ''
  }
}

const formValue = ref(emptySeedForm())

const genInput = ref({
  idea: '',
  genre: '',
  stylePreference: '',
  forbidden: ''
})

onMounted(async () => {
  await seedStore.loadSeeds(props.projectId)
  await novelStore.loadBible(props.projectId)
})

const selectedSeed = computed(() =>
  seedStore.seeds.find(s => s.status === 'selected')
)

async function handleCreate() {
  if (!formValue.value.title.trim()) {
    message.warning('请输入种子标题')
    return
  }
  try {
    await seedStore.createSeed(props.projectId, formValue.value)
    message.success('种子创建成功')
    showCreateModal.value = false
    formValue.value = emptySeedForm()
  } catch (e) {
    message.error('创建失败：' + e.message)
  }
}

async function handleSelect(seed) {
  await seedStore.selectSeed(seed)
  message.success(`已选择种子「${seed.title}」`)
  emit('seedSelected', seed)
}

async function handleDelete(seed) {
  await seedStore.deleteSeed(seed.id)
  message.success('已删除')
}

async function handleClearSeeds() {
  if (!seedStore.seeds.length) {
    message.warning('当前没有可清空的种子')
    return
  }
  const { confirmed } = await confirmStageReset({
    projectId: props.projectId,
    title: '清空创作种子',
    safeContent: '将清空当前项目的所有创作种子。后续可以重新生成或手动创建种子。',
    riskContent: '清空种子不会删除已生成的圣经、设定库和章节，但会移除它们的早期来源依据。',
    finalContent: '最终确认：清空种子后，所有候选种子和当前选中种子都会被删除。已写章节不会删除。',
    positiveText: '确认清空种子'
  })
  if (!confirmed) return

  try {
    await seedStore.clearSeeds(props.projectId)
    detailSeed.value = null
    detailForm.value = null
    showDetailModal.value = false
    selectedStyleBible.value = ''
    message.success('创作种子已清空，可以重新生成')
  } catch (e) {
    message.error('清空种子失败：' + e.message)
  }
}

async function handleGenerate() {
  if (!genInput.value.idea.trim()) {
    message.warning('请输入你的创作想法')
    return
  }
  const imported = await handleImportPastedSeeds(false)
  if (imported) return

  try {
    const created = await seedStore.generateSeeds(props.projectId, genInput.value)
    message.success(`AI 生成了 ${created.length} 个种子`)
    showGenModal.value = false
  } catch (e) {
    message.error('生成失败：' + e.message)
  }
}

async function handleImportPastedSeeds(showFailure = true) {
  const text = [
    genInput.value.idea || '',
    genInput.value.genre || '',
    genInput.value.stylePreference || '',
    genInput.value.forbidden || ''
  ].filter(Boolean).join('\n\n')

  const parsed = extractSeedsFromText(text)
  if (!parsed.length) {
    if (showFailure) {
      message.warning('没有从粘贴内容中解析到种子，请确认包含 title/标题、genre/题材、logline/一句话等字段')
    }
    return false
  }

  try {
    for (const seed of parsed) {
      await seedStore.createSeed(props.projectId, { ...seed, source: 'user' })
    }
    message.success(`已从粘贴内容保存 ${parsed.length} 个种子`)
    showGenModal.value = false
    return true
  } catch (e) {
    message.error('保存粘贴种子失败：' + e.message)
    return true
  }
}

function viewDetail(seed) {
  detailSeed.value = seed
  detailForm.value = toSeedForm(seed)
  showDetailModal.value = true
}

function editSelectedSeed() {
  if (selectedSeed.value) viewDetail(selectedSeed.value)
}

async function handleSaveDetail() {
  if (!detailSeed.value || !detailForm.value) return
  if (!detailForm.value.title.trim()) {
    message.warning('请输入种子标题')
    return
  }

  detailSaving.value = true
  try {
    const updated = await seedStore.updateSeed({
      ...detailSeed.value,
      ...detailForm.value
    })
    detailSeed.value = updated
    message.success('种子已保存')
  } catch (e) {
    message.error('保存失败：' + e.message)
  } finally {
    detailSaving.value = false
  }
}

async function handleSaveAsNewSeed() {
  if (!detailForm.value) return
  if (!detailForm.value.title.trim()) {
    message.warning('请输入种子标题')
    return
  }

  detailSaving.value = true
  try {
    const created = await seedStore.createSeed(props.projectId, {
      ...detailForm.value,
      title: detailForm.value.title.endsWith(' 调整版') ? detailForm.value.title : `${detailForm.value.title} 调整版`,
      source: 'user'
    })
    detailSeed.value = created
    detailForm.value = toSeedForm(created)
    message.success('已另存为新种子')
  } catch (e) {
    message.error('另存失败：' + e.message)
  } finally {
    detailSaving.value = false
  }
}

function handleApplyStyle({ styleBible }) {
  selectedStyleBible.value = styleBible
}

async function planningIsLocked() {
  await Promise.allSettled([
    writerStore.loadChapters(props.projectId),
    settingStore.loadEntities(props.projectId),
    settingStore.loadChangeEvents(props.projectId)
  ])

  const hasWrittenChapter = writerStore.chapters.some(ch =>
    Number(ch.wordCount || 0) > 0
    || Boolean(ch.finalVersionId)
    || ch.status === 'final'
    || ch.status === 'draft'
  )
  const hasSettingData = settingStore.entities.length > 0
    || settingStore.changeEvents.some(event => event.status !== 'rejected')

  return hasWrittenChapter || hasSettingData
}

// 从选中的种子创建创作圣经
async function createBibleFromSeed() {
  const seed = selectedSeed.value
  if (!seed) {
    message.warning('请先选择一个种子')
    return
  }
  try {
    const existingBible = novelStore.bible || await novelStore.loadBible(props.projectId)
    if (existingBible) {
      message.warning('当前项目已有创作圣经，不能再从种子重复生成并覆盖。请到创作圣经页局部编辑。')
      return
    }
    if (await planningIsLocked()) {
      message.warning('项目已进入设定库或写作阶段，不能再从种子生成创作圣经；请在创作圣经中局部编辑。')
      return
    }
    await novelStore.generateBibleFromSeed(props.projectId, seed, {
      selectedStyleBible: selectedStyleBible.value
    })
    message.success('创作圣经已生成，请到创作圣经页编辑确认')
  } catch (e) {
    message.error('生成创作圣经失败：' + e.message)
  }
}
</script>

<template>
  <div class="seed-workbench">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-lg font-semibold text-gray-700">创作种子</h3>
      <n-space>
        <n-button size="small" type="error" secondary :disabled="!seedStore.seeds.length" @click="handleClearSeeds">
          清空种子
        </n-button>
        <n-button size="small" @click="showGenModal = true" :loading="seedStore.generating">
          🤖 AI 生成种子
        </n-button>
        <n-button size="small" type="primary" @click="showCreateModal = true">
          手动创建种子
        </n-button>
      </n-space>
    </div>

    <!-- 已选中的种子 -->
    <n-card v-if="selectedSeed" title="当前选中的种子" class="mb-4 border-2 border-green-300" size="small">
      <div class="space-y-4 text-[15px] leading-7 text-gray-700 break-words">
        <div><span class="font-medium text-gray-500">题材：</span>{{ selectedSeed.genre }}</div>
        <div><span class="font-medium text-gray-500">风格：</span>{{ selectedSeed.styleTarget || '未指定' }}</div>
        <div class="col-span-2"><span class="font-medium text-gray-500">一句话：</span>{{ selectedSeed.logline }}</div>
        <div><span class="font-medium text-gray-500">主角：</span>{{ selectedSeed.protagonist }}</div>
        <div><span class="font-medium text-gray-500">欲望：</span>{{ selectedSeed.desire }}</div>
        <div class="col-span-2"><span class="font-medium text-gray-500">核心矛盾：</span>{{ selectedSeed.coreConflict }}</div>
        <div class="col-span-2"><span class="font-medium text-gray-500">开局钩子：</span>{{ selectedSeed.openingHook }}</div>
        <div v-if="selectedSeed.riskNotes" class="col-span-2"><span class="font-medium text-gray-500">风险提示：</span>{{ selectedSeed.riskNotes }}</div>
        <div v-if="selectedSeed.endingAnchor" class="col-span-2"><span class="font-medium text-gray-500">结局锚点：</span>{{ selectedSeed.endingAnchor }}</div>
        <div v-if="selectedStyleBible" class="rounded bg-green-50 border border-green-100 px-3 py-2 text-sm text-green-800">
          已选择风格试写结果，创建创作圣经时会写入风格基准。
        </div>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="editSelectedSeed">
            手动调整
          </n-button>
          <n-button size="small" type="primary" :loading="novelStore.generatingBible" @click="createBibleFromSeed">
            以此创建创作圣经
          </n-button>
        </n-space>
      </template>
    </n-card>

    <StyleTrialPanel
      v-if="selectedSeed"
      :project-id="projectId"
      :seed="selectedSeed"
      @apply-style="handleApplyStyle"
    />

    <!-- 种子列表 -->
    <n-empty v-if="seedStore.seeds.length === 0 && !seedStore.loading" description="还没有创作种子，点击上方按钮创建">
    </n-empty>

    <div class="grid grid-cols-1 xl:grid-cols-2 gap-4" v-if="seedStore.seeds.length > 0">
      <SeedCard
        v-for="seed in seedStore.seeds"
        :key="seed.id"
        :seed="seed"
        :selected="seed.status === 'selected'"
        @select="handleSelect"
        @delete="handleDelete"
        @view="viewDetail"
      />
    </div>

    <!-- 手动创建弹窗 -->
    <n-modal v-model:show="showCreateModal" title="创建种子" preset="card" style="width: 600px">
      <n-form :model="formValue" label-placement="left" label-width="90">
        <n-form-item label="标题" required>
          <n-input v-model:value="formValue.title" placeholder="种子标题" />
        </n-form-item>
        <n-form-item label="题材">
          <n-input v-model:value="formValue.genre" placeholder="如：玄幻、都市、科幻" />
        </n-form-item>
        <n-form-item label="一句话故事">
          <n-input v-model:value="formValue.logline" type="textarea" rows="2" placeholder="30字以内" />
        </n-form-item>
        <n-form-item label="主角">
          <n-input v-model:value="formValue.protagonist" placeholder="主角简介" />
        </n-form-item>
        <n-form-item label="主角欲望">
          <n-input v-model:value="formValue.desire" placeholder="核心欲望" />
        </n-form-item>
        <n-form-item label="核心矛盾">
          <n-input v-model:value="formValue.coreConflict" type="textarea" rows="2" placeholder="核心矛盾" />
        </n-form-item>
        <n-form-item label="世界压力">
          <n-input v-model:value="formValue.worldPressure" type="textarea" rows="2" placeholder="世界施加的压力" />
        </n-form-item>
        <n-form-item label="开局钩子">
          <n-input v-model:value="formValue.openingHook" type="textarea" rows="3" placeholder="开局场景" />
        </n-form-item>
        <n-form-item label="情绪价值">
          <n-input v-model:value="formValue.emotionalPromise" placeholder="如：爽感、悬念、共鸣" />
        </n-form-item>
        <n-form-item label="差异化">
          <n-input v-model:value="formValue.differentiation" type="textarea" rows="2" placeholder="与同类作品的区别" />
        </n-form-item>
        <n-form-item label="风格目标">
          <n-input v-model:value="formValue.styleTarget" placeholder="如：快节奏爽文、慢热文学" />
        </n-form-item>
        <n-form-item label="风险提示">
          <n-input v-model:value="formValue.riskNotes" type="textarea" rows="2" placeholder="可能踩的坑、需要回避的问题" />
        </n-form-item>
        <n-form-item label="结局锚点">
          <n-input v-model:value="formValue.endingAnchor" type="textarea" rows="3" placeholder="故事最终抵达的画面、主题归宿或收束方式" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreateModal = false">取消</n-button>
          <n-button type="primary" @click="handleCreate">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- AI 生成弹窗 -->
    <n-modal v-model:show="showGenModal" title="AI 生成种子" preset="card" style="width: 560px">
      <n-form :model="genInput" label-placement="left" label-width="90">
        <n-form-item label="创作想法" required>
          <n-input v-model:value="genInput.idea" type="textarea" rows="4" placeholder="描述你的创作想法，越具体 AI 给出的种子越精准..." />
        </n-form-item>
        <n-form-item label="偏好题材">
          <n-input v-model:value="genInput.genre" placeholder="如：玄幻、都市、科幻" />
        </n-form-item>
        <n-form-item label="偏好风格">
          <n-input v-model:value="genInput.stylePreference" placeholder="如：快节奏爽文、慢热文学" />
        </n-form-item>
        <n-form-item label="不想写">
          <n-input v-model:value="genInput.forbidden" placeholder="不想写的方向、套路或类型" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showGenModal = false">取消</n-button>
          <n-button :disabled="seedStore.generating" @click="handleImportPastedSeeds(true)">保存粘贴种子</n-button>
          <n-button type="primary" :loading="seedStore.generating" @click="handleGenerate">生成</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 种子详情弹窗 -->
    <n-modal
      v-model:show="showDetailModal"
      title="查看 / 调整种子"
      preset="card"
      class="seed-detail-modal"
      style="width: min(880px, calc(100vw - 48px));"
    >
      <div v-if="detailSeed && detailForm" class="seed-detail-body space-y-3">
        <div class="flex items-center gap-2 text-xs text-gray-400">
          <span>来源：{{ detailSeed.source === 'ai' ? 'AI 生成' : '手动创建' }}</span>
          <span>状态：{{ detailSeed.status === 'selected' ? '当前选中' : '候选' }}</span>
        </div>
        <n-form :model="detailForm" label-placement="left" label-width="96">
          <n-form-item label="标题" required>
            <n-input v-model:value="detailForm.title" placeholder="种子标题" />
          </n-form-item>
          <n-form-item label="题材">
            <n-input v-model:value="detailForm.genre" placeholder="如：玄幻、都市、科幻" />
          </n-form-item>
          <n-form-item label="一句话">
            <n-input v-model:value="detailForm.logline" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="一句话故事核心" />
          </n-form-item>
          <n-form-item label="主角">
            <n-input v-model:value="detailForm.protagonist" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="主角身份、性格、初始处境" />
          </n-form-item>
          <n-form-item label="主角欲望">
            <n-input v-model:value="detailForm.desire" placeholder="ta 最想要什么" />
          </n-form-item>
          <n-form-item label="核心矛盾">
            <n-input v-model:value="detailForm.coreConflict" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="阻碍主角的核心力量" />
          </n-form-item>
          <n-form-item label="世界压力">
            <n-input v-model:value="detailForm.worldPressure" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="时代、社会、规则、环境施加的压力" />
          </n-form-item>
          <n-form-item label="开局钩子">
            <n-input v-model:value="detailForm.openingHook" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="第一章可直接使用的开局场景" />
          </n-form-item>
          <n-form-item label="情绪价值">
            <n-input v-model:value="detailForm.emotionalPromise" placeholder="爽感、共情、悬念、热血等" />
          </n-form-item>
          <n-form-item label="差异化">
            <n-input v-model:value="detailForm.differentiation" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="和同类作品相比哪里不同" />
          </n-form-item>
          <n-form-item label="风格目标">
            <n-input v-model:value="detailForm.styleTarget" placeholder="如：快节奏爽文、冷峻克制、轻松吐槽" />
          </n-form-item>
          <n-form-item label="风险提示">
            <n-input v-model:value="detailForm.riskNotes" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="可能踩的坑、需要回避的问题" />
          </n-form-item>
          <n-form-item label="结局锚点">
            <n-input v-model:value="detailForm.endingAnchor" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" placeholder="故事最终抵达的画面、主题归宿或收束方式" />
          </n-form-item>
        </n-form>
      </div>
      <template #footer>
        <n-space justify="end" class="seed-detail-footer">
          <n-button @click="showDetailModal = false">关闭</n-button>
          <n-button :loading="detailSaving" @click="handleSaveAsNewSeed">另存为新种子</n-button>
          <n-button type="primary" :loading="detailSaving" @click="handleSaveDetail">保存修改</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.seed-detail-body {
  max-height: calc(88vh - 150px);
  overflow-y: auto;
  padding-right: 6px;
}

.seed-detail-footer {
  padding-top: 12px;
  border-top: 1px solid #eef0f4;
}

.seed-detail-body :deep(.n-form-item) {
  margin-bottom: 14px;
}

.seed-detail-body :deep(.n-form-item-label) {
  align-items: flex-start;
  padding-top: 8px;
  font-weight: 500;
}

.seed-detail-body :deep(.n-input__textarea-el),
.seed-detail-body :deep(.n-input__input-el) {
  line-height: 1.7;
}

@media (max-width: 768px) {
  .seed-detail-body {
    max-height: calc(88vh - 170px);
  }
}
</style>
