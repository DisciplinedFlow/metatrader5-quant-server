<script setup>
import { ref } from 'vue'
import { usePolling } from '@/composables/usePolling'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'
import EquityCurveChart from '@/components/charts/EquityCurveChart.vue'
import TradeMarkersChart from '@/components/charts/TradeMarkersChart.vue'
import SymbolBreakdownTable from '@/components/charts/SymbolBreakdownTable.vue'
import BacktestHistoryChart from '@/components/charts/BacktestHistoryChart.vue'
import StrategyBuilder from '@/components/StrategyBuilder.vue'
import StrategyLibrary from '@/components/StrategyLibrary.vue'
import SectionNav from '@/components/SectionNav.vue'

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
const strategies = ref([])
const customStrategies = ref([])
const loadingBtn = ref({})
const detailData = ref({})
const historyData = ref({})
const activeTab = ref({})
const showBuilder = ref(false)
const botPaused = ref(false)
const botStatusLoading = ref(false)

// Active page tab
const pageTab = ref('active')

async function refresh() {
  try {
    const [stratResp, botResp] = await Promise.allSettled([
      api.getStrategies(),
      api.getBotStatus(),
    ])
    if (stratResp.status === 'fulfilled') {
      strategies.value = stratResp.value.results || stratResp.value
    }
    if (botResp.status === 'fulfilled') {
      botPaused.value = botResp.value.paused
    }
  } catch (err) {
    console.error('Strategies error:', err)
  }
}

async function toggleBot() {
  botStatusLoading.value = true
  try {
    const resp = await api.setBotPaused(!botPaused.value)
    botPaused.value = resp.paused
  } catch (err) {
    toast.error(`Bot toggle failed: ${err.message}`)
  }
  botStatusLoading.value = false
}

async function refreshCustom() {
  try {
    const resp = await api.getCustomStrategies('FOREX')
    customStrategies.value = resp.results || resp
  } catch (err) {
    console.error('Custom strategies error:', err)
  }
}

async function loadDetailForConfig(configId, cs) {
  if (!configId) return
  const bt = cs?.latest_backtest
  if (!bt) return
  // Skip if already loaded for this exact backtest
  if (detailData.value[configId]?.id === bt.id) return
  try {
    const data = await api.getBacktestDetail(configId, bt.id)
    detailData.value[configId] = data
  } catch (err) {
    console.error('Detail load error:', err)
  }
}

usePolling(async () => { await refresh(); await refreshCustom() }, 10000)

async function activate(id) {
  loadingBtn.value[`activate-${id}`] = true
  try {
    await api.activateStrategy(id)
    toast.success('Strategy activated')
    await refresh()
  } catch (err) {
    toast.error(`Activation failed: ${err.message}`)
  }
  loadingBtn.value[`activate-${id}`] = false
}

async function runBacktest(id) {
  loadingBtn.value[`backtest-${id}`] = true
  try {
    await api.runBacktest(id)
    toast.success('Backtest started -- results will appear shortly')
  } catch (err) {
    toast.error(`Backtest failed: ${err.message}`)
  }
  loadingBtn.value[`backtest-${id}`] = false
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

async function activateCustom(id) {
  loadingBtn.value[`cactivate-${id}`] = true
  try {
    await api.activateCustomStrategy(id)
    toast.success('Custom strategy activated')
    await Promise.all([refresh(), refreshCustom()])
  } catch (err) {
    toast.error(`Activation failed: ${err.message}`)
  }
  loadingBtn.value[`cactivate-${id}`] = false
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

async function loadDetail(strategy) {
  const bt = strategy.latest_backtest
  if (!bt) return
  // Re-fetch if backtest ID changed (new backtest ran)
  if (detailData.value[strategy.id]?.id === bt.id) return
  try {
    const data = await api.getBacktestDetail(strategy.id, bt.id)
    detailData.value[strategy.id] = data
  } catch (err) {
    console.error('Detail load error:', err)
  }
}

async function loadHistory(strategyId) {
  if (historyData.value[strategyId]) return
  try {
    const data = await api.getBacktestResults(strategyId)
    historyData.value[strategyId] = data.results || data
  } catch (err) {
    console.error('History load error:', err)
  }
}

function setTab(strategyId, tab) {
  activeTab.value[strategyId] = tab
}

function onBuilderSaved() {
  showBuilder.value = false
  refreshCustom()
}

// Utility icon map for strategy cards
const strategyIcons = ['bolt', 'grid_view', 'trending_up', 'auto_graph', 'insights', 'speed', 'analytics', 'candlestick_chart']
const strategyColors = ['var(--tp-primary)', '#f97316', '#8b5cf6', '#06b6d4', '#ec4899', '#14b8a6', '#eab308', '#6366f1']

function getIcon(index) {
  return strategyIcons[index % strategyIcons.length]
}
function getColor(index) {
  return strategyColors[index % strategyColors.length]
}
</script>

<template>
  <SectionNav :links="forexLinks" />
  <div class="tp-page strat-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <h1>Bot Strategies</h1>
        <p>Algorithmic bot management & backtesting.</p>
      </div>
      <div class="header-actions">
        <button class="tp-btn tp-btn-outline" @click="showBuilder = !showBuilder">
          <span class="material-symbols-outlined" style="font-size:14px">{{ showBuilder ? 'close' : 'history' }}</span>
          {{ showBuilder ? 'Cancel' : 'Strategy Builder' }}
        </button>
        <button
          class="tp-btn"
          :class="botPaused ? 'tp-btn-primary' : 'tp-btn-dark'"
          :aria-busy="botStatusLoading"
          @click="toggleBot"
        >
          <span class="material-symbols-outlined" style="font-size:14px">{{ botPaused ? 'play_arrow' : 'pause' }}</span>
          {{ botPaused ? 'Resume Bot' : 'Pause Bot' }}
        </button>
      </div>
    </div>

    <!-- Bot Status Banner -->
    <div class="status-banner" :class="botPaused ? 'status-paused' : 'status-running'" style="margin-bottom: 1rem;">
      <span class="material-symbols-outlined" style="font-size:16px">{{ botPaused ? 'pause_circle' : 'play_circle' }}</span>
      <span class="status-text">Bot is {{ botPaused ? 'PAUSED' : 'RUNNING' }}</span>
    </div>

    <!-- Stats Overview -->
    <div class="tp-stats-grid" style="margin-bottom: 1.25rem;">
      <div class="tp-stat-card">
        <div class="stat-label">Total Strategies</div>
        <div class="stat-value">{{ strategies.length + customStrategies.length }}</div>
      </div>
      <div class="tp-stat-card">
        <div class="stat-label">Active Strategies</div>
        <div>
          <span class="stat-value">{{ strategies.filter(s => s.is_active).length + customStrategies.filter(c => c.is_active).length }}</span>
          <span class="stat-change positive"> / {{ strategies.length + customStrategies.length }}</span>
        </div>
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
    <StrategyBuilder v-if="showBuilder" domain="FOREX" @saved="onBuilderSaved" @cancel="showBuilder = false" />

    <!-- Tabs -->
    <div class="tp-tabs">
      <button :class="{ active: pageTab === 'active' }" @click="pageTab = 'active'">Active Strategies</button>
      <button :class="{ active: pageTab === 'custom' }" @click="pageTab = 'custom'">Custom Strategies</button>
      <button :class="{ active: pageTab === 'library' }" @click="pageTab = 'library'">CVD Library</button>
    </div>

    <!-- Built-in Strategies Grid -->
    <div v-if="pageTab === 'active'" class="strategy-grid">
      <div v-for="(s, idx) in strategies" :key="s.id" class="tp-card strategy-card" :class="{ 'card-inactive': !s.is_active }">
        <!-- Card Header -->
        <div class="card-top">
          <div class="card-title-row">
            <div class="strat-icon" :style="{ background: getColor(idx) + '15', color: getColor(idx) }">
              <span class="material-symbols-outlined" style="font-size:18px">{{ getIcon(idx) }}</span>
            </div>
            <div>
              <h3 class="strat-name">{{ s.name }}</h3>
              <p class="strat-desc">{{ s.description || 'No description' }}</p>
            </div>
          </div>
          <span class="tp-badge" :class="s.is_active ? 'tp-badge-success' : 'tp-badge-neutral'">
            <span class="pulse-dot" v-if="s.is_active"></span>
            {{ s.is_active ? 'Active' : 'Inactive' }}
          </span>
        </div>

        <!-- Backtest Stats -->
        <div v-if="s.latest_backtest" class="card-stats">
          <div class="stat-item">
            <span class="stat-micro-label">Win Rate</span>
            <span class="stat-micro-value" :class="(s.latest_backtest.win_rate * 100) >= 50 ? 'positive' : 'negative'">
              {{ (s.latest_backtest.win_rate * 100).toFixed(1) }}%
            </span>
          </div>
          <div class="stat-item">
            <span class="stat-micro-label">Trades</span>
            <span class="stat-micro-value">{{ s.latest_backtest.total_trades }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-micro-label">Total PnL</span>
            <span class="stat-micro-value" :class="(s.latest_backtest.total_pnl ?? 0) >= 0 ? 'positive' : 'negative'">
              {{ s.latest_backtest.total_pnl != null ? (s.latest_backtest.total_pnl * 100).toFixed(3) + '%' : 'N/A' }}
            </span>
          </div>
        </div>
        <div v-else class="card-stats card-stats-empty">
          <span class="stat-micro-label">No backtest results yet</span>
        </div>

        <!-- Performance Bars (visual) -->
        <div v-if="s.latest_backtest" class="tp-perf-bars" style="margin: 0 1rem;">
          <div class="bar" v-for="n in 8" :key="n"
            :style="{
              height: (20 + Math.random() * 80) + '%',
              background: getColor(idx),
              opacity: 0.2 + (n * 0.1)
            }"></div>
        </div>

        <!-- Expandable Sections -->
        <div class="card-expandable">
          <!-- Backtest Details -->
          <details v-if="s.latest_backtest">
            <summary class="expand-summary">
              <span class="material-symbols-outlined" style="font-size:16px">bar_chart</span>
              Latest Backtest Details
            </summary>
            <div class="expand-content">
              <table class="detail-table">
                <tbody>
                  <tr><td>Status</td><td><span class="tp-badge" :class="s.latest_backtest.passed ? 'tp-badge-success' : 'tp-badge-danger'">{{ s.latest_backtest.passed ? 'PASS' : 'FAIL' }}</span></td></tr>
                  <tr><td>Wins / Losses</td><td>{{ s.latest_backtest.winning_trades }} / {{ s.latest_backtest.losing_trades }}</td></tr>
                  <tr><td>Profit Factor</td><td>{{ s.latest_backtest.profit_factor != null ? s.latest_backtest.profit_factor.toFixed(2) : 'N/A' }}</td></tr>
                  <tr><td>Avg Win</td><td>{{ s.latest_backtest.avg_win != null ? (s.latest_backtest.avg_win * 100).toFixed(3) + '%' : 'N/A' }}</td></tr>
                  <tr><td>Avg Loss</td><td>{{ s.latest_backtest.avg_loss != null ? (s.latest_backtest.avg_loss * 100).toFixed(3) + '%' : 'N/A' }}</td></tr>
                  <tr><td>Data Source</td><td>{{ s.latest_backtest.data_source || 'MT5' }}{{ s.latest_backtest.data_source === 'YAHOO' ? ` (${s.latest_backtest.period_days}d)` : '' }}</td></tr>
                  <tr><td>Run Time</td><td>{{ new Date(s.latest_backtest.run_time).toLocaleString() }}</td></tr>
                </tbody>
              </table>
            </div>
          </details>

          <!-- Charts -->
          <details @toggle="e => { if (e.target.open) loadDetail(s) }">
            <summary class="expand-summary">
              <span class="material-symbols-outlined" style="font-size:16px">ssid_chart</span>
              Backtest Charts
            </summary>
            <div class="expand-content">
              <template v-if="detailData[s.id]">
                <div class="chart-tabs">
                  <button class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': !activeTab[s.id] || activeTab[s.id] === 'equity' }" @click="setTab(s.id, 'equity')">Equity Curve</button>
                  <button v-if="detailData[s.id].trades?.length" class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': activeTab[s.id] === 'trades' }" @click="setTab(s.id, 'trades')">Trade Markers</button>
                  <button v-if="detailData[s.id].trades?.length || Object.keys(detailData[s.id].symbol_breakdown || {}).length" class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': activeTab[s.id] === 'breakdown' }" @click="setTab(s.id, 'breakdown')">Symbol Breakdown</button>
                </div>
                <EquityCurveChart v-if="!activeTab[s.id] || activeTab[s.id] === 'equity'" :equity-curve="detailData[s.id].equity_curve || []" />
                <TradeMarkersChart v-if="activeTab[s.id] === 'trades' && detailData[s.id].trades?.length" :trades="detailData[s.id].trades" :strategy="s.name" />
                <SymbolBreakdownTable v-if="activeTab[s.id] === 'breakdown'" :breakdown="detailData[s.id].symbol_breakdown || {}" />
              </template>
              <p v-else style="color:var(--tp-text-dim);font-size:0.85rem;padding:0.5rem 0;">Loading chart data...</p>
            </div>
          </details>

          <!-- Backtest History (lazy-loaded) -->
          <details @toggle="e => { if (e.target.open) loadHistory(s.id) }">
            <summary class="expand-summary">
              <span class="material-symbols-outlined" style="font-size:16px">history</span>
              Backtest History
            </summary>
            <div class="expand-content">
              <BacktestHistoryChart v-if="historyData[s.id]" :results="historyData[s.id]" />
              <p v-else style="color:var(--tp-text-dim);font-size:0.85rem;padding:0.5rem 0;">Loading history...</p>
            </div>
          </details>
        </div>

        <!-- Card Footer Actions -->
        <div class="card-actions">
          <button
            v-if="!s.is_active"
            class="tp-btn tp-btn-primary"
            style="flex:1;"
            :aria-busy="loadingBtn[`activate-${s.id}`]"
            @click="activate(s.id)"
          >Activate</button>
          <button
            class="tp-btn tp-btn-outline"
            style="flex:1;"
            :aria-busy="loadingBtn[`backtest-${s.id}`]"
            @click="runBacktest(s.id)"
          >
            <span class="material-symbols-outlined" style="font-size:16px">science</span>
            Run Backtest
          </button>
        </div>
      </div>

      <!-- Add New Strategy Card -->
      <div class="tp-add-card" @click="showBuilder = true">
        <div class="icon-circle">
          <span class="material-symbols-outlined" style="font-size:1.5rem">add</span>
        </div>
        <p style="font-weight:700;font-size:0.88rem;color:var(--tp-text);margin-bottom:0.15rem;">Create Custom Strategy</p>
        <p style="font-size:0.75rem;text-align:center;max-width:200px;">Use the visual builder to create and backtest your own strategy.</p>
      </div>
    </div>

    <!-- CVD Library Tab -->
    <div v-if="pageTab === 'library'" style="margin-top: 1rem;">
      <StrategyLibrary domain="FOREX" />
    </div>

    <!-- Custom Strategies Tab -->
    <div v-if="pageTab === 'custom'">
      <div v-if="customStrategies.length === 0" class="empty-state">
        <span class="material-symbols-outlined" style="font-size:2rem;color:var(--tp-text-dim)">inventory_2</span>
        <p style="font-weight:600;font-size:0.88rem;color:var(--tp-text);margin-top:0.4rem;">No Custom Strategies</p>
        <p style="font-size:0.75rem;">Create one using the Strategy Builder above.</p>
      </div>
      <div v-else class="strategy-grid">
        <div v-for="(cs, idx) in customStrategies" :key="'c'+cs.id" class="tp-card strategy-card" :class="{ 'card-active': cs.is_active }">
          <div class="card-top">
            <div class="card-title-row">
              <div class="strat-icon" :style="cs.is_active ? 'background:rgba(34,197,94,0.15);color:#22c55e;' : 'background:rgba(139,92,246,0.15);color:#8b5cf6;'">
                <span class="material-symbols-outlined" style="font-size:18px">{{ cs.is_active ? 'bolt' : 'code' }}</span>
              </div>
              <div>
                <h3 class="strat-name">{{ cs.name }}</h3>
                <p class="strat-desc">{{ cs.description || 'Custom strategy' }}</p>
              </div>
            </div>
            <span class="tp-badge" :class="cs.is_active ? 'tp-badge-success' : 'tp-badge-primary'">
              <span class="pulse-dot" v-if="cs.is_active"></span>
              {{ cs.is_active ? 'Active' : 'Custom' }}
            </span>
          </div>

          <!-- Definition (expandable) -->
          <div class="card-expandable">
            <details>
              <summary class="expand-summary">
                <span class="material-symbols-outlined" style="font-size:16px">code</span>
                Definition
              </summary>
              <div class="expand-content">
                <pre class="result-pre">{{ JSON.stringify(cs.definition, null, 2) }}</pre>
              </div>
            </details>

            <!-- Charts for custom strategies -->
            <template v-if="cs.strategy_config">
              <!-- Backtest Stats -->
              <template v-if="cs.latest_backtest">
                <div class="card-stats">
                  <div class="stat-item">
                    <span class="stat-micro-label">Win Rate</span>
                    <span class="stat-micro-value" :class="(cs.latest_backtest.win_rate * 100) >= 50 ? 'positive' : 'negative'">
                      {{ (cs.latest_backtest.win_rate * 100).toFixed(1) }}%
                    </span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-micro-label">Trades</span>
                    <span class="stat-micro-value">{{ cs.latest_backtest.total_trades }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-micro-label">Total PnL</span>
                    <span class="stat-micro-value" :class="(cs.latest_backtest.total_pnl ?? 0) >= 0 ? 'positive' : 'negative'">
                      {{ cs.latest_backtest.total_pnl != null ? (cs.latest_backtest.total_pnl * 100).toFixed(3) + '%' : 'N/A' }}
                    </span>
                  </div>
                </div>
              </template>

              <!-- Backtest Charts -->
              <details @toggle="e => { if (e.target.open) loadDetailForConfig(cs.strategy_config, cs) }">
                <summary class="expand-summary">
                  <span class="material-symbols-outlined" style="font-size:16px">ssid_chart</span>
                  Backtest Charts
                </summary>
                <div class="expand-content">
                  <template v-if="detailData[cs.strategy_config]">
                    <div class="chart-tabs">
                      <button class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': !activeTab[cs.strategy_config] || activeTab[cs.strategy_config] === 'equity' }" @click="setTab(cs.strategy_config, 'equity')">Equity Curve</button>
                      <button v-if="detailData[cs.strategy_config].trades?.length" class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': activeTab[cs.strategy_config] === 'trades' }" @click="setTab(cs.strategy_config, 'trades')">Trade Markers</button>
                      <button v-if="detailData[cs.strategy_config].trades?.length || Object.keys(detailData[cs.strategy_config].symbol_breakdown || {}).length" class="tp-btn tp-btn-outline" :class="{ 'tp-btn-primary': activeTab[cs.strategy_config] === 'breakdown' }" @click="setTab(cs.strategy_config, 'breakdown')">Symbol Breakdown</button>
                    </div>
                    <EquityCurveChart v-if="!activeTab[cs.strategy_config] || activeTab[cs.strategy_config] === 'equity'" :equity-curve="detailData[cs.strategy_config].equity_curve || []" />
                    <TradeMarkersChart v-if="activeTab[cs.strategy_config] === 'trades' && detailData[cs.strategy_config].trades?.length" :trades="detailData[cs.strategy_config].trades" :strategy="cs.name" :timeframe="cs.definition?.timeframe || 'M5'" />
                    <SymbolBreakdownTable v-if="activeTab[cs.strategy_config] === 'breakdown'" :breakdown="detailData[cs.strategy_config].symbol_breakdown || {}" />
                  </template>
                  <p v-else style="color:var(--tp-text-dim);font-size:0.85rem;padding:0.5rem 0;">Loading chart data...</p>
                </div>
              </details>

              <!-- Backtest History -->
              <details @toggle="e => { if (e.target.open) loadHistory(cs.strategy_config) }">
                <summary class="expand-summary">
                  <span class="material-symbols-outlined" style="font-size:16px">history</span>
                  Backtest History
                </summary>
                <div class="expand-content">
                  <BacktestHistoryChart v-if="historyData[cs.strategy_config]" :results="historyData[cs.strategy_config]" />
                  <p v-else style="color:var(--tp-text-dim);font-size:0.85rem;padding:0.5rem 0;">Loading history...</p>
                </div>
              </details>
            </template>
          </div>

          <div class="card-actions">
            <button
              v-if="!cs.is_active"
              class="tp-btn tp-btn-primary"
              style="flex:1;"
              :aria-busy="loadingBtn[`cactivate-${cs.id}`]"
              @click="activateCustom(cs.id)"
            >
              <span class="material-symbols-outlined" style="font-size:16px">power_settings_new</span>
              Activate
            </button>
            <span v-else class="tp-btn tp-btn-dark" style="flex:1;cursor:default;text-align:center;">
              <span class="material-symbols-outlined" style="font-size:16px">check_circle</span>
              Currently Active
            </span>
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
      </div>
    </div>
  </div>
</template>

<style scoped>
.strat-page {
  padding: 1.5rem 1.5rem 2rem;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 1.25rem;
}
.page-header h1 {
  font-size: 1.25rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin-bottom: 0.1rem;
}
.page-header p {
  font-size: 0.8rem;
  color: var(--tp-text-dim);
}
.header-actions {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}

/* Status banner */
.status-banner {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.85rem;
  border-radius: var(--tp-radius-sm);
  font-size: 0.72rem;
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
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 1rem;
}

/* Strategy Card */
.strategy-card {
  display: flex;
  flex-direction: column;
}
.strategy-card.card-inactive {
  opacity: 0.7;
}
.strategy-card.card-active {
  border: 1px solid rgba(34,197,94,0.3);
  box-shadow: 0 0 12px rgba(34,197,94,0.08);
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 0.85rem 1rem;
  border-bottom: 1px solid var(--tp-border);
}
.card-title-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}
.strat-icon {
  width: 2.25rem; height: 2.25rem;
  border-radius: var(--tp-radius);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.strat-name {
  font-size: 0.88rem;
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 0.1rem;
}
.strat-desc {
  font-size: 0.7rem;
  color: var(--tp-text-dim) !important;
}

/* Card Stats */
.card-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.5rem;
  padding: 0.65rem 1rem;
  background: rgba(30,41,59,0.2);
}
.card-stats-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.65rem 1rem;
}
.stat-item {
  display: flex;
  flex-direction: column;
}
.stat-micro-label {
  font-size: 0.58rem;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--tp-text-dim);
  letter-spacing: 0.06em;
}
.stat-micro-value {
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--tp-text);
}
.stat-micro-value.positive { color: var(--tp-success); }
.stat-micro-value.negative { color: var(--tp-danger); }

/* Expandable sections */
.card-expandable {
  padding: 0 1rem;
}
.expand-summary {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.55rem 0;
  font-size: 0.75rem;
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
  padding: 0.5rem 0;
}

/* Detail Table */
.detail-table {
  width: 100%;
  font-size: 0.75rem;
}
.detail-table td {
  padding: 0.3rem 0;
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
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  margin-top: auto;
}

/* Result Pre */
.result-pre {
  background: var(--tp-bg-surface);
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  padding: 0.65rem;
  font-size: 0.7rem;
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
  padding: 3rem 2rem;
  text-align: center;
}

/* Performance bars compact */
.tp-perf-bars {
  margin: 0 1rem !important;
}
</style>
