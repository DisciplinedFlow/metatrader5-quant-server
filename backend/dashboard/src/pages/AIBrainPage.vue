<script setup>
import { ref, computed } from 'vue'
import { usePolling } from '@/composables/usePolling'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'

const toast = useToast()

const brainStatus = ref({ enabled: false, last_analysis: null })
const logs = ref([])
const loading = ref(false)
const showLogs = ref(false)

const analysis = computed(() => brainStatus.value.last_analysis)
const meta = computed(() => analysis.value?._meta)

async function refresh() {
  try {
    brainStatus.value = await api.getAIBrainStatus()
  } catch (err) {
    console.error('AI Brain status error:', err)
  }
}

async function toggle() {
  loading.value = true
  try {
    const newState = !brainStatus.value.enabled
    brainStatus.value = await api.setAIBrainEnabled(newState, newState)
    toast.success(newState ? 'AI Brain enabled — first analysis running...' : 'AI Brain disabled')
  } catch (err) {
    toast.error(`Toggle failed: ${err.message}`)
  }
  loading.value = false
}

async function runNow() {
  loading.value = true
  try {
    brainStatus.value = await api.setAIBrainEnabled(true, true)
    toast.success('Analysis triggered')
  } catch (err) {
    toast.error(`Run failed: ${err.message}`)
  }
  loading.value = false
}

async function loadLogs() {
  showLogs.value = !showLogs.value
  if (showLogs.value) {
    try {
      const resp = await api.getAIBrainLogs(100)
      logs.value = resp.logs || []
    } catch (err) {
      logs.value = ['Failed to load logs']
    }
  }
}

function riskColor(score) {
  if (score <= 3) return 'var(--tp-success)'
  if (score <= 6) return 'var(--tp-warning)'
  return 'var(--tp-danger)'
}

function regimeIcon(regime) {
  const map = { risk_on: 'trending_up', risk_off: 'trending_down', neutral: 'horizontal_rule', volatile: 'bolt' }
  return map[regime] || 'help'
}

usePolling(refresh, 15000)
</script>

<template>
  <div class="tp-page brain-page">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1>AI Brain</h1>
        <p>Autonomous quant analyst powered by Claude. Analyzes all domains every 5 minutes.</p>
      </div>
      <div class="header-actions">
        <button class="tp-btn tp-btn-outline" @click="loadLogs">
          <span class="material-symbols-outlined" style="font-size:18px">terminal</span>
          {{ showLogs ? 'Hide Logs' : 'Logs' }}
        </button>
        <button class="tp-btn tp-btn-outline" :aria-busy="loading" @click="runNow" :disabled="loading">
          <span class="material-symbols-outlined" style="font-size:18px">play_arrow</span>
          Run Now
        </button>
        <button
          class="tp-btn"
          :class="brainStatus.enabled ? 'tp-btn-primary' : 'tp-btn-dark'"
          :aria-busy="loading"
          @click="toggle"
        >
          <span class="material-symbols-outlined" style="font-size:18px">{{ brainStatus.enabled ? 'stop' : 'smart_toy' }}</span>
          {{ brainStatus.enabled ? 'Disable' : 'Enable' }}
        </button>
      </div>
    </div>

    <!-- Status Banner -->
    <div class="status-banner" :class="brainStatus.enabled ? 'status-running' : 'status-paused'" style="margin-bottom: 1.5rem;">
      <span class="material-symbols-outlined" style="font-size:16px">{{ brainStatus.enabled ? 'smart_toy' : 'pause_circle' }}</span>
      <span class="status-text">AI Brain is {{ brainStatus.enabled ? 'ACTIVE' : 'DISABLED' }}</span>
      <span v-if="meta" style="margin-left:auto; font-size:0.75rem; opacity:0.7;">
        Last run: {{ new Date(meta.timestamp).toLocaleString() }} · {{ meta.input_tokens + meta.output_tokens }} tokens
      </span>
    </div>

    <!-- No Analysis State -->
    <div v-if="!analysis" class="empty-state">
      <span class="material-symbols-outlined" style="font-size:4rem;color:var(--tp-text-dim)">psychology</span>
      <p style="font-weight:700;font-size:1.1rem;margin-top:0.75rem;">No Analysis Yet</p>
      <p style="font-size:0.85rem;color:var(--tp-text-dim);max-width:320px;text-align:center;">
        Enable the AI Brain or click "Run Now" to get your first portfolio analysis.
      </p>
    </div>

    <!-- Analysis Results -->
    <template v-if="analysis">
      <!-- Top Stats -->
      <div class="tp-stats-grid" style="margin-bottom: 2rem;">
        <div class="tp-stat-card">
          <div class="stat-label">Market Regime</div>
          <div class="stat-value" style="display:flex;align-items:center;gap:0.5rem;">
            <span class="material-symbols-outlined" style="font-size:24px">{{ regimeIcon(analysis.market_regime) }}</span>
            {{ (analysis.market_regime || '').replace('_', ' ').toUpperCase() }}
          </div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Risk Score</div>
          <div class="stat-value" :style="{ color: riskColor(analysis.risk_score) }">
            {{ analysis.risk_score }} / 10
          </div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Risk Alerts</div>
          <div class="stat-value" :style="{ color: (analysis.risk_alerts?.length || 0) > 0 ? 'var(--tp-danger)' : 'var(--tp-success)' }">
            {{ analysis.risk_alerts?.length || 0 }}
          </div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Strategy Ideas</div>
          <div class="stat-value">{{ analysis.new_strategy_ideas?.length || 0 }}</div>
        </div>
      </div>

      <!-- Risk Alerts -->
      <div v-if="analysis.risk_alerts?.length" class="tp-card alert-card" style="margin-bottom:1.5rem;">
        <div class="card-section-header danger">
          <span class="material-symbols-outlined" style="font-size:18px">warning</span>
          Risk Alerts
        </div>
        <ul class="alert-list">
          <li v-for="(alert, i) in analysis.risk_alerts" :key="i">{{ alert }}</li>
        </ul>
      </div>

      <!-- Domain Analysis Grid -->
      <div class="analysis-grid">
        <!-- Forex -->
        <div class="tp-card">
          <div class="card-section-header">
            <span class="material-symbols-outlined" style="font-size:18px">currency_exchange</span>
            Forex Analysis
          </div>
          <p class="analysis-summary">{{ analysis.forex_analysis?.summary }}</p>
          <ul v-if="analysis.forex_analysis?.recommendations?.length" class="rec-list">
            <li v-for="(r, i) in analysis.forex_analysis.recommendations" :key="i">{{ r }}</li>
          </ul>
        </div>

        <!-- Crypto -->
        <div class="tp-card">
          <div class="card-section-header">
            <span class="material-symbols-outlined" style="font-size:18px">currency_bitcoin</span>
            Crypto Analysis
          </div>
          <p class="analysis-summary">{{ analysis.crypto_analysis?.summary }}</p>
          <ul v-if="analysis.crypto_analysis?.recommendations?.length" class="rec-list">
            <li v-for="(r, i) in analysis.crypto_analysis.recommendations" :key="i">{{ r }}</li>
          </ul>
        </div>

      </div>

      <!-- Strategy Insights -->
      <div v-if="analysis.strategy_insights?.length" class="tp-card" style="margin-top:1.5rem;">
        <div class="card-section-header">
          <span class="material-symbols-outlined" style="font-size:18px">lightbulb</span>
          Strategy Insights
        </div>
        <ul class="rec-list">
          <li v-for="(s, i) in analysis.strategy_insights" :key="i">{{ s }}</li>
        </ul>
      </div>

      <!-- New Strategy Ideas -->
      <div v-if="analysis.new_strategy_ideas?.length" style="margin-top:1.5rem;">
        <h3 style="font-size:1rem;font-weight:700;margin-bottom:0.75rem;">
          <span class="material-symbols-outlined" style="font-size:18px;vertical-align:middle;">auto_awesome</span>
          New Strategy Ideas
        </h3>
        <div class="analysis-grid">
          <div v-for="(idea, i) in analysis.new_strategy_ideas" :key="i" class="tp-card">
            <div class="card-section-header">
              <span class="tp-badge tp-badge-primary" style="font-size:0.65rem;margin-right:0.5rem;">{{ idea.domain }}</span>
              {{ idea.name }}
            </div>
            <p class="analysis-summary">{{ idea.description }}</p>
            <p v-if="idea.edge" style="font-size:0.8rem;color:var(--tp-success);font-weight:600;margin:0.5rem 0 0;">
              Edge: {{ idea.edge }}
            </p>
          </div>
        </div>
      </div>

      <!-- Portfolio Actions -->
      <div v-if="analysis.portfolio_actions?.length" class="tp-card" style="margin-top:1.5rem;">
        <div class="card-section-header">
          <span class="material-symbols-outlined" style="font-size:18px">checklist</span>
          Recommended Actions
        </div>
        <ul class="rec-list actions-list">
          <li v-for="(a, i) in analysis.portfolio_actions" :key="i">{{ a }}</li>
        </ul>
      </div>
    </template>

    <!-- Logs Panel -->
    <div v-if="showLogs" class="tp-card" style="margin-top:1.5rem;">
      <div class="card-section-header">
        <span class="material-symbols-outlined" style="font-size:18px">terminal</span>
        AI Brain Logs
      </div>
      <pre class="log-pre">{{ logs.join('') || 'No logs yet.' }}</pre>
    </div>
  </div>
</template>

<style scoped>
.brain-page {
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
  background: rgba(99,102,241,0.08);
  border: 1px solid rgba(99,102,241,0.2);
  color: var(--tp-primary);
}
.status-paused {
  background: rgba(245,158,11,0.08);
  border: 1px solid rgba(245,158,11,0.2);
  color: var(--tp-warning);
}

/* Cards */
.card-section-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  font-weight: 700;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--tp-border);
  color: var(--tp-text);
}
.card-section-header.danger {
  color: var(--tp-danger);
}

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 1rem;
}

.analysis-summary {
  font-size: 0.85rem;
  color: var(--tp-text-muted);
  padding: 0.75rem 1rem 0;
  margin: 0;
  line-height: 1.5;
}

.rec-list, .alert-list, .actions-list {
  margin: 0;
  padding: 0.75rem 1rem 0.75rem 2rem;
  font-size: 0.8rem;
  color: var(--tp-text-muted);
}
.rec-list li, .alert-list li, .actions-list li {
  margin-bottom: 0.35rem;
  line-height: 1.4;
}
.alert-list li {
  color: var(--tp-danger);
}
.actions-list li {
  color: var(--tp-text);
  font-weight: 500;
}

/* Logs */
.log-pre {
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  padding: 1rem;
  font-size: 0.7rem;
  color: var(--tp-text-muted);
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
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
