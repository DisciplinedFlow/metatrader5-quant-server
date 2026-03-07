<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries, CrosshairMode } from 'lightweight-charts'
import { useToast } from '@/composables/useToast'
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

const symbol = ref('EURUSD')
const timeframe = ref('H1')
const numBars = ref(200)
const chartEl = ref(null)

// Plain variables - NOT reactive (Vue Proxy breaks chart internals)
let chart = null
let candleSeries = null
let volumeSeries = null
let resizeObserver = null

function initChart() {
  if (!chartEl.value) return

  chart = createChart(chartEl.value, {
    width: chartEl.value.clientWidth,
    height: 500,
    layout: {
      background: { color: '#1a1a2e' },
      textColor: '#e0e0e0',
    },
    grid: {
      vertLines: { color: '#2a2a4a' },
      horzLines: { color: '#2a2a4a' },
    },
    crosshair: { mode: CrosshairMode.Normal },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: '#26a69a',
    downColor: '#ef5350',
    borderDownColor: '#ef5350',
    borderUpColor: '#26a69a',
    wickDownColor: '#ef5350',
    wickUpColor: '#26a69a',
  })

  volumeSeries = chart.addSeries(HistogramSeries, {
    color: '#385263',
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

    const volumes = data.map((d) => ({
      time: Math.floor(new Date(d.time).getTime() / 1000),
      value: d.tick_volume || d.real_volume || 0,
      color: d.close >= d.open ? '#26a69a80' : '#ef535080',
    }))

    candleSeries.setData(candles)
    volumeSeries.setData(volumes)
    chart.timeScale().fitContent()
  } catch (err) {
    toast.error(`Chart error: ${err.message}`)
  }
}

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
  <SectionNav :links="forexLinks" />
  <h2>Chart</h2>
  <form class="grid" style="align-items:end;" @submit.prevent="loadChart">
    <label>
      Symbol
      <SymbolSelect v-model="symbol" />
    </label>
    <label>
      Timeframe
      <select v-model="timeframe">
        <option value="M1">M1</option>
        <option value="M5">M5</option>
        <option value="M15">M15</option>
        <option value="M30">M30</option>
        <option value="H1">H1</option>
        <option value="H4">H4</option>
        <option value="D1">D1</option>
        <option value="W1">W1</option>
      </select>
    </label>
    <label>
      Bars
      <input v-model.number="numBars" type="number" min="10" max="1000">
    </label>
    <button type="submit">Load</button>
  </form>
  <div ref="chartEl" class="chart-container"></div>
</template>
