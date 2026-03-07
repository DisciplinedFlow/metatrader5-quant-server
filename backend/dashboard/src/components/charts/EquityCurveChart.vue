<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { createChart, AreaSeries, CrosshairMode } from 'lightweight-charts'

const props = defineProps({
  equityCurve: { type: Array, default: () => [] },
})

const chartEl = ref(null)
let chart = null
let series = null
let resizeObserver = null

function initChart() {
  if (!chartEl.value) return
  chart = createChart(chartEl.value, {
    width: chartEl.value.clientWidth,
    height: 300,
    layout: { background: { color: '#1a1a2e' }, textColor: '#e0e0e0' },
    grid: { vertLines: { color: '#2a2a4a' }, horzLines: { color: '#2a2a4a' } },
    crosshair: { mode: CrosshairMode.Normal },
    timeScale: { timeVisible: true, secondsVisible: false },
  })
  series = chart.addSeries(AreaSeries, {
    lineColor: '#26a69a',
    topColor: 'rgba(38, 166, 154, 0.4)',
    bottomColor: 'rgba(38, 166, 154, 0.0)',
    lineWidth: 2,
  })
  resizeObserver = new ResizeObserver(() => {
    if (chartEl.value) chart.applyOptions({ width: chartEl.value.clientWidth })
  })
  resizeObserver.observe(chartEl.value)
}

function updateData() {
  if (!series || !props.equityCurve.length) return
  // Deduplicate timestamps (lightweight-charts requires unique ascending times)
  // Keep last entry per timestamp since it has the correct cumulative value
  const byTime = new Map()
  for (const p of props.equityCurve) {
    if (p.time > 0) {
      byTime.set(p.time, p.value * 100)
    }
  }
  const data = Array.from(byTime.entries())
    .map(([time, value]) => ({ time, value }))
    .sort((a, b) => a.time - b.time)
  if (data.length) {
    series.setData(data)
    chart.timeScale().fitContent()
  }
}

watch(() => props.equityCurve, updateData, { deep: true })

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
  <p v-if="!equityCurve.length" class="secondary" style="text-align:center;">No equity curve data available.</p>
</template>
