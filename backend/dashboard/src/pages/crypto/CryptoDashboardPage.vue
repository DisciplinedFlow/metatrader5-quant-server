<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'

const router = useRouter()

const cryptoLinks = [
  { to: '/crypto', label: 'Overview' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/history', label: 'History' },
  { to: '/crypto/chart', label: 'Chart' },
  { to: '/crypto/logs', label: 'Logs' },
  { to: '/crypto/strategy', label: 'Strategies' },
]

// Bot state
const botPaused = ref(false)
const botStatusLoading = ref(false)

// Wallet data from Hyperliquid
const walletAddress = ref('')
const accountValue = ref(0)
const totalMarginUsed = ref(0)
const totalNtlPos = ref(0)
const withdrawable = ref(0)
const livePositions = ref([])
const prices = ref([])
const walletError = ref('')
const walletLoaded = ref(false)

// DB data
const openPositionsCount = ref(0)
const totalPnl = ref(0)
const closedPositions = ref([])

// Computed values
const totalPositionValue = computed(() =>
  livePositions.value.reduce((sum, p) => sum + Math.abs(p.size * p.mark_price), 0)
)

const allocation = computed(() => {
  if (!totalPositionValue.value) return []
  return livePositions.value.map(p => ({
    coin: p.coin,
    pct: Math.abs(p.size * p.mark_price) / totalPositionValue.value,
    value: Math.abs(p.size * p.mark_price),
    side: p.side,
  })).sort((a, b) => b.pct - a.pct)
})

const marginUsedPct = computed(() => {
  if (!accountValue.value) return 0
  return (totalMarginUsed.value / accountValue.value) * 100
})

const totalUnrealizedPnl = computed(() =>
  livePositions.value.reduce((sum, p) => sum + p.unrealized_pnl, 0)
)

const shortAddress = computed(() => {
  if (!walletAddress.value) return ''
  return walletAddress.value.slice(0, 6) + '...' + walletAddress.value.slice(-4)
})

// P&L performance data from closed positions
const sortedClosed = computed(() =>
  closedPositions.value
    .filter(p => p.closed_at && p.pnl_usd != null)
    .sort((a, b) => new Date(a.closed_at) - new Date(b.closed_at))
)

const equityCurve = computed(() => {
  let cumulative = 0
  return sortedClosed.value.map(p => {
    cumulative += Number(p.pnl_usd)
    return { pnl: Number(p.pnl_usd), cumulative, symbol: p.symbol, time: p.closed_at }
  })
})

const pnlStats = computed(() => {
  const ct = sortedClosed.value
  const wins = ct.filter(p => Number(p.pnl_usd) > 0)
  const losses = ct.filter(p => Number(p.pnl_usd) <= 0)
  const total = ct.reduce((s, p) => s + Number(p.pnl_usd), 0)
  const winRate = ct.length ? (wins.length / ct.length * 100) : 0
  const bestTrade = ct.length ? Math.max(...ct.map(p => Number(p.pnl_usd))) : 0
  const worstTrade = ct.length ? Math.min(...ct.map(p => Number(p.pnl_usd))) : 0
  return { total: ct.length, wins: wins.length, losses: losses.length, totalPnl: total, winRate, bestTrade, worstTrade }
})

// SVG equity curve
const chartPath = computed(() => {
  const pts = equityCurve.value
  if (pts.length < 2) return ''
  const w = 280, h = 80, pad = 4
  const vals = pts.map(p => p.cumulative)
  const minV = Math.min(0, ...vals)
  const maxV = Math.max(0, ...vals)
  const range = maxV - minV || 1
  const scaleX = i => pad + (i / (pts.length - 1)) * (w - pad * 2)
  const scaleY = v => pad + (1 - (v - minV) / range) * (h - pad * 2)
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${scaleX(i).toFixed(1)} ${scaleY(p.cumulative).toFixed(1)}`).join(' ')
})

const chartFill = computed(() => {
  const pts = equityCurve.value
  if (pts.length < 2) return ''
  const w = 280, h = 80, pad = 4
  const vals = pts.map(p => p.cumulative)
  const minV = Math.min(0, ...vals)
  const maxV = Math.max(0, ...vals)
  const range = maxV - minV || 1
  const scaleX = i => pad + (i / (pts.length - 1)) * (w - pad * 2)
  const scaleY = v => pad + (1 - (v - minV) / range) * (h - pad * 2)
  const lineParts = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${scaleX(i).toFixed(1)} ${scaleY(p.cumulative).toFixed(1)}`).join(' ')
  return `${lineParts} L${scaleX(pts.length - 1).toFixed(1)} ${h} L${scaleX(0).toFixed(1)} ${h} Z`
})

const zeroLineY = computed(() => {
  const pts = equityCurve.value
  if (pts.length < 2) return 40
  const vals = pts.map(p => p.cumulative)
  const minV = Math.min(0, ...vals)
  const maxV = Math.max(0, ...vals)
  const range = maxV - minV || 1
  return 4 + (1 - (0 - minV) / range) * 72
})

// Coin colors
const COIN_COLORS = {
  BTC: '#f7931a', ETH: '#627eea', SOL: '#9945ff', AVAX: '#e84142',
  DOGE: '#c2a633', ARB: '#28a0f0', MATIC: '#8247e5', LINK: '#2a5ada',
  OP: '#ff0420', SUI: '#4da2ff',
}

function getCoinColor(coin) {
  return COIN_COLORS[coin] || 'var(--tp-primary)'
}

async function refresh() {
  const [botResult, dashResult, walletResult, closedResult] = await Promise.allSettled([
    api.getCryptoBotStatus(),
    api.getCryptoDashboard(),
    api.getCryptoWallet(),
    api.getCryptoPositions('closed'),
  ])

  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }
  if (dashResult.status === 'fulfilled') {
    openPositionsCount.value = dashResult.value.open_positions ?? 0
    totalPnl.value = dashResult.value.total_pnl ?? 0
  }
  if (walletResult.status === 'fulfilled') {
    const w = walletResult.value
    walletAddress.value = w.wallet_address ?? ''
    accountValue.value = w.account_value ?? 0
    totalMarginUsed.value = w.total_margin_used ?? 0
    totalNtlPos.value = w.total_ntl_pos ?? 0
    withdrawable.value = w.withdrawable ?? 0
    livePositions.value = w.positions ?? []
    prices.value = w.prices ?? []
    walletError.value = ''
    walletLoaded.value = true
  } else if (walletResult.status === 'rejected') {
    walletError.value = walletResult.reason?.message || 'Failed to load wallet'
    walletLoaded.value = true
  }
  if (closedResult.status === 'fulfilled') {
    closedPositions.value = closedResult.value.results ?? closedResult.value ?? []
  }
}

async function toggleBot() {
  botStatusLoading.value = true
  try {
    const resp = await api.setCryptoBotPaused(!botPaused.value)
    botPaused.value = resp.paused
  } catch (err) {
    console.error('Bot toggle error:', err)
  }
  botStatusLoading.value = false
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

function fmtPct(val) {
  return (val * 100).toFixed(1) + '%'
}

onMounted(refresh)
usePolling(refresh, 10000)
</script>

<template>
  <SectionNav :links="cryptoLinks" />
  <div class="tp-page dashboard-page">

    <!-- Bot Status + Account Stats — full-width glass strip -->
    <div class="top-row">
      <div class="tp-card bot-card">
        <div class="bot-header">
          <div class="bot-label-row">
            <div class="bot-icon" :class="botPaused ? 'bot-icon-paused' : 'bot-icon-running'">
              <span class="material-symbols-outlined">currency_bitcoin</span>
            </div>
            <div>
              <p class="micro-label">Crypto Bot</p>
              <div class="bot-status-row">
                <span class="status-dot" :class="botPaused ? 'dot-paused' : 'dot-running'"></span>
                <p class="bot-status-text">{{ botPaused ? 'PAUSED' : 'RUNNING' }}</p>
              </div>
            </div>
          </div>
          <button
            class="tp-btn tp-btn-outline"
            :aria-busy="botStatusLoading"
            @click="toggleBot"
          >
            <span class="material-symbols-outlined" style="font-size:16px">{{ botPaused ? 'play_arrow' : 'pause' }}</span>
            {{ botPaused ? 'Resume' : 'Pause' }}
          </button>
        </div>
      </div>

      <div class="tp-card stats-row-card">
        <div class="mini-stat">
          <p class="micro-label">Account Value</p>
          <p class="mini-stat-value">${{ fmt(accountValue) }}</p>
        </div>
        <div class="mini-stat">
          <p class="micro-label">Unrealized P&L</p>
          <p class="mini-stat-value" :class="totalUnrealizedPnl >= 0 ? 'text-success' : 'text-danger'">
            {{ totalUnrealizedPnl >= 0 ? '+' : '' }}${{ fmt(totalUnrealizedPnl) }}
          </p>
        </div>
        <div class="mini-stat">
          <p class="micro-label">Margin Level</p>
          <p class="mini-stat-value">{{ marginUsedPct.toFixed(1) }}%</p>
        </div>
        <div class="mini-stat">
          <p class="micro-label">Withdrawable</p>
          <p class="mini-stat-value">${{ fmt(withdrawable) }}</p>
        </div>
      </div>
    </div>

    <div class="dash-grid">

      <!-- ===== LEFT COLUMN ===== -->
      <div class="left-col">

        <!-- Live Prices -->
        <div class="tp-card prices-card">
          <div class="prices-header">
            <h3>
              <span class="material-symbols-outlined" style="color:var(--tp-primary);font-size:20px">show_chart</span>
              Live Prices
            </h3>
            <span class="tp-badge tp-badge-success" style="font-size: 0.6rem;">
              <span class="pulse-dot"></span> Real-time
            </span>
          </div>
          <div class="prices-grid">
            <div v-for="p in prices" :key="p.coin" class="price-item">
              <div class="price-coin-row">
                <div class="coin-icon" :style="{ background: getCoinColor(p.coin) + '22', color: getCoinColor(p.coin) }">
                  {{ p.coin.slice(0, 2) }}
                </div>
                <div>
                  <div class="price-coin-name">{{ p.coin }}</div>
                  <div class="price-coin-pair">{{ p.coin }}/USD</div>
                </div>
              </div>
              <div class="price-value">${{ fmtPrice(p.price) }}</div>
            </div>
          </div>
        </div>

        <!-- On-Chain Positions -->
        <div class="tp-card positions-card">
          <div class="positions-header">
            <h3>On-Chain Positions</h3>
            <div class="positions-header-right">
              <span class="tp-badge tp-badge-primary">{{ livePositions.length }} active</span>
              <button class="view-history-btn" @click="router.push('/crypto/history')">View History</button>
            </div>
          </div>
          <div class="positions-body">
            <template v-if="livePositions.length > 0">
              <div style="overflow-x: auto;">
                <table class="tp-table">
                  <thead>
                    <tr>
                      <th>Asset</th>
                      <th>Side</th>
                      <th>Size</th>
                      <th>Entry</th>
                      <th>Mark</th>
                      <th>Lev</th>
                      <th>Margin</th>
                      <th>P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="p in livePositions" :key="p.coin">
                      <td>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                          <div class="coin-icon-sm" :style="{ background: getCoinColor(p.coin) + '22', color: getCoinColor(p.coin) }">
                            {{ p.coin.slice(0, 2) }}
                          </div>
                          <span style="font-weight: 700;">{{ p.coin }}</span>
                        </div>
                      </td>
                      <td>
                        <span class="tp-badge" :class="p.side === 'LONG' ? 'tp-badge-success' : 'tp-badge-danger'">
                          {{ p.side }}
                        </span>
                      </td>
                      <td style="font-weight: 600;">{{ fmt(Math.abs(p.size), 4) }}</td>
                      <td style="font-weight: 500;">${{ fmtPrice(p.entry_price) }}</td>
                      <td style="font-weight: 500;">${{ fmtPrice(p.mark_price) }}</td>
                      <td>{{ p.leverage }}x</td>
                      <td>${{ fmt(p.margin_used) }}</td>
                      <td>
                        <span style="font-weight: 700;" :style="{ color: p.unrealized_pnl >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
                          {{ p.unrealized_pnl >= 0 ? '+' : '' }}${{ fmt(p.unrealized_pnl) }}
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
            <div v-else class="empty-positions">
              <div class="empty-icon">
                <span class="material-symbols-outlined" style="font-size:2rem;color:var(--tp-text-dim)">account_balance_wallet</span>
              </div>
              <p class="empty-title">No open positions</p>
              <p class="empty-desc">Live positions from Hyperliquid will appear here.</p>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== RIGHT COLUMN ===== -->
      <div class="right-col">

        <!-- P&L Performance Card -->
        <div class="tp-card pnl-card">
          <div class="pnl-header">
            <div>
              <h3 class="pnl-title">Performance</h3>
              <p class="pnl-subtitle">{{ pnlStats.total }} closed trades</p>
            </div>
            <div class="pnl-total" :class="pnlStats.totalPnl >= 0 ? 'text-success' : 'text-danger'">
              {{ pnlStats.totalPnl >= 0 ? '+' : '' }}${{ pnlStats.totalPnl.toFixed(2) }}
            </div>
          </div>

          <!-- Equity Curve -->
          <div class="equity-chart" v-if="equityCurve.length >= 2">
            <svg viewBox="0 0 280 80" preserveAspectRatio="none" class="equity-svg">
              <line x1="4" :y1="zeroLineY" x2="276" :y2="zeroLineY" stroke="var(--tp-border)" stroke-width="0.5" stroke-dasharray="4 2" />
              <path :d="chartFill" :fill="pnlStats.totalPnl >= 0 ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)'" />
              <path :d="chartPath" fill="none" :stroke="pnlStats.totalPnl >= 0 ? '#22c55e' : '#ef4444'" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
          <div v-else class="equity-empty">
            <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">show_chart</span>
            <p>Waiting for closed trades...</p>
          </div>

          <!-- Trade Bars -->
          <div class="trade-bars" v-if="sortedClosed.length">
            <div v-for="(t, i) in sortedClosed.slice(-20)" :key="i"
                 class="trade-bar"
                 :class="Number(t.pnl_usd) >= 0 ? 'bar-win' : 'bar-loss'"
                 :style="{ height: Math.min(100, Math.max(8, Math.abs(Number(t.pnl_usd)) * 3)) + '%' }"
                 :title="`${t.symbol} ${Number(t.pnl_usd) >= 0 ? '+' : ''}$${Number(t.pnl_usd).toFixed(2)}`"
            ></div>
          </div>

          <!-- Stats Grid -->
          <div class="pnl-stats-grid">
            <div class="pnl-stat">
              <span class="pnl-stat-label">Win Rate</span>
              <span class="pnl-stat-value">{{ pnlStats.winRate.toFixed(0) }}%</span>
            </div>
            <div class="pnl-stat">
              <span class="pnl-stat-label">W / L</span>
              <span class="pnl-stat-value">{{ pnlStats.wins }} / {{ pnlStats.losses }}</span>
            </div>
            <div class="pnl-stat">
              <span class="pnl-stat-label">Best</span>
              <span class="pnl-stat-value text-success">+${{ pnlStats.bestTrade.toFixed(2) }}</span>
            </div>
            <div class="pnl-stat">
              <span class="pnl-stat-label">Worst</span>
              <span class="pnl-stat-value text-danger">${{ pnlStats.worstTrade.toFixed(2) }}</span>
            </div>
          </div>

          <button class="tp-btn tp-btn-outline pnl-history-btn" @click="router.push('/crypto/history')">
            <span class="material-symbols-outlined" style="font-size:16px">history</span>
            View Full History
          </button>
        </div>

        <!-- Margin & Risk Card -->
        <div class="tp-card margin-card">
          <div class="margin-header">
            <h3>
              <span class="material-symbols-outlined" style="color:var(--tp-primary);font-size:20px">shield</span>
              Margin & Risk
            </h3>
          </div>
          <div class="margin-body">
            <div class="margin-bar-wrap">
              <div class="margin-bar">
                <div
                  class="margin-bar-fill"
                  :style="{ width: Math.min(marginUsedPct, 100) + '%' }"
                  :class="{
                    'bar-safe': marginUsedPct < 50,
                    'bar-warning': marginUsedPct >= 50 && marginUsedPct < 80,
                    'bar-danger': marginUsedPct >= 80,
                  }"
                ></div>
              </div>
              <span class="margin-pct">{{ marginUsedPct.toFixed(1) }}%</span>
            </div>
            <div class="margin-detail-row">
              <span class="meta-label">Margin Used</span>
              <span class="meta-value">${{ fmt(totalMarginUsed) }}</span>
            </div>
            <div class="margin-detail-row">
              <span class="meta-label">Notional Exposure</span>
              <span class="meta-value">${{ fmt(Math.abs(totalNtlPos)) }}</span>
            </div>
            <div class="margin-detail-row">
              <span class="meta-label">Position Value</span>
              <span class="meta-value">${{ fmt(totalPositionValue) }}</span>
            </div>
          </div>
        </div>

        <!-- Portfolio Allocation -->
        <div v-if="allocation.length" class="tp-card alloc-card">
          <div class="alloc-header">
            <h3>
              <span class="material-symbols-outlined" style="color:var(--tp-primary);font-size:20px">pie_chart</span>
              Portfolio Allocation
            </h3>
          </div>
          <div class="alloc-body">
            <div class="alloc-bar">
              <div
                v-for="a in allocation"
                :key="a.coin"
                class="alloc-segment"
                :style="{ width: fmtPct(a.pct), background: getCoinColor(a.coin) }"
                :title="a.coin + ' – ' + fmtPct(a.pct)"
              ></div>
            </div>
            <div class="alloc-legend">
              <div v-for="a in allocation" :key="a.coin" class="alloc-legend-item">
                <span class="alloc-dot" :style="{ background: getCoinColor(a.coin) }"></span>
                <span class="alloc-coin">{{ a.coin }}</span>
                <span class="alloc-pct">{{ fmtPct(a.pct) }}</span>
                <span class="alloc-val">${{ fmt(a.value) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Wallet Info -->
        <div class="tp-card wallet-card" v-if="walletAddress">
          <div class="wallet-header">
            <h3>
              <span class="material-symbols-outlined" style="color:var(--tp-primary);font-size:20px">wallet</span>
              Wallet
            </h3>
          </div>
          <div class="wallet-body">
            <div class="wallet-address-row">
              <span class="wallet-dot"></span>
              <span class="wallet-addr">{{ shortAddress }}</span>
              <span class="wallet-chain">Arbitrum</span>
            </div>
            <div class="wallet-detail-row">
              <span class="meta-label">Network</span>
              <span class="meta-value">Hyperliquid L1</span>
            </div>
            <div class="wallet-detail-row">
              <span class="meta-label">Open Positions</span>
              <span class="meta-value" style="font-weight: 700;">{{ livePositions.length || openPositionsCount }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Wallet error banner -->
    <div v-if="walletError" class="wallet-error-banner">
      <span class="material-symbols-outlined">warning</span>
      <span>{{ walletError }}</span>
    </div>
  </div>
</template>

<style scoped>
.dashboard-page {
  padding: 1rem 1.5rem 2rem;
}

/* ===== Grid Layout ===== */
.dash-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1.25rem;
}
@media (min-width: 1024px) {
  .dash-grid {
    grid-template-columns: 1.65fr 1fr;
  }
}
.left-col, .right-col {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  min-width: 0;
}

/* ===== Top Row: Bot + Stats — full-width strip above grid ===== */
.top-row {
  display: flex;
  gap: 0;
  border-radius: var(--tp-radius);
  overflow: hidden;
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
  border: var(--tp-glass-border);
  box-shadow: var(--tp-glass-shadow);
  margin-bottom: 1.25rem;
}

.bot-card {
  padding: 1rem 1.25rem;
  display: flex;
  flex-direction: column;
  justify-content: center;
  border-right: 1px solid var(--tp-border);
  background: none;
  backdrop-filter: none;
  border-radius: 0;
  border-top: none;
  border-bottom: none;
  border-left: none;
  box-shadow: none;
  flex-shrink: 0;
}
.bot-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.bot-label-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}
.bot-icon {
  width: 2rem; height: 2rem;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.bot-icon .material-symbols-outlined { font-size: 18px; }
.bot-icon-running {
  background: rgba(34,197,94,0.12);
  color: var(--tp-success);
}
.bot-icon-paused {
  background: rgba(245,158,11,0.12);
  color: var(--tp-warning);
}
.micro-label {
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 700;
  color: var(--tp-text-dim);
  margin: 0;
}
.bot-status-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.1rem;
}
.status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-running { background: var(--tp-success); }
.dot-paused { background: var(--tp-warning); }
.bot-status-text {
  font-size: 0.9rem;
  font-weight: 800;
  color: var(--tp-text);
  margin: 0;
}

.stats-row-card {
  display: flex;
  flex: 1;
  min-width: 0;
  background: none;
  backdrop-filter: none;
  border-radius: 0;
  border: none;
  box-shadow: none;
  padding: 0;
  align-items: stretch;
}
.mini-stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.2rem;
  padding: 1rem 1.25rem;
  border-right: 1px solid var(--tp-border);
  min-width: 0;
}
.mini-stat:last-child {
  border-right: none;
}
.mini-stat-value {
  font-size: 1.35rem;
  font-weight: 800;
  color: var(--tp-text);
  margin: 0;
  line-height: 1;
  font-feature-settings: 'tnum' 1;
  white-space: nowrap;
}
.text-success { color: var(--tp-success) !important; }
.text-danger { color: var(--tp-danger) !important; }

@media (max-width: 768px) {
  .top-row {
    flex-direction: column;
  }
  .bot-card {
    border-right: none;
    border-bottom: 1px solid var(--tp-border);
  }
  .stats-row-card {
    flex-wrap: wrap;
  }
  .mini-stat {
    min-width: 45%;
  }
}

/* ===== Prices Card ===== */
.prices-card {
  padding: 1.25rem;
}
.prices-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}
.prices-header h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  font-weight: 700;
}
.prices-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 0.5rem;
}
.price-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.6rem 0.75rem;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  transition: transform var(--tp-transition);
}
.price-item:hover {
  transform: translateY(-1px);
}
.price-coin-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.coin-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.6rem;
  font-weight: 800;
  letter-spacing: 0.03em;
  flex-shrink: 0;
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
.price-coin-name {
  font-weight: 700;
  font-size: 0.8rem;
  line-height: 1.2;
}
.price-coin-pair {
  font-size: 0.6rem;
  color: var(--tp-text-dim);
}
.price-value {
  font-size: 0.9rem;
  font-weight: 800;
  font-feature-settings: 'tnum' 1;
}

/* ===== Positions Card ===== */
.positions-card {
  overflow: hidden;
}
.positions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem;
  border-bottom: 1px solid var(--tp-border);
}
.positions-header h3 {
  font-size: 0.95rem;
  font-weight: 700;
}
.positions-header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.view-history-btn {
  background: none;
  border: none;
  color: var(--tp-primary);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  font-family: var(--tp-font);
}
.view-history-btn:hover { text-decoration: underline; }
.positions-body {
  padding: 0;
}
.empty-positions {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 2rem;
  text-align: center;
}
.empty-icon {
  width: 4rem; height: 4rem;
  border-radius: 50%;
  background: var(--tp-bg-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1rem;
}
.empty-title {
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--tp-text) !important;
  margin-bottom: 0.25rem;
}
.empty-desc {
  font-size: 0.85rem;
  color: var(--tp-text-dim) !important;
}

/* ===== Right Column: P&L Card ===== */
.pnl-card {
  padding: 1.25rem;
}
.pnl-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1rem;
}
.pnl-title {
  font-size: 0.95rem;
  font-weight: 700;
  margin: 0;
}
.pnl-subtitle {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
  margin: 0.15rem 0 0;
}
.pnl-total {
  font-size: 1.5rem;
  font-weight: 800;
  font-family: 'Inter', monospace;
}

.equity-chart {
  width: 100%;
  height: 5rem;
  margin-bottom: 0.75rem;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  overflow: hidden;
}
.equity-svg {
  width: 100%;
  height: 100%;
}
.equity-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 1.5rem;
  color: var(--tp-text-dim);
  font-size: 0.8rem;
  text-align: center;
}

.trade-bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 2.5rem;
  margin-bottom: 0.75rem;
  padding: 0 2px;
}
.trade-bar {
  flex: 1;
  border-radius: 2px 2px 0 0;
  min-height: 3px;
  transition: opacity 0.15s;
  cursor: default;
}
.trade-bar:hover { opacity: 0.7; }
.bar-win { background: #22c55e; }
.bar-loss { background: #ef4444; }

.pnl-stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.pnl-stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0;
  border-bottom: 1px solid var(--tp-border);
  font-size: 0.78rem;
}
.pnl-stat-label { color: var(--tp-text-dim); }
.pnl-stat-value { font-weight: 700; font-family: 'Inter', monospace; }

.pnl-history-btn {
  width: 100%;
  justify-content: center;
  font-size: 0.8rem;
}

/* ===== Margin Card ===== */
.margin-card {
  padding: 1.25rem;
}
.margin-header {
  margin-bottom: 1rem;
}
.margin-header h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  font-weight: 700;
}
.margin-bar-wrap {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.margin-bar {
  flex: 1;
  height: 6px;
  background: var(--tp-border);
  border-radius: 3px;
  overflow: hidden;
}
.margin-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.5s ease;
}
.bar-safe { background: var(--tp-success); }
.bar-warning { background: var(--tp-warning); }
.bar-danger { background: var(--tp-danger); }
.margin-pct {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--tp-text-dim);
  min-width: 3rem;
  text-align: right;
}
.margin-detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.35rem 0;
}
.margin-detail-row + .margin-detail-row {
  border-top: 1px solid var(--tp-border);
}
.meta-label {
  font-size: 0.78rem;
  color: var(--tp-text-dim);
}
.meta-value {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--tp-text);
}

/* ===== Allocation Card ===== */
.alloc-card {
  padding: 1.25rem;
}
.alloc-header {
  margin-bottom: 1rem;
}
.alloc-header h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  font-weight: 700;
}
.alloc-bar {
  display: flex;
  height: 10px;
  border-radius: 5px;
  overflow: hidden;
  gap: 2px;
  margin-bottom: 0.75rem;
}
.alloc-segment {
  min-width: 4px;
  border-radius: 3px;
  transition: width 0.5s ease;
}
.alloc-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
}
.alloc-legend-item {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
}
.alloc-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.alloc-coin {
  font-weight: 700;
  color: var(--tp-text);
}
.alloc-pct {
  color: var(--tp-text-dim);
  font-weight: 500;
}
.alloc-val {
  color: var(--tp-text-dim);
  font-size: 0.7rem;
}

/* ===== Wallet Card ===== */
.wallet-card {
  padding: 1.25rem;
}
.wallet-header {
  margin-bottom: 1rem;
}
.wallet-header h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  font-weight: 700;
}
.wallet-address-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  margin-bottom: 0.75rem;
}
.wallet-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--tp-success);
  box-shadow: 0 0 6px var(--tp-success);
}
.wallet-addr {
  font-family: var(--tp-font-mono);
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.wallet-chain {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--tp-text-dim);
  background: var(--tp-bg-glass);
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  margin-left: auto;
}
.wallet-detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.35rem 0;
}
.wallet-detail-row + .wallet-detail-row {
  border-top: 1px solid var(--tp-border);
}

/* Error banner */
.wallet-error-banner {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: var(--tp-radius-sm);
  color: var(--tp-danger);
  font-size: 0.85rem;
  margin-top: 1.5rem;
}

@media (max-width: 480px) {
  .prices-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
