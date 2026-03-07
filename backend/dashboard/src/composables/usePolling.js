import { onBeforeUnmount, ref } from 'vue'

export function usePolling(fn, intervalMs) {
  const active = ref(true)
  let timer = null

  function start() {
    fn()
    timer = setInterval(() => {
      if (active.value) fn()
    }, intervalMs)
  }

  function pause() {
    active.value = false
  }

  function resume() {
    active.value = true
  }

  start()

  onBeforeUnmount(() => {
    if (timer) clearInterval(timer)
  })

  return { pause, resume }
}
