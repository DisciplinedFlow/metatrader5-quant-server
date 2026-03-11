import { ref } from 'vue'
import api from '@/services/api'

export function useConfluenceScore() {
  const data = ref(null)
  const loading = ref(false)
  const error = ref(null)

  async function fetch(limit = 200) {
    loading.value = true
    error.value = null
    try {
      data.value = await api.getConfluenceScores(limit)
    } catch (err) {
      error.value = err.message || 'Failed to load confluence scores'
      console.error('Confluence score fetch error:', err)
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, fetch }
}
