<script setup>
defineProps({
  shell: {
    type: Object,
    required: true,
  },
})
</script>

<template>
  <header class="product-topbar">
    <div class="product-topbar__context">
      <nav
        v-if="shell.breadcrumbs.length"
        class="product-topbar__breadcrumbs"
        aria-label="面包屑"
      >
        <template v-for="(item, index) in shell.breadcrumbs" :key="item.path">
          <span v-if="index" aria-hidden="true">/</span>
          <router-link :to="item.path">{{ item.label }}</router-link>
        </template>
      </nav>
      <p v-else class="product-topbar__scope">
        {{ shell.globalNavigation.find(item => item.selected)?.label || '本机创作台' }}
      </p>
      <strong class="product-topbar__title">{{ shell.routeTitle }}</strong>
    </div>

    <div class="product-topbar__session" aria-label="当前运行模式">
      <strong
        v-if="shell.globalNavigation.find(item => item.key === 'assets')?.selected"
        class="product-topbar__asset-scope"
      >CREATIVE ASSETS</strong>
      <span aria-hidden="true"></span>
      本机单用户
    </div>
  </header>
</template>

<style scoped>
.product-topbar {
  display: flex;
  min-height: 78px;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 10px clamp(18px, 3vw, 36px);
  border-bottom: 1px solid #d8cbb7;
  color: #302a23;
  background: rgba(255, 253, 248, .9);
  backdrop-filter: blur(12px);
}

.product-topbar__context {
  display: grid;
  min-width: 0;
  gap: 5px;
}

.product-topbar__breadcrumbs {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  color: #8b7d6d;
  font-size: 11px;
}

.product-topbar__breadcrumbs a {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  overflow: hidden;
  color: inherit;
  text-decoration: none;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-topbar__breadcrumbs a:hover {
  color: #8f3d32;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.product-topbar__breadcrumbs a:focus-visible {
  border-radius: 2px;
  outline: 3px solid rgba(143, 61, 50, .22);
  outline-offset: 2px;
}

.product-topbar__scope {
  margin: 0;
  color: #9a7860;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .13em;
}

.product-topbar__title {
  overflow: hidden;
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 18px;
  font-weight: 650;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-topbar__session {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
  color: #817668;
  font-size: 11px;
}

.product-topbar__session > span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #70815d;
}

.product-topbar__asset-scope {
  margin-right: 4px;
  color: #8f6d4c;
  font: 700 9px Georgia, serif;
  letter-spacing: .13em;
}

@media (max-width: 620px) {
  .product-topbar {
    min-height: 68px;
    padding-inline: 16px;
  }

  .product-topbar__session {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
  }
}
</style>
