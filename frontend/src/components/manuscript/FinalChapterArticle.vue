<script setup>
import { computed } from 'vue'

const props = defineProps({ content: { type: String, required: true } })
const paragraphs = computed(() => props.content.replace(/\r\n?/gu, '\n').split(/\n[\t ]*\n+/u).filter(value => value.trim().length > 0))
</script>

<template>
  <article class="final-chapter-article" aria-label="定稿正文">
    <p v-for="(paragraph, index) in paragraphs" :key="index">{{ paragraph }}</p>
  </article>
</template>

<style scoped>
.final-chapter-article { max-width: 42em; margin: 0 auto; font-size: 1.125rem; line-height: 1.9; }
.final-chapter-article p { margin: 0 0 1.5em; white-space: pre-wrap; }
</style>
