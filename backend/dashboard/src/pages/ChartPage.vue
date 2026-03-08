<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries, CrosshairMode } from 'lightweight-charts'
import { useToast } from '@/composables/useToast'
import { useTheme, getChartThemeColors } from '@/composables/useTheme'
import SymbolSelect from '@/components/SymbolSelect.vue'
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
]

const toast = useToast()
const { theme } = useTheme()

const symbol = ref('EURUSD')
const timeframe = ref('H1')
const numBars = ref(200)
const chartEl = ref(null)

// Plain variables - NOT reactive (Vue Proxy breaks chart internals)
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
    height: 500,
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
    scaleMargins: { top: 0.8, bottom: 0 },
  })

  resizeObserver = new ResizeObserver(() => {
    chart.applyOptions({ width: chartEl.value.clientWidth })
  })
  resizeObserver.observe(chartEl.value)
}

async function loadChart() {
  if (!symbol.value || !chart) return

  try {
    const data = await api.fetchDataPos(symbol.value, timeframe.value, numBars.value)

    const candles = data.map((d) => ({
      time: Math.floor(new Date(d.time).getTime() / 1000),
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }))

    const c = getChartThemeColors()
    const volumes = data.map((d) => ({
      time: Math.floor(new Date(d.time).getTime() / 1000),
      value: d.tick_volume || d.real_volume || 0,
      color: d.close >= d.open ? c.up + '80' : c.down + '80',
    }))

    candleSeries.setData(candles)
    volumeSeries.setData(volumes)
    chart.timeScale().fitContent()
  } catch (err) {
    toast.error(`Chart error: ${err.message}`)
  }
}

watch(theme, () => {
  setTimeout(applyThemeToChart, 50)
})

onMounted(() => {
  initChart()
  loadChart()
})

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) chart.remove()
})
</script>

<template>
  <div class="tp-page">
    <SectionNav :links="forexLinks" />
    
    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 2rem;">
      <div>
        <h1 style="font-size: 2.25rem; font-weight: 900; letter-spacing: -0.02em;">Live Charts</h1>
        <p style="color: var(--tp-text-muted); margin-top: 0.25rem;">Market Analysis</p>
      </div>
    </div>

    <div class="tp-card" style="margin-bottom: 1.5rem; padding: 1.5rem;">
      <form style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end;" @submit.prevent="loadChart">
        <div style="flex: 1; min-width: 150px;">
          <label class="tp-label">Symbol</label>
          <SymbolSelect v-model="symbol" class="tp-select" />
        </div>
        <div style="flex: 1; min-width: 120px;">
          <label class="tp-label">Timeframe</label>
          <select v-model="timeframe" class="tp-select">
            <option value="M1">M1</option>
            <option value="M5">M5</option>
            <option value="M15">M15</option>
            <option value="M30">M30</option>
            <option value="H1">H1</option>
            <option value="H4">H4</option>
            <option value="D1">D1</option>
            <option value="W1">W1</option>
          </select>
        </div>
        <div style="flex: 1; min-width: 120px;">
          <label class="tp-label">Bars</label>
          <input v-model.number="numBars" type="number" min="10" max="1000" class="tp-input">
        </div>
        <div style="flex: 0 0 auto;">
          <button type="submit" class="tp-btn tp-btn-primary" style="height: 2.75rem;">
            <span class="material-symbols-outlined" style="font-size:18px">show_chart</span>
            Load Chart
          </button>
        </div>
      </form>
    </div>

    <div class="tp-card" style="padding: 0; overflow: hidden; border-radius: var(--tp-radius);">
      <div ref="chartEl" style="width: 100%; height: 500px;"></div>
    </div>
  </div>
</template>
