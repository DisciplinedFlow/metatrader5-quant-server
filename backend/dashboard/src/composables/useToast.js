import { ref, provide, inject } from 'vue'

const TOAST_KEY = Symbol('toast')
let nextId = 0

export function createToast() {
  const toasts = ref([])

  function add(message, type = 'info', duration = 4000) {
    const id = nextId++
    toasts.value.push({ id, message, type })
    setTimeout(() => {
      toasts.value = toasts.value.filter((t) => t.id !== id)
    }, duration)
  }

  const toast = {
    success: (msg) => add(msg, 'success'),
    error: (msg) => add(msg, 'error'),
    info: (msg) => add(msg, 'info'),
  }

  function provideToast() {
    provide(TOAST_KEY, toast)
  }

  return { toasts, toast, provideToast }
}

export function useToast() {
  const toast = inject(TOAST_KEY)
  if (!toast) throw new Error('Toast not provided. Wrap App with createToast().')
  return toast
}
