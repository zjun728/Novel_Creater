<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { createModalFocusManager } from '@/components/common/modalFocusManager.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  closeDisabled: { type: Boolean, default: false },
})
const emit = defineEmits(['close'])
const dialog = ref(null)
const mounted = ref(false)
let focusGeneration = 0
let componentMounted = false
const focusManager = createModalFocusManager({
  getDialog: () => dialog.value,
  getInitialFocus: () => dialog.value?.querySelectorAll?.(
    'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
  )?.[0] ?? dialog.value,
})

async function mountFocus() {
  const generation = ++focusGeneration
  await nextTick()
  if (generation !== focusGeneration || !componentMounted || !props.open || !dialog.value) return
  focusManager.mount()
}

function cancelFocus() {
  focusGeneration += 1
  focusManager.unmount()
}

function close() { if (!props.closeDisabled) emit('close') }
function handleKeydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); close(); return }
  if (event.key === 'Tab' && !focusManager.trapTab(event)) {
    event.preventDefault()
    dialog.value?.focus?.()
  }
}

onMounted(() => { componentMounted = true; mounted.value = true; if (props.open) mountFocus() })
watch(() => props.open, open => { if (open) mountFocus(); else cancelFocus() })
onBeforeUnmount(() => { componentMounted = false; cancelFocus() })
</script>

<template>
  <Teleport to="body" :disabled="!mounted">
    <div v-if="open" class="foundation-confirmation-dialog__overlay">
      <section
        ref="dialog"
        class="foundation-confirmation-dialog"
        role="dialog"
        aria-modal="true"
        tabindex="-1"
        :aria-label="title"
        @keydown="handleKeydown"
      >
        <p class="foundation-confirmation-dialog__kicker">CONFIRM REVISION</p>
        <h2>{{ title }}</h2>
        <div v-if="$slots.snapshot" class="foundation-confirmation-dialog__snapshot"><slot name="snapshot" /></div>
        <div v-if="$slots.source" class="foundation-confirmation-dialog__source"><slot name="source" /></div>
        <footer v-if="$slots.action" class="foundation-confirmation-dialog__actions"><slot name="action" /></footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.foundation-confirmation-dialog__overlay { position:fixed; z-index:34; inset:0; display:grid; min-width:0; padding:24px; place-items:center; background:color-mix(in srgb,var(--nc-ink) 40%,transparent); }
.foundation-confirmation-dialog { width:min(640px,100%); max-height:calc(100vh - 48px); min-width:0; overflow:auto; padding:clamp(22px,4vw,34px); overflow-wrap:anywhere; color:var(--nc-ink); border:1px solid var(--nc-vermilion); background:var(--nc-paper); box-shadow:0 24px 64px color-mix(in srgb,var(--nc-ink) 24%,transparent); }
.foundation-confirmation-dialog__kicker { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,'Noto Serif SC',serif; letter-spacing:.17em; }.foundation-confirmation-dialog h2 { margin:7px 0 18px; font:600 clamp(26px,4vw,38px)/1.2 Georgia,'Noto Serif SC',serif; }.foundation-confirmation-dialog__snapshot,.foundation-confirmation-dialog__source { min-width:0; padding:13px; border-left:2px solid var(--nc-vermilion); background:color-mix(in srgb,var(--nc-paper) 82%,var(--nc-canvas)); }.foundation-confirmation-dialog__source { margin-top:12px; color:var(--nc-muted); font-size:13px; line-height:1.65; }.foundation-confirmation-dialog__actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:10px; margin-top:22px; }.foundation-confirmation-dialog :deep(button) { min-height:40px; border:1px solid var(--nc-border); padding:8px 13px; color:var(--nc-ink); background:var(--nc-paper); font:600 14px Georgia,'Noto Serif SC',serif; cursor:pointer; }.foundation-confirmation-dialog :deep(button):focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:3px; }
@media (max-width:760px) { .foundation-confirmation-dialog__overlay { padding:12px; } .foundation-confirmation-dialog { max-height:calc(100vh - 24px); } .foundation-confirmation-dialog__actions { align-items:stretch; flex-direction:column-reverse; } }
@media (prefers-reduced-motion:reduce) { .foundation-confirmation-dialog, .foundation-confirmation-dialog * { scroll-behavior:auto !important; transition:none !important; animation:none !important; } }
</style>
