<script setup>
import { ref, watch } from 'vue'
import { NButton, NForm, NFormItem, NInput, NSelect, NSpace, NSwitch, NInputNumber } from 'naive-ui'
import { providerTypeOptions, defaultBaseUrls } from '@/api/ai/providerPresets'

const props = defineProps({
  initial: { type: Object, default: null }
})

const emit = defineEmits(['save', 'cancel'])

const form = ref({
  name: '',
  providerType: 'openai-compatible',
  baseURL: '',
  apiKey: '',
  model: '',
  stream: true,
  maxContextTokens: 200000,
  maxOutputTokens: 4096,
  temperature: 0.8,
  topP: 0.9,
  supportsJSON: true,
  supportsStreaming: true,
  notes: ''
})

const defaults = {
  name: '',
  providerType: 'openai-compatible',
  baseURL: '',
  apiKey: '',
  model: '',
  stream: true,
  maxContextTokens: 200000,
  maxOutputTokens: 4096,
  temperature: 0.8,
  topP: 0.9,
  supportsJSON: true,
  supportsStreaming: true,
  notes: ''
}

watch(() => props.initial, (val) => {
  if (val) {
    form.value = { ...defaults, ...val, apiKey: '' }
  } else {
    form.value = { ...defaults }
  }
}, { immediate: true })

function handleTypeChange(type) {
  form.value.providerType = type
  if (!props.initial) {
    form.value.baseURL = defaultBaseUrls[type] || ''
  }
}

function handleSubmit() {
  if (!form.value.name.trim()) return
  if (!form.value.model.trim()) return
  emit('save', { ...form.value })
}
</script>

<template>
  <n-form :model="form">
    <n-form-item label="名称" required>
      <n-input v-model:value="form.name" placeholder="如：Claude 主创、DeepSeek 脑洞" />
    </n-form-item>
    <n-form-item label="Provider 类型" required>
      <n-select
        v-model:value="form.providerType"
        :options="providerTypeOptions"
        @update:value="handleTypeChange"
      />
    </n-form-item>
    <n-form-item label="Base URL">
      <n-input v-model:value="form.baseURL" placeholder="默认使用 API 供应商的官方地址" />
    </n-form-item>
    <n-form-item label="模型 ID" required>
      <n-input v-model:value="form.model" placeholder="如：claude-sonnet-4-20250514、gpt-4o" />
    </n-form-item>
    <n-form-item label="API Key">
      <n-input
        v-model:value="form.apiKey"
        type="password"
        show-password-on="click"
        :placeholder="props.initial?.hasApiKey ? '已配置；留空则保留现有 API Key' : '输入 API Key'"
      />
    </n-form-item>
    <n-form-item label="备注">
      <n-input v-model:value="form.notes" type="textarea" rows="2" placeholder="可选备注信息" />
    </n-form-item>
    <div class="grid grid-cols-2 gap-4">
      <n-form-item label="流式输出">
        <n-switch v-model:value="form.stream" />
      </n-form-item>
      <n-form-item label="支持 JSON">
        <n-switch v-model:value="form.supportsJSON" />
      </n-form-item>
      <n-form-item label="Temperature">
        <n-input-number v-model:value="form.temperature" :min="0" :max="2" :step="0.1" />
      </n-form-item>
      <n-form-item label="Top P">
        <n-input-number v-model:value="form.topP" :min="0" :max="1" :step="0.1" />
      </n-form-item>
      <n-form-item label="最大上下文 Tokens">
        <n-input-number v-model:value="form.maxContextTokens" :min="1000" :step="1000" />
      </n-form-item>
      <n-form-item label="最大输出 Tokens">
        <n-input-number v-model:value="form.maxOutputTokens" :min="256" :step="256" />
      </n-form-item>
    </div>
  </n-form>
  <div class="flex justify-end gap-2 mt-6">
    <n-button @click="emit('cancel')">取消</n-button>
    <n-button type="primary" @click="handleSubmit">保存</n-button>
  </div>
</template>
