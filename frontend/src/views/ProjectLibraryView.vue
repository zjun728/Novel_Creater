<script setup>
import { onMounted, ref } from 'vue'
import { NAlert, NEmpty, NSkeleton } from 'naive-ui'

import { useProjectStore } from '../stores/projectStore.js'

const projectStore = useProjectStore()
const loading = ref(true)
const loadError = ref('')

async function loadActiveProjects() {
  loading.value = true
  loadError.value = ''
  try {
    await projectStore.loadActiveProjects()
  } catch (error) {
    loadError.value = error.message || '项目库加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadActiveProjects)
</script>

<template>
  <main class="library-page">
    <header class="library-heading">
      <p>LONG-FORM FICTION DESK</p>
      <h1>项目库</h1>
      <span>在这里选择要继续创作的长篇小说项目。</span>
    </header>
    <section class="library-sheet" aria-live="polite">
      <template v-if="loading">
        <n-skeleton text width="24%" />
        <n-skeleton text :repeat="3" />
      </template>
      <n-alert v-else-if="loadError" type="error" :bordered="false">{{ loadError }}</n-alert>
      <n-empty
        v-else-if="!projectStore.activeProjects.length"
        description="项目库还是空的，下一步将在这里建立新项目。"
      />
      <p v-else class="project-count">已有 {{ projectStore.activeProjects.length }} 个活动项目</p>
    </section>
  </main>
</template>

<style scoped>
.library-page {
  min-height: 100%;
  padding: clamp(24px, 5vw, 64px);
  color: #302a23;
  background: #f4efe4;
}
.library-heading,
.library-sheet {
  width: min(1040px, 100%);
  margin-inline: auto;
}
.library-heading {
  padding-bottom: 24px;
  border-bottom: 1px solid #d4c7b2;
}
.library-heading p {
  margin: 0;
  color: #9a3f32;
  font: 700 10px Georgia, serif;
  letter-spacing: .17em;
}
.library-heading h1 {
  margin: 8px 0 0;
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: clamp(36px, 6vw, 58px);
  font-weight: 600;
}
.library-heading span {
  display: block;
  margin-top: 10px;
  color: #766c60;
}
.library-sheet {
  min-height: 220px;
  margin-top: 24px;
  padding: clamp(24px, 4vw, 42px);
  border: 1px solid #d8cbb7;
  border-radius: 14px;
  background: #fffdf8;
  box-shadow: 0 20px 56px rgba(58, 43, 27, .07);
}
.project-count {
  margin: 0;
  color: #62584c;
  font-family: 'Noto Serif SC', serif;
}
</style>
