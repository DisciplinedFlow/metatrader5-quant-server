<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme } from '@/composables/useTheme'

const route = useRoute()
const { isDark, toggleTheme } = useTheme()

const sections = [
  { path: '/forex', label: 'Forex' },
  { path: '/crypto', label: 'Crypto' },
  { path: '/ai-brain', label: 'AI Brain' },
  { path: '/ml', label: 'ML' },
]

const activeSection = computed(() => {
  const p = route.path
  if (p.startsWith('/crypto')) return '/crypto'
  if (p.startsWith('/ai-brain')) return '/ai-brain'
  if (p.startsWith('/ml')) return '/ml'
  return '/forex'
})
</script>

<template>
  <nav class="tp-nav container-fluid">
    <ul>
      <li><strong class="tp-brand"><span class="brand-full">Quant Platform</span><span class="brand-short">QP</span></strong></li>
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
      <li>
        <button class="tp-theme-toggle" @click="toggleTheme" :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'">
          <span class="material-symbols-outlined">{{ isDark ? 'light_mode' : 'dark_mode' }}</span>
        </button>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.tp-nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
  border-bottom: var(--tp-glass-border);
}

.tp-brand {
  background: var(--tp-gradient-primary);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-size: 1.1rem;
  letter-spacing: -0.025em;
  white-space: nowrap;
}

.brand-short { display: none; }

@media (max-width: 480px) {
  .brand-full { display: none; }
  .brand-short { display: inline; }
  .tp-nav {
    padding-inline: 0.75rem;
  }
  .tp-nav :deep(a) {
    font-size: 0.8rem;
  }
  .tp-theme-toggle {
    padding: 0.25rem 0.35rem;
  }
  .tp-theme-toggle .material-symbols-outlined {
    font-size: 16px;
  }
}

.tp-theme-toggle {
  background: none;
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  color: var(--tp-text-muted);
  cursor: pointer;
  padding: 0.35rem 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  line-height: 1;
}

.tp-theme-toggle:hover {
  color: var(--tp-primary);
  border-color: var(--tp-primary);
  box-shadow: 0 0 12px var(--tp-primary-glow);
}

.tp-theme-toggle .material-symbols-outlined {
  font-size: 20px;
}
</style>
