<script setup>
import { ref, watch } from 'vue'
import {
  NAlert, NButton, NCheckbox, NForm, NFormItem, NInput, NInputNumber,
  NSelect, NSwitch,
} from 'naive-ui'
import { defaultBaseUrls, providerTypeOptions } from '@/api/ai/providerPresets'

const props = defineProps({ initial: { type: Object, default: null } })
const emit = defineEmits(['save', 'cancel'])

const defaults = {
  name: '',
  providerType: 'openai-compatible',
  baseURL: '',
  apiKey: '',
  model: '',
  enabled: true,
  stream: true,
  maxContextTokens: 200000,
  maxOutputTokens: 4096,
  temperature: 0.8,
  topP: 0.9,
  supportsJSON: true,
  supportsStreaming: true,
  notes: '',
  clearApiKey: false,
  clearBaseURL: false,
}
const form = ref({ ...defaults })

watch(() => props.initial, value => {
  form.value = value
    ? { ...defaults, ...value, apiKey: '', baseURL: '', clearApiKey: false, clearBaseURL: false }
    : { ...defaults }
}, { immediate: true })

function handleTypeChange(type) {
  form.value.providerType = type
  if (!props.initial) form.value.baseURL = defaultBaseUrls[type] || ''
}

function handleSubmit() {
  if (!form.value.name.trim() || !form.value.model.trim()) return
  emit('save', { ...form.value, name: form.value.name.trim(), model: form.value.model.trim() })
}
</script>

<template>
  <n-form :model="form" label-placement="top">
    <n-form-item label="名称" required>
      <n-input v-model:value="form.name" placeholder="如：联通云" />
    </n-form-item>
    <n-form-item label="Provider 类型" required>
      <n-select v-model:value="form.providerType" :options="providerTypeOptions" @update:value="handleTypeChange" />
    </n-form-item>
    <n-form-item label="模型 ID" required>
      <n-input v-model:value="form.model" placeholder="如：deepseek-v4-flash" />
    </n-form-item>

    <div class="secret-panel">
      <div class="secret-heading">本机私密配置</div>
      <n-alert v-if="initial?.hasKey" type="success" :bordered="false" class="mb-3">
        密钥已配置。留空会保留现有密钥，页面不会读取或回显原值。
      </n-alert>
      <n-form-item label="新 API Key">
        <n-input v-model:value="form.apiKey" type="password" show-password-on="click" placeholder="留空表示不更改" :disabled="form.clearApiKey" />
      </n-form-item>
      <n-checkbox v-if="initial?.hasKey" v-model:checked="form.clearApiKey">
        我确认清除当前 API Key
      </n-checkbox>

      <n-alert v-if="initial?.hasBaseURL" type="info" :bordered="false" class="my-3">
        Base URL 已配置。留空会保留现有地址，页面不会读取或回显原值。
      </n-alert>
      <n-form-item label="新 Base URL">
        <n-input v-model:value="form.baseURL" placeholder="留空表示不更改" :disabled="form.clearBaseURL" />
      </n-form-item>
      <n-checkbox v-if="initial?.hasBaseURL" v-model:checked="form.clearBaseURL">
        我确认清除当前 Base URL
      </n-checkbox>
    </div>

    <n-form-item label="备注" class="mt-4">
      <n-input v-model:value="form.notes" type="textarea" rows="2" placeholder="仅保存公开说明，不填写密钥" />
    </n-form-item>
    <div class="settings-grid">
      <n-form-item label="启用"><n-switch v-model:value="form.enabled" /></n-form-item>
      <n-form-item label="流式输出"><n-switch v-model:value="form.stream" /></n-form-item>
      <n-form-item label="支持 JSON"><n-switch v-model:value="form.supportsJSON" /></n-form-item>
      <n-form-item label="支持流式"><n-switch v-model:value="form.supportsStreaming" /></n-form-item>
      <n-form-item label="Temperature"><n-input-number v-model:value="form.temperature" :min="0" :max="2" :step="0.1" /></n-form-item>
      <n-form-item label="Top P"><n-input-number v-model:value="form.topP" :min="0" :max="1" :step="0.1" /></n-form-item>
      <n-form-item label="上下文 Tokens"><n-input-number v-model:value="form.maxContextTokens" :min="1000" :step="1000" /></n-form-item>
      <n-form-item label="输出 Tokens"><n-input-number v-model:value="form.maxOutputTokens" :min="256" :step="256" /></n-form-item>
    </div>
  </n-form>
  <div class="form-actions">
    <n-button @click="emit('cancel')">取消</n-button>
    <n-button type="primary" @click="handleSubmit">保存</n-button>
  </div>
</template>

<style scoped>
.secret-panel { padding: 16px; border: 1px solid #ddd3bd; border-radius: 10px; background: #fbf8f0; }
.secret-heading { margin-bottom: 12px; color: #3c372f; font-weight: 650; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.form-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }
@media (max-width: 620px) { .settings-grid { grid-template-columns: 1fr; } }
</style>
