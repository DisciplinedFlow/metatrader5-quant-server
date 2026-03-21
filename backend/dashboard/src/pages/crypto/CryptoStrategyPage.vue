<script setup>
import { ref, computed } from 'vue'
import { usePolling } from '@/composables/usePolling'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'
import { cryptoLinks, fmt } from '@/utils/cryptoConstants'

const toast = useToast()

// ── Strategy definitions (mirrors the actual Celery tasks) ──
const STRATEGIES = [
  {
    key: 'rsi2_scalper',
    task: 'run_lighter_rsi_scalper',
    name: 'RSI(2) Scalper',
    desc: 'Ultra-fast mean reversion — RSI(2) oversold/overbought with EMA(50) trend filter. 20-50 trades/day.',
    icon: 'bolt',
    color: '#f59e0b',
    interval: '30s',
    type: 'entry',
    signals: ['rsi2_validated', 'rsi2_buy_rsi15_emaup', 'rsi2_sell_rsi100_emadown', 'rsi2_sell_rsi88_emadown'],
  },
  {
    key: 'ema_crossover',
    task: 'run_lighter_entry',
    name: 'EMA Crossover',
    desc: 'Multi-timeframe EMA momentum — 1h crossover for trend, 15m RSI pullback for timing. Per-symbol validated params.',
    icon: 'stacked_line_chart',
    color: '#8b5cf6',
    interval: '60s',
    type: 'entry',
    signals: ['crossover_confirmed_ema_'],
  },
  {
    key: 'mean_reversion',
    task: 'run_lighter_mean_reversion',
    name: 'BB Mean Reversion',
    desc: 'Bollinger Bands(14, 3σ) + RSI(14) + ADX < 35 range filter. Liquidation cascade boost. 85-89% backtest WR.',
    icon: 'swap_vert',
    color: '#3b82f6',
    interval: '5m',
    type: 'entry',
    signals: ['mean_reversion', 'bb_reversal'],
  },
  {
    key: 'cvd_main',
    task: 'run_crypto_entry',
    name: 'H4/H1 CVD Entry',
    desc: 'Multi-timeframe structure — H4 bias + H1 CVD divergence + real-time order book filter. Core alpha strategy.',
    icon: 'query_stats',
    color: '#22c55e',
    interval: '60s',
    type: 'entry',
    signals: ['h4_h1_cvd', 'cvd_lop', 'cvd_absorption'],
  },
  {
    key: 'funding_arb',
    task: 'run_funding_arb_scan',
    name: 'Funding Arb Scout',
    desc: 'Scans funding rate spreads across exchanges for arbitrage signals. Monitor-only, no auto-execution.',
    icon: 'search_insights',
    color: '#06b6d4',
    interval: '5m',
    type: 'monitor',
    signals: [],
  },
  {
    key: 'cvd_lighter',
    task: 'run_lighter_cvd',
    name: 'CVD Divergence (Lighter)',
    desc: 'Binance CVD proxy for Lighter entries. DISABLED — 7.8% live WR, failed backtest validation Mar 20.',
    icon: 'show_chart',
    color: '#6b7280',
    interval: '60s',
    type: 'entry',
    disabled: true,
    signals: [],
  },
  {
    key: 'momentum_lighter',
    task: 'run_lighter_momentum',
    name: 'EMA Momentum (Lighter)',
    desc: 'Trend-following pullback entries. DISABLED — failed backtest validation Mar 20.',
    icon: 'trending_up',
    color: '#6b7280',
    interval: '60s',
    type: 'entry',
    disabled: true,
    signals: [],
  },
]

// ── State ──
const botPaused = ref(false)
const botStatusLoading = ref(false)
const mlData = ref(null)
const showDisabled = ref(false)

const activeStrategies = computed(() => STRATEGIES.filter(s => !s.disabled))
const disabledStrategies = computed(() => STRATEGIES.filter(s => s.disabled))
const displayStrategies = computed(() => showDisabled.value ? STRATEGIES : activeStrategies.value)

// ── Live performance from ML stats API ──
// API returns: { training: { total, wins, losses, win_rate, net_pnl, avg_duration_min, by_strategy: { "lighter:rsi2_validated": { wins, losses, pnl }, ... } } }
function strategyStats(strategy) {
  if (!mlData.value?.training?.by_strategy) return { trades: 0, wins: 0, losses: 0, winRate: 0, pnl: 0, avgDuration: 0 }
  const byStrat = mlData.value.training.by_strategy
  let wins = 0, losses = 0, pnl = 0
  for (const [key, val] of Object.entries(byStrat)) {
    if (strategy.signals.some(s => key.includes(s))) {
      wins += val.wins || 0
      losses += val.losses || 0
      pnl += val.pnl || 0
    }
  }
  const total = wins + losses
  return {
    trades: total,
    wins,
    losses,
    winRate: total ? (wins / total * 100) : 0,
    pnl,
    avgDuration: mlData.value.training.avg_duration_min || 0,
  }
}

const totalStats = computed(() => {
  const t = mlData.value?.training
  if (!t) return { trades: 0, wins: 0, winRate: 0, pnl: 0 }
  return {
    trades: t.total || 0,
    wins: t.wins || 0,
    winRate: t.win_rate || 0,
    pnl: t.net_pnl || 0,
  }
})

// ── API ──
async function refresh() {
  const [botResult, mlResult] = await Promise.allSettled([
    api.getCryptoBotStatus(),
    api.getCryptoMLStats(),
  ])
  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }
  if (mlResult.status === 'fulfilled') {
    mlData.value = mlResult.value
  }
}

async function toggleBot() {
  botStatusLoading.value = true
  try {
    const resp = await api.setCryptoBotPaused(!botPaused.value)
    botPaused.value = resp.paused
    toast.success(botPaused.value ? 'Bot paused' : 'Bot resumed')
  } catch (err) {
    toast.error(`Bot toggle failed: ${err.message}`)
  }
  botStatusLoading.value = false
}

usePolling(refresh, 60000)  // was 15s — bot gets API priority
</script>

<template>
  <SectionNav :links="cryptoLinks" />
  <div class="tp-page strat-page">

    <!-- Header -->
    <div class="strat-header">
      <div>
        <h1 class="strat-title">Strategy Engine</h1>
        <p class="strat-subtitle">{{ activeStrategies.length }} active strategies &middot; {{ disabledStrategies.length }} disabled</p>
      </div>
      <div class="header-controls">
        <label class="toggle-label">
          <input v-model="showDisabled" type="checkbox" role="switch" />
          Show disabled
        </label>
        <button
          class="bot-toggle-btn"
          :class="botPaused ? 'bot-paused' : 'bot-running'"
          :aria-busy="botStatusLoading"
          @click="toggleBot"
        >
          <span class="material-symbols-outlined" style="font-size:18px">{{ botPaused ? 'play_arrow' : 'pause' }}</span>
          {{ botPaused ? 'Resume' : 'Pause' }}
        </button>
      </div>
    </div>

    <!-- Bot Status Indicator -->
    <div class="bot-status-strip" :class="botPaused ? 'strip-paused' : 'strip-running'">
      <div class="strip-dot" :class="botPaused ? 'dot-paused' : 'dot-running'"></div>
      <span>{{ botPaused ? 'Entry algorithms paused — exit & reconciliation still active' : 'All strategies operational' }}</span>
    </div>

    <!-- Aggregate Stats -->
    <div class="agg-stats">
      <div class="agg-stat">
        <div class="agg-value">{{ totalStats.trades }}</div>
        <div class="agg-label">Total Trades</div>
      </div>
      <div class="agg-divider"></div>
      <div class="agg-stat">
        <div class="agg-value" :class="totalStats.winRate >= 60 ? 'val-green' : totalStats.winRate >= 40 ? 'val-amber' : 'val-red'">
          {{ fmt(totalStats.winRate, 1) }}%
        </div>
        <div class="agg-label">Win Rate</div>
      </div>
      <div class="agg-divider"></div>
      <div class="agg-stat">
        <div class="agg-value" :class="totalStats.pnl >= 0 ? 'val-green' : 'val-red'">
          {{ totalStats.pnl >= 0 ? '+' : '' }}${{ fmt(totalStats.pnl) }}
        </div>
        <div class="agg-label">Net P&L</div>
      </div>
      <div class="agg-divider"></div>
      <div class="agg-stat">
        <div class="agg-value">{{ totalStats.wins }}<span class="agg-sep">/</span>{{ totalStats.trades - totalStats.wins }}</div>
        <div class="agg-label">W / L</div>
      </div>
    </div>

    <!-- Strategy Cards -->
    <div class="strat-grid">
      <div
        v-for="s in displayStrategies"
        :key="s.key"
        class="strat-card"
        :class="{ 'card-disabled': s.disabled }"
      >
        <!-- Card Header -->
        <div class="card-head">
          <div class="card-icon" :style="{ background: s.color + '18', color: s.color }">
            <span class="material-symbols-outlined">{{ s.icon }}</span>
          </div>
          <div class="card-meta">
            <h3 class="card-name">{{ s.name }}</h3>
            <div class="card-badges">
              <span class="badge-interval">{{ s.interval }}</span>
              <span class="badge-type" :class="'type-' + s.type">{{ s.type }}</span>
              <span v-if="s.disabled" class="badge-disabled">disabled</span>
              <span v-else class="badge-active">
                <span class="live-dot"></span>live
              </span>
            </div>
          </div>
        </div>

        <!-- Description -->
        <p class="card-desc">{{ s.desc }}</p>

        <!-- Performance Stats (only for strategies with signal data) -->
        <div v-if="!s.disabled && s.signals.length" class="card-perf">
          <div class="perf-stat">
            <div class="perf-value">{{ strategyStats(s).trades }}</div>
            <div class="perf-label">trades</div>
          </div>
          <div class="perf-stat">
            <div class="perf-value" :class="strategyStats(s).winRate >= 60 ? 'val-green' : strategyStats(s).winRate >= 40 ? 'val-amber' : strategyStats(s).trades ? 'val-red' : ''">
              {{ strategyStats(s).trades ? fmt(strategyStats(s).winRate, 1) + '%' : '-' }}
            </div>
            <div class="perf-label">win rate</div>
          </div>
          <div class="perf-stat">
            <div class="perf-value" :class="strategyStats(s).pnl >= 0 ? 'val-green' : 'val-red'">
              {{ strategyStats(s).trades ? (strategyStats(s).pnl >= 0 ? '+' : '') + '$' + fmt(strategyStats(s).pnl) : '-' }}
            </div>
            <div class="perf-label">P&L</div>
          </div>
          <div class="perf-stat">
            <div class="perf-value">{{ strategyStats(s).trades ? fmt(strategyStats(s).avgDuration, 0) + 'm' : '-' }}</div>
            <div class="perf-label">avg hold</div>
          </div>
        </div>

        <!-- Win/Loss Bar -->
        <div v-if="!s.disabled && strategyStats(s).trades > 0" class="wl-bar-container">
          <div class="wl-bar">
            <div class="wl-wins" :style="{ width: strategyStats(s).winRate + '%' }"></div>
          </div>
          <div class="wl-labels">
            <span class="wl-w">{{ strategyStats(s).wins }}W</span>
            <span class="wl-l">{{ strategyStats(s).losses }}L</span>
          </div>
        </div>

        <!-- No data state -->
        <div v-else-if="!s.disabled && !strategyStats(s).trades" class="card-nodata">
          <span class="material-symbols-outlined" style="font-size:16px;opacity:0.4">hourglass_empty</span>
          <span>Collecting data</span>
        </div>
      </div>
    </div>

    <!-- Infrastructure Section -->
    <div class="infra-section">
      <h2 class="infra-title">Infrastructure</h2>
      <div class="infra-grid">
        <div class="infra-card">
          <div class="infra-icon">
            <span class="material-symbols-outlined">shield</span>
          </div>
          <div>
            <h4>Exit Manager</h4>
            <p>SL/TP + trailing every 15s. Runs when paused.</p>
          </div>
          <span class="badge-active"><span class="live-dot"></span>live</span>
        </div>
        <div class="infra-card">
          <div class="infra-icon">
            <span class="material-symbols-outlined">sync</span>
          </div>
          <div>
            <h4>Reconciler</h4>
            <p>DB ↔ exchange sync every 60s. Runs when paused.</p>
          </div>
          <span class="badge-active"><span class="live-dot"></span>live</span>
        </div>
        <div class="infra-card">
          <div class="infra-icon">
            <span class="material-symbols-outlined">cell_tower</span>
          </div>
          <div>
            <h4>WS Streamer</h4>
            <p>Real-time orderbook + trades for BTC, ETH, SOL, XAU.</p>
          </div>
          <span class="badge-active"><span class="live-dot"></span>live</span>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.strat-page {
  padding: 1.5rem;
  max-width: 1100px;
  margin: 0 auto;
}

/* ── Header ── */
.strat-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1rem;
}
.strat-title {
  font-size: 1.5rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  margin: 0 0 0.2rem;
}
.strat-subtitle {
  font-size: 0.8rem;
  color: var(--tp-text-dim);
  margin: 0;
}
.header-controls {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.toggle-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--tp-text-dim);
  font-size: 0.8rem;
  cursor: pointer;
}
.toggle-label input { margin: 0; }

.bot-toggle-btn {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 1rem;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 700;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
}
.bot-paused {
  background: #22c55e;
  color: #fff;
}
.bot-paused:hover { background: #16a34a; }
.bot-running {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.3);
}
.bot-running:hover { background: rgba(239, 68, 68, 0.25); }

/* ── Status Strip ── */
.bot-status-strip {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  font-size: 0.78rem;
  font-weight: 500;
  margin-bottom: 1.25rem;
}
.strip-paused {
  background: rgba(251, 191, 36, 0.08);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.2);
}
.strip-running {
  background: rgba(34, 197, 94, 0.06);
  color: #34d399;
  border: 1px solid rgba(34, 197, 94, 0.15);
}
.strip-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-paused { background: #fbbf24; }
.dot-running {
  background: #22c55e;
  animation: pulse-dot 2s ease-in-out infinite;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.5); }
  50% { opacity: 0.7; box-shadow: 0 0 0 6px rgba(34, 197, 94, 0); }
}

/* ── Aggregate Stats ── */
.agg-stats {
  display: flex;
  align-items: center;
  gap: 0;
  background: var(--tp-bg-glass);
  border: var(--tp-glass-border);
  border-radius: var(--tp-radius);
  padding: 0.75rem 0;
  margin-bottom: 1.5rem;
  backdrop-filter: var(--tp-glass-blur);
}
.agg-stat {
  flex: 1;
  text-align: center;
}
.agg-value {
  font-size: 1.3rem;
  font-weight: 800;
  font-feature-settings: 'tnum' 1;
  letter-spacing: -0.02em;
}
.agg-sep {
  font-weight: 400;
  opacity: 0.4;
  margin: 0 0.1rem;
}
.agg-label {
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 700;
  color: var(--tp-text-dim);
  margin-top: 0.1rem;
}
.agg-divider {
  width: 1px;
  height: 2.2rem;
  background: var(--tp-border);
  flex-shrink: 0;
}

/* ── Strategy Grid ── */
.strat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}

.strat-card {
  background: var(--tp-bg-glass);
  border: var(--tp-glass-border);
  border-radius: var(--tp-radius);
  padding: 1.25rem;
  backdrop-filter: var(--tp-glass-blur);
  transition: border-color 0.2s, transform 0.15s;
}
.strat-card:hover {
  border-color: var(--tp-border-light);
  transform: translateY(-1px);
}
.card-disabled {
  opacity: 0.45;
}
.card-disabled:hover {
  opacity: 0.55;
  transform: none;
}

/* Card header */
.card-head {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.card-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.card-icon .material-symbols-outlined {
  font-size: 22px;
}
.card-meta {
  min-width: 0;
}
.card-name {
  font-size: 0.95rem;
  font-weight: 700;
  margin: 0 0 0.25rem;
  letter-spacing: -0.01em;
}
.card-badges {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.badge-interval,
.badge-type,
.badge-disabled,
.badge-active {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.1rem 0.45rem;
  border-radius: 4px;
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.badge-interval {
  background: rgba(255, 255, 255, 0.06);
  color: var(--tp-text-dim);
}
.type-entry {
  background: rgba(139, 92, 246, 0.12);
  color: #a78bfa;
}
.type-monitor {
  background: rgba(6, 182, 212, 0.12);
  color: #22d3ee;
}
.badge-disabled {
  background: rgba(239, 68, 68, 0.1);
  color: #f87171;
}
.badge-active {
  background: rgba(34, 197, 94, 0.1);
  color: #34d399;
}
.live-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse-dot 2s ease-in-out infinite;
}

/* Description */
.card-desc {
  font-size: 0.76rem;
  color: var(--tp-text-muted);
  line-height: 1.5;
  margin: 0 0 1rem;
}

/* Performance stats */
.card-perf {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.25rem;
  padding: 0.65rem 0;
  border-top: 1px solid var(--tp-border);
}
.perf-stat {
  text-align: center;
}
.perf-value {
  font-size: 0.9rem;
  font-weight: 800;
  font-feature-settings: 'tnum' 1;
}
.perf-label {
  font-size: 0.55rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--tp-text-dim);
  font-weight: 600;
  margin-top: 0.1rem;
}

/* Win/Loss bar */
.wl-bar-container {
  margin-top: 0.6rem;
}
.wl-bar {
  height: 4px;
  border-radius: 2px;
  background: rgba(239, 68, 68, 0.3);
  overflow: hidden;
}
.wl-wins {
  height: 100%;
  background: #22c55e;
  border-radius: 2px;
  transition: width 0.3s;
}
.wl-labels {
  display: flex;
  justify-content: space-between;
  font-size: 0.6rem;
  font-weight: 700;
  margin-top: 0.2rem;
}
.wl-w { color: #22c55e; }
.wl-l { color: #ef4444; }

/* No data */
.card-nodata {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.65rem 0;
  border-top: 1px solid var(--tp-border);
  font-size: 0.75rem;
  color: var(--tp-text-dim);
}

/* ── Infrastructure ── */
.infra-section {
  margin-top: 1rem;
}
.infra-title {
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--tp-text-dim);
  margin: 0 0 0.75rem;
}
.infra-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
}
.infra-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: var(--tp-bg-glass);
  border: var(--tp-glass-border);
  border-radius: var(--tp-radius-sm);
  padding: 0.85rem 1rem;
  backdrop-filter: var(--tp-glass-blur);
}
.infra-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--tp-text-dim);
}
.infra-icon .material-symbols-outlined {
  font-size: 18px;
}
.infra-card h4 {
  font-size: 0.8rem;
  font-weight: 700;
  margin: 0;
}
.infra-card p {
  font-size: 0.68rem;
  color: var(--tp-text-dim);
  margin: 0.15rem 0 0;
  line-height: 1.4;
}
.infra-card .badge-active {
  margin-left: auto;
  flex-shrink: 0;
}

/* ── Color utilities ── */
.val-green { color: #22c55e; }
.val-amber { color: #fbbf24; }
.val-red { color: #ef4444; }

/* ── Responsive ── */
@media (max-width: 768px) {
  .strat-header { flex-direction: column; gap: 1rem; }
  .strat-grid { grid-template-columns: 1fr; }
  .infra-grid { grid-template-columns: 1fr; }
  .agg-stats { flex-wrap: wrap; }
  .agg-divider { display: none; }
  .agg-stat { min-width: 50%; padding: 0.5rem 0; }
}
</style>
