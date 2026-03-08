<script setup>
import { ref, computed } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'

const cryptoLinks = [
  { to: '/crypto', label: 'Dashboard' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/logs', label: 'Logs' },
  { to: '/crypto/strategy', label: 'Strategy' },
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

// DB dashboard data
const openPositions = ref(0)
const totalPnl = ref(0)

// Allocation computed from live positions
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

// Colors for allocation
const COIN_COLORS = {
  BTC: '#f7931a', ETH: '#627eea', SOL: '#9945ff', AVAX: '#e84142',
  DOGE: '#c2a633', ARB: '#28a0f0', MATIC: '#8247e5', LINK: '#2a5ada',
  OP: '#ff0420', SUI: '#4da2ff',
}

function getCoinColor(coin) {
  return COIN_COLORS[coin] || 'var(--tp-primary)'
}

async function refresh() {
  const [botResult, dashResult, walletResult] = await Promise.allSettled([
    api.getCryptoBotStatus(),
    api.getCryptoDashboard(),
    api.getCryptoWallet(),
  ])

  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }
  if (dashResult.status === 'fulfilled') {
    openPositions.value = dashResult.value.open_positions ?? 0
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

usePolling(refresh, 15000)
</script>

<template>
  <div class="tp-page">
    <SectionNav :links="cryptoLinks" />

    <!-- Page Header -->
    <div class="dash-header">
      <div>
        <h1 class="dash-title">Crypto Portfolio</h1>
        <p class="dash-subtitle">Hyperliquid Perpetuals</p>
      </div>
      <div class="dash-header-right">
        <!-- Wallet badge -->
        <div v-if="walletAddress" class="wallet-badge">
          <span class="wallet-dot"></span>
          <span class="wallet-addr">{{ shortAddress }}</span>
          <span class="wallet-chain">Arbitrum</span>
        </div>
        <div v-else-if="walletLoaded && walletError" class="wallet-badge wallet-badge-error">
          <span class="material-symbols-outlined" style="font-size: 14px;">error</span>
          <span>Disconnected</span>
        </div>
        <!-- Bot control -->
        <button
          class="tp-btn"
          :class="botPaused ? 'tp-btn-success' : 'tp-btn-outline'"
          :disabled="botStatusLoading"
          @click="toggleBot"
        >
          <span class="material-symbols-outlined">{{ botPaused ? 'play_arrow' : 'pause' }}</span>
          {{ botPaused ? 'Resume Bot' : 'Pause Bot' }}
        </button>
      </div>
    </div>

    <!-- Portfolio Summary Row -->
    <div class="portfolio-row">
      <!-- Account Value Card (hero) -->
      <div class="portfolio-hero">
        <div class="hero-label">Account Equity</div>
        <div class="hero-value">${{ fmt(accountValue) }}</div>
        <div class="hero-pnl" :class="totalUnrealizedPnl >= 0 ? 'positive' : 'negative'">
          <span class="material-symbols-outlined" style="font-size: 16px;">
            {{ totalUnrealizedPnl >= 0 ? 'trending_up' : 'trending_down' }}
          </span>
          {{ totalUnrealizedPnl >= 0 ? '+' : '' }}${{ fmt(totalUnrealizedPnl) }} unrealized
        </div>
        <div class="hero-meta">
          <div class="hero-meta-item">
            <span class="meta-label">Withdrawable</span>
            <span class="meta-value">${{ fmt(withdrawable) }}</span>
          </div>
          <div class="hero-meta-item">
            <span class="meta-label">Closed P&L</span>
            <span class="meta-value" :style="{ color: totalPnl >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
              {{ totalPnl >= 0 ? '+' : '' }}${{ fmt(totalPnl) }}
            </span>
          </div>
        </div>
      </div>

      <!-- Margin & Risk Card -->
      <div class="tp-stat-card portfolio-card">
        <div class="stat-label">Margin Usage</div>
        <div class="stat-value">${{ fmt(totalMarginUsed) }}</div>
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
        <div class="card-detail-row">
          <span class="meta-label">Notional Exposure</span>
          <span class="meta-value">${{ fmt(Math.abs(totalNtlPos)) }}</span>
        </div>
      </div>

      <!-- Bot & Positions Card -->
      <div class="tp-stat-card portfolio-card">
        <div class="stat-label">Trading Bot</div>
        <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem;">
          <span class="tp-badge" :class="botPaused ? 'tp-badge-warning' : 'tp-badge-success'">
            <span v-if="!botPaused" class="pulse-dot"></span>
            {{ botPaused ? 'Paused' : 'Running' }}
          </span>
        </div>
        <div class="card-detail-row">
          <span class="meta-label">Open Positions</span>
          <span class="meta-value" style="font-weight: 700;">{{ livePositions.length || openPositions }}</span>
        </div>
        <div class="card-detail-row">
          <span class="meta-label">Position Value</span>
          <span class="meta-value">${{ fmt(totalPositionValue) }}</span>
        </div>
        <div style="margin-top: 0.75rem;">
          <RouterLink to="/crypto/positions" class="tp-btn tp-btn-outline" style="width: 100%; font-size: 0.75rem;">
            View All Positions
          </RouterLink>
        </div>
      </div>
    </div>

    <!-- Live Prices Grid -->
    <div class="section-header">
      <h2 class="section-title">Live Prices</h2>
      <span class="tp-badge tp-badge-success" style="font-size: 0.6rem;">
        <span class="pulse-dot"></span> Real-time
      </span>
    </div>
    <div class="prices-grid">
      <div v-for="p in prices" :key="p.coin" class="price-card">
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

    <!-- Allocation Bar (only if positions exist) -->
    <div v-if="allocation.length" class="tp-card" style="margin-bottom: 1.5rem;">
      <div style="padding: 1.25rem;">
        <div class="section-header" style="margin-bottom: 1rem;">
          <h3 class="section-title" style="font-size: 1rem;">Portfolio Allocation</h3>
        </div>
        <!-- Stacked bar -->
        <div class="alloc-bar">
          <div
            v-for="a in allocation"
            :key="a.coin"
            class="alloc-segment"
            :style="{ width: fmtPct(a.pct), background: getCoinColor(a.coin) }"
            :title="a.coin + ' – ' + fmtPct(a.pct)"
          ></div>
        </div>
        <!-- Legend -->
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

    <!-- Live Positions Table -->
    <div class="tp-card">
      <div style="padding: 1rem 1.5rem; border-bottom: 1px solid var(--tp-border); display: flex; align-items: center; justify-content: space-between;">
        <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0;">On-Chain Positions</h3>
        <span class="tp-badge tp-badge-primary">{{ livePositions.length }} active</span>
      </div>
      <div style="overflow-x: auto;">
        <table class="tp-table">
          <thead>
            <tr>
              <th>Asset</th>
              <th>Side</th>
              <th>Size</th>
              <th>Entry Price</th>
              <th>Mark Price</th>
              <th>Leverage</th>
              <th>Margin Used</th>
              <th>Unrealized P&L</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!livePositions.length">
              <td colspan="8" style="padding: 3rem 2rem; text-align: center;">
                <div style="display: flex; flex-direction: column; align-items: center;">
                  <div class="empty-icon">
                    <span class="material-symbols-outlined" style="font-size: 2rem; color: var(--tp-text-dim);">account_balance_wallet</span>
                  </div>
                  <p style="font-weight: 600; margin-bottom: 0.25rem;">No open positions</p>
                  <p style="font-size: 0.8rem; color: var(--tp-text-dim); margin: 0;">Live positions from Hyperliquid will appear here.</p>
                </div>
              </td>
            </tr>
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
    </div>

    <!-- Wallet error banner -->
    <div v-if="walletError" class="wallet-error-banner">
      <span class="material-symbols-outlined">warning</span>
      <span>{{ walletError }}</span>
    </div>
  </div>
</template>

<style scoped>
/* Dashboard Header */
.dash-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 2rem;
  flex-wrap: wrap;
  gap: 1rem;
}
.dash-title {
  font-size: 2.25rem;
  font-weight: 900;
  letter-spacing: -0.02em;
}
.dash-subtitle {
  color: var(--tp-text-dim);
  margin-top: 0.25rem;
  font-size: 0.9rem;
}
.dash-header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

/* Wallet Badge */
.wallet-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.85rem;
  background: var(--tp-bg-glass);
  border: 1px solid var(--tp-border);
  border-radius: 9999px;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--tp-text-muted);
  backdrop-filter: var(--tp-glass-blur);
}
.wallet-badge-error {
  border-color: var(--tp-danger);
  color: var(--tp-danger);
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
  font-size: 0.78rem;
  letter-spacing: 0.02em;
}
.wallet-chain {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--tp-text-dim);
  background: var(--tp-bg-surface);
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
}

/* Portfolio Summary Row */
.portfolio-row {
  display: grid;
  grid-template-columns: 1.5fr 1fr 1fr;
  gap: 1rem;
  margin-bottom: 2rem;
}
@media (max-width: 900px) {
  .portfolio-row {
    grid-template-columns: 1fr;
  }
}

/* Hero Card */
.portfolio-hero {
  padding: 1.5rem;
  background: var(--tp-gradient-primary);
  border-radius: var(--tp-radius);
  color: white;
  position: relative;
  overflow: hidden;
}
.portfolio-hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 80% 20%, rgba(255,255,255,0.1), transparent 60%);
  pointer-events: none;
}
.hero-label {
  font-size: 0.8rem;
  font-weight: 500;
  opacity: 0.85;
  margin-bottom: 0.25rem;
}
.hero-value {
  font-size: 2.2rem;
  font-weight: 900;
  letter-spacing: -0.02em;
  line-height: 1.1;
  margin-bottom: 0.5rem;
}
.hero-pnl {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.85rem;
  font-weight: 600;
  padding: 0.2rem 0.6rem;
  border-radius: 6px;
  margin-bottom: 1rem;
}
.hero-pnl.positive {
  background: rgba(52, 211, 153, 0.2);
  color: #6ee7b7;
}
.hero-pnl.negative {
  background: rgba(248, 113, 113, 0.2);
  color: #fca5a5;
}
.hero-meta {
  display: flex;
  gap: 1.5rem;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(255,255,255,0.15);
}
.hero-meta-item {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.hero-meta .meta-label {
  font-size: 0.7rem;
  opacity: 0.7;
  font-weight: 500;
}
.hero-meta .meta-value {
  font-size: 1rem;
  font-weight: 700;
}

/* Portfolio cards */
.portfolio-card {
  display: flex;
  flex-direction: column;
}
.card-detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.35rem 0;
}
.card-detail-row + .card-detail-row {
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

/* Margin bar */
.margin-bar-wrap {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.75rem 0;
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

/* Section Headers */
.section-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.section-title {
  font-size: 1.15rem;
  font-weight: 800;
  letter-spacing: -0.01em;
}

/* Live Prices Grid */
.prices-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 0.75rem;
  margin-bottom: 2rem;
}
.price-card {
  padding: 1rem;
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius);
  transition: transform var(--tp-transition), box-shadow var(--tp-transition);
}
.price-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
}
.price-coin-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.6rem;
}
.coin-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
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
  font-size: 0.9rem;
  line-height: 1.2;
}
.price-coin-pair {
  font-size: 0.65rem;
  color: var(--tp-text-dim);
}
.price-value {
  font-size: 1.1rem;
  font-weight: 800;
  font-family: var(--tp-font);
  font-feature-settings: 'tnum' 1;
}

/* Allocation Bar */
.alloc-bar {
  display: flex;
  height: 12px;
  border-radius: 6px;
  overflow: hidden;
  gap: 2px;
  margin-bottom: 1rem;
}
.alloc-segment {
  min-width: 4px;
  border-radius: 3px;
  transition: width 0.5s ease;
}
.alloc-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1.5rem;
}
.alloc-legend-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
}
.alloc-dot {
  width: 8px;
  height: 8px;
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
  font-size: 0.75rem;
}

/* Empty state */
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
  .dash-title { font-size: 1.75rem; }
  .hero-value { font-size: 1.5rem; }
  .hero-meta { flex-direction: column; gap: 0.5rem; }
  .prices-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
