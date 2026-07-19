<script setup>
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NDynamicTags,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSelect,
} from 'naive-ui'
import { computed, reactive, ref, watch } from 'vue'

import { useCorpusStore } from '@/stores/corpusStore'
import { generateId } from '@/utils/id'

const props = defineProps({
  show: { type: Boolean, default: false },
  source: { type: Object, default: null },
})
const emit = defineEmits(['update:show', 'imported'])
const store = useCorpusStore()
const submitting = ref(false)
const discovering = ref(false)
const error = ref('')
const form = reactive({
  relativePath: null,
  displayName: '',
  referenceTags: [],
  notes: '',
  createDistinctSource: false,
})

const fileOptions = computed(() => (store.discovery?.items || []).map(item => ({
  label: `${item.relativePath} · ${formatBytes(item.byteSize)}`,
  value: item.relativePath,
  disabled: item.preflightStatus !== 'eligible',
})))
const modeLabel = computed(() => (
  props.source ? `作为“${props.source.name}”的新版本导入` : '导入为新的受管语料'
))

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`
}

function reset() {
  form.relativePath = null
  form.displayName = props.source?.name || ''
  form.referenceTags = [...(props.source?.referenceTags || [])]
  form.notes = ''
  form.createDistinctSource = false
  error.value = ''
}

async function discover() {
  discovering.value = true
  error.value = ''
  try {
    await store.discover({ limit: 200 })
  } catch (failure) {
    error.value = failure?.message || '无法读取可导入文件清单'
  } finally {
    discovering.value = false
  }
}

async function submit() {
  if (!form.relativePath) {
    error.value = '请选择一个已发现的 TXT 文件'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const result = await store.importSource({
      idempotencyKey: generateId(),
      relativePath: form.relativePath,
      sourceId: props.source?.id,
      createDistinctSource: props.source ? false : form.createDistinctSource,
      displayName: form.displayName.trim() || undefined,
      referenceTags: form.referenceTags,
      notes: form.notes.trim(),
    })
    if (result.status !== 'succeeded') {
      throw new Error('导入未完成，请检查文件格式后重新发起')
    }
    emit('imported', result)
    emit('update:show', false)
  } catch (failure) {
    error.value = failure?.message || '语料导入失败'
  } finally {
    submitting.value = false
  }
}

watch(
  () => props.show,
  show => {
    if (!show) return
    reset()
    void discover()
  },
)
</script>

<template>
  <n-modal :show="show" @update:show="emit('update:show', $event)">
    <n-card class="import-card" :bordered="false" role="dialog" aria-modal="true">
      <template #header>
        <div class="dialog-heading">
          <span>CORPUS INTAKE</span>
          <strong>{{ modeLabel }}</strong>
        </div>
      </template>

      <n-alert v-if="error" type="error" class="dialog-alert">{{ error }}</n-alert>
      <n-form label-placement="top" @submit.prevent="submit">
        <n-form-item label="来源文件">
          <n-select
            v-model:value="form.relativePath"
            filterable
            :loading="discovering"
            :options="fileOptions"
            placeholder="从受控发现清单中选择"
          />
        </n-form-item>
        <n-form-item label="馆藏名称">
          <n-input
            v-model:value="form.displayName"
            maxlength="300"
            show-count
            placeholder="例如：北境卷叙事样本"
          />
        </n-form-item>
        <n-form-item label="参考标签">
          <n-dynamic-tags v-model:value="form.referenceTags" :max="12" />
        </n-form-item>
        <n-form-item label="编目备注">
          <n-input
            v-model:value="form.notes"
            type="textarea"
            maxlength="1000"
            show-count
            :autosize="{ minRows: 3, maxRows: 6 }"
            placeholder="记录适用场景、版本差异或使用边界"
          />
        </n-form-item>
        <n-checkbox
          v-if="!source"
          v-model:checked="form.createDistinctSource"
          class="distinct-check"
        >
          即使内容相同，也创建独立逻辑来源
        </n-checkbox>
        <p class="privacy-note">
          仅提交相对来源标签与编目字段；浏览器不会上传原始字节或受管目录。
        </p>
        <div class="dialog-actions">
          <n-button @click="emit('update:show', false)">取消</n-button>
          <n-button secondary :loading="discovering" @click="discover">刷新清单</n-button>
          <n-button type="primary" :loading="submitting" @click="submit">确认导入</n-button>
        </div>
      </n-form>
    </n-card>
  </n-modal>
</template>

<style scoped>
.import-card { width: min(600px, calc(100vw - 28px)); color: #302a23; background: #fffdf8; }
.dialog-heading { display: grid; gap: 5px; }
.dialog-heading span { color: #957557; font: 750 9px Georgia, serif; letter-spacing: .16em; }
.dialog-heading strong { font: 650 23px 'Noto Serif SC', 'Songti SC', Georgia, serif; }
.dialog-alert { margin-bottom: 14px; }
.distinct-check { margin-bottom: 10px; }
.privacy-note { margin: 10px 0 18px; color: #827568; font-size: 11px; line-height: 1.65; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
