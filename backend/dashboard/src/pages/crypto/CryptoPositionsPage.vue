<script setup>
import { ref, computed } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'

const cryptoLinks = [
  { to: '/crypto', label: 'Overview' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/history', label: 'History' },
  { to: '/crypto/chart', label: 'Chart' },
  { to: '/crypto/logs', label: 'Logs' },
  { to: '/crypto/strategy', label: 'Strategies' },
]

// Wallet data for live positions
const livePositions = ref([])
const walletLoaded = ref(false)

// DB positions for closed
const dbPositions = ref([])
const showClosed = ref(false)

const displayPositions = computed(() => showClosed.value ? dbPositions.value : livePositions.value)

const totalUnrealizedPnl = computed(() =>
  livePositions.value.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0)
)

const totalClosedPnl = computed(() =>
  dbPositions.value.reduce((sum, p) => sum + Number(p.pnl_usd ?? 0), 0)
)

const COIN_COLORS = {
  BTC: '#f7931a', ETH: '#627eea', SOL: '#9945ff', AVAX: '#e84142',
  DOGE: '#c2a633', ARB: '#28a0f0', MATIC: '#8247e5', LINK: '#2a5ada',
  OP: '#ff0420', SUI: '#4da2ff',
}

function getCoinColor(coin) {
  return COIN_COLORS[coin] || 'var(--tp-primary)'
}

async function refresh() {
  const [walletResult, closedResult] = await Promise.allSettled([
    api.getCryptoWallet(),
    api.getCryptoPositions('closed'),
  ])
  if (walletResult.status === 'fulfilled') {
    livePositions.value = walletResult.value.positions ?? []
    walletLoaded.value = true
  }
  if (closedResult.status === 'fulfilled') {
    dbPositions.value = closedResult.value.results ?? closedResult.value ?? []
  }
}

function fmt(val, decimals = 2) {
  if (val == null) return '-'
  return Number(val).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function fmtPrice(val) {
  if (val == null) return '-'
  const n = Number(val)
  if (n >= 1000) return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (n >= 1) return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
  return n.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 6 })
}

function fmtDate(val) {
  if (!val) return '-'
  const d = new Date(val)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

usePolling(refresh, 10000)
</script>

<template>
  <SectionNav :links="cryptoLinks" />
  <div class="tp-page positions-page">
    <div class="page-header">
      <div>
        <h1>Crypto Positions</h1>
        <p>{{ showClosed ? 'Closed position history' : 'Live on-chain positions from Hyperliquid' }}</p>
      </div>
      <div class="header-actions">
        <label class="toggle-label">
          <input v-model="showClosed" type="checkbox" role="switch" />
          Show closed
        </label>
        <button class="tp-btn tp-btn-outline" @click="refresh">
          <span class="material-symbols-outlined" style="font-size:16px">refresh</span>
          Refresh
        </button>
      </div>
    </div>

    <!-- Stats Row — glass strip -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ showClosed ? dbPositions.length : livePositions.length }}</div>
        <div class="stat-label">{{ showClosed ? 'Closed Trades' : 'Open Positions' }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" :class="(showClosed ? totalClosedPnl : totalUnrealizedPnl) >= 0 ? 'pnl-pos' : 'pnl-neg'">
          {{ (showClosed ? totalClosedPnl : totalUnrealizedPnl) >= 0 ? '+' : '' }}${{ fmt(showClosed ? totalClosedPnl : totalUnrealizedPnl) }}
        </div>
        <div class="stat-label">{{ showClosed ? 'Total P&L' : 'Unrealized P&L' }}</div>
      </div>
    </div>

    <!-- LIVE POSITIONS TABLE -->
    <div v-if="!showClosed" class="tp-card">
      <div class="card-inner" style="padding:0">
        <div class="table-wrapper">
          <table class="tp-table positions-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Side</th>
                <th>Size</th>
                <th>Entry Price</th>
                <th>Mark Price</th>
                <th>Leverage</th>
                <th>Margin</th>
                <th>P&L</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!livePositions.length">
                <td colspan="8" style="padding: 3rem 2rem; text-align: center;">
                  <div class="empty-state-inner">
                    <div class="empty-icon">
                      <span class="material-symbols-outlined" style="font-size:2rem;color:var(--tp-text-dim)">account_balance_wallet</span>
                    </div>
                    <p class="empty-title">No open positions</p>
                    <p class="empty-desc">Live positions from Hyperliquid will appear here.</p>
                  </div>
                </td>
              </tr>
              <tr v-for="p in livePositions" :key="p.coin">
                <td>
                  <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <div class="coin-icon-sm" :style="{ background: getCoinColor(p.coin) + '22', color: getCoinColor(p.coin) }">
                      {{ p.coin.slice(0, 2) }}
                    </div>
                    <span class="td-symbol">{{ p.coin }}</span>
                  </div>
                </td>
                <td>
                  <span class="side-badge" :class="p.side === 'LONG' ? 'buy' : 'sell'">
                    {{ p.side }}
                  </span>
                </td>
                <td style="font-weight: 600;">{{ fmt(Math.abs(p.size), 4) }}</td>
                <td class="td-price">${{ fmtPrice(p.entry_price) }}</td>
                <td class="td-price">${{ fmtPrice(p.mark_price) }}</td>
                <td>{{ p.leverage }}x</td>
                <td>${{ fmt(p.margin_used) }}</td>
                <td>
                  <span class="td-pnl" :class="p.unrealized_pnl >= 0 ? 'pnl-pos' : 'pnl-neg'">
                    {{ p.unrealized_pnl >= 0 ? '+' : '' }}${{ fmt(p.unrealized_pnl) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- CLOSED POSITIONS TABLE -->
    <div v-else class="tp-card">
      <div class="card-inner" style="padding:0">
        <div class="table-wrapper">
          <table class="tp-table positions-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Close</th>
                <th>Size</th>
                <th>Lev</th>
                <th>P&L</th>
                <th>Reason</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!dbPositions.length">
                <td colspan="9" style="padding: 3rem 2rem; text-align: center;">
                  <div class="empty-state-inner">
                    <div class="empty-icon">
                      <span class="material-symbols-outlined" style="font-size:2rem;color:var(--tp-text-dim)">inventory_2</span>
                    </div>
                    <p class="empty-title">No closed positions</p>
                    <p class="empty-desc">Closed trades will appear here.</p>
                  </div>
                </td>
              </tr>
              <tr v-for="p in dbPositions" :key="p.id">
                <td class="td-symbol">{{ p.symbol }}</td>
                <td>
                  <span class="side-badge" :class="p.side === 'LONG' ? 'buy' : 'sell'">
                    {{ p.side }}
                  </span>
                </td>
                <td class="td-price">${{ fmtPrice(p.entry_price) }}</td>
                <td class="td-price">{{ p.close_price ? '$' + fmtPrice(p.close_price) : '-' }}</td>
                <td style="font-weight: 500;">{{ fmt(p.size, 4) }}</td>
                <td>{{ p.leverage }}x</td>
                <td>
                  <span class="td-pnl" :class="Number(p.pnl_usd ?? 0) >= 0 ? 'pnl-pos' : 'pnl-neg'">
                    {{ Number(p.pnl_usd ?? 0) >= 0 ? '+' : '' }}${{ fmt(p.pnl_usd) }}
                  </span>
                </td>
                <td class="td-reason">{{ p.close_reason ?? '-' }}</td>
                <td class="td-time">{{ fmtDate(p.opened_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.positions-page {
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
.header-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.toggle-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--tp-text-dim);
  font-size: 0.85rem;
  cursor: pointer;
}
.toggle-label input {
  margin: 0;
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
  max-height: calc(100vh - 20rem);
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
.positions-table {
  width: 100%;
  font-size: 0.82rem;
}
.positions-table th {
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
.positions-table td {
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
.td-pnl {
  font-weight: 700;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.td-time {
  color: var(--tp-text-muted);
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

.coin-icon-sm {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.55rem;
  font-weight: 800;
  flex-shrink: 0;
}

/* Empty states */
.empty-state-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.empty-icon {
  width: 3.5rem;
  height: 3.5rem;
  border-radius: 50%;
  background: var(--tp-bg-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 0.75rem;
}
.empty-title {
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.empty-desc {
  font-size: 0.8rem;
  color: var(--tp-text-dim);
  margin: 0;
}
</style>
