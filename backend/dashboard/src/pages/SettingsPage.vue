<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'

const toast = useToast()

// --- Config ---
const config = ref({
  mode: 'remote',
  ssh_host: '',
  ssh_user: '',
  ssh_key_path: '~/.ssh/id_ed25519',
  ssh_port: 22,
  remote_training_dir: '~/quant-training',
  train_xgboost: true,
  train_llm: true,
})
const configLoading = ref(true)
const configSaving = ref(false)

async function loadConfig() {
  try {
    const data = await api.getTrainingConfig()
    Object.assign(config.value, data)
  } catch (err) {
    console.error('Config load error:', err)
  }
  configLoading.value = false
}

async function saveConfig() {
  configSaving.value = true
  try {
    await api.updateTrainingConfig(config.value)
    toast.success('Configuration saved')
  } catch (err) {
    toast.error(`Save failed: ${err.message}`)
  }
  configSaving.value = false
}

// --- Training Run ---
const currentRun = ref(null)
const training = ref(false)
const trainError = ref('')
const logEl = ref(null)

const isRunning = computed(() =>
  currentRun.value && ['pending', 'running'].includes(currentRun.value.status)
)

const stepLabel = computed(() => {
  if (!currentRun.value) return ''
  const labels = {
    queued: 'Queued',
    exporting: 'Exporting data',
    syncing_data: 'Syncing to remote',
    training_xgboost: 'Training XGBoost',
    training_llm: 'Training LLM (MLX)',
    syncing_models: 'Syncing models back',
    loading_models: 'Loading models',
    done: 'Complete',
  }
  return labels[currentRun.value.step] || currentRun.value.step
})

const stepProgress = computed(() => {
  if (!currentRun.value) return 0
  const steps = ['queued', 'exporting', 'syncing_data', 'training_xgboost', 'training_llm', 'syncing_models', 'loading_models', 'done']
  const idx = steps.indexOf(currentRun.value.step)
  return idx >= 0 ? Math.round(((idx + 1) / steps.length) * 100) : 0
})

async function startTraining(options = {}) {
  training.value = true
  trainError.value = ''
  try {
    const resp = await api.startTraining(options)
    currentRun.value = { id: resp.run_id, status: 'pending', step: 'queued', log: '' }
    startPolling()
    toast.success('Training started')
  } catch (err) {
    trainError.value = err.message
    toast.error(err.message)
  }
  training.value = false
}

async function retryTraining() {
  const opts = {}
  if (currentRun.value) {
    opts.train_xgboost = currentRun.value.train_xgboost
    opts.train_llm = currentRun.value.train_llm
  }
  await startTraining(opts)
}

async function pollStatus() {
  try {
    const runId = currentRun.value?.id
    const data = await api.getTrainingStatus(runId)
    if (data.run) {
      currentRun.value = data.run
      await nextTick()
      scrollLog()
      if (!isRunning.value) loadHistory()
    }
  } catch (err) {
    console.error('Poll error:', err)
  }
}

function scrollLog() {
  if (logEl.value) {
    logEl.value.scrollTop = logEl.value.scrollHeight
  }
}

let pollTimer = null
function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    await pollStatus()
    if (!isRunning.value) stopPolling()
  }, 2000)
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// --- History ---
const history = ref([])
const historyLoading = ref(false)

async function loadHistory() {
  historyLoading.value = true
  try {
    const data = await api.getTrainingHistory(10)
    history.value = data.runs || []
  } catch (err) {
    console.error('History error:', err)
  }
  historyLoading.value = false
}

function viewRun(run) {
  currentRun.value = run
  if (isRunning.value) startPolling()
}

// --- Lifecycle ---
onMounted(async () => {
  await Promise.all([loadConfig(), loadHistory()])
  try {
    const data = await api.getTrainingStatus()
    if (data.run) {
      currentRun.value = data.run
      if (isRunning.value) startPolling()
    }
  } catch {}
})
onUnmounted(stopPolling)

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function duration(run) {
  if (!run.completed_at) return isRunning.value ? 'Running...' : '—'
  const ms = new Date(run.completed_at) - new Date(run.started_at)
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}
</script>

<template>
  <div class="tp-page settings-page">

    <!-- Page Header -->
    <div class="page-header">
      <div>
        <h1>Settings</h1>
        <p>ML training infrastructure and system configuration.</p>
      </div>
    </div>

    <!-- ── Remote Training Configuration ───────────────────── -->
    <div class="tp-card section-card">
      <div class="section-header">
        <div class="section-icon">
          <span class="material-symbols-outlined">dns</span>
        </div>
        <div>
          <h3>Remote Training</h3>
          <p>SSH connection to your training machine.</p>
        </div>
      </div>

      <div v-if="configLoading" class="loading-state">
        <span class="material-symbols-outlined spin">progress_activity</span>
        Loading configuration...
      </div>

      <div v-else class="config-body">
        <!-- Mode Toggle -->
        <div class="mode-toggle-row">
          <span class="tp-label">Training Mode</span>
          <div class="tp-toggle">
            <button :class="{ active: config.mode === 'remote' }" @click="config.mode = 'remote'">
              <span class="material-symbols-outlined" style="font-size:16px">cloud</span> Remote
            </button>
            <button :class="{ active: config.mode === 'local' }" @click="config.mode = 'local'">
              <span class="material-symbols-outlined" style="font-size:16px">computer</span> Local
            </button>
          </div>
        </div>

        <!-- SSH Fields -->
        <div v-if="config.mode === 'remote'" class="form-grid">
          <div class="form-field">
            <label class="tp-label">SSH Host</label>
            <input class="tp-input" v-model="config.ssh_host" placeholder="192.168.1.x" />
          </div>
          <div class="form-field">
            <label class="tp-label">SSH User</label>
            <input class="tp-input" v-model="config.ssh_user" placeholder="davino" />
          </div>
          <div class="form-field">
            <label class="tp-label">SSH Key Path</label>
            <input class="tp-input" v-model="config.ssh_key_path" placeholder="~/.ssh/id_ed25519" />
          </div>
          <div class="form-field">
            <label class="tp-label">SSH Port</label>
            <input class="tp-input" v-model.number="config.ssh_port" type="number" />
          </div>
          <div class="form-field span-2">
            <label class="tp-label">Remote Training Directory</label>
            <input class="tp-input" v-model="config.remote_training_dir" placeholder="~/quant-training" />
          </div>
        </div>

        <!-- Pipelines -->
        <div class="pipelines-row">
          <label class="pipeline-toggle" :class="{ on: config.train_xgboost }">
            <input type="checkbox" v-model="config.train_xgboost" />
            <span class="toggle-track"><span class="toggle-knob"></span></span>
            <div class="toggle-label">
              <strong>XGBoost</strong>
              <span>Meta-filter model</span>
            </div>
          </label>
          <label class="pipeline-toggle" :class="{ on: config.train_llm }">
            <input type="checkbox" v-model="config.train_llm" />
            <span class="toggle-track"><span class="toggle-knob"></span></span>
            <div class="toggle-label">
              <strong>LLM Fine-tune</strong>
              <span>MLX LoRA on Qwen 2.5</span>
            </div>
          </label>
        </div>

        <!-- Save -->
        <div class="config-actions">
          <button class="tp-btn tp-btn-primary" @click="saveConfig" :disabled="configSaving" :aria-busy="configSaving">
            <span class="material-symbols-outlined" style="font-size:16px">save</span>
            {{ configSaving ? 'Saving...' : 'Save Configuration' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ── Training Execution ──────────────────────────────── -->
    <div class="tp-card section-card">
      <div class="section-header">
        <div class="section-icon section-icon-accent">
          <span class="material-symbols-outlined">model_training</span>
        </div>
        <div>
          <h3>Training Pipeline</h3>
          <p>Trigger and monitor ML model training.</p>
        </div>
        <div class="header-actions">
          <button
            v-if="currentRun && currentRun.status === 'failed'"
            class="tp-btn tp-btn-outline"
            @click="retryTraining"
            :disabled="isRunning || training"
          >
            <span class="material-symbols-outlined" style="font-size:16px">refresh</span>
            Retry
          </button>
          <button
            class="tp-btn tp-btn-primary"
            @click="startTraining()"
            :disabled="isRunning || training"
            :aria-busy="training"
          >
            <span class="material-symbols-outlined" style="font-size:16px">play_arrow</span>
            {{ training ? 'Starting...' : 'Train Now' }}
          </button>
        </div>
      </div>

      <!-- Active Run -->
      <div v-if="currentRun" class="run-panel">
        <!-- Status Bar -->
        <div class="run-status-bar" :class="'run-' + currentRun.status">
          <div class="status-left">
            <span class="status-dot" :class="{ pulse: isRunning }"></span>
            <span class="status-label">{{ currentRun.status.toUpperCase() }}</span>
            <span class="status-step" v-if="isRunning">{{ stepLabel }}</span>
          </div>
          <div class="status-right">
            <span class="status-time">{{ formatDate(currentRun.started_at) }}</span>
            <span class="status-duration">{{ duration(currentRun) }}</span>
          </div>
        </div>

        <!-- Progress Bar -->
        <div v-if="isRunning" class="progress-track">
          <div class="progress-fill" :style="{ width: stepProgress + '%' }"></div>
        </div>

        <!-- Results Cards -->
        <div v-if="currentRun.xgboost_result?.success || currentRun.llm_result?.success" class="results-grid">
          <div v-if="currentRun.xgboost_result?.success" class="result-card result-success">
            <div class="result-icon"><span class="material-symbols-outlined">analytics</span></div>
            <div class="result-body">
              <strong>XGBoost {{ currentRun.xgboost_result.model_type }}</strong>
              <div class="result-metrics">
                <span>{{ (currentRun.xgboost_result.accuracy * 100).toFixed(1) }}% acc</span>
                <span>{{ (currentRun.xgboost_result.cv_accuracy * 100).toFixed(1) }}% CV</span>
                <span>{{ currentRun.xgboost_result.trade_count }} trades</span>
              </div>
            </div>
          </div>
          <div v-if="currentRun.llm_result?.success" class="result-card result-success">
            <div class="result-icon"><span class="material-symbols-outlined">psychology</span></div>
            <div class="result-body">
              <strong>LLM v{{ currentRun.llm_result.version }}</strong>
              <div class="result-metrics">
                <span>{{ currentRun.llm_result.training_examples }} examples</span>
                <span>{{ currentRun.llm_result.train_split }} train</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Error -->
        <div v-if="currentRun.error" class="error-banner">
          <span class="material-symbols-outlined">error</span>
          {{ currentRun.error }}
        </div>

        <!-- Terminal Log -->
        <div v-if="currentRun.log" class="logs-terminal" style="margin-top: 1rem;">
          <div class="logs-terminal-header">
            <div class="dots">
              <span class="dot red"></span>
              <span class="dot yellow"></span>
              <span class="dot green"></span>
              <span class="session-label">Training Log &mdash; Run #{{ currentRun.id }}</span>
            </div>
            <div class="header-right">
              <span class="line-count">{{ currentRun.log.split('\n').length }} lines</span>
            </div>
          </div>
          <div ref="logEl" class="logs-terminal-body">
            <div
              v-for="(line, i) in currentRun.log.split('\n').filter(l => l)"
              :key="i"
              class="log-line"
              :class="{
                'level-error': line.toLowerCase().includes('error') || line.toLowerCase().includes('fail'),
                'level-exec': line.includes('===') || line.toLowerCase().includes('success') || line.toLowerCase().includes('complete'),
                'level-warning': line.toLowerCase().includes('warning') || line.toLowerCase().includes('skip'),
                'level-info': !line.toLowerCase().includes('error') && !line.includes('==='),
                'log-line-latest': i === currentRun.log.split('\n').filter(l => l).length - 1 && isRunning,
              }"
            >
              <span class="log-msg">{{ line }}</span>
              <span v-if="i === currentRun.log.split('\n').filter(l => l).length - 1 && isRunning" class="log-cursor"></span>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else class="empty-state">
        <span class="material-symbols-outlined">school</span>
        <p><strong>No training runs yet</strong></p>
        <p class="sub">Configure your remote machine above, then click Train Now.</p>
      </div>
    </div>

    <!-- ── Training History ────────────────────────────────── -->
    <div class="tp-card section-card">
      <div class="section-header">
        <div class="section-icon">
          <span class="material-symbols-outlined">history</span>
        </div>
        <div>
          <h3>Training History</h3>
          <p>Past training runs and results.</p>
        </div>
        <div class="header-actions">
          <button class="tp-btn tp-btn-outline" @click="loadHistory" :aria-busy="historyLoading">
            <span class="material-symbols-outlined" style="font-size:16px">refresh</span>
          </button>
        </div>
      </div>

      <div v-if="historyLoading" class="loading-state">
        <span class="material-symbols-outlined spin">progress_activity</span>
      </div>
      <div v-else-if="history.length" class="table-wrap">
        <table class="tp-table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Status</th>
              <th>Mode</th>
              <th>Pipelines</th>
              <th>Started</th>
              <th>Duration</th>
              <th>Accuracy</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in history" :key="r.id" :class="{ 'row-active': currentRun?.id === r.id }">
              <td class="mono">#{{ r.id }}</td>
              <td>
                <span class="tp-badge" :class="{
                  'tp-badge-success': r.status === 'success',
                  'tp-badge-danger': r.status === 'failed',
                  'tp-badge-primary': r.status === 'running',
                  'tp-badge-neutral': r.status === 'pending',
                }">
                  <span v-if="r.status === 'running'" class="pulse-dot"></span>
                  {{ r.status }}
                </span>
              </td>
              <td>{{ r.mode }}</td>
              <td>
                <span v-if="r.train_xgboost" class="tp-badge tp-badge-info" style="margin-right:4px">XGB</span>
                <span v-if="r.train_llm" class="tp-badge tp-badge-info">LLM</span>
                <span v-if="!r.train_xgboost && !r.train_llm">—</span>
              </td>
              <td style="font-size: 0.78rem;">{{ formatDate(r.started_at) }}</td>
              <td class="mono">{{ duration(r) }}</td>
              <td>
                <strong v-if="r.xgboost_result?.accuracy" class="profit">
                  {{ (r.xgboost_result.accuracy * 100).toFixed(1) }}%
                </strong>
                <span v-else style="color: var(--tp-text-dim)">—</span>
              </td>
              <td>
                <button class="tp-btn tp-btn-outline" style="padding: 0.25rem 0.6rem; font-size: 0.72rem;" @click="viewRun(r)">
                  View
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state small">
        <span class="material-symbols-outlined">folder_open</span>
        <p>No training history yet.</p>
      </div>
    </div>

  </div>
</template>

<style scoped>
/* ===== Page Layout ===== */
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0 0.25rem;
}

.page-header h1 {
  font-size: 1.35rem;
  font-weight: 800;
  letter-spacing: -0.03em;
}

.page-header p {
  font-size: 0.82rem;
  color: var(--tp-text-dim);
  margin-top: 0.15rem;
}

/* ===== Section Cards ===== */
.section-card {
  padding: 1.5rem;
}

.section-header {
  display: flex;
  align-items: flex-start;
  gap: 0.85rem;
  margin-bottom: 1.5rem;
}

.section-header h3 {
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.section-header p {
  font-size: 0.78rem;
  color: var(--tp-text-dim);
  margin-top: 0.1rem;
}

.section-header .header-actions {
  margin-left: auto;
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}

.section-icon {
  width: 38px;
  height: 38px;
  border-radius: var(--tp-radius-sm);
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.section-icon .material-symbols-outlined {
  font-size: 20px;
  color: var(--tp-primary);
}

.section-icon-accent {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.15);
}

.section-icon-accent .material-symbols-outlined {
  color: #818cf8;
}

/* ===== Config Form ===== */
.config-body {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.mode-toggle-row {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.mode-toggle-row .tp-label {
  margin: 0;
  white-space: nowrap;
}

.mode-toggle-row .tp-toggle {
  max-width: 280px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.form-field .tp-label {
  margin-bottom: 0.4rem;
}

.span-2 {
  grid-column: span 2;
}

@media (max-width: 640px) {
  .form-grid { grid-template-columns: 1fr; }
  .span-2 { grid-column: span 1; }
  .mode-toggle-row { flex-direction: column; align-items: flex-start; }
}

/* ===== Pipeline Toggles ===== */
.pipelines-row {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}

.pipeline-toggle {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: var(--tp-bg-surface);
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  cursor: pointer;
  transition: all 0.15s ease;
  flex: 1;
  min-width: 200px;
}

.pipeline-toggle:hover {
  border-color: var(--tp-border-light);
}

.pipeline-toggle.on {
  border-color: rgba(59, 130, 246, 0.3);
  background: rgba(59, 130, 246, 0.04);
}

.pipeline-toggle input { display: none; }

.toggle-track {
  position: relative;
  width: 36px;
  min-width: 36px;
  height: 20px;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  transition: background 0.2s, border-color 0.2s;
}

.pipeline-toggle.on .toggle-track {
  background: var(--tp-primary);
  border-color: var(--tp-primary);
}

.toggle-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
}

.pipeline-toggle.on .toggle-knob {
  transform: translateX(16px);
}

.toggle-label strong {
  display: block;
  font-size: 0.82rem;
  color: var(--tp-text);
}

.toggle-label span {
  font-size: 0.72rem;
  color: var(--tp-text-dim);
}

/* ===== Config Actions ===== */
.config-actions {
  padding-top: 0.5rem;
  border-top: 1px solid var(--tp-border);
}

/* ===== Run Panel ===== */
.run-panel {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.run-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.65rem 1rem;
  border-radius: var(--tp-radius-sm);
  background: var(--tp-bg-surface);
  border: 1px solid var(--tp-border);
  flex-wrap: wrap;
  gap: 0.5rem;
}

.status-left {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.run-pending .status-dot { background: var(--tp-text-dim); }
.run-running .status-dot { background: var(--tp-primary); }
.run-success .status-dot { background: var(--tp-success); }
.run-failed .status-dot { background: var(--tp-danger); }

.status-dot.pulse {
  animation: pulse-glow 2s ease-in-out infinite;
  box-shadow: 0 0 8px var(--tp-primary-glow);
}

.status-label {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.run-pending .status-label { color: var(--tp-text-dim); }
.run-running .status-label { color: var(--tp-primary); }
.run-success .status-label { color: var(--tp-success); }
.run-failed .status-label { color: var(--tp-danger); }

.status-step {
  font-size: 0.78rem;
  color: var(--tp-text-muted);
  padding-left: 0.6rem;
  border-left: 1px solid var(--tp-border);
}

.status-right {
  display: flex;
  gap: 1rem;
  font-size: 0.72rem;
  color: var(--tp-text-dim);
}

.status-duration {
  font-family: var(--tp-font-mono);
  font-weight: 600;
  color: var(--tp-text-muted);
}

/* ===== Progress Bar ===== */
.progress-track {
  height: 3px;
  background: var(--tp-border);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--tp-gradient-primary);
  border-radius: 2px;
  transition: width 0.6s ease;
}

/* ===== Result Cards ===== */
.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 0.75rem;
}

.result-card {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  border-radius: var(--tp-radius-sm);
}

.result-success {
  background: rgba(52, 211, 153, 0.06);
  border: 1px solid rgba(52, 211, 153, 0.15);
}

.result-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(52, 211, 153, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.result-icon .material-symbols-outlined {
  font-size: 18px;
  color: var(--tp-success);
}

.result-body strong {
  font-size: 0.82rem;
  display: block;
  margin-bottom: 0.2rem;
}

.result-metrics {
  display: flex;
  gap: 0.75rem;
  font-size: 0.72rem;
  color: var(--tp-text-dim);
}

.result-metrics span {
  font-family: var(--tp-font-mono);
}

/* ===== Error Banner ===== */
.error-banner {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-radius: var(--tp-radius-sm);
  background: rgba(248, 113, 113, 0.06);
  border: 1px solid rgba(248, 113, 113, 0.15);
  color: var(--tp-danger);
  font-size: 0.82rem;
  line-height: 1.4;
}

.error-banner .material-symbols-outlined {
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 1px;
}

/* ===== Empty State ===== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 2.5rem 1rem;
  color: var(--tp-text-dim);
  text-align: center;
}

.empty-state .material-symbols-outlined {
  font-size: 48px;
  opacity: 0.2;
  margin-bottom: 0.75rem;
}

.empty-state p { margin: 0; }
.empty-state strong { color: var(--tp-text-muted); font-size: 0.95rem; }
.empty-state .sub { font-size: 0.8rem; margin-top: 0.25rem; max-width: 320px; }
.empty-state.small { padding: 1.5rem 1rem; }
.empty-state.small .material-symbols-outlined { font-size: 32px; }

/* ===== Loading ===== */
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 2rem;
  color: var(--tp-text-dim);
  font-size: 0.85rem;
}

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 1s linear infinite; }

/* ===== Table ===== */
.table-wrap { overflow-x: auto; }

.row-active {
  background: rgba(59, 130, 246, 0.04) !important;
}

.mono {
  font-family: var(--tp-font-mono);
  font-size: 0.78rem;
}
</style>
