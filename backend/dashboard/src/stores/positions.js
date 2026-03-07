import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'

export const usePositionsStore = defineStore('positions', () => {
  const positions = ref([])

  const totalProfit = computed(() =>
    positions.value.reduce((s, p) => s + (p.profit || 0), 0)
  )

  const totalSwap = computed(() =>
    positions.value.reduce((s, p) => s + (p.swap || 0), 0)
  )

  async function fetchPositions(magic) {
    const data = await api.getPositions(magic)
    positions.value = Array.isArray(data) ? data : (data.positions || [])
    return positions.value
  }

  return { positions, totalProfit, totalSwap, fetchPositions }
})
