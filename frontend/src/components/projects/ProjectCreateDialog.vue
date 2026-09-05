<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'

import { PROJECT_METADATA_DEFAULTS } from '../../application/projects/projectMetadata.js'
import { createModalFocusManager } from '../common/modalFocusManager.js'

const props = defineProps({
  pending: { type: Boolean, default: false },
  serverError: { type: String, default: '' },
  onCancel: { type: Function, default: () => {} },
})
const emit = defineEmits(['submit'])
const titleInput = ref(null)
const dialog = ref(null)
const localError = ref('')
const form = reactive({
  title: '',
  genre: PROJECT_METADATA_DEFAULTS.genre,
  description: PROJECT_METADATA_DEFAULTS.description,
  targetWords: PROJECT_METADATA_DEFAULTS.targetWords,
  targetChapters: PROJECT_METADATA_DEFAULTS.targetChapters,
})
const visibleError = computed(() => localError.value || props.serverError)
const focusManager = createModalFocusManager({
  getDialog: () => dialog.value,
  getInitialFocus: () => titleInput.value,
})

function submit() {
  if (props.pending) return
  if (!form.title.trim()) {
    localError.value = '请输入项目名称'
    void nextTick(() => titleInput.value?.focus())
    return
  }
  if (!Number.isSafeInteger(form.targetWords) || form.targetWords < 1
    || !Number.isSafeInteger(form.targetChapters) || form.targetChapters < 1) {
    localError.value = '目标字数和预计章节数必须是正整数'
    return
  }
  localError.value = ''
  emit('submit', { ...form, title: form.title.trim(), genre: form.genre.trim(), description: form.description.trim() })
}

function cancel() {
  if (!props.pending) props.onCancel()
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    cancel()
    return
  }
  focusManager.trapTab(event)
}

onMounted(focusManager.mount)
onUnmounted(focusManager.unmount)
</script>

<template>
  <Teleport to="body">
    <div class="project-create-backdrop" @keydown="handleKeydown">
      <section ref="dialog" class="project-create-dialog" role="dialog" aria-modal="true" aria-labelledby="create-project-title">
        <header>
          <p>PROJECT FOUNDATION</p>
          <h2 id="create-project-title">新建项目</h2>
          <span>先确定作品定位和长篇规模，创建后仍可在“项目资料”中调整。</span>
        </header>
        <form @submit.prevent="submit">
          <label class="field field--wide">
            <span>项目名称 <b>必填</b></span>
            <input ref="titleInput" v-model="form.title" maxlength="200" autocomplete="off" :disabled="pending">
          </label>
          <label class="field">
            <span>题材</span>
            <input v-model="form.genre" maxlength="120" placeholder="如：东方奇幻" :disabled="pending">
          </label>
          <label class="field">
            <span>目标字数</span>
            <input v-model.number="form.targetWords" type="number" min="1" max="2147483647" step="1" :disabled="pending">
            <small>默认 240 万字，适合长篇连载</small>
          </label>
          <label class="field">
            <span>预计章节数</span>
            <input v-model.number="form.targetChapters" type="number" min="1" max="2147483647" step="1" :disabled="pending">
          </label>
          <label class="field field--wide">
            <span>项目简介</span>
            <textarea v-model="form.description" maxlength="5000" rows="4" placeholder="概括故事方向、主角目标和核心冲突" :disabled="pending"></textarea>
          </label>
          <p class="project-create-error" role="alert">{{ visibleError }}</p>
          <footer>
            <button type="button" class="secondary" :disabled="pending" @click="cancel">取消</button>
            <button type="submit" class="primary" :disabled="pending">{{ pending ? '正在创建…' : '创建并打开' }}</button>
          </footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.project-create-backdrop { position: fixed; z-index: 1200; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(47,40,33,.3); backdrop-filter: blur(3px); }
.project-create-dialog { width: min(680px, 100%); max-height: calc(100vh - 48px); overflow: auto; padding: 38px 42px 34px; border: 1px solid #d8cbb7; border-radius: 18px; background: #fffdf8; box-shadow: 0 26px 80px rgba(45,35,24,.24); color: #302a23; }
header { padding-bottom: 22px; border-bottom: 1px solid #dfd3c2; }
header p { margin: 0; color: #9a3f32; font: 700 11px Georgia,serif; letter-spacing: .18em; }
h2 { margin: 8px 0 6px; font: 600 38px Georgia,'Noto Serif SC',serif; }
header span, small { color: #817568; font-size: 12px; }
form { display: grid; grid-template-columns: 1fr 1fr; gap: 18px 20px; margin-top: 24px; }
.field { display: grid; gap: 8px; }
.field--wide, .project-create-error, footer { grid-column: 1 / -1; }
.field > span { font-weight: 700; font-size: 14px; }
.field b { margin-left: 5px; color: #9a3f32; font-size: 11px; }
input, textarea { box-sizing: border-box; width: 100%; min-height: 46px; padding: 11px 13px; border: 1px solid #d8cbb7; border-radius: 8px; outline: none; background: #fffefb; color: #302a23; font: inherit; }
textarea { resize: vertical; line-height: 1.7; }
input:focus, textarea:focus { border-color: #9a3f32; box-shadow: 0 0 0 3px rgba(154,63,50,.1); }
.project-create-error { min-height: 20px; margin: -4px 0 0; color: #a43f32; font-size: 13px; }
footer { display: flex; justify-content: flex-end; gap: 12px; }
button { min-height: 44px; padding: 0 20px; border: 0; border-radius: 9px; font-weight: 700; cursor: pointer; }
button:disabled { cursor: wait; opacity: .58; }
.secondary { background: #eee6d9; color: #433a31; }
.primary { background: #9a3f32; color: white; }
@media (max-width: 620px) { .project-create-dialog { padding: 28px 22px; } form { grid-template-columns: 1fr; } .field, .field--wide { grid-column: 1; } }
</style>
