<script setup>
import { ref, watch } from 'vue'
import { NAlert, NButton } from 'naive-ui'

import { useTopicCenterStore } from '@/stores/topicCenterStore'

const props = defineProps({
  show: { type: Boolean, default: false },
  candidate: { type: Object, default: null },
  version: { type: Object, default: null },
})
const emit = defineEmits(['close', 'created'])
const topics = useTopicCenterStore()
const projectTitle = ref('')
const error = ref('')
const handoffAttempt = ref(null)

watch(() => [
  props.show,
  props.candidate?.id,
  props.version?.version,
  props.version?.contentHash,
], () => {
  handoffAttempt.value = null
  if (props.show) {
    projectTitle.value = props.version?.payload?.title || ''
    error.value = ''
  }
})

function commandKey() {
  const bytes = new Uint8Array(32)
  globalThis.crypto.getRandomValues(bytes)
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
}

function handoffKeyFor(title) {
  const fingerprint = [
    props.candidate?.id,
    props.version?.version,
    props.version?.contentHash,
    title,
  ].join('\u0000')
  if (handoffAttempt.value?.fingerprint !== fingerprint) {
    handoffAttempt.value = { fingerprint, key: commandKey() }
  }
  return handoffAttempt.value.key
}

async function createProject() {
  const title = projectTitle.value.trim()
  if (!props.candidate || !props.version || !title) return
  error.value = ''
  try {
    const handoff = await topics.handoff(props.candidate.id, props.version.version, {
      candidateHash: props.version.contentHash,
      projectTitle: title,
      idempotencyKey: handoffKeyFor(title),
    })
    emit('created', handoff)
  } catch (failure) {
    error.value = failure?.message || '项目创建失败，请刷新候选版本后重试'
  }
}
</script>

<template>
  <div v-if="show" class="dialog-backdrop" @keydown.esc="emit('close')">
    <section class="project-dialog" role="dialog" aria-modal="true" aria-labelledby="candidate-project-title">
      <p>EXACT VERSION HANDOFF</p>
      <h2 id="candidate-project-title">从指定版本创建项目</h2>
      <div class="candidate-stamp"><strong>《{{ version?.payload?.title }}》</strong><span>候选版本 {{ version?.version }}</span></div>
      <p class="explanation">这里只复制当前指定版本。创建后，项目种子仍为“待确认”，你可以在项目内检查和编辑，再手动确认进入创作契约。</p>
      <n-alert v-if="error" type="error" aria-live="assertive">{{ error }}</n-alert>
      <label for="candidate-project-name">项目名称</label>
      <input id="candidate-project-name" v-model="projectTitle" maxlength="200" autofocus>
      <footer>
        <n-button :disabled="topics.handoffBusy" @click="emit('close')">取消</n-button>
        <n-button type="primary" :disabled="!projectTitle.trim()" :loading="topics.handoffBusy" @click="createProject">创建项目并检查种子</n-button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.dialog-backdrop { position:fixed; z-index:60; inset:0; display:grid; padding:20px; place-items:center; background:rgba(42,35,28,.46); }
.project-dialog { width:min(520px,100%); padding:28px; border:1px solid #b79c7b; color:#302923; background:#fffdf8; box-shadow:0 26px 80px rgba(43,34,25,.25); }
.project-dialog>p:first-child { margin:0; color:#9a4938; font:750 9px Georgia,serif; letter-spacing:.16em; }.project-dialog h2{margin:7px 0 18px;font:650 27px 'Noto Serif SC','Songti SC',serif}.candidate-stamp{display:flex;justify-content:space-between;gap:12px;padding:13px;border-block:1px solid #e1d6c5}.candidate-stamp span{color:#876f57;font-size:11px}.explanation{color:#6f6458;font-size:12px;line-height:1.75}.project-dialog label{display:block;margin:18px 0 6px;color:#765f48;font-size:11px;font-weight:700}.project-dialog input{width:100%;min-width:0;box-sizing:border-box;border:1px solid #cbb99f;padding:10px;color:#302923;background:#fff;font:inherit}.project-dialog footer{display:flex;justify-content:flex-end;gap:9px;margin-top:22px}
@media(max-width:720px){.project-dialog{padding:20px}.candidate-stamp,.project-dialog footer{align-items:stretch;flex-direction:column}.project-dialog footer :deep(.n-button){width:100%}}
</style>
