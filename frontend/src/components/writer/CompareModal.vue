<script setup>
import { ref, computed } from 'vue'
import { NModal, NButton, NCheckbox, NCard, NTag, NProgress, NSpace, useMessage } from 'naive-ui'
import { useCompareStore } from '@/stores/compareStore'
import { useProviderStore } from '@/stores/providerStore'
import { buildWritingContext } from '@/utils/contextBuilder'
import { useNovelStore } from '@/stores/novelStore'

const props = defineProps({
  projectId: { type: String, required: true },
  chapterNum: { type: Number, required: true }
})

const emit = defineEmits(['close'])

const compareStore = useCompareStore()
const providerStore = useProviderStore()
const novelStore = useNovelStore()
const message = useMessage()

const step = ref('select') // 'select' | 'running' | 'done'
const selectedModels = ref([])

const writableProviders = computed(() =>
  providerStore.providers.filter(p => p.apiKey && p.model)
)

const doneCount = computed(() =>
  Object.values(compareStore.runningJobs).filter(j => j.done).length
)

const totalCount = computed(() => Object.keys(compareStore.runningJobs).length)

function toggleModel(providerId) {
  const idx = selectedModels.value.indexOf(providerId)
  if (idx >= 0) {
    selectedModels.value.splice(idx, 1)
  } else {
    selectedModels.value.push(providerId)
  }
}

async function startComparison() {
  if (selectedModels.value.length < 2) {
    message.warning('请至少选择 2 个模型')
    return
  }
  step.value = 'running'
  const context = buildWritingContext(novelStore, props.chapterNum)
  try {
    await compareStore.startComparison(
      props.projectId,
      props.chapterNum,
      context.context,
      selectedModels.value
    )
    step.value = 'done'
  } catch (e) {
    message.error('对比失败：' + e.message)
    step.value = 'select'
  }
}

function done() {
  compareStore.clearComparison()
  emit('close')
}
</script>

<template>
  <n-modal
    :show="true"
    preset="card"
    title="多模型试写对比"
    style="width: 90vw; max-width: 960px; max-height: 85vh;"
    @close="done"
  >
    <!-- Step 1: 选择模型 -->
    <div v-if="step === 'select'">
      <p class="text-sm text-gray-500 mb-4">选择 2 个或更多模型，系统将用相同的上下文并发生成章节</p>
      <div class="grid grid-cols-2 gap-2 mb-4">
        <div
          v-for="p in writableProviders"
          :key="p.id"
          :class="[
            'flex items-center gap-2 p-2 rounded border cursor-pointer transition-colors',
            selectedModels.includes(p.id) ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
          ]"
          @click="toggleModel(p.id)"
        >
          <n-checkbox :checked="selectedModels.includes(p.id)" />
          <div class="text-sm">
            <div class="font-medium text-gray-700">{{ p.name }}</div>
            <div class="text-xs text-gray-400">{{ p.model }}</div>
          </div>
        </div>
      </div>
      <div v-if="!writableProviders.length" class="text-center text-gray-400 py-8 text-sm">
        请先在设置中配置至少 2 个模型
      </div>
      <div class="flex justify-end gap-2">
        <n-button size="small" @click="emit('close')">取消</n-button>
        <n-button size="small" type="primary" :disabled="selectedModels.length < 2" @click="startComparison">
          开始对比（{{ selectedModels.length }} 个模型）
        </n-button>
      </div>
    </div>

    <!-- Step 2: 运行中 / 完成 -->
    <div v-else>
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <n-tag :type="step === 'running' ? 'info' : 'success'" size="small" :bordered="false">
            {{ step === 'running' ? '生成中...' : '已完成' }}
          </n-tag>
          <span class="text-sm text-gray-500">{{ doneCount }} / {{ totalCount }} 完成</span>
        </div>
      </div>

      <div class="flex gap-3 overflow-x-auto pb-3" style="min-height: 300px">
        <div
          v-for="mid in selectedModels"
          :key="mid"
          class="flex-shrink-0 rounded border p-3"
          style="width: 280px; max-height: 55vh; overflow-y: auto"
        >
          <div class="flex items-center justify-between mb-2">
            <n-tag size="tiny" :type="compareStore.runningJobs[mid]?.error ? 'error' : compareStore.runningJobs[mid]?.done ? 'success' : 'info'">
              {{ providerStore.providers.find(p => p.id === mid)?.name || mid }}
            </n-tag>
          </div>

          <div v-if="compareStore.runningJobs[mid]?.error" class="text-xs text-red-500">
            {{ compareStore.runningJobs[mid].error }}
          </div>

          <div
            v-else-if="compareStore.runningJobs[mid]?.content"
            class="text-xs text-gray-700 whitespace-pre-wrap leading-relaxed"
          >
            {{ compareStore.runningJobs[mid].content }}
          </div>

          <div v-else-if="compareStore.runningJobs[mid]?.streaming" class="text-xs text-gray-400 animate-pulse">
            正在生成...
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-3">
        <n-button v-if="step === 'running'" size="small" @click="compareStore.cancelAll()">取消</n-button>
        <n-button size="small" type="primary" @click="done">
          {{ step === 'done' ? '完成' : '关闭' }}
        </n-button>
      </div>
    </div>
  </n-modal>
</template>
