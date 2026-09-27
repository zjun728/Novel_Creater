<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NModal } from 'naive-ui'
import { usePlanningStore } from '../../stores/planningStore.js'
import { createChapterOutlineController } from '../../application/planning/chapterOutlineController.js'
import ChapterOutlineWorkspace from '../planning/ChapterOutlineWorkspace.vue'
import { createModalFocusManager } from '../common/modalFocusManager.js'

const props = defineProps({ show: Boolean, projectId: { type: String, required: true }, chapterNumber: { type: Number, required: true } })
const emit = defineEmits(['update:show', 'confirmed'])
const store = usePlanningStore()
const controller = createChapterOutlineController({ store, projectId: () => props.projectId })
const message = ref('')
const starting = ref(false)
const nestedOverlayOpen = ref(false)
const dialogBody = ref(null)
const focus = createModalFocusManager({ getDialog: () => dialogBody.value, getInitialFocus: () => dialogBody.value })
function handleKeydown(event) { if (!nestedOverlayOpen.value) focus.trapTab(event) }
const matchesChapter = computed(() => store.outlineState?.authoritativeChapterNumber === props.chapterNumber)
const hasRisk = () => starting.value || controller.busy.value || controller.hasCombinedLeaveRisk()
function canClose() {
  if (nestedOverlayOpen.value) return false
  if (starting.value || controller.busy.value || controller.hasCriticalRecovery.value) return false
  return !hasRisk() || window.confirm('小纲有未保存的修改或补充要求，确定关闭吗？')
}
function close() {
  if (!canClose()) return
  if (store.outlineDirty) store.discardOutlineLocal()
  controller.authorInstructions.value = ''
  emit('update:show', false)
}
async function generate() {
  if (starting.value || !matchesChapter.value) return
  starting.value = true
  message.value = ''
  try {
    if (!store.outlineState?.draft) await controller.createManualDraft()
    if (!controller.canGenerate.value) { message.value = controller.generationDisabledReason.value; return }
    await controller.generate()
  } catch { message.value = '本章小纲未能生成，请重试；已有内容保留。' }
  finally { starting.value = false }
}
const originalConfirm = controller.confirm
controller.confirm = async () => {
  const result = await originalConfirm()
  if (result) { emit('confirmed'); emit('update:show', false) }
  return result
}
watch(() => props.show, async show => {
  if (!show) return
  message.value = ''
  try { await controller.hydrate({ force: true }) }
  catch { message.value = '小纲暂时无法读取，请关闭后重试。' }
}, { immediate: true })
function beforeUnload(event) { if (props.show && hasRisk()) { event.preventDefault(); event.returnValue = '' } }
globalThis.window?.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => { globalThis.window?.removeEventListener('beforeunload', beforeUnload); focus.unmount() })
defineExpose({ hasRisk, canClose })
</script>

<template>
  <n-modal :show="show" :z-index="2000" :trap-focus="false" :close-on-esc="!nestedOverlayOpen" preset="card" title="当前章小纲" style="width:1000px;max-width:calc(100vw - 64px)" content-style="max-height:calc(100vh - 180px);overflow:auto" :mask-closable="false" @keydown="handleKeydown" @after-enter="focus.mount" @after-leave="focus.unmount" @update:show="close">
    <div ref="dialogBody" tabindex="-1">
    <p v-if="message" role="alert">{{ message }}</p>
    <p v-if="store.outlineLoading" role="status">正在读取本章小纲…</p>
    <p v-else-if="!matchesChapter">章节进度已变化，请关闭后重新读取工作台。</p>
    <section v-else-if="(store.outlineState?.reasons || []).some(reason => ['activeStoryBlockCompleted', 'activeStoryBlockTasksCompleted'].includes(reason))" role="status">
      <p>{{ controller.generationDisabledReason.value }}</p>
      <router-link v-for="action in controller.recoveryActions.value" :key="action.path" :to="action.path">{{ action.label }}</router-link>
    </section>
    <template v-else-if="!store.outlineState?.draft && !store.outlineState?.confirmedOutline">
      <p>根据已确认的故事规划生成本章小纲，确认后才能用于正文。</p>
      <button :disabled="starting || !controller.canCreateDraft.value" @click="generate">{{ starting ? '正在生成小纲…' : '生成本章小纲' }}</button>
    </template>
    <chapter-outline-workspace v-else :store="store" :controller="controller" :overlay-z-index="2100" @overlay-change="nestedOverlayOpen = $event" />
    </div>
  </n-modal>
</template>
