<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, CrosshairMode, createSeriesMarkers } from 'lightweight-charts'
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
  { to: '/forex/performance', label: 'Performance' },
]

const toast = useToast()
const { theme } = useTheme()

const symbol = ref('EURUSD')
const timeframe = ref('M5')
const numBars = ref(500)
const showTrades = ref(true)
const chartEl = ref(null)

// Trade overlay state
const trades = ref([])
const selectedTradeIdx = ref(null)

// Plain variables — NOT reactive (Vue Proxy breaks chart internals)
let chart = null
let candleSeries = null
let volumeSeries = null
let entryLineSeries = null
let slLineSeries = null
let tpLineSeries = null
let seriesMarkers = null
let resizeObserver = null
let chartTimeRange = null

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

  // Trade overlay line series
  entryLineSeries = chart.addSeries(LineSeries, {
    color: '#42a5f5', lineWidth: 1, lineStyle: 2,
    crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
  })
  slLineSeries = chart.addSeries(LineSeries, {
    color: '#ef5350', lineWidth: 1, lineStyle: 2,
    crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
  })
  tpLineSeries = chart.addSeries(LineSeries, {
    color: '#26a69a', lineWidth: 1, lineStyle: 2,
    crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
  })

  resizeObserver = new ResizeObserver(() => {
    if (chartEl.value) chart.applyOptions({ width: chartEl.value.clientWidth })
  })
  resizeObserver.observe(chartEl.value)
}

// Transform API trade to chart marker format
function transformTrade(t) {
  const entryTs = Math.floor(new Date(t.entry_time).getTime() / 1000)
  const exitTs = t.close_time ? Math.floor(new Date(t.close_time).getTime() / 1000) : null

  // Extract last SL/TP from mutations
  let sl = null, tp = null
  if (t.close_prices_mutations && t.close_prices_mutations.length) {
    const last = t.close_prices_mutations[t.close_prices_mutations.length - 1]
    sl = last.new_sl_price
    tp = last.new_tp_price
  }

  return {
    entry_time: entryTs,
    exit_time: exitTs,
    entry: t.entry_price,
    exit: t.close_price,
    type: t.type || 'BUY',
    result: t.closing_reason || (t.close_time ? 'CLOSED' : 'OPEN'),
    sl, tp,
    pnl: t.pnl,
    strategy: t.strategy_config_name || t.strategy || '—',
    duration: exitTs && entryTs ? formatDuration(exitTs - entryTs) : 'Open',
    isOpen: !t.close_time,
  }
}

function formatDuration(secs) {
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  const rm = mins % 60
  return `${hrs}h ${rm}m`
}

function formatPrice(p) {
  if (p == null) return '—'
  return Number(p).toFixed(5)
}

async function fetchTrades() {
  if (!showTrades.value) { trades.value = []; return }
  try {
    const data = await api.getForexTrades(`&symbol=${symbol.value}`)
    const raw = data.results || data || []
    trades.value = raw.map(transformTrade)
  } catch {
    trades.value = []
  }
}

function tradeInRange(t) {
  if (!chartTimeRange) return false
  return t.entry_time >= chartTimeRange.from && t.entry_time <= chartTimeRange.to
}

function renderMarkers() {
  if (seriesMarkers) { seriesMarkers.detach(); seriesMarkers = null }
  if (!candleSeries || !showTrades.value || !trades.value.length) return

  const markers = []
  for (const t of trades.value) {
    if (!tradeInRange(t)) continue
    if (t.entry_time) {
      markers.push({
        time: t.entry_time,
        position: t.type === 'BUY' ? 'belowBar' : 'aboveBar',
        color: t.type === 'BUY' ? '#26a69a' : '#ef5350',
        shape: t.type === 'BUY' ? 'arrowUp' : 'arrowDown',
        text: t.type,
        size: 1,
      })
    }
    if (t.exit_time) {
      const win = t.result === 'TP' || t.pnl > 0
      markers.push({
        time: t.exit_time,
        position: win ? 'aboveBar' : 'belowBar',
        color: win ? '#26a69a' : '#ef5350',
        shape: 'circle',
        text: t.pnl != null ? `${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(1)}` : t.result,
        size: 0,
      })
    }
  }
  markers.sort((a, b) => a.time - b.time)
  if (markers.length) {
    seriesMarkers = createSeriesMarkers(candleSeries, markers)
  }
}

function clearLines() {
  if (entryLineSeries) entryLineSeries.setData([])
  if (slLineSeries) slLineSeries.setData([])
  if (tpLineSeries) tpLineSeries.setData([])
}

function highlightTrade(idx) {
  const t = trades.value[idx]
  if (!t || !chart) return

  if (selectedTradeIdx.value === idx) {
    selectedTradeIdx.value = null
    clearLines()
    chart.timeScale().fitContent()
    return
  }

  // Skip zoom for trades outside chart data range
  if (!tradeInRange(t)) return

  selectedTradeIdx.value = idx
  const from = t.entry_time
  const to = t.exit_time || (from + 3600)

  entryLineSeries.setData([
    { time: from, value: t.entry },
    { time: to, value: t.entry },
  ])
  if (t.sl != null) {
    slLineSeries.setData([{ time: from, value: t.sl }, { time: to, value: t.sl }])
  } else { slLineSeries.setData([]) }
  if (t.tp != null) {
    tpLineSeries.setData([{ time: from, value: t.tp }, { time: to, value: t.tp }])
  } else { tpLineSeries.setData([]) }

  const tradeSpan = to - from
  const padding = Math.max(tradeSpan * 2, 1800) // At least 30 min each side, or 2x trade duration
  chart.timeScale().setVisibleRange({ from: from - padding, to: to + padding })
}

async function loadChart() {
  if (!symbol.value || !chart) return
  selectedTradeIdx.value = null
  clearLines()

  try {
    const data = await api.fetchDataPos(symbol.value, timeframe.value, numBars.value)
    const c = getChartThemeColors()

    const candles = data.map(d => ({
      time: Math.floor(new Date(d.time).getTime() / 1000),
      open: d.open, high: d.high, low: d.low, close: d.close,
    }))
    const volumes = data.map(d => ({
      time: Math.floor(new Date(d.time).getTime() / 1000),
      value: d.tick_volume || d.real_volume || 0,
      color: d.close >= d.open ? c.up + '80' : c.down + '80',
    }))

    candleSeries.setData(candles)
    volumeSeries.setData(volumes)
    chart.timeScale().fitContent()

    // Store candle time range for filtering trades
    if (candles.length) {
      chartTimeRange = { from: candles[0].time, to: candles[candles.length - 1].time }
    } else {
      chartTimeRange = null
    }

    await fetchTrades()
    renderMarkers()
  } catch (err) {
    toast.error(`Chart error: ${err.message}`)
  }
}

watch(theme, () => setTimeout(applyThemeToChart, 50))
watch(showTrades, () => { fetchTrades().then(renderMarkers) })

onMounted(() => { initChart(); loadChart() })
onBeforeUnmount(() => {
  if (seriesMarkers) seriesMarkers.detach()
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) chart.remove()
})
</script>

<template>
  <SectionNav :links="forexLinks" />
  <div class="tp-page chart-page">
    <!-- Controls Strip -->
    <div class="controls-strip">
      <div class="ctrl-field">
        <label class="tp-label">Symbol</label>
        <SymbolSelect v-model="symbol" class="tp-select" />
      </div>
      <div class="ctrl-field">
        <label class="tp-label">Timeframe</label>
        <select v-model="timeframe" class="tp-select">
          <option value="M1">M1</option>
          <option value="M5">M5</option>
          <option value="M15">M15</option>
          <option value="M30">M30</option>
          <option value="H1">H1</option>
          <option value="H4">H4</option>
          <option value="D1">D1</option>
        </select>
      </div>
      <div class="ctrl-field">
        <label class="tp-label">Bars</label>
        <input v-model.number="numBars" type="number" min="50" max="1000" class="tp-input" />
      </div>
      <div class="ctrl-field ctrl-toggle">
        <label class="trade-toggle">
          <input type="checkbox" v-model="showTrades" />
          <span class="toggle-track"><span class="toggle-thumb"></span></span>
          Trades
        </label>
      </div>
      <div class="ctrl-field ctrl-action">
        <button type="button" class="tp-btn tp-btn-primary" @click="loadChart">
          <span class="material-symbols-outlined" style="font-size:16px">show_chart</span>
          Load
        </button>
      </div>
    </div>

    <!-- Chart -->
    <div class="tp-card chart-card">
      <div ref="chartEl" class="chart-container"></div>
      <!-- Legend -->
      <div class="chart-legend" v-if="showTrades && trades.length">
        <span class="legend-entry"><span class="legend-line" style="background:#42a5f5"></span> Entry</span>
        <span class="legend-entry"><span class="legend-line" style="background:#ef5350"></span> Stop Loss</span>
        <span class="legend-entry"><span class="legend-line" style="background:#26a69a"></span> Take Profit</span>
        <span class="legend-hint">Click a trade to zoom</span>
      </div>
    </div>

    <!-- Trade List -->
    <div class="tp-card trades-card" v-if="showTrades && trades.length">
      <div class="trades-header">
        <h3>Recent Trades on {{ symbol }}</h3>
        <span class="trade-count">{{ trades.length }} trades</span>
      </div>
      <div class="trades-table-wrap">
        <table class="tp-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Side</th>
              <th>Entry</th>
              <th>SL</th>
              <th>TP</th>
              <th>Exit</th>
              <th>P&L</th>
              <th>Duration</th>
              <th>Strategy</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(t, idx) in trades.slice(0, 30)" :key="idx"
                class="trade-row"
                :class="{ 'trade-row-selected': selectedTradeIdx === idx, 'trade-row-open': t.isOpen, 'trade-row-dimmed': !tradeInRange(t) }"
                @click="highlightTrade(idx)">
              <td class="td-time">{{ new Date(t.entry_time * 1000).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) }} {{ new Date(t.entry_time * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) }}</td>
              <td>
                <span class="side-badge" :class="t.type === 'BUY' ? 'buy' : 'sell'">{{ t.type }}</span>
              </td>
              <td class="td-mono">{{ formatPrice(t.entry) }}</td>
              <td class="td-mono td-sl">{{ formatPrice(t.sl) }}</td>
              <td class="td-mono td-tp">{{ formatPrice(t.tp) }}</td>
              <td class="td-mono">{{ formatPrice(t.exit) }}</td>
              <td class="td-pnl" :class="t.pnl > 0 ? 'pnl-pos' : t.pnl < 0 ? 'pnl-neg' : ''">
                <template v-if="t.pnl != null">{{ t.pnl >= 0 ? '+' : '' }}${{ t.pnl.toFixed(2) }}</template>
                <span v-else class="open-badge">OPEN</span>
              </td>
              <td class="td-dim">{{ t.duration }}</td>
              <td class="td-strategy">{{ t.strategy }}</td>
              <td>
                <span class="result-badge" :class="t.result === 'TP' || t.pnl > 0 ? 'result-win' : 'result-loss'">{{ t.result }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
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
.ctrl-field:nth-child(1) { flex: 1.5; min-width: 130px; }
.ctrl-field:nth-child(2) { flex: 1; min-width: 100px; }
.ctrl-field:nth-child(3) { flex: 0.7; min-width: 80px; }
.ctrl-toggle { justify-content: flex-end; flex: 0 0 auto; }
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

/* Trade toggle switch */
.trade-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--tp-text-dim);
  cursor: pointer;
}
.trade-toggle input { display: none; }
.toggle-track {
  position: relative;
  width: 32px; height: 18px;
  background: var(--tp-border-light);
  border-radius: 9px;
  transition: background 0.2s;
}
.toggle-thumb {
  position: absolute;
  top: 2px; left: 2px;
  width: 14px; height: 14px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
}
.trade-toggle input:checked + .toggle-track {
  background: var(--tp-primary);
}
.trade-toggle input:checked + .toggle-track .toggle-thumb {
  transform: translateX(14px);
}

/* Chart */
.chart-card {
  padding: 0;
  overflow: hidden;
  margin-bottom: 1rem;
}
.chart-container {
  width: 100%;
  height: 520px;
}
.chart-legend {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  padding: 0.5rem 1rem;
  border-top: 1px solid var(--tp-border);
  font-size: 0.72rem;
  color: var(--tp-text-dim);
}
.legend-entry {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.legend-line {
  width: 16px; height: 2px;
  display: inline-block;
}
.legend-hint {
  margin-left: auto;
  font-style: italic;
  opacity: 0.7;
}

/* Trades Card */
.trades-card {
  overflow: hidden;
}
.trades-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--tp-border);
}
.trades-header h3 {
  font-size: 0.85rem;
  font-weight: 700;
}
.trade-count {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
  font-weight: 600;
}
.trades-table-wrap {
  overflow-x: auto;
  max-height: 320px;
  overflow-y: auto;
}
.trades-table-wrap::-webkit-scrollbar { width: 6px; }
.trades-table-wrap::-webkit-scrollbar-thumb { background: var(--tp-border-light); border-radius: 3px; }

.trade-row { cursor: pointer; transition: background 0.1s; }
.trade-row:hover { background: var(--tp-bg-hover); }
.trade-row-selected { background: rgba(66, 165, 245, 0.1) !important; }
.trade-row-open { background: rgba(59, 130, 246, 0.04); }
.trade-row-dimmed { opacity: 0.35; cursor: default; }

.td-time { font-size: 0.75rem; color: var(--tp-text-dim); white-space: nowrap; }
.td-mono { font-family: var(--tp-font-mono); font-size: 0.75rem; color: var(--tp-text-muted); }
.td-sl { color: #ef5350 !important; }
.td-tp { color: #26a69a !important; }
.td-pnl { font-weight: 700; font-family: var(--tp-font-mono); font-size: 0.78rem; }
.td-dim { font-size: 0.75rem; color: var(--tp-text-dim); }
.td-strategy { font-size: 0.72rem; color: var(--tp-text-dim); max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pnl-pos { color: #22c55e; }
.pnl-neg { color: #ef4444; }

.side-badge {
  display: inline-block;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.side-badge.buy { background: rgba(34, 197, 94, 0.12); color: #22c55e; }
.side-badge.sell { background: rgba(239, 68, 68, 0.12); color: #ef4444; }
.open-badge {
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 700;
  background: rgba(59, 130, 246, 0.12);
  color: #3b82f6;
}
.result-badge {
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 700;
}
.result-win { background: rgba(34, 197, 94, 0.12); color: #22c55e; }
.result-loss { background: rgba(239, 68, 68, 0.12); color: #ef4444; }

@media (max-width: 768px) {
  .controls-strip { gap: 0.5rem; padding: 0.5rem; }
  .chart-container { height: 400px; }
}
</style>
