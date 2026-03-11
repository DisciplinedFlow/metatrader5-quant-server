import { ref } from 'vue'
import api from '@/services/api'

export function useHMMRegime() {
  const data = ref(null)
  const loading = ref(false)
  const error = ref(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      data.value = await api.getHMMRegimes()
    } catch (err) {
      error.value = err.message || 'Failed to load HMM regimes'
      console.error('HMM regime fetch error:', err)
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, fetch }
}
