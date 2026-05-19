<script setup>
import { computed, ref } from 'vue'
import { NButton, NCard, NEmpty, NInput, NSpin, NTag } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useStyleTrialStore } from '@/stores/styleTrialStore'

const props = defineProps({
  projectId: { type: String, required: true },
  seed: { type: Object, required: true }
})

const emit = defineEmits(['applyStyle'])

const message = useAppMessage()
const styleTrialStore = useStyleTrialStore()

const selectedPresetIds = ref(['fast-web', 'cold-restraint', 'suspense-pressure'])
const sampleName = ref('自定义参考风格')
const sampleText = ref('')

const canGenerate = computed(() =>
  selectedPresetIds.value.length > 0 || sampleText.value.trim().length > 80
)

function togglePreset(id) {
  if (selectedPresetIds.value.includes(id)) {
    selectedPresetIds.value = selectedPresetIds.value.filter(item => item !== id)
  } else {
    selectedPresetIds.value.push(id)
  }
}

async function handleGenerate() {
  if (!canGenerate.value) {
    message.warning('请选择至少一个默认风格，或粘贴一段 80 字以上的参考文本')
    return
  }

  try {
    await styleTrialStore.generateTrials(props.projectId, props.seed, {
      presetIds: selectedPresetIds.value,
      sampleName: sampleName.value,
      sampleText: sampleText.value.trim()
    })
    message.success('风格试写已生成')
  } catch (e) {
    message.error('风格试写失败：' + e.message)
  }
}

function applyStyle(trial) {
  styleTrialStore.selectTrial(trial)
  emit('applyStyle', {
    trial,
    styleBible: styleTrialStore.buildStyleBible(trial)
  })
  message.success(`已将「${trial.name}」设为创作圣经风格基准`)
}
</script>

<template>
  <n-card title="风格试写对比" size="small" class="mb-4">
    <div class="space-y-5">
      <div>
        <div class="text-sm text-gray-500 mb-3">
          在正式创建创作圣经前，用同一个开局场景试写不同风格，先确认这本书的叙事味道。
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
          <button
            v-for="preset in styleTrialStore.presets"
            :key="preset.id"
            type="button"
            class="text-left rounded border px-3 py-2 transition-colors"
            :class="selectedPresetIds.includes(preset.id)
              ? 'border-green-400 bg-green-50 text-green-800'
              : 'border-gray-200 bg-white hover:border-gray-300'"
            @click="togglePreset(preset.id)"
          >
            <div class="text-sm font-medium">{{ preset.name }}</div>
            <div class="mt-1 text-xs leading-5 text-gray-500">{{ preset.description }}</div>
          </button>
        </div>
      </div>

      <div class="rounded border border-dashed border-gray-300 bg-gray-50 p-3">
        <div class="flex items-center justify-between gap-3 mb-2">
          <div>
            <div class="text-sm font-medium text-gray-700">自定义风格参考</div>
            <div class="text-xs text-gray-400">可粘贴你喜欢的示例文本，AI 会提取风格指纹，不照搬内容。</div>
          </div>
          <n-input
            v-model:value="sampleName"
            size="small"
            placeholder="示例名称"
            style="width: 180px"
          />
        </div>
        <n-input
          v-model:value="sampleText"
          type="textarea"
          rows="5"
          placeholder="粘贴 500-3000 字参考片段。可以是你喜欢的叙事质感、对话节奏、氛围写法。"
        />
      </div>

      <div class="flex justify-end gap-2">
        <n-button size="small" @click="styleTrialStore.clearTrials">
          清空对比
        </n-button>
        <n-button
          size="small"
          type="primary"
          :loading="styleTrialStore.generating"
          :disabled="!canGenerate"
          @click="handleGenerate"
        >
          生成风格试写
        </n-button>
      </div>

      <n-spin :show="styleTrialStore.generating">
        <div
          v-if="styleTrialStore.sampleAnalysis?.fingerprint?.length"
          class="rounded bg-amber-50 border border-amber-100 p-3"
        >
          <div class="text-sm font-medium text-amber-900 mb-2">参考示例风格指纹</div>
          <div class="flex flex-wrap gap-1.5">
            <n-tag
              v-for="item in styleTrialStore.sampleAnalysis.fingerprint"
              :key="item"
              size="small"
              :bordered="false"
              type="warning"
            >
              {{ item }}
            </n-tag>
          </div>
          <div class="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs leading-5 text-amber-900">
            <div v-if="styleTrialStore.sampleAnalysis.usableAdvice">
              <span class="font-medium">可借鉴：</span>{{ styleTrialStore.sampleAnalysis.usableAdvice }}
            </div>
            <div v-if="styleTrialStore.sampleAnalysis.risk">
              <span class="font-medium">风险：</span>{{ styleTrialStore.sampleAnalysis.risk }}
            </div>
          </div>
        </div>

        <n-empty
          v-if="!styleTrialStore.trials.length && !styleTrialStore.generating"
          size="small"
          description="还没有风格试写结果"
        />

        <div v-if="styleTrialStore.trials.length" class="grid grid-cols-1 xl:grid-cols-2 gap-3">
          <div
            v-for="trial in styleTrialStore.trials"
            :key="trial.id"
            class="rounded border bg-white p-4"
            :class="styleTrialStore.selectedTrial?.id === trial.id ? 'border-green-400' : 'border-gray-200'"
          >
            <div class="flex items-start justify-between gap-3">
              <div>
                <div class="font-semibold text-gray-800">{{ trial.name }}</div>
                <div class="mt-1 text-xs leading-5 text-gray-500">{{ trial.positioning }}</div>
              </div>
              <n-button size="tiny" type="primary" @click="applyStyle(trial)">
                设为主风格
              </n-button>
            </div>

            <div class="mt-3 grid grid-cols-3 gap-2 text-center">
              <div class="rounded bg-gray-50 py-2">
                <div class="text-[11px] text-gray-400">适配</div>
                <div class="font-semibold text-gray-800">{{ trial.suitabilityScore }}</div>
              </div>
              <div class="rounded bg-gray-50 py-2">
                <div class="text-[11px] text-gray-400">稳定</div>
                <div class="font-semibold text-gray-800">{{ trial.continuationStability }}</div>
              </div>
              <div class="rounded bg-gray-50 py-2">
                <div class="text-[11px] text-gray-400">想象</div>
                <div class="font-semibold text-gray-800">{{ trial.imaginationSpace }}</div>
              </div>
            </div>

            <div v-if="trial.styleFingerprint?.length" class="mt-3 flex flex-wrap gap-1">
              <n-tag
                v-for="item in trial.styleFingerprint"
                :key="item"
                size="tiny"
                :bordered="false"
              >
                {{ item }}
              </n-tag>
            </div>

            <div class="mt-3 rounded bg-gray-50 p-3 text-sm leading-7 text-gray-700 whitespace-pre-wrap max-h-72 overflow-y-auto">
              {{ trial.excerpt }}
            </div>

            <div class="mt-3 text-xs leading-5 text-gray-500">
              <div v-if="trial.recommendation">
                <span class="font-medium text-gray-700">建议：</span>{{ trial.recommendation }}
              </div>
              <div v-if="trial.risks?.length" class="mt-1">
                <span class="font-medium text-gray-700">风险：</span>{{ trial.risks.join('；') }}
              </div>
            </div>
          </div>
        </div>
      </n-spin>
    </div>
  </n-card>
</template>

