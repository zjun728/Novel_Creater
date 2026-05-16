<script setup>
import { ref, onMounted, computed } from 'vue'
import { NButton, NCard, NModal, NForm, NFormItem, NInput, NSpace, NEmpty, NSpin, useMessage } from 'naive-ui'
import { useSeedStore } from '@/stores/seedStore'
import { useNovelStore } from '@/stores/novelStore'
import SeedCard from './SeedCard.vue'

const props = defineProps({
  projectId: { type: String, required: true }
})

const emit = defineEmits(['seedSelected'])

const seedStore = useSeedStore()
const novelStore = useNovelStore()
const message = useMessage()

const showCreateModal = ref(false)
const showGenModal = ref(false)
const showDetailModal = ref(false)
const detailSeed = ref(null)

const formValue = ref({
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
  styleTarget: ''
})

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
  await seedStore.createSeed(props.projectId, formValue.value)
  message.success('种子创建成功')
  showCreateModal.value = false
  formValue.value = { title: '', genre: '', logline: '', protagonist: '', desire: '', coreConflict: '', worldPressure: '', openingHook: '', emotionalPromise: '', differentiation: '', styleTarget: '' }
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

async function handleGenerate() {
  if (!genInput.value.idea.trim()) {
    message.warning('请输入你的创作想法')
    return
  }
  try {
    const created = await seedStore.generateSeeds(props.projectId, genInput.value)
    message.success(`AI 生成了 ${created.length} 个种子`)
    showGenModal.value = false
  } catch (e) {
    message.error('生成失败：' + e.message)
  }
}

function viewDetail(seed) {
  detailSeed.value = seed
  showDetailModal.value = true
}

// 从选中的种子创建创作圣经
async function createBibleFromSeed() {
  const seed = selectedSeed.value
  if (!seed) {
    message.warning('请先选择一个种子')
    return
  }
  await novelStore.saveBible(props.projectId, {
    premise: seed.logline,
    styleBible: seed.styleTarget || '',
    worldRules: seed.worldPressure || '',
    forbiddenDirections: []
  })
  message.success('创作圣经已创建')
}
</script>

<template>
  <div class="seed-workbench">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-lg font-semibold text-gray-700">创作种子</h3>
      <n-space>
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
      <div class="grid grid-cols-2 gap-3 text-sm">
        <div><span class="font-medium text-gray-500">题材：</span>{{ selectedSeed.genre }}</div>
        <div><span class="font-medium text-gray-500">风格：</span>{{ selectedSeed.styleTarget || '未指定' }}</div>
        <div class="col-span-2"><span class="font-medium text-gray-500">一句话：</span>{{ selectedSeed.logline }}</div>
        <div><span class="font-medium text-gray-500">主角：</span>{{ selectedSeed.protagonist }}</div>
        <div><span class="font-medium text-gray-500">欲望：</span>{{ selectedSeed.desire }}</div>
        <div class="col-span-2"><span class="font-medium text-gray-500">核心矛盾：</span>{{ selectedSeed.coreConflict }}</div>
        <div class="col-span-2"><span class="font-medium text-gray-500">开局钩子：</span>{{ selectedSeed.openingHook }}</div>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" type="primary" @click="createBibleFromSeed">
            以此创建创作圣经
          </n-button>
        </n-space>
      </template>
    </n-card>

    <!-- 种子列表 -->
    <n-empty v-if="seedStore.seeds.length === 0 && !seedStore.loading" description="还没有创作种子，点击上方按钮创建">
    </n-empty>

    <div class="grid grid-cols-2 gap-3" v-if="seedStore.seeds.length > 0">
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
          <n-button type="primary" :loading="seedStore.generating" @click="handleGenerate">生成</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 种子详情弹窗 -->
    <n-modal v-model:show="showDetailModal" title="种子详情" preset="card" style="width: 600px">
      <div v-if="detailSeed" class="space-y-3 text-sm">
        <div class="grid grid-cols-2 gap-2">
          <div><span class="font-medium text-gray-500">题材：</span>{{ detailSeed.genre }}</div>
          <div><span class="font-medium text-gray-500">来源：</span>{{ detailSeed.source === 'ai' ? 'AI 生成' : '手动创建' }}</div>
        </div>
        <div><span class="font-medium text-gray-500">一句话故事：</span>{{ detailSeed.logline }}</div>
        <div><span class="font-medium text-gray-500">主角：</span>{{ detailSeed.protagonist }}</div>
        <div><span class="font-medium text-gray-500">主角欲望：</span>{{ detailSeed.desire }}</div>
        <div><span class="font-medium text-gray-500">核心矛盾：</span>{{ detailSeed.coreConflict }}</div>
        <div><span class="font-medium text-gray-500">世界压力：</span>{{ detailSeed.worldPressure }}</div>
        <div><span class="font-medium text-gray-500">开局钩子：</span></div>
        <p class="text-gray-700 bg-gray-50 p-3 rounded whitespace-pre-wrap">{{ detailSeed.openingHook }}</p>
        <div><span class="font-medium text-gray-500">情绪价值：</span>{{ detailSeed.emotionalPromise }}</div>
        <div><span class="font-medium text-gray-500">差异化：</span>{{ detailSeed.differentiation }}</div>
        <div><span class="font-medium text-gray-500">风格目标：</span>{{ detailSeed.styleTarget }}</div>
      </div>
    </n-modal>
  </div>
</template>
