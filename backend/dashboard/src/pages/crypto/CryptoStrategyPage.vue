<script setup>
import { ref } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'

const cryptoLinks = [
  { to: '/crypto', label: 'Dashboard' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/logs', label: 'Logs' },
  { to: '/crypto/strategy', label: 'Strategy' },
]

const config = ref({
  pairs: ['BTC', 'ETH', 'SOL'],
  capital_usd: 1000,
  max_positions: 3,
  leverage: 1,
  strategy: 'momentum',
  fast_ma: 50,
  slow_ma: 200,
  lookback: 252,
  max_position_pct: 0.10,
})
const configLoading = ref(false)
const backtestLoading = ref(false)
const latestBacktest = ref(null)
const backtests = ref([])
const showTrades = ref(false)

async function refresh() {
  const [configResult, backtestsResult] = await Promise.allSettled([
    api.getCryptoStrategyConfig(),
    api.getCryptoBacktests(),
  ])
  if (configResult.status === 'fulfilled') {
    config.value = { ...config.value, ...configResult.value }
  }
  if (backtestsResult.status === 'fulfilled') {
    const list = backtestsResult.value.results || backtestsResult.value
    backtests.value = list
    if (list.length > 0) latestBacktest.value = list[0]
  }
}

async function saveConfig() {
  configLoading.value = true
  try {
    await api.updateCryptoStrategyConfig(config.value)
  } catch (err) {
    console.error('Config save error:', err)
  }
  configLoading.value = false
}

async function runBacktest() {
  backtestLoading.value = true
  try {
    await api.runCryptoBacktest()
  } catch (err) {
    console.error('Backtest error:', err)
  }
  backtestLoading.value = false
}

function fmt(val, decimals = 2) {
  return val != null ? Number(val).toFixed(decimals) : 'N/A'
}

function fmtPct(val) {
  return val != null ? (Number(val) * 100).toFixed(1) + '%' : 'N/A'
}

function fmtDate(val) {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

usePolling(refresh, 15000)
</script>

<template>
  <div class="tp-page">
    <SectionNav :links="cryptoLinks" />
    
    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 2rem;">
      <div>
        <h1 style="font-size: 2.25rem; font-weight: 900; letter-spacing: -0.02em;">Crypto Strategy</h1>
        <p style="color: var(--tp-text-muted); margin-top: 0.25rem;">Trading Pro Platform</p>
      </div>
      <div>
        <button class="tp-btn tp-btn-primary" :disabled="backtestLoading" @click="runBacktest">
          <span class="material-symbols-outlined">play_arrow</span>
          Run Backtest
        </button>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; margin-bottom: 1.5rem;">
      <!-- Strategy Configuration -->
      <div class="tp-card" style="padding: 1.5rem;">
        <h3 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 1rem;">Configuration</h3>
        <div style="display: flex; flex-direction: column; gap: 0.75rem;">
          <label class="tp-label">
            Pairs (comma-separated)
            <input class="tp-input" v-model="config.pairs" type="text" />
          </label>
          <label class="tp-label">
            Capital (USD)
            <input class="tp-input" v-model.number="config.capital_usd" type="number" step="1" min="0" />
          </label>
          <label class="tp-label">
            Max Positions
            <input class="tp-input" v-model.number="config.max_positions" type="number" step="1" min="1" />
          </label>
          <label class="tp-label">
            Leverage
            <input class="tp-input" v-model.number="config.leverage" type="number" step="1" min="1" max="20" />
          </label>
          <label class="tp-label">
            Fast MA
            <input class="tp-input" v-model.number="config.fast_ma" type="number" step="1" min="5" />
          </label>
          <label class="tp-label">
            Slow MA
            <input class="tp-input" v-model.number="config.slow_ma" type="number" step="1" min="10" />
          </label>
          <label class="tp-label">
            Max Position %
            <input class="tp-input" v-model.number="config.max_position_pct" type="number" step="0.01" min="0.01" max="1" />
          </label>
        </div>
        <div style="margin-top: 1.25rem;">
          <button class="tp-btn" :class="configLoading ? 'tp-btn-outline' : 'tp-btn-success'" :disabled="configLoading" @click="saveConfig" style="width: 100%;">
            <span class="material-symbols-outlined">save</span>
            Save Config
          </button>
        </div>
      </div>

      <!-- Latest Backtest Result -->
      <div class="tp-card" style="padding: 1.5rem;">
        <h3 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 1rem;">Latest Backtest</h3>
        <div v-if="latestBacktest" style="display: flex; flex-direction: column; gap: 0.75rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--tp-border); padding-bottom: 0.5rem;">
            <span class="tp-label" style="margin: 0;">Symbol</span>
            <span style="font-weight: 600;">{{ latestBacktest.symbol }}</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--tp-border); padding-bottom: 0.5rem;">
            <span class="tp-label" style="margin: 0;">Status</span>
            <span class="tp-badge" :class="latestBacktest.passed ? 'tp-badge-success' : 'tp-badge-danger'">
              {{ latestBacktest.passed ? 'PASS' : 'FAIL' }}
            </span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--tp-border); padding-bottom: 0.5rem;">
            <span class="tp-label" style="margin: 0;">Total Trades</span>
            <span style="font-weight: 600;">{{ latestBacktest.total_trades ?? '0' }}</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--tp-border); padding-bottom: 0.5rem;">
            <span class="tp-label" style="margin: 0;">Win Rate</span>
            <span style="font-weight: 600;">{{ fmtPct(latestBacktest.win_rate) }}</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--tp-border); padding-bottom: 0.5rem;">
            <span class="tp-label" style="margin: 0;">Total P&amp;L</span>
            <span style="font-weight: 700;" :style="{ color: Number(latestBacktest.total_pnl ?? 0) >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
              {{ Number(latestBacktest.total_pnl ?? 0) >= 0 ? '+' : '' }}${{ fmt(latestBacktest.total_pnl) }}
            </span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--tp-border); padding-bottom: 0.5rem;">
            <span class="tp-label" style="margin: 0;">Win / Loss Ratio</span>
            <span style="font-weight: 600; font-size: 0.85rem;">{{ latestBacktest.winning_trades ?? '-' }}W / {{ latestBacktest.losing_trades ?? '-' }}L</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--tp-border); padding-bottom: 0.5rem;">
            <span class="tp-label" style="margin: 0;">Profit Factor</span>
            <span style="font-weight: 600;">{{ fmt(latestBacktest.profit_factor) }}</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--tp-border); padding-bottom: 0.5rem;">
            <span class="tp-label" style="margin: 0;">Max Drawdown</span>
            <span style="font-weight: 600;">{{ fmtPct(latestBacktest.max_drawdown) }}</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span class="tp-label" style="margin: 0;">Run Time</span>
            <span style="font-weight: 500; font-size: 0.8rem; color: var(--tp-text-dim);">{{ fmtDate(latestBacktest.run_time) }}</span>
          </div>
        </div>
        <div v-else style="color: var(--tp-text-dim); font-size: 0.9rem;">
          No backtests available for this strategy.
        </div>
      </div>
    </div>

    <!-- Trade Details -->
    <div v-if="latestBacktest && latestBacktest.trades && latestBacktest.trades.length" class="tp-card" style="margin-bottom: 1.5rem; padding: 0;">
      <div style="padding: 1rem 1.5rem; border-bottom: 1px solid var(--tp-border); display: flex; align-items: center; justify-content: space-between; cursor: pointer; user-select: none;" @click="showTrades = !showTrades">
        <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0;">Trade Details ({{ latestBacktest.trades.length }})</h3>
        <span class="material-symbols-outlined" style="color: var(--tp-text-dim);">
          {{ showTrades ? 'expand_less' : 'expand_more' }}
        </span>
      </div>
      <div v-if="showTrades" style="overflow-x: auto;">
        <table class="tp-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Size</th>
              <th>P&amp;L</th>
              <th>Reason</th>
              <th>Cum. P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(t, i) in latestBacktest.trades" :key="i">
              <td style="color: var(--tp-text-dim); font-size: 0.8rem;">{{ i + 1 }}</td>
              <td style="font-weight: 500;">{{ t.symbol ?? '-' }}</td>
              <td>
                <span class="tp-badge" :class="t.side === 'LONG' ? 'tp-badge-success' : t.side === 'SHORT' ? 'tp-badge-danger' : 'tp-badge-neutral'">
                  {{ t.side ?? '-' }}
                </span>
              </td>
              <td style="font-weight: 500;">${{ fmt(t.entry_price) }}</td>
              <td style="font-weight: 500;">${{ fmt(t.exit_price) }}</td>
              <td style="font-weight: 500;">{{ fmt(t.size) }}</td>
              <td>
                <span style="font-weight: 700;" :style="{ color: Number(t.pnl ?? 0) >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
                  {{ Number(t.pnl ?? 0) >= 0 ? '+' : '' }}${{ fmt(t.pnl) }}
                </span>
              </td>
              <td style="font-size: 0.8rem; color: var(--tp-text-dim);">{{ t.reason ?? '-' }}</td>
              <td style="font-weight: 700;">${{ fmt(t.cumulative_pnl) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Backtest History -->
    <div v-if="backtests.length > 1" class="tp-card" style="padding: 0;">
      <div style="padding: 1rem 1.5rem; border-bottom: 1px solid var(--tp-border);">
        <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0;">Backtest History</h3>
      </div>
      <div style="overflow-x: auto;">
        <table class="tp-table">
          <thead>
            <tr>
              <th>Run Time</th>
              <th>Symbol</th>
              <th>Total Trades</th>
              <th>Win Rate</th>
              <th>P&amp;L</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="bt in backtests" :key="bt.id">
              <td style="font-size: 0.8rem; color: var(--tp-text-dim);">{{ fmtDate(bt.run_time) }}</td>
              <td style="font-weight: 500;">{{ bt.symbol }}</td>
              <td style="font-weight: 500;">{{ bt.total_trades ?? '-' }}</td>
              <td style="font-weight: 500;">{{ fmtPct(bt.win_rate) }}</td>
              <td>
                <span style="font-weight: 700;" :style="{ color: Number(bt.total_pnl ?? 0) >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
                  {{ Number(bt.total_pnl ?? 0) >= 0 ? '+' : '' }}${{ fmt(bt.total_pnl) }}
                </span>
              </td>
              <td>
                <span class="tp-badge" :class="bt.passed ? 'tp-badge-success' : 'tp-badge-danger'">
                  {{ bt.passed ? 'PASS' : 'FAIL' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
