<script setup>
defineProps({
  title: {
    type: String,
    default: '此入口已升级或不存在',
  },
  description: {
    type: String,
    default: '请从项目库重新进入，系统不会把你带到错误的项目或模块。',
  },
})
</script>

<template>
  <section class="route-state-page">
    <section class="state-sheet" aria-labelledby="not-found-title">
      <p class="eyebrow">ROUTE NOT FOUND</p>
      <h1 id="not-found-title">{{ title }}</h1>
      <p>{{ description }}</p>
      <router-link class="primary-link" to="/projects">返回项目库</router-link>
    </section>
  </section>
</template>

<style scoped>
.route-state-page {
  display: grid;
  min-height: 100%;
  padding: clamp(24px, 6vw, 72px);
  place-items: center;
  color: #302a23;
  background: #f4efe4;
}
.state-sheet {
  width: min(680px, 100%);
  padding: clamp(28px, 6vw, 64px);
  border: 1px solid #d8cbb7;
  border-radius: 14px;
  background: #fffdf8;
  box-shadow: 0 24px 64px rgba(58, 43, 27, .08);
}
.eyebrow {
  margin: 0 0 12px;
  color: #9a3f32;
  font: 700 11px Georgia, serif;
  letter-spacing: .16em;
}
h1 {
  margin: 0;
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: clamp(30px, 5vw, 48px);
  font-weight: 600;
}
.state-sheet > p:not(.eyebrow) {
  margin: 18px 0 28px;
  color: #766c60;
  line-height: 1.8;
}
.primary-link {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  padding: 0 18px;
  border-radius: 8px;
  color: #fffdf8;
  background: #8f3d32;
  font-weight: 650;
  text-decoration: none;
}
.primary-link:focus-visible {
  outline: 3px solid rgba(143, 61, 50, .28);
  outline-offset: 3px;
}
</style>
