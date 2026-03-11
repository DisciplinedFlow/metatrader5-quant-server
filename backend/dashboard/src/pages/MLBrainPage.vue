<script setup>
import { ref, computed, onMounted } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'

const status = ref(null)
const predictions = ref([])
const loading = ref(true)
const activeTab = ref('overview')

async function refresh() {
  try {
    const [s, p] = await Promise.all([
      api.getMLStatus(),
      api.getMLPredictions(50),
    ])
    status.value = s
    predictions.value = p
  } catch (err) {
    console.error('ML status error:', err)
  }
  loading.value = false
}

usePolling(refresh, 30000) // refresh every 30s
onMounted(refresh)

const model = computed(() => status.value?.active_model)
const features = computed(() => status.value?.features || {})
const llm = computed(() => status.value?.llm_training_data || {})
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

const predictionAccuracy = computed(() => {
  const resolved = predictions.value.filter(p => p.actual_win !== null && p.ml_score !== null)
  if (resolved.length === 0) return null
  const correct = resolved.filter(p => {
    const predicted_win = p.ml_score >= 0.5
    return predicted_win === p.actual_win
  })
  return (correct.length / resolved.length * 100).toFixed(1)
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
  <main class="container">
    <hgroup>
      <h2>ML Learning Pipeline</h2>
      <p>Continuous learning from trade outcomes — the model improves with every closed trade</p>
    </hgroup>

    <div v-if="loading" aria-busy="true">Loading ML data...</div>

    <template v-else>
      <!-- Model Type Banner -->
      <div v-if="model" class="model-type-banner" style="margin-bottom: 1.5rem;">
        <div class="model-type-pill" :class="modelTypeClass">
          {{ model.model_type }}
        </div>
        <div class="model-type-meta">
          <span class="model-version">v{{ model.version }}</span>
          <span class="model-sep">/</span>
          <span>{{ model.trade_count }} trades</span>
          <span class="model-sep">/</span>
          <span>Trained {{ fmtTime(model.trained_at) }}</span>
        </div>
      </div>

      <!-- Status Cards -->
      <div class="tp-stats-grid" style="margin-bottom: 2rem;">
        <div class="tp-stat-card">
          <div class="stat-label">Model Status</div>
          <div class="stat-value" :style="model ? 'color: var(--tp-success)' : 'color: var(--tp-text-muted)'">
            {{ model ? `v${model.version}` : 'No Model' }}
          </div>
          <div v-if="model" style="font-size:0.75rem; color:var(--tp-text-muted)">
            {{ model.model_type }} &bull; {{ model.trade_count }} trades
          </div>
        </div>

        <div class="tp-stat-card">
          <div class="stat-label">Accuracy</div>
          <div class="stat-value" :style="model && model.accuracy > 0.55 ? 'color:var(--tp-success)' : ''">
            {{ model ? fmtPct(model.accuracy) : '-' }}
          </div>
          <div v-if="model" style="font-size:0.75rem; color:var(--tp-text-muted)">
            CV: {{ fmtPct(model.cv_accuracy) }} &plusmn; {{ fmtPct(model.cv_std) }}
          </div>
        </div>

        <div class="tp-stat-card" v-if="model && model.walk_forward_accuracy != null">
          <div class="stat-label">Walk-Forward</div>
          <div class="stat-value" :style="model.walk_forward_accuracy > 0.55 ? 'color:var(--tp-success)' : model.walk_forward_accuracy > 0.50 ? 'color:var(--tp-warning)' : 'color:var(--tp-danger)'">
            {{ fmtPct(model.walk_forward_accuracy) }}
          </div>
          <div style="font-size:0.75rem; color:var(--tp-text-muted)">
            No future leakage
          </div>
        </div>

        <div class="tp-stat-card">
          <div class="stat-label">Training Data</div>
          <div class="stat-value">{{ features.labeled || 0 }}</div>
          <div style="font-size:0.75rem; color:var(--tp-text-muted)">
            <span style="color:var(--tp-success)">{{ features.wins || 0 }}W</span> /
            <span style="color:var(--tp-danger)">{{ features.losses || 0 }}L</span>
            &bull; {{ features.unlabeled || 0 }} open
          </div>
        </div>

        <div class="tp-stat-card">
          <div class="stat-label">LLM Training Data</div>
          <div class="stat-value">{{ llm.total_examples || 0 }}</div>
          <div style="font-size:0.75rem; color:var(--tp-text-muted)">
            {{ llm.file_size_kb || 0 }} KB &bull; JSONL format
          </div>
        </div>

        <div class="tp-stat-card">
          <div class="stat-label">ML Rejected</div>
          <div class="stat-value" style="color:var(--tp-warning)">{{ features.ml_rejected || 0 }}</div>
          <div style="font-size:0.75rem; color:var(--tp-text-muted)">
            Trades blocked by scorer
          </div>
        </div>

        <div class="tp-stat-card" v-if="predictionAccuracy !== null">
          <div class="stat-label">Prediction Accuracy</div>
          <div class="stat-value" :style="parseFloat(predictionAccuracy) > 55 ? 'color:var(--tp-success)' : ''">
            {{ predictionAccuracy }}%
          </div>
          <div style="font-size:0.75rem; color:var(--tp-text-muted)">
            On resolved predictions
          </div>
        </div>
      </div>

      <!-- Tabs -->
      <div style="display:flex; gap:0.5rem; margin-bottom:1.5rem; flex-wrap:wrap;">
        <button
          v-for="tab in ['overview', 'predictions', 'features', 'history']"
          :key="tab"
          :class="activeTab === tab ? 'contrast' : 'outline'"
          @click="activeTab = tab"
          style="text-transform:capitalize; padding:0.4rem 1rem; font-size:0.85rem;"
        >{{ tab }}</button>
      </div>

      <!-- Overview Tab -->
      <template v-if="activeTab === 'overview'">
        <!-- Learning Curve -->
        <div class="tp-card" v-if="learningCurve.length > 0" style="margin-bottom:1.5rem;">
          <h4>Learning Curve</h4>
          <p style="font-size:0.8rem; color:var(--tp-text-muted); margin-bottom:1rem;">
            Model accuracy as training data grows — should trend upward
          </p>
          <div class="learning-curve-chart">
            <div
              v-for="(point, i) in learningCurve"
              :key="i"
              class="lc-bar-container"
            >
              <div class="lc-bar" :style="{
                height: (point.accuracy * 100) + '%',
                background: point.accuracy > 0.55 ? 'var(--tp-success)' : point.accuracy > 0.5 ? 'var(--tp-warning)' : 'var(--tp-danger)'
              }">
                <span class="lc-label">{{ (point.accuracy * 100).toFixed(0) }}%</span>
              </div>
              <span class="lc-x-label">{{ point.trades }}</span>
            </div>
          </div>
          <div style="text-align:center; font-size:0.75rem; color:var(--tp-text-muted); margin-top:0.5rem;">
            Number of training trades
          </div>
        </div>

        <!-- No Model Yet -->
        <div v-if="!model" class="tp-card" style="text-align:center; padding:3rem;">
          <p style="font-size:1.2rem; margin-bottom:0.5rem;">Collecting Training Data</p>
          <p style="color:var(--tp-text-muted)">
            The ML model will automatically train once {{ 30 - (features.labeled || 0) > 0 ? 30 - (features.labeled || 0) : 0 }}
            more trades close. Currently at {{ features.labeled || 0 }} / 30 minimum.
          </p>
          <div style="margin-top:1rem;">
            <progress :value="features.labeled || 0" max="30" style="width:60%"></progress>
          </div>
        </div>

        <!-- Model Details -->
        <div v-if="model" class="tp-card">
          <h4>Active Model Details</h4>
          <table>
            <tbody>
              <tr><td>Version</td><td>v{{ model.version }}</td></tr>
              <tr>
                <td>Type</td>
                <td><span class="model-type-inline" :class="modelTypeClass">{{ model.model_type }}</span></td>
              </tr>
              <tr><td>Training Trades</td><td>{{ model.trade_count }}</td></tr>
              <tr><td>Accuracy</td><td>{{ fmtPct(model.accuracy) }}</td></tr>
              <tr><td>Cross-Validated</td><td>{{ fmtPct(model.cv_accuracy) }} &plusmn; {{ fmtPct(model.cv_std) }}</td></tr>
              <tr v-if="model.walk_forward_accuracy != null">
                <td>Walk-Forward</td>
                <td :style="model.walk_forward_accuracy > 0.55 ? 'color:var(--tp-success);font-weight:700' : model.walk_forward_accuracy > 0.50 ? 'color:var(--tp-warning);font-weight:700' : 'color:var(--tp-danger);font-weight:700'">
                  {{ fmtPct(model.walk_forward_accuracy) }}
                  <span style="font-weight:400;font-size:0.75rem;color:var(--tp-text-muted);margin-left:0.5rem;">Lopez de Prado method</span>
                </td>
              </tr>
              <tr><td>Precision</td><td>{{ fmtPct(model.precision) }}</td></tr>
              <tr><td>Recall</td><td>{{ fmtPct(model.recall) }}</td></tr>
              <tr><td>F1 Score</td><td>{{ fmtPct(model.f1_score) }}</td></tr>
              <tr><td>Baseline Win Rate</td><td>{{ fmtPct(model.win_rate_baseline) }}</td></tr>
              <tr><td>Trained At</td><td>{{ fmtTime(model.trained_at) }}</td></tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- Features Tab -->
      <template v-if="activeTab === 'features'">
        <div class="tp-card" v-if="topFeatures.length > 0">
          <h4>SHAP Feature Importance</h4>
          <p style="font-size:0.8rem; color:var(--tp-text-muted); margin-bottom:1rem;">
            SHAP values show how each feature contributes to WIN/LOSS predictions.
            Higher = more influence on model decisions.
          </p>
          <div class="feature-bars">
            <div v-for="([name, importance], i) in topFeatures" :key="name" class="feature-row">
              <span class="feature-name">{{ name.replace(/_/g, ' ') }}</span>
              <div class="feature-bar-bg">
                <div
                  class="feature-bar-fill"
                  :style="{
                    width: (importance / topFeatures[0][1] * 100) + '%',
                    background: i < 3 ? 'var(--tp-primary)' : 'var(--tp-text-muted)',
                    opacity: i < 3 ? 1 : 0.6,
                  }"
                ></div>
              </div>
              <span class="feature-value">{{ (importance * 100).toFixed(1) }}%</span>
            </div>
          </div>
        </div>

        <!-- SHAP Directional Analysis -->
        <div class="tp-card" v-if="shapSummary.length > 0" style="margin-top:1.5rem;">
          <h4>Feature Direction Analysis</h4>
          <p style="font-size:0.8rem; color:var(--tp-text-muted); margin-bottom:1rem;">
            Positive = pushes toward WIN, Negative = pushes toward LOSS
          </p>
          <table>
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
                <td style="font-size:0.85rem;">{{ s.feature.replace(/_/g, ' ') }}</td>
                <td>{{ (s.mean_abs * 100).toFixed(2) }}%</td>
                <td :style="s.mean_signed > 0 ? 'color:var(--tp-success)' : s.mean_signed < 0 ? 'color:var(--tp-danger)' : ''">
                  {{ s.mean_signed > 0 ? 'WIN ↑' : s.mean_signed < 0 ? 'LOSS ↓' : 'Neutral' }}
                </td>
                <td style="font-size:0.8rem; color:var(--tp-text-muted)">
                  ±{{ (s.std * 100).toFixed(2) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="topFeatures.length === 0" class="tp-card" style="text-align:center; padding:2rem;">
          <p style="color:var(--tp-text-muted)">No model trained yet — feature importance will appear after first training</p>
        </div>
      </template>

      <!-- Predictions Tab -->
      <template v-if="activeTab === 'predictions'">
        <div class="tp-card">
          <h4>Recent Predictions</h4>
          <div v-if="predictions.length === 0" style="text-align:center; padding:2rem; color:var(--tp-text-muted);">
            No predictions yet — trades will appear here as they are scored
          </div>
          <div v-else class="table-responsive">
            <table>
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
                  <td style="font-size:0.8rem;">{{ fmtTime(p.entry_time) }}</td>
                  <td><strong>{{ p.symbol }}</strong></td>
                  <td :style="p.type === 'BUY' ? 'color:var(--tp-success)' : 'color:var(--tp-danger)'">
                    {{ p.type }}
                  </td>
                  <td :style="scoreColor(p.ml_score)">
                    {{ p.ml_score !== null ? p.ml_score.toFixed(2) : '-' }}
                  </td>
                  <td>
                    <span v-if="p.ml_accepted === true" style="color:var(--tp-success)">YES</span>
                    <span v-else-if="p.ml_accepted === false" style="color:var(--tp-danger)">NO</span>
                    <span v-else style="color:var(--tp-text-muted)">-</span>
                  </td>
                  <td>
                    <span v-if="p.actual_win === true" style="color:var(--tp-success); font-weight:700">WIN</span>
                    <span v-else-if="p.actual_win === false" style="color:var(--tp-danger); font-weight:700">LOSS</span>
                    <span v-else style="color:var(--tp-text-muted)">OPEN</span>
                  </td>
                  <td :style="pnlColor(p.pnl)">
                    {{ p.pnl !== null ? '$' + p.pnl.toFixed(2) : '-' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <!-- History Tab -->
      <template v-if="activeTab === 'history'">
        <div class="tp-card">
          <h4>Model Version History</h4>
          <div v-if="history.length === 0" style="text-align:center; padding:2rem; color:var(--tp-text-muted);">
            No models trained yet
          </div>
          <table v-else>
            <thead>
              <tr>
                <th>Version</th>
                <th>Type</th>
                <th>Trades</th>
                <th>Accuracy</th>
                <th>CV Acc</th>
                <th>WF Acc</th>
                <th>Trained</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in history" :key="m.version" :style="m.is_active ? 'background:rgba(var(--tp-success-rgb, 0,200,100), 0.05)' : ''">
                <td><strong>v{{ m.version }}</strong></td>
                <td><span class="model-type-inline" :class="modelTypeClassFor(m.model_type)">{{ m.model_type }}</span></td>
                <td>{{ m.trade_count }}</td>
                <td :style="m.accuracy > 0.55 ? 'color:var(--tp-success)' : ''">{{ fmtPct(m.accuracy) }}</td>
                <td>{{ fmtPct(m.cv_accuracy) }}</td>
                <td :style="m.walk_forward_accuracy > 0.55 ? 'color:var(--tp-success);font-weight:700' : m.walk_forward_accuracy > 0.50 ? 'color:var(--tp-warning)' : ''">
                  {{ m.walk_forward_accuracy != null ? fmtPct(m.walk_forward_accuracy) : '-' }}
                </td>
                <td style="font-size:0.8rem;">{{ fmtTime(m.trained_at) }}</td>
                <td>{{ m.is_active ? 'Active' : '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- LLM Export Info -->
      <div class="tp-card" style="margin-top:1.5rem;">
        <h4>LLM Fine-Tuning Pipeline</h4>
        <p style="font-size:0.85rem; color:var(--tp-text-muted); margin-bottom:1rem;">
          Every closed trade generates an instruction-tuning example. When enough data accumulates,
          you can fine-tune a local LLM (e.g., Llama 3.1 8B) and export as GGUF for Ollama.
        </p>
        <div class="tp-stats-grid">
          <div class="tp-stat-card">
            <div class="stat-label">Examples</div>
            <div class="stat-value">{{ llm.total_examples || 0 }}</div>
          </div>
          <div class="tp-stat-card">
            <div class="stat-label">File Size</div>
            <div class="stat-value">{{ llm.file_size_kb || 0 }} KB</div>
          </div>
          <div class="tp-stat-card">
            <div class="stat-label">Win Examples</div>
            <div class="stat-value" style="color:var(--tp-success)">{{ llm.wins || 0 }}</div>
          </div>
          <div class="tp-stat-card">
            <div class="stat-label">Loss Examples</div>
            <div class="stat-value" style="color:var(--tp-danger)">{{ llm.losses || 0 }}</div>
          </div>
        </div>
      </div>
    </template>
  </main>
</template>

<style scoped>
.tp-card {
  padding: 1.5rem;
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
  border: var(--tp-glass-border);
  border-radius: var(--tp-radius);
  box-shadow: var(--tp-glass-shadow);
}

.table-responsive {
  overflow-x: auto;
}

/* Learning Curve Chart */
.learning-curve-chart {
  display: flex;
  align-items: flex-end;
  gap: 0.75rem;
  height: 160px;
  padding: 0 1rem;
}

.lc-bar-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  justify-content: flex-end;
}

.lc-bar {
  width: 100%;
  max-width: 48px;
  border-radius: 4px 4px 0 0;
  position: relative;
  min-height: 4px;
  transition: height 0.5s ease;
}

.lc-label {
  position: absolute;
  top: -1.2rem;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.65rem;
  font-weight: 700;
  white-space: nowrap;
}

.lc-x-label {
  font-size: 0.7rem;
  color: var(--tp-text-muted);
  margin-top: 0.25rem;
}

/* Feature Importance Bars */
.feature-bars {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.feature-row {
  display: grid;
  grid-template-columns: 140px 1fr 50px;
  align-items: center;
  gap: 0.75rem;
}

.feature-name {
  font-size: 0.8rem;
  text-transform: capitalize;
  text-align: right;
}

.feature-bar-bg {
  height: 20px;
  background: rgba(128, 128, 128, 0.1);
  border-radius: 4px;
  overflow: hidden;
}

.feature-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s ease;
}

.feature-value {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--tp-text-muted);
}

@media (max-width: 480px) {
  .feature-row {
    grid-template-columns: 100px 1fr 40px;
  }
}

/* Model Type Banner */
.model-type-banner {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.5rem;
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
  border: var(--tp-glass-border);
  border-radius: var(--tp-radius);
  box-shadow: var(--tp-glass-shadow);
}

.model-type-pill {
  font-size: 0.8rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  padding: 0.3rem 0.75rem;
  border-radius: 6px;
  white-space: nowrap;
}

.model-type-inline {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  white-space: nowrap;
}

.mt-xgboost {
  background: rgba(99, 102, 241, 0.12);
  color: #818cf8;
}

.mt-lightgbm {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
}

.mt-sklearn {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}

.model-type-meta {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  color: var(--tp-text-muted);
}

.model-version {
  font-weight: 700;
  color: var(--tp-text);
}

.model-sep {
  color: var(--tp-border);
}
</style>
