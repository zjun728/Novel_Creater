<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  NAlert, NButton, NForm, NFormItem, NInput, NInputNumber,
  NSelect, NSwitch,
} from 'naive-ui'
import { defaultBaseUrls, providerTypeOptions } from '@/api/ai/providerPresets'

const props = defineProps({
  initial: { type: Object, default: null },
  saving: { type: Boolean, default: false },
})
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
}
const form = ref({ ...defaults })
const validationError = ref('')
const editing = computed(() => Boolean(props.initial?.id))

function clearSensitiveFields() {
  form.value.apiKey = ''
  form.value.baseURL = ''
}

watch(() => props.initial, value => {
  validationError.value = ''
  form.value = value
    ? { ...defaults, ...value, apiKey: '', baseURL: '' }
    : { ...defaults }
}, { immediate: true })

function handleTypeChange(type) {
  form.value.providerType = type
  if (!props.initial) form.value.baseURL = defaultBaseUrls[type] || ''
}

function handleSubmit() {
  if (props.saving) return
  validationError.value = ''
  if (!form.value.name.trim() || !form.value.model.trim()) {
    validationError.value = '请填写名称和模型 ID。'
    return
  }
  if (!editing.value && (!form.value.apiKey.trim() || !form.value.baseURL.trim())) {
    validationError.value = '新增 Provider 必须填写 API Key 与 Base URL。'
    return
  }
  const submitted = {
    ...form.value,
    name: form.value.name.trim(),
    model: form.value.model.trim(),
  }
  try {
    emit('save', submitted)
  } finally {
    clearSensitiveFields()
  }
}

function handleCancel() {
  clearSensitiveFields()
  emit('cancel')
}

onBeforeUnmount(clearSensitiveFields)
</script>

<template>
  <n-form :model="form" label-placement="top">
    <n-form-item label="名称" required>
      <n-input v-model:value="form.name" :disabled="saving" placeholder="如：联通云" />
    </n-form-item>
    <n-form-item label="Provider 类型" required>
      <n-select v-model:value="form.providerType" :options="providerTypeOptions" :disabled="saving || editing" @update:value="handleTypeChange" />
      <small v-if="editing" class="immutable-hint">Provider 类型创建后不可更改；如需换协议，请新建 Provider 后重新绑定。</small>
    </n-form-item>
    <n-form-item label="模型 ID" required>
      <n-input v-model:value="form.model" :disabled="saving" placeholder="如：deepseek-v4-flash" />
    </n-form-item>

    <div class="secret-panel">
      <div class="secret-heading">本机私密配置</div>
      <n-alert v-if="initial?.hasKey" type="success" :bordered="false" class="mb-3">
        密钥已配置。留空会保留现有密钥，页面不会读取或回显原值。
      </n-alert>
      <n-form-item :label="editing ? '新 API Key' : 'API Key'" :required="!editing">
        <n-input
          v-model:value="form.apiKey"
          type="password"
          show-password-on="click"
          autocomplete="new-password"
          :disabled="saving"
          :placeholder="editing ? '留空保留现有密钥' : '仅在本次请求中提交给后端'"
        />
      </n-form-item>

      <n-alert v-if="initial?.hasBaseURL" type="info" :bordered="false" class="my-3">
        Base URL 已配置。留空会保留现有地址，页面不会读取或回显原值。
      </n-alert>
      <n-form-item :label="editing ? '新 Base URL' : 'Base URL'" :required="!editing">
        <n-input
          v-model:value="form.baseURL"
          :disabled="saving"
          :placeholder="editing ? '留空保留现有地址' : '如：https://provider.example/v1'"
        />
      </n-form-item>
    </div>

    <n-alert v-if="validationError" type="error" class="mt-4" aria-live="assertive">
      {{ validationError }}
    </n-alert>

    <n-form-item label="备注" class="mt-4">
      <n-input v-model:value="form.notes" type="textarea" rows="2" :disabled="saving" placeholder="仅保存公开说明，不填写密钥" />
    </n-form-item>
    <div class="settings-grid">
      <n-form-item label="启用"><n-switch v-model:value="form.enabled" :disabled="saving" /></n-form-item>
      <n-form-item label="流式输出"><n-switch v-model:value="form.stream" :disabled="saving" /></n-form-item>
      <n-form-item label="支持 JSON"><n-switch v-model:value="form.supportsJSON" :disabled="saving" /></n-form-item>
      <n-form-item label="支持流式"><n-switch v-model:value="form.supportsStreaming" :disabled="saving" /></n-form-item>
      <n-form-item label="Temperature"><n-input-number v-model:value="form.temperature" :disabled="saving" :min="0" :max="2" :step="0.1" /></n-form-item>
      <n-form-item label="Top P"><n-input-number v-model:value="form.topP" :disabled="saving" :min="0" :max="1" :step="0.1" /></n-form-item>
      <n-form-item label="上下文 Tokens"><n-input-number v-model:value="form.maxContextTokens" :disabled="saving" :min="1000" :step="1000" /></n-form-item>
      <n-form-item label="输出 Tokens"><n-input-number v-model:value="form.maxOutputTokens" :disabled="saving" :min="256" :step="256" /></n-form-item>
    </div>
  </n-form>
  <div class="form-actions">
    <n-button :disabled="saving" @click="handleCancel">取消</n-button>
    <n-button type="primary" :loading="saving" @click="handleSubmit">保存</n-button>
  </div>
</template>

<style scoped>
.secret-panel { padding: 16px; border: 1px solid #ddd3bd; border-radius: 10px; background: #fbf8f0; }
.secret-heading { margin-bottom: 12px; color: #3c372f; font-weight: 650; }
.immutable-hint { display: block; margin-top: 7px; color: #817667; line-height: 1.55; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.form-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }
@media (max-width: 620px) { .settings-grid { grid-template-columns: 1fr; } }
</style>
