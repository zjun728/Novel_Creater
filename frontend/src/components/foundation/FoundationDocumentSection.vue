<script setup>
defineProps({
  targetId: { type: String, required: true },
  title: { type: String, required: true },
  eyebrow: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
})
</script>

<template>
  <section class="foundation-document-section">
    <header>
      <p v-if="eyebrow">{{ eyebrow }}</p>
      <h2 :id="targetId" tabindex="-1">{{ title }}</h2>
    </header>
    <div v-if="$slots.read" class="foundation-document-section__read"><slot name="read" /></div>
    <div v-if="!readOnly && $slots.edit" class="foundation-document-section__edit"><slot name="edit" /></div>
  </section>
</template>

<style scoped>
.foundation-document-section { min-width:0; padding:clamp(22px,4vw,44px); overflow-wrap:anywhere; }
.foundation-document-section+.foundation-document-section { border-top:1px solid var(--nc-border); }
header { margin-bottom:18px; padding-bottom:12px; border-bottom:1px solid var(--nc-border); } header p { margin:0 0 5px; color:var(--nc-vermilion); font:700 10px Georgia,'Noto Serif SC',serif; letter-spacing:.16em; } h2 { margin:0; scroll-margin-top:20px; font:600 clamp(24px,3vw,34px)/1.25 Georgia,'Noto Serif SC',serif; } h2:focus { outline:2px solid var(--nc-vermilion); outline-offset:5px; }.foundation-document-section__read,.foundation-document-section__edit { min-width:0; }.foundation-document-section__edit { margin-top:18px; padding-top:18px; border-top:1px dashed var(--nc-border); }
@media (max-width:760px) { .foundation-document-section { padding:22px 18px; } }
</style>
