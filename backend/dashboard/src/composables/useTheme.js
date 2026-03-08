import { ref, computed, watchEffect, provide, inject } from 'vue'

const THEME_KEY = Symbol('theme')
const STORAGE_KEY = 'tp-theme'

export function createTheme() {
  const stored = localStorage.getItem(STORAGE_KEY)
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  const theme = ref(stored || (prefersDark ? 'dark' : 'light'))

  const isDark = computed(() => theme.value === 'dark')

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  watchEffect(() => {
    document.documentElement.setAttribute('data-theme', theme.value)
    localStorage.setItem(STORAGE_KEY, theme.value)
  })

  function provideTheme() {
    provide(THEME_KEY, { theme, isDark, toggleTheme })
  }

  return { theme, isDark, toggleTheme, provideTheme }
}

export function useTheme() {
  const ctx = inject(THEME_KEY)
  if (!ctx) throw new Error('Theme not provided. Wrap App with createTheme().')
  return ctx
}

export function getChartThemeColors() {
  const s = getComputedStyle(document.documentElement)
  const get = (v) => s.getPropertyValue(v).trim()
  return {
    bg: get('--tp-chart-bg') || '#1a1a2e',
    text: get('--tp-chart-text') || '#e0e0e0',
    grid: get('--tp-chart-grid') || '#2a2a4a',
    up: get('--tp-success') || '#34d399',
    down: get('--tp-danger') || '#f87171',
    accent: get('--tp-primary') || '#3b82f6',
    volume: get('--tp-chart-volume') || '#385263',
  }
}
