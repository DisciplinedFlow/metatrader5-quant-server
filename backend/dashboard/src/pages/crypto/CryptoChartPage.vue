<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries, CrosshairMode, createSeriesMarkers } from 'lightweight-charts'
import { useTheme, getChartThemeColors } from '@/composables/useTheme'
import { useToast } from '@/composables/useToast'
import SectionNav from '@/components/SectionNav.vue'
import api from '@/services/api'

const cryptoLinks = [
  { to: '/crypto', label: 'Overview' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/history', label: 'History' },
  { to: '/crypto/chart', label: 'Chart' },
  { to: '/crypto/logs', label: 'Logs' },
  { to: '/crypto/strategy', label: 'Strategies' },
]

const toast = useToast()
const { theme } = useTheme()

const CRYPTO_SYMBOLS = [
  { label: 'Gold', value: 'GC=F', dbSymbol: 'XAU', icon: 'diamond', color: '#d4af37' },
  { label: 'Bitcoin', value: 'BTC-USD', dbSymbol: 'BTC', icon: 'currency_bitcoin', color: '#f7931a' },
  { label: 'Ethereum', value: 'ETH-USD', dbSymbol: 'ETH', icon: 'token', color: '#627eea' },
  { label: 'Solana', value: 'SOL-USD', dbSymbol: 'SOL', icon: 'bolt', color: '#9945ff' },
  { label: 'Avalanche', value: 'AVAX-USD', dbSymbol: 'AVAX', icon: 'landscape', color: '#e84142' },
  { label: 'Dogecoin', value: 'DOGE-USD', dbSymbol: 'DOGE', icon: 'pets', color: '#c2a633' },
  { label: 'Chainlink', value: 'LINK-USD', dbSymbol: 'LINK', icon: 'link', color: '#2a5ada' },
  { label: 'Sui', value: 'SUI-USD', dbSymbol: 'SUI', icon: 'water_drop', color: '#4da2ff' },
  { label: 'Arbitrum', value: 'ARB-USD', dbSymbol: 'ARB', icon: 'hub', color: '#28a0f0' },
]

const symbol = ref('GC=F')
const interval = ref('15m')
const period = ref('30d')
const loading = ref(false)
const chartEl = ref(null)
const allTrades = ref([])

let chart = null
let candleSeries = null
let volumeSeries = null
let seriesMarkers = null
let resizeObserver = null

// ── Computed: trades for the selected symbol ──
const currentDbSymbol = computed(() => {
  const found = CRYPTO_SYMBOLS.find(s => s.value === symbol.value)
  return found ? found.dbSymbol : ''
})

const currentMeta = computed(() => CRYPTO_SYMBOLS.find(s => s.value === symbol.value) || {})

const symbolTrades = computed(() => {
  return allTrades.value
    .filter(t => t.symbol === currentDbSymbol.value)
    .sort((a, b) => new Date(b.closed_at || b.opened_at) - new Date(a.closed_at || a.opened_at))
})

const symbolStats = computed(() => {
  const trades = symbolTrades.value
  if (!trades.length) return null
  const wins = trades.filter(t => Number(t.pnl_usd || 0) > 0)
  const pnl = trades.reduce((s, t) => s + Number(t.pnl_usd || 0), 0)
  return {
    total: trades.length,
    wins: wins.length,
    losses: trades.length - wins.length,
    winRate: (wins.length / trades.length * 100),
    pnl,
  }
})

// ── Chart functions ──
function applyThemeToChart() {
  if (!chart) return
  const c = getChartThemeColors()
  chart.applyOptions({
    layout: { background: { color: c.bg }, textColor: c.text },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
  })
  if (candleSeries) {
    candleSeries.applyOptions({
      upColor: c.up, downColor: c.down,
      borderUpColor: c.up, borderDownColor: c.down,
      wickUpColor: c.up, wickDownColor: c.down,
    })
  }
}

function initChart() {
  if (!chartEl.value) return
  const c = getChartThemeColors()

  chart = createChart(chartEl.value, {
    width: chartEl.value.clientWidth,
    height: 520,
    layout: { background: { color: c.bg }, textColor: c.text },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
    crosshair: { mode: CrosshairMode.Normal },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: c.up, downColor: c.down,
    borderUpColor: c.up, borderDownColor: c.down,
    wickUpColor: c.up, wickDownColor: c.down,
  })

  volumeSeries = chart.addSeries(HistogramSeries, {
    color: c.volume,
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  })
  chart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.85, bottom: 0 },
  })

  resizeObserver = new ResizeObserver(() => {
    if (chartEl.value) chart.applyOptions({ width: chartEl.value.clientWidth })
  })
  resizeObserver.observe(chartEl.value)
}

function addTradeMarkers() {
  if (!candleSeries || !symbolTrades.value.length) {
    if (seriesMarkers) { seriesMarkers.detach(); seriesMarkers = null }
    return
  }

  const markers = []

  for (const t of symbolTrades.value) {
    // Entry marker
    if (t.opened_at) {
      const ts = Math.floor(new Date(t.opened_at).getTime() / 1000)
      markers.push({
        time: ts,
        position: t.side === 'LONG' ? 'belowBar' : 'aboveBar',
        color: t.side === 'LONG' ? '#22c55e' : '#ef4444',
        shape: t.side === 'LONG' ? 'arrowUp' : 'arrowDown',
        text: `${t.side === 'LONG' ? 'BUY' : 'SELL'} $${Number(t.entry_price).toFixed(2)}`,
      })
    }

    // Exit marker
    if (t.closed_at && t.close_price) {
      const ts = Math.floor(new Date(t.closed_at).getTime() / 1000)
      const won = Number(t.pnl_usd || 0) > 0
      markers.push({
        time: ts,
        position: t.side === 'LONG' ? 'aboveBar' : 'belowBar',
        color: won ? '#22c55e' : '#ef4444',
        shape: 'circle',
        text: `EXIT ${won ? '+' : ''}$${Number(t.pnl_usd || 0).toFixed(2)}`,
      })
    }
  }

  markers.sort((a, b) => a.time - b.time)

  if (seriesMarkers) { seriesMarkers.detach(); seriesMarkers = null }
  if (markers.length) {
    seriesMarkers = createSeriesMarkers(candleSeries, markers)
  }
}

async function loadChart() {
  if (!symbol.value || !chart) return
  loading.value = true

  try {
    const data = await api.fetchYahooData(symbol.value, period.value, interval.value)

    if (!data || !data.length) {
      toast.error('No data returned for ' + symbol.value)
      loading.value = false
      return
    }

    const c = getChartThemeColors()

    const candles = data.map(d => ({
      time: Math.floor(new Date(d.time || d.Date || d.datetime).getTime() / 1000),
      open: d.open || d.Open,
      high: d.high || d.High,
      low: d.low || d.Low,
      close: d.close || d.Close,
    })).filter(d => d.time && d.open && d.close)

    const volumes = data.map(d => ({
      time: Math.floor(new Date(d.time || d.Date || d.datetime).getTime() / 1000),
      value: d.volume || d.Volume || 0,
      color: (d.close || d.Close) >= (d.open || d.Open) ? c.up + '80' : c.down + '80',
    })).filter(d => d.time)

    // Deduplicate and sort
    const seen = new Set()
    const uniqueCandles = candles.filter(c => {
      if (seen.has(c.time)) return false
      seen.add(c.time)
      return true
    }).sort((a, b) => a.time - b.time)

    const seenV = new Set()
    const uniqueVolumes = volumes.filter(v => {
      if (seenV.has(v.time)) return false
      seenV.add(v.time)
      return true
    }).sort((a, b) => a.time - b.time)

    candleSeries.setData(uniqueCandles)
    volumeSeries.setData(uniqueVolumes)

    // Add trade markers after chart data is set
    addTradeMarkers()

    chart.timeScale().fitContent()
  } catch (err) {
    toast.error(`Chart error: ${err.message}`)
  }
  loading.value = false
}

async function fetchTrades() {
  try {
    const resp = await api.getCryptoPositions()
    allTrades.value = resp.results || resp || []
  } catch (err) {
    console.error('Failed to fetch trades:', err)
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

function fmtTime(val) {
  if (!val) return '-'
  const d = new Date(val)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) + ' ' +
    d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function duration(opened, closed) {
  if (!opened || !closed) return '-'
  const mins = Math.round((new Date(closed) - new Date(opened)) / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  return `${hrs}h ${mins % 60}m`
}

watch(theme, () => setTimeout(applyThemeToChart, 50))
onMounted(async () => {
  initChart()
  await fetchTrades()
  loadChart()
})
onBeforeUnmount(() => {
  if (seriesMarkers) seriesMarkers.detach()
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) chart.remove()
})
</script>

<template>
  <SectionNav :links="cryptoLinks" />
  <div class="tp-page chart-page">

    <!-- Controls Strip -->
    <div class="controls-strip">
      <div class="ctrl-field sym-field">
        <label class="tp-label">Symbol</label>
        <select v-model="symbol" class="tp-select" @change="loadChart">
          <option v-for="s in CRYPTO_SYMBOLS" :key="s.value" :value="s.value">
            {{ s.label }} ({{ s.dbSymbol }})
          </option>
        </select>
      </div>
      <div class="ctrl-field">
        <label class="tp-label">Interval</label>
        <select v-model="interval" class="tp-select">
          <option value="1m">1 min</option>
          <option value="5m">5 min</option>
          <option value="15m">15 min</option>
          <option value="30m">30 min</option>
          <option value="1h">1 hour</option>
          <option value="1d">1 day</option>
        </select>
      </div>
      <div class="ctrl-field">
        <label class="tp-label">Period</label>
        <select v-model="period" class="tp-select">
          <option value="5d">5 days</option>
          <option value="15d">15 days</option>
          <option value="30d">30 days</option>
          <option value="60d">60 days</option>
          <option value="90d">90 days</option>
        </select>
      </div>
      <div class="ctrl-field ctrl-action">
        <button type="button" class="tp-btn tp-btn-primary" @click="loadChart" :disabled="loading">
          <span class="material-symbols-outlined" style="font-size:16px">{{ loading ? 'hourglass_empty' : 'show_chart' }}</span>
          {{ loading ? 'Loading...' : 'Load' }}
        </button>
      </div>
    </div>

    <!-- Chart Header -->
    <div class="chart-head">
      <div class="chart-symbol-row">
        <span class="material-symbols-outlined sym-icon" :style="{ color: currentMeta.color }">{{ currentMeta.icon }}</span>
        <span class="sym-name">{{ currentMeta.label }}</span>
        <span class="sym-pair">{{ currentDbSymbol }}</span>
      </div>
      <div v-if="symbolStats" class="chart-head-stats">
        <span class="hs">{{ symbolStats.total }} trades</span>
        <span class="hs-sep">&middot;</span>
        <span class="hs" :class="symbolStats.winRate >= 60 ? 'hs-green' : symbolStats.winRate >= 40 ? 'hs-amber' : 'hs-red'">
          {{ fmt(symbolStats.winRate, 1) }}% WR
        </span>
        <span class="hs-sep">&middot;</span>
        <span class="hs" :class="symbolStats.pnl >= 0 ? 'hs-green' : 'hs-red'">
          {{ symbolStats.pnl >= 0 ? '+' : '' }}${{ fmt(symbolStats.pnl) }}
        </span>
      </div>
    </div>

    <!-- Chart -->
    <div class="tp-card chart-card">
      <div ref="chartEl" class="chart-container"></div>
    </div>

    <!-- Trade History for Selected Pair -->
    <div v-if="symbolTrades.length" class="trades-section">
      <div class="trades-header">
        <h2 class="trades-title">
          {{ currentDbSymbol }} Trade History
        </h2>
        <span class="trades-count">{{ symbolTrades.length }} trades</span>
      </div>

      <div class="tp-card trades-card">
        <div class="trades-table-wrap">
          <table class="trades-table">
            <thead>
              <tr>
                <th>Side</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Size</th>
                <th>P&L</th>
                <th>Strategy</th>
                <th>Reason</th>
                <th>Duration</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in symbolTrades" :key="t.id" class="trade-row">
                <td>
                  <span class="side-tag" :class="t.side === 'LONG' ? 'tag-long' : 'tag-short'">
                    {{ t.side }}
                  </span>
                </td>
                <td class="td-mono">${{ fmtPrice(t.entry_price) }}</td>
                <td class="td-mono">{{ t.close_price ? '$' + fmtPrice(t.close_price) : '-' }}</td>
                <td class="td-mono">{{ fmt(t.size, 4) }}</td>
                <td>
                  <span class="td-pnl" :class="Number(t.pnl_usd || 0) >= 0 ? 'pnl-win' : 'pnl-loss'">
                    {{ Number(t.pnl_usd || 0) >= 0 ? '+' : '' }}${{ fmt(t.pnl_usd) }}
                  </span>
                </td>
                <td class="td-strat">{{ (t.entry_signal || '').replace('lighter:', '') }}</td>
                <td class="td-reason">{{ t.close_reason || '-' }}</td>
                <td class="td-mono">{{ duration(t.opened_at, t.closed_at) }}</td>
                <td class="td-time">{{ fmtTime(t.opened_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- No trades for this pair -->
    <div v-else class="no-trades">
      <span class="material-symbols-outlined" style="font-size:24px;opacity:0.3">inbox</span>
      <span>No trades recorded for {{ currentDbSymbol }}</span>
    </div>

  </div>
</template>

<style scoped>
.chart-page {
  padding: 1rem 1.5rem 2rem;
  max-width: 1200px;
  margin: 0 auto;
}

/* ── Controls ── */
.controls-strip {
  display: flex;
  align-items: flex-end;
  gap: 0.75rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
  border: var(--tp-glass-border);
  border-radius: var(--tp-radius);
  box-shadow: var(--tp-glass-shadow);
  padding: 0.75rem 1rem;
}
.ctrl-field {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.sym-field { flex: 1.5; min-width: 160px; }
.ctrl-field:nth-child(2) { flex: 1; min-width: 100px; }
.ctrl-field:nth-child(3) { flex: 1; min-width: 100px; }
.ctrl-action { flex: 0 0 auto; }
.controls-strip .tp-btn {
  height: 2.25rem;
  font-size: 0.8rem;
}

/* ── Chart Header ── */
.chart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}
.chart-symbol-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.sym-icon { font-size: 22px; }
.sym-name {
  font-size: 1.15rem;
  font-weight: 800;
  letter-spacing: -0.02em;
}
.sym-pair {
  font-size: 0.75rem;
  color: var(--tp-text-dim);
  font-weight: 500;
}
.chart-head-stats {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.78rem;
  font-weight: 600;
}
.hs { font-feature-settings: 'tnum' 1; }
.hs-sep { color: var(--tp-border-light); }
.hs-green { color: #22c55e; }
.hs-amber { color: #fbbf24; }
.hs-red { color: #ef4444; }

/* ── Chart ── */
.chart-card {
  padding: 0;
  overflow: hidden;
  margin-bottom: 1.5rem;
}
.chart-container {
  width: 100%;
  height: 520px;
}

/* ── Trade History Section ── */
.trades-section {
  animation: fadeSlideUp 0.3s ease;
}
@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.trades-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.6rem;
}
.trades-title {
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  margin: 0;
}
.trades-count {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--tp-text-dim);
  background: var(--tp-bg-surface);
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
}

.trades-card {
  padding: 0;
  overflow: hidden;
}
.trades-table-wrap {
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
}
.trades-table-wrap::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}
.trades-table-wrap::-webkit-scrollbar-thumb {
  background: var(--tp-border);
  border-radius: 3px;
}

.trades-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.78rem;
}
.trades-table th {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 700;
  color: var(--tp-text-dim);
  padding: 0.6rem 0.75rem;
  white-space: nowrap;
  position: sticky;
  top: 0;
  background: var(--tp-bg-glass, var(--tp-bg-card, #0f1729));
  z-index: 2;
  border-bottom: 1px solid var(--tp-border);
}
.trades-table td {
  padding: 0.55rem 0.75rem;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}
.trade-row:hover {
  background: var(--tp-bg-hover);
}

.td-mono {
  font-family: var(--tp-font-mono, monospace);
  font-size: 0.75rem;
  color: var(--tp-text-muted);
}
.td-pnl {
  font-weight: 700;
  font-family: var(--tp-font-mono, monospace);
  font-size: 0.78rem;
}
.pnl-win { color: #22c55e; }
.pnl-loss { color: #ef4444; }

.td-strat {
  font-size: 0.7rem;
  color: var(--tp-text-muted);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.td-reason {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
}
.td-time {
  font-size: 0.72rem;
  color: var(--tp-text-dim);
}

.side-tag {
  display: inline-block;
  padding: 0.1rem 0.45rem;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.tag-long {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
}
.tag-short {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

/* ── No trades ── */
.no-trades {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 2rem;
  color: var(--tp-text-dim);
  font-size: 0.85rem;
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .controls-strip { gap: 0.5rem; padding: 0.5rem; }
  .chart-container { height: 380px; }
  .chart-head { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
}
</style>
