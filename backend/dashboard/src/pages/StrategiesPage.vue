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
import SectionNav from '@/components/SectionNav.vue'

const forexLinks = [
  { to: '/forex', label: 'Overview' },
  { to: '/forex/positions', label: 'Positions' },
  { to: '/forex/order', label: 'Order' },
  { to: '/forex/history', label: 'History' },
  { to: '/forex/chart', label: 'Chart' },
  { to: '/forex/logs', label: 'Logs' },
  { to: '/forex/strategy', label: 'Strategies' },
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
    const resp = await api.getCustomStrategies()
    customStrategies.value = resp.results || resp
  } catch (err) {
    console.error('Custom strategies error:', err)
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
  if (!bt || detailData.value[strategy.id]) return
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
</script>

<template>
  <SectionNav :links="forexLinks" />
  <h2>Strategy Management</h2>

  <div style="display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem;">
    <button class="outline" @click="showBuilder = !showBuilder">
      {{ showBuilder ? 'Cancel' : '+ New Strategy' }}
    </button>
    <mark :class="botPaused ? 'secondary' : ''" style="font-size: 0.85rem;">
      {{ botPaused ? 'BOT PAUSED' : 'BOT RUNNING' }}
    </mark>
    <button
      :class="botPaused ? '' : 'outline secondary'"
      :aria-busy="botStatusLoading"
      style="width: auto;"
      @click="toggleBot"
    >
      {{ botPaused ? 'Resume Bot' : 'Pause Bot' }}
    </button>
  </div>

  <StrategyBuilder v-if="showBuilder" @saved="onBuilderSaved" @cancel="showBuilder = false" />

  <!-- Built-in Strategies -->
  <div class="grid">
    <article v-for="s in strategies" :key="s.id">
      <header>
        <strong>{{ s.name }}</strong>
        {{ ' ' }}<mark v-if="s.is_active">ACTIVE</mark>
        <span v-else class="secondary"> Inactive</span>
      </header>
      <p>{{ s.description || '' }}</p>

      <!-- Latest Backtest Stats -->
      <details>
        <summary>Latest Backtest</summary>
        <template v-if="s.latest_backtest">
          <table>
            <tbody>
              <tr>
                <td>Status</td>
                <td><mark :class="{ secondary: !s.latest_backtest.passed }">{{ s.latest_backtest.passed ? 'PASS' : 'FAIL' }}</mark></td>
              </tr>
              <tr><td>Win Rate</td><td>{{ (s.latest_backtest.win_rate * 100).toFixed(1) }}%</td></tr>
              <tr><td>Total Trades</td><td>{{ s.latest_backtest.total_trades }}</td></tr>
              <tr><td>Wins / Losses</td><td>{{ s.latest_backtest.winning_trades }} / {{ s.latest_backtest.losing_trades }}</td></tr>
              <tr><td>Total PnL</td><td>{{ s.latest_backtest.total_pnl != null ? (s.latest_backtest.total_pnl * 100).toFixed(3) + '%' : 'N/A' }}</td></tr>
              <tr><td>Profit Factor</td><td>{{ s.latest_backtest.profit_factor != null ? s.latest_backtest.profit_factor.toFixed(2) : 'N/A' }}</td></tr>
              <tr><td>Avg Win</td><td>{{ s.latest_backtest.avg_win != null ? (s.latest_backtest.avg_win * 100).toFixed(3) + '%' : 'N/A' }}</td></tr>
              <tr><td>Avg Loss</td><td>{{ s.latest_backtest.avg_loss != null ? (s.latest_backtest.avg_loss * 100).toFixed(3) + '%' : 'N/A' }}</td></tr>
              <tr><td>Data Source</td><td>{{ s.latest_backtest.data_source || 'MT5' }}{{ s.latest_backtest.data_source === 'YAHOO' ? ` (${s.latest_backtest.period_days}d)` : '' }}</td></tr>
              <tr><td>Run Time</td><td>{{ new Date(s.latest_backtest.run_time).toLocaleString() }}</td></tr>
            </tbody>
          </table>
        </template>
        <p v-else>No backtest results yet.</p>
      </details>

      <!-- Backtest Charts (lazy-loaded) -->
      <details @toggle="e => { if (e.target.open) loadDetail(s) }">
        <summary>Backtest Charts</summary>
        <template v-if="detailData[s.id]">
          <div style="display: flex; gap: 0.5rem; margin-bottom: 0.75rem;">
            <button
              :class="['outline', { secondary: activeTab[s.id] !== 'equity' && activeTab[s.id] !== undefined }]"
              style="width: auto;"
              @click="setTab(s.id, 'equity')"
            >Equity Curve</button>
            <button
              :class="['outline', { secondary: activeTab[s.id] !== 'trades' }]"
              style="width: auto;"
              @click="setTab(s.id, 'trades')"
            >Trade Markers</button>
            <button
              :class="['outline', { secondary: activeTab[s.id] !== 'breakdown' }]"
              style="width: auto;"
              @click="setTab(s.id, 'breakdown')"
            >Symbol Breakdown</button>
          </div>
          <EquityCurveChart
            v-if="!activeTab[s.id] || activeTab[s.id] === 'equity'"
            :equity-curve="detailData[s.id].equity_curve || []"
          />
          <TradeMarkersChart
            v-if="activeTab[s.id] === 'trades'"
            :trades="detailData[s.id].trades || []"
            :strategy="s.name"
          />
          <SymbolBreakdownTable
            v-if="activeTab[s.id] === 'breakdown'"
            :breakdown="detailData[s.id].symbol_breakdown || {}"
          />
        </template>
        <p v-else class="secondary">Loading chart data...</p>
      </details>

      <!-- Backtest History (lazy-loaded) -->
      <details @toggle="e => { if (e.target.open) loadHistory(s.id) }">
        <summary>Backtest History</summary>
        <BacktestHistoryChart v-if="historyData[s.id]" :results="historyData[s.id]" />
        <p v-else class="secondary">Loading history...</p>
      </details>

      <footer>
        <button
          v-if="!s.is_active"
          class="outline"
          :aria-busy="loadingBtn[`activate-${s.id}`]"
          @click="activate(s.id)"
        >Activate</button>
        <button
          class="outline secondary"
          :aria-busy="loadingBtn[`backtest-${s.id}`]"
          @click="runBacktest(s.id)"
        >Run Backtest</button>
      </footer>
    </article>
  </div>

  <!-- Custom Strategies -->
  <template v-if="customStrategies.length">
    <h3 style="margin-top: 2rem;">Custom Strategies</h3>
    <div class="grid">
      <article v-for="cs in customStrategies" :key="'c'+cs.id">
        <header>
          <strong>{{ cs.name }}</strong>
          <span class="secondary"> Custom</span>
        </header>
        <p>{{ cs.description || '' }}</p>
        <details>
          <summary>Definition</summary>
          <pre style="font-size: 0.8rem; overflow-x: auto;">{{ JSON.stringify(cs.definition, null, 2) }}</pre>
        </details>

        <!-- Charts for custom strategies (if they have a linked strategy_config) -->
        <template v-if="cs.strategy_config">
          <details @toggle="e => { if (e.target.open) loadHistory(cs.strategy_config) }">
            <summary>Backtest History</summary>
            <BacktestHistoryChart v-if="historyData[cs.strategy_config]" :results="historyData[cs.strategy_config]" />
            <p v-else class="secondary">Loading history...</p>
          </details>
        </template>

        <footer>
          <button
            class="outline secondary"
            :aria-busy="loadingBtn[`cbacktest-${cs.id}`]"
            @click="runCustomBacktest(cs.id)"
          >Run Backtest</button>
          <button class="outline secondary" @click="deleteCustom(cs.id)">Delete</button>
        </footer>
      </article>
    </div>
  </template>
</template>
