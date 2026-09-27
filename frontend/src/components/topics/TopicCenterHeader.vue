<script setup>


import {
  topicCandidatesPath,
  topicDirectionsPath,
  topicDiscussionsPath,
  topicMarketPath,
} from '@/router/projectRoutes'

const props = defineProps({ activeSection: { type: String, required: true } })

const destinations = Object.freeze([
  { key: 'market', label: '热门选题建议', note: '按类型获取参考与建议', path: topicMarketPath() },
  { key: 'discussions', label: 'AI 讨论', note: '从想法开始推演', path: topicDiscussionsPath() },
  { key: 'directions', label: '选题方向', note: '沉淀可行方向', path: topicDirectionsPath() },
  { key: 'candidates', label: '候选种子', note: '管理项目候选', path: topicCandidatesPath() },
])


</script>

<template>
  <header class="topic-header">
    <div class="topic-header__identity">

      <h1 id="topic-center-page-title">选题中心</h1>
      <span>{{ activeSection === 'market' ? '先选择创作类型，再让系统分析市场并提出创作建议。' : '让一个值得写的想法，成为你的下一部作品。' }}</span>
    </div>
    <nav class="topic-nav" aria-label="选题中心功能">
      <router-link
        v-for="item in destinations"
        :key="item.key"
        :to="item.path"
        :aria-current="activeSection === item.key ? 'page' : undefined"
        :class="{ active: activeSection === item.key }"
      >
        <strong>{{ item.label }}</strong>

      </router-link>
    </nav>
  </header>
</template>

<style scoped>
.topic-header{display:grid;gap:24px}.topic-header__identity h1{margin:0 0 3px;color:#302d28;font:600 30px/46px 'Noto Serif SC','Songti SC',serif}.topic-header__identity span{color:#6f685e;font-size:14px;line-height:22px}
.topic-nav{display:flex;gap:10px;border-bottom:1px solid #ddd5c8;height:40px}.topic-nav a{position:relative;display:flex;align-items:flex-start;justify-content:flex-start;min-width:0;width:154px;color:#6f685e;text-decoration:none}.topic-nav strong{font-size:15px;font-weight:500}.topic-nav a.active{color:#934735}.topic-nav a.active:after{position:absolute;bottom:-1px;width:100px;height:3px;background:#934735;content:''}.topic-nav a:hover{color:#934735}
@media(max-width:720px){.topic-nav{gap:0}.topic-nav a{flex:1}.topic-nav strong{font-size:13px}.topic-nav a.active:after{width:75%}}
@media(min-width:1120px) and (max-height:820px){.topic-header{gap:12px}.topic-header__identity h1{font-size:28px;line-height:36px}.topic-header__identity span{line-height:18px;font-size:13px}.topic-nav{height:32px}}
</style>
