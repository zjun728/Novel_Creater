<script setup>
defineProps({ outline: { type: Object, required: true } })
const labels = Object.freeze({ chapterGoal: '本章目标', expectedCharacters: '预计人物', continuation: '延续项', plannedTasks: '计划任务', scenes: '场景', forbiddenEarlyEvents: '禁止提前发生事项' })
function value(items) { return Array.isArray(items) ? (items.length ? items.join('；') : '无') : items || '无' }
</script>
<template>
  <section class="final-outline-panel" aria-labelledby="final-outline-title">
    <h2 id="final-outline-title">本章小纲</h2>
    <dl><template v-for="(label, key) in labels" :key="key"><dt>{{ label }}</dt><dd>{{ value(outline[key]) }}</dd></template></dl>
  </section>
</template>
<style scoped>
.final-outline-panel { max-width: 48rem; margin: 0 auto; padding: 24px; border: 1px solid var(--nc-border); background: var(--nc-paper); }
.final-outline-panel h2 { margin-top: 0; font-family: Georgia, 'Noto Serif SC', serif; }.final-outline-panel dl { display: grid; gap: 12px; }.final-outline-panel dt { color: var(--nc-muted); font-size: .875rem; }.final-outline-panel dd { margin: 0; line-height: 1.75; }
</style>
