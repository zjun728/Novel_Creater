<script setup>
import { nextTick, ref, watch } from 'vue'
import { NAlert, NButton, NInput, NInputNumber } from 'naive-ui'

import { useCreationContractStore } from '@/stores/creationContractStore.js'

const props = defineProps({ projectId: { type: String, required: true } })
const emit = defineEmits(['saved', 'back', 'dirty-change'])
const store = useCreationContractStore()
const targetTotalWords = ref(0)
const expectedVolumeCount = ref(0)
const expectedChapterCount = ref(0)
const chapterWordMin = ref(0)
const chapterWordMax = ref(0)
const prohibitedDirectionsText = ref('')
const authorNotes = ref('')
const errorMessage = ref('')
const errorRegion = ref(null)
let hydrating = false

function listFromText(value) {
  return [...new Set(String(value || '').split(/\r?\n/u).map(item => item.trim()).filter(Boolean))]
}

function hydrate(draft) {
  hydrating = true
  targetTotalWords.value = Number(draft?.targetTotalWords || 0)
  expectedVolumeCount.value = Number(draft?.expectedVolumeCount || 0)
  expectedChapterCount.value = Number(draft?.expectedChapterCount || 0)
  chapterWordMin.value = Number(draft?.chapterWordRangePreference?.[0] || 0)
  chapterWordMax.value = Number(draft?.chapterWordRangePreference?.[1] || 0)
  prohibitedDirectionsText.value = Array.isArray(draft?.prohibitedDirections)
    ? draft.prohibitedDirections.join('\n')
    : ''
  authorNotes.value = String(draft?.authorNotes || '')
  void nextTick(() => { hydrating = false })
}

function markDirty() {
  if (hydrating || store.saving) return
  store.markUnsavedChanges()
  emit('dirty-change', true)
}

async function showError(message) {
  errorMessage.value = message
  await nextTick()
  errorRegion.value?.focus({ preventScroll: false })
}

function positiveInteger(value, label, max) {
  const number = Number(value)
  if (!Number.isInteger(number) || number < 1 || number > max) {
    throw new Error(`${label}必须是 1–${max.toLocaleString()} 的整数。`)
  }
  return number
}

async function saveAndContinue() {
  if (store.saving || store.requiresReload) return
  const current = store.draft?.draft
  if (!current?.engineOptionId || current?.draftStage !== 'assets') {
    await showError('素材范围草稿已失效，请返回上一步重新加载。')
    return
  }
  try {
    const targetWords = positiveInteger(targetTotalWords.value, '总字数', 100_000_000)
    const volumes = positiveInteger(expectedVolumeCount.value, '预计卷数', 1_000)
    const chapters = positiveInteger(expectedChapterCount.value, '预计章节数', 100_000)
    const chapterMin = positiveInteger(chapterWordMin.value, '章节字数下限', 100_000)
    const chapterMax = positiveInteger(chapterWordMax.value, '章节字数上限', 100_000)
    if (chapterMax < chapterMin) throw new Error('章节字数上限不能小于下限。')
    const prohibitedDirections = listFromText(prohibitedDirectionsText.value)
    if (prohibitedDirections.length > 20) throw new Error('禁止方向最多填写 20 条。')

    const saved = await store.saveDraft(props.projectId, {
      ...current,
      draftStage: 'assets',
      targetTotalWords: targetWords,
      expectedVolumeCount: volumes,
      expectedChapterCount: chapters,
      chapterWordRangePreference: [chapterMin, chapterMax],
      prohibitedDirections,
      authorNotes: authorNotes.value.trim() || null,
    })
    if (store.draft !== saved) {
      await showError('保存期间契约状态发生变化，请重新加载并核对。')
      return
    }
    errorMessage.value = ''
    emit('dirty-change', false)
    emit('saved', saved)
  } catch (error) {
    await showError(error?.message || '容量约定保存失败')
  }
}

watch(() => store.draft?.draft, draft => hydrate(draft), { immediate: true })
</script>

<template>
  <section class="capacity-step" aria-labelledby="capacity-step-heading">
    <header class="step-heading">
      <div>
        <p class="step-kicker">STEP 04 · CAPACITY</p>
        <h2 id="capacity-step-heading">给长篇一副可调整的骨架</h2>
        <p>总量约束用于滚动规划，不会强迫每章机械等长；禁止方向和作者备注会随正式契约一起冻结。</p>
      </div>
      <span aria-hidden="true">04</span>
    </header>

    <div class="capacity-grid">
      <label>
        <span>目标总字数</span>
        <small>整书容量的主锚点</small>
        <n-input-number v-model:value="targetTotalWords" :min="1" :max="100000000" :step="10000" @update:value="markDirty" />
      </label>
      <label>
        <span>预计卷数</span>
        <small>允许后续规划调整</small>
        <n-input-number v-model:value="expectedVolumeCount" :min="1" :max="1000" @update:value="markDirty" />
      </label>
      <label>
        <span>预计章节数</span>
        <small>用于估算推进密度</small>
        <n-input-number v-model:value="expectedChapterCount" :min="1" :max="100000" @update:value="markDirty" />
      </label>
      <fieldset>
        <legend>章节字数偏好</legend>
        <div>
          <label><span>下限</span><n-input-number v-model:value="chapterWordMin" :min="1" :max="100000" :step="100" @update:value="markDirty" /></label>
          <label><span>上限</span><n-input-number v-model:value="chapterWordMax" :min="1" :max="100000" :step="100" @update:value="markDirty" /></label>
        </div>
      </fieldset>
    </div>

    <div class="direction-grid">
      <label>
        <span>禁止方向</span>
        <small>每行一条，最多 20 条。例如“不写无代价升级”。</small>
        <n-input v-model:value="prohibitedDirectionsText" type="textarea" :autosize="{ minRows: 4, maxRows: 9 }" maxlength="2000" show-count @update:value="markDirty" />
      </label>
      <label>
        <span>作者备注</span>
        <small>写给未来规划和写作阶段的短笺，可留空。</small>
        <n-input v-model:value="authorNotes" type="textarea" :autosize="{ minRows: 4, maxRows: 9 }" maxlength="2000" show-count @update:value="markDirty" />
      </label>
    </div>

    <n-alert
      v-if="errorMessage"
      ref="errorRegion"
      tabindex="-1"
      type="error"
      class="state-alert"
      aria-live="assertive"
    >
      {{ errorMessage }}
    </n-alert>

    <footer class="step-actions">
      <n-button secondary :disabled="store.saving" @click="emit('back')">返回素材范围</n-button>
      <div>
        <small>保存会建立明确的草稿检查点；确认仍在下一步一次完成。</small>
        <n-button type="primary" size="large" :loading="store.saving" :disabled="store.saving || store.requiresReload" @click="saveAndContinue">保存草稿并继续</n-button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.capacity-step { color: var(--ink, #302b24); }
.step-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 30px; padding-bottom: 22px; border-bottom: 1px solid var(--rule, #d9cfbb); }
.step-kicker { margin: 0; color: var(--cinnabar, #9c3d2f); font: 800 10px Georgia, serif; letter-spacing: .17em; }
.step-heading h2 { margin: 7px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(25px, 4vw, 36px); font-weight: 650; }
.step-heading p:not(.step-kicker) { max-width: 720px; margin: 10px 0 0; color: var(--muted, #766c5e); font-size: 13px; line-height: 1.8; }
.step-heading > span { color: #c9baa1; font-family: Georgia, serif; font-size: 50px; line-height: .9; }
.capacity-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 26px; }
.capacity-grid > label, .capacity-grid fieldset, .direction-grid > label { display: grid; gap: 7px; margin: 0; padding: 17px; border: 1px solid var(--rule, #ddd2be); border-radius: 9px; background: var(--paper, #fffdf8); }
.capacity-grid span, .direction-grid span, legend { font-family: 'Noto Serif SC', serif; font-size: 13px; font-weight: 700; }
.capacity-grid small, .direction-grid small { color: #887d6d; font-size: 10px; }
.capacity-grid fieldset { grid-column: 1 / -1; }
.capacity-grid fieldset > div { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.capacity-grid fieldset label { display: grid; gap: 6px; }
.direction-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
.state-alert { margin-top: 16px; }
.step-actions { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-top: 26px; padding-top: 20px; border-top: 1px solid var(--rule, #ded5c4); }
.step-actions > div { display: flex; align-items: center; gap: 14px; }
.step-actions small { max-width: 340px; color: #8a8071; font-size: 10px; text-align: right; }
@media (max-width: 760px) { .capacity-grid, .direction-grid { grid-template-columns: 1fr; } .capacity-grid fieldset { grid-column: 1; } .step-actions, .step-actions > div { align-items: stretch; flex-direction: column; } .step-actions small { text-align: left; } }
</style>
