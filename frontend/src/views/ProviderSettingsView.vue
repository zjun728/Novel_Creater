<script setup>
import ProviderSettings from '../components/settings/ProviderSettings.vue'
</script>

<template>
  <main class="provider-route">
    <header class="route-heading">
      <p>LOCAL MODEL SETTINGS</p>
      <h1>Provider 与模型</h1>
      <span>私密配置只写入本机后端，页面仅显示是否已配置的安全摘要。</span>
    </header>
    <section class="settings-sheet">
      <provider-settings />
    </section>
  </main>
</template>

<style scoped>
.provider-route {
  min-height: 100%;
  padding: clamp(22px, 4vw, 48px);
  color: #302a23;
  background: #f4efe4;
}
.route-heading,
.settings-sheet {
  width: min(1120px, 100%);
  margin-inline: auto;
}
.route-heading {
  padding-bottom: 24px;
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
  font-size: clamp(32px, 5vw, 50px);
  font-weight: 600;
}
.route-heading span {
  display: block;
  margin-top: 10px;
  color: #766c60;
  line-height: 1.7;
}
.settings-sheet {
  margin-top: 24px;
  padding: clamp(18px, 3vw, 32px);
  border: 1px solid #d8cbb7;
  border-radius: 14px;
  background: #fffdf8;
  box-shadow: 0 20px 56px rgba(58, 43, 27, .07);
}
</style>
