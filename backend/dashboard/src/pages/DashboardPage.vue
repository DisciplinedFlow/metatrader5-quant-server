<script setup>
import { ref } from 'vue'
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
const tick = ref(null)
const tickError = ref(false)
const posError = ref(false)
const botPaused = ref(false)
const botStatusLoading = ref(false)
const marketPulse = ref({ news: [], calendar: [] })

async function refresh() {
  const [posResult, tickResult, botResult] = await Promise.allSettled([
    positionsStore.fetchPositions(),
    api.symbolInfoTick('EURUSD'),
    api.getBotStatus(),
  ])

  posError.value = posResult.status === 'rejected'
  if (tickResult.status === 'fulfilled') {
    tick.value = tickResult.value
    tickError.value = false
  } else {
    tickError.value = true
  }
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

usePolling(refresh, 5000)
usePolling(fetchMarketPulse, 120000)
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

        <!-- Market Tick Card -->
        <div class="tp-card tick-card">
          <div class="tick-bg-accent"></div>
          <div class="tick-header">
            <div class="tick-pair">
              <div class="pair-icons">
                <div class="pair-icon"><span class="material-symbols-outlined" style="font-size:14px">euro</span></div>
                <div class="pair-icon pair-icon-2"><span class="material-symbols-outlined" style="font-size:14px">attach_money</span></div>
              </div>
              <div>
                <h4 class="pair-name">EURUSD</h4>
                <p class="pair-desc">Euro / US Dollar</p>
              </div>
            </div>
            <span class="tp-badge tp-badge-success" style="font-size:0.6rem">
              <span class="pulse-dot"></span> LIVE
            </span>
          </div>

          <template v-if="tick && !tickError">
            <!-- Bid / Ask -->
            <div class="bid-ask-row">
              <div>
                <p class="micro-label">Bid</p>
                <p class="tick-price">{{ tick.bid }}</p>
              </div>
              <div style="text-align:right">
                <p class="micro-label">Ask</p>
                <p class="tick-price">{{ tick.ask }}</p>
              </div>
            </div>

            <!-- Spread / Last -->
            <div class="tick-details">
              <div class="tick-detail-row">
                <span>Spread</span>
                <span class="tick-detail-value">{{ ((tick.ask - tick.bid) * 100000).toFixed(1) }} pips</span>
              </div>
              <div class="tick-detail-row">
                <span>Last Trade</span>
                <span class="tick-detail-value">{{ tick.last || 'N/A' }}</span>
              </div>
            </div>

            <!-- Mini Chart Visual -->
            <div class="mini-chart">
              <div class="mini-chart-grid"></div>
              <svg class="mini-chart-line" preserveAspectRatio="none" viewBox="0 0 100 20">
                <path d="M0 20 L0 15 Q 10 5, 20 12 T 40 8 T 60 14 T 80 5 T 100 12 L 100 20 Z" fill="currentColor" fill-opacity="0.1" stroke="currentColor" stroke-width="0.5"></path>
              </svg>
            </div>

            <!-- Buy / Sell Buttons -->
            <div class="trade-btns">
              <button class="tp-btn tp-btn-success trade-btn" @click="router.push('/forex/order')">BUY</button>
              <button class="tp-btn tp-btn-danger trade-btn" @click="router.push('/forex/order')">SELL</button>
            </div>
          </template>

          <div v-else-if="tickError" class="tick-error">
            <span class="material-symbols-outlined" style="font-size:2rem;color:var(--tp-text-dim)">signal_wifi_off</span>
            <p>Failed to load market data</p>
          </div>
          <div v-else class="tick-loading">
            <p style="color:var(--tp-text-dim);font-size:0.85rem;">Loading tick data...</p>
          </div>
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

/* ===== Right Column: Tick Card ===== */
.tick-card {
  padding: 1.5rem;
  position: relative;
  overflow: hidden;
}
.tick-bg-accent {
  position: absolute;
  top: -3rem; right: -3rem;
  width: 8rem; height: 8rem;
  background: rgba(13,127,242,0.05);
  border-radius: 50%;
  filter: blur(40px);
  pointer-events: none;
}
.tick-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
  position: relative;
}
.tick-pair {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.pair-icons {
  display: flex;
  position: relative;
}
.pair-icon {
  width: 2rem; height: 2rem;
  border-radius: 50%;
  background: var(--tp-bg-surface);
  border: 2px solid var(--tp-bg-dark);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--tp-text);
}
.pair-icon-2 {
  margin-left: -0.5rem;
}
.pair-name {
  font-size: 1rem;
  font-weight: 800;
  color: var(--tp-text);
  margin: 0;
  line-height: 1.2;
}
.pair-desc {
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 600;
  color: var(--tp-text-dim) !important;
  margin: 0;
}

/* Bid/Ask */
.bid-ask-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-bottom: 1rem;
}
.tick-price {
  font-size: 1.35rem;
  font-weight: 800;
  color: var(--tp-text);
  margin: 0;
  font-family: 'Inter', monospace;
  letter-spacing: -0.01em;
}

/* Tick Details */
.tick-details {
  border-top: 1px solid var(--tp-border);
  padding-top: 0.75rem;
  margin-bottom: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.tick-detail-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  color: var(--tp-text-dim);
}
.tick-detail-value {
  font-weight: 700;
  color: var(--tp-text);
  font-family: 'Inter', monospace;
}

/* Mini Chart */
.mini-chart {
  height: 5rem;
  width: 100%;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  overflow: hidden;
  position: relative;
  margin-bottom: 1rem;
}
.mini-chart-grid {
  position: absolute;
  inset: 0;
  opacity: 0.15;
  background-image:
    linear-gradient(90deg, transparent 49%, var(--tp-primary) 50%, transparent 51%),
    linear-gradient(0deg, transparent 49%, var(--tp-primary) 50%, transparent 51%);
  background-size: 20px 20px;
}
.mini-chart-line {
  position: absolute;
  bottom: 0;
  width: 100%;
  height: 3.5rem;
  color: var(--tp-primary);
}

/* Trade Buttons */
.trade-btns {
  display: flex;
  gap: 0.75rem;
}
.trade-btn {
  flex: 1;
  height: 2.5rem;
  font-size: 0.85rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}

/* Tick error/loading */
.tick-error, .tick-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 2rem 1rem;
  text-align: center;
  color: var(--tp-text-dim);
  font-size: 0.85rem;
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
