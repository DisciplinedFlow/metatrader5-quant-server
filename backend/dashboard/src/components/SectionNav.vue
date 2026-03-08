<script setup>
defineProps({
  links: {
    type: Array,
    required: true,
  },
})
</script>

<template>
  <nav class="tp-tabs">
    <RouterLink v-for="link in links" :key="link.to" :to="link.to">
      {{ link.label }}
    </RouterLink>
  </nav>
</template>
