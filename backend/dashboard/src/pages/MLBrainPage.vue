<script setup>
import { ref, computed, onMounted } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'

const status = ref(null)
const predictions = ref([])
const cryptoML = ref(null)
const cryptoPredictions = ref([])
const loading = ref(true)
const activeTab = ref('overview')
const activeCryptoTab = ref('overview')
const activeMLTab = ref('forex')

async function refresh() {
  try {
    const [s, p, c, cp] = await Promise.all([
      api.getMLStatus(),
      api.getMLPredictions(50),
      api.getCryptoMLStatus(),
      api.getCryptoMLPredictions(50),
    ])
    status.value = s
    predictions.value = p
    cryptoML.value = c
    cryptoPredictions.value = cp
  } catch (err) {
    console.error('ML status error:', err)
  }
  loading.value = false
}

usePolling(refresh, 30000)
onMounted(refresh)

const model = computed(() => status.value?.active_model)
const features = computed(() => status.value?.features || {})
const llm = computed(() => status.value?.llm_training_data || {})
const llmRefreshing = ref(false)

async function refreshLLM() {
  llmRefreshing.value = true
  try {
    await api.backfillLLM()
    await refresh()
  } catch (err) {
    console.error('LLM backfill error:', err)
  }
  llmRefreshing.value = false
}
const history = computed(() => status.value?.model_history || [])
const learningCurve = computed(() => model.value?.learning_curve || [])

const topFeatures = computed(() => {
  if (!model.value?.feature_importance) return []
  const imp = model.value.feature_importance
  return Object.entries(imp)
    .filter(([k]) => !k.startsWith('_'))
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
})

const shapSummary = computed(() => model.value?.shap_summary || [])

// --- Derived analytics from predictions ---
const resolvedPredictions = computed(() =>
  predictions.value.filter(p => p.actual_win !== null && p.ml_score !== null)
)

const predictionAccuracy = computed(() => {
  if (resolvedPredictions.value.length === 0) return null
  const correct = resolvedPredictions.value.filter(p => (p.ml_score >= 0.5) === p.actual_win)
  return (correct.length / resolvedPredictions.value.length * 100).toFixed(1)
})

// Confusion matrix: TP, FP, TN, FN
const confusionMatrix = computed(() => {
  const r = resolvedPredictions.value
  if (r.length === 0) return null
  let tp = 0, fp = 0, tn = 0, fn = 0
  for (const p of r) {
    const pred = p.ml_score >= 0.5
    if (pred && p.actual_win) tp++
    else if (pred && !p.actual_win) fp++
    else if (!pred && !p.actual_win) tn++
    else fn++
  }
  const total = tp + fp + tn + fn
  return { tp, fp, tn, fn, total }
})

// PnL per confusion matrix quadrant
const confusionPnl = computed(() => {
  const r = resolvedPredictions.value.filter(p => p.pnl != null)
  if (r.length === 0) return null
  const buckets = { tp: [], fp: [], tn: [], fn: [] }
  for (const p of r) {
    const pred = p.ml_score >= 0.5
    if (pred && p.actual_win) buckets.tp.push(p.pnl)
    else if (pred && !p.actual_win) buckets.fp.push(p.pnl)
    else if (!pred && !p.actual_win) buckets.tn.push(p.pnl)
    else buckets.fn.push(p.pnl)
  }
  const avg = arr => arr.length ? (arr.reduce((s, v) => s + v, 0) / arr.length) : 0
  const sum = arr => arr.reduce((s, v) => s + v, 0)
  return {
    tp: { avg: avg(buckets.tp), sum: sum(buckets.tp), n: buckets.tp.length },
    fp: { avg: avg(buckets.fp), sum: sum(buckets.fp), n: buckets.fp.length },
    tn: { avg: avg(buckets.tn), sum: sum(buckets.tn), n: buckets.tn.length },
    fn: { avg: avg(buckets.fn), sum: sum(buckets.fn), n: buckets.fn.length },
  }
})

// Score distribution histogram (10 buckets)
const scoreDistribution = computed(() => {
  const r = resolvedPredictions.value
  if (r.length === 0) return []
  const buckets = Array.from({ length: 10 }, (_, i) => ({
    label: `${(i * 10)}`,
    min: i * 0.1,
    max: (i + 1) * 0.1,
    wins: 0,
    losses: 0,
  }))
  for (const p of r) {
    const idx = Math.min(Math.floor(p.ml_score * 10), 9)
    if (p.actual_win) buckets[idx].wins++
    else buckets[idx].losses++
  }
  return buckets
})

const scoreDistMax = computed(() => {
  if (scoreDistribution.value.length === 0) return 1
  return Math.max(...scoreDistribution.value.map(b => b.wins + b.losses), 1)
})

// Score vs PnL scatter data
const scorePnlData = computed(() => {
  const r = resolvedPredictions.value.filter(p => p.pnl != null && p.ml_score != null)
  if (r.length === 0) return { points: [], minPnl: 0, maxPnl: 0, zeroNorm: 50 }
  const pnls = r.map(p => p.pnl)
  const minPnl = Math.min(...pnls)
  const maxPnl = Math.max(...pnls)
  const range = maxPnl - minPnl || 1
  const points = r.map(p => ({
    score: p.ml_score,
    pnl: p.pnl,
    win: p.actual_win,
    symbol: p.symbol,
    xPct: (p.ml_score * 100),
    yPct: ((p.pnl - minPnl) / range * 100),
  }))
  const zeroNorm = ((0 - minPnl) / range * 100)
  return { points, minPnl, maxPnl, zeroNorm }
})

// Calibration: actual win rate per score bucket
const calibrationBuckets = computed(() => {
  const r = resolvedPredictions.value
  if (r.length < 3) return []
  const buckets = [
    { label: '0-30%', min: 0, max: 0.3, wins: 0, total: 0 },
    { label: '30-45%', min: 0.3, max: 0.45, wins: 0, total: 0 },
    { label: '45-55%', min: 0.45, max: 0.55, wins: 0, total: 0 },
    { label: '55-70%', min: 0.55, max: 0.7, wins: 0, total: 0 },
    { label: '70-100%', min: 0.7, max: 1.01, wins: 0, total: 0 },
  ]
  for (const p of r) {
    const b = buckets.find(b => p.ml_score >= b.min && p.ml_score < b.max)
    if (b) {
      b.total++
      if (p.actual_win) b.wins++
    }
  }
  return buckets.filter(b => b.total > 0).map(b => ({
    ...b,
    winRate: b.total > 0 ? (b.wins / b.total * 100) : 0,
  }))
})

// Training data balance
const trainBalance = computed(() => {
  const w = features.value.wins || 0
  const l = features.value.losses || 0
  const total = w + l
  if (total === 0) return null
  return {
    wins: w,
    losses: l,
    total,
    winPct: (w / total * 100).toFixed(0),
    lossPct: (l / total * 100).toFixed(0),
    winDeg: (w / total * 360),
  }
})

// Symbol breakdown from predictions
const symbolStats = computed(() => {
  const r = resolvedPredictions.value
  if (r.length === 0) return []
  const map = {}
  for (const p of r) {
    if (!map[p.symbol]) map[p.symbol] = { symbol: p.symbol, wins: 0, losses: 0, total: 0, pnl: 0 }
    map[p.symbol].total++
    if (p.actual_win) map[p.symbol].wins++
    else map[p.symbol].losses++
    if (p.pnl != null) map[p.symbol].pnl += p.pnl
  }
  return Object.values(map).sort((a, b) => b.total - a.total)
})

// SHAP diverging data for visual bars
const shapDivergingData = computed(() => {
  const s = shapSummary.value
  if (!s.length) return []
  const sorted = [...s].sort((a, b) => Math.abs(b.mean_signed) - Math.abs(a.mean_signed))
  const maxAbs = Math.max(...sorted.map(x => Math.abs(x.mean_signed)), 0.001)
  return sorted.map(item => ({
    ...item,
    barPct: (Math.abs(item.mean_signed) / maxAbs) * 45,
    positive: item.mean_signed >= 0,
  }))
})

// Threshold analysis — what accuracy/PnL at different score thresholds
const thresholdAnalysis = computed(() => {
  const r = resolvedPredictions.value.filter(p => p.pnl != null)
  if (r.length < 5) return []
  return [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65].map(t => {
    const accepted = r.filter(p => p.ml_score >= t)
    const wins = accepted.filter(p => p.actual_win)
    const totalPnl = accepted.reduce((s, p) => s + (p.pnl || 0), 0)
    return {
      threshold: t,
      accepted: accepted.length,
      rejected: r.length - accepted.length,
      winRate: accepted.length > 0 ? (wins.length / accepted.length * 100).toFixed(1) : '-',
      pnl: totalPnl.toFixed(2),
      avgPnl: accepted.length > 0 ? (totalPnl / accepted.length).toFixed(2) : '-',
      isCurrent: t === 0.50,
    }
  })
})

// --- Crypto ML computed properties ---
const cryptoModel = computed(() => cryptoML.value?.active_model)
const cryptoFeatures = computed(() => cryptoML.value?.features || {})

const cryptoTopFeatures = computed(() => {
  if (!cryptoModel.value?.feature_importance) return []
  const imp = cryptoModel.value.feature_importance
  return Object.entries(imp)
    .filter(([k]) => !k.startsWith('_'))
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
})

const cryptoResolvedPredictions = computed(() =>
  cryptoPredictions.value.filter(p => p.actual_win !== null && p.ml_score !== null)
)

const cryptoPredictionAccuracy = computed(() => {
  if (cryptoResolvedPredictions.value.length === 0) return null
  const correct = cryptoResolvedPredictions.value.filter(p => (p.ml_score >= 0.5) === p.actual_win)
  return (correct.length / cryptoResolvedPredictions.value.length * 100).toFixed(1)
})

const cryptoTrainBalance = computed(() => {
  const w = cryptoFeatures.value.wins || 0
  const l = cryptoFeatures.value.losses || 0
  const total = w + l
  if (total === 0) return null
  return {
    wins: w,
    losses: l,
    total,
    winPct: (w / total * 100).toFixed(0),
    lossPct: (l / total * 100).toFixed(0),
    winDeg: (w / total * 360),
  }
})

const cryptoScoreDistribution = computed(() => {
  const r = cryptoResolvedPredictions.value
  if (r.length === 0) return []
  const buckets = Array.from({ length: 10 }, (_, i) => ({
    label: `${(i * 10)}`,
    min: i * 0.1,
    max: (i + 1) * 0.1,
    wins: 0,
    losses: 0,
  }))
  for (const p of r) {
    const idx = Math.min(Math.floor(p.ml_score * 10), 9)
    if (p.actual_win) buckets[idx].wins++
    else buckets[idx].losses++
  }
  return buckets
})

const cryptoScoreDistMax = computed(() => {
  if (cryptoScoreDistribution.value.length === 0) return 1
  return Math.max(...cryptoScoreDistribution.value.map(b => b.wins + b.losses), 1)
})

const cryptoSymbolStats = computed(() => {
  const r = cryptoResolvedPredictions.value
  if (r.length === 0) return []
  const map = {}
  for (const p of r) {
    if (!map[p.symbol]) map[p.symbol] = { symbol: p.symbol, wins: 0, losses: 0, total: 0, pnl: 0 }
    map[p.symbol].total++
    if (p.actual_win) map[p.symbol].wins++
    else map[p.symbol].losses++
    if (p.pnl != null) map[p.symbol].pnl += p.pnl
  }
  return Object.values(map).sort((a, b) => b.total - a.total)
})

const cryptoHistory = computed(() => cryptoML.value?.model_history || [])

const cryptoNetPnl = computed(() => {
  // Try resolved predictions first
  const r = cryptoResolvedPredictions.value.filter(p => p.pnl != null)
  if (r.length > 0) return r.reduce((s, p) => s + p.pnl, 0)
  // Fall back to session/training data from API
  if (cryptoML.value?.session?.net_pnl != null) return cryptoML.value.session.net_pnl
  if (cryptoML.value?.training?.net_pnl != null) return cryptoML.value.training.net_pnl
  return null
})

const cryptoModelTypeClass = computed(() => {
  if (!cryptoModel.value) return ''
  return modelTypeClassFor(cryptoModel.value.model_type)
})

// Crypto confusion matrix
const cryptoConfusionMatrix = computed(() => {
  const preds = cryptoPredictions.value.filter(p => p.actual_win !== null)
  if (preds.length === 0) return null
  let tp = 0, fp = 0, tn = 0, fn = 0
  for (const p of preds) {
    const pred = p.ml_score != null ? p.ml_score >= 0.5 : p.actual_win // no model: use outcome as "prediction"
    if (pred && p.actual_win) tp++
    else if (pred && !p.actual_win) fp++
    else if (!pred && !p.actual_win) tn++
    else fn++
  }
  return { tp, fp, tn, fn, total: tp + fp + tn + fn }
})

const cryptoConfusionPnl = computed(() => {
  const r = cryptoPredictions.value.filter(p => p.actual_win !== null && p.pnl != null)
  if (r.length === 0) return null
  const buckets = { tp: [], fp: [], tn: [], fn: [] }
  for (const p of r) {
    const pred = p.ml_score != null ? p.ml_score >= 0.5 : p.actual_win
    if (pred && p.actual_win) buckets.tp.push(p.pnl)
    else if (pred && !p.actual_win) buckets.fp.push(p.pnl)
    else if (!pred && !p.actual_win) buckets.tn.push(p.pnl)
    else buckets.fn.push(p.pnl)
  }
  const avg = arr => arr.length ? (arr.reduce((s, v) => s + v, 0) / arr.length) : 0
  const sum = arr => arr.reduce((s, v) => s + v, 0)
  return {
    tp: { avg: avg(buckets.tp), sum: sum(buckets.tp), n: buckets.tp.length },
    fp: { avg: avg(buckets.fp), sum: sum(buckets.fp), n: buckets.fp.length },
    tn: { avg: avg(buckets.tn), sum: sum(buckets.tn), n: buckets.tn.length },
    fn: { avg: avg(buckets.fn), sum: sum(buckets.fn), n: buckets.fn.length },
  }
})

const cryptoScorePnlData = computed(() => {
  const r = cryptoPredictions.value.filter(p => p.pnl != null && p.actual_win !== null)
  if (r.length === 0) return { points: [], minPnl: 0, maxPnl: 0, zeroNorm: 50 }
  const pnls = r.map(p => p.pnl)
  const minPnl = Math.min(...pnls)
  const maxPnl = Math.max(...pnls)
  const range = maxPnl - minPnl || 1
  const points = r.map(p => ({
    score: p.ml_score || 0,
    pnl: p.pnl,
    win: p.actual_win,
    symbol: p.symbol,
    xPct: ((p.ml_score || 0) * 100),
    yPct: ((p.pnl - minPnl) / range * 100),
  }))
  const zeroNorm = ((0 - minPnl) / range * 100)
  return { points, minPnl, maxPnl, zeroNorm }
})

// Crypto threshold analysis
const cryptoThresholdAnalysis = computed(() => {
  const r = cryptoPredictions.value.filter(p => p.pnl != null && p.actual_win !== null)
  if (r.length < 3) return []
  return [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65].map(t => {
    const accepted = r.filter(p => (p.ml_score || 0) >= t)
    const wins = accepted.filter(p => p.actual_win)
    const totalPnl = accepted.reduce((s, p) => s + (p.pnl || 0), 0)
    return {
      threshold: t,
      accepted: accepted.length,
      rejected: r.length - accepted.length,
      winRate: accepted.length > 0 ? (wins.length / accepted.length * 100).toFixed(1) : '-',
      pnl: totalPnl.toFixed(2),
      avgPnl: accepted.length > 0 ? (totalPnl / accepted.length).toFixed(2) : '-',
      isCurrent: t === 0.50,
    }
  })
})

const cryptoCalibrationBuckets = computed(() => {
  const r = cryptoPredictions.value.filter(p => p.actual_win !== null && p.ml_score != null)
  if (r.length < 3) return []
  const buckets = [
    { label: '0-30%', min: 0, max: 0.3, wins: 0, total: 0 },
    { label: '30-45%', min: 0.3, max: 0.45, wins: 0, total: 0 },
    { label: '45-55%', min: 0.45, max: 0.55, wins: 0, total: 0 },
    { label: '55-70%', min: 0.55, max: 0.7, wins: 0, total: 0 },
    { label: '70-100%', min: 0.7, max: 1.01, wins: 0, total: 0 },
  ]
  for (const p of r) {
    const b = buckets.find(b => p.ml_score >= b.min && p.ml_score < b.max)
    if (b) { b.total++; if (p.actual_win) b.wins++ }
  }
  return buckets.filter(b => b.total > 0).map(b => ({
    ...b, winRate: b.total > 0 ? (b.wins / b.total * 100) : 0,
  }))
})

function scoreColor(score) {
  if (score === null || score === undefined) return ''
  if (score >= 0.6) return 'color: var(--tp-success)'
  if (score >= 0.45) return 'color: var(--tp-warning)'
  return 'color: var(--tp-danger)'
}

function pnlColor(pnl) {
  if (pnl === null || pnl === undefined) return ''
  return pnl >= 0 ? 'color: var(--tp-success)' : 'color: var(--tp-danger)'
}

function fmtTime(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  })
}

function fmtPct(val) {
  if (val === null || val === undefined) return '-'
  return (val * 100).toFixed(1) + '%'
}

function fmtDollar(val) {
  if (val === null || val === undefined) return '-'
  const prefix = val >= 0 ? '+$' : '-$'
  return prefix + Math.abs(val).toFixed(2)
}

const modelTypeClass = computed(() => {
  if (!model.value) return ''
  return modelTypeClassFor(model.value.model_type)
})

function modelTypeClassFor(type) {
  if (!type) return ''
  const t = type.toLowerCase()
  if (t.includes('xgboost')) return 'mt-xgboost'
  if (t.includes('lightgbm') || t.includes('lgbm')) return 'mt-lightgbm'
  return 'mt-sklearn'
}
</script>

<template>
  <div class="tp-page ml-page">
    <!-- Header -->
    <div class="ml-header">
      <div>
        <h1>ML Learning Pipeline</h1>
        <p class="ml-subtitle">Continuous learning from trade outcomes.</p>
      </div>
      <div v-if="model" class="model-pill-row">
        <span class="model-type-pill" :class="modelTypeClass">{{ model.model_type }}</span>
        <span class="pill-meta">v{{ model.version }} / {{ model.trade_count }} trades / {{ fmtTime(model.trained_at) }}</span>
      </div>
    </div>

    <!-- Forex / Crypto ML Tabs -->
    <div class="ml-tab-group">
      <button class="ml-tab" :class="{ active: activeMLTab === 'forex' }" @click="activeMLTab = 'forex'">Forex ML</button>
      <button class="ml-tab" :class="{ active: activeMLTab === 'crypto' }" @click="activeMLTab = 'crypto'">Crypto ML</button>
    </div>

    <!-- ===== FOREX ML TAB ===== -->
    <template v-if="activeMLTab === 'forex'">
    <div v-if="loading" class="ml-loading">Loading ML data...</div>

    <template v-else>
      <!-- Stats Strip -->
      <div class="tp-stats-grid" style="margin-bottom:1.25rem;padding-left:1.15rem;padding-right:1.15rem;">
        <div class="tp-stat-card">
          <div class="stat-label">Model</div>
          <div class="stat-value" :style="model ? 'color:var(--tp-success)' : ''">{{ model ? `v${model.version}` : 'None' }}</div>
          <div v-if="model" class="stat-sub">{{ model.model_type }}</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Accuracy</div>
          <div class="stat-value" :style="model && model.accuracy > 0.55 ? 'color:var(--tp-success)' : ''">{{ model ? fmtPct(model.accuracy) : '-' }}</div>
          <div v-if="model" class="stat-sub">CV: {{ fmtPct(model.cv_accuracy) }} &plusmn; {{ fmtPct(model.cv_std) }}</div>
        </div>
        <div class="tp-stat-card" v-if="model && model.walk_forward_accuracy != null">
          <div class="stat-label">Walk-Forward</div>
          <div class="stat-value" :style="model.walk_forward_accuracy > 0.55 ? 'color:var(--tp-success)' : model.walk_forward_accuracy > 0.50 ? 'color:var(--tp-warning)' : 'color:var(--tp-danger)'">{{ fmtPct(model.walk_forward_accuracy) }}</div>
          <div class="stat-sub">No future leakage</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Training Data</div>
          <div class="stat-value">{{ features.labeled || 0 }}</div>
          <div class="stat-sub"><span style="color:var(--tp-success)">{{ features.wins || 0 }}W</span> / <span style="color:var(--tp-danger)">{{ features.losses || 0 }}L</span></div>
        </div>
        <div class="tp-stat-card" v-if="predictionAccuracy !== null">
          <div class="stat-label">Prediction Acc</div>
          <div class="stat-value" :style="parseFloat(predictionAccuracy) > 55 ? 'color:var(--tp-success)' : ''">{{ predictionAccuracy }}%</div>
          <div class="stat-sub">{{ resolvedPredictions.length }} resolved</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">ML Rejected</div>
          <div class="stat-value" style="color:var(--tp-warning)">{{ features.ml_rejected || 0 }}</div>
          <div class="stat-sub">Blocked by scorer</div>
        </div>
      </div>

      <!-- Tabs -->
      <div class="tp-tabs" style="padding-left:1.15rem;padding-right:1.15rem;">
        <button v-for="tab in ['overview', 'predictions', 'features', 'history']" :key="tab"
          :class="{ active: activeTab === tab }" @click="activeTab = tab">
          {{ tab.charAt(0).toUpperCase() + tab.slice(1) }}
        </button>
      </div>

      <!-- ========== OVERVIEW TAB ========== -->
      <template v-if="activeTab === 'overview'">
        <!-- No Model Yet -->
        <div v-if="!model" class="tp-card ml-empty-state">
          <span class="material-symbols-outlined" style="font-size:2.5rem;color:var(--tp-text-dim)">model_training</span>
          <p class="empty-title">Collecting Training Data</p>
          <p class="empty-desc">
            Auto-trains after {{ 30 - (features.labeled || 0) > 0 ? 30 - (features.labeled || 0) : 0 }} more trades.
            Currently {{ features.labeled || 0 }} / 30.
          </p>
          <div class="progress-wrap">
            <div class="progress-bar" :style="{ width: Math.min((features.labeled || 0) / 30 * 100, 100) + '%' }"></div>
          </div>
        </div>

        <!-- Row 1: Confusion Matrix + Score Distribution -->
        <div v-if="confusionMatrix || scoreDistribution.length" class="ml-chart-row">
          <!-- Confusion Matrix with PnL -->
          <div v-if="confusionMatrix" class="tp-card ml-chart-card">
            <h4>Confusion Matrix</h4>
            <p class="chart-desc">Model prediction accuracy on {{ confusionMatrix.total }} resolved trades</p>
            <div class="cm-grid">
              <div class="cm-corner"></div>
              <div class="cm-header">Predicted WIN</div>
              <div class="cm-header">Predicted LOSS</div>
              <div class="cm-row-label">Actual WIN</div>
              <div class="cm-cell cm-tp" :title="`True Positive: ${confusionMatrix.tp}`">
                <span class="cm-val">{{ confusionMatrix.tp }}</span>
                <span class="cm-tag">TP</span>
                <span v-if="confusionPnl && confusionPnl.tp.n" class="cm-pnl" :style="pnlColor(confusionPnl.tp.avg)">
                  avg {{ fmtDollar(confusionPnl.tp.avg) }}
                </span>
              </div>
              <div class="cm-cell cm-fn" :title="`False Negative: ${confusionMatrix.fn}`">
                <span class="cm-val">{{ confusionMatrix.fn }}</span>
                <span class="cm-tag">FN</span>
                <span v-if="confusionPnl && confusionPnl.fn.n" class="cm-pnl" :style="pnlColor(confusionPnl.fn.avg)">
                  avg {{ fmtDollar(confusionPnl.fn.avg) }}
                </span>
              </div>
              <div class="cm-row-label">Actual LOSS</div>
              <div class="cm-cell cm-fp" :title="`False Positive: ${confusionMatrix.fp}`">
                <span class="cm-val">{{ confusionMatrix.fp }}</span>
                <span class="cm-tag">FP</span>
                <span v-if="confusionPnl && confusionPnl.fp.n" class="cm-pnl" :style="pnlColor(confusionPnl.fp.avg)">
                  avg {{ fmtDollar(confusionPnl.fp.avg) }}
                </span>
              </div>
              <div class="cm-cell cm-tn" :title="`True Negative: ${confusionMatrix.tn}`">
                <span class="cm-val">{{ confusionMatrix.tn }}</span>
                <span class="cm-tag">TN</span>
                <span v-if="confusionPnl && confusionPnl.tn.n" class="cm-pnl" :style="pnlColor(confusionPnl.tn.avg)">
                  avg {{ fmtDollar(confusionPnl.tn.avg) }}
                </span>
              </div>
            </div>
            <div class="cm-summary">
              <span>Precision: <strong>{{ confusionMatrix.tp + confusionMatrix.fp > 0 ? ((confusionMatrix.tp / (confusionMatrix.tp + confusionMatrix.fp)) * 100).toFixed(0) + '%' : '-' }}</strong></span>
              <span>Recall: <strong>{{ confusionMatrix.tp + confusionMatrix.fn > 0 ? ((confusionMatrix.tp / (confusionMatrix.tp + confusionMatrix.fn)) * 100).toFixed(0) + '%' : '-' }}</strong></span>
            </div>
          </div>

          <!-- Score Distribution -->
          <div v-if="scoreDistribution.length" class="tp-card ml-chart-card">
            <h4>Score Distribution</h4>
            <p class="chart-desc">How model scores separate wins from losses</p>
            <div class="sd-chart">
              <div v-for="b in scoreDistribution" :key="b.label" class="sd-col">
                <div class="sd-bar-stack">
                  <div class="sd-bar sd-loss" :style="{ height: (b.losses / scoreDistMax * 100) + '%' }"></div>
                  <div class="sd-bar sd-win" :style="{ height: (b.wins / scoreDistMax * 100) + '%' }"></div>
                </div>
                <span class="sd-label">.{{ b.label }}</span>
              </div>
            </div>
            <div class="sd-legend">
              <span class="sd-leg-item"><span class="sd-dot sd-dot-win"></span> Win</span>
              <span class="sd-leg-item"><span class="sd-dot sd-dot-loss"></span> Loss</span>
            </div>
          </div>
        </div>

        <!-- Row 2: Score vs PnL Scatter + Threshold Analyzer -->
        <div class="ml-chart-row" style="margin-top:1rem;">
          <!-- Score vs PnL Scatter -->
          <div v-if="scorePnlData.points.length > 2" class="tp-card ml-chart-card">
            <h4>Confidence vs Returns</h4>
            <p class="chart-desc">Does higher ML score produce better PnL?</p>
            <div class="scatter-wrap">
              <div class="scatter-y-axis">
                <span>{{ fmtDollar(scorePnlData.maxPnl) }}</span>
                <span style="color:var(--tp-text-dim)">$0</span>
                <span>{{ fmtDollar(scorePnlData.minPnl) }}</span>
              </div>
              <div class="scatter-container">
                <!-- Zero line -->
                <div class="scatter-zero" :style="{ bottom: scorePnlData.zeroNorm + '%' }"></div>
                <!-- Threshold line at 0.5 -->
                <div class="scatter-threshold" style="left:50%"></div>
                <!-- Dots -->
                <div v-for="(d, i) in scorePnlData.points" :key="i"
                  class="scatter-dot"
                  :class="d.win ? 'dot-win' : 'dot-loss'"
                  :style="{ left: d.xPct + '%', bottom: d.yPct + '%' }"
                  :title="`${d.symbol} | Score: ${d.score.toFixed(2)} | PnL: $${d.pnl.toFixed(2)}`"
                ></div>
              </div>
            </div>
            <div class="scatter-x-axis">
              <span>0.0</span>
              <span>0.5</span>
              <span>1.0</span>
            </div>
            <div class="chart-axis-label">ML Score</div>
            <div class="scatter-legend">
              <span class="sd-leg-item"><span class="sd-dot sd-dot-win"></span> Win</span>
              <span class="sd-leg-item"><span class="sd-dot sd-dot-loss"></span> Loss</span>
              <span class="sd-leg-item"><span class="scatter-leg-line scatter-leg-zero"></span> $0 line</span>
              <span class="sd-leg-item"><span class="scatter-leg-line scatter-leg-thresh"></span> Threshold</span>
            </div>
          </div>

          <!-- Threshold Analyzer -->
          <div v-if="thresholdAnalysis.length" class="tp-card ml-chart-card">
            <h4>Threshold Simulator</h4>
            <p class="chart-desc">Impact of different ML score cutoffs on trading performance</p>
            <div class="thresh-table-wrap">
              <table class="thresh-table">
                <thead>
                  <tr>
                    <th>Cutoff</th>
                    <th>Trades</th>
                    <th>Win Rate</th>
                    <th>Total PnL</th>
                    <th>Avg PnL</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="t in thresholdAnalysis" :key="t.threshold"
                    :class="{ 'thresh-current': t.isCurrent }">
                    <td class="thresh-val">
                      {{ t.threshold.toFixed(2) }}
                      <span v-if="t.isCurrent" class="thresh-badge">current</span>
                    </td>
                    <td>{{ t.accepted }}<span class="thresh-dim"> / {{ t.accepted + t.rejected }}</span></td>
                    <td :style="parseFloat(t.winRate) >= 55 ? 'color:var(--tp-success);font-weight:700' : parseFloat(t.winRate) < 45 ? 'color:var(--tp-danger)' : ''">
                      {{ t.winRate }}%
                    </td>
                    <td :style="pnlColor(parseFloat(t.pnl))">
                      {{ parseFloat(t.pnl) >= 0 ? '+' : '' }}${{ t.pnl }}
                    </td>
                    <td :style="pnlColor(parseFloat(t.avgPnl))">
                      {{ parseFloat(t.avgPnl) >= 0 ? '+' : '' }}${{ t.avgPnl }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="thresh-hint">Raise the threshold to reject low-confidence trades. Watch for trade count vs quality tradeoff.</p>
          </div>
        </div>

        <!-- Row 3: Calibration + Training Balance -->
        <div class="ml-chart-row" style="margin-top:1rem;">
          <!-- Prediction Calibration -->
          <div v-if="calibrationBuckets.length" class="tp-card ml-chart-card">
            <h4>Prediction Calibration</h4>
            <p class="chart-desc">Actual win rate vs predicted confidence — perfect calibration = diagonal</p>
            <div class="cal-chart">
              <div v-for="b in calibrationBuckets" :key="b.label" class="cal-bucket">
                <div class="cal-bar-wrap">
                  <div class="cal-bar" :style="{
                    height: b.winRate + '%',
                    background: b.winRate > 55 ? 'var(--tp-success)' : b.winRate > 45 ? 'var(--tp-warning)' : 'var(--tp-danger)',
                  }">
                    <span class="cal-val">{{ b.winRate.toFixed(0) }}%</span>
                  </div>
                </div>
                <span class="cal-label">{{ b.label }}</span>
                <span class="cal-n">n={{ b.total }}</span>
              </div>
            </div>
          </div>

          <!-- Training Balance -->
          <div v-if="trainBalance" class="tp-card ml-chart-card">
            <h4>Training Balance</h4>
            <p class="chart-desc">Win/loss ratio in training data — imbalance affects model bias</p>
            <div class="bal-ring-wrap">
              <div class="bal-ring" :style="{
                background: `conic-gradient(var(--tp-success) 0deg ${trainBalance.winDeg}deg, var(--tp-danger) ${trainBalance.winDeg}deg 360deg)`
              }">
                <div class="bal-ring-inner">
                  <span class="bal-total">{{ trainBalance.total }}</span>
                  <span class="bal-sub">trades</span>
                </div>
              </div>
              <div class="bal-legend">
                <div class="bal-leg-row">
                  <span class="bal-dot" style="background:var(--tp-success)"></span>
                  <span>Wins</span>
                  <strong style="color:var(--tp-success)">{{ trainBalance.wins }} ({{ trainBalance.winPct }}%)</strong>
                </div>
                <div class="bal-leg-row">
                  <span class="bal-dot" style="background:var(--tp-danger)"></span>
                  <span>Losses</span>
                  <strong style="color:var(--tp-danger)">{{ trainBalance.losses }} ({{ trainBalance.lossPct }}%)</strong>
                </div>
              </div>
            </div>

            <!-- Symbol Breakdown Mini with PnL -->
            <div v-if="symbolStats.length" class="sym-mini">
              <h5>Per-Symbol Performance</h5>
              <div v-for="s in symbolStats" :key="s.symbol" class="sym-row">
                <span class="sym-name">{{ s.symbol }}</span>
                <div class="sym-bar-bg">
                  <div class="sym-bar-fill" :style="{ width: (s.wins / s.total * 100) + '%' }"></div>
                </div>
                <span class="sym-wr" :style="s.wins / s.total >= 0.5 ? 'color:var(--tp-success)' : 'color:var(--tp-danger)'">
                  {{ (s.wins / s.total * 100).toFixed(0) }}%
                </span>
                <span class="sym-pnl" :style="pnlColor(s.pnl)">{{ fmtDollar(s.pnl) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Learning Curve -->
        <div class="tp-card" v-if="learningCurve.length > 0" style="margin-top:1rem;">
          <h4>Learning Curve</h4>
          <p class="chart-desc">Model accuracy as training data grows</p>
          <div class="learning-curve-chart">
            <div v-for="(point, i) in learningCurve" :key="i" class="lc-bar-container">
              <div class="lc-bar" :style="{
                height: (point.accuracy * 100) + '%',
                background: point.accuracy > 0.55 ? 'var(--tp-success)' : point.accuracy > 0.5 ? 'var(--tp-warning)' : 'var(--tp-danger)'
              }">
                <span class="lc-label">{{ (point.accuracy * 100).toFixed(0) }}%</span>
              </div>
              <span class="lc-x-label">{{ point.trades }}</span>
            </div>
          </div>
          <div class="chart-axis-label">Number of training trades</div>
        </div>

        <!-- Model Details -->
        <div v-if="model" class="tp-card" style="margin-top:1rem;">
          <h4>Active Model Details</h4>
          <div class="detail-grid">
            <div class="detail-item">
              <span class="detail-label">Version</span>
              <span class="detail-val">v{{ model.version }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Type</span>
              <span class="detail-val"><span class="model-type-inline" :class="modelTypeClass">{{ model.model_type }}</span></span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Training Trades</span>
              <span class="detail-val">{{ model.trade_count }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Accuracy</span>
              <span class="detail-val">{{ fmtPct(model.accuracy) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Cross-Validated</span>
              <span class="detail-val">{{ fmtPct(model.cv_accuracy) }} &plusmn; {{ fmtPct(model.cv_std) }}</span>
            </div>
            <div class="detail-item" v-if="model.walk_forward_accuracy != null">
              <span class="detail-label">Walk-Forward</span>
              <span class="detail-val" :style="model.walk_forward_accuracy > 0.55 ? 'color:var(--tp-success);font-weight:700' : ''">
                {{ fmtPct(model.walk_forward_accuracy) }}
              </span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Precision</span>
              <span class="detail-val">{{ fmtPct(model.precision) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Recall</span>
              <span class="detail-val">{{ fmtPct(model.recall) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">F1 Score</span>
              <span class="detail-val">{{ fmtPct(model.f1_score) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Baseline WR</span>
              <span class="detail-val">{{ fmtPct(model.win_rate_baseline) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Trained At</span>
              <span class="detail-val">{{ fmtTime(model.trained_at) }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- ========== FEATURES TAB ========== -->
      <template v-if="activeTab === 'features'">
        <!-- SHAP Diverging Impact Chart -->
        <div class="tp-card" v-if="shapDivergingData.length > 0">
          <h4>SHAP Feature Impact</h4>
          <p class="chart-desc">Signed directional influence — features pushing toward WIN (right) vs LOSS (left)</p>
          <div class="shap-diverging">
            <div v-for="item in shapDivergingData" :key="item.feature" class="shap-div-row">
              <span class="shap-div-name">{{ item.feature.replace(/_/g, ' ') }}</span>
              <div class="shap-div-track">
                <div class="shap-div-center"></div>
                <div class="shap-div-bar"
                  :class="item.positive ? 'shap-positive' : 'shap-negative'"
                  :style="{
                    width: item.barPct + '%',
                    [item.positive ? 'left' : 'right']: '50%',
                  }">
                </div>
              </div>
              <span class="shap-div-val" :style="item.positive ? 'color:var(--tp-success)' : 'color:var(--tp-danger)'">
                {{ item.positive ? '+' : '' }}{{ (item.mean_signed * 100).toFixed(2) }}
              </span>
            </div>
            <div class="shap-div-axis">
              <span class="shap-axis-loss">LOSS</span>
              <span class="shap-axis-zero">0</span>
              <span class="shap-axis-win">WIN</span>
            </div>
          </div>
        </div>

        <!-- Feature Importance Bars -->
        <div class="tp-card" v-if="topFeatures.length > 0" style="margin-top:1rem;">
          <h4>Feature Importance (Absolute)</h4>
          <p class="chart-desc">Magnitude of influence regardless of direction. Higher = more impact on predictions.</p>
          <div class="feature-bars">
            <div v-for="([name, importance], i) in topFeatures" :key="name" class="feature-row">
              <span class="feature-rank">{{ i + 1 }}</span>
              <span class="feature-name">{{ name.replace(/_/g, ' ') }}</span>
              <div class="feature-bar-bg">
                <div class="feature-bar-fill" :style="{
                  width: (importance / topFeatures[0][1] * 100) + '%',
                  background: i < 3 ? 'var(--tp-primary)' : i < 6 ? 'rgba(99,102,241,0.5)' : 'var(--tp-text-dim)',
                }"></div>
              </div>
              <span class="feature-value">{{ (importance * 100).toFixed(1) }}%</span>
            </div>
          </div>
        </div>

        <!-- Feature Direction Analysis Table -->
        <div class="tp-card" v-if="shapSummary.length > 0" style="margin-top:1rem;">
          <h4>Feature Direction Details</h4>
          <p class="chart-desc">Raw SHAP values — positive pushes toward WIN, negative toward LOSS</p>
          <div class="table-responsive">
            <table class="ml-table">
              <thead>
                <tr>
                  <th>Feature</th>
                  <th>Impact</th>
                  <th>Direction</th>
                  <th>Consistency</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in shapSummary" :key="s.feature">
                  <td>{{ s.feature.replace(/_/g, ' ') }}</td>
                  <td>{{ (s.mean_abs * 100).toFixed(2) }}%</td>
                  <td :style="s.mean_signed > 0 ? 'color:var(--tp-success)' : s.mean_signed < 0 ? 'color:var(--tp-danger)' : ''">
                    {{ s.mean_signed > 0 ? 'WIN' : s.mean_signed < 0 ? 'LOSS' : 'Neutral' }}
                  </td>
                  <td style="color:var(--tp-text-dim)">&plusmn;{{ (s.std * 100).toFixed(2) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-if="topFeatures.length === 0 && shapDivergingData.length === 0" class="tp-card ml-empty-state">
          <span class="material-symbols-outlined" style="font-size:2rem;color:var(--tp-text-dim)">analytics</span>
          <p class="empty-desc">Feature importance appears after first model training.</p>
        </div>
      </template>

      <!-- ========== PREDICTIONS TAB ========== -->
      <template v-if="activeTab === 'predictions'">
        <div class="tp-card">
          <h4>Recent Predictions</h4>
          <div v-if="predictions.length === 0" class="ml-empty-state" style="padding:2rem 0;">
            <p class="empty-desc">Trades appear here as they are scored by the model.</p>
          </div>
          <div v-else class="table-responsive">
            <table class="ml-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>ML Score</th>
                  <th>Accepted</th>
                  <th>Outcome</th>
                  <th>PnL</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in predictions" :key="p.trade_id">
                  <td>{{ fmtTime(p.entry_time) }}</td>
                  <td><strong>{{ p.symbol }}</strong></td>
                  <td :style="p.type === 'BUY' ? 'color:var(--tp-success)' : 'color:var(--tp-danger)'">{{ p.type }}</td>
                  <td :style="scoreColor(p.ml_score)">{{ p.ml_score !== null ? p.ml_score.toFixed(2) : '-' }}</td>
                  <td>
                    <span v-if="p.ml_accepted === true" style="color:var(--tp-success)">YES</span>
                    <span v-else-if="p.ml_accepted === false" style="color:var(--tp-danger)">NO</span>
                    <span v-else style="color:var(--tp-text-dim)">-</span>
                  </td>
                  <td>
                    <span v-if="p.actual_win === true" class="outcome-badge win">WIN</span>
                    <span v-else-if="p.actual_win === false" class="outcome-badge loss">LOSS</span>
                    <span v-else class="outcome-badge open">OPEN</span>
                  </td>
                  <td :style="pnlColor(p.pnl)">{{ p.pnl !== null ? '$' + p.pnl.toFixed(2) : '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <!-- ========== HISTORY TAB ========== -->
      <template v-if="activeTab === 'history'">
        <!-- Model Evolution Chart -->
        <div v-if="history.length > 1" class="tp-card" style="margin-bottom:1rem;">
          <h4>Model Evolution</h4>
          <p class="chart-desc">Accuracy across model versions</p>
          <div class="evo-chart">
            <div v-for="(m, i) in history" :key="m.version" class="evo-col">
              <div class="evo-bar-wrap">
                <div class="evo-bar" :style="{
                  height: ((m.accuracy || 0) * 100) + '%',
                  background: m.is_active ? 'var(--tp-primary)' : 'var(--tp-text-dim)',
                  opacity: m.is_active ? 1 : 0.5,
                }">
                  <span class="evo-val">{{ ((m.accuracy || 0) * 100).toFixed(0) }}%</span>
                </div>
              </div>
              <span class="evo-label">v{{ m.version }}</span>
            </div>
          </div>
        </div>

        <div class="tp-card">
          <h4>Version History</h4>
          <div v-if="history.length === 0" class="ml-empty-state" style="padding:2rem 0;">
            <p class="empty-desc">No models trained yet.</p>
          </div>
          <div v-else class="table-responsive">
            <table class="ml-table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Type</th>
                  <th>Trades</th>
                  <th>Accuracy</th>
                  <th>CV Acc</th>
                  <th>WF Acc</th>
                  <th>Trained</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in history" :key="m.version" :class="{ 'row-active': m.is_active }">
                  <td><strong>v{{ m.version }}</strong></td>
                  <td><span class="model-type-inline" :class="modelTypeClassFor(m.model_type)">{{ m.model_type }}</span></td>
                  <td>{{ m.trade_count }}</td>
                  <td :style="m.accuracy > 0.55 ? 'color:var(--tp-success)' : ''">{{ fmtPct(m.accuracy) }}</td>
                  <td>{{ fmtPct(m.cv_accuracy) }}</td>
                  <td :style="m.walk_forward_accuracy > 0.55 ? 'color:var(--tp-success);font-weight:700' : ''">
                    {{ m.walk_forward_accuracy != null ? fmtPct(m.walk_forward_accuracy) : '-' }}
                  </td>
                  <td>{{ fmtTime(m.trained_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <!-- LLM Fine-Tuning (always visible) -->
      <div class="tp-card" style="margin-top:1rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <h4>LLM Fine-Tuning Pipeline</h4>
            <p class="chart-desc">Every closed trade generates an instruction-tuning example for local LLM fine-tuning.</p>
          </div>
          <button class="tp-btn tp-btn-outline" @click="refreshLLM" :disabled="llmRefreshing">
            <span class="material-symbols-outlined" :class="{ spinning: llmRefreshing }" style="font-size:16px">refresh</span>
            {{ llmRefreshing ? 'Syncing...' : 'Sync' }}
          </button>
        </div>
        <div class="llm-grid">
          <div class="llm-stat">
            <span class="llm-val">{{ llm.total_examples || 0 }}</span>
            <span class="llm-label">Examples</span>
          </div>
          <div class="llm-stat">
            <span class="llm-val">{{ llm.file_size_kb || 0 }} KB</span>
            <span class="llm-label">File Size</span>
          </div>
          <div class="llm-stat">
            <span class="llm-val" style="color:var(--tp-success)">{{ llm.wins || 0 }}</span>
            <span class="llm-label">Win Examples</span>
          </div>
          <div class="llm-stat">
            <span class="llm-val" style="color:var(--tp-danger)">{{ llm.losses || 0 }}</span>
            <span class="llm-label">Loss Examples</span>
          </div>
        </div>
      </div>
    </template>
    </template>

    <!-- ===== CRYPTO ML TAB ===== -->
    <template v-if="activeMLTab === 'crypto'">
    <div v-if="loading" class="ml-loading">Loading Crypto ML data...</div>

    <template v-else>
      <!-- Stats Strip -->
      <div class="tp-stats-grid" style="margin-bottom:1.25rem;padding-left:1.15rem;padding-right:1.15rem;">
        <div class="tp-stat-card">
          <div class="stat-label">Model</div>
          <div class="stat-value" :style="cryptoModel ? 'color:var(--tp-success)' : ''">{{ cryptoModel ? `v${cryptoModel.version}` : 'Collecting' }}</div>
          <div v-if="cryptoModel" class="stat-sub">{{ cryptoModel.model_type }}</div>
          <div v-else class="stat-sub">{{ cryptoFeatures.labeled || 0 }} / 200 trades</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Accuracy</div>
          <div class="stat-value" :style="cryptoModel && cryptoModel.accuracy > 0.55 ? 'color:var(--tp-success)' : ''">{{ cryptoModel ? fmtPct(cryptoModel.accuracy) : '-' }}</div>
          <div v-if="cryptoModel" class="stat-sub">CV: {{ fmtPct(cryptoModel.cv_accuracy) }}</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Training Data</div>
          <div class="stat-value">{{ cryptoFeatures.labeled || 0 }}</div>
          <div class="stat-sub"><span style="color:var(--tp-success)">{{ cryptoFeatures.wins || 0 }}W</span> / <span style="color:var(--tp-danger)">{{ cryptoFeatures.losses || 0 }}L</span></div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Win Rate</div>
          <div class="stat-value" :style="cryptoTrainBalance && parseInt(cryptoTrainBalance.winPct) >= 55 ? 'color:var(--tp-success)' : ''">
            {{ cryptoTrainBalance ? cryptoTrainBalance.winPct + '%' : '-' }}
          </div>
          <div v-if="cryptoTrainBalance" class="stat-sub">{{ cryptoTrainBalance.wins }}W / {{ cryptoTrainBalance.losses }}L</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Net P&L</div>
          <div class="stat-value" :style="pnlColor(cryptoNetPnl)">{{ cryptoNetPnl !== null ? fmtDollar(cryptoNetPnl) : '-' }}</div>
          <div class="stat-sub">Resolved trades</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">ML Rejected</div>
          <div class="stat-value" style="color:var(--tp-warning)">{{ cryptoFeatures.ml_rejected || 0 }}</div>
          <div class="stat-sub">Blocked by scorer</div>
        </div>
      </div>

      <!-- Tabs -->
      <div class="tp-tabs" style="padding-left:1.15rem;padding-right:1.15rem;">
        <button v-for="tab in ['overview', 'predictions', 'features', 'history']" :key="tab"
          :class="{ active: activeCryptoTab === tab }" @click="activeCryptoTab = tab">
          {{ tab.charAt(0).toUpperCase() + tab.slice(1) }}
        </button>
      </div>

      <!-- ========== CRYPTO OVERVIEW TAB ========== -->
      <template v-if="activeCryptoTab === 'overview'">
        <!-- No Model Yet — Collecting State -->
        <div v-if="!cryptoModel" class="tp-card ml-empty-state">
          <span class="material-symbols-outlined" style="font-size:2.5rem;color:var(--tp-text-dim)">model_training</span>
          <p class="empty-title">Collecting Training Data</p>
          <p class="empty-desc">
            Auto-trains after {{ 200 - (cryptoFeatures.labeled || 0) > 0 ? 200 - (cryptoFeatures.labeled || 0) : 0 }} more trades.
            Currently {{ cryptoFeatures.labeled || 0 }} / 200.
          </p>
          <div class="progress-wrap">
            <div class="progress-bar" :style="{ width: Math.min((cryptoFeatures.labeled || 0) / 200 * 100, 100) + '%' }"></div>
          </div>
        </div>

        <!-- Row 1: Confusion Matrix + Score Distribution -->
        <div v-if="cryptoConfusionMatrix || cryptoScoreDistribution.length" class="ml-chart-row">
          <!-- Confusion Matrix with PnL -->
          <div v-if="cryptoConfusionMatrix" class="tp-card ml-chart-card">
            <h4>Confusion Matrix</h4>
            <p class="chart-desc">Prediction accuracy on {{ cryptoConfusionMatrix.total }} resolved trades</p>
            <div class="cm-grid">
              <div class="cm-corner"></div>
              <div class="cm-header">Predicted WIN</div>
              <div class="cm-header">Predicted LOSS</div>
              <div class="cm-row-label">Actual WIN</div>
              <div class="cm-cell cm-tp" :title="`True Positive: ${cryptoConfusionMatrix.tp}`">
                <span class="cm-val">{{ cryptoConfusionMatrix.tp }}</span>
                <span class="cm-tag">TP</span>
                <span v-if="cryptoConfusionPnl && cryptoConfusionPnl.tp.n" class="cm-pnl" :style="pnlColor(cryptoConfusionPnl.tp.avg)">
                  avg {{ fmtDollar(cryptoConfusionPnl.tp.avg) }}
                </span>
              </div>
              <div class="cm-cell cm-fn" :title="`False Negative: ${cryptoConfusionMatrix.fn}`">
                <span class="cm-val">{{ cryptoConfusionMatrix.fn }}</span>
                <span class="cm-tag">FN</span>
                <span v-if="cryptoConfusionPnl && cryptoConfusionPnl.fn.n" class="cm-pnl" :style="pnlColor(cryptoConfusionPnl.fn.avg)">
                  avg {{ fmtDollar(cryptoConfusionPnl.fn.avg) }}
                </span>
              </div>
              <div class="cm-row-label">Actual LOSS</div>
              <div class="cm-cell cm-fp" :title="`False Positive: ${cryptoConfusionMatrix.fp}`">
                <span class="cm-val">{{ cryptoConfusionMatrix.fp }}</span>
                <span class="cm-tag">FP</span>
                <span v-if="cryptoConfusionPnl && cryptoConfusionPnl.fp.n" class="cm-pnl" :style="pnlColor(cryptoConfusionPnl.fp.avg)">
                  avg {{ fmtDollar(cryptoConfusionPnl.fp.avg) }}
                </span>
              </div>
              <div class="cm-cell cm-tn" :title="`True Negative: ${cryptoConfusionMatrix.tn}`">
                <span class="cm-val">{{ cryptoConfusionMatrix.tn }}</span>
                <span class="cm-tag">TN</span>
                <span v-if="cryptoConfusionPnl && cryptoConfusionPnl.tn.n" class="cm-pnl" :style="pnlColor(cryptoConfusionPnl.tn.avg)">
                  avg {{ fmtDollar(cryptoConfusionPnl.tn.avg) }}
                </span>
              </div>
            </div>
            <div class="cm-summary">
              <span>Precision: <strong>{{ cryptoConfusionMatrix.tp + cryptoConfusionMatrix.fp > 0 ? ((cryptoConfusionMatrix.tp / (cryptoConfusionMatrix.tp + cryptoConfusionMatrix.fp)) * 100).toFixed(0) + '%' : '-' }}</strong></span>
              <span>Recall: <strong>{{ cryptoConfusionMatrix.tp + cryptoConfusionMatrix.fn > 0 ? ((cryptoConfusionMatrix.tp / (cryptoConfusionMatrix.tp + cryptoConfusionMatrix.fn)) * 100).toFixed(0) + '%' : '-' }}</strong></span>
            </div>
          </div>

          <!-- Score Distribution -->
          <div v-if="cryptoScoreDistribution.length" class="tp-card ml-chart-card">
            <h4>Score Distribution</h4>
            <p class="chart-desc">How model scores separate wins from losses</p>
            <div class="sd-chart">
              <div v-for="b in cryptoScoreDistribution" :key="b.label" class="sd-col">
                <div class="sd-bar-stack">
                  <div class="sd-bar sd-loss" :style="{ height: (b.losses / cryptoScoreDistMax * 100) + '%' }"></div>
                  <div class="sd-bar sd-win" :style="{ height: (b.wins / cryptoScoreDistMax * 100) + '%' }"></div>
                </div>
                <span class="sd-label">.{{ b.label }}</span>
              </div>
            </div>
            <div class="sd-legend">
              <span class="sd-leg-item"><span class="sd-dot sd-dot-win"></span> Win</span>
              <span class="sd-leg-item"><span class="sd-dot sd-dot-loss"></span> Loss</span>
            </div>
          </div>
        </div>

        <!-- Row 2: Confidence vs Returns + Threshold Simulator -->
        <div class="ml-chart-row" style="margin-top:1rem;">
          <!-- Confidence vs Returns Scatter -->
          <div v-if="cryptoScorePnlData.points.length > 2" class="tp-card ml-chart-card">
            <h4>Confidence vs Returns</h4>
            <p class="chart-desc">Does higher ML score produce better PnL?</p>
            <div class="scatter-wrap">
              <div class="scatter-y-axis">
                <span>{{ fmtDollar(cryptoScorePnlData.maxPnl) }}</span>
                <span style="color:var(--tp-text-dim)">$0</span>
                <span>{{ fmtDollar(cryptoScorePnlData.minPnl) }}</span>
              </div>
              <div class="scatter-container">
                <!-- Zero line -->
                <div class="scatter-zero" :style="{ bottom: cryptoScorePnlData.zeroNorm + '%' }"></div>
                <!-- Threshold line at 0.5 -->
                <div class="scatter-threshold" style="left:50%"></div>
                <!-- Dots -->
                <div v-for="(d, i) in cryptoScorePnlData.points" :key="i"
                  class="scatter-dot"
                  :class="d.win ? 'dot-win' : 'dot-loss'"
                  :style="{ left: d.xPct + '%', bottom: d.yPct + '%' }"
                  :title="`${d.symbol} | Score: ${d.score.toFixed(2)} | PnL: $${d.pnl.toFixed(2)}`"
                ></div>
              </div>
            </div>
            <div class="scatter-x-axis">
              <span>0.0</span>
              <span>0.5</span>
              <span>1.0</span>
            </div>
            <div class="chart-axis-label">ML Score</div>
            <div class="scatter-legend">
              <span class="sd-leg-item"><span class="sd-dot sd-dot-win"></span> Win</span>
              <span class="sd-leg-item"><span class="sd-dot sd-dot-loss"></span> Loss</span>
              <span class="sd-leg-item"><span class="scatter-leg-line scatter-leg-zero"></span> $0 line</span>
              <span class="sd-leg-item"><span class="scatter-leg-line scatter-leg-thresh"></span> Threshold</span>
            </div>
          </div>

          <!-- Threshold Simulator -->
          <div v-if="cryptoThresholdAnalysis.length" class="tp-card ml-chart-card">
            <h4>Threshold Simulator</h4>
            <p class="chart-desc">Impact of different ML score cutoffs on trading performance</p>
            <div class="thresh-table-wrap">
              <table class="thresh-table">
                <thead>
                  <tr>
                    <th>Cutoff</th>
                    <th>Trades</th>
                    <th>Win Rate</th>
                    <th>Total PnL</th>
                    <th>Avg PnL</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="t in cryptoThresholdAnalysis" :key="t.threshold"
                    :class="{ 'thresh-current': t.isCurrent }">
                    <td class="thresh-val">
                      {{ t.threshold.toFixed(2) }}
                      <span v-if="t.isCurrent" class="thresh-badge">current</span>
                    </td>
                    <td>{{ t.accepted }}<span class="thresh-dim"> / {{ t.accepted + t.rejected }}</span></td>
                    <td :style="parseFloat(t.winRate) >= 55 ? 'color:var(--tp-success);font-weight:700' : parseFloat(t.winRate) < 45 ? 'color:var(--tp-danger)' : ''">
                      {{ t.winRate }}%
                    </td>
                    <td :style="pnlColor(parseFloat(t.pnl))">
                      {{ parseFloat(t.pnl) >= 0 ? '+' : '' }}${{ t.pnl }}
                    </td>
                    <td :style="pnlColor(parseFloat(t.avgPnl))">
                      {{ parseFloat(t.avgPnl) >= 0 ? '+' : '' }}${{ t.avgPnl }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="thresh-hint">Raise the threshold to reject low-confidence trades. Watch for trade count vs quality tradeoff.</p>
          </div>
        </div>

        <!-- Row 3: Calibration + Training Balance -->
        <div class="ml-chart-row" style="margin-top:1rem;">
          <!-- Prediction Calibration -->
          <div v-if="cryptoCalibrationBuckets.length" class="tp-card ml-chart-card">
            <h4>Prediction Calibration</h4>
            <p class="chart-desc">Actual win rate vs predicted confidence — perfect calibration = diagonal</p>
            <div class="cal-chart">
              <div v-for="b in cryptoCalibrationBuckets" :key="b.label" class="cal-bucket">
                <div class="cal-bar-wrap">
                  <div class="cal-bar" :style="{
                    height: b.winRate + '%',
                    background: b.winRate > 55 ? 'var(--tp-success)' : b.winRate > 45 ? 'var(--tp-warning)' : 'var(--tp-danger)',
                  }">
                    <span class="cal-val">{{ b.winRate.toFixed(0) }}%</span>
                  </div>
                </div>
                <span class="cal-label">{{ b.label }}</span>
                <span class="cal-n">n={{ b.total }}</span>
              </div>
            </div>
          </div>

          <!-- Training Balance -->
          <div v-if="cryptoTrainBalance" class="tp-card ml-chart-card">
            <h4>Training Balance</h4>
            <p class="chart-desc">Win/loss ratio in training data — imbalance affects model bias</p>
            <div class="bal-ring-wrap">
              <div class="bal-ring" :style="{
                background: `conic-gradient(var(--tp-success) 0deg ${cryptoTrainBalance.winDeg}deg, var(--tp-danger) ${cryptoTrainBalance.winDeg}deg 360deg)`
              }">
                <div class="bal-ring-inner">
                  <span class="bal-total">{{ cryptoTrainBalance.total }}</span>
                  <span class="bal-sub">trades</span>
                </div>
              </div>
              <div class="bal-legend">
                <div class="bal-leg-row">
                  <span class="bal-dot" style="background:var(--tp-success)"></span>
                  <span>Wins</span>
                  <strong style="color:var(--tp-success)">{{ cryptoTrainBalance.wins }} ({{ cryptoTrainBalance.winPct }}%)</strong>
                </div>
                <div class="bal-leg-row">
                  <span class="bal-dot" style="background:var(--tp-danger)"></span>
                  <span>Losses</span>
                  <strong style="color:var(--tp-danger)">{{ cryptoTrainBalance.losses }} ({{ cryptoTrainBalance.lossPct }}%)</strong>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Per-Symbol Performance (standalone card) -->
        <div v-if="cryptoSymbolStats.length" class="tp-card" style="margin-top:1rem;">
          <div class="sym-mini">
            <h5>Per-Symbol Performance</h5>
            <div v-for="s in cryptoSymbolStats" :key="s.symbol" class="sym-row">
              <span class="sym-name">{{ s.symbol }}</span>
              <div class="sym-bar-bg">
                <div class="sym-bar-fill" :style="{ width: (s.wins / s.total * 100) + '%' }"></div>
              </div>
              <span class="sym-wr" :style="s.wins / s.total >= 0.5 ? 'color:var(--tp-success)' : 'color:var(--tp-danger)'">
                {{ (s.wins / s.total * 100).toFixed(0) }}%
              </span>
              <span class="sym-pnl" :style="pnlColor(s.pnl)">{{ fmtDollar(s.pnl) }}</span>
            </div>
          </div>
        </div>

        <!-- Model Details Card -->
        <div v-if="cryptoModel" class="tp-card" style="margin-top:1rem;">
          <h4>Active Model Details</h4>
          <div class="detail-grid">
            <div class="detail-item">
              <span class="detail-label">Version</span>
              <span class="detail-val">v{{ cryptoModel.version }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Type</span>
              <span class="detail-val"><span class="model-type-inline" :class="cryptoModelTypeClass">{{ cryptoModel.model_type }}</span></span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Training Trades</span>
              <span class="detail-val">{{ cryptoModel.trade_count }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Accuracy</span>
              <span class="detail-val">{{ fmtPct(cryptoModel.accuracy) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Cross-Validated</span>
              <span class="detail-val">{{ fmtPct(cryptoModel.cv_accuracy) }} &plusmn; {{ fmtPct(cryptoModel.cv_std) }}</span>
            </div>
            <div class="detail-item" v-if="cryptoModel.walk_forward_accuracy != null">
              <span class="detail-label">Walk-Forward</span>
              <span class="detail-val" :style="cryptoModel.walk_forward_accuracy > 0.55 ? 'color:var(--tp-success);font-weight:700' : ''">
                {{ fmtPct(cryptoModel.walk_forward_accuracy) }}
              </span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Precision</span>
              <span class="detail-val">{{ fmtPct(cryptoModel.precision) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Recall</span>
              <span class="detail-val">{{ fmtPct(cryptoModel.recall) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">F1 Score</span>
              <span class="detail-val">{{ fmtPct(cryptoModel.f1_score) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Trained At</span>
              <span class="detail-val">{{ fmtTime(cryptoModel.trained_at) }}</span>
            </div>
          </div>
        </div>

        <!-- Per-symbol chips from old stats API (fallback) -->
        <div v-if="cryptoML?.training?.by_symbol && Object.keys(cryptoML.training.by_symbol).length && !cryptoSymbolStats.length" class="tp-card" style="margin-top:1rem;">
          <h4>Per Symbol</h4>
          <div style="display: flex; gap: 0.75rem; flex-wrap: wrap; margin-top:0.5rem;">
            <div v-for="(stats, sym) in cryptoML.training.by_symbol" :key="sym" class="symbol-chip">
              <span style="font-weight: 700;">{{ sym }}</span>
              <span :style="{ color: stats.pnl >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
                {{ stats.wins }}W/{{ stats.losses }}L {{ fmtDollar(stats.pnl) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Session Card -->
        <div v-if="cryptoML?.session?.total" class="tp-card" style="margin-top: 1rem;">
          <h4>Current Session</h4>
          <div style="display: flex; gap: 1.5rem; align-items: center; margin-top:0.5rem;">
            <div>
              <span style="font-weight: 700;">{{ cryptoML.session.wins }}W / {{ cryptoML.session.losses }}L</span>
              <span style="color: var(--tp-text-dim); font-size: 0.8rem;"> ({{ cryptoML.session.win_rate }}%)</span>
            </div>
            <div :style="{ color: cryptoML.session.net_pnl >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)', fontWeight: 700 }">
              {{ fmtDollar(cryptoML.session.net_pnl) }}
            </div>
          </div>
        </div>

        <!-- Progress bar for data collection -->
        <div v-if="!cryptoModel" class="tp-card" style="margin-top: 1rem;">
          <h4>Data Collection Progress</h4>
          <p class="chart-desc">{{ cryptoFeatures.labeled || 0 }} / 200 labeled trades collected. Model training begins at 200 trades.</p>
          <div style="height: 8px; background: var(--tp-border); border-radius: 4px; overflow: hidden; margin-top:0.5rem;">
            <div :style="{ width: Math.min((cryptoFeatures.labeled || 0) / 200 * 100, 100) + '%', background: 'var(--tp-primary)', height: '100%', transition: 'width 0.5s' }"></div>
          </div>
          <p v-if="cryptoML?.features?.length" style="color: var(--tp-text-dim); margin-top: 0.75rem; font-size: 0.75rem;">
            Features: {{ cryptoML.features.join(', ') }}
          </p>
        </div>

        <!-- Feature list if model exists -->
        <div v-if="cryptoModel && cryptoML?.feature_names?.length" class="tp-card" style="margin-top: 1rem;">
          <h4>Feature Set</h4>
          <div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-top:0.5rem;">
            <span v-for="f in cryptoML.feature_names" :key="f" class="feature-chip">{{ f.replace(/_/g, ' ') }}</span>
          </div>
        </div>
      </template>

      <!-- ========== CRYPTO PREDICTIONS TAB ========== -->
      <template v-if="activeCryptoTab === 'predictions'">
        <div class="tp-card">
          <h4>Recent Crypto Predictions</h4>
          <div v-if="cryptoPredictions.length === 0" class="ml-empty-state" style="padding:2rem 0;">
            <p class="empty-desc">Trades appear here as they are scored by the model.</p>
          </div>
          <div v-else class="table-responsive">
            <table class="ml-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Entry</th>
                  <th>Close</th>
                  <th>PnL</th>
                  <th>ML Score</th>
                  <th>Won</th>
                  <th>Reason</th>
                  <th>Duration</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in cryptoPredictions" :key="p.trade_id || p.id">
                  <td>{{ fmtTime(p.entry_time) }}</td>
                  <td><strong>{{ p.symbol }}</strong></td>
                  <td :style="p.type === 'BUY' || p.side === 'BUY' ? 'color:var(--tp-success)' : 'color:var(--tp-danger)'">{{ p.type || p.side }}</td>
                  <td>{{ p.entry_price != null ? p.entry_price.toFixed(2) : '-' }}</td>
                  <td>{{ p.close_price != null ? p.close_price.toFixed(2) : '-' }}</td>
                  <td :style="pnlColor(p.pnl)">{{ p.pnl !== null && p.pnl !== undefined ? fmtDollar(p.pnl) : '-' }}</td>
                  <td :style="scoreColor(p.ml_score)">{{ p.ml_score !== null && p.ml_score !== undefined ? p.ml_score.toFixed(2) : '-' }}</td>
                  <td>
                    <span v-if="p.actual_win === true" class="outcome-badge win">WIN</span>
                    <span v-else-if="p.actual_win === false" class="outcome-badge loss">LOSS</span>
                    <span v-else class="outcome-badge open">OPEN</span>
                  </td>
                  <td style="font-size:0.7rem;color:var(--tp-text-dim)">{{ p.reason || p.signal_reason || '-' }}</td>
                  <td style="font-size:0.7rem;color:var(--tp-text-dim)">{{ p.duration_min != null ? p.duration_min.toFixed(0) + 'm' : '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <!-- ========== CRYPTO FEATURES TAB ========== -->
      <template v-if="activeCryptoTab === 'features'">
        <!-- Feature Importance Bars -->
        <div class="tp-card" v-if="cryptoTopFeatures.length > 0">
          <h4>Feature Importance</h4>
          <p class="chart-desc">Magnitude of influence on predictions. Higher = more impact.</p>
          <div class="feature-bars">
            <div v-for="([name, importance], i) in cryptoTopFeatures" :key="name" class="feature-row">
              <span class="feature-rank">{{ i + 1 }}</span>
              <span class="feature-name">{{ name.replace(/_/g, ' ') }}</span>
              <div class="feature-bar-bg">
                <div class="feature-bar-fill" :style="{
                  width: (importance / cryptoTopFeatures[0][1] * 100) + '%',
                  background: i < 3 ? 'var(--tp-primary)' : i < 6 ? 'rgba(99,102,241,0.5)' : 'var(--tp-text-dim)',
                }"></div>
              </div>
              <span class="feature-value">{{ (importance * 100).toFixed(1) }}%</span>
            </div>
          </div>
        </div>

        <!-- Feature list from API -->
        <div v-if="cryptoML?.feature_names?.length" class="tp-card" style="margin-top:1rem;">
          <h4>Feature Set ({{ cryptoML.feature_names.length }} features)</h4>
          <div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-top:0.5rem;">
            <span v-for="f in cryptoML.feature_names" :key="f" class="feature-chip">{{ f.replace(/_/g, ' ') }}</span>
          </div>
        </div>

        <div v-if="cryptoTopFeatures.length === 0 && !(cryptoML?.feature_names?.length)" class="tp-card ml-empty-state">
          <span class="material-symbols-outlined" style="font-size:2rem;color:var(--tp-text-dim)">analytics</span>
          <p class="empty-desc">Feature importance appears after first model training.</p>
        </div>
      </template>

      <!-- ========== CRYPTO HISTORY TAB ========== -->
      <template v-if="activeCryptoTab === 'history'">
        <!-- Model Evolution Chart -->
        <div v-if="cryptoHistory.length > 1" class="tp-card" style="margin-bottom:1rem;">
          <h4>Model Evolution</h4>
          <p class="chart-desc">Accuracy across model versions</p>
          <div class="evo-chart">
            <div v-for="m in cryptoHistory" :key="m.version" class="evo-col">
              <div class="evo-bar-wrap">
                <div class="evo-bar" :style="{
                  height: ((m.accuracy || 0) * 100) + '%',
                  background: m.is_active ? 'var(--tp-primary)' : 'var(--tp-text-dim)',
                  opacity: m.is_active ? 1 : 0.5,
                }">
                  <span class="evo-val">{{ ((m.accuracy || 0) * 100).toFixed(0) }}%</span>
                </div>
              </div>
              <span class="evo-label">v{{ m.version }}</span>
            </div>
          </div>
        </div>

        <div class="tp-card">
          <h4>Version History</h4>
          <div v-if="cryptoHistory.length === 0" class="ml-empty-state" style="padding:2rem 0;">
            <p class="empty-desc">No models trained yet. Training begins after 200 labeled trades.</p>
          </div>
          <div v-else class="table-responsive">
            <table class="ml-table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Type</th>
                  <th>Trades</th>
                  <th>Accuracy</th>
                  <th>CV Acc</th>
                  <th>WF Acc</th>
                  <th>Trained</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in cryptoHistory" :key="m.version" :class="{ 'row-active': m.is_active }">
                  <td><strong>v{{ m.version }}</strong></td>
                  <td><span class="model-type-inline" :class="modelTypeClassFor(m.model_type)">{{ m.model_type }}</span></td>
                  <td>{{ m.trade_count }}</td>
                  <td :style="m.accuracy > 0.55 ? 'color:var(--tp-success)' : ''">{{ fmtPct(m.accuracy) }}</td>
                  <td>{{ fmtPct(m.cv_accuracy) }}</td>
                  <td :style="m.walk_forward_accuracy > 0.55 ? 'color:var(--tp-success);font-weight:700' : ''">
                    {{ m.walk_forward_accuracy != null ? fmtPct(m.walk_forward_accuracy) : '-' }}
                  </td>
                  <td>{{ fmtTime(m.trained_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>
    </template>

  </div>
</template>

<style scoped>
.ml-page { padding: 1.5rem 1.5rem 2rem; }

/* Header */
.ml-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1.25rem;
  padding-left: 1.15rem;
  padding-right: 1.15rem;
}
.ml-header h1 { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em; margin: 0; }
.ml-subtitle { font-size: 0.8rem; color: var(--tp-text-dim); margin: 0.1rem 0 0; }
.stat-sub { font-size: 0.7rem; color: var(--tp-text-dim); }
.ml-loading { text-align: center; padding: 3rem; color: var(--tp-text-dim); }

/* Model pill */
.model-pill-row { display: flex; align-items: center; gap: 0.6rem; }
.pill-meta { font-size: 0.75rem; color: var(--tp-text-dim); }

/* Cards */
.tp-card {
  padding: 1rem 1.15rem;
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
  border: var(--tp-glass-border);
  border-radius: var(--tp-radius);
  box-shadow: var(--tp-glass-shadow);
}
.tp-card h4 { font-size: 0.88rem; font-weight: 700; margin: 0 0 0.15rem; }
.chart-desc { font-size: 0.72rem; color: var(--tp-text-dim); margin: 0 0 0.75rem; }
.chart-axis-label { text-align: center; font-size: 0.65rem; color: var(--tp-text-dim); margin-top: 0.4rem; }
.table-responsive { overflow-x: auto; }

/* Chart row — side by side */
.ml-chart-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
.ml-chart-card {
  display: flex;
  flex-direction: column;
}
.ml-chart-card > .sd-chart,
.ml-chart-card > .cal-chart,
.ml-chart-card > .scatter-wrap {
  flex: 1;
}
@media (max-width: 768px) {
  .ml-chart-row { grid-template-columns: 1fr; }
}

/* ===== Confusion Matrix ===== */
.cm-grid {
  display: grid;
  grid-template-columns: 80px 1fr 1fr;
  gap: 3px;
  margin-bottom: 0.65rem;
}
.cm-corner { background: transparent; }
.cm-header {
  text-align: center;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--tp-text-dim);
  padding: 0.4rem 0;
}
.cm-row-label {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--tp-text-dim);
}
.cm-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0.75rem 0.5rem;
  border-radius: 6px;
  gap: 0.1rem;
}
.cm-val { font-size: 1.4rem; font-weight: 800; line-height: 1.1; }
.cm-tag { font-size: 0.55rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.7; }
.cm-pnl { font-size: 0.58rem; font-weight: 600; opacity: 0.85; margin-top: 0.1rem; }
.cm-tp { background: rgba(34, 197, 94, 0.12); color: var(--tp-success); }
.cm-tn { background: rgba(59, 130, 246, 0.12); color: #60a5fa; }
.cm-fp { background: rgba(239, 68, 68, 0.1); color: var(--tp-danger); }
.cm-fn { background: rgba(245, 158, 11, 0.1); color: var(--tp-warning); }
.cm-summary {
  display: flex;
  gap: 1.5rem;
  font-size: 0.72rem;
  color: var(--tp-text-dim);
}
.cm-summary strong { color: var(--tp-text); }

/* ===== Score Distribution ===== */
.sd-chart {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  min-height: 120px;
}
.sd-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
.sd-bar-stack { width: 100%; display: flex; flex-direction: column; justify-content: flex-end; height: 100%; }
.sd-bar { width: 100%; border-radius: 2px 2px 0 0; min-height: 0; transition: height 0.4s ease; }
.sd-win { background: var(--tp-success); }
.sd-loss { background: var(--tp-danger); opacity: 0.7; }
.sd-label { font-size: 0.6rem; color: var(--tp-text-dim); margin-top: 0.2rem; }
.sd-legend { display: flex; gap: 1rem; margin-top: 0.5rem; font-size: 0.65rem; color: var(--tp-text-dim); }
.sd-leg-item { display: flex; align-items: center; gap: 0.3rem; }
.sd-dot { width: 8px; height: 8px; border-radius: 2px; }
.sd-dot-win { background: var(--tp-success); }
.sd-dot-loss { background: var(--tp-danger); opacity: 0.7; }

/* ===== Score vs PnL Scatter ===== */
.scatter-wrap {
  display: flex;
  gap: 0.4rem;
  align-items: stretch;
}
.scatter-y-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  font-size: 0.55rem;
  color: var(--tp-text-dim);
  min-width: 42px;
  text-align: right;
  padding: 0 0.2rem;
}
.scatter-container {
  flex: 1;
  min-height: 160px;
  position: relative;
  background: rgba(128, 128, 128, 0.04);
  border-radius: 4px;
  border-left: 1px solid rgba(128, 128, 128, 0.15);
  border-bottom: 1px solid rgba(128, 128, 128, 0.15);
  overflow: hidden;
}
.scatter-zero {
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  background: rgba(128, 128, 128, 0.3);
  pointer-events: none;
}
.scatter-threshold {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(99, 102, 241, 0.3);
  pointer-events: none;
}
.scatter-dot {
  position: absolute;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  transform: translate(-50%, 50%);
  transition: transform 0.2s, box-shadow 0.2s;
  cursor: default;
  z-index: 1;
}
.scatter-dot:hover {
  transform: translate(-50%, 50%) scale(1.6);
  z-index: 10;
}
.dot-win {
  background: var(--tp-success);
  box-shadow: 0 0 4px rgba(34, 197, 94, 0.4);
}
.dot-loss {
  background: var(--tp-danger);
  box-shadow: 0 0 4px rgba(239, 68, 68, 0.4);
  opacity: 0.8;
}
.scatter-x-axis {
  display: flex;
  justify-content: space-between;
  font-size: 0.55rem;
  color: var(--tp-text-dim);
  padding-left: 46px;
  margin-top: 0.2rem;
}
.scatter-legend {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.4rem;
  font-size: 0.6rem;
  color: var(--tp-text-dim);
}
.scatter-leg-line {
  width: 14px;
  height: 2px;
  border-radius: 1px;
  display: inline-block;
  vertical-align: middle;
}
.scatter-leg-zero { background: rgba(128, 128, 128, 0.5); }
.scatter-leg-thresh { background: rgba(99, 102, 241, 0.5); }

/* ===== Threshold Analyzer ===== */
.thresh-table-wrap { overflow-x: auto; }
.thresh-table {
  width: 100%;
  font-size: 0.72rem;
  border-collapse: collapse;
}
.thresh-table th {
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--tp-text-dim);
  font-weight: 700;
  text-align: left;
  padding: 0.35rem 0.4rem;
  border-bottom: 1px solid var(--tp-border);
}
.thresh-table td {
  padding: 0.35rem 0.4rem;
  border-bottom: 1px solid rgba(128, 128, 128, 0.06);
}
.thresh-current {
  background: rgba(99, 102, 241, 0.08);
}
.thresh-val {
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.3rem;
}
.thresh-badge {
  font-size: 0.5rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: rgba(99, 102, 241, 0.15);
  color: var(--tp-primary);
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
}
.thresh-dim { color: var(--tp-text-dim); font-size: 0.65rem; }
.thresh-hint {
  font-size: 0.62rem;
  color: var(--tp-text-dim);
  margin: 0.6rem 0 0;
  font-style: italic;
}

/* ===== Calibration ===== */
.cal-chart {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  min-height: 120px;
}
.cal-bucket { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; }
.cal-bar-wrap { flex: 1; width: 100%; display: flex; align-items: flex-end; }
.cal-bar {
  width: 100%;
  border-radius: 4px 4px 0 0;
  position: relative;
  transition: height 0.4s ease;
  min-height: 2px;
}
.cal-val {
  position: absolute;
  top: -1rem;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.6rem;
  font-weight: 700;
  white-space: nowrap;
}
.cal-label { font-size: 0.62rem; color: var(--tp-text-dim); margin-top: 0.2rem; white-space: nowrap; }
.cal-n { font-size: 0.55rem; color: var(--tp-text-dim); opacity: 0.6; }

/* ===== Training Balance Ring ===== */
.bal-ring-wrap { display: flex; align-items: center; gap: 1.5rem; margin-bottom: 1rem; }
.bal-ring {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.bal-ring-inner {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: var(--tp-bg-surface);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.bal-total { font-size: 1.1rem; font-weight: 800; line-height: 1; }
.bal-sub { font-size: 0.55rem; color: var(--tp-text-dim); }
.bal-legend { display: flex; flex-direction: column; gap: 0.4rem; }
.bal-leg-row { display: flex; align-items: center; gap: 0.5rem; font-size: 0.75rem; }
.bal-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }

/* Symbol mini breakdown */
.sym-mini { border-top: 1px solid var(--tp-border); padding-top: 0.75rem; }
.sym-mini h5 { font-size: 0.75rem; font-weight: 700; margin: 0 0 0.5rem; }
.sym-row { display: grid; grid-template-columns: 60px 1fr 36px 54px; align-items: center; gap: 0.5rem; margin-bottom: 0.3rem; }
.sym-name { font-size: 0.68rem; font-weight: 600; }
.sym-bar-bg { height: 6px; background: rgba(128,128,128,0.12); border-radius: 3px; overflow: hidden; }
.sym-bar-fill { height: 100%; background: var(--tp-success); border-radius: 3px; transition: width 0.4s; }
.sym-wr { font-size: 0.65rem; font-weight: 700; text-align: right; }
.sym-pnl { font-size: 0.6rem; font-weight: 600; text-align: right; }

/* ===== SHAP Diverging Bars ===== */
.shap-diverging { display: flex; flex-direction: column; gap: 0.4rem; }
.shap-div-row {
  display: grid;
  grid-template-columns: 120px 1fr 56px;
  align-items: center;
  gap: 0.5rem;
}
.shap-div-name {
  font-size: 0.7rem;
  text-align: right;
  text-transform: capitalize;
  color: var(--tp-text);
  font-weight: 500;
}
.shap-div-track {
  position: relative;
  height: 18px;
  background: rgba(128, 128, 128, 0.06);
  border-radius: 3px;
  overflow: hidden;
}
.shap-div-center {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(128, 128, 128, 0.25);
}
.shap-div-bar {
  position: absolute;
  top: 2px;
  bottom: 2px;
  border-radius: 2px;
  transition: width 0.4s ease;
}
.shap-positive { background: linear-gradient(90deg, rgba(34, 197, 94, 0.2), rgba(34, 197, 94, 0.6)); }
.shap-negative { background: linear-gradient(270deg, rgba(239, 68, 68, 0.2), rgba(239, 68, 68, 0.6)); }
.shap-div-val {
  font-size: 0.62rem;
  font-weight: 700;
  text-align: left;
  font-variant-numeric: tabular-nums;
}
.shap-div-axis {
  display: grid;
  grid-template-columns: 120px 1fr 56px;
  gap: 0.5rem;
  margin-top: 0.3rem;
}
.shap-div-axis span {
  font-size: 0.55rem;
  color: var(--tp-text-dim);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.shap-axis-loss { text-align: right; color: var(--tp-danger) !important; }
.shap-axis-zero { text-align: center; }
.shap-axis-win { text-align: left; color: var(--tp-success) !important; }
@media (max-width: 480px) { .shap-div-row { grid-template-columns: 80px 1fr 48px; } }

/* ===== Learning Curve ===== */
.learning-curve-chart {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  height: 130px;
}
.lc-bar-container { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
.lc-bar { width: 100%; max-width: 40px; border-radius: 3px 3px 0 0; position: relative; min-height: 3px; transition: height 0.5s ease; }
.lc-label { position: absolute; top: -1rem; left: 50%; transform: translateX(-50%); font-size: 0.6rem; font-weight: 700; white-space: nowrap; }
.lc-x-label { font-size: 0.6rem; color: var(--tp-text-dim); margin-top: 0.2rem; }

/* ===== Model Details Grid ===== */
.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.1rem 1.5rem;
}
.detail-item {
  display: flex;
  justify-content: space-between;
  padding: 0.35rem 0;
  border-bottom: 1px solid rgba(128,128,128,0.08);
  font-size: 0.78rem;
}
.detail-label { color: var(--tp-text-dim); }
.detail-val { font-weight: 600; }

/* ===== Feature Bars ===== */
.feature-bars { display: flex; flex-direction: column; gap: 0.35rem; }
.feature-row { display: grid; grid-template-columns: 24px 130px 1fr 44px; align-items: center; gap: 0.5rem; }
.feature-rank { font-size: 0.6rem; font-weight: 700; color: var(--tp-text-dim); text-align: center; }
.feature-name { font-size: 0.72rem; text-transform: capitalize; text-align: right; }
.feature-bar-bg { height: 16px; background: rgba(128,128,128,0.08); border-radius: 3px; overflow: hidden; }
.feature-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
.feature-value { font-size: 0.65rem; font-weight: 600; color: var(--tp-text-dim); }
@media (max-width: 480px) { .feature-row { grid-template-columns: 20px 90px 1fr 36px; } }

/* ===== ML Table ===== */
.ml-table { width: 100%; font-size: 0.75rem; border-collapse: collapse; }
.ml-table th { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--tp-text-dim); font-weight: 700; text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--tp-border); }
.ml-table td { padding: 0.4rem 0.5rem; border-bottom: 1px solid rgba(128,128,128,0.06); }
.row-active { background: rgba(34,197,94,0.04); }

/* Outcome badges */
.outcome-badge { font-size: 0.65rem; font-weight: 700; padding: 0.1rem 0.4rem; border-radius: 3px; letter-spacing: 0.03em; }
.outcome-badge.win { background: rgba(34,197,94,0.12); color: var(--tp-success); }
.outcome-badge.loss { background: rgba(239,68,68,0.1); color: var(--tp-danger); }
.outcome-badge.open { background: rgba(128,128,128,0.1); color: var(--tp-text-dim); }

/* ===== Model Evolution Chart ===== */
.evo-chart { display: flex; align-items: flex-end; gap: 0.5rem; height: 100px; }
.evo-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
.evo-bar-wrap { flex: 1; width: 100%; display: flex; align-items: flex-end; }
.evo-bar { width: 100%; max-width: 36px; margin: 0 auto; border-radius: 3px 3px 0 0; position: relative; min-height: 3px; transition: height 0.4s; }
.evo-val { position: absolute; top: -0.9rem; left: 50%; transform: translateX(-50%); font-size: 0.55rem; font-weight: 700; white-space: nowrap; }
.evo-label { font-size: 0.6rem; color: var(--tp-text-dim); margin-top: 0.2rem; }

/* ===== LLM Grid ===== */
.llm-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; }
.llm-stat { display: flex; flex-direction: column; padding: 0.6rem; background: rgba(30,41,59,0.2); border-radius: 6px; }
.llm-val { font-size: 1rem; font-weight: 800; }
.llm-label { font-size: 0.6rem; text-transform: uppercase; font-weight: 600; color: var(--tp-text-dim); letter-spacing: 0.04em; }

/* Model type pills */
.model-type-pill {
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  padding: 0.2rem 0.6rem;
  border-radius: 5px;
  white-space: nowrap;
}
.model-type-inline {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  white-space: nowrap;
}
.mt-xgboost { background: rgba(99,102,241,0.12); color: #818cf8; }
.mt-lightgbm { background: rgba(34,197,94,0.12); color: #22c55e; }
.mt-sklearn { background: rgba(245,158,11,0.12); color: #f59e0b; }

/* Empty state */
.ml-empty-state { text-align: center; padding: 2.5rem 1rem; margin-bottom: 1rem; }
.empty-title { font-size: 1rem; font-weight: 700; margin: 0.5rem 0 0.25rem; }
.empty-desc { font-size: 0.8rem; color: var(--tp-text-dim); margin: 0; }
.progress-wrap { width: 60%; margin: 0.75rem auto 0; height: 6px; background: rgba(128,128,128,0.12); border-radius: 3px; overflow: hidden; }
.progress-bar { height: 100%; background: var(--tp-primary); border-radius: 3px; transition: width 0.5s; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.spinning { animation: spin 1s linear infinite; }

/* Forex / Crypto ML Tabs */
.ml-tab-group {
  display: flex;
  gap: 0;
  border: 1px solid var(--tp-border);
  border-radius: 4px;
  overflow: hidden;
  margin: 0 1.15rem 1.25rem;
  width: fit-content;
}
.ml-tab {
  font-family: var(--tp-font);
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  padding: 0.3rem 0.75rem;
  background: transparent;
  border: none;
  color: var(--tp-text-dim);
  cursor: pointer;
  transition: all 0.15s ease;
  border-right: 1px solid var(--tp-border);
}
.ml-tab:last-child { border-right: none; }
.ml-tab:hover { background: var(--tp-bg-hover); color: var(--tp-text); }
.ml-tab.active { background: var(--tp-primary); color: white; }

/* Crypto ML placeholder */
.crypto-ml-placeholder, .crypto-ml-section { padding: 0 1.15rem; }
.stat-mini { display: flex; flex-direction: column; align-items: center; gap: 0.2rem; }
.stat-val { font-size: 1.2rem; font-weight: 800; color: var(--tp-text); }
.stat-lbl { font-size: 0.6rem; color: var(--tp-text-dim); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; }
.symbol-chip { display: flex; gap: 0.5rem; padding: 0.3rem 0.75rem; background: var(--tp-bg-card); border: 1px solid var(--tp-border); border-radius: 6px; font-size: 0.78rem; }
.feature-chip {
  font-size: 0.68rem;
  padding: 0.15rem 0.5rem;
  background: rgba(99,102,241,0.08);
  border: 1px solid rgba(99,102,241,0.15);
  border-radius: 4px;
  color: var(--tp-text);
  text-transform: capitalize;
}
</style>
