<script setup>
import { onMounted, ref, watch, nextTick } from 'vue'

const props = defineProps({
  toasts: { type: Array, required: true },
})

const shown = ref(new Set())

watch(() => props.toasts.length, async () => {
  await nextTick()
  for (const t of props.toasts) {
    if (!shown.value.has(t.id)) {
      shown.value.add(t.id)
      await nextTick()
      requestAnimationFrame(() => {
        shown.value = new Set(shown.value)
      })
    }
  }
})
</script>

<template>
  <div class="toast-container">
    <div
      v-for="t in toasts"
      :key="t.id"
      :class="['toast', `toast-${t.type}`, { show: shown.has(t.id) }]"
    >
      {{ t.message }}
    </div>
  </div>
</template>
