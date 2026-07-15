<script setup>
import { ref, computed } from 'vue'
import { NModal, NButton, NCheckbox, NTag } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useCompareStore } from '@/stores/compareStore'
import { useProviderStore } from '@/stores/providerStore'

const props = defineProps({
  projectId: { type: String, required: true },
  chapterNum: { type: Number, required: true },
  context: { type: Object, default: () => ({}) },
  beatPlan: { type: String, default: '' }
})

const emit = defineEmits(['close'])

const compareStore = useCompareStore()
const providerStore = useProviderStore()
const message = useAppMessage()

const step = ref('select')
const selectedModels = ref([])

const writableProviders = computed(() =>
  providerStore.availableProviders
)

const doneCount = computed(() =>
  Object.values(compareStore.runningJobs).filter(job => job.done).length
)

const totalCount = computed(() => Object.keys(compareStore.runningJobs).length)

const canStart = computed(() => Boolean(props.beatPlan?.trim()))

function toggleModel(providerId) {
  const idx = selectedModels.value.indexOf(providerId)
  if (idx >= 0) selectedModels.value.splice(idx, 1)
  else selectedModels.value.push(providerId)
}

async function startComparison() {
  if (!canStart.value) {
    message.warning('请先确认本章小纲后再开始多模型对比')
    return
  }
  if (selectedModels.value.length < 2) {
    message.warning('请至少选择 2 个模型')
    return
  }
  step.value = 'running'
  try {
    await compareStore.startComparison(
      props.projectId,
      props.chapterNum,
      props.context,
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
    <div v-if="step === 'select'">
      <p class="text-sm text-gray-500 mb-3">选择 2 个或更多模型，系统会用当前确认小纲和写字台完整上下文并发生成章节候选。</p>
      <div class="rounded border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 mb-3">
        已接入当前确认小纲、设定库、分卷上下文和未完成纠偏任务。
      </div>
      <div class="grid grid-cols-2 gap-2 mb-4">
        <div
          v-for="provider in writableProviders"
          :key="provider.id"
          :class="[
            'flex items-center gap-2 p-2 rounded border cursor-pointer transition-colors',
            selectedModels.includes(provider.id) ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
          ]"
          @click="toggleModel(provider.id)"
        >
          <n-checkbox :checked="selectedModels.includes(provider.id)" />
          <div class="text-sm">
            <div class="font-medium text-gray-700">{{ provider.name }}</div>
            <div class="text-xs text-gray-400">{{ provider.model }}</div>
          </div>
        </div>
      </div>
      <div v-if="!writableProviders.length" class="text-center text-gray-400 py-8 text-sm">
        请先在设置中配置至少 2 个模型
      </div>
      <div class="flex justify-end gap-2">
        <n-button size="small" @click="emit('close')">取消</n-button>
        <n-button size="small" type="primary" :disabled="!canStart || selectedModels.length < 2" @click="startComparison">
          开始对比（{{ selectedModels.length }} 个模型）
        </n-button>
      </div>
    </div>

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
          v-for="modelId in selectedModels"
          :key="modelId"
          class="flex-shrink-0 rounded border p-3"
          style="width: 280px; max-height: 55vh; overflow-y: auto"
        >
          <div class="flex items-center justify-between mb-2">
            <n-tag size="tiny" :type="compareStore.runningJobs[modelId]?.error ? 'error' : compareStore.runningJobs[modelId]?.done ? 'success' : 'info'">
              {{ providerStore.providers.find(provider => provider.id === modelId)?.name || modelId }}
            </n-tag>
          </div>

          <div v-if="compareStore.runningJobs[modelId]?.error" class="text-xs text-red-500">
            {{ compareStore.runningJobs[modelId].error }}
          </div>

          <div
            v-else-if="compareStore.runningJobs[modelId]?.content"
            class="text-xs text-gray-700 whitespace-pre-wrap leading-relaxed"
          >
            {{ compareStore.runningJobs[modelId].content }}
          </div>

          <div v-else-if="compareStore.runningJobs[modelId]?.streaming" class="text-xs text-gray-400 animate-pulse">
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
