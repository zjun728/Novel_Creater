<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { NAlert, NButton, NInput, NSpin, NTag } from 'naive-ui'

import { useCreationContractStore } from '@/stores/creationContractStore.js'

const props = defineProps({
  projectId: { type: String, required: true },
  selectionRevision: { type: Number, required: true },
  engineOptionId: { type: String, required: true },
  engineHash: { type: String, required: true },
  primaryStyleRef: { type: Object, default: null },
  secondaryStyleRef: { type: Object, default: null },
})
const store = useCreationContractStore()
const authorScenario = ref('')
const requestKey = ref('')
const errorMessage = ref('')
const errorRegion = ref(null)
const result = computed(() => store.styleTrial)
const canRun = computed(() => Boolean(
  props.selectionRevision > 0
  && props.engineOptionId
  && props.engineHash
  && props.primaryStyleRef?.id
  && props.primaryStyleRef?.contentHash
  && authorScenario.value.trim(),
))

function newRequestKey() {
  const uuid = globalThis.crypto?.randomUUID?.().replaceAll('-', '')
    || `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
  return uuid.repeat(4).replace(/[^A-Za-z0-9_-]/gu, '').padEnd(64, '0').slice(0, 64)
}

async function showError(message) {
  errorMessage.value = String(message || '临时风格试写失败')
  await nextTick()
  errorRegion.value?.focus({ preventScroll: false })
}

async function runTrial() {
  if (!canRun.value || store.styleTrialLoading) return
  errorMessage.value = ''
  if (!requestKey.value) requestKey.value = newRequestKey()
  try {
    const trial = await store.runStyleTrial(props.projectId, {
      selectionRevision: props.selectionRevision,
      engineOptionId: props.engineOptionId,
      engineHash: props.engineHash,
      primaryStyleRevisionId: props.primaryStyleRef.id,
      primaryStyleHash: props.primaryStyleRef.contentHash,
      secondaryStyleRevisionId: props.secondaryStyleRef?.id || null,
      secondaryStyleHash: props.secondaryStyleRef?.contentHash || null,
      authorScenario: authorScenario.value.trim(),
      idempotencyKey: requestKey.value,
    })
    if (trial.status !== 'succeeded') {
      await showError(`试写未完成（${trial.publicErrorCode || trial.status}）`)
    }
  } catch (error) {
    await showError(error?.message || '临时风格试写失败')
  }
}

watch(
  () => [
    props.selectionRevision,
    props.engineOptionId,
    props.engineHash,
    props.primaryStyleRef?.id,
    props.primaryStyleRef?.contentHash,
    props.secondaryStyleRef?.id,
    props.secondaryStyleRef?.contentHash,
    authorScenario.value,
  ],
  () => {
    requestKey.value = ''
    errorMessage.value = ''
    store.clearStyleTrial()
  },
)
</script>

<template>
  <aside class="trial-panel" aria-labelledby="style-trial-heading">
    <header>
      <div>
        <span>TEMPORARY STYLE TRIAL</span>
        <h3 id="style-trial-heading">临时试写，不改变任何选择</h3>
        <p>试写只通过后端安全网关调用当前绑定。结果不会进入创作契约，也不会自动选择主风格或辅风格。</p>
      </div>
      <n-tag :type="result?.status === 'succeeded' ? 'success' : result?.status === 'failed' ? 'error' : 'default'" round>
        {{ store.styleTrialLoading ? '试写中' : result?.status === 'succeeded' ? '已完成' : result?.status === 'failed' ? '失败' : '未试写' }}
      </n-tag>
    </header>

    <label>
      <span>作者场景</span>
      <small>给出一个具体选择或压力场景，最多 2000 字；它只用于本次临时试写。</small>
      <n-input v-model:value="authorScenario" type="textarea" :autosize="{ minRows: 3, maxRows: 7 }" maxlength="2000" show-count placeholder="例如：主角必须在救人和守住唯一证据之间做选择。" />
    </label>

    <n-alert v-if="errorMessage" ref="errorRegion" tabindex="-1" type="error" aria-live="assertive">{{ errorMessage }}</n-alert>

    <n-spin :show="store.styleTrialLoading">
      <article v-if="result?.status === 'succeeded'" class="trial-result" aria-live="polite">
        <div class="provider-line">
          <span>实际 Provider</span>
          <strong>{{ result.provider?.providerType }} · {{ result.provider?.modelName }}</strong>
          <small>配置修订 R{{ result.provider?.profileRevision }}</small>
        </div>
        <p>{{ result.sample }}</p>
        <footer>这段文字仅供比较阅读感受，不会自动选择、保存或冻结。</footer>
      </article>
    </n-spin>

    <div class="trial-actions">
      <span>更换场景或风格后会建立新的试写命令。</span>
      <n-button type="primary" secondary :loading="store.styleTrialLoading" :disabled="!canRun || store.styleTrialLoading" @click="runTrial">运行临时试写</n-button>
    </div>
  </aside>
</template>

<style scoped>
.trial-panel { margin-top: 18px; padding: 19px; border: 1px solid #c9b99e; border-radius: 11px; background: linear-gradient(135deg, #f8f3e8, #fffdf8); }
.trial-panel header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.trial-panel header span { color: #9c3d2f; font: 800 9px Georgia, serif; letter-spacing: .15em; }
.trial-panel h3 { margin: 5px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 19px; }
.trial-panel header p { max-width: 680px; margin: 7px 0 0; color: #776d60; font-size: 11px; line-height: 1.7; }
.trial-panel > label { display: grid; gap: 6px; margin-top: 15px; }
.trial-panel > label > span { font-size: 12px; font-weight: 700; }
.trial-panel > label > small { color: #887c6b; font-size: 10px; }
.trial-result { margin-top: 14px; border: 1px solid #d6c9b5; background: #fffdf8; }
.provider-line { display: flex; align-items: baseline; flex-wrap: wrap; gap: 7px 12px; padding: 11px 14px; border-bottom: 1px solid #e2d8c7; }
.provider-line span { color: #4f725b; font-size: 9px; font-weight: 800; letter-spacing: .1em; }
.provider-line strong { font-size: 11px; }
.provider-line small { color: #8b7f6f; font-size: 9px; }
.trial-result p { margin: 0; padding: 18px; color: #4e473e; font-family: Georgia, 'Noto Serif SC', serif; font-size: 14px; line-height: 2; white-space: pre-wrap; }
.trial-result footer { padding: 9px 14px; color: #8b7c68; background: #f5efe4; font-size: 9px; }
.trial-actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-top: 13px; }
.trial-actions > span { color: #887c6b; font-size: 10px; }
@media (max-width: 620px) { .trial-panel header, .trial-actions { align-items: stretch; flex-direction: column; } }
</style>
