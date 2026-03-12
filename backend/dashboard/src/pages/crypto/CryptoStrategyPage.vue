<script setup>
import { ref } from 'vue'
import { usePolling } from '@/composables/usePolling'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'
import EquityCurveChart from '@/components/charts/EquityCurveChart.vue'
import TradeMarkersChart from '@/components/charts/TradeMarkersChart.vue'
import SymbolBreakdownTable from '@/components/charts/SymbolBreakdownTable.vue'
import BacktestHistoryChart from '@/components/charts/BacktestHistoryChart.vue'
import StrategyBuilder from '@/components/StrategyBuilder.vue'
import StrategyLibrary from '@/components/StrategyLibrary.vue'

const cryptoLinks = [
  { to: '/crypto', label: 'Overview' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/history', label: 'History' },
  { to: '/crypto/chart', label: 'Chart' },
  { to: '/crypto/logs', label: 'Logs' },
  { to: '/crypto/strategy', label: 'Strategies' },
]

const toast = useToast()

// Active strategy state
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
const latestBacktest = ref(null)
const backtests = ref([])

// Custom strategy state
const customStrategies = ref([])
const loadingBtn = ref({})
const detailData = ref({})
const historyData = ref({})
const activeTab = ref({})
const showBuilder = ref(false)

// Bot control
const botPaused = ref(false)
const botStatusLoading = ref(false)

// Page tab
const pageTab = ref('active')

// Chart tab for active strategy
const activeChartTab = ref('equity')

async function refresh() {
  const [configResult, backtestsResult, botResult] = await Promise.allSettled([
    api.getCryptoStrategyConfig(),
    api.getCryptoBacktests(),
    api.getCryptoBotStatus(),
  ])
  if (configResult.status === 'fulfilled') {
    config.value = { ...config.value, ...configResult.value }
  }
  if (backtestsResult.status === 'fulfilled') {
    const list = backtestsResult.value.results || backtestsResult.value
    backtests.value = list
    if (list.length > 0) latestBacktest.value = list[0]
  }
  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }
}

async function refreshCustom() {
  try {
    const resp = await api.getCustomStrategies('CRYPTO')
    customStrategies.value = resp.results || resp
  } catch (err) {
    console.error('Custom strategies error:', err)
  }
}

async function toggleBot() {
  botStatusLoading.value = true
  try {
    const resp = await api.setCryptoBotPaused(!botPaused.value)
    botPaused.value = resp.paused
  } catch (err) {
    toast.error(`Bot toggle failed: ${err.message}`)
  }
  botStatusLoading.value = false
}

async function saveConfig() {
  configLoading.value = true
  try {
    await api.updateCryptoStrategyConfig(config.value)
    toast.success('Config saved')
  } catch (err) {
    toast.error(`Config save failed: ${err.message}`)
  }
  configLoading.value = false
}

async function runBacktest() {
  loadingBtn.value['active-backtest'] = true
  try {
    await api.runCryptoBacktest()
    toast.success('Backtest started -- results will appear shortly')
  } catch (err) {
    toast.error(`Backtest failed: ${err.message}`)
  }
  loadingBtn.value['active-backtest'] = false
}

async function runCustomBacktest(id) {
  loadingBtn.value[`cbacktest-${id}`] = true
  try {
    await api.runCustomBacktest(id)
    toast.success('Custom backtest started')
  } catch (err) {
    toast.error(`Backtest failed: ${err.message}`)
  }
  loadingBtn.value[`cbacktest-${id}`] = false
}

async function deleteCustom(id) {
  try {
    await api.deleteCustomStrategy(id)
    toast.success('Strategy deleted')
    await refreshCustom()
  } catch (err) {
    toast.error(`Delete failed: ${err.message}`)
  }
}

async function activateCustom(id) {
  loadingBtn.value[`activate-${id}`] = true
  try {
    await api.activateCustomStrategy(id)
    toast.success('Strategy activated — config updated')
    await refresh()
  } catch (err) {
    toast.error(`Activation failed: ${err.message}`)
  }
  loadingBtn.value[`activate-${id}`] = false
}

function computeBreakdown(trades) {
  if (!trades || !trades.length) return {}
  const breakdown = {}
  for (const t of trades) {
    const key = t.symbol || 'Unknown'
    if (!breakdown[key]) {
      breakdown[key] = { wins: 0, losses: 0, total_pnl: 0, trades: 0 }
    }
    breakdown[key].trades++
    breakdown[key].total_pnl += Number(t.pnl ?? 0)
    if (Number(t.pnl ?? 0) >= 0) breakdown[key].wins++
    else breakdown[key].losses++
  }
  for (const key of Object.keys(breakdown)) {
    const b = breakdown[key]
    b.win_rate = b.trades > 0 ? b.wins / b.trades : 0
  }
  return breakdown
}

function setTab(strategyId, tab) {
  activeTab.value[strategyId] = tab
}

function onBuilderSaved() {
  showBuilder.value = false
  refreshCustom()
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

usePolling(async () => { await refresh(); await refreshCustom() }, 15000)
</script>

<template>
  <SectionNav :links="cryptoLinks" />
  <div class="tp-page strat-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <h1>Crypto Strategies</h1>
        <p>Manage and backtest your cryptocurrency trading strategies.</p>
      </div>
      <div class="header-actions">
        <button class="tp-btn tp-btn-outline" @click="showBuilder = !showBuilder">
          <span class="material-symbols-outlined" style="font-size:18px">{{ showBuilder ? 'close' : 'history' }}</span>
          {{ showBuilder ? 'Cancel' : 'Create Strategy' }}
        </button>
        <button
          class="tp-btn"
          :class="botPaused ? 'tp-btn-primary' : 'tp-btn-dark'"
          :aria-busy="botStatusLoading"
          @click="toggleBot"
        >
          <span class="material-symbols-outlined" style="font-size:18px">{{ botPaused ? 'play_arrow' : 'pause' }}</span>
          {{ botPaused ? 'Resume Bot' : 'Pause Bot' }}
        </button>
      </div>
    </div>

    <!-- Bot Status Banner -->
    <div class="status-banner" :class="botPaused ? 'status-paused' : 'status-running'" style="margin-bottom: 1.5rem;">
      <span class="material-symbols-outlined" style="font-size:16px">{{ botPaused ? 'pause_circle' : 'play_circle' }}</span>
      <span class="status-text">Bot is {{ botPaused ? 'PAUSED' : 'RUNNING' }}</span>
    </div>

    <!-- Stats Overview -->
    <div class="tp-stats-grid" style="margin-bottom: 2rem;">
      <div class="tp-stat-card">
        <div class="stat-label">Latest Win Rate</div>
        <div class="stat-value">{{ latestBacktest ? fmtPct(latestBacktest.win_rate) : 'N/A' }}</div>
      </div>
      <div class="tp-stat-card">
        <div class="stat-label">Total Trades</div>
        <div class="stat-value">{{ latestBacktest?.total_trades ?? 0 }}</div>
      </div>
      <div class="tp-stat-card">
        <div class="stat-label">Custom Strategies</div>
        <div class="stat-value">{{ customStrategies.length }}</div>
      </div>
      <div class="tp-stat-card">
        <div class="stat-label">Bot Status</div>
        <div>
          <span class="tp-badge" :class="botPaused ? 'tp-badge-warning' : 'tp-badge-success'" style="font-size:0.75rem">
            <span class="pulse-dot" v-if="!botPaused"></span>
            {{ botPaused ? 'Paused' : 'Running' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Strategy Builder -->
    <StrategyBuilder v-if="showBuilder" domain="CRYPTO" @saved="onBuilderSaved" @cancel="showBuilder = false" />

    <!-- Tabs -->
    <div class="tp-tabs">
      <button :class="{ active: pageTab === 'active' }" @click="pageTab = 'active'">Active Strategies</button>
      <button :class="{ active: pageTab === 'custom' }" @click="pageTab = 'custom'">Custom Strategies</button>
      <button :class="{ active: pageTab === 'library' }" @click="pageTab = 'library'">Strategy Library</button>
    </div>

    <!-- ==================== ACTIVE STRATEGIES TAB ==================== -->
    <div v-if="pageTab === 'active'" class="strategy-grid">
      <div class="tp-card strategy-card">
        <!-- Card Header -->
        <div class="card-top">
          <div class="card-title-row">
            <div class="strat-icon" style="background:rgba(245,158,11,0.15);color:#f59e0b;">
              <span class="material-symbols-outlined" style="font-size:24px">trending_up</span>
            </div>
            <div>
              <h3 class="strat-name">Momentum MA Crossover</h3>
              <p class="strat-desc">Moving average crossover strategy for crypto</p>
            </div>
          </div>
          <span class="tp-badge tp-badge-success">
            <span class="pulse-dot"></span>
            Active
          </span>
        </div>

        <!-- Config Summary -->
        <div class="card-stats">
          <div class="stat-item">
            <span class="stat-micro-label">Fast MA</span>
            <span class="stat-micro-value">{{ config.fast_ma }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-micro-label">Slow MA</span>
            <span class="stat-micro-value">{{ config.slow_ma }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-micro-label">Leverage</span>
            <span class="stat-micro-value">{{ config.leverage }}x</span>
          </div>
        </div>

        <!-- Backtest Stats -->
        <div v-if="latestBacktest" class="card-stats">
          <div class="stat-item">
            <span class="stat-micro-label">Win Rate</span>
            <span class="stat-micro-value" :class="(latestBacktest.win_rate * 100) >= 50 ? 'positive' : 'negative'">
              {{ fmtPct(latestBacktest.win_rate) }}
            </span>
          </div>
          <div class="stat-item">
            <span class="stat-micro-label">Trades</span>
            <span class="stat-micro-value">{{ latestBacktest.total_trades }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-micro-label">Total PnL</span>
            <span class="stat-micro-value" :class="Number(latestBacktest.total_pnl ?? 0) >= 0 ? 'positive' : 'negative'">
              {{ Number(latestBacktest.total_pnl ?? 0) >= 0 ? '+' : '' }}${{ fmt(latestBacktest.total_pnl) }}
            </span>
          </div>
        </div>
        <div v-else class="card-stats card-stats-empty">
          <span class="stat-micro-label">No backtest results yet</span>
        </div>

        <!-- Expandable Sections -->
        <div class="card-expandable">
          <!-- Backtest Details -->
          <details v-if="latestBacktest">
            <summary class="expand-summary">
              <span class="material-symbols-outlined" style="font-size:16px">bar_chart</span>
              Latest Backtest Details
            </summary>
            <div class="expand-content">
              <table class="detail-table">
                <tbody>
                  <tr><td>Symbol</td><td>{{ latestBacktest.symbol }}</td></tr>
                  <tr><td>Status</td><td><span class="tp-badge" :class="latestBacktest.passed ? 'tp-badge-success' : 'tp-badge-danger'">{{ latestBacktest.passed ? 'PASS' : 'FAIL' }}</span></td></tr>
                  <tr><td>Wins / Losses</td><td>{{ latestBacktest.winning_trades ?? '-' }} / {{ latestBacktest.losing_trades ?? '-' }}</td></tr>
                  <tr><td>Profit Factor</td><td>{{ latestBacktest.profit_factor != null ? Number(latestBacktest.profit_factor).toFixed(2) : 'N/A' }}</td></tr>
                  <tr><td>Max Drawdown</td><td>{{ fmtPct(latestBacktest.max_drawdown) }}</td></tr>
                  <tr><td>Run Time</td><td>{{ fmtDate(latestBacktest.run_time) }}</td></tr>
                </tbody>
              </table>
            </div>
          </details>

          <!-- Trade Details -->
          <details v-if="latestBacktest && latestBacktest.trades && latestBacktest.trades.length">
            <summary class="expand-summary">
              <span class="material-symbols-outlined" style="font-size:16px">receipt_long</span>
              Trade Details ({{ latestBacktest.trades.length }})
            </summary>
            <div class="expand-content" style="overflow-x: auto;">
              <table class="detail-table">
                <thead>
                  <tr><th>#</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Size</th><th>PnL</th><th>Reason</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(t, i) in latestBacktest.trades" :key="i">
                    <td>{{ i + 1 }}</td>
                    <td>{{ t.symbol ?? '-' }}</td>
                    <td>
                      <span class="tp-badge" :class="t.side === 'LONG' ? 'tp-badge-success' : 'tp-badge-danger'" style="font-size:0.65rem;">
                        {{ t.side ?? '-' }}
                      </span>
                    </td>
                    <td>${{ fmt(t.entry_price) }}</td>
                    <td>${{ fmt(t.exit_price) }}</td>
                    <td>{{ fmt(t.size) }}</td>
                    <td :style="{ color: Number(t.pnl ?? 0) >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)', fontWeight: 700 }">
                      {{ Number(t.pnl ?? 0) >= 0 ? '+' : '' }}${{ fmt(t.pnl) }}
                    </td>
                    <td style="font-size:0.8rem;color:var(--tp-text-dim);">{{ t.reason ?? '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </details>

          <!-- Charts (Equity Curve + Trade Markers + Symbol Breakdown) -->
          <details v-if="latestBacktest">
            <summary class="expand-summary">
              <span class="material-symbols-outlined" style="font-size:16px">ssid_chart</span>
              Backtest Charts
            </summary>
            <div class="expand-content">
              <div class="chart-tabs">
                <button class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': activeChartTab === 'equity' }" @click="activeChartTab = 'equity'">Equity Curve</button>
                <button v-if="latestBacktest.trades?.length" class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': activeChartTab === 'trades' }" @click="activeChartTab = 'trades'">Trade Markers</button>
                <button v-if="latestBacktest.trades?.length" class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': activeChartTab === 'breakdown' }" @click="activeChartTab = 'breakdown'">Symbol Breakdown</button>
              </div>
              <EquityCurveChart v-if="activeChartTab === 'equity'" :equity-curve="latestBacktest.equity_curve || []" />
              <TradeMarkersChart v-if="activeChartTab === 'trades' && latestBacktest.trades?.length" :trades="latestBacktest.trades" strategy="momentum" symbol-suffix="-USD" />
              <SymbolBreakdownTable v-if="activeChartTab === 'breakdown' && latestBacktest.trades?.length" :breakdown="computeBreakdown(latestBacktest.trades)" />
            </div>
          </details>

          <!-- Backtest History -->
          <details v-if="backtests.length > 1">
            <summary class="expand-summary">
              <span class="material-symbols-outlined" style="font-size:16px">history</span>
              Backtest History
            </summary>
            <div class="expand-content">
              <BacktestHistoryChart :results="backtests" />
            </div>
          </details>

          <!-- Config Form -->
          <details>
            <summary class="expand-summary">
              <span class="material-symbols-outlined" style="font-size:16px">settings</span>
              Strategy Configuration
            </summary>
            <div class="expand-content">
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
            </div>
          </details>
        </div>

        <!-- Card Footer Actions -->
        <div class="card-actions">
          <button
            class="tp-btn tp-btn-outline"
            style="flex:1;"
            :aria-busy="configLoading"
            @click="saveConfig"
          >
            <span class="material-symbols-outlined" style="font-size:16px">save</span>
            Save Config
          </button>
          <button
            class="tp-btn tp-btn-primary"
            style="flex:1;"
            :aria-busy="loadingBtn['active-backtest']"
            @click="runBacktest"
          >
            <span class="material-symbols-outlined" style="font-size:16px">science</span>
            Run Backtest
          </button>
        </div>
      </div>
    </div>

    <!-- ==================== CUSTOM STRATEGIES TAB ==================== -->
    <div v-if="pageTab === 'custom'">
      <div v-if="customStrategies.length === 0" class="empty-state">
        <span class="material-symbols-outlined" style="font-size:3rem;color:var(--tp-text-dim)">inventory_2</span>
        <p style="font-weight:600;font-size:1rem;color:var(--tp-text);margin-top:0.5rem;">No Custom Strategies</p>
        <p style="font-size:0.85rem;">Create one using the Strategy Builder above.</p>
      </div>
      <div v-else class="strategy-grid">
        <div v-for="(cs, idx) in customStrategies" :key="'c'+cs.id" class="tp-card strategy-card">
          <div class="card-top">
            <div class="card-title-row">
              <div class="strat-icon" style="background:rgba(139,92,246,0.15);color:#8b5cf6;">
                <span class="material-symbols-outlined" style="font-size:24px">code</span>
              </div>
              <div>
                <h3 class="strat-name">{{ cs.name }}</h3>
                <p class="strat-desc">{{ cs.description || 'Custom strategy' }}</p>
              </div>
            </div>
            <span class="tp-badge tp-badge-primary">Custom</span>
          </div>

          <!-- Backtest Stats -->
          <template v-if="cs.latest_backtest">
            <div class="card-stats">
              <div class="stat-item">
                <span class="stat-micro-label">Win Rate</span>
                <span class="stat-micro-value" :class="(cs.latest_backtest.win_rate * 100) >= 50 ? 'positive' : 'negative'">
                  {{ fmtPct(cs.latest_backtest.win_rate) }}
                </span>
              </div>
              <div class="stat-item">
                <span class="stat-micro-label">Trades</span>
                <span class="stat-micro-value">{{ cs.latest_backtest.total_trades }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-micro-label">Total PnL</span>
                <span class="stat-micro-value" :class="Number(cs.latest_backtest.total_pnl ?? 0) >= 0 ? 'positive' : 'negative'">
                  {{ cs.latest_backtest.total_pnl != null ? (Number(cs.latest_backtest.total_pnl) >= 0 ? '+' : '') + '$' + fmt(cs.latest_backtest.total_pnl) : 'N/A' }}
                </span>
              </div>
            </div>
          </template>
          <div v-else class="card-stats card-stats-empty">
            <span class="stat-micro-label">No backtest results yet</span>
          </div>

          <!-- Expandable Sections -->
          <div class="card-expandable">
            <!-- Definition -->
            <details>
              <summary class="expand-summary">
                <span class="material-symbols-outlined" style="font-size:16px">code</span>
                Definition
              </summary>
              <div class="expand-content">
                <pre class="result-pre">{{ JSON.stringify(cs.definition, null, 2) }}</pre>
              </div>
            </details>

            <!-- Charts (Equity Curve + Trade Markers + Breakdown) -->
            <template v-if="cs.latest_backtest">
              <details>
                <summary class="expand-summary">
                  <span class="material-symbols-outlined" style="font-size:16px">ssid_chart</span>
                  Backtest Charts
                </summary>
                <div class="expand-content">
                  <div class="chart-tabs">
                    <button class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': !activeTab[cs.id] || activeTab[cs.id] === 'equity' }" @click="setTab(cs.id, 'equity')">Equity Curve</button>
                    <button v-if="cs.latest_backtest.trades?.length" class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': activeTab[cs.id] === 'trades' }" @click="setTab(cs.id, 'trades')">Trade Markers</button>
                    <button v-if="cs.latest_backtest.trades?.length" class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': activeTab[cs.id] === 'breakdown' }" @click="setTab(cs.id, 'breakdown')">Symbol Breakdown</button>
                  </div>
                  <EquityCurveChart v-if="!activeTab[cs.id] || activeTab[cs.id] === 'equity'" :equity-curve="cs.latest_backtest.equity_curve || []" />
                  <TradeMarkersChart v-if="activeTab[cs.id] === 'trades' && cs.latest_backtest.trades?.length" :trades="cs.latest_backtest.trades" :strategy="cs.name" symbol-suffix="-USD" />
                  <SymbolBreakdownTable v-if="activeTab[cs.id] === 'breakdown' && cs.latest_backtest.trades?.length" :breakdown="computeBreakdown(cs.latest_backtest.trades)" />
                </div>
              </details>
            </template>
          </div>

          <div class="card-actions">
            <button
              class="tp-btn tp-btn-primary"
              style="flex:1;"
              :aria-busy="loadingBtn[`activate-${cs.id}`]"
              @click="activateCustom(cs.id)"
            >Activate</button>
            <button
              class="tp-btn tp-btn-outline"
              style="flex:1;"
              :aria-busy="loadingBtn[`cbacktest-${cs.id}`]"
              @click="runCustomBacktest(cs.id)"
            >
              <span class="material-symbols-outlined" style="font-size:16px">science</span>
              Run Backtest
            </button>
            <button class="tp-btn tp-btn-danger" style="flex:0 0 auto;" @click="deleteCustom(cs.id)">
              <span class="material-symbols-outlined" style="font-size:16px">delete</span>
            </button>
          </div>
        </div>

        <!-- Add New Strategy Card -->
        <div class="tp-add-card" @click="showBuilder = true">
          <div class="icon-circle">
            <span class="material-symbols-outlined" style="font-size:2rem">add</span>
          </div>
          <p style="font-weight:700;font-size:1.1rem;color:var(--tp-text);margin-bottom:0.25rem;">Create Custom Strategy</p>
          <p style="font-size:0.85rem;text-align:center;max-width:220px;">Use the visual builder to create and backtest crypto strategies.</p>
        </div>
      </div>
    </div>

    <!-- ==================== STRATEGY LIBRARY TAB ==================== -->
    <div v-if="pageTab === 'library'" style="margin-top: 1rem;">
      <StrategyLibrary domain="CRYPTO" />
    </div>
  </div>
</template>

<style scoped>
.strat-page {
  padding: 2rem 1rem;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1.5rem;
  flex-wrap: wrap;
  margin-bottom: 1.5rem;
}
.page-header h1 {
  font-size: 2rem;
  font-weight: 900;
  letter-spacing: -0.02em;
  margin-bottom: 0.35rem;
}
.header-actions {
  display: flex;
  gap: 0.75rem;
  flex-shrink: 0;
}

/* Status banner */
.status-banner {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  border-radius: var(--tp-radius-sm);
  font-size: 0.8rem;
  font-weight: 700;
}
.status-running {
  background: rgba(34,197,94,0.08);
  border: 1px solid rgba(34,197,94,0.2);
  color: var(--tp-success);
}
.status-paused {
  background: rgba(245,158,11,0.08);
  border: 1px solid rgba(245,158,11,0.2);
  color: var(--tp-warning);
}

/* Strategy Grid */
.strategy-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 1.5rem;
}

/* Strategy Card */
.strategy-card {
  display: flex;
  flex-direction: column;
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 1.25rem;
  border-bottom: 1px solid var(--tp-border);
}
.card-title-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.strat-icon {
  width: 3rem; height: 3rem;
  border-radius: var(--tp-radius);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.strat-name {
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 0.15rem;
}
.strat-desc {
  font-size: 0.75rem;
  color: var(--tp-text-dim) !important;
}

/* Card Stats */
.card-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  background: rgba(30,41,59,0.2);
}
.card-stats-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.stat-item {
  display: flex;
  flex-direction: column;
}
.stat-micro-label {
  font-size: 0.6rem;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--tp-text-dim);
  letter-spacing: 0.06em;
}
.stat-micro-value {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--tp-text);
}
.stat-micro-value.positive { color: var(--tp-success); }
.stat-micro-value.negative { color: var(--tp-danger); }

/* Expandable sections */
.card-expandable {
  padding: 0 1.25rem;
}
.expand-summary {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.75rem 0;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--tp-text-muted);
  cursor: pointer;
  border-bottom: 1px solid var(--tp-border);
  list-style: none;
}
.expand-summary::-webkit-details-marker { display: none; }
.expand-summary::after {
  content: '';
  margin-left: auto;
  width: 0; height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid var(--tp-text-dim);
  transition: transform 0.2s;
}
details[open] > .expand-summary::after {
  transform: rotate(180deg);
}
.expand-content {
  padding: 0.75rem 0;
}

/* Detail Table */
.detail-table {
  width: 100%;
  font-size: 0.8rem;
}
.detail-table td, .detail-table th {
  padding: 0.4rem 0;
  border: none;
}
.detail-table td:first-child {
  color: var(--tp-text-dim);
  width: 40%;
}
.detail-table td:last-child {
  font-weight: 600;
  color: var(--tp-text);
}

/* Chart tabs */
.chart-tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.chart-tabs .tp-btn {
  font-size: 0.7rem;
  padding: 0.3rem 0.75rem;
}

/* Card Actions */
.card-actions {
  display: flex;
  gap: 0.75rem;
  padding: 1.25rem;
  margin-top: auto;
}

/* Result Pre */
.result-pre {
  background: var(--tp-bg-surface);
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  padding: 1rem;
  font-size: 0.75rem;
  color: var(--tp-text-muted);
  overflow-x: auto;
  margin: 0;
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  text-align: center;
}
</style>
