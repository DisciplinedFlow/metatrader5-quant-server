<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { createChart, CandlestickSeries, LineSeries, CrosshairMode, createSeriesMarkers } from 'lightweight-charts'
import { useTheme, getChartThemeColors } from '@/composables/useTheme'
import api from '@/services/api'

const STRATEGY_INTERVAL = {
  SCALPING: '5m',
  MEAN_REVERSION: '15m',
  // MT5 timeframe codes used by custom strategies
  M1: '1m', M5: '5m', M15: '15m',
  H1: '1h', H4: '4h', D1: '1d',
}

const props = defineProps({
  trades: { type: Array, default: () => [] },
  symbol: { type: String, default: '' },
  strategy: { type: String, default: '' },
  timeframe: { type: String, default: '' },
  symbolSuffix: { type: String, default: '' },
})

const emit = defineEmits(['update:symbol'])
const { theme } = useTheme()

const chartEl = ref(null)
const symbols = ref([])
const selectedSymbol = ref('')
const loading = ref(false)
const selectedTradeIdx = ref(null)

let chart = null
let candleSeries = null
let entryLineSeries = null
let slLineSeries = null
let tpLineSeries = null
let seriesMarkers = null
let resizeObserver = null

// Extract unique symbols from trades
function extractSymbols() {
  const syms = [...new Set(props.trades.map(t => t.symbol).filter(Boolean))]
  symbols.value = syms.sort()
  if (syms.length && !selectedSymbol.value) {
    selectedSymbol.value = props.symbol || syms[0]
  }
}

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
    height: 450,
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

  // Entry price line (blue dashed)
  entryLineSeries = chart.addSeries(LineSeries, {
    color: '#42a5f5',
    lineWidth: 1,
    lineStyle: 2, // dashed
    crosshairMarkerVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
  })

  // SL line (red dashed)
  slLineSeries = chart.addSeries(LineSeries, {
    color: '#ef5350',
    lineWidth: 1,
    lineStyle: 2,
    crosshairMarkerVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
  })

  // TP line (green dashed)
  tpLineSeries = chart.addSeries(LineSeries, {
    color: '#26a69a',
    lineWidth: 1,
    lineStyle: 2,
    crosshairMarkerVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
  })

  resizeObserver = new ResizeObserver(() => {
    if (chartEl.value) chart.applyOptions({ width: chartEl.value.clientWidth })
  })
  resizeObserver.observe(chartEl.value)
}

function filteredTrades() {
  return props.trades.filter(t => t.symbol === selectedSymbol.value)
}

async function loadChart() {
  if (!selectedSymbol.value || !chart) return
  loading.value = true
  selectedTradeIdx.value = null
  try {
    const interval = STRATEGY_INTERVAL[props.timeframe] || STRATEGY_INTERVAL[props.strategy] || '5m'
    const data = await api.fetchYahooData(selectedSymbol.value + props.symbolSuffix, '60d', interval)
    const candles = data.map(d => ({
      time: Math.floor(new Date(d.time).getTime() / 1000),
      open: d.open, high: d.high, low: d.low, close: d.close,
    }))
    candleSeries.setData(candles)

    // Build markers from trades for this symbol
    const symbolTrades = filteredTrades()
    const markers = []
    for (const t of symbolTrades) {
      if (t.entry_time) {
        markers.push({
          time: t.entry_time,
          position: t.type === 'BUY' ? 'belowBar' : 'aboveBar',
          color: t.type === 'BUY' ? '#26a69a' : '#ef5350',
          shape: t.type === 'BUY' ? 'arrowUp' : 'arrowDown',
          text: `${t.type} @ ${formatPrice(t.entry)}`,
        })
      }
      if (t.exit_time) {
        markers.push({
          time: t.exit_time,
          position: t.result === 'TP' ? 'aboveBar' : 'belowBar',
          color: t.result === 'TP' ? '#26a69a' : '#ef5350',
          shape: 'circle',
          text: `${t.result} @ ${formatPrice(t.exit)}`,
        })
      }
    }
    markers.sort((a, b) => a.time - b.time)
    if (seriesMarkers) seriesMarkers.detach()
    seriesMarkers = createSeriesMarkers(candleSeries, markers)

    // Clear level lines
    entryLineSeries.setData([])
    slLineSeries.setData([])
    tpLineSeries.setData([])

    chart.timeScale().fitContent()
  } catch (err) {
    console.error('TradeMarkers chart error:', err)
  }
  loading.value = false
}

function highlightTrade(idx) {
  if (!chart) return
  const symbolTrades = filteredTrades()
  const t = symbolTrades[idx]
  if (!t || !t.entry_time || !t.exit_time) return

  selectedTradeIdx.value = idx

  // Draw entry, SL, TP lines spanning entry_time to exit_time
  const from = t.entry_time
  const to = t.exit_time

  entryLineSeries.setData([
    { time: from, value: t.entry },
    { time: to, value: t.entry },
  ])

  if (t.sl != null) {
    slLineSeries.setData([
      { time: from, value: t.sl },
      { time: to, value: t.sl },
    ])
  } else {
    slLineSeries.setData([])
  }

  if (t.tp != null) {
    tpLineSeries.setData([
      { time: from, value: t.tp },
      { time: to, value: t.tp },
    ])
  } else {
    tpLineSeries.setData([])
  }

  // Zoom to the trade time range with some padding
  const padding = (to - from) * 0.3 || 300
  chart.timeScale().setVisibleRange({
    from: from - padding,
    to: to + padding,
  })
}

function clearHighlight() {
  selectedTradeIdx.value = null
  if (entryLineSeries) entryLineSeries.setData([])
  if (slLineSeries) slLineSeries.setData([])
  if (tpLineSeries) tpLineSeries.setData([])
  if (chart) chart.timeScale().fitContent()
}

function formatPrice(p) {
  if (p == null) return 'N/A'
  return Number(p).toFixed(5)
}

function formatTime(ts) {
  if (!ts) return 'N/A'
  return new Date(ts * 1000).toLocaleString()
}

watch(theme, () => {
  setTimeout(applyThemeToChart, 50)
})

watch(selectedSymbol, () => {
  emit('update:symbol', selectedSymbol.value)
  loadChart()
})

watch(() => props.trades, () => {
  extractSymbols()
  loadChart()
}, { deep: true })

onMounted(() => {
  extractSymbols()
  initChart()
  loadChart()
})

onBeforeUnmount(() => {
  if (seriesMarkers) seriesMarkers.detach()
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) chart.remove()
})
</script>

<template>
  <div style="margin-bottom: 0.5rem;">
    <label>
      Symbol
      <select v-model="selectedSymbol" :aria-busy="loading">
        <option v-for="s in symbols" :key="s" :value="s">{{ s }}</option>
      </select>
    </label>
  </div>
  <div ref="chartEl" style="width: 100%; min-height: 450px;"></div>

  <!-- Legend -->
  <div v-if="trades.length" style="display: flex; gap: 1.5rem; justify-content: center; margin: 0.5rem 0; font-size: 0.8rem;">
    <span><span style="color: var(--tp-primary);">---</span> Entry</span>
    <span><span style="color: var(--tp-danger);">---</span> Stop Loss</span>
    <span><span style="color: var(--tp-success);">---</span> Take Profit</span>
    <span style="opacity: 0.7;">Click a trade row to highlight on chart</span>
  </div>

  <!-- Trade Detail Table -->
  <figure v-if="filteredTrades().length" style="overflow-x: auto; margin-top: 0.5rem;">
    <table role="grid">
      <thead>
        <tr>
          <th>#</th>
          <th>Type</th>
          <th>Signal</th>
          <th>Entry Price</th>
          <th>Stop Loss</th>
          <th>Take Profit</th>
          <th>Exit Price</th>
          <th>Result</th>
          <th>PnL</th>
          <th>Entry Time</th>
          <th>Exit Time</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(t, idx) in filteredTrades()"
          :key="idx"
          :style="{
            cursor: 'pointer',
            background: selectedTradeIdx === idx ? 'rgba(66, 165, 245, 0.15)' : 'transparent',
          }"
          @click="selectedTradeIdx === idx ? clearHighlight() : highlightTrade(idx)"
        >
          <td>{{ idx + 1 }}</td>
          <td :style="{ color: t.type === 'BUY' ? 'var(--tp-success)' : 'var(--tp-danger)', fontWeight: 'bold' }">{{ t.type }}</td>
          <td style="font-size: 0.8rem; opacity: 0.85;">{{ t.signal || '-' }}</td>
          <td>{{ formatPrice(t.entry) }}</td>
          <td style="color: var(--tp-danger);">{{ formatPrice(t.sl) }}</td>
          <td style="color: var(--tp-success);">{{ formatPrice(t.tp) }}</td>
          <td>{{ formatPrice(t.exit) }}</td>
          <td>
            <mark :class="{ secondary: t.result !== 'TP' }">{{ t.result }}</mark>
          </td>
          <td :style="{ color: t.pnl_pct >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
            {{ (t.pnl_pct * 100).toFixed(3) }}%
          </td>
          <td style="font-size: 0.8rem;">{{ formatTime(t.entry_time) }}</td>
          <td style="font-size: 0.8rem;">{{ formatTime(t.exit_time) }}</td>
        </tr>
      </tbody>
    </table>
  </figure>
  <p v-else-if="!trades.length" class="secondary" style="text-align:center;">No trade data available.</p>
</template>
