<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { usePolling } from '@/composables/usePolling'
import SectionNav from '@/components/SectionNav.vue'
import api from '@/services/api'

const forexLinks = [
  { to: '/forex', label: 'Overview' },
  { to: '/forex/positions', label: 'Positions' },
  { to: '/forex/order', label: 'Order' },
  { to: '/forex/history', label: 'History' },
  { to: '/forex/chart', label: 'Chart' },
  { to: '/forex/logs', label: 'Logs' },
  { to: '/forex/strategy', label: 'Strategies' },
  { to: '/forex/performance', label: 'Performance' },
]

const lines = ref('200')
const autoScroll = ref(true)
const logs = ref([])
const status = ref('')
const viewerEl = ref(null)
const searchQuery = ref('')
const showInfo = ref(true)
const showWarning = ref(true)
const showError = ref(true)
const sessionId = ref(Math.floor(Math.random() * 90000) + 10000)
const botPaused = ref(false)

async function refresh() {
  const [logsResult, botResult] = await Promise.allSettled([
    api.django(`v1/logs/?lines=${lines.value}`),
    api.getBotStatus(),
  ])

  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }

  if (logsResult.status === 'fulfilled') {
    const data = logsResult.value
    if (!data.logs || data.logs.length === 0) {
      logs.value = []
      status.value = 'Empty log'
      return
    }
    logs.value = data.logs
    status.value = `${data.logs.length} lines -- updated ${new Date().toLocaleTimeString()}`
  } else {
    status.value = `Error: ${logsResult.reason?.message || 'fetch failed'}`
  }
}

usePolling(refresh, 30000)  // was 5s — bot gets API priority

watch(logs, async () => {
  if (autoScroll.value && viewerEl.value) {
    await nextTick()
    viewerEl.value.scrollTop = viewerEl.value.scrollHeight
  }
})

function parseLogLine(line) {
  const trimmed = line.trimEnd()
  // Try to extract timestamp, level, and message
  // Common formats: "2024-01-01 12:00:00 INFO message" or "INFO message"
  const timestampMatch = trimmed.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+(.*)/)
  let timestamp = ''
  let rest = trimmed
  if (timestampMatch) {
    timestamp = timestampMatch[1]
    rest = timestampMatch[2]
  }

  let level = 'info'
  let levelTag = '[INFO]'
  let message = rest

  if (rest.startsWith('ERROR') || rest.includes('[ERR')) {
    level = 'error'
    levelTag = '[ERR!]'
    message = rest.replace(/^ERROR\s*/, '').replace(/^\[ERR!?\]\s*/, '')
  } else if (rest.startsWith('WARNING') || rest.includes('[WARN')) {
    level = 'warning'
    levelTag = '[WARN]'
    message = rest.replace(/^WARNING\s*/, '').replace(/^\[WARN\]\s*/, '')
  } else if (rest.startsWith('INFO') || rest.includes('[INFO')) {
    level = 'info'
    levelTag = '[INFO]'
    message = rest.replace(/^INFO\s*/, '').replace(/^\[INFO\]\s*/, '')
  } else if (rest.includes('EXEC') || rest.includes('Order Placed') || rest.includes('Executed')) {
    level = 'exec'
    levelTag = '[EXEC]'
    message = rest.replace(/^\[EXEC\]\s*/, '')
  }

  return { timestamp, level, levelTag, message }
}

const parsedLogs = computed(() => logs.value.map(parseLogLine))

const filteredLogs = computed(() => {
  return parsedLogs.value.filter(entry => {
    // Level filter
    if (entry.level === 'info' && !showInfo.value) return false
    if (entry.level === 'warning' && !showWarning.value) return false
    if (entry.level === 'error' && !showError.value) return false
    // Search filter
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase()
      return entry.message.toLowerCase().includes(q) ||
             entry.timestamp.toLowerCase().includes(q) ||
             entry.levelTag.toLowerCase().includes(q)
    }
    return true
  })
})

const levelCounts = computed(() => ({
  info: parsedLogs.value.filter(e => e.level === 'info' || e.level === 'exec').length,
  warning: parsedLogs.value.filter(e => e.level === 'warning').length,
  error: parsedLogs.value.filter(e => e.level === 'error').length,
}))
</script>

<template>
  <SectionNav :links="forexLinks" />

  <div class="tp-page">
    <!-- Header -->
    <div class="logs-header">
      <div class="logs-header-left">
        <div class="logs-title-row">
          <h1>Bot Logs</h1>
          <div :class="['logs-badge', botPaused ? 'logs-badge-paused' : 'logs-badge-running']">
            <span class="pulse-ring"></span>
            {{ botPaused ? 'Paused' : 'Running' }}
          </div>
        </div>
        <p class="logs-subtitle">Real-time bot diagnostics & execution logs.</p>
      </div>
      <div class="logs-header-actions">
        <button class="tp-btn tp-btn-outline" @click="refresh">
          <span class="material-symbols-outlined" style="font-size:14px">refresh</span>
          Refresh
        </button>
        <button class="tp-btn tp-btn-outline" @click="logs = []">
          <span class="material-symbols-outlined" style="font-size:14px">delete_sweep</span>
          Clear
        </button>
      </div>
    </div>

    <!-- Layout: Sidebar + Terminal -->
    <div class="logs-layout">
      <!-- Sidebar -->
      <aside class="logs-sidebar">
        <div class="logs-sidebar-card">
          <!-- Search -->
          <div>
            <h3>Search &amp; Filter</h3>
            <div class="logs-search-wrap" style="margin-top:0.4rem;">
              <input v-model="searchQuery" class="logs-search logs-search-noicon" type="text" placeholder="Filter logs..." />
            </div>
          </div>

          <!-- Log Level -->
          <div>
            <h3>Log Level</h3>
            <div class="logs-level-list" style="margin-top:0.3rem;">
              <div class="logs-level-item">
                <label>
                  <input v-model="showInfo" type="checkbox" />
                  <span class="level-name">Info</span>
                </label>
                <span class="logs-level-count info">{{ levelCounts.info.toLocaleString() }}</span>
              </div>
              <div class="logs-level-item">
                <label>
                  <input v-model="showWarning" type="checkbox" />
                  <span class="level-name">Warning</span>
                </label>
                <span class="logs-level-count warning">{{ levelCounts.warning }}</span>
              </div>
              <div class="logs-level-item">
                <label>
                  <input v-model="showError" type="checkbox" />
                  <span class="level-name">Error</span>
                </label>
                <span class="logs-level-count error">{{ levelCounts.error }}</span>
              </div>
            </div>
          </div>

          <!-- Lines select -->
          <div>
            <h3>Display Lines</h3>
            <select v-model="lines" @change="refresh" class="tp-select" style="margin-top:0.3rem;font-size:0.78rem;height:2rem;">
              <option value="100">100 Lines</option>
              <option value="200">200 Lines</option>
              <option value="500">500 Lines</option>
              <option value="1000">1000 Lines</option>
            </select>
          </div>

          <!-- Auto-scroll -->
          <div class="logs-toggle-row">
            <span>Auto-scroll</span>
            <label class="logs-toggle-switch">
              <input v-model="autoScroll" type="checkbox" />
              <span class="slider"></span>
            </label>
          </div>
        </div>

        <!-- Quick Insight -->
        <div class="logs-insight-card">
          <div class="insight-header">
            <span class="material-symbols-outlined">info</span>
            <h4>Quick Insight</h4>
          </div>
          <p>
            Bot has processed <span class="insight-value">{{ parsedLogs.length }}</span> log entries.
            <template v-if="levelCounts.error === 0">
              No critical errors detected in current session.
            </template>
            <template v-else>
              <span class="insight-value" style="color:var(--tp-danger);">{{ levelCounts.error }}</span> error(s) detected.
            </template>
          </p>
        </div>
      </aside>

      <!-- Terminal -->
      <div class="logs-terminal">
        <div class="logs-terminal-header">
          <div class="dots">
            <div class="dot red"></div>
            <div class="dot yellow"></div>
            <div class="dot green"></div>
            <span class="session-label">Terminal Output — Session_{{ sessionId }}</span>
          </div>
          <div class="header-right">
            <span class="line-count">Lines: {{ filteredLogs.length }}</span>
          </div>
        </div>

        <div ref="viewerEl" class="logs-terminal-body">
          <template v-if="filteredLogs.length === 0">
            <div class="logs-empty">
              <span class="material-symbols-outlined">terminal</span>
              <span>{{ logs.length === 0 ? 'Waiting for log data...' : 'No matching log entries' }}</span>
            </div>
          </template>
          <template v-else>
            <div
              v-for="(entry, i) in filteredLogs"
              :key="i"
              :class="['log-line', `level-${entry.level}`, { 'log-line-latest': i === filteredLogs.length - 1 }]"
            >
              <span v-if="entry.timestamp" class="log-timestamp">{{ entry.timestamp }}</span>
              <span class="log-level">{{ entry.levelTag }}</span>
              <span class="log-msg">
                {{ entry.message }}
                <span v-if="i === filteredLogs.length - 1" class="log-cursor"></span>
              </span>
            </div>
          </template>
        </div>

        <div class="logs-terminal-footer">
          <div class="footer-stats">
            <div class="stat-item">
              <span :class="['stat-dot', botPaused ? 'amber' : 'green']"></span>
              <span>{{ status || 'Connecting...' }}</span>
            </div>
            <div v-if="botPaused" class="stat-item">
              <span class="stat-dot amber"></span>
              <span>Bot paused</span>
            </div>
          </div>
          <div class="footer-right">
            Polling every 5s
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
