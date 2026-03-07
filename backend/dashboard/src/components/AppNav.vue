<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const sections = [
  { path: '/forex', label: 'Forex' },
  { path: '/polymarket', label: 'Polymarket' },
  { path: '/crypto', label: 'Crypto' },
]

const activeSection = computed(() => {
  const p = route.path
  if (p.startsWith('/polymarket')) return '/polymarket'
  if (p.startsWith('/crypto')) return '/crypto'
  return '/forex'
})
</script>

<template>
  <nav class="container-fluid">
    <ul>
      <li><strong>Quant Platform</strong></li>
    </ul>
    <ul>
      <li v-for="s in sections" :key="s.path">
        <RouterLink
          :to="s.path"
          :class="{ contrast: activeSection === s.path }"
          style="font-weight: 600;"
        >
          {{ s.label }}
        </RouterLink>
      </li>
    </ul>
  </nav>
</template>
