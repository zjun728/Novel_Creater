<script setup>
import { computed, ref, watch } from 'vue'

defineOptions({ name: 'FinalizationValueEditor' })
const props = defineProps({
  modelValue: { required: true },
  disabled: { type: Boolean, default: false },
  path: { type: String, default: '事实内容' },
})
const emit = defineEmits(['update:modelValue', 'pending-change'])
const types = { string: '文字', number: '数字', boolean: '是 / 否', null: '空值', object: '字段组', array: '列表' }
const kind = computed(() => props.modelValue === null ? 'null' : Array.isArray(props.modelValue) ? 'array' : typeof props.modelValue)
const fields = computed(() => kind.value === 'object' ? Object.keys(props.modelValue) : kind.value === 'array' ? props.modelValue.map((_, index) => String(index)) : [])
const numberText = ref('')
const numberError = ref('')
const newField = ref('')
const fieldError = ref('')
const childPending = ref(new Map())
const pending = computed(() => Boolean(numberError.value || newField.value || [...childPending.value.values()].some(Boolean)))
const fieldNames = { severity: '严重程度', condition: '具体情况', result: '结果', status: '状态', cause: '原因', location: '位置', description: '说明', amount: '数量', name: '名称' }
const fieldLabel = key => fieldNames[key] ? `${fieldNames[key]}（${key}）` : key

watch(pending, value => emit('pending-change', value), { immediate: true, flush: 'sync' })
watch(() => props.modelValue, value => {
  if (typeof value === 'number' && (!numberText.value || Number(numberText.value) !== value)) {
    numberText.value = String(value)
    numberError.value = ''
  }
}, { immediate: true })
watch(kind, () => {
  numberText.value = kind.value === 'number' ? String(props.modelValue) : ''
  numberError.value = ''; newField.value = ''; fieldError.value = ''; childPending.value.clear()
})
watch(fields, keys => {
  for (const key of childPending.value.keys()) if (!keys.includes(key)) childPending.value.delete(key)
})

function replace(value) {
  if (!props.disabled) emit('update:modelValue', value)
}
function changeType(value) {
  if (props.disabled || !Object.hasOwn(types, value)) return
  replace(({ string: '', number: 0, boolean: false, null: null, object: {}, array: [] })[value])
}
function updateNumber(value) {
  if (props.disabled) return
  numberText.value = value
  if (!/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value) || !Number.isFinite(Number(value))) {
    numberError.value = '请填写完整、有效的数字。'
    return
  }
  numberError.value = ''
  replace(Number(value))
}
function updateChild(key, value) {
  if (props.disabled) return
  if (kind.value === 'array') {
    const next = [...props.modelValue]; next[Number(key)] = value; replace(next)
  } else replace({ ...props.modelValue, [key]: value })
}
function removeChild(key) {
  if (props.disabled) return
  childPending.value.delete(key)
  if (kind.value === 'array') {
    const next = [...props.modelValue]; next.splice(Number(key), 1); replace(next)
  } else {
    const next = { ...props.modelValue }; delete next[key]; replace(next)
  }
}
function addField() {
  if (props.disabled) return
  const key = newField.value.trim()
  if (!key) { fieldError.value = '请填写字段名称。'; return }
  if (Object.hasOwn(props.modelValue, key)) { fieldError.value = '已有同名字段，请修改名称。'; return }
  newField.value = ''; fieldError.value = ''
  replace({ ...props.modelValue, [key]: '' })
}
function updateNewField(value) {
  if (!props.disabled) { newField.value = value; fieldError.value = '' }
}
</script>

<template>
  <div class="fact-value-editor" :data-value-path="path">
    <label class="value-type"><span>内容类型</span><select :value="kind" :disabled="disabled" :aria-label="`${path}：类型`" @change="changeType($event.target.value)"><option v-for="(title, type) in types" :key="type" :value="type">{{ title }}</option></select></label>
    <textarea v-if="kind === 'string'" :value="modelValue" :disabled="disabled" :aria-label="`${path}：文字`" rows="2" @input="replace($event.target.value)" />
    <template v-else-if="kind === 'number'">
      <input :value="numberText" :disabled="disabled" :aria-label="`${path}：数字`" :aria-invalid="Boolean(numberError)" inputmode="decimal" @input="updateNumber($event.target.value)" />
      <p v-if="numberError" class="value-error" role="alert">{{ numberError }}</p>
    </template>
    <select v-else-if="kind === 'boolean'" :value="String(modelValue)" :disabled="disabled" :aria-label="`${path}：是或否`" @change="replace($event.target.value === 'true')"><option value="true">是</option><option value="false">否</option></select>
    <p v-else-if="kind === 'null'" class="value-empty">此项为空值。</p>
    <template v-else-if="kind === 'object' || kind === 'array'">
      <section v-for="key in fields" :key="key" class="value-field">
        <div class="value-field-heading"><strong>{{ kind === 'array' ? `第 ${Number(key) + 1} 项` : fieldLabel(key) }}</strong><button type="button" :disabled="disabled" :aria-label="`${path}.${key}：删除`" @click="removeChild(key)">{{ kind === 'array' ? '删除此项' : '删除字段' }}</button></div>
        <FinalizationValueEditor :model-value="modelValue[key]" :disabled="disabled" :path="`${path}.${key}`" @update:model-value="updateChild(key, $event)" @pending-change="childPending.set(key, $event)" />
      </section>
      <p v-if="!fields.length" class="value-empty">{{ kind === 'array' ? '列表中尚无内容。' : '尚无字段。' }}</p>
      <div v-if="kind === 'object'" class="value-add">
        <label><span>新增字段名称</span><input :value="newField" :disabled="disabled" :aria-label="`${path}：新字段名称`" placeholder="例如 result（结果）" @input="updateNewField($event.target.value)" @keydown.enter.prevent="addField" /></label>
        <button type="button" :disabled="disabled" @click="addField">添加字段</button>
        <p v-if="fieldError" class="value-error" role="alert">{{ fieldError }}</p>
      </div>
      <button v-else type="button" :disabled="disabled" @click="replace([...modelValue, ''])">添加列表项</button>
    </template>
  </div>
</template>

<style scoped>
.fact-value-editor { display: grid; gap: 8px; min-width: 0; color: #55493c; font-size: 12px; }
.value-type { display: flex; align-items: center; gap: 9px; }
.value-type select { width: auto; min-width: 100px; }
label { display: grid; gap: 5px; }
input, textarea, select { box-sizing: border-box; width: 100%; border: 1px solid #d9cbb7; border-radius: 6px; padding: 8px 9px; background: #fffdf8; color: inherit; font: inherit; }
textarea { resize: vertical; line-height: 1.65; }
button { justify-self: start; min-height: 32px; border: 1px solid #d9cbb7; border-radius: 6px; padding: 6px 9px; color: #754331; background: #fffaf1; font: inherit; cursor: pointer; }
button:disabled, input:disabled, textarea:disabled, select:disabled { opacity: .6; cursor: default; }
:is(button,input,textarea,select):focus-visible { outline: 2px solid #9b6a32; outline-offset: 2px; }
.value-field { min-width: 0; border-left: 2px solid #dfcdb5; padding: 8px 0 8px 12px; }
.value-field-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
.value-field-heading strong { overflow-wrap: anywhere; }
.value-add { display: flex; align-items: end; flex-wrap: wrap; gap: 8px; }
.value-add label { flex: 1 1 150px; }
.value-empty { margin: 0; color: #817565; }
.value-error { margin: 0; color: #a13b32; }
</style>
