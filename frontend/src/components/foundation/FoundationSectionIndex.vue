<script setup>
const props = defineProps({
  items: { type: Array, required: true },
  currentKey: { type: String, default: '' },
  focusOnNavigate: { type: Boolean, default: true },
})

const emit = defineEmits(['navigate'])

function navigate(item) {
  emit('navigate', item.key)
  if (!props.focusOnNavigate) return
  const target = globalThis.document?.getElementById?.(item.targetId)
  const reducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true
  target?.scrollIntoView?.({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' })
  target?.focus?.({ preventScroll: true })
}
</script>

<template>
  <nav class="foundation-section-index" aria-label="文档章节">
    <p class="foundation-section-index__label">目录 / SECTIONS</p>
    <ol>
      <li v-for="item in items" :key="item.key">
        <button
          type="button"
          :class="{ 'foundation-section-index__item--current': item.key === currentKey }"
          :aria-current="item.key === currentKey ? 'true' : undefined"
          :aria-controls="item.targetId"
          :disabled="item.disabled === true"
          @click="navigate(item)"
        >
          <span class="foundation-section-index__item-label">{{ item.label }}</span>
          <span class="foundation-section-index__item-status" :data-status="item.status">{{ item.statusLabel }}</span>
        </button>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.foundation-section-index { --foundation-status-filled:#496750; --foundation-status-suggested:#60420f; min-width:0; padding:16px 0; overflow-wrap:anywhere; touch-action:pan-y; overscroll-behavior:auto; }
.foundation-section-index__label { margin:0 0 10px; color:var(--nc-vermilion); font:700 10px Georgia,'Noto Serif SC',serif; letter-spacing:.16em; }
ol { display:grid; gap:3px; margin:0; padding:0; list-style:none; }
button { display:grid; grid-template-columns:minmax(0,1fr) auto; width:100%; min-width:0; gap:8px; padding:10px 0 10px 10px; border:0; border-left:2px solid transparent; color:var(--nc-ink); background:transparent; font:inherit; text-align:left; cursor:pointer; }
button:hover,.foundation-section-index__item--current { border-left-color:var(--nc-vermilion); background:color-mix(in srgb,var(--nc-paper) 68%,transparent); }
button:focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:2px; }
.foundation-section-index__item-label { min-width:0; font:600 14px/1.45 Georgia,'Noto Serif SC',serif; }
.foundation-section-index__item-status { align-self:center; color:var(--nc-muted); font-size:11px; white-space:nowrap; }
.foundation-section-index__item-status[data-status='current'] { color:var(--nc-vermilion); }.foundation-section-index__item-status[data-status='filled'] { color:var(--foundation-status-filled); }.foundation-section-index__item-status[data-status='suggested'] { color:var(--foundation-status-suggested); }.foundation-section-index__item-status[data-status='blocked'] { color:var(--nc-vermilion); }
@media (max-width:760px) { .foundation-section-index { padding:12px 0; } ol { grid-template-columns:repeat(auto-fit,minmax(155px,1fr)); gap:4px 14px; } }
</style>
