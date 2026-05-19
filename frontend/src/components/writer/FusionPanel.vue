<script setup>
import { ref, computed } from 'vue'
import { NModal, NButton, NTag, NInput, NSpace } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useCompareStore } from '@/stores/compareStore'
import { useProviderStore } from '@/stores/providerStore'
import { useWriterStore } from '@/stores/writerStore'

const props = defineProps({
  projectId: { type: String, required: true },
  chapterNum: { type: Number, required: true }
})

const emit = defineEmits(['close'])

const compareStore = useCompareStore()
const providerStore = useProviderStore()
const writerStore = useWriterStore()
const message = useAppMessage()

const fusing = ref(false)
const fusedContent = ref('')
const selectedProviderId = ref(null)

const sourceVersions = computed(() =>
  compareStore.comparisonVersions || []
)

const providerOptions = computed(() =>
  providerStore.providers.map(p => ({ label: `${p.name} (${p.model})`, value: p.id }))
)

async function handleFuse() {
  if (sourceVersions.value.length < 2) {
    message.warning('至少需要 2 个版本才能融合')
    return
  }
  fusing.value = true
  try {
    const fragments = sourceVersions.value.map((v, i) => ({
      label: providerStore.providers.find(p => p.id === v.sourceModelId)?.name || `模型${i + 1}`,
      content: v.content
    }))

    const result = await compareStore.fuseFragments(
      props.projectId,
      props.chapterNum,
      fragments,
      selectedProviderId.value
    )
    fusedContent.value = result
  } catch (e) {
    message.error('融合失败：' + e.message)
  } finally {
    fusing.value = false
  }
}

async function saveFusedVersion() {
  if (!fusedContent.value) return
  try {
    const chapter = writerStore.chapters.find(c => c.chapterNum === props.chapterNum)
    if (!chapter) { message.error('章节不存在'); return }
    await writerStore.createVersion(props.projectId, chapter.id, {
      chapterNum: props.chapterNum,
      title: chapter.title || `第 ${props.chapterNum} 章`,
      content: fusedContent.value,
      versionType: 'ai_candidate',
      sourceModelId: selectedProviderId.value || '',
      promptBrief: '多模型融合版'
    })
    await writerStore.loadVersions(props.projectId, chapter.id)
    message.success('融合版本已保存')
    emit('close')
  } catch (e) {
    message.error('保存失败：' + e.message)
  }
}
</script>

<template>
  <n-modal
    :show="true"
    preset="card"
    title="多模型融合"
    style="width: 800px; max-width: 90vw; max-height: 85vh;"
    @close="emit('close')"
  >
    <div class="flex gap-3" style="min-height: 400px">
      <!-- 左侧：源版本列表 -->
      <div class="w-48 flex-shrink-0 space-y-2 overflow-y-auto" style="max-height: 55vh">
        <div class="text-xs font-semibold text-gray-500 mb-1">源版本（{{ sourceVersions.length }}）</div>
        <div
          v-for="(v, i) in sourceVersions"
          :key="i"
          class="p-2 rounded border border-gray-200 text-xs"
        >
          <n-tag size="tiny" :bordered="false" class="mb-1">
            {{ providerStore.providers.find(p => p.id === v.sourceModelId)?.name || `未知` }}
          </n-tag>
          <div class="text-gray-600 line-clamp-3 mt-1">{{ v.content?.slice(0, 150) || '(空)' }}</div>
        </div>
      </div>

      <!-- 右侧：融合区域 -->
      <div class="flex-1 flex flex-col min-h-0">
        <div class="mb-2">
          <div class="text-xs font-semibold text-gray-500 mb-1">融合模型</div>
          <n-select
            v-model:value="selectedProviderId"
            :options="providerOptions"
            size="tiny"
            :placeholder="providerOptions[0]?.label || '选择模型'"
            style="width: 200px"
          />
        </div>

        <n-button
          size="small"
          type="primary"
          :loading="fusing"
          @click="handleFuse"
          :disabled="sourceVersions.length < 2"
          class="mb-2 self-start"
        >
          智能融合
        </n-button>

        <div class="flex-1 min-h-0">
          <n-input
            v-model:value="fusedContent"
            type="textarea"
            placeholder="融合后的内容将在此显示..."
            :rows="0"
            class="h-full"
            :input-props="{ style: 'min-height: 250px; font-size: 13px' }"
          />
        </div>

        <div class="flex justify-end gap-2 mt-2">
          <n-button size="small" @click="emit('close')">取消</n-button>
          <n-button size="small" type="primary" :disabled="!fusedContent" @click="saveFusedVersion">
            保存为候选版本
          </n-button>
        </div>
      </div>
    </div>
  </n-modal>
</template>

