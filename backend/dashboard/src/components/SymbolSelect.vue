<script setup>
import { useSymbols } from '@/composables/useSymbols'

const props = defineProps({
  modelValue: { type: String, default: 'EURUSD' },
})

const emit = defineEmits(['update:modelValue'])

const { symbols, loading } = useSymbols()
</script>

<template>
  <select
    :value="modelValue"
    :aria-busy="loading"
    @change="emit('update:modelValue', $event.target.value)"
  >
    <option v-if="symbols.length === 0" :value="modelValue">{{ modelValue }}</option>
    <option v-for="s in symbols" :key="s" :value="s" :selected="s === modelValue">{{ s }}</option>
  </select>
</template>
