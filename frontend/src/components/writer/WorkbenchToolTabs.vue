<script setup>
defineProps({ modelValue: { type: String, default: 'assistant' }, count: { type: Number, default: null }, prefix: { type: String, default: 'tool' } })
const emit = defineEmits(['update:modelValue'])
const tabs = [{ key: 'assistant', label: '助手' }, { key: 'review', label: '审稿' }, { key: 'reference', label: '参考' }, { key: 'versions', label: '版本' }]
function move(event, index) {
  const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null
  if (next === null) return
  event.preventDefault()
  event.currentTarget.parentElement.children[next].focus()
  emit('update:modelValue', tabs[next].key)
}
</script>
<template>
  <div class="workbench-tabs" role="tablist" aria-label="章节工具">
    <button v-for="(tab, index) in tabs" :id="`${prefix}-tab-${tab.key}`" :key="tab.key" role="tab" :aria-selected="modelValue === tab.key" :aria-controls="`${prefix}-panel-${tab.key}`" :tabindex="modelValue === tab.key ? 0 : -1" @click="emit('update:modelValue', tab.key)" @keydown="move($event, index)">{{ tab.label }}<small v-if="tab.key === 'versions' && count !== null"> {{ count }}</small></button>
  </div>
</template>
<style scoped>
.workbench-tabs { position:sticky; top:0; z-index:3; display:flex; gap:4px; background:var(--nc-paper); padding:8px; border-bottom:1px solid var(--nc-border); }
.workbench-tabs button { flex:1; min-width:0; padding:8px 2px; border:0; border-bottom:2px solid transparent; color:var(--nc-ink); background:transparent; font:inherit; cursor:pointer; }
.workbench-tabs button[aria-selected=true] { border-color:var(--nc-vermilion); color:var(--nc-vermilion); }
.workbench-tabs button:focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:-2px; }
</style>
