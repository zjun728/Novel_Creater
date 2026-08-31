<script setup>
defineProps({ seed: { type: Object, required: true }, readOnly: { type: Boolean, default: false }, busy: { type: Boolean, default: false } })
const emit = defineEmits(['open', 'archive', 'restore', 'delete'])
</script>

<template>
  <article class="seed-card">
    <span>{{ seed.payload?.genre || '题材未填写' }}</span>
    <strong>{{ seed.payload?.title || '未命名候选' }}</strong>
    <small>{{ seed.payload?.logline || '尚未写下一句话故事。' }}</small>
    <button type="button" class="seed-card__open" :disabled="busy" @click="emit('open', seed)">查看完整内容 →</button>
    <footer v-if="!readOnly && !seed.isSelected"><button v-if="seed.capabilities?.canArchive" type="button" :disabled="busy" @click="emit('archive', seed)">归档</button><button v-if="seed.capabilities?.canRestore" type="button" :disabled="busy" @click="emit('restore', seed)">恢复</button><button v-if="seed.capabilities?.canPermanentlyDelete" type="button" :disabled="busy" @click="emit('delete', seed)">永久删除</button></footer>
  </article>
</template>

<style scoped>
.seed-card{display:grid;width:100%;gap:5px;padding:12px;border:1px solid var(--nc-border);color:var(--nc-ink);background:var(--nc-paper);font:inherit;text-align:left}.seed-card:hover{border-left:3px solid var(--nc-vermilion);background:color-mix(in srgb,var(--nc-paper) 76%,var(--nc-canvas))}.seed-card button{width:max-content;border:0;padding:0;color:var(--nc-vermilion);background:transparent;cursor:pointer}.seed-card__open{margin-top:2px;font-size:11px}.seed-card footer{display:flex;gap:12px}.seed-card strong{font:600 15px Georgia,'Noto Serif SC',serif}.seed-card small{color:var(--nc-muted);font:12px/1.55 Georgia,'Noto Serif SC',serif}
</style>
