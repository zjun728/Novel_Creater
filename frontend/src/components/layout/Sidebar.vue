<script setup>
defineProps({
  shell: {
    type: Object,
    required: true,
  },
})
</script>

<template>
  <aside
    class="product-sidebar"
    :class="{ 'product-sidebar--collapsed': shell.sidebarCollapsed }"
    :data-collapsed="String(shell.sidebarCollapsed)"
    aria-label="产品导航"
  >
    <router-link
      class="product-sidebar__brand"
      to="/projects"
      aria-label="Novel Creator 项目库"
    >
      <span class="product-sidebar__seal" aria-hidden="true">章</span>
      <span class="product-sidebar__brand-copy">
        <strong>Novel Creator</strong>
        <small>长篇创作台</small>
      </span>
    </router-link>

    <nav class="product-sidebar__global" aria-label="全局导航">
      <router-link
        v-for="item in shell.globalNavigation"
        :key="item.key"
        class="product-sidebar__nav-link"
        :class="{ 'product-sidebar__nav-link--selected': item.selected }"
        :to="item.path"
        :aria-label="item.label"
        :aria-current="item.selected ? 'page' : undefined"
      >
        <span class="product-sidebar__nav-mark" aria-hidden="true">{{ item.mark }}</span>
        <span class="product-sidebar__nav-label">{{ item.label }}</span>
      </router-link>
      <div
        v-if="shell.globalNavigation.find(item => item.key === 'assets')?.selected"
        class="product-sidebar__asset-subnav"
        aria-label="创作资产分类"
      >
        <router-link
          v-for="item in shell.assetNavigation"
          :key="item.key"
          :to="item.path"
          :class="{ 'product-sidebar__asset-link--selected': item.selected }"
          :aria-current="item.selected ? 'page' : undefined"
        >
          {{ item.label }}
        </router-link>
      </div>
    </nav>

    <section
      v-if="shell.projectContext"
      class="product-sidebar__project"
      :class="{ 'product-sidebar__project--archived': shell.projectContext.archived }"
      :aria-label="`当前项目：${shell.projectContext.title}`"
    >
      <div class="product-sidebar__project-heading">
        <span class="product-sidebar__project-kicker">CURRENT MANUSCRIPT</span>
        <strong class="product-sidebar__project-title">
          {{ shell.projectContext.title }}
        </strong>
        <span
          v-if="shell.projectContext.archived"
          class="product-sidebar__archive-mark"
        >
          已归档
        </span>
      </div>

      <nav
        v-if="shell.projectContext.modules.length"
        class="product-sidebar__modules"
        aria-label="项目模块"
      >
        <router-link
          v-for="module in shell.projectContext.modules"
          :key="module.key"
          class="product-sidebar__module-link"
          :class="{ 'product-sidebar__module-link--selected': module.selected }"
          :to="module.path"
          :aria-label="module.label"
          :aria-current="module.selected ? 'page' : undefined"
        >
          <span aria-hidden="true">{{ module.mark }}</span>
          <span>{{ module.label }}</span>
        </router-link>
      </nav>

      <p v-else class="product-sidebar__archive-note">
        只读保留，恢复后继续创作
      </p>
    </section>

    <p class="product-sidebar__local-note">
      <span aria-hidden="true"></span>
      <span>仅限本机</span>
    </p>
  </aside>
</template>

<style scoped>
.product-sidebar {
  display: flex;
  width: 248px;
  min-width: 248px;
  height: 100%;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #d8cbb7;
  color: #302a23;
  background:
    linear-gradient(rgba(255, 253, 248, .82), rgba(249, 244, 234, .94)),
    repeating-linear-gradient(0deg, transparent 0 30px, rgba(98, 77, 52, .025) 31px);
  transition: width .18s ease, min-width .18s ease;
}

.product-sidebar__brand {
  display: flex;
  min-height: 78px;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border-bottom: 1px solid rgba(216, 203, 183, .78);
  color: inherit;
  text-decoration: none;
}

.product-sidebar__seal {
  display: grid;
  width: 37px;
  height: 37px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid #9a483a;
  color: #8f3d32;
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 20px;
  line-height: 1;
  box-shadow: inset 0 0 0 3px #fffaf1;
  transform: rotate(-2deg);
}

.product-sidebar__brand-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.product-sidebar__brand-copy strong {
  overflow: hidden;
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: .02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-sidebar__brand-copy small {
  color: #817668;
  font-size: 11px;
  letter-spacing: .14em;
}

.product-sidebar__global,
.product-sidebar__modules {
  display: grid;
  gap: 4px;
}

.product-sidebar__global {
  padding: 15px 12px;
  border-bottom: 1px solid rgba(216, 203, 183, .72);
}

.product-sidebar__asset-subnav {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  padding: 3px 4px 4px 41px;
}

.product-sidebar__asset-subnav a {
  display: flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  padding: 5px 3px;
  border-bottom: 1px solid transparent;
  color: #85786a;
  font-size: 10px;
  text-align: center;
  text-decoration: none;
}

.product-sidebar__asset-subnav a:hover,
.product-sidebar__asset-link--selected {
  border-bottom-color: #8f3d32;
  color: #7d3128;
}

.product-sidebar__nav-link,
.product-sidebar__module-link {
  display: flex;
  min-height: 44px;
  align-items: center;
  gap: 11px;
  border-radius: 6px;
  color: #64594d;
  font-size: 13px;
  font-weight: 650;
  text-decoration: none;
  transition: color .14s ease, background .14s ease, transform .14s ease;
}

.product-sidebar__nav-link {
  padding: 0 11px;
}

.product-sidebar__nav-link:hover,
.product-sidebar__module-link:hover {
  color: #7f3229;
  background: rgba(143, 61, 50, .065);
}

.product-sidebar__nav-link:focus-visible,
.product-sidebar__module-link:focus-visible,
.product-sidebar__brand:focus-visible {
  outline: 3px solid rgba(143, 61, 50, .22);
  outline-offset: -2px;
}

.product-sidebar__nav-link--selected,
.product-sidebar__module-link--selected {
  color: #7d3128;
  background: #efe2d3;
  box-shadow: inset 3px 0 0 #8f3d32;
}

.product-sidebar__nav-mark {
  display: grid;
  width: 25px;
  height: 25px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid rgba(126, 102, 75, .24);
  border-radius: 50%;
  font-family: 'Noto Serif SC', 'Songti SC', serif;
  font-size: 11px;
}

.product-sidebar__project {
  min-height: 0;
  padding: 22px 12px;
  overflow-y: auto;
}

.product-sidebar__project-heading {
  display: grid;
  gap: 7px;
  padding: 0 8px 14px;
}

.product-sidebar__project-kicker {
  color: #9a7860;
  font: 700 9px Georgia, serif;
  letter-spacing: .15em;
}

.product-sidebar__project-title {
  overflow: hidden;
  color: #342d25;
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 15px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-sidebar__archive-mark {
  width: fit-content;
  padding: 3px 8px;
  border: 1px solid #c9b9a2;
  border-radius: 999px;
  color: #6f6253;
  font-size: 11px;
}

.product-sidebar__module-link {
  padding: 0 12px;
}

.product-sidebar__module-link > span:first-child {
  color: #a1715f;
  font-family: 'Noto Serif SC', 'Songti SC', serif;
}

.product-sidebar__archive-note {
  margin: 2px 8px 0;
  padding-top: 12px;
  border-top: 1px solid #ded2c0;
  color: #817668;
  font-size: 11px;
  line-height: 1.65;
}

.product-sidebar__local-note {
  display: flex;
  min-height: 48px;
  align-items: center;
  gap: 8px;
  margin: auto 0 0;
  padding: 0 20px;
  border-top: 1px solid rgba(216, 203, 183, .72);
  color: #887d70;
  font-size: 10px;
  letter-spacing: .08em;
}

.product-sidebar__local-note > span:first-child {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #70815d;
  box-shadow: 0 0 0 3px rgba(112, 129, 93, .11);
}

.product-sidebar--collapsed {
  width: 72px;
  min-width: 72px;
}

.product-sidebar--collapsed .product-sidebar__brand {
  justify-content: center;
  padding-inline: 0;
}

.product-sidebar--collapsed .product-sidebar__brand-copy,
.product-sidebar--collapsed .product-sidebar__nav-label,
.product-sidebar--collapsed .product-sidebar__project-kicker,
.product-sidebar--collapsed .product-sidebar__project-title,
.product-sidebar--collapsed .product-sidebar__archive-note,
.product-sidebar--collapsed .product-sidebar__local-note span:last-child {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.product-sidebar--collapsed .product-sidebar__global,
.product-sidebar--collapsed .product-sidebar__project {
  padding-inline: 10px;
}

.product-sidebar--collapsed .product-sidebar__asset-subnav {
  grid-template-columns: 1fr;
  padding: 2px 0 5px;
}

.product-sidebar--collapsed .product-sidebar__asset-subnav a {
  overflow: hidden;
  font-size: 0;
}

.product-sidebar--collapsed .product-sidebar__asset-subnav a::first-letter {
  font-size: 10px;
}

.product-sidebar--collapsed .product-sidebar__nav-link,
.product-sidebar--collapsed .product-sidebar__module-link {
  justify-content: center;
  padding: 0;
}

.product-sidebar--collapsed .product-sidebar__project-heading {
  min-height: 22px;
  justify-items: center;
  padding-inline: 0;
}

.product-sidebar--collapsed .product-sidebar__archive-mark {
  width: 30px;
  padding: 3px;
  overflow: hidden;
  text-align: center;
  white-space: nowrap;
}

.product-sidebar--collapsed .product-sidebar__archive-mark::first-letter {
  font-size: 11px;
}

.product-sidebar--collapsed .product-sidebar__local-note {
  justify-content: center;
  padding-inline: 0;
}

@media (prefers-reduced-motion: reduce) {
  .product-sidebar,
  .product-sidebar__nav-link,
  .product-sidebar__module-link {
    transition: none;
  }
}
</style>
