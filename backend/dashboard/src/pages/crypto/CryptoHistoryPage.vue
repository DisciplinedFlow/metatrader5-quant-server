<script setup>
import { ref, computed, onMounted } from 'vue'
import SectionNav from '@/components/SectionNav.vue'
import api from '@/services/api'
import { cryptoLinks, fmtTime, fmtPrice, duration } from '@/utils/cryptoConstants'

const positions = ref([])
const loading = ref(true)
const error = ref('')

// Net PnL = gross pnl_usd minus exchange fees (from total_fees field)
const netPnl = (p) => Number(p.pnl_usd ?? 0) - Number(p.total_fees ?? 0)

const stats = computed(() => {
  const closed = positions.value.filter(p => p.status === 'CLOSED')
  const wins = closed.filter(p => netPnl(p) > 0)
  const losses = closed.filter(p => netPnl(p) <= 0)
  const totalPnl = closed.reduce((sum, p) => sum + netPnl(p), 0)
  const totalFees = closed.reduce((sum, p) => sum + Number(p.total_fees ?? 0), 0)
  const avgWin = wins.length ? wins.reduce((s, p) => s + netPnl(p), 0) / wins.length : 0
  const avgLoss = losses.length ? losses.reduce((s, p) => s + netPnl(p), 0) / losses.length : 0
  const winRate = closed.length ? (wins.length / closed.length * 100) : 0
  const openCount = positions.value.filter(p => p.status === 'OPEN').length
  return { total: closed.length, wins: wins.length, losses: losses.length, totalPnl, totalFees, avgWin, avgLoss, winRate, openCount }
})

async function fetchHistory() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.getCryptoPositions('closed')
    positions.value = data.results || data || []
  } catch (err) {
    error.value = err.message
  }
  loading.value = false
}

function formatPnl(val) {
  if (val == null) return '-'
  const n = Number(val)
  return (n >= 0 ? '+' : '') + n.toFixed(2)
}

onMounted(fetchHistory)
</script>

<template>
  <SectionNav :links="cryptoLinks" />
  <div class="tp-page history-page">
    <div class="page-header">
      <div>
        <h1>Trade History</h1>
        <p>All crypto trades tracked by the bot — Lighter.xyz & Hyperliquid Perpetuals.</p>
      </div>
      <button class="tp-btn tp-btn-outline" @click="fetchHistory" :disabled="loading">
        <span class="material-symbols-outlined" style="font-size:16px">refresh</span>
        Refresh
      </button>
    </div>

    <!-- Stats Cards -->
    <div class="stats-row" v-if="!loading && positions.length">
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
    <div v-else-if="!positions.length" class="empty-state tp-card">
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
                <th>Size</th>
                <th>Leverage</th>
                <th>P&L</th>
                <th>Peak</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in positions" :key="p.id">
                <td class="td-time">{{ fmtTime(p.opened_at) }}</td>
                <td class="td-symbol">{{ p.symbol }}</td>
                <td>
                  <span class="side-badge" :class="p.side === 'LONG' ? 'buy' : 'sell'">
                    {{ p.side }}
                  </span>
                </td>
                <td class="td-price">${{ fmtPrice(p.entry_price) }}</td>
                <td class="td-price">{{ p.close_price ? '$' + fmtPrice(p.close_price) : '-' }}</td>
                <td class="td-duration">{{ duration(p.opened_at, p.closed_at) }}</td>
                <td style="font-weight:500">{{ Number(p.size).toFixed(4) }}</td>
                <td>{{ p.leverage }}x</td>
                <td class="td-pnl" :class="netPnl(p) > 0 ? 'pnl-pos' : netPnl(p) < 0 ? 'pnl-neg' : ''">
                  {{ formatPnl(netPnl(p)) }}
                </td>
                <td class="td-peak">
                  <span v-if="p.peak_profit_usd != null" class="pnl-pos">${{ Number(p.peak_profit_usd).toFixed(2) }}</span>
                  <span v-else>-</span>
                </td>
                <td class="td-reason">{{ p.close_reason ?? '-' }}</td>
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

/* Table */
.table-wrapper {
  max-height: calc(100vh - 21rem);
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
</style>
