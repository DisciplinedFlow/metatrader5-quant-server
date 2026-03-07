<script setup>
defineProps({
  links: {
    type: Array,
    required: true,
  },
})
</script>

<template>
  <nav style="padding: 0.25rem 0; margin-bottom: 1rem; border-bottom: 1px solid var(--muted-border-color);">
    <ul style="margin: 0; padding: 0; list-style: none; display: flex; gap: 0.75rem;">
      <li v-for="link in links" :key="link.to">
        <RouterLink :to="link.to" style="font-size: 0.9rem;">{{ link.label }}</RouterLink>
      </li>
    </ul>
  </nav>
</template>
