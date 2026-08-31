<script setup>
// This rail applies the same caller-owned readOnly state to its distinct action slot.
defineProps({
  readOnly: { type: Boolean, default: false },
})
</script>

<template>
  <section class="foundation-status-rail" aria-label="文档状态">
    <div v-if="$slots.summary" class="foundation-status-rail__summary"><slot name="summary" /></div>
    <div v-if="$slots.status" class="foundation-status-rail__status"><slot name="status" /></div>
    <div v-if="$slots.source" class="foundation-status-rail__source"><slot name="source" /></div>
    <div v-if="!readOnly && $slots.action" class="foundation-status-rail__action"><slot name="action" /></div>
  </section>
</template>

<style scoped>
.foundation-status-rail { display:grid; min-width:0; gap:14px; padding:16px 0; overflow-wrap:anywhere; }
.foundation-status-rail__summary,.foundation-status-rail__status,.foundation-status-rail__source,.foundation-status-rail__action { min-width:0; padding:12px; border:1px solid var(--nc-border); background:color-mix(in srgb,var(--nc-paper) 84%,var(--nc-canvas)); }
.foundation-status-rail__status { color:var(--nc-vermilion); font:700 11px Georgia,'Noto Serif SC',serif; letter-spacing:.1em; }.foundation-status-rail__source { color:var(--nc-muted); font-size:12px; line-height:1.65; }.foundation-status-rail__action { display:grid; gap:8px; border-color:var(--nc-vermilion); }
@media (max-width:760px) { .foundation-status-rail { grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); } }
</style>
