<script setup>
import AppNav from '@/components/AppNav.vue'
import ToastContainer from '@/components/ToastContainer.vue'
import { createToast } from '@/composables/useToast'
import { createTheme } from '@/composables/useTheme'

const { toasts, provideToast } = createToast()
provideToast()

const { provideTheme } = createTheme()
provideTheme()
</script>

<template>
  <AppNav />
  <main class="container">
    <RouterView />
  </main>
  <ToastContainer :toasts="toasts" />
</template>
