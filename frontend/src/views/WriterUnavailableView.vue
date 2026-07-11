<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const projectPath = computed(() => `/project/${encodeURIComponent(String(route.params.projectId || ''))}`)
</script>

<template>
  <main class="unavailable-shell">
    <section class="unavailable-card" aria-labelledby="writer-unavailable-heading">
      <div class="folio">M1 · FOUNDATION</div>
      <div class="seal" aria-hidden="true">稿</div>
      <h1 id="writer-unavailable-heading">写作内核尚未开放</h1>
      <p class="lead">旧章节、临时草稿和版本定稿链已停用。</p>
      <p class="detail">
        当前里程碑只展示项目、种子、Canon 与投影的真实状态。章节会话、工作稿和候选体系将在各自里程碑验收后重新开放。
      </p>
      <router-link :to="projectPath" class="back-link">
        <span aria-hidden="true">←</span>
        返回项目
      </router-link>
    </section>
  </main>
</template>

<style scoped>
.unavailable-shell { min-height: 100%; display: grid; place-items: center; padding: 40px 24px; background: #f3eee3; }
.unavailable-card { position: relative; width: min(620px, 100%); padding: 46px; overflow: hidden; border: 1px solid #d7ccb7; border-radius: 14px; background: #fffdf7; box-shadow: 0 22px 70px rgba(61, 51, 37, .12); }
.folio { color: #9b7d53; font-size: 11px; font-weight: 800; letter-spacing: .2em; }
.seal { position: absolute; top: 30px; right: 36px; display: grid; width: 48px; height: 48px; place-items: center; border: 2px solid #a04b3f; color: #a04b3f; font-family: 'Noto Serif SC', serif; font-size: 23px; transform: rotate(-4deg); }
h1 { margin: 24px 0 12px; color: #2e2923; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(28px, 5vw, 40px); font-weight: 650; }
.lead { margin: 0; color: #4d463d; font-size: 17px; }
.detail { max-width: 52ch; margin: 22px 0 32px; color: #786d5e; line-height: 1.9; }
.back-link { display: inline-flex; align-items: center; gap: 9px; padding: 10px 15px; border: 1px solid #413a31; border-radius: 7px; color: #342f29; font-weight: 650; text-decoration: none; }
.back-link:hover, .back-link:focus-visible { background: #342f29; color: #fffdf7; outline: none; }
@media (max-width: 560px) { .unavailable-card { padding: 34px 26px; } .seal { right: 24px; } }
</style>
