<script setup>
import AppNav from '@/components/AppNav.vue'
import ToastContainer from '@/components/ToastContainer.vue'
import { createToast } from '@/composables/useToast'

const { toasts, provideToast } = createToast()
provideToast()
</script>

<template>
  <AppNav />
  <main class="container">
    <RouterView />
  </main>
  <ToastContainer :toasts="toasts" />
</template>
