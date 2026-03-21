<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { usePolling } from '@/composables/usePolling'
import { useWebSocket } from '@/composables/useWebSocket'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'
import { cryptoLinks, COIN_COLORS, fmt, fmtPrice } from '@/utils/cryptoConstants'

const router = useRouter()

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

// Venue health
const venueHealth = reactive({
  lighter: { status: 'unknown', latency: null, lastCheck: null },
  hyperliquid: { status: 'unknown', latency: null, lastCheck: null },
})

// Per-venue trading toggles
const lighterEnabled = ref(true)
const lighterToggling = ref(false)
const hyperliquidEnabled = ref(true)
const hyperliquidToggling = ref(false)

// Lighter proxy direct state (browser → macOS localhost:5555)
const proxyDirect = reactive({
  online: false,
  active: false,
  uptime: 0,
  markets: 0,
})

// Active venue tab for positions
const activeVenueTab = ref('all')

// News feed
const newsFeed = ref([])
const newsLoading = ref(false)

// WebSocket (enhancement over polling — polling remains the primary data source)
const { connected: wsConnected, on: wsOn } = useWebSocket()

wsOn('bot_status', (data) => {
  if (data && data.paused != null) botPaused.value = data.paused
})

wsOn('trade_opened', () => {
  refresh()
})

wsOn('trade_closed', () => {
  refresh()
})

wsOn('position_update', () => {
  refresh()
})

wsOn('price_update', () => {
  refresh()
})

wsOn('news_alert', (data) => {
  if (data && data.headline) {
    newsFeed.value.unshift(data)
    if (newsFeed.value.length > 20) newsFeed.value.pop()
  }
})

// Funding rates (mock structure — will populate from API when available)
const fundingRates = ref([
  { symbol: 'BTC', lighter: null, hyperliquid: null },
  { symbol: 'ETH', lighter: null, hyperliquid: null },
  { symbol: 'SOL', lighter: null, hyperliquid: null },
])

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

const marginLevel = computed(() => {
  if (!totalMarginUsed.value) return Infinity
  return (accountValue.value / totalMarginUsed.value) * 100
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
  const losses = ct.filter(p => Number(p.pnl_usd) < 0)
  const total = ct.reduce((s, p) => s + Number(p.pnl_usd), 0)
  const winRate = ct.length ? (wins.length / ct.length * 100) : 0
  const bestTrade = ct.length ? Math.max(...ct.map(p => Number(p.pnl_usd))) : 0
  const worstTrade = ct.length ? Math.min(...ct.map(p => Number(p.pnl_usd))) : 0
  const avgWin = wins.length ? wins.reduce((s, p) => s + Number(p.pnl_usd), 0) / wins.length : 0
  const avgLoss = losses.length ? losses.reduce((s, p) => s + Number(p.pnl_usd), 0) / losses.length : 0
  const profitFactor = avgLoss !== 0 ? Math.abs(avgWin * wins.length / (avgLoss * losses.length)) : 0
  return { total: ct.length, wins: wins.length, losses: losses.length, totalPnl: total, winRate, bestTrade, worstTrade, avgWin, avgLoss, profitFactor }
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

// Filtered positions by venue tab
const filteredPositions = computed(() => {
  if (activeVenueTab.value === 'all') return livePositions.value
  return livePositions.value.filter(p => (p.venue || 'hyperliquid') === activeVenueTab.value)
})

const positionsByVenue = computed(() => {
  const hl = livePositions.value.filter(p => (p.venue || 'hyperliquid') === 'hyperliquid')
  const lt = livePositions.value.filter(p => (p.venue || '') === 'lighter')
  return { hyperliquid: hl, lighter: lt }
})

function getCoinColor(coin) {
  return COIN_COLORS[coin] || 'var(--tp-primary)'
}

async function checkVenueHealth() {
  // Check Lighter proxy via Django endpoint (also returns account data)
  try {
    const data = await api.getLighterProxyStatus()
    venueHealth.lighter = {
      status: data.proxy_status || 'unknown',
      latency: data.latency_ms,
      lastCheck: new Date(),
    }
    lighterEnabled.value = data.enabled !== false

    // Update account stats from Lighter — ONLY if data is valid (never reset to zero)
    if (data.equity != null && data.equity > 0) {
      accountValue.value = data.equity
      withdrawable.value = data.available_balance ?? 0
      totalMarginUsed.value = data.equity - (data.available_balance ?? 0)
      totalNtlPos.value = data.equity - (data.available_balance ?? 0)
    }
  } catch {
    // Don't reset venue health on failure — keep last known state
    if (venueHealth.lighter.status === 'unknown') {
      venueHealth.lighter = { status: 'offline', latency: null, lastCheck: new Date() }
    }
  }

  // Hyperliquid health is inferred from wallet call success
  if (walletLoaded.value && !walletError.value) {
    venueHealth.hyperliquid = { status: 'connected', latency: null, lastCheck: new Date() }
  } else if (walletError.value) {
    venueHealth.hyperliquid = { status: 'error', latency: null, lastCheck: new Date() }
  }

  // Fetch Hyperliquid trading toggle state
  try {
    const hlData = await api.getHyperliquidStatus()
    hyperliquidEnabled.value = hlData.enabled !== false
  } catch {
    // fail silently
  }
}

async function checkProxyDirect() {
  const data = await api.lighterProxyDirect()
  proxyDirect.online = !data._offline
  proxyDirect.active = data.active ?? false
  proxyDirect.uptime = data.uptime_s ?? 0
  proxyDirect.markets = data.markets ?? 0
}

async function toggleLighter() {
  lighterToggling.value = true
  try {
    // Toggle directly on the macOS proxy (no Django middleman)
    const resp = await api.lighterProxyToggle()
    proxyDirect.active = resp.active
    // Also sync the Django-side flag for Celery tasks
    await api.setLighterEnabled(resp.active)
    lighterEnabled.value = resp.active
  } catch (err) {
    console.error('Lighter toggle error:', err)
  }
  lighterToggling.value = false
}

async function toggleHyperliquid() {
  hyperliquidToggling.value = true
  try {
    const resp = await api.setHyperliquidEnabled(!hyperliquidEnabled.value)
    hyperliquidEnabled.value = resp.enabled
  } catch (err) {
    console.error('Hyperliquid toggle error:', err)
  }
  hyperliquidToggling.value = false
}

async function fetchFundingRates() {
  try {
    const resp = await fetch('/api/django/v1/crypto/funding-rates/', { signal: AbortSignal.timeout(5000) })
    if (resp.ok) {
      const data = await resp.json()
      if (Array.isArray(data)) {
        fundingRates.value = data
      }
    }
  } catch {
    // Funding rates are optional — fail silently
  }
}

async function fetchNews() {
  newsLoading.value = true
  try {
    const data = await api.getCryptoNews()
    if (Array.isArray(data)) {
      newsFeed.value = data.slice(0, 20)
    }
  } catch {
    // News is optional — fail silently
  }
  newsLoading.value = false
}

function timeAgo(timestamp) {
  if (!timestamp) return ''
  const seconds = Math.floor(Date.now() / 1000) - timestamp
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago'
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago'
  return Math.floor(seconds / 86400) + 'd ago'
}

async function refresh() {
  const [botResult, dashResult, walletResult, closedResult, openResult] = await Promise.allSettled([
    api.getCryptoBotStatus(),
    api.getCryptoDashboard(),
    api.getCryptoWallet(),
    api.getCryptoPositions('CLOSED'),
    api.getCryptoPositions('OPEN'),
  ])

  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }
  if (dashResult.status === 'fulfilled') {
    openPositionsCount.value = dashResult.value.open_positions ?? 0
    totalPnl.value = dashResult.value.total_pnl ?? 0
  }

  // Build price map from wallet for live mark prices
  let priceMap = {}
  if (walletResult.status === 'fulfilled') {
    const w = walletResult.value
    walletAddress.value = w.wallet_address ?? ''
    accountValue.value = w.account_value ?? 0
    totalMarginUsed.value = w.total_margin_used ?? 0
    totalNtlPos.value = w.total_ntl_pos ?? 0
    withdrawable.value = w.withdrawable ?? 0
    prices.value = w.prices ?? []
    walletError.value = ''
    walletLoaded.value = true
    for (const p of (w.prices ?? [])) priceMap[p.coin] = p.price
  } else if (walletResult.status === 'rejected') {
    walletError.value = walletResult.reason?.message || 'Failed to load wallet'
    walletLoaded.value = true
  }

  // Build livePositions from DB open positions (Lighter reconciler keeps these in sync)
  if (openResult.status === 'fulfilled') {
    const dbOpen = openResult.value.results ?? openResult.value ?? []
    livePositions.value = dbOpen.map(p => {
      const mark = priceMap[p.symbol] ?? null
      const uPnl = mark && p.entry_price
        ? (p.side === 'LONG' ? (mark - p.entry_price) * p.size : (p.entry_price - mark) * p.size)
        : 0
      return {
        coin: p.symbol,
        side: p.side,
        size: p.size,
        entry_price: p.entry_price,
        mark_price: mark,
        leverage: p.leverage,
        margin_used: p.entry_price * p.size / p.leverage,
        unrealized_pnl: uPnl,
        venue: 'lighter',
      }
    })
  }

  if (closedResult.status === 'fulfilled') {
    closedPositions.value = closedResult.value.results ?? closedResult.value ?? []
  }

  // Non-blocking secondary fetches
  checkVenueHealth()
  fetchFundingRates()
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

function fmtPct(val) {
  return (val * 100).toFixed(1) + '%'
}

function fmtFunding(val) {
  if (val == null) return '--'
  return (val * 100).toFixed(4) + '%'
}

// Lighter proxy direct — three-state display
const proxyDirectIcon = computed(() => {
  if (!proxyDirect.online) return 'cancel'
  return proxyDirect.active ? 'check_circle' : 'pause_circle'
})
const proxyDirectLabel = computed(() => {
  if (!proxyDirect.online) return 'OFFLINE'
  return proxyDirect.active ? 'ACTIVE' : 'STANDBY'
})
const proxyDirectClass = computed(() => {
  if (!proxyDirect.online) return 'venue-down'
  return proxyDirect.active ? 'venue-ok' : 'venue-standby'
})

function venueStatusIcon(status) {
  switch (status) {
    case 'connected': return 'check_circle'
    case 'error': return 'error'
    case 'offline': return 'cancel'
    default: return 'help'
  }
}

function venueStatusClass(status) {
  switch (status) {
    case 'connected': return 'venue-ok'
    case 'error': return 'venue-warn'
    case 'offline': return 'venue-down'
    default: return 'venue-unknown'
  }
}

onMounted(() => {
  refresh()
  fetchNews()
  checkProxyDirect()
})
usePolling(refresh, 30000)  // 30s — Lighter API is slow + rate limited
usePolling(fetchNews, 300000)  // 5 min — news doesn't need real-time polling
usePolling(checkProxyDirect, 10000)  // 10s — lightweight direct ping to macOS proxy
</script>

<template>
  <SectionNav :links="cryptoLinks" />
  <div class="tp-page dashboard-page">

    <!-- ======= SYSTEM STATUS BAR ======= -->
    <div class="system-bar">
      <div class="system-bar-left">
        <div class="bot-indicator" :class="botPaused ? 'bot-paused' : 'bot-live'">
          <span class="material-symbols-outlined bot-pulse-icon">currency_bitcoin</span>
          <div class="bot-indicator-text">
            <span class="bot-indicator-label">CRYPTO ENGINE</span>
            <span class="bot-indicator-status">{{ botPaused ? 'PAUSED' : 'LIVE' }}</span>
          </div>
          <button
            class="bot-toggle-btn"
            :class="botPaused ? 'btn-resume' : 'btn-pause'"
            :aria-busy="botStatusLoading"
            @click="toggleBot"
          >
            <span class="material-symbols-outlined" style="font-size:14px">{{ botPaused ? 'play_arrow' : 'pause' }}</span>
            {{ botPaused ? 'Resume' : 'Pause' }}
          </button>
        </div>

        <span v-if="wsConnected" class="ws-badge" title="WebSocket connected">WS</span>

        <div class="system-bar-divider"></div>

        <!-- Venue Health Indicators -->
        <div class="venue-health-group">
          <div class="venue-chip" :class="[venueStatusClass(venueHealth.hyperliquid.status), { 'venue-disabled': !hyperliquidEnabled }]">
            <span class="material-symbols-outlined venue-chip-icon">{{ venueStatusIcon(venueHealth.hyperliquid.status) }}</span>
            <span class="venue-chip-name">Hyperliquid</span>
            <button
              class="venue-toggle-btn"
              :class="hyperliquidEnabled ? 'vt-on' : 'vt-off'"
              :aria-busy="hyperliquidToggling"
              @click.stop="toggleHyperliquid"
              :title="hyperliquidEnabled ? 'Disable Hyperliquid trading' : 'Enable Hyperliquid trading'"
            >
              <span class="material-symbols-outlined" style="font-size:13px">{{ hyperliquidEnabled ? 'pause' : 'play_arrow' }}</span>
            </button>
          </div>
          <div class="venue-chip" :class="proxyDirectClass">
            <span class="material-symbols-outlined venue-chip-icon">{{ proxyDirectIcon }}</span>
            <span class="venue-chip-name">Lighter</span>
            <span class="venue-chip-state">{{ proxyDirectLabel }}</span>
            <span v-if="proxyDirect.online && proxyDirect.uptime" class="venue-chip-latency">
              {{ Math.floor(proxyDirect.uptime / 60) }}m up
            </span>
            <button
              class="venue-toggle-btn"
              :class="proxyDirect.active ? 'vt-on' : 'vt-off'"
              :disabled="!proxyDirect.online"
              :aria-busy="lighterToggling"
              @click.stop="toggleLighter"
              :title="!proxyDirect.online ? 'Proxy offline — start it on macOS' : proxyDirect.active ? 'Pause Lighter trading' : 'Activate Lighter trading'"
            >
              <span class="material-symbols-outlined" style="font-size:13px">
                {{ !proxyDirect.online ? 'power_off' : proxyDirect.active ? 'pause' : 'play_arrow' }}
              </span>
            </button>
          </div>
        </div>
      </div>

      <div class="system-bar-right">
        <div class="sys-stat">
          <span class="sys-stat-label">ACCOUNT</span>
          <span class="sys-stat-value">${{ fmt(accountValue) }}</span>
        </div>
        <div class="sys-stat">
          <span class="sys-stat-label">UNREAL. P&L</span>
          <span class="sys-stat-value" :class="totalUnrealizedPnl >= 0 ? 'text-success' : 'text-danger'">
            {{ totalUnrealizedPnl >= 0 ? '+' : '' }}${{ fmt(totalUnrealizedPnl) }}
          </span>
        </div>
        <div class="sys-stat">
          <span class="sys-stat-label">MARGIN</span>
          <span class="sys-stat-value">{{ marginUsedPct.toFixed(1) }}%</span>
        </div>
        <div class="sys-stat">
          <span class="sys-stat-label">WITHDRAW</span>
          <span class="sys-stat-value">${{ fmt(withdrawable) }}</span>
        </div>
      </div>
    </div>

    <!-- ======= MAIN GRID ======= -->
    <div class="dash-grid">

      <!-- ===== LEFT COLUMN ===== -->
      <div class="left-col">

        <!-- Live Prices -->
        <div class="tp-card card-terminal prices-card">
          <div class="card-header-row">
            <div class="card-title-group">
              <span class="material-symbols-outlined card-icon">show_chart</span>
              <h3>Live Prices</h3>
            </div>
            <span class="tp-badge tp-badge-success" style="font-size: 0.6rem;">
              <span class="pulse-dot"></span> FEED
            </span>
          </div>
          <div class="prices-grid">
            <div v-for="p in prices" :key="p.coin" class="price-tile">
              <div class="price-tile-head">
                <div class="coin-badge" :style="{ background: getCoinColor(p.coin) + '18', color: getCoinColor(p.coin), borderColor: getCoinColor(p.coin) + '30' }">
                  {{ p.coin.slice(0, 2) }}
                </div>
                <span class="price-ticker">{{ p.coin }}</span>
              </div>
              <div class="price-amount">${{ fmtPrice(p.price) }}</div>
            </div>
          </div>
        </div>

        <!-- Funding Rate Comparison -->
        <div class="tp-card card-terminal funding-card">
          <div class="card-header-row">
            <div class="card-title-group">
              <span class="material-symbols-outlined card-icon">compare_arrows</span>
              <h3>Funding Rates</h3>
            </div>
            <span class="funding-legend">
              <span class="funding-legend-dot" style="background: #3b82f6;"></span> Hyperliquid
              <span class="funding-legend-dot" style="background: #a855f7; margin-left: 0.5rem;"></span> Lighter
            </span>
          </div>
          <div class="funding-grid">
            <div v-for="fr in fundingRates" :key="fr.symbol" class="funding-row">
              <span class="funding-symbol">{{ fr.symbol }}</span>
              <div class="funding-bars">
                <div class="funding-bar-pair">
                  <div class="funding-bar-track">
                    <div
                      class="funding-bar-fill funding-bar-hl"
                      :style="{ width: fr.hyperliquid != null ? Math.min(Math.abs(fr.hyperliquid) * 10000, 100) + '%' : '0%' }"
                      :class="{ 'funding-negative': fr.hyperliquid < 0 }"
                    ></div>
                  </div>
                  <span class="funding-rate-val" :class="{ 'text-danger': fr.hyperliquid < 0, 'text-success': fr.hyperliquid > 0 }">{{ fmtFunding(fr.hyperliquid) }}</span>
                </div>
                <div class="funding-bar-pair">
                  <div class="funding-bar-track">
                    <div
                      class="funding-bar-fill funding-bar-lt"
                      :style="{ width: fr.lighter != null ? Math.min(Math.abs(fr.lighter) * 10000, 100) + '%' : '0%' }"
                      :class="{ 'funding-negative': fr.lighter < 0 }"
                    ></div>
                  </div>
                  <span class="funding-rate-val" :class="{ 'text-danger': fr.lighter < 0, 'text-success': fr.lighter > 0 }">{{ fmtFunding(fr.lighter) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- On-Chain Positions -->
        <div class="tp-card card-terminal positions-card">
          <div class="card-header-row positions-header">
            <div class="card-title-group">
              <h3>Positions</h3>
            </div>
            <div class="positions-header-right">
              <div class="venue-tab-group">
                <button
                  class="venue-tab"
                  :class="{ active: activeVenueTab === 'all' }"
                  @click="activeVenueTab = 'all'"
                >All ({{ livePositions.length }})</button>
                <button
                  class="venue-tab"
                  :class="{ active: activeVenueTab === 'hyperliquid' }"
                  @click="activeVenueTab = 'hyperliquid'"
                >HL ({{ positionsByVenue.hyperliquid.length }})</button>
                <button
                  class="venue-tab"
                  :class="{ active: activeVenueTab === 'lighter' }"
                  @click="activeVenueTab = 'lighter'"
                >LT ({{ positionsByVenue.lighter.length }})</button>
              </div>
              <button class="view-history-btn" @click="router.push('/crypto/history')">
                <span class="material-symbols-outlined" style="font-size:14px">history</span>
                History
              </button>
            </div>
          </div>
          <div class="positions-body">
            <template v-if="filteredPositions.length > 0">
              <div style="overflow-x: auto;">
                <table class="tp-table terminal-table">
                  <thead>
                    <tr>
                      <th>Asset</th>
                      <th>Venue</th>
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
                    <tr v-for="p in filteredPositions" :key="p.coin + (p.venue || '')">
                      <td>
                        <div class="cell-asset">
                          <div class="coin-icon-sm" :style="{ background: getCoinColor(p.coin) + '22', color: getCoinColor(p.coin) }">
                            {{ p.coin.slice(0, 2) }}
                          </div>
                          <span class="asset-name">{{ p.coin }}</span>
                        </div>
                      </td>
                      <td>
                        <span class="venue-label" :class="(p.venue || 'hyperliquid') === 'lighter' ? 'venue-lighter' : 'venue-hl'">
                          {{ (p.venue || 'hyperliquid') === 'lighter' ? 'LT' : 'HL' }}
                        </span>
                      </td>
                      <td>
                        <span class="tp-badge" :class="p.side === 'LONG' ? 'tp-badge-success' : 'tp-badge-danger'">
                          {{ p.side }}
                        </span>
                      </td>
                      <td class="mono-cell">{{ fmt(Math.abs(p.size), 4) }}</td>
                      <td class="mono-cell">${{ fmtPrice(p.entry_price) }}</td>
                      <td class="mono-cell">${{ fmtPrice(p.mark_price) }}</td>
                      <td class="mono-cell">{{ p.leverage }}x</td>
                      <td class="mono-cell">${{ fmt(p.margin_used) }}</td>
                      <td>
                        <span class="pnl-cell" :class="p.unrealized_pnl >= 0 ? 'text-success' : 'text-danger'">
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
              <p class="empty-desc">Positions from Hyperliquid and Lighter will appear here.</p>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== RIGHT COLUMN ===== -->
      <div class="right-col">

        <!-- P&L Performance Card -->
        <div class="tp-card card-terminal pnl-card">
          <div class="pnl-header">
            <div>
              <div class="card-title-group">
                <span class="material-symbols-outlined card-icon">analytics</span>
                <h3 class="pnl-title">Performance</h3>
              </div>
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
              <path :d="chartFill" :fill="pnlStats.totalPnl >= 0 ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)'" />
              <path :d="chartPath" fill="none" :stroke="pnlStats.totalPnl >= 0 ? '#22c55e' : '#ef4444'" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
          <div v-else class="equity-empty">
            <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">show_chart</span>
            <p>Waiting for closed trades...</p>
          </div>

          <!-- Trade Bars -->
          <div class="trade-bars" v-if="sortedClosed.length">
            <div v-for="(t, i) in sortedClosed.slice(-30)" :key="i"
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
            <div class="pnl-stat">
              <span class="pnl-stat-label">Avg Win</span>
              <span class="pnl-stat-value text-success">+${{ pnlStats.avgWin.toFixed(2) }}</span>
            </div>
            <div class="pnl-stat">
              <span class="pnl-stat-label">Profit Factor</span>
              <span class="pnl-stat-value">{{ pnlStats.profitFactor.toFixed(2) }}</span>
            </div>
          </div>

          <button class="tp-btn tp-btn-outline pnl-history-btn" @click="router.push('/crypto/history')">
            <span class="material-symbols-outlined" style="font-size:16px">history</span>
            View Full History
          </button>
        </div>

        <!-- Crypto News Feed -->
        <div class="tp-card card-terminal news-card">
          <div class="card-header-row">
            <div class="card-title-group">
              <span class="material-symbols-outlined card-icon">newspaper</span>
              <h3>Crypto News</h3>
            </div>
            <span v-if="newsLoading" class="tp-badge tp-badge-dim" style="font-size: 0.55rem;">
              <span class="material-symbols-outlined" style="font-size:12px">sync</span> Loading
            </span>
          </div>
          <div class="news-body">
            <template v-if="newsFeed.length > 0">
              <a
                v-for="article in newsFeed.slice(0, 8)"
                :key="article.id || article.datetime"
                :href="article.url"
                target="_blank"
                rel="noopener noreferrer"
                class="news-item"
              >
                <div class="news-item-top">
                  <span class="news-source-badge">{{ article.source }}</span>
                  <span class="news-time">{{ timeAgo(article.datetime) }}</span>
                </div>
                <div class="news-headline">{{ article.headline }}</div>
                <span class="news-link-icon material-symbols-outlined">open_in_new</span>
              </a>
            </template>
            <div v-else class="news-empty">
              <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">newspaper</span>
              <p>No recent crypto news</p>
            </div>
          </div>
        </div>

        <!-- Margin & Risk Card -->
        <div class="tp-card card-terminal margin-card">
          <div class="card-header-row">
            <div class="card-title-group">
              <span class="material-symbols-outlined card-icon">shield</span>
              <h3>Margin & Risk</h3>
            </div>
            <span class="margin-level-badge" :class="{
              'badge-safe': marginUsedPct < 50,
              'badge-warning': marginUsedPct >= 50 && marginUsedPct < 80,
              'badge-danger': marginUsedPct >= 80,
            }">
              {{ marginUsedPct < 50 ? 'LOW RISK' : marginUsedPct < 80 ? 'MODERATE' : 'HIGH RISK' }}
            </span>
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
            <div class="margin-detail-row">
              <span class="meta-label">Margin Level</span>
              <span class="meta-value">{{ marginLevel === Infinity ? '--' : marginLevel.toFixed(0) + '%' }}</span>
            </div>
          </div>
        </div>

        <!-- Portfolio Allocation -->
        <div v-if="allocation.length" class="tp-card card-terminal alloc-card">
          <div class="card-header-row">
            <div class="card-title-group">
              <span class="material-symbols-outlined card-icon">pie_chart</span>
              <h3>Allocation</h3>
            </div>
          </div>
          <div class="alloc-body">
            <div class="alloc-bar">
              <div
                v-for="a in allocation"
                :key="a.coin"
                class="alloc-segment"
                :style="{ width: fmtPct(a.pct), background: getCoinColor(a.coin) }"
                :title="a.coin + ' - ' + fmtPct(a.pct)"
              ></div>
            </div>
            <div class="alloc-legend">
              <div v-for="a in allocation" :key="a.coin" class="alloc-legend-item">
                <span class="alloc-dot" :style="{ background: getCoinColor(a.coin) }"></span>
                <span class="alloc-coin">{{ a.coin }}</span>
                <span class="alloc-side" :class="a.side === 'LONG' ? 'text-success' : 'text-danger'">{{ a.side }}</span>
                <span class="alloc-pct">{{ fmtPct(a.pct) }}</span>
                <span class="alloc-val">${{ fmt(a.value) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Wallet & Venues -->
        <div class="tp-card card-terminal wallet-card">
          <div class="card-header-row">
            <div class="card-title-group">
              <span class="material-symbols-outlined card-icon">wallet</span>
              <h3>Wallet & Venues</h3>
            </div>
          </div>
          <div class="wallet-body">
            <!-- Hyperliquid Venue -->
            <div class="venue-block">
              <div class="venue-block-header">
                <span class="venue-block-dot" :class="venueStatusClass(venueHealth.hyperliquid.status)"></span>
                <span class="venue-block-name">Hyperliquid L1</span>
                <span class="venue-block-chain">Arbitrum</span>
                <button
                  class="venue-block-toggle"
                  :class="hyperliquidEnabled ? 'vbt-on' : 'vbt-off'"
                  :aria-busy="hyperliquidToggling"
                  @click="toggleHyperliquid"
                >
                  <span class="material-symbols-outlined" style="font-size:13px">{{ hyperliquidEnabled ? 'pause' : 'play_arrow' }}</span>
                  {{ hyperliquidEnabled ? 'Disable' : 'Enable' }}
                </button>
              </div>
              <div v-if="walletAddress" class="wallet-address-row">
                <span class="wallet-addr">{{ shortAddress }}</span>
              </div>
              <div class="venue-block-stats">
                <div class="venue-mini-stat">
                  <span class="meta-label">Positions</span>
                  <span class="meta-value">{{ positionsByVenue.hyperliquid.length }}</span>
                </div>
                <div class="venue-mini-stat">
                  <span class="meta-label">Network</span>
                  <span class="meta-value">Hyperliquid L1</span>
                </div>
              </div>
            </div>

            <!-- Lighter Venue -->
            <div class="venue-block">
              <div class="venue-block-header">
                <span class="venue-block-dot" :class="venueStatusClass(venueHealth.lighter.status)"></span>
                <span class="venue-block-name">Lighter.xyz</span>
                <span class="venue-block-chain">Zero-Fee</span>
                <button
                  class="venue-block-toggle"
                  :class="lighterEnabled ? 'vbt-on' : 'vbt-off'"
                  :aria-busy="lighterToggling"
                  @click="toggleLighter"
                >
                  <span class="material-symbols-outlined" style="font-size:13px">{{ lighterEnabled ? 'pause' : 'play_arrow' }}</span>
                  {{ lighterEnabled ? 'Disable' : 'Enable' }}
                </button>
              </div>
              <div class="venue-block-stats">
                <div class="venue-mini-stat">
                  <span class="meta-label">Positions</span>
                  <span class="meta-value">{{ positionsByVenue.lighter.length }}</span>
                </div>
                <div class="venue-mini-stat">
                  <span class="meta-label">Proxy</span>
                  <span class="meta-value" :class="venueHealth.lighter.status === 'connected' ? 'val-ok' : 'val-down'">
                    {{ venueHealth.lighter.status === 'connected' ? 'Online' : venueHealth.lighter.status }}
                  </span>
                </div>
                <div class="venue-mini-stat">
                  <span class="meta-label">Trading</span>
                  <span class="meta-value" :class="lighterEnabled ? 'val-ok' : 'val-down'">
                    {{ lighterEnabled ? 'Enabled' : 'Disabled' }}
                  </span>
                </div>
              </div>
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
  gap: 1rem;
}
@media (min-width: 1024px) {
  .dash-grid {
    grid-template-columns: 1.65fr 1fr;
  }
}
.left-col, .right-col {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}

/* ===== Card Terminal Style ===== */
.card-terminal {
  position: relative;
}
.card-terminal::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--tp-primary), transparent);
  opacity: 0.3;
}

.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--tp-border);
}
.card-title-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.card-title-group h3 {
  font-size: 0.85rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.card-icon {
  font-size: 18px;
  color: var(--tp-primary);
  opacity: 0.8;
}

/* ===== System Status Bar ===== */
.system-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.65rem 1rem;
  margin-bottom: 1rem;
  border-radius: var(--tp-radius);
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
  border: var(--tp-glass-border);
  box-shadow: var(--tp-glass-shadow);
  position: relative;
  overflow: hidden;
}
.system-bar::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--tp-primary), transparent);
  opacity: 0.2;
}
.system-bar-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-shrink: 0;
}
.system-bar-right {
  display: flex;
  align-items: center;
  gap: 0;
  flex: 1;
  justify-content: flex-end;
  min-width: 0;
}
.system-bar-divider {
  width: 1px;
  height: 28px;
  background: var(--tp-border);
  flex-shrink: 0;
}

/* Bot Indicator */
.bot-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.5rem 0.25rem 0.35rem;
  border-radius: var(--tp-radius-sm);
  border: 1px solid transparent;
  transition: all 0.2s ease;
}
.bot-live {
  border-color: rgba(34, 197, 94, 0.2);
  background: rgba(34, 197, 94, 0.04);
}
.bot-paused {
  border-color: rgba(245, 158, 11, 0.2);
  background: rgba(245, 158, 11, 0.04);
}
.bot-pulse-icon {
  font-size: 20px;
}
.bot-live .bot-pulse-icon {
  color: var(--tp-success);
  animation: icon-pulse 2s ease-in-out infinite;
}
.bot-paused .bot-pulse-icon {
  color: var(--tp-warning);
}
@keyframes icon-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.bot-indicator-text {
  display: flex;
  flex-direction: column;
  gap: 0;
  line-height: 1;
}
.bot-indicator-label {
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--tp-text-dim);
  text-transform: uppercase;
}
.bot-indicator-status {
  font-size: 0.8rem;
  font-weight: 800;
  color: var(--tp-text);
  margin-top: 1px;
}
.bot-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-family: var(--tp-font);
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  border: 1px solid var(--tp-border);
  cursor: pointer;
  transition: all 0.15s ease;
  background: transparent;
  color: var(--tp-text-muted);
}
.btn-resume:hover {
  background: rgba(34, 197, 94, 0.1);
  border-color: var(--tp-success);
  color: var(--tp-success);
}
.btn-pause:hover {
  background: rgba(245, 158, 11, 0.1);
  border-color: var(--tp-warning);
  color: var(--tp-warning);
}

/* Venue Health Chips */
.venue-health-group {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.venue-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 700;
  border: 1px solid transparent;
  transition: all 0.2s ease;
}
.venue-chip-icon {
  font-size: 13px;
}
.venue-chip-name {
  letter-spacing: 0.02em;
}
.venue-chip-latency {
  font-size: 0.55rem;
  opacity: 0.7;
  font-family: var(--tp-font-mono);
}
.venue-ok {
  color: var(--tp-success);
  background: rgba(34, 197, 94, 0.06);
  border-color: rgba(34, 197, 94, 0.15);
}
.venue-warn {
  color: var(--tp-warning);
  background: rgba(245, 158, 11, 0.06);
  border-color: rgba(245, 158, 11, 0.15);
}
.venue-down {
  color: var(--tp-danger);
  background: rgba(239, 68, 68, 0.06);
  border-color: rgba(239, 68, 68, 0.15);
}
.venue-unknown {
  color: var(--tp-text-dim);
  background: rgba(100, 116, 139, 0.06);
  border-color: rgba(100, 116, 139, 0.15);
}
.venue-standby {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
  border-color: rgba(245, 158, 11, 0.2);
}
.venue-chip-state {
  font-size: 0.5rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  opacity: 0.85;
}

/* System Stats */
.sys-stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 0.35rem 1rem;
  border-left: 1px solid var(--tp-border);
  min-width: 0;
}
.sys-stat:first-child {
  border-left: none;
}
.sys-stat-label {
  font-size: 0.5rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--tp-text-dim);
  text-transform: uppercase;
  white-space: nowrap;
}
.sys-stat-value {
  font-size: 1.1rem;
  font-weight: 800;
  color: var(--tp-text);
  font-feature-settings: 'tnum' 1;
  white-space: nowrap;
  line-height: 1.1;
}

/* ===== Prices Card ===== */
.prices-card {
  overflow: hidden;
}
.prices-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 1px;
  background: var(--tp-border);
}
.price-tile {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.65rem 0.6rem;
  background: var(--tp-bg-glass);
  transition: background 0.15s ease;
}
.price-tile:hover {
  background: var(--tp-bg-hover);
}
.price-tile-head {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.coin-badge {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.5rem;
  font-weight: 800;
  letter-spacing: 0.03em;
  flex-shrink: 0;
  border: 1px solid transparent;
}
.price-ticker {
  font-weight: 700;
  font-size: 0.7rem;
  color: var(--tp-text-muted);
  line-height: 1;
}
.price-amount {
  font-size: 0.8rem;
  font-weight: 800;
  font-feature-settings: 'tnum' 1;
  font-family: var(--tp-font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--tp-text);
}

/* ===== Funding Card ===== */
.funding-card {
  overflow: hidden;
}
.funding-legend {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.6rem;
  color: var(--tp-text-dim);
  font-weight: 600;
}
.funding-legend-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.funding-grid {
  padding: 0.75rem 1.25rem 1rem;
}
.funding-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.5rem 0;
}
.funding-row + .funding-row {
  border-top: 1px solid var(--tp-border);
}
.funding-symbol {
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--tp-text);
  width: 2.5rem;
  flex-shrink: 0;
}
.funding-bars {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.funding-bar-pair {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.funding-bar-track {
  flex: 1;
  height: 4px;
  background: var(--tp-border);
  border-radius: 2px;
  overflow: hidden;
}
.funding-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s ease;
}
.funding-bar-hl {
  background: #3b82f6;
}
.funding-bar-lt {
  background: #a855f7;
}
.funding-bar-fill.funding-negative {
  opacity: 0.6;
}
.funding-rate-val {
  font-size: 0.65rem;
  font-weight: 700;
  font-family: var(--tp-font-mono);
  width: 4rem;
  text-align: right;
  flex-shrink: 0;
}

/* ===== Positions Card ===== */
.positions-card {
  overflow: hidden;
}
.positions-header {
  padding: 0.75rem 1.25rem;
}
.positions-header h3 {
  font-size: 0.85rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.positions-header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

/* Venue Tabs */
.venue-tab-group {
  display: flex;
  gap: 0;
  border: 1px solid var(--tp-border);
  border-radius: 4px;
  overflow: hidden;
}
.venue-tab {
  font-family: var(--tp-font);
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  padding: 0.25rem 0.5rem;
  border: none;
  background: transparent;
  color: var(--tp-text-dim);
  cursor: pointer;
  transition: all 0.15s ease;
  border-right: 1px solid var(--tp-border);
}
.venue-tab:last-child {
  border-right: none;
}
.venue-tab:hover {
  background: var(--tp-bg-hover);
  color: var(--tp-text);
}
.venue-tab.active {
  background: var(--tp-primary);
  color: white;
}

.view-history-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: none;
  border: 1px solid var(--tp-border);
  border-radius: 4px;
  color: var(--tp-text-dim);
  font-size: 0.65rem;
  font-weight: 700;
  cursor: pointer;
  font-family: var(--tp-font);
  padding: 0.25rem 0.5rem;
  transition: all 0.15s ease;
}
.view-history-btn:hover {
  color: var(--tp-primary);
  border-color: var(--tp-primary);
}

.positions-body {
  padding: 0;
}

/* Terminal Table Overrides */
.terminal-table {
  font-size: 0.78rem;
}
.terminal-table thead tr {
  background: var(--tp-bg-surface);
}
.terminal-table th {
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--tp-text-dim);
  font-weight: 700;
  padding: 0.5rem 0.6rem;
  white-space: nowrap;
}
.terminal-table td {
  padding: 0.5rem 0.6rem;
  border-bottom: 1px solid var(--tp-border);
}
.terminal-table tbody tr:hover {
  background: var(--tp-bg-hover);
}

.cell-asset {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.asset-name {
  font-weight: 700;
  font-size: 0.8rem;
}
.mono-cell {
  font-family: var(--tp-font-mono);
  font-weight: 600;
  font-size: 0.75rem;
}
.pnl-cell {
  font-weight: 700;
  font-family: var(--tp-font-mono);
  font-size: 0.78rem;
}

.coin-icon-sm {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.5rem;
  font-weight: 800;
  flex-shrink: 0;
}

/* Venue label in positions table */
.venue-label {
  font-size: 0.55rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  text-transform: uppercase;
}
.venue-hl {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}
.venue-lighter {
  background: rgba(168, 85, 247, 0.1);
  color: #a855f7;
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
  font-size: 0.9rem;
  color: var(--tp-text) !important;
  margin-bottom: 0.2rem;
}
.empty-desc {
  font-size: 0.78rem;
  color: var(--tp-text-dim) !important;
}

/* ===== P&L Card ===== */
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
  font-size: 0.85rem;
  font-weight: 700;
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.pnl-subtitle {
  font-size: 0.65rem;
  color: var(--tp-text-dim);
  margin: 0.15rem 0 0;
  font-weight: 600;
}
.pnl-total {
  font-size: 1.4rem;
  font-weight: 800;
  font-family: var(--tp-font-mono);
  line-height: 1;
}

.equity-chart {
  width: 100%;
  height: 5rem;
  margin-bottom: 0.75rem;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  overflow: hidden;
  border: 1px solid var(--tp-border);
}
.equity-svg {
  width: 100%;
  height: 100%;
}
.equity-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.3rem;
  padding: 1.25rem;
  color: var(--tp-text-dim);
  font-size: 0.75rem;
  text-align: center;
}

.trade-bars {
  display: flex;
  align-items: flex-end;
  gap: 1px;
  height: 2rem;
  margin-bottom: 0.75rem;
  padding: 0 1px;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  border: 1px solid var(--tp-border);
  overflow: hidden;
}
.trade-bar {
  flex: 1;
  min-height: 2px;
  transition: opacity 0.15s;
  cursor: default;
}
.trade-bar:hover { opacity: 0.7; }
.bar-win { background: #22c55e; }
.bar-loss { background: #ef4444; }

.pnl-stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  margin-bottom: 0.75rem;
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  overflow: hidden;
}
.pnl-stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0.6rem;
  font-size: 0.72rem;
  border-bottom: 1px solid var(--tp-border);
  border-right: 1px solid var(--tp-border);
}
.pnl-stat:nth-child(even) {
  border-right: none;
}
.pnl-stat:nth-last-child(-n+2) {
  border-bottom: none;
}
.pnl-stat-label {
  color: var(--tp-text-dim);
  font-weight: 600;
}
.pnl-stat-value {
  font-weight: 700;
  font-family: var(--tp-font-mono);
  font-size: 0.72rem;
}

.pnl-history-btn {
  width: 100%;
  justify-content: center;
  font-size: 0.75rem;
}

/* ===== Margin Card ===== */
.margin-card {
  overflow: hidden;
}
.margin-body {
  padding: 0.75rem 1.25rem 1rem;
}
.margin-level-badge {
  font-size: 0.55rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  padding: 0.15rem 0.45rem;
  border-radius: 3px;
  text-transform: uppercase;
}
.badge-safe {
  background: rgba(34, 197, 94, 0.1);
  color: var(--tp-success);
}
.badge-warning {
  background: rgba(245, 158, 11, 0.1);
  color: var(--tp-warning);
}
.badge-danger {
  background: rgba(239, 68, 68, 0.1);
  color: var(--tp-danger);
}
.margin-bar-wrap {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
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
  font-size: 0.7rem;
  font-weight: 700;
  font-family: var(--tp-font-mono);
  color: var(--tp-text-dim);
  min-width: 2.5rem;
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
  font-size: 0.72rem;
  color: var(--tp-text-dim);
  font-weight: 600;
}
.meta-value {
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--tp-text);
  font-family: var(--tp-font-mono);
}

/* ===== Allocation Card ===== */
.alloc-card {
  overflow: hidden;
}
.alloc-body {
  padding: 0.75rem 1.25rem 1rem;
}
.alloc-bar {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  gap: 1px;
  margin-bottom: 0.6rem;
}
.alloc-segment {
  min-width: 3px;
  border-radius: 2px;
  transition: width 0.5s ease;
}
.alloc-legend {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.alloc-legend-item {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.72rem;
}
.alloc-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.alloc-coin {
  font-weight: 700;
  color: var(--tp-text);
  min-width: 2.5rem;
}
.alloc-side {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  min-width: 2.5rem;
}
.alloc-pct {
  color: var(--tp-text-dim);
  font-weight: 600;
  font-family: var(--tp-font-mono);
  min-width: 2.5rem;
  text-align: right;
}
.alloc-val {
  color: var(--tp-text-dim);
  font-size: 0.65rem;
  font-family: var(--tp-font-mono);
  margin-left: auto;
}

/* ===== Wallet & Venues Card ===== */
.wallet-card {
  overflow: hidden;
}
.wallet-body {
  padding: 0.75rem 1.25rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.venue-block {
  padding: 0.65rem 0.75rem;
  border-radius: var(--tp-radius-sm);
  background: var(--tp-bg-surface);
  border: 1px solid var(--tp-border);
}
.venue-block-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.4rem;
}
.venue-block-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.venue-block-dot.venue-ok {
  background: var(--tp-success);
  box-shadow: 0 0 6px var(--tp-success);
}
.venue-block-dot.venue-warn {
  background: var(--tp-warning);
  box-shadow: 0 0 6px var(--tp-warning);
}
.venue-block-dot.venue-down {
  background: var(--tp-danger);
  box-shadow: 0 0 6px var(--tp-danger);
}
.venue-block-dot.venue-unknown {
  background: var(--tp-text-dim);
}
.venue-block-name {
  font-weight: 700;
  font-size: 0.8rem;
  color: var(--tp-text);
}
.venue-block-chain {
  font-size: 0.55rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--tp-text-dim);
  background: var(--tp-bg-glass);
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  margin-left: auto;
}
.wallet-address-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.5rem;
  background: var(--tp-bg-glass);
  border-radius: 3px;
  margin-bottom: 0.35rem;
}
.wallet-addr {
  font-family: var(--tp-font-mono);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--tp-text-muted);
}
.venue-block-stats {
  display: flex;
  gap: 1rem;
}
.venue-mini-stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.venue-mini-stat .meta-label {
  font-size: 0.6rem;
}
.venue-mini-stat .meta-value {
  font-size: 0.72rem;
}

/* Lighter Proxy Toggle (system bar) */
.venue-toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 3px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s ease;
  background: transparent;
  padding: 0;
  margin-left: 0.15rem;
}
.vt-on {
  color: var(--tp-success);
  border-color: rgba(34, 197, 94, 0.2);
}
.vt-on:hover {
  background: rgba(245, 158, 11, 0.15);
  color: var(--tp-warning);
  border-color: var(--tp-warning);
}
.vt-off {
  color: var(--tp-danger);
  border-color: rgba(239, 68, 68, 0.2);
}
.vt-off:hover {
  background: rgba(34, 197, 94, 0.15);
  color: var(--tp-success);
  border-color: var(--tp-success);
}
.venue-disabled {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
  border-color: rgba(245, 158, 11, 0.2);
  opacity: 1;
}
.venue-disabled .venue-chip-icon {
  color: #f59e0b;
}

/* Lighter Proxy Toggle (venue block) */
.venue-block-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  font-size: 0.6rem;
  font-weight: 700;
  padding: 0.15rem 0.4rem;
  border-radius: 3px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s ease;
  background: transparent;
  margin-left: auto;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.vbt-on {
  color: var(--tp-success);
  border-color: rgba(34, 197, 94, 0.2);
}
.vbt-on:hover {
  background: rgba(245, 158, 11, 0.12);
  color: var(--tp-warning);
  border-color: var(--tp-warning);
}
.vbt-off {
  color: var(--tp-danger);
  border-color: rgba(239, 68, 68, 0.2);
}
.vbt-off:hover {
  background: rgba(34, 197, 94, 0.12);
  color: var(--tp-success);
  border-color: var(--tp-success);
}

/* Value status colors */
.val-ok { color: var(--tp-success); }
.val-down { color: var(--tp-danger); }

/* ===== WS Badge ===== */
.ws-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  font-size: 0.55rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 0.15rem 0.4rem;
  border-radius: 3px;
  background: rgba(34, 197, 94, 0.1);
  color: var(--tp-success);
  border: 1px solid rgba(34, 197, 94, 0.2);
}

/* ===== News Card ===== */
.news-card {
  overflow: hidden;
}
.news-body {
  padding: 0;
  max-height: 24rem;
  overflow-y: auto;
}
.news-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.6rem 1.25rem;
  border-bottom: 1px solid var(--tp-border);
  text-decoration: none;
  color: inherit;
  position: relative;
  transition: background 0.15s ease;
  cursor: pointer;
}
.news-item:hover {
  background: var(--tp-bg-hover);
}
.news-item:last-child {
  border-bottom: none;
}
.news-item-top {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.news-source-badge {
  font-size: 0.55rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
  flex-shrink: 0;
}
.news-time {
  font-size: 0.6rem;
  color: var(--tp-text-dim);
  font-weight: 600;
}
.news-headline {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--tp-text);
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  padding-right: 1.5rem;
}
.news-link-icon {
  position: absolute;
  right: 1rem;
  top: 50%;
  transform: translateY(-50%);
  font-size: 14px;
  color: var(--tp-text-dim);
  opacity: 0;
  transition: opacity 0.15s ease;
}
.news-item:hover .news-link-icon {
  opacity: 1;
  color: var(--tp-primary);
}
.news-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.3rem;
  padding: 2rem;
  color: var(--tp-text-dim);
  font-size: 0.75rem;
  text-align: center;
}
.tp-badge-dim {
  background: rgba(100, 116, 139, 0.1);
  color: var(--tp-text-dim);
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-weight: 700;
}

/* ===== Utility Classes ===== */
.text-success { color: var(--tp-success) !important; }
.text-danger { color: var(--tp-danger) !important; }

/* Error banner */
.wallet-error-banner {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 1rem;
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.15);
  border-radius: var(--tp-radius-sm);
  color: var(--tp-danger);
  font-size: 0.8rem;
  margin-top: 1rem;
  font-weight: 600;
}

/* ===== Responsive ===== */
@media (max-width: 768px) {
  .system-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .system-bar-left {
    flex-wrap: wrap;
  }
  .system-bar-right {
    flex-wrap: wrap;
    justify-content: flex-start;
  }
  .system-bar-divider {
    display: none;
  }
  .sys-stat {
    border-left: none;
    border-top: 1px solid var(--tp-border);
    padding: 0.35rem 0.5rem;
  }
  .sys-stat:first-child {
    border-top: none;
  }
  .prices-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  .positions-header-right {
    flex-wrap: wrap;
    gap: 0.4rem;
  }
}
@media (max-width: 480px) {
  .prices-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .venue-health-group {
    flex-wrap: wrap;
  }
}
</style>
