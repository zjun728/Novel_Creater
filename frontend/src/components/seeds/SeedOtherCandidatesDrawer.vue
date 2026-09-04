<script setup>
import { computed } from 'vue'
const props = defineProps({ seeds: { type: Array, default: () => [] } })
const candidates = computed(() => props.seeds.filter(seed => !seed.isSelected))
</script>
<template><details v-if="candidates.length" class="seed-other-candidates"><summary>其他候选（只读）</summary><p>这些是不同候选，不是当前种子的版本历史；确认后不再允许切换。</p><article v-for="seed in candidates" :key="seed.id"><strong>{{ seed.payload?.title || '未命名候选' }}</strong><span>{{ seed.payload?.genre || '题材未填写' }}</span><small>{{ seed.payload?.logline || '尚未记录一句话故事。' }}</small></article></details></template>
<style scoped>.seed-other-candidates{box-sizing:border-box;max-width:100%;min-width:0;border-top:1px solid var(--nc-border);padding:14px 0;color:var(--nc-ink);overflow-wrap:anywhere;touch-action:pan-y;overscroll-behavior:auto}summary{cursor:pointer;color:var(--nc-vermilion);font:700 13px Georgia,'Noto Serif SC',serif}p,small{color:var(--nc-muted);font:12px/1.65 Georgia,'Noto Serif SC',serif}article{display:grid;min-width:0;gap:4px;margin-top:10px;padding:10px;border:1px solid var(--nc-border);background:var(--nc-paper)}article strong{font:600 14px Georgia,'Noto Serif SC',serif}article span{color:var(--nc-vermilion);font-size:12px}</style>
