<script setup>
import { ref, computed, onMounted } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'

const results = ref([])
const loading = ref(true)

async function refresh() {
  try {
    results.value = await api.getICTScanResults(10)
  } catch (err) {
    console.error('ICT scan fetch error:', err)
  }
  loading.value = false
}

usePolling(refresh, 60000)
onMounted(refresh)

const stepLabels = ['HTF Bias', 'Sweep', 'MSS', 'FVG', 'Price@FVG']

function gradeClass(grade) {
  if (grade === 'A+') return 'grade-aplus'
  if (grade === 'A') return 'grade-a'
  if (grade === 'B') return 'grade-b'
  return 'grade-f'
}

function directionClass(dir) {
  if (dir === 'BUY') return 'dir-buy'
  if (dir === 'SELL') return 'dir-sell'
  return ''
}

function fmtTime(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  })
}

// Deduplicate: show only one entry per symbol from the latest scan batch
const latestResults = computed(() => {
  if (!results.value.length) return []
  // Group by timestamp, take the most recent batch, then show all symbols
  const sorted = [...results.value].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
  return sorted.slice(0, 10)
})
</script>

<template>
  <div class="ict-log">
    <div class="ict-header">
      <h3>
        <span class="material-symbols-outlined" style="font-size:20px;color:var(--tp-primary)">target</span>
        ICT 5-Step Scanner
      </h3>
      <span class="ict-badge">Every 60s</span>
    </div>

    <div v-if="loading" class="ict-loading" aria-busy="true">Scanning...</div>

    <div v-else-if="latestResults.length === 0" class="ict-empty">
      <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">search_off</span>
      <p>No ICT scan results yet</p>
    </div>

    <div v-else class="ict-table-wrap">
      <table class="ict-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Dir</th>
            <th>Grade</th>
            <th class="chain-header">Chain</th>
            <th>R:R</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(r, i) in latestResults"
            :key="i"
            :class="{ 'ict-row-setup': r.grade !== 'F' }"
          >
            <td class="sym-cell"><strong>{{ r.symbol }}</strong></td>
            <td>
              <span :class="directionClass(r.direction)" class="dir-badge">
                {{ r.direction }}
              </span>
            </td>
            <td>
              <span :class="gradeClass(r.grade)" class="grade-badge">{{ r.grade }}</span>
            </td>
            <td class="chain-cell">
              <span
                v-for="(step, si) in r.steps"
                :key="si"
                class="chain-step"
                :class="step ? 'step-pass' : 'step-fail'"
                :title="stepLabels[si]"
              >{{ step ? '\u2713' : '\u2717' }}</span>
            </td>
            <td class="rr-cell">
              <span v-if="r.rr_ratio > 0" :class="r.rr_ratio >= 2.0 ? 'rr-good' : 'rr-ok'">
                {{ r.rr_ratio.toFixed(1) }}
              </span>
              <span v-else class="rr-none">-</span>
            </td>
            <td class="time-cell">{{ fmtTime(r.timestamp) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.ict-log {
  padding: 1.25rem;
}

.ict-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.ict-header h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  font-weight: 700;
  margin: 0;
}

.ict-badge {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.1);
  color: var(--tp-primary);
}

.ict-loading, .ict-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 2rem;
  color: var(--tp-text-dim);
  font-size: 0.85rem;
  text-align: center;
}

.ict-table-wrap {
  overflow-x: auto;
}

.ict-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.ict-table th {
  text-align: left;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--tp-text-dim);
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid var(--tp-border);
  white-space: nowrap;
}

.ict-table td {
  padding: 0.45rem 0.5rem;
  border-bottom: 1px solid var(--tp-border-light, rgba(128,128,128,0.08));
  white-space: nowrap;
}

.ict-row-setup {
  background: rgba(34, 197, 94, 0.03);
}

.sym-cell {
  font-family: 'Inter', monospace;
  font-size: 0.8rem;
}

/* Direction badges */
.dir-badge {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
}
.dir-buy {
  color: var(--tp-success);
  background: rgba(34, 197, 94, 0.1);
}
.dir-sell {
  color: var(--tp-danger);
  background: rgba(239, 68, 68, 0.1);
}

/* Grade badges */
.grade-badge {
  font-size: 0.7rem;
  font-weight: 800;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  display: inline-block;
  min-width: 1.8rem;
  text-align: center;
}
.grade-aplus {
  background: rgba(34, 197, 94, 0.15);
  color: #16a34a;
}
.grade-a {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}
.grade-b {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}
.grade-f {
  background: rgba(128, 128, 128, 0.08);
  color: var(--tp-text-dim);
}

/* Chain steps */
.chain-cell {
  display: flex;
  gap: 0.2rem;
  align-items: center;
}
.chain-header {
  min-width: 5rem;
}
.chain-step {
  font-size: 0.75rem;
  font-weight: 700;
  width: 1.1rem;
  height: 1.1rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
}
.step-pass {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}
.step-fail {
  background: rgba(239, 68, 68, 0.08);
  color: rgba(239, 68, 68, 0.4);
}

/* R:R */
.rr-cell {
  font-family: 'Inter', monospace;
  font-weight: 600;
}
.rr-good { color: var(--tp-success); }
.rr-ok { color: var(--tp-warning); }
.rr-none { color: var(--tp-text-dim); }

/* Time */
.time-cell {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
}
</style>
