<script setup>
defineProps({
  kicker: { type: String, default: 'CURRENT MANUSCRIPT' },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  genre: { type: String, default: '' },
  archived: { type: Boolean, default: false },
})
</script>

<template>
  <header class="project-page-header">
    <div class="project-page-header__identity">
      <p class="project-page-header__kicker">{{ kicker }}</p>
      <div class="project-page-header__title-line">
        <h1>{{ title }}</h1>
        <span v-if="archived" class="project-page-header__archive">已归档 · 只读</span>
      </div>
      <p v-if="description" class="project-page-header__description">{{ description }}</p>
    </div>
    <p v-if="genre" class="project-page-header__genre">{{ genre }}</p>
  </header>
</template>

<style scoped>
.project-page-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 24px;
  align-items: start;
  padding-bottom: 28px;
  border-bottom: 1px solid var(--nc-border);
}

.project-page-header__identity {
  min-width: 0;
}

.project-page-header__kicker {
  margin: 0 0 10px;
  color: var(--nc-vermilion);
  font: 700 10px Georgia, 'Noto Serif SC', serif;
  letter-spacing: .18em;
}

.project-page-header__title-line {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  align-items: center;
}

.project-page-header h1 {
  margin: 0;
  overflow-wrap: anywhere;
  font-family: Georgia, 'Noto Serif SC', 'Songti SC', serif;
  font-size: clamp(34px, 5vw, 54px);
  font-weight: 600;
  letter-spacing: -.035em;
  line-height: 1.15;
}

.project-page-header__archive,
.project-page-header__genre {
  width: fit-content;
  border: 1px solid var(--nc-border);
  border-radius: 999px;
  color: var(--nc-muted);
  background: rgba(244, 239, 228, .72);
  font-size: 12px;
}

.project-page-header__archive {
  padding: 5px 10px;
}

.project-page-header__genre {
  margin: 23px 0 0;
  padding: 7px 12px;
  white-space: nowrap;
}

.project-page-header__description {
  max-width: 68ch;
  margin: 16px 0 0;
  color: var(--nc-muted);
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 16px;
  line-height: 1.9;
}

@media (max-width: 640px) {
  .project-page-header { grid-template-columns: 1fr; gap: 12px; }
  .project-page-header__genre { margin: 0; }
}
</style>
