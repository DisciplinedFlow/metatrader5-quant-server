import { ref } from 'vue'
import api from '@/services/api'

let cached = null
let promise = null

export function useSymbols() {
  const symbols = ref([])
  const loading = ref(false)

  if (cached) {
    symbols.value = cached
  } else {
    loading.value = true
    if (!promise) {
      promise = api.getSymbols().then((data) => {
        cached = data
        return data
      }).catch((err) => {
        console.warn('Failed to load symbols:', err)
        return []
      })
    }
    promise.then((data) => {
      symbols.value = data
      loading.value = false
    })
  }

  return { symbols, loading }
}
