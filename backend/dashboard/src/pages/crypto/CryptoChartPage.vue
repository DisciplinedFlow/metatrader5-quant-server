<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, CrosshairMode } from 'lightweight-charts'
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
  { label: 'Bitcoin', value: 'BTC-USD' },
  { label: 'Ethereum', value: 'ETH-USD' },
  { label: 'Solana', value: 'SOL-USD' },
  { label: 'Avalanche', value: 'AVAX-USD' },
  { label: 'Dogecoin', value: 'DOGE-USD' },
  { label: 'Arbitrum', value: 'ARB-USD' },
  { label: 'Chainlink', value: 'LINK-USD' },
  { label: 'Optimism', value: 'OP-USD' },
  { label: 'Sui', value: 'SUI-USD' },
  { label: 'Polygon', value: 'MATIC-USD' },
]

const symbol = ref('BTC-USD')
const interval = ref('15m')
const period = ref('30d')
const loading = ref(false)
const chartEl = ref(null)

let chart = null
let candleSeries = null
let volumeSeries = null
let resizeObserver = null

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
  if (volumeSeries) {
    volumeSeries.applyOptions({ color: c.volume })
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

    // Deduplicate and sort by time
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
    chart.timeScale().fitContent()
  } catch (err) {
    toast.error(`Chart error: ${err.message}`)
  }
  loading.value = false
}

function getDisplayName(val) {
  const found = CRYPTO_SYMBOLS.find(s => s.value === val)
  return found ? found.label : val
}

watch(theme, () => setTimeout(applyThemeToChart, 50))
onMounted(() => { initChart(); loadChart() })
onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) chart.remove()
})
</script>

<template>
  <SectionNav :links="cryptoLinks" />
  <div class="tp-page chart-page">
    <!-- Controls Strip -->
    <div class="controls-strip">
      <div class="ctrl-field">
        <label class="tp-label">Symbol</label>
        <select v-model="symbol" class="tp-select">
          <option v-for="s in CRYPTO_SYMBOLS" :key="s.value" :value="s.value">
            {{ s.label }} ({{ s.value }})
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

    <!-- Chart Info Bar -->
    <div class="chart-info-bar">
      <div class="chart-symbol-name">
        <span class="material-symbols-outlined" style="font-size:20px;color:var(--tp-primary)">currency_bitcoin</span>
        {{ getDisplayName(symbol) }}
        <span class="chart-pair">{{ symbol }}</span>
      </div>
    </div>

    <!-- Chart -->
    <div class="tp-card chart-card">
      <div ref="chartEl" class="chart-container"></div>
    </div>
  </div>
</template>

<style scoped>
.chart-page {
  padding: 1rem 1.5rem 2rem;
}

/* Controls Strip */
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
.ctrl-field:nth-child(1) { flex: 1.5; min-width: 160px; }
.ctrl-field:nth-child(2) { flex: 1; min-width: 100px; }
.ctrl-field:nth-child(3) { flex: 1; min-width: 100px; }
.ctrl-action { flex: 0 0 auto; }
.controls-strip :deep(.tp-input),
.controls-strip :deep(.tp-select) {
  height: 2.25rem;
  font-size: 0.85rem;
}
.controls-strip .tp-btn {
  height: 2.25rem;
  font-size: 0.8rem;
}

/* Chart Info Bar */
.chart-info-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}
.chart-symbol-name {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.1rem;
  font-weight: 800;
  letter-spacing: -0.01em;
}
.chart-pair {
  font-size: 0.75rem;
  color: var(--tp-text-dim);
  font-weight: 500;
}

/* Chart */
.chart-card {
  padding: 0;
  overflow: hidden;
}
.chart-container {
  width: 100%;
  height: 520px;
}

@media (max-width: 768px) {
  .controls-strip { gap: 0.5rem; padding: 0.5rem; }
  .chart-container { height: 400px; }
}
</style>
