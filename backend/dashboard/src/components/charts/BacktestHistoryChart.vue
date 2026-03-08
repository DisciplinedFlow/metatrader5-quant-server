<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { createChart, LineSeries, HistogramSeries, CrosshairMode } from 'lightweight-charts'
import { useTheme, getChartThemeColors } from '@/composables/useTheme'

const props = defineProps({
  results: { type: Array, default: () => [] },
})

const { theme } = useTheme()
const chartEl = ref(null)
let chart = null
let winRateSeries = null
let pnlSeries = null
let resizeObserver = null

function applyThemeToChart() {
  if (!chart) return
  const c = getChartThemeColors()
  chart.applyOptions({
    layout: { background: { color: c.bg }, textColor: c.text },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
  })
  if (winRateSeries) winRateSeries.applyOptions({ color: c.accent })
}

function initChart() {
  if (!chartEl.value) return
  const c = getChartThemeColors()
  chart = createChart(chartEl.value, {
    width: chartEl.value.clientWidth,
    height: 300,
    layout: { background: { color: c.bg }, textColor: c.text },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
    crosshair: { mode: CrosshairMode.Normal },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  winRateSeries = chart.addSeries(LineSeries, {
    color: c.accent,
    lineWidth: 2,
    title: 'Win Rate',
    priceFormat: { type: 'custom', formatter: v => (v * 100).toFixed(1) + '%' },
  })

  pnlSeries = chart.addSeries(HistogramSeries, {
    priceScaleId: 'pnl',
    title: 'Total PnL',
    priceFormat: { type: 'custom', formatter: v => (v * 100).toFixed(2) + '%' },
  })
  chart.priceScale('pnl').applyOptions({
    scaleMargins: { top: 0.6, bottom: 0 },
  })

  resizeObserver = new ResizeObserver(() => {
    if (chartEl.value) chart.applyOptions({ width: chartEl.value.clientWidth })
  })
  resizeObserver.observe(chartEl.value)
}

function updateData() {
  if (!winRateSeries || !props.results.length) return

  // Sort by run_time ascending
  const sorted = [...props.results].sort((a, b) =>
    new Date(a.run_time).getTime() - new Date(b.run_time).getTime()
  )

  const winRateData = sorted.map(r => ({
    time: Math.floor(new Date(r.run_time).getTime() / 1000),
    value: r.win_rate,
  }))

  const c = getChartThemeColors()
  const pnlData = sorted.map(r => ({
    time: Math.floor(new Date(r.run_time).getTime() / 1000),
    value: r.total_pnl,
    color: r.total_pnl >= 0 ? c.up : c.down,
  }))

  winRateSeries.setData(winRateData)
  pnlSeries.setData(pnlData)
  chart.timeScale().fitContent()
}

watch(() => props.results, updateData, { deep: true })
watch(theme, () => { setTimeout(applyThemeToChart, 50) })

onMounted(() => {
  initChart()
  updateData()
})

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) chart.remove()
})
</script>

<template>
  <div ref="chartEl" style="width: 100%; min-height: 300px;"></div>
  <div v-if="results.length" style="display: flex; gap: 1.5rem; justify-content: center; margin-top: 0.5rem; font-size: 0.85rem;">
    <span><span style="color: var(--tp-primary);">&#9644;</span> Win Rate (left axis)</span>
    <span><span style="color: var(--tp-success);">&#9632;</span>/<span style="color: var(--tp-danger);">&#9632;</span> Total PnL (right axis)</span>
  </div>
  <p v-else class="secondary" style="text-align:center;">No backtest history available.</p>
</template>
