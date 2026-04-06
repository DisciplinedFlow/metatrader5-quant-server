<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { usePositionsStore } from '@/stores/positions'
import { usePolling } from '@/composables/usePolling'
import { useHMMRegime } from '@/composables/useHMMRegime'
import { useWebSocket } from '@/composables/useWebSocket'
import PositionsTable from '@/components/PositionsTable.vue'
import MarketSessions from '@/components/MarketSessions.vue'
import SectionNav from '@/components/SectionNav.vue'
import ICTSetupLog from '@/components/ICTSetupLog.vue'
import HMMRegimeWidget from '@/components/HMMRegimeWidget.vue'
import api from '@/services/api'

const router = useRouter()

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

const positionsStore = usePositionsStore()
const posError = ref(false)
const botPaused = ref(false)
const botStatusLoading = ref(false)
const marketPulse = ref({ news: [], calendar: [] })
const trades = ref([])

// P&L chart data
const closedTrades = computed(() =>
  trades.value.filter(t => t.close_time && t.pnl != null).sort((a, b) => new Date(a.close_time) - new Date(b.close_time))
)

const equityCurve = computed(() => {
  let cumulative = 0
  return closedTrades.value.map(t => {
    cumulative += t.pnl
    return { pnl: t.pnl, cumulative, symbol: t.symbol, time: t.close_time }
  })
})

const pnlStats = computed(() => {
  const ct = closedTrades.value
  const wins = ct.filter(t => t.pnl > 0)
  const losses = ct.filter(t => t.pnl <= 0)
  const totalPnl = ct.reduce((s, t) => s + t.pnl, 0)
  const totalGross = ct.reduce((s, t) => s + (t.pnl_excluding_commission ?? t.pnl), 0)
  const totalCommission = ct.reduce((s, t) => s + (t.order_commission ?? 0), 0)
  const winRate = ct.length ? (wins.length / ct.length * 100) : 0
  const bestTrade = ct.length ? Math.max(...ct.map(t => t.pnl)) : 0
  const worstTrade = ct.length ? Math.min(...ct.map(t => t.pnl)) : 0
  return { total: ct.length, wins: wins.length, losses: losses.length, totalPnl, totalGross, totalCommission, winRate, bestTrade, worstTrade }
})

// SVG equity curve path
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

async function refresh() {
  const [posResult, botResult] = await Promise.allSettled([
    positionsStore.fetchPositions(),
    api.getBotStatus(),
  ])
  posError.value = posResult.status === 'rejected'
  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }
}

async function toggleBot() {
  botStatusLoading.value = true
  try {
    const resp = await api.setBotPaused(!botPaused.value)
    botPaused.value = resp.paused
  } catch (err) {
    console.error('Bot toggle error:', err)
  }
  botStatusLoading.value = false
}

async function fetchMarketPulse() {
  try {
    marketPulse.value = await api.getMarketPulse()
  } catch (err) {
    console.error('Market pulse fetch error:', err)
  }
}

async function fetchTrades() {
  try {
    const data = await api.getForexTrades()
    trades.value = data.results || data || []
  } catch (err) {
    console.error('Trades fetch error:', err)
  }
}

function formatNewsTime(unixTimestamp) {
  if (!unixTimestamp) return ''
  const d = new Date(unixTimestamp * 1000)
  const now = new Date()
  const diffMs = now - d
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  return d.toLocaleDateString()
}

const hmmRegime = useHMMRegime()

// WebSocket: auto-refresh on live trade events
const { connected: wsConnected, on: wsOn } = useWebSocket()
wsOn('trade_opened', () => { refresh(); fetchTrades() })
wsOn('trade_closed', () => { refresh(); fetchTrades() })
wsOn('position_update', () => refresh())
wsOn('bot_status', (data) => { if (data && data.paused != null) botPaused.value = data.paused })
wsOn('news_alert', () => fetchMarketPulse())

onMounted(fetchTrades)
usePolling(refresh, 30000)              // was 5s — bot gets API priority
usePolling(fetchMarketPulse, 300000)    // was 120s — use Lighter browser instead
usePolling(fetchTrades, 60000)          // was 30s
usePolling(() => hmmRegime.fetch(), 120000)  // was 30s
</script>

<template>
  <SectionNav :links="forexLinks" />
  <div class="tp-page dashboard-page">

    <!-- ═══════ COMMAND BAR ═══════ -->
    <div class="command-bar">
      <div class="cmd-left">
        <div class="cmd-bot">
          <span class="bot-dot" :class="botPaused ? 'dot-paused' : 'dot-live'"></span>
          <span class="bot-label">{{ botPaused ? 'PAUSED' : 'LIVE' }}</span>
        </div>
        <button class="cmd-toggle" @click="toggleBot" :aria-busy="botStatusLoading">
          <span class="material-symbols-outlined">{{ botPaused ? 'play_arrow' : 'pause' }}</span>
        </button>
        <span class="ws-indicator" :class="wsConnected ? 'ws-connected' : 'ws-disconnected'">
          <span class="pulse-dot" v-if="wsConnected"></span>
          {{ wsConnected ? 'Live' : 'Polling' }}
        </span>
      </div>

      <div class="cmd-metrics">
        <div class="cmd-sep"></div>
        <div class="cmd-metric cmd-metric-hero">
          <span class="cmd-label">Net P&L</span>
          <span class="cmd-value" :class="pnlStats.totalPnl >= 0 ? 'val-pos' : 'val-neg'">
            {{ pnlStats.totalPnl >= 0 ? '+' : '' }}&euro;{{ pnlStats.totalPnl.toFixed(2) }}
          </span>
        </div>
        <div class="cmd-sep"></div>
        <div class="cmd-metric">
          <span class="cmd-label">Gross</span>
          <span class="cmd-value" :class="pnlStats.totalGross >= 0 ? 'val-pos' : 'val-neg'">
            {{ pnlStats.totalGross >= 0 ? '+' : '' }}&euro;{{ pnlStats.totalGross.toFixed(2) }}
          </span>
        </div>
        <div class="cmd-sep"></div>
        <div class="cmd-metric">
          <span class="cmd-label">Fees</span>
          <span class="cmd-value val-neg">
            &euro;{{ pnlStats.totalCommission.toFixed(2) }}
          </span>
        </div>
        <div class="cmd-sep"></div>
        <div class="cmd-metric">
          <span class="cmd-label">Win Rate</span>
          <span class="cmd-value">{{ pnlStats.winRate.toFixed(0) }}%</span>
        </div>
        <div class="cmd-sep"></div>
        <div class="cmd-metric">
          <span class="cmd-label">W / L</span>
          <span class="cmd-value">{{ pnlStats.wins }}<span class="cmd-dim"> / </span>{{ pnlStats.losses }}</span>
        </div>
        <div class="cmd-sep"></div>
        <div class="cmd-metric">
          <span class="cmd-label">Open</span>
          <span class="cmd-value">{{ positionsStore.positions.length }}</span>
        </div>
        <div class="cmd-sep"></div>
        <div class="cmd-metric">
          <span class="cmd-label">Floating</span>
          <span class="cmd-value" :class="positionsStore.totalProfit >= 0 ? 'val-pos' : 'val-neg'" v-if="!posError">
            {{ positionsStore.totalProfit >= 0 ? '+' : '' }}&euro;{{ positionsStore.totalProfit.toFixed(2) }}
          </span>
          <span v-else class="cmd-value cmd-dim">&mdash;</span>
        </div>
        <div class="cmd-sep"></div>
        <div class="cmd-metric">
          <span class="cmd-label">Swap</span>
          <span class="cmd-value" v-if="!posError">&euro;{{ positionsStore.totalSwap.toFixed(2) }}</span>
          <span v-else class="cmd-value cmd-dim">&mdash;</span>
        </div>
      </div>
    </div>

    <!-- ═══════ ROW 1: Performance + Active Positions (full width) ═══════ -->
    <div class="row-perf-pos">
      <!-- Performance -->
      <div class="tp-card dash-card perf-card" style="--stagger: 1">
        <div class="card-accent accent-green"></div>
        <div class="perf-header">
          <h3 class="card-title">Performance</h3>
          <span class="perf-total" :class="pnlStats.totalPnl >= 0 ? 'val-pos' : 'val-neg'">
            {{ pnlStats.totalPnl >= 0 ? '+' : '' }}&euro;{{ pnlStats.totalPnl.toFixed(2) }}
          </span>
        </div>
        <span class="perf-trades">{{ pnlStats.total }} closed trades</span>

        <div class="equity-chart" v-if="equityCurve.length >= 2">
          <svg viewBox="0 0 280 80" preserveAspectRatio="none" class="equity-svg">
            <line x1="4" :y1="zeroLineY" x2="276" :y2="zeroLineY" stroke="var(--tp-border)" stroke-width="0.5" stroke-dasharray="4 2" />
            <path :d="chartFill" :fill="pnlStats.totalPnl >= 0 ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)'" />
            <path :d="chartPath" fill="none" :stroke="pnlStats.totalPnl >= 0 ? '#22c55e' : '#ef4444'" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <div v-else class="equity-empty">
          <span class="material-symbols-outlined" style="font-size:1.25rem;color:var(--tp-text-dim)">show_chart</span>
          <span>Awaiting trades...</span>
        </div>

        <div class="trade-bars" v-if="closedTrades.length">
          <div v-for="(t, i) in closedTrades.slice(-30)" :key="i"
               class="trade-bar"
               :class="t.pnl >= 0 ? 'bar-win' : 'bar-loss'"
               :style="{ height: Math.min(100, Math.max(8, Math.abs(t.pnl) * 3)) + '%' }"
               :title="`${t.symbol} ${t.pnl >= 0 ? '+' : ''}€${t.pnl.toFixed(2)}`"
          ></div>
        </div>

        <div class="perf-footer">
          <div class="perf-kpi">
            <span class="perf-kpi-label">Win Rate</span>
            <span class="perf-kpi-val">{{ pnlStats.winRate.toFixed(1) }}%</span>
          </div>
          <div class="perf-kpi">
            <span class="perf-kpi-label">Best</span>
            <span class="perf-kpi-val val-pos">+&euro;{{ pnlStats.bestTrade.toFixed(2) }}</span>
          </div>
          <div class="perf-kpi">
            <span class="perf-kpi-label">Worst</span>
            <span class="perf-kpi-val val-neg">&euro;{{ pnlStats.worstTrade.toFixed(2) }}</span>
          </div>
          <button class="perf-hist-btn" @click="router.push('/forex/history')">
            <span class="material-symbols-outlined">history</span>
            Full History
          </button>
        </div>
      </div>

      <!-- Active Positions -->
      <div class="tp-card dash-card positions-card" style="--stagger: 2">
        <div class="card-accent accent-blue"></div>
        <div class="pos-header">
          <h3 class="card-title">Active Positions</h3>
          <div class="pos-header-right">
            <span class="pos-count" v-if="positionsStore.positions.length">{{ positionsStore.positions.length }} open</span>
            <button class="link-btn" @click="router.push('/forex/history')">View History</button>
          </div>
        </div>
        <div class="pos-body">
          <template v-if="positionsStore.positions.length > 0">
            <PositionsTable :positions="positionsStore.positions" />
          </template>
          <div v-else-if="posError" class="pos-empty">
            <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">cloud_off</span>
            <p>Failed to load positions</p>
          </div>
          <div v-else class="pos-empty">
            <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">view_list</span>
            <p class="pos-empty-title">No open positions</p>
            <p class="pos-empty-sub">Trades will appear here once executed</p>
            <button class="tp-btn tp-btn-primary pos-trade-btn" @click="router.push('/forex/order')">
              <span class="material-symbols-outlined" style="font-size:16px">add_circle</span>
              Trade Now
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════ ROW 2: HMM Regime + Sessions ═══════ -->
    <div class="row-dual">
      <div style="--stagger: 3" class="dash-card hmm-wrapper">
        <HMMRegimeWidget :data="hmmRegime.data.value" :loading="hmmRegime.loading.value" />
      </div>

      <div class="tp-card dash-card sessions-card" style="--stagger: 4">
        <div class="card-accent accent-amber"></div>
        <div class="sessions-head">
          <h3 class="card-title">
            <span class="material-symbols-outlined" style="font-size:18px">schedule</span>
            Sessions
          </h3>
        </div>
        <MarketSessions />
      </div>
    </div>

    <!-- ═══════ ROW 3: ICT Scanner + Market Pulse (aligned bottoms) ═══════ -->
    <div class="row-bottom">
      <!-- ICT Scanner — always expanded, stretches to match -->
      <div class="tp-card dash-card ict-card" style="--stagger: 5">
        <div class="card-accent accent-teal"></div>
        <div class="ict-inner">
          <ICTSetupLog />
        </div>
      </div>

      <!-- Market Pulse — 10 items -->
      <div class="tp-card dash-card news-card" style="--stagger: 6">
        <div class="card-accent accent-slate"></div>
        <div class="news-head">
          <h3 class="card-title">
            <span class="material-symbols-outlined" style="font-size:18px;color:var(--tp-primary)">rss_feed</span>
            Market Pulse
          </h3>
          <span class="news-count" v-if="marketPulse.news.length || marketPulse.calendar.length">
            {{ marketPulse.calendar.length + marketPulse.news.length }} items
          </span>
        </div>
        <div class="news-feed">
          <!-- Calendar events first (high impact) -->
          <div v-for="event in marketPulse.calendar.slice(0, 4)" :key="'cal-' + event.event"
               class="news-item" :class="{ 'news-hi': event.impact === 'high' || event.impact === 3 }">
            <div class="news-left">
              <span class="news-tag news-tag-cal">{{ event.country || 'ECON' }}</span>
              <span v-if="event.impact === 'high' || event.impact === 3" class="news-impact">HIGH</span>
            </div>
            <span class="news-text">{{ event.event }}</span>
          </div>
          <!-- News articles -->
          <div v-for="item in marketPulse.news.slice(0, 10)" :key="item.id" class="news-item">
            <div class="news-left">
              <span class="news-tag">{{ formatNewsTime(item.datetime) }}</span>
            </div>
            <a :href="item.url" target="_blank" rel="noopener" class="news-text news-link">{{ item.headline }}</a>
          </div>
          <div v-if="!marketPulse.news.length && !marketPulse.calendar.length" class="news-empty">
            <span class="material-symbols-outlined" style="font-size:1.25rem;color:var(--tp-text-dim)">rss_feed</span>
            <span>Loading market news...</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ══════════════════════════════════════════════════
   FOREX DASHBOARD — Tactical Command Center v2
   Priority: Valuable data first, full-width usage
   ══════════════════════════════════════════════════ */

:global(.container:has(.dashboard-page)) {
  max-width: 1600px !important;
}
:global(.container:has(.dashboard-page) .tp-tabs) {
  max-width: 1600px;
}

.dashboard-page {
  max-width: 1600px;
  padding: 0.75rem 1.25rem 2rem;
}

/* ═══ STAGGER REVEAL ═══ */
@keyframes card-enter {
  from { opacity: 0; transform: translateY(14px); }
  to   { opacity: 1; transform: translateY(0); }
}
.dash-card {
  animation: card-enter 0.4s cubic-bezier(0.22, 1, 0.36, 1) both;
  animation-delay: calc(var(--stagger, 0) * 0.06s);
}

/* ═══ CARD ACCENTS ═══ */
.card-accent {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  border-radius: var(--tp-radius) var(--tp-radius) 0 0;
  pointer-events: none;
}
.accent-green { background: linear-gradient(90deg, #22c55e, transparent 60%); }
.accent-blue  { background: linear-gradient(90deg, var(--tp-primary), transparent 60%); }
.accent-amber { background: linear-gradient(90deg, #f59e0b, transparent 60%); }
.accent-teal  { background: linear-gradient(90deg, #14b8a6, transparent 60%); }
.accent-slate { background: linear-gradient(90deg, #64748b, transparent 60%); }

.card-title {
  font-size: 0.88rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
}

.val-pos { color: var(--tp-success) !important; }
.val-neg { color: var(--tp-danger) !important; }

/* ══════════════════════════════════════════════════
   COMMAND BAR
   ══════════════════════════════════════════════════ */
.command-bar {
  display: flex;
  align-items: center;
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
  border: var(--tp-glass-border);
  border-radius: var(--tp-radius);
  margin-bottom: 0.875rem;
  overflow: hidden;
  position: relative;
  animation: card-enter 0.3s ease both;
}
.command-bar::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, var(--tp-success), var(--tp-primary), transparent);
  opacity: 0.5;
}
.cmd-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 1rem;
  flex-shrink: 0;
}
.cmd-bot {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.bot-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.45); }
  50%      { box-shadow: 0 0 0 5px rgba(34,197,94,0); }
}
.dot-live   { background: var(--tp-success); animation: pulse-glow 2s ease infinite; }
.dot-paused { background: var(--tp-warning); }
.bot-label {
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  color: var(--tp-text);
}
.cmd-toggle {
  background: var(--tp-bg-surface);
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  color: var(--tp-text);
  cursor: pointer;
  padding: 0.2rem 0.35rem;
  display: flex;
  align-items: center;
  transition: all 0.15s;
  font-family: var(--tp-font);
}
.cmd-toggle:hover { border-color: var(--tp-primary); color: var(--tp-primary); }
.cmd-toggle .material-symbols-outlined { font-size: 16px; }
.cmd-metrics {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
}
.cmd-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0.45rem 0.7rem;
  flex: 1;
  min-width: 0;
}
.cmd-metric-hero .cmd-value { font-size: 1.1rem; }
.cmd-label {
  font-size: 0.52rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--tp-text-dim);
  white-space: nowrap;
  margin-bottom: 0.1rem;
}
.cmd-value {
  font-size: 0.92rem;
  font-weight: 800;
  color: var(--tp-text);
  font-family: var(--tp-font-mono, 'JetBrains Mono', monospace);
  font-feature-settings: 'tnum' 1;
  white-space: nowrap;
  line-height: 1;
}
.cmd-dim { color: var(--tp-text-dim); }
.cmd-sep {
  width: 1px; height: 1.5rem;
  background: var(--tp-border);
  flex-shrink: 0;
}

/* ══════════════════════════════════════════════════
   ROW 1: PERFORMANCE + POSITIONS (most valuable)
   ══════════════════════════════════════════════════ */
.row-perf-pos {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.875rem;
  margin-bottom: 0.875rem;
}
@media (min-width: 1024px) {
  .row-perf-pos {
    grid-template-columns: 1fr 1.5fr;
  }
}

/* ═══ Performance ═══ */
.perf-card {
  position: relative;
  overflow: hidden;
  padding: 1rem;
  display: flex;
  flex-direction: column;
}
.perf-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.15rem;
}
.perf-total {
  font-size: 1.4rem;
  font-weight: 800;
  font-family: var(--tp-font-mono, monospace);
  line-height: 1;
}
.perf-trades {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--tp-text-dim);
  font-family: var(--tp-font-mono, monospace);
  margin-bottom: 0.65rem;
}
.equity-chart {
  width: 100%;
  flex: 1;
  min-height: 6rem;
  margin-bottom: 0.5rem;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  overflow: hidden;
}
.equity-svg { width: 100%; height: 100%; }
.equity-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  height: 6rem;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  margin-bottom: 0.5rem;
  color: var(--tp-text-dim);
  font-size: 0.78rem;
}
.trade-bars {
  display: flex;
  align-items: flex-end;
  gap: 1.5px;
  height: 3.5rem;
  margin-bottom: 0.6rem;
}
.trade-bar {
  flex: 1;
  border-radius: 1.5px 1.5px 0 0;
  min-height: 2px;
  transition: opacity 0.15s;
  cursor: default;
}
.trade-bar:hover { opacity: 0.6; }
.bar-win  { background: #22c55e; }
.bar-loss { background: #ef4444; }

.perf-footer {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  padding-top: 0.6rem;
  border-top: 1px solid var(--tp-border);
  margin-top: auto;
}
.perf-kpi {
  display: flex;
  flex-direction: column;
  gap: 0.05rem;
}
.perf-kpi-label {
  font-size: 0.55rem;
  font-weight: 700;
  color: var(--tp-text-dim);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.perf-kpi-val {
  font-size: 0.85rem;
  font-weight: 800;
  font-family: var(--tp-font-mono, monospace);
  color: var(--tp-text);
}
.perf-hist-btn {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  background: none;
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  color: var(--tp-text-muted);
  font-size: 0.7rem;
  font-weight: 600;
  font-family: var(--tp-font);
  padding: 0.3rem 0.6rem;
  cursor: pointer;
  transition: all 0.15s;
}
.perf-hist-btn:hover { border-color: var(--tp-primary); color: var(--tp-primary); }
.perf-hist-btn .material-symbols-outlined { font-size: 14px; }

/* ═══ Positions ═══ */
.positions-card {
  position: relative;
  overflow: hidden;
}
.pos-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.8rem 1rem;
  border-bottom: 1px solid var(--tp-border);
}
.pos-header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.pos-count {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--tp-success);
  background: rgba(34,197,94,0.1);
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
}
.link-btn {
  background: none;
  border: none;
  color: var(--tp-primary);
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  font-family: var(--tp-font);
  transition: opacity 0.15s;
}
.link-btn:hover { opacity: 0.7; text-decoration: underline; }
.pos-body { padding: 0; }
.pos-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 2.5rem 1.5rem;
  text-align: center;
  gap: 0.25rem;
}
.pos-empty-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--tp-text) !important;
}
.pos-empty-sub {
  font-size: 0.78rem;
  color: var(--tp-text-dim) !important;
}
.pos-trade-btn { margin-top: 0.75rem; font-size: 0.8rem; }

/* ══════════════════════════════════════════════════
   ROW 2: HMM + Sessions (align top)
   ══════════════════════════════════════════════════ */
.row-dual {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.875rem;
  margin-bottom: 0.875rem;
}
@media (min-width: 1024px) {
  .row-dual {
    grid-template-columns: 1fr 1fr;
    align-items: stretch;
  }
}

/* ══════════════════════════════════════════════════
   ROW 3: ICT + News (stretch to align bottoms)
   ══════════════════════════════════════════════════ */
.row-bottom {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.875rem;
  margin-bottom: 0.875rem;
}
@media (min-width: 1024px) {
  .row-bottom {
    grid-template-columns: 1fr 1fr;
    align-items: stretch;
  }
}

/* ═══ HMM wrapper — fill row height ═══ */
.hmm-wrapper {
  display: flex;
  flex-direction: column;
}
.hmm-wrapper :deep(.hmm-widget) {
  flex: 1;
  display: flex;
  flex-direction: column;
}

/* ═══ Sessions ═══ */
.sessions-card {
  position: relative;
  overflow: hidden;
  padding: 1rem;
}
.sessions-head { margin-bottom: 0.35rem; }

/* ═══ ICT Scanner ═══ */
.ict-card {
  position: relative;
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.ict-inner {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--tp-border) transparent;
}

/* ═══ Market Pulse ═══ */
.news-card {
  position: relative;
  overflow: hidden;
  padding: 1rem;
  display: flex;
  flex-direction: column;
}
.news-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}
.news-count {
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--tp-text-dim);
  background: var(--tp-bg-surface);
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
}
.news-feed {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.news-item {
  display: flex;
  gap: 0.6rem;
  align-items: baseline;
  padding: 0.4rem 0 0.4rem 0.65rem;
  border-left: 2px solid var(--tp-border);
  border-bottom: 1px solid rgba(128,128,128,0.06);
}
.news-item:last-child { border-bottom: none; }
.news-hi { border-left-color: var(--tp-warning); }
.news-left {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex-shrink: 0;
}
.news-tag {
  font-size: 0.58rem;
  font-weight: 700;
  color: var(--tp-text-dim);
  text-transform: uppercase;
  white-space: nowrap;
  min-width: 3rem;
  letter-spacing: 0.02em;
}
.news-tag-cal {
  color: var(--tp-warning);
}
.news-impact {
  font-size: 0.5rem;
  font-weight: 800;
  color: var(--tp-danger);
  background: rgba(239,68,68,0.1);
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
  letter-spacing: 0.04em;
}
.news-text {
  font-size: 0.78rem;
  color: var(--tp-text);
  line-height: 1.35;
}
.news-link {
  color: var(--tp-text);
  text-decoration: none;
  transition: color 0.15s;
}
.news-link:hover { color: var(--tp-primary); }
.news-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 2rem 1rem;
  color: var(--tp-text-dim);
  font-size: 0.8rem;
}

/* ══════════════════════════════════════════════════
   RESPONSIVE
   ══════════════════════════════════════════════════ */
@media (max-width: 768px) {
  .command-bar { flex-direction: column; }
  .cmd-left {
    width: 100%;
    justify-content: center;
    border-bottom: 1px solid var(--tp-border);
  }
  .cmd-metrics { flex-wrap: wrap; padding: 0.25rem; justify-content: center; }
  .cmd-sep { display: none; }
  .cmd-metric { min-width: 30%; padding: 0.35rem 0.5rem; }
  .dashboard-page { padding: 0.5rem 0.75rem 2rem; }
}

@media (min-width: 769px) and (max-width: 1023px) {
  .row-perf-pos { grid-template-columns: 1fr 1fr; }
}

/* ═══ WebSocket Connection Indicator ═══ */
.ws-indicator {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.65rem;
  font-weight: 600;
  padding: 0.2rem 0.5rem;
  border-radius: 9999px;
  font-family: var(--tp-font);
}
.ws-connected {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}
.ws-disconnected {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}
.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
  animation: ws-pulse 2s ease infinite;
}
@keyframes ws-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.4); }
  50%      { box-shadow: 0 0 0 4px rgba(34, 197, 94, 0); }
}
</style>
