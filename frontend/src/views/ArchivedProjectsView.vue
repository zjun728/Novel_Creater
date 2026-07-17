<script setup>
import { onMounted, ref } from 'vue'
import { NAlert, NEmpty, NSkeleton } from 'naive-ui'

import { useProjectStore } from '../stores/projectStore.js'

const projectStore = useProjectStore()
const loading = ref(true)
const loadError = ref('')

async function loadArchivedProjects() {
  loading.value = true
  loadError.value = ''
  try {
    await projectStore.loadArchivedProjects()
  } catch (error) {
    loadError.value = error.message || '已归档项目加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadArchivedProjects)
</script>

<template>
  <main class="archive-page">
    <header class="archive-heading">
      <p>ARCHIVED WORKS</p>
      <h1>已归档项目</h1>
      <router-link to="/projects">返回项目库</router-link>
    </header>
    <section class="archive-sheet" aria-live="polite">
      <template v-if="loading">
        <n-skeleton text width="24%" />
        <n-skeleton text :repeat="3" />
      </template>
      <n-alert v-else-if="loadError" type="error" :bordered="false">{{ loadError }}</n-alert>
      <n-empty
        v-else-if="!projectStore.archivedProjects.length"
        description="目前没有已归档项目。"
      />
      <p v-else class="project-count">共有 {{ projectStore.archivedProjects.length }} 个已归档项目</p>
    </section>
  </main>
</template>

<style scoped>
.archive-page {
  min-height: 100%;
  padding: clamp(24px, 5vw, 64px);
  color: #302a23;
  background: #f4efe4;
}
.archive-heading,
.archive-sheet {
  width: min(1040px, 100%);
  margin-inline: auto;
}
.archive-heading {
  position: relative;
  padding-bottom: 24px;
  border-bottom: 1px solid #d4c7b2;
}
.archive-heading p {
  margin: 0;
  color: #9a3f32;
  font: 700 10px Georgia, serif;
  letter-spacing: .17em;
}
.archive-heading h1 {
  margin: 8px 0 0;
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: clamp(36px, 6vw, 58px);
  font-weight: 600;
}
.archive-heading a {
  display: inline-flex;
  margin-top: 12px;
  color: #8f3d32;
  font-weight: 650;
  text-underline-offset: 4px;
}
.archive-sheet {
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
