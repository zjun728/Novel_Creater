<script setup>
defineProps({
  archived: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['create'])
</script>

<template>
  <div class="project-empty">
    <span aria-hidden="true">{{ archived ? '藏' : '始' }}</span>
    <h2>{{ archived ? '没有已归档项目' : '从一个名字开始' }}</h2>
    <p>
      {{ archived
        ? '归档的项目会完整保留正文、工作稿与候选，并出现在这里。'
        : '新建项目只需要名称，其他创作决定都可以进入项目后再完成。' }}
    </p>
    <button v-if="!archived" type="button" @click="$emit('create')">新建项目</button>
  </div>
</template>

<style scoped>
.project-empty {
  display: grid;
  min-height: 280px;
  padding: 44px 24px;
  place-items: center;
  align-content: center;
  border: 1px dashed #cdbda6;
  border-radius: 12px;
  color: var(--nc-muted, #766c60);
  text-align: center;
  background: rgba(255, 253, 248, .62);
}

.project-empty > span {
  display: grid;
  width: 54px;
  height: 54px;
  margin-bottom: 16px;
  place-items: center;
  border: 1px solid rgba(143, 61, 50, .28);
  border-radius: 50%;
  color: var(--nc-vermilion, #8f3d32);
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 20px;
}

.project-empty h2 {
  margin: 0;
  color: var(--nc-ink, #302a23);
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 24px;
  font-weight: 600;
}

.project-empty p {
  max-width: 480px;
  margin: 10px 0 22px;
  line-height: 1.7;
}

.project-empty button {
  min-height: 40px;
  padding: 0 18px;
  border: 0;
  border-radius: 7px;
  color: #fffaf0;
  background: var(--nc-vermilion, #8f3d32);
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}

.project-empty button:focus-visible {
  outline: 3px solid rgba(143, 61, 50, .25);
  outline-offset: 3px;
}
</style>
