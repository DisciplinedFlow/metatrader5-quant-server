<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { usePositionsStore } from '@/stores/positions'
import { usePolling } from '@/composables/usePolling'
import PositionsTable from '@/components/PositionsTable.vue'
import MarketSessions from '@/components/MarketSessions.vue'
import SectionNav from '@/components/SectionNav.vue'
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
  const winRate = ct.length ? (wins.length / ct.length * 100) : 0
  const bestTrade = ct.length ? Math.max(...ct.map(t => t.pnl)) : 0
  const worstTrade = ct.length ? Math.min(...ct.map(t => t.pnl)) : 0
  return { total: ct.length, wins: wins.length, losses: losses.length, totalPnl, winRate, bestTrade, worstTrade }
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

onMounted(fetchTrades)
usePolling(refresh, 5000)
usePolling(fetchMarketPulse, 120000)
usePolling(fetchTrades, 30000)
</script>

<template>
  <SectionNav :links="forexLinks" />
  <div class="tp-page dashboard-page">
    <div class="dash-grid">

      <!-- ===== LEFT COLUMN ===== -->
      <div class="left-col">

        <!-- Bot Status + Positions Stats row -->
        <div class="top-row">
          <!-- Bot Status Card -->
          <div class="tp-card bot-card">
            <div class="bot-header">
              <div class="bot-label-row">
                <div class="bot-icon" :class="botPaused ? 'bot-icon-paused' : 'bot-icon-running'">
                  <span class="material-symbols-outlined">smart_toy</span>
                </div>
                <div>
                  <p class="micro-label">Bot Status</p>
                  <div class="bot-status-row">
                    <span class="status-dot" :class="botPaused ? 'dot-paused' : 'dot-running'"></span>
                    <p class="bot-status-text">{{ botPaused ? 'PAUSED' : 'RUNNING' }}</p>
                  </div>
                </div>
              </div>
              <button
                class="tp-btn tp-btn-outline"
                :aria-busy="botStatusLoading"
                @click="toggleBot"
              >
                <span class="material-symbols-outlined" style="font-size:16px">{{ botPaused ? 'play_arrow' : 'pause' }}</span>
                {{ botPaused ? 'Resume Bot' : 'Pause Bot' }}
              </button>
            </div>
          </div>

          <!-- Positions Stats Card -->
          <div class="tp-card stats-row-card" v-if="!posError">
            <div class="mini-stat">
              <p class="micro-label">Count</p>
              <p class="mini-stat-value">{{ positionsStore.positions.length }}</p>
            </div>
            <div class="mini-stat">
              <p class="micro-label">Total Profit</p>
              <p class="mini-stat-value" :class="positionsStore.totalProfit >= 0 ? 'text-success' : 'text-danger'">
                ${{ positionsStore.totalProfit.toFixed(2) }}
              </p>
            </div>
            <div class="mini-stat">
              <p class="micro-label">Total Swap</p>
              <p class="mini-stat-value">${{ positionsStore.totalSwap.toFixed(2) }}</p>
            </div>
          </div>
          <div v-else class="tp-card stats-row-card">
            <p style="color:var(--tp-text-dim);font-size:0.85rem;padding:1rem;">Failed to load positions</p>
          </div>
        </div>

        <!-- Market Sessions -->
        <div class="tp-card sessions-card">
          <div class="sessions-header">
            <h3>
              <span class="material-symbols-outlined" style="color:var(--tp-primary);font-size:20px">schedule</span>
              Market Trading Sessions
            </h3>
            <div class="legend">
              <span class="legend-item"><span class="legend-dot dot-running"></span> Open</span>
              <span class="legend-item"><span class="legend-dot" style="background:var(--tp-border-light)"></span> Closed</span>
            </div>
          </div>
          <MarketSessions />
        </div>

        <!-- Active Positions -->
        <div class="tp-card positions-card">
          <div class="positions-header">
            <h3>Active Positions</h3>
            <button class="view-history-btn" @click="router.push('/forex/history')">View History</button>
          </div>
          <div class="positions-body">
            <template v-if="positionsStore.positions.length > 0">
              <PositionsTable :positions="positionsStore.positions" />
            </template>
            <div v-else class="empty-positions">
              <div class="empty-icon">
                <span class="material-symbols-outlined" style="font-size:2rem;color:var(--tp-text-dim)">view_list</span>
              </div>
              <p class="empty-title">No open positions</p>
              <p class="empty-desc">Your active trades will appear here once executed.</p>
              <button class="tp-btn tp-btn-primary" style="margin-top:0.75rem;" @click="router.push('/forex/order')">
                <span class="material-symbols-outlined" style="font-size:16px">add_circle</span>
                Trade Now
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== RIGHT COLUMN ===== -->
      <div class="right-col">

        <!-- P&L Performance Card -->
        <div class="tp-card pnl-card">
          <div class="pnl-header">
            <div>
              <h3 class="pnl-title">Performance</h3>
              <p class="pnl-subtitle">{{ pnlStats.total }} trades</p>
            </div>
            <div class="pnl-total" :class="pnlStats.totalPnl >= 0 ? 'text-success' : 'text-danger'">
              {{ pnlStats.totalPnl >= 0 ? '+' : '' }}${{ pnlStats.totalPnl.toFixed(2) }}
            </div>
          </div>

          <!-- Equity Curve -->
          <div class="equity-chart" v-if="equityCurve.length >= 2">
            <svg viewBox="0 0 280 80" preserveAspectRatio="none" class="equity-svg">
              <line x1="4" :y1="zeroLineY" x2="276" :y2="zeroLineY" stroke="var(--tp-border)" stroke-width="0.5" stroke-dasharray="4 2" />
              <path :d="chartFill" :fill="pnlStats.totalPnl >= 0 ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)'" />
              <path :d="chartPath" fill="none" :stroke="pnlStats.totalPnl >= 0 ? '#22c55e' : '#ef4444'" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
          <div v-else class="equity-empty">
            <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">show_chart</span>
            <p>Waiting for closed trades...</p>
          </div>

          <!-- Trade Bars -->
          <div class="trade-bars" v-if="closedTrades.length">
            <div v-for="(t, i) in closedTrades.slice(-20)" :key="i"
                 class="trade-bar"
                 :class="t.pnl >= 0 ? 'bar-win' : 'bar-loss'"
                 :style="{ height: Math.min(100, Math.max(8, Math.abs(t.pnl) * 3)) + '%' }"
                 :title="`${t.symbol} ${t.pnl >= 0 ? '+' : ''}$${t.pnl.toFixed(2)}`"
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
          </div>

          <button class="tp-btn tp-btn-outline pnl-history-btn" @click="router.push('/forex/history')">
            <span class="material-symbols-outlined" style="font-size:16px">history</span>
            View Full History
          </button>
        </div>

        <!-- Market Pulse / News Card -->
        <div class="tp-card news-card">
          <div class="news-header">
            <h3>Market Pulse</h3>
            <span class="material-symbols-outlined" style="font-size:20px;color:var(--tp-text-dim)">rss_feed</span>
          </div>
          <div class="news-list">
            <!-- Economic Calendar Events -->
            <div v-for="event in marketPulse.calendar.slice(0, 3)" :key="'cal-' + event.event"
                 class="news-item" :class="{ 'news-item-featured': event.impact === 'high' || event.impact === 3 }">
              <p class="news-time">{{ event.country || 'ECON' }}</p>
              <p class="news-text">{{ event.event }}</p>
            </div>
            <!-- News Articles -->
            <div v-for="item in marketPulse.news.slice(0, 5)" :key="item.id" class="news-item">
              <p class="news-time">{{ formatNewsTime(item.datetime) }}</p>
              <p class="news-text">
                <a :href="item.url" target="_blank" rel="noopener" class="news-link">{{ item.headline }}</a>
              </p>
            </div>
            <!-- Fallback when no data -->
            <div v-if="!marketPulse.news.length && !marketPulse.calendar.length" class="news-item news-item-featured">
              <p class="news-time">Live</p>
              <p class="news-text">Loading market news...</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-page {
  padding: 1.5rem 1rem 2rem;
}

/* ===== Grid Layout ===== */
.dash-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1.5rem;
}
@media (min-width: 1024px) {
  .dash-grid {
    grid-template-columns: 2fr 1fr;
  }
}
.left-col, .right-col {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* ===== Top Row: Bot + Stats ===== */
.top-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
}
@media (max-width: 768px) {
  .top-row {
    grid-template-columns: 1fr;
  }
}

/* Bot Card */
.bot-card {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.bot-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}
.bot-label-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.bot-icon {
  width: 2.5rem; height: 2.5rem;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.bot-icon-running {
  background: rgba(34,197,94,0.1);
  color: var(--tp-success);
}
.bot-icon-paused {
  background: rgba(245,158,11,0.1);
  color: var(--tp-warning);
}
.micro-label {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 700;
  color: var(--tp-text-dim);
  margin: 0;
}
.bot-status-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.15rem;
}
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-running { background: var(--tp-success); }
.dot-paused { background: var(--tp-warning); }
.bot-status-text {
  font-size: 1.1rem;
  font-weight: 800;
  color: var(--tp-text);
  margin: 0;
}

/* Stats Row Card */
.stats-row-card {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
  padding: 1.25rem;
  align-items: center;
}
.mini-stat {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.mini-stat-value {
  font-size: 1.75rem;
  font-weight: 800;
  color: var(--tp-text);
  margin: 0;
  line-height: 1;
}
.text-success { color: var(--tp-success) !important; }
.text-danger { color: var(--tp-danger) !important; }

/* Sessions Card */
.sessions-card {
  padding: 1.25rem;
}
.sessions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}
.sessions-header h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  font-weight: 700;
}
.legend {
  display: flex;
  gap: 1rem;
  font-size: 0.7rem;
  color: var(--tp-text-dim);
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 0.3rem;
}
.legend-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
}

/* Positions Card */
.positions-card {
  overflow: hidden;
}
.positions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem;
  border-bottom: 1px solid var(--tp-border);
}
.positions-header h3 {
  font-size: 0.95rem;
  font-weight: 700;
}
.view-history-btn {
  background: none;
  border: none;
  color: var(--tp-primary);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  font-family: var(--tp-font);
}
.view-history-btn:hover { text-decoration: underline; }
.positions-body {
  padding: 0;
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
  width: 4rem; height: 4rem;
  border-radius: 50%;
  background: var(--tp-bg-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1rem;
}
.empty-title {
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--tp-text) !important;
  margin-bottom: 0.25rem;
}
.empty-desc {
  font-size: 0.85rem;
  color: var(--tp-text-dim) !important;
}

/* ===== Right Column: P&L Card ===== */
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
  font-size: 0.95rem;
  font-weight: 700;
  margin: 0;
}
.pnl-subtitle {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
  margin: 0.15rem 0 0;
}
.pnl-total {
  font-size: 1.5rem;
  font-weight: 800;
  font-family: 'Inter', monospace;
}

/* Equity Curve */
.equity-chart {
  width: 100%;
  height: 5rem;
  margin-bottom: 0.75rem;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  overflow: hidden;
}
.equity-svg {
  width: 100%;
  height: 100%;
}
.equity-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 1.5rem;
  color: var(--tp-text-dim);
  font-size: 0.8rem;
  text-align: center;
}

/* Trade Bars (mini bar chart of last 20 trades) */
.trade-bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 2.5rem;
  margin-bottom: 0.75rem;
  padding: 0 2px;
}
.trade-bar {
  flex: 1;
  border-radius: 2px 2px 0 0;
  min-height: 3px;
  transition: opacity 0.15s;
  cursor: default;
}
.trade-bar:hover { opacity: 0.7; }
.bar-win { background: #22c55e; }
.bar-loss { background: #ef4444; }

/* Stats Grid */
.pnl-stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.pnl-stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0;
  border-bottom: 1px solid var(--tp-border);
  font-size: 0.78rem;
}
.pnl-stat-label { color: var(--tp-text-dim); }
.pnl-stat-value { font-weight: 700; font-family: 'Inter', monospace; }

.pnl-history-btn {
  width: 100%;
  justify-content: center;
  font-size: 0.8rem;
}

/* ===== News Card ===== */
.news-card {
  padding: 1.25rem;
}
.news-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}
.news-header h3 {
  font-size: 0.95rem;
  font-weight: 700;
}
.news-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.news-item {
  border-left: 2px solid var(--tp-border);
  padding-left: 0.75rem;
  padding: 0.35rem 0 0.35rem 0.75rem;
}
.news-item-featured {
  border-left-color: var(--tp-primary);
}
.news-time {
  font-size: 0.7rem;
  color: var(--tp-text-dim) !important;
  margin-bottom: 0.2rem;
  font-weight: 600;
}
.news-text {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--tp-text) !important;
  line-height: 1.4;
}
.news-link {
  color: var(--tp-text);
  text-decoration: none;
}
.news-link:hover {
  color: var(--tp-primary);
  text-decoration: underline;
}
</style>
