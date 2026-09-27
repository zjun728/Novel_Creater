<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
const route = useRoute()
const bindingPath = computed(() => typeof route.query.projectId === 'string' ? `/projects/${encodeURIComponent(route.query.projectId)}/settings/models` : '/projects')
import ProviderSettings from '../components/settings/ProviderSettings.vue'
</script>

<template>
  <section class="provider-route">
    <header class="route-heading">

      <h1>服务商与模型</h1>
      <span>私密配置只写入本机后端，页面仅显示是否已配置的安全摘要。</span>
      <nav aria-label="设置页面">
        <router-link to="/settings/providers" aria-current="page">服务商与模型</router-link>
        <router-link to="/settings/application">应用默认与诊断</router-link>
      </nav>
    </header>
    <section class="settings-sheet">
      <provider-settings />
    </section>
    <footer class="settings-return"><span>新增与测试不会修改已生成的作品内容。</span><router-link :to="bindingPath">{{ route.query.projectId ? '返回项目模型绑定' : '选择项目并绑定模型' }}</router-link></footer>
  </section>
</template>

<style scoped>
.provider-route {
  min-height: 100%;
  padding: 24px 36px;
  color: #302a23;
  background: var(--nc-canvas);
}
.route-heading,
.settings-sheet {
  width: min(1120px, 100%);
  margin-inline: auto;
}
.route-heading {
  padding-bottom: 12px;
  border-bottom: 1px solid #d4c7b2;
}
.route-heading p {
  margin: 0;
  color: #9a3f32;
  font: 700 10px Georgia, serif;
  letter-spacing: .17em;
}
.route-heading h1 {
  margin: 8px 0 0;
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: 30px;
  font-weight: 600;
}
.route-heading span {
  display: block;
  margin-top: 10px;
  color: #766c60;
  line-height: 1.7;
}
.route-heading nav { display: flex; gap: 8px; margin-top: 18px; }
.route-heading nav a { padding: 7px 12px; border: 1px solid #d5c7b1; border-radius: 999px; color: #6f6153; font-size: 12px; text-decoration: none; }
.route-heading nav a[aria-current='page'] { border-color: #8f3d32; color: #7d3128; background: #efe2d3; }
.settings-sheet {
  margin-top: 24px;
  padding: 20px;
  border: 1px solid #d8cbb7;
  border-radius: 14px;
  background: #fffdf8;
  box-shadow: 0 20px 56px rgba(58, 43, 27, .07);
}
.settings-return{display:flex;justify-content:space-between;align-items:center;gap:20px;max-width:1120px;margin:24px auto;padding:20px;background:var(--nc-paper);font-size:13px;color:var(--nc-muted)}.settings-return a{padding:12px 24px;background:var(--nc-vermilion);color:white;border-radius:6px;text-decoration:none}
</style>
