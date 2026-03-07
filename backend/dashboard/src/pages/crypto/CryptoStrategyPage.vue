<script setup>
import { ref } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'

const cryptoLinks = [
  { to: '/crypto', label: 'Dashboard' },
  { to: '/crypto/positions', label: 'Positions' },
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
  <SectionNav :links="cryptoLinks" />
  <h2>Crypto Strategy</h2>

  <div class="grid">
    <article>
      <header>Strategy Configuration</header>
      <label>
        Pairs (comma-separated)
        <input v-model="config.pairs" type="text" />
      </label>
      <label>
        Capital (USD)
        <input v-model.number="config.capital_usd" type="number" step="1" min="0" />
      </label>
      <label>
        Max Positions
        <input v-model.number="config.max_positions" type="number" step="1" min="1" />
      </label>
      <label>
        Leverage
        <input v-model.number="config.leverage" type="number" step="1" min="1" max="20" />
      </label>
      <label>
        Fast MA
        <input v-model.number="config.fast_ma" type="number" step="1" min="5" />
      </label>
      <label>
        Slow MA
        <input v-model.number="config.slow_ma" type="number" step="1" min="10" />
      </label>
      <label>
        Max Position %
        <input v-model.number="config.max_position_pct" type="number" step="0.01" min="0.01" max="1" />
      </label>
      <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
        <button :aria-busy="configLoading" @click="saveConfig" style="margin-bottom: 0;">Save</button>
      </div>
    </article>

    <article>
      <header>Latest Backtest</header>
      <template v-if="latestBacktest">
        <dl>
          <dt>Symbol</dt>
          <dd>{{ latestBacktest.symbol }}</dd>
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
          <dd>{{ fmtDate(latestBacktest.run_time) }}</dd>
        </dl>
      </template>
      <p v-else>No backtest results yet.</p>
    </article>
  </div>

  <div style="margin-bottom: 1.5rem;">
    <button :aria-busy="backtestLoading" @click="runBacktest" style="width: auto;">Run Backtest</button>
  </div>

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
            <th>Symbol</th>
            <th>Side</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>Size</th>
            <th>P&amp;L</th>
            <th>Reason</th>
            <th>Cumulative</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(t, i) in latestBacktest.trades" :key="i">
            <td>{{ i + 1 }}</td>
            <td>{{ t.symbol ?? '-' }}</td>
            <td>{{ t.side ?? '-' }}</td>
            <td>${{ fmt(t.entry_price) }}</td>
            <td>${{ fmt(t.exit_price) }}</td>
            <td>{{ fmt(t.size) }}</td>
            <td>
              <strong :style="{ color: Number(t.pnl ?? 0) >= 0 ? 'var(--ins-color)' : 'var(--del-color)' }">
                ${{ fmt(t.pnl) }}
              </strong>
            </td>
            <td>{{ t.reason ?? '-' }}</td>
            <td>${{ fmt(t.cumulative_pnl) }}</td>
          </tr>
        </tbody>
      </table>
    </figure>
  </article>

  <article v-if="backtests.length">
    <header>Backtest History</header>
    <figure>
      <table>
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
            <td>{{ fmtDate(bt.run_time) }}</td>
            <td>{{ bt.symbol }}</td>
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
