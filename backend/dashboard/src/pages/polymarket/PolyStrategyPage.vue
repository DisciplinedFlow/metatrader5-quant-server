<script setup>
import { ref } from 'vue'
import { usePolling } from '@/composables/usePolling'
import SectionNav from '@/components/SectionNav.vue'
import api from '@/services/api'

const polyLinks = [
  { to: '/polymarket', label: 'Dashboard' },
  { to: '/polymarket/markets', label: 'Markets' },
  { to: '/polymarket/positions', label: 'Positions' },
  { to: '/polymarket/strategy', label: 'Strategy' },
]

const config = ref({
  ev_threshold: 0.05,
  kelly_fraction: 0.15,
  max_positions: 5,
  capital_usd: 500,
  stop_loss_threshold: 0.15,
})
const configLoading = ref(false)
const backtestLoading = ref(false)
const latestBacktest = ref(null)
const backtests = ref([])
const showTrades = ref(false)

async function refresh() {
  const [configResult, backtestsResult] = await Promise.allSettled([
    api.getPolymarketStrategyConfig(),
    api.getPolymarketBacktests(),
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
    await api.updatePolymarketStrategyConfig(config.value)
  } catch (err) {
    console.error('Config save error:', err)
  }
  configLoading.value = false
}

async function runBacktest() {
  backtestLoading.value = true
  try {
    await api.runPolymarketBacktest()
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
  <SectionNav :links="polyLinks" />
  <h2>Polymarket Strategy</h2>

  <div class="grid">
    <!-- Strategy Configuration -->
    <article>
      <header>Strategy Configuration</header>
      <label>
        EV Threshold
        <input v-model.number="config.ev_threshold" type="number" step="0.01" min="0" />
      </label>
      <label>
        Kelly Fraction
        <input v-model.number="config.kelly_fraction" type="number" step="0.01" min="0" max="1" />
      </label>
      <label>
        Max Positions
        <input v-model.number="config.max_positions" type="number" step="1" min="1" />
      </label>
      <label>
        Capital (USD)
        <input v-model.number="config.capital_usd" type="number" step="1" min="0" />
      </label>
      <label>
        Stop Loss Threshold
        <input v-model.number="config.stop_loss_threshold" type="number" step="0.01" min="0" max="1" />
      </label>
      <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
        <button :aria-busy="configLoading" @click="saveConfig" style="margin-bottom: 0;">Save</button>
      </div>
    </article>

    <!-- Latest Backtest Result -->
    <article>
      <header>Latest Backtest</header>
      <template v-if="latestBacktest">
        <dl>
          <dt>Status</dt>
          <dd>
            <mark :class="latestBacktest.passed ? '' : 'secondary'">
              {{ latestBacktest.passed ? 'PASS' : 'FAIL' }}
            </mark>
          </dd>
          <dt>Total Trades</dt>
          <dd>{{ latestBacktest.total_trades ?? 'N/A' }}</dd>
          <dt>Win Rate</dt>
          <dd>{{ fmtPct(latestBacktest.win_rate) }}</dd>
          <dt>Winning / Losing</dt>
          <dd>{{ latestBacktest.winning_trades ?? '-' }} / {{ latestBacktest.losing_trades ?? '-' }}</dd>
          <dt>Total P&amp;L</dt>
          <dd>
            <strong :style="{ color: Number(latestBacktest.total_pnl ?? 0) >= 0 ? 'var(--ins-color)' : 'var(--del-color)' }">
              ${{ fmt(latestBacktest.total_pnl) }}
            </strong>
          </dd>
          <dt>Avg Win / Avg Loss</dt>
          <dd>${{ fmt(latestBacktest.avg_win) }} / ${{ fmt(latestBacktest.avg_loss) }}</dd>
          <dt>Profit Factor</dt>
          <dd>{{ fmt(latestBacktest.profit_factor) }}</dd>
          <dt>Max Drawdown</dt>
          <dd>{{ fmtPct(latestBacktest.max_drawdown) }}</dd>
          <dt>Run Time</dt>
          <dd>{{ fmtDate(latestBacktest.created_at ?? latestBacktest.run_time) }}</dd>
        </dl>
      </template>
      <p v-else>No backtest results yet.</p>
    </article>
  </div>

  <!-- Run Backtest -->
  <div style="margin-bottom: 1.5rem;">
    <button :aria-busy="backtestLoading" @click="runBacktest" style="width: auto;">Run Backtest</button>
  </div>

  <!-- Trade Details (expandable) -->
  <article v-if="latestBacktest && latestBacktest.trades && latestBacktest.trades.length">
    <header>
      <label style="cursor: pointer; margin-bottom: 0;">
        <input v-model="showTrades" type="checkbox" role="switch" />
        Trade Details ({{ latestBacktest.trades.length }} trades)
      </label>
    </header>
    <figure v-if="showTrades">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Market</th>
            <th>Side</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>Shares</th>
            <th>P&amp;L</th>
            <th>Cumulative</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(t, i) in latestBacktest.trades" :key="i">
            <td>{{ i + 1 }}</td>
            <td>{{ t.market ?? '-' }}</td>
            <td>{{ t.side ?? '-' }}</td>
            <td>{{ fmt(t.entry_price) }}</td>
            <td>{{ fmt(t.exit_price) }}</td>
            <td>{{ fmt(t.shares) }}</td>
            <td>
              <strong :style="{ color: Number(t.pnl ?? 0) >= 0 ? 'var(--ins-color)' : 'var(--del-color)' }">
                ${{ fmt(t.pnl) }}
              </strong>
            </td>
            <td>${{ fmt(t.cumulative_pnl) }}</td>
          </tr>
        </tbody>
      </table>
    </figure>
  </article>

  <!-- Backtest History -->
  <article v-if="backtests.length">
    <header>Backtest History</header>
    <figure>
      <table>
        <thead>
          <tr>
            <th>Run Time</th>
            <th>Total Trades</th>
            <th>Win Rate</th>
            <th>P&amp;L</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="bt in backtests" :key="bt.id">
            <td>{{ fmtDate(bt.created_at ?? bt.run_time) }}</td>
            <td>{{ bt.total_trades ?? '-' }}</td>
            <td>{{ fmtPct(bt.win_rate) }}</td>
            <td>
              <strong :style="{ color: Number(bt.total_pnl ?? 0) >= 0 ? 'var(--ins-color)' : 'var(--del-color)' }">
                ${{ fmt(bt.total_pnl) }}
              </strong>
            </td>
            <td>
              <mark :class="bt.passed ? '' : 'secondary'">
                {{ bt.passed ? 'PASS' : 'FAIL' }}
              </mark>
            </td>
          </tr>
        </tbody>
      </table>
    </figure>
  </article>
</template>
