<script setup>
import { computed, nextTick, ref, watch } from 'vue'

import {
  capturePlainTextInput,
  capturePlainTextRange,
  locatePlainTextRange,
} from '@/utils/plainTextRange'

const props = defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  readonly: { type: Boolean, default: false },
  streaming: { type: Boolean, default: false },
  placeholder: { type: String, default: '' },
  dirty: { type: Boolean, default: false },
  status: { type: String, default: 'idle' },
  lastSavedAt: { type: String, default: '--:--:--' },
})
const emit = defineEmits(['update:modelValue', 'selection-change', 'retry'])
const textarea = ref(null)
const autoFollow = ref(true)
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
  if (props.readonly || props.disabled || props.streaming) return
  try {
    const input = capturePlainTextInput(event.target)
    emit('update:modelValue', input.value)
    emit('selection-change', input.selection)
  } catch {
    // Fail closed: never persist text whose UTF-16 selection cannot be safely mapped.
  }
}

function blockPaste(event) {
  if (props.readonly || props.disabled || props.streaming) event.preventDefault()
}

function scrollToLatest() {
  if (!textarea.value) return
  textarea.value.scrollTop = textarea.value.scrollHeight
}

function updateFollow(event) {
  if (!props.streaming) return
  const target = event.target
  const distance = target.scrollHeight - target.scrollTop - target.clientHeight
  if (distance > 24) autoFollow.value = false
  else autoFollow.value = true
}

function returnToLatest() {
  autoFollow.value = true
  scrollToLatest()
}

watch(() => props.modelValue, () => {
  if (props.streaming && autoFollow.value) void nextTick(scrollToLatest)
})

watch(() => props.streaming, streaming => {
  autoFollow.value = true
  if (streaming) void nextTick(scrollToLatest)
})

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
    :readonly="readonly || streaming"
    :disabled="disabled"
    :placeholder="placeholder"
    @input="updateText"
    @paste="blockPaste"
    @scroll="updateFollow"
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
      <span v-else-if="status === 'failed'">暂存失败，<button type="button" :disabled="disabled || readonly || streaming" @click="emit('retry')">重试</button></span>
      <span v-else-if="status === 'saving'">正在暂存</span>
      <span v-else-if="dirty">未暂存</span>
      <span v-else>已暂存 {{ savedAt }}</span>
    </span>
  </div>
  <button
    v-if="streaming && !autoFollow"
    type="button"
    class="return-to-latest"
    aria-label="回到最新输出"
    @click="returnToLatest"
  >回到最新</button>
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
.plain-text-draft-editor:read-only:not(:disabled) { color: #4e463d; background: #faf6ee; cursor: text; }
.plain-text-draft-editor:disabled { color: #81776a; background: #f1ebdf; cursor: not-allowed; }
.draft-persistence { display: flex; justify-content: space-between; gap: 12px; margin-top: 9px; color: #82786b; font-size: 12px; }
.draft-status { display: inline-flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; text-align: right; }
.draft-persistence button { border: 0; padding: 0; color: #8b5c25; background: transparent; font: inherit; font-weight: 700; cursor: pointer; text-decoration: underline; }
.draft-persistence button:disabled { color: #9d9387; cursor: not-allowed; }
.return-to-latest { margin-top: 9px; border: 1px solid #967548; border-radius: 999px; padding: 6px 11px; color: #6c471c; background: #fffdf8; font: 700 12px/1 system-ui, sans-serif; cursor: pointer; }
.return-to-latest:focus-visible { outline: 2px solid #8b5c25; outline-offset: 3px; }
</style>
