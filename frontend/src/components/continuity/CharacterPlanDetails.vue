<script setup>
defineProps({ design: { type: Object, required: true } })
const dimensions = { stage: '计划阶段', goal: '目标', belief: '信念', relationship: '关系', ability: '能力' }
</script>

<template>
  <section class="character-plan" aria-label="人物计划节点">
    <h4>{{ design.displayName }} · 人物计划</h4>
    <p class="binding-label">{{ design.entityId ? '已明确关联正文人物' : '尚未关联正文人物' }} · 以下节点均为创作意图</p>
    <ol>
      <li v-for="node in design.nodes" :key="node.id">
        <h5>{{ node.title }}</h5>
        <p v-if="node.expectedChapter" class="binding-label">预计第 {{ node.expectedChapter }} 章 · 不代表已发生</p>
        <dl><template v-for="(label, field) in dimensions" :key="field"><dt v-if="node[field]">{{ label }}</dt><dd v-if="node[field]">{{ node[field] }}</dd></template></dl>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.character-plan{padding:14px 18px;margin:14px 0;background:var(--nc-canvas);border-left:2px solid var(--nc-vermilion)}h4{font-size:15px;margin:0 0 8px}h5{font-size:14px;margin:12px 0}.binding-label{color:var(--nc-muted);font-size:12px;line-height:1.8}ol{margin:0;padding-left:20px}li{padding:2px 0 10px}dl{display:grid;grid-template-columns:80px minmax(0,1fr);gap:8px;line-height:1.8;font-size:13px}dt{color:var(--nc-muted)}dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}
</style>
