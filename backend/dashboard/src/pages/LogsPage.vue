<script setup>
import { ref, watch, nextTick } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'

const lines = ref('200')
const autoScroll = ref(true)
const logs = ref([])
const status = ref('')
const viewerEl = ref(null)

async function refresh() {
  try {
    const data = await api.django(`v1/logs/?lines=${lines.value}`)
    if (!data.logs || data.logs.length === 0) {
      logs.value = []
      status.value = 'Empty log'
      return
    }
    logs.value = data.logs
    status.value = `${data.logs.length} lines -- updated ${new Date().toLocaleTimeString()}`
  } catch (err) {
    status.value = `Error: ${err.message}`
  }
}

usePolling(refresh, 5000)

watch(logs, async () => {
  if (autoScroll.value && viewerEl.value) {
    await nextTick()
    viewerEl.value.scrollTop = viewerEl.value.scrollHeight
  }
})

function logClass(line) {
  const trimmed = line.trimEnd()
  if (trimmed.startsWith('ERROR')) return 'log-error'
  if (trimmed.startsWith('WARNING')) return 'log-warning'
  if (trimmed.startsWith('INFO')) return 'log-info'
  return ''
}
</script>

<template>
  <h2>Bot Logs</h2>
  <div style="display:flex;gap:1rem;align-items:center;margin-bottom:1rem;">
    <label style="margin:0;">
      Lines
      <select v-model="lines" @change="refresh">
        <option value="100">100</option>
        <option value="200">200</option>
        <option value="500">500</option>
        <option value="1000">1000</option>
      </select>
    </label>
    <label style="margin:0;display:flex;align-items:center;gap:0.4rem;">
      <input v-model="autoScroll" type="checkbox" role="switch">
      Auto-scroll
    </label>
    <small style="margin-left:auto;color:var(--pico-muted-color);">{{ status }}</small>
  </div>
  <pre ref="viewerEl" class="log-viewer"><template
    v-for="(line, i) in logs" :key="i"
  ><span :class="logClass(line)">{{ line.trimEnd() }}</span>{{ '\n' }}</template></pre>
</template>
