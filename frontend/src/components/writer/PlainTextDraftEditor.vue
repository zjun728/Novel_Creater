<script setup>
import { computed, ref } from 'vue'

import {
  capturePlainTextInput,
  capturePlainTextRange,
  locatePlainTextRange,
} from '@/utils/plainTextRange'

const props = defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: '' },
  dirty: { type: Boolean, default: false },
  status: { type: String, default: 'idle' },
  lastSavedAt: { type: String, default: '--:--:--' },
})
const emit = defineEmits(['update:modelValue', 'selection-change', 'retry'])
const textarea = ref(null)
const text = computed(() => props.modelValue)
const characterCount = computed(() => Array.from(text.value).length)
const savedAt = computed(() => props.lastSavedAt || '--:--:--')

function emitSelection(target = textarea.value) {
  if (!target) return
  try {
    emit('selection-change', capturePlainTextRange(
      text.value,
      target.selectionStart,
      target.selectionEnd,
    ))
  } catch {
    // Selection events may race reactive DOM updates; never emit an unsafe range.
  }
}

function updateText(event) {
  try {
    const input = capturePlainTextInput(event.target)
    emit('update:modelValue', input.value)
    emit('selection-change', input.selection)
  } catch {
    // Fail closed: never persist text whose UTF-16 selection cannot be safely mapped.
  }
}

function locateRange(startOffset, endOffset) {
  return locatePlainTextRange(
    textarea.value,
    text.value,
    startOffset,
    endOffset,
  )
}

defineExpose({ locateRange })
</script>

<template>
  <textarea
    ref="textarea"
    class="plain-text-draft-editor"
    aria-label="章节正文工作稿"
    :value="modelValue"
    :disabled="disabled"
    :placeholder="placeholder"
    @input="updateText"
    @select="emitSelection($event.target)"
    @keyup="emitSelection($event.target)"
    @mouseup="emitSelection($event.target)"
  />
  <div class="draft-persistence">
    <span>{{ characterCount }} 字</span>
    <span class="draft-status" aria-live="polite">
      <template v-if="status === 'conflict'">
        <span>与服务端版本冲突</span>
        <span>请先复制当前正文，再刷新页面重新加载服务端版本。</span>
      </template>
      <span v-else-if="status === 'failed'">暂存失败，<button type="button" :disabled="disabled" @click="emit('retry')">重试</button></span>
      <span v-else-if="status === 'saving'">正在暂存</span>
      <span v-else-if="dirty">未暂存</span>
      <span v-else>已暂存 {{ savedAt }}</span>
    </span>
  </div>
</template>

<style scoped>
.plain-text-draft-editor {
  display: block;
  box-sizing: border-box;
  width: 100%;
  min-height: 440px;
  resize: vertical;
  border: 1px solid #d7cbb8;
  border-radius: 10px;
  padding: 18px;
  color: #2d2923;
  background: #fffefb;
  font: 16px/1.9 Georgia, 'Noto Serif SC', serif;
  outline: none;
}
.plain-text-draft-editor:focus { border-color: #967548; box-shadow: 0 0 0 3px rgba(150, 117, 72, .14); }
.plain-text-draft-editor:disabled { color: #81776a; background: #f1ebdf; cursor: not-allowed; }
.draft-persistence { display: flex; justify-content: space-between; gap: 12px; margin-top: 9px; color: #82786b; font-size: 12px; }
.draft-status { display: inline-flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; text-align: right; }
.draft-persistence button { border: 0; padding: 0; color: #8b5c25; background: transparent; font: inherit; font-weight: 700; cursor: pointer; text-decoration: underline; }
.draft-persistence button:disabled { color: #9d9387; cursor: not-allowed; }
</style>
