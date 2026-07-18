<script setup>
defineProps({
  blocking: {
    type: Boolean,
    default: false,
  },
})
</script>

<template>
  <div class="app-interaction-boundary" :inert="blocking || undefined">
    <slot />
  </div>
  <slot name="overlay" />
</template>
