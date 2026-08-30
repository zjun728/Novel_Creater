<script setup>
import { computed } from 'vue'

import {
  topicCandidatesPath,
  topicDirectionsPath,
  topicDiscussionsPath,
  topicMarketPath,
} from '@/router/projectRoutes'

const props = defineProps({ activeSection: { type: String, required: true } })

const destinations = Object.freeze([
  { key: 'market', label: '市场热门', note: '查看公开榜单快照', path: topicMarketPath() },
  { key: 'discussions', label: 'AI 讨论', note: '从想法开始推演', path: topicDiscussionsPath() },
  { key: 'directions', label: '选题方向', note: '沉淀可行方向', path: topicDirectionsPath() },
  { key: 'candidates', label: '候选种子库', note: '管理项目候选', path: topicCandidatesPath() },
])

const current = computed(() => destinations.find(item => item.key === props.activeSection))
</script>

<template>
  <header class="topic-header">
    <div class="topic-header__identity">
      <p>EDITORIAL DISCOVERY · BEFORE PROJECT</p>
      <h1>选题中心</h1>
      <span>{{ current?.label }} · {{ current?.note }}。这里的成果只有经过你的明确保存，才进入方向库或候选种子库。</span>
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
        <small>{{ item.note }}</small>
      </router-link>
    </nav>
  </header>
</template>

<style scoped>
.topic-header { display:grid; gap:24px; }
.topic-header__identity p { margin:0; color:#9a4938; font:750 10px Georgia,serif; letter-spacing:.18em; }
.topic-header__identity h1 { margin:8px 0 6px; color:#302923; font:650 clamp(38px,5vw,58px) 'Noto Serif SC','Songti SC',Georgia,serif; letter-spacing:-.05em; }
.topic-header__identity span { display:block; max-width:760px; color:#786c5e; font-size:13px; line-height:1.75; }
.topic-nav { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border:1px solid #d8c9b5; background:rgba(247,240,229,.78); }
.topic-nav a { min-width:0; padding:14px 18px; border-right:1px solid #d8c9b5; color:#65594d; text-decoration:none; transition:background-color .16s ease,color .16s ease; }
.topic-nav a:last-child { border-right:0; }
.topic-nav a:hover,.topic-nav a.active { color:#8f3f31; background:#fffdf8; box-shadow:inset 0 3px #9a4938; }
.topic-nav strong,.topic-nav small { display:block; }
.topic-nav strong { font:650 15px 'Noto Serif SC','Songti SC',serif; }
.topic-nav small { margin-top:4px; overflow:hidden; font-size:10px; text-overflow:ellipsis; white-space:nowrap; }
@media(max-width:720px){.topic-nav{grid-template-columns:repeat(2,minmax(0,1fr))}.topic-nav a:nth-child(2){border-right:0}.topic-nav a:nth-child(-n+2){border-bottom:1px solid #d8c9b5}}
</style>
