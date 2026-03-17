<script setup>
import { ref, computed, onMounted } from 'vue'
import SectionNav from '@/components/SectionNav.vue'
import { useWebSocket } from '@/composables/useWebSocket'
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

const trades = ref([])
const loading = ref(true)
const error = ref('')

// Stats
const stats = computed(() => {
  const closed = trades.value.filter(t => t.close_time)
  const wins = closed.filter(t => t.pnl > 0)
  const losses = closed.filter(t => t.pnl <= 0)
  const totalPnl = closed.reduce((sum, t) => sum + (t.pnl || 0), 0)
  const avgWin = wins.length ? wins.reduce((s, t) => s + t.pnl, 0) / wins.length : 0
  const avgLoss = losses.length ? losses.reduce((s, t) => s + t.pnl, 0) / losses.length : 0
  const winRate = closed.length ? (wins.length / closed.length * 100) : 0
  const openTrades = trades.value.filter(t => !t.close_time)
  return { total: closed.length, wins: wins.length, losses: losses.length, totalPnl, avgWin, avgLoss, winRate, openCount: openTrades.length }
})

async function fetchTrades() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.getForexTrades()
    trades.value = data.results || data || []
  } catch (err) {
    error.value = err.message
  }
  loading.value = false
}

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function formatPnl(val) {
  if (val == null) return '—'
  return (val >= 0 ? '+' : '') + val.toFixed(2)
}

function duration(entry, close) {
  if (!entry || !close) return '—'
  const ms = new Date(close) - new Date(entry)
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  const rm = mins % 60
  if (hrs < 24) return `${hrs}h ${rm}m`
  return `${Math.floor(hrs / 24)}d ${hrs % 24}h`
}

// WebSocket: auto-refresh on trade close events
const { connected: wsConnected, on: wsOn } = useWebSocket()
wsOn('trade_closed', () => fetchTrades())

onMounted(fetchTrades)
</script>

<template>
  <SectionNav :links="forexLinks" />
  <div class="tp-page history-page">
    <div class="page-header">
      <div>
        <h1>Trade History</h1>
        <p>All forex trades tracked by the bot — updated automatically.</p>
      </div>
      <div class="header-right">
        <span class="ws-indicator" :class="wsConnected ? 'ws-connected' : 'ws-disconnected'">
          <span class="pulse-dot" v-if="wsConnected"></span>
          {{ wsConnected ? 'Live' : 'Polling' }}
        </span>
        <button class="tp-btn tp-btn-outline" @click="fetchTrades" :disabled="loading">
          <span class="material-symbols-outlined" style="font-size:16px">refresh</span>
          Refresh
        </button>
      </div>
    </div>

    <!-- Stats Cards -->
    <div class="stats-row" v-if="!loading && trades.length">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-label">Closed Trades</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" :class="stats.totalPnl >= 0 ? 'pnl-pos' : 'pnl-neg'">${{ stats.totalPnl.toFixed(2) }}</div>
        <div class="stat-label">Total P&L</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.winRate.toFixed(1) }}%</div>
        <div class="stat-label">Win Rate ({{ stats.wins }}W / {{ stats.losses }}L)</div>
      </div>
      <div class="stat-card">
        <div class="stat-value pnl-pos">${{ stats.avgWin.toFixed(2) }}</div>
        <div class="stat-label">Avg Win</div>
      </div>
      <div class="stat-card">
        <div class="stat-value pnl-neg">${{ stats.avgLoss.toFixed(2) }}</div>
        <div class="stat-label">Avg Loss</div>
      </div>
      <div class="stat-card" v-if="stats.openCount">
        <div class="stat-value" style="color:var(--tp-primary)">{{ stats.openCount }}</div>
        <div class="stat-label">Open Now</div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading-msg">
      <span class="material-symbols-outlined spinning">hourglass_empty</span> Loading trades...
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-msg">
      <span class="material-symbols-outlined" style="font-size:16px">error</span>
      {{ error }}
    </div>

    <!-- Empty -->
    <div v-else-if="!trades.length" class="empty-state tp-card">
      <div class="card-inner">
        <span class="material-symbols-outlined" style="font-size:48px;color:var(--tp-text-muted)">inbox</span>
        <p>No trades recorded yet.</p>
      </div>
    </div>

    <!-- Trades Table -->
    <div v-else class="tp-card">
      <div class="card-inner" style="padding:0">
        <div class="table-wrapper">
          <table class="tp-table trades-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Close</th>
                <th>Duration</th>
                <th>Strategy</th>
                <th>P&L</th>
                <th>Peak</th>
                <th>Reason</th>
                <th>BE</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in trades" :key="t.id" :class="{ 'row-open': !t.close_time }">
                <td class="td-time">{{ formatTime(t.entry_time) }}</td>
                <td class="td-symbol">{{ t.symbol }}</td>
                <td>
                  <span class="side-badge" :class="t.type === 'SELL' ? 'sell' : 'buy'">
                    {{ t.type || 'BUY' }}
                  </span>
                </td>
                <td class="td-price">{{ t.entry_price ? Number(t.entry_price).toFixed(5) : '—' }}</td>
                <td class="td-price">{{ t.close_price ? Number(t.close_price).toFixed(5) : '—' }}</td>
                <td class="td-duration">{{ duration(t.entry_time, t.close_time) }}</td>
                <td class="td-strategy">{{ t.strategy_config_name || t.strategy || '—' }}</td>
                <td class="td-pnl" :class="t.pnl > 0 ? 'pnl-pos' : t.pnl < 0 ? 'pnl-neg' : ''">
                  <template v-if="t.close_time">{{ formatPnl(t.pnl) }}</template>
                  <span v-else class="open-badge">OPEN</span>
                </td>
                <td class="td-peak">
                  <span v-if="t.max_profit != null" class="pnl-pos">${{ t.max_profit.toFixed(2) }}</span>
                  <span v-else>—</span>
                </td>
                <td class="td-reason">{{ t.closing_reason || '—' }}</td>
                <td class="td-be">
                  <span v-if="t.breakeven_moved" class="be-yes">
                    <span class="material-symbols-outlined" style="font-size:14px">check_circle</span>
                  </span>
                  <span v-else class="be-no">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-page {
  padding: 1.5rem 1.5rem 1rem;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.25rem;
}
.page-header h1 {
  font-size: 1.25rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin-bottom: 0.15rem;
}
.page-header p {
  font-size: 0.8rem;
  color: var(--tp-text-dim);
}

/* Stats Row */
.stats-row {
  display: flex;
  gap: 0;
  margin-bottom: 1.25rem;
  border-radius: var(--tp-radius);
  overflow: hidden;
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
  border: var(--tp-glass-border);
  box-shadow: var(--tp-glass-shadow);
}
.stat-card {
  flex: 1;
  min-width: 0;
  padding: 0.75rem 1rem;
  text-align: center;
  border-right: 1px solid var(--tp-border);
}
.stat-card:last-child {
  border-right: none;
}
.stat-value {
  font-size: 1.15rem;
  font-weight: 800;
  margin-bottom: 0.15rem;
  font-feature-settings: 'tnum' 1;
  white-space: nowrap;
}
.stat-label {
  font-size: 0.6rem;
  color: var(--tp-text-dim);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 700;
  white-space: nowrap;
}

/* Table — scrolls vertically within remaining viewport */
.table-wrapper {
  max-height: calc(100vh - 21rem); /* viewport minus nav, tabs, header, stats, padding */
  overflow-y: auto;
  overflow-x: auto;
}
.table-wrapper::-webkit-scrollbar {
  width: 6px;
}
.table-wrapper::-webkit-scrollbar-track {
  background: transparent;
}
.table-wrapper::-webkit-scrollbar-thumb {
  background: var(--tp-border);
  border-radius: 3px;
}
.table-wrapper::-webkit-scrollbar-thumb:hover {
  background: var(--tp-text-muted);
}
.trades-table {
  width: 100%;
  font-size: 0.82rem;
}
.trades-table th {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--tp-text-muted);
  white-space: nowrap;
  position: sticky;
  top: 0;
  background: var(--tp-bg-glass, var(--tp-bg-card, #0f1729));
  z-index: 2;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
.trades-table td {
  white-space: nowrap;
  padding: 0.6rem 0.75rem;
}
.row-open {
  background: rgba(59, 130, 246, 0.04);
}
.td-symbol {
  font-weight: 600;
}
.td-price {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
  color: var(--tp-text-muted);
}
.td-time {
  color: var(--tp-text-muted);
  font-size: 0.78rem;
}
.td-duration {
  color: var(--tp-text-muted);
  font-size: 0.78rem;
}
.td-strategy {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 0.75rem;
  color: var(--tp-text-muted);
}
.td-pnl {
  font-weight: 700;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.td-peak {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
}
.td-reason {
  font-size: 0.75rem;
  color: var(--tp-text-muted);
}
.pnl-pos { color: #22c55e; }
.pnl-neg { color: #ef4444; }

.side-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.side-badge.buy {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
}
.side-badge.sell {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}
.open-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 700;
  background: rgba(59, 130, 246, 0.12);
  color: #3b82f6;
}
.be-yes { color: #22c55e; }
.be-no { color: var(--tp-text-muted); }

.empty-state {
  text-align: center;
  padding: 3rem;
}
.empty-state .card-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}

.error-msg {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.75rem 1rem;
  background: rgba(239,68,68,0.05);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: var(--tp-radius-sm);
  color: var(--tp-danger);
  font-size: 0.85rem;
}
.loading-msg {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 2rem;
  color: var(--tp-text-muted);
  justify-content: center;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.spinning { animation: spin 1.5s linear infinite; }

/* WebSocket indicator */
.header-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.ws-indicator {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.65rem;
  font-weight: 600;
  padding: 0.2rem 0.5rem;
  border-radius: 9999px;
}
.ws-connected {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}
.ws-disconnected {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}
.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
  animation: ws-pulse 2s ease infinite;
}
@keyframes ws-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.4); }
  50%      { box-shadow: 0 0 0 4px rgba(34, 197, 94, 0); }
}
</style>
