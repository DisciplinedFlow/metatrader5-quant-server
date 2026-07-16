<script setup>
import { ref, computed, onMounted } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'

const summary = ref(null)
const health = ref(null)
const loading = ref(true)

async function refresh() {
  try {
    const [s, h] = await Promise.all([
      api.django('v1/knowledge-graph/summary/'),
      api.django('v1/knowledge-graph/health/'),
    ])
    summary.value = s
    health.value = h
  } catch (err) {
    console.error('Knowledge graph error:', err)
  }
  loading.value = false
}

usePolling(refresh, 30000)
onMounted(refresh)

const connected = computed(() => health.value?.connected ?? false)
const statusText = computed(() => health.value?.status ?? 'unknown')

const totalTrades = computed(() => summary.value?.trades ?? 0)
const totalConditions = computed(() => summary.value?.conditions ?? 0)
const totalNews = computed(() => summary.value?.news ?? 0)

const nodeBreakdown = computed(() => {
  if (!summary.value) return []
  const keys = [
    { key: 'trades', label: 'Trades' },
    { key: 'symbols', label: 'Symbols' },
    { key: 'strategies', label: 'Strategies' },
    { key: 'regimes', label: 'Regimes' },
    { key: 'conditions', label: 'Conditions' },
    { key: 'news', label: 'News' },
    { key: 'rejected_signals', label: 'RejectedSignals' },
    { key: 'exit_events', label: 'ExitEvents' },
    { key: 'ict_partials', label: 'ICTPartials' },
    { key: 'confluence_breakdowns', label: 'ConfluenceBreakdowns' },
  ]
  return keys.map(({ key, label }) => ({
    label,
    count: summary.value[key] ?? 0,
  }))
})

const recentActivity = computed(() => summary.value?.recent_activity ?? [])

// Self-refinement phase logic
const graphPhase = computed(() => {
  if (!summary.value) return 1
  const t = summary.value.trades ?? 0
  if (t >= 200) return 3
  if (t >= 50) return 2
  return 1
})

const phaseLabel = computed(() => {
  switch (graphPhase.value) {
    case 1: return 'Phase 1: Recording'
    case 2: return 'Phase 2: Learning'
    case 3: return 'Phase 3: Recommending'
    default: return 'Unknown'
  }
})

const graphFeaturesActive = computed(() => summary.value?.graph_features_active ?? false)
const graphRouterSignal = computed(() => summary.value?.graph_router_signal ?? false)

function fmtTime(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}
</script>

<template>
  <div class="tp-page kg-page">
    <!-- Header -->
    <div class="kg-header">
      <div>
        <h1>Knowledge Brain</h1>
        <p class="kg-subtitle">Neo4j graph database — trade memory and self-refinement engine.</p>
      </div>
      <div class="kg-status-pill" :class="connected ? 'pill-connected' : 'pill-disconnected'">
        <span class="kg-status-dot" :class="connected ? 'dot-green' : 'dot-red'"></span>
        {{ connected ? 'Connected' : 'Disconnected' }}
      </div>
    </div>

    <div v-if="loading" class="kg-loading">Loading knowledge graph data...</div>

    <template v-else>
      <!-- Section 1: Graph Health & Stats -->
      <div class="tp-stats-grid" style="margin-bottom:1.25rem;padding-left:1.15rem;padding-right:1.15rem;">
        <div class="tp-stat-card">
          <div class="stat-label">Status</div>
          <div class="stat-value">
            <span class="kg-health-indicator" :class="connected ? 'ind-green' : 'ind-red'"></span>
            {{ connected ? 'Online' : 'Offline' }}
          </div>
          <div class="stat-sub">{{ statusText }}</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Trade Nodes</div>
          <div class="stat-value" style="color:var(--tp-primary)">{{ totalTrades }}</div>
          <div class="stat-sub">Recorded trades</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">Condition Nodes</div>
          <div class="stat-value" style="color:var(--tp-warning)">{{ totalConditions }}</div>
          <div class="stat-sub">Market conditions</div>
        </div>
        <div class="tp-stat-card">
          <div class="stat-label">News Nodes</div>
          <div class="stat-value" style="color:var(--tp-success)">{{ totalNews }}</div>
          <div class="stat-sub">News events linked</div>
        </div>
      </div>

      <!-- Section 2: Node Breakdown -->
      <div class="tp-card" style="margin-bottom:1.25rem;">
        <h4>Node Breakdown</h4>
        <p class="chart-desc">Count of each node type in the knowledge graph.</p>
        <div class="table-responsive">
          <table class="kg-table">
            <thead>
              <tr>
                <th>Node Type</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in nodeBreakdown" :key="row.label">
                <td>
                  <span class="kg-node-badge" :class="'badge-' + row.label.toLowerCase()">{{ row.label }}</span>
                </td>
                <td class="kg-count-cell">{{ row.count.toLocaleString() }}</td>
              </tr>
              <tr v-if="nodeBreakdown.length === 0">
                <td colspan="2" style="text-align:center;color:var(--tp-text-dim);">No data available</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Section 3: Recent Graph Activity -->
      <div class="tp-card" style="margin-bottom:1.25rem;">
        <div class="kg-section-header">
          <div>
            <h4>Recent Graph Activity</h4>
            <p class="chart-desc">Last 10 recorded items — auto-refreshes every 30s.</p>
          </div>
          <span class="kg-live-badge">
            <span class="kg-live-dot"></span>
            LIVE
          </span>
        </div>
        <div v-if="recentActivity.length === 0" class="kg-empty-state">
          <span class="material-symbols-outlined" style="font-size:2rem;color:var(--tp-text-dim)">timeline</span>
          <p class="empty-desc">No recent activity recorded yet.</p>
        </div>
        <div v-else class="kg-activity-list">
          <div v-for="(item, i) in recentActivity" :key="i" class="kg-activity-item">
            <div class="kg-activity-icon" :class="{
              'icon-trade': item.type === 'trade',
              'icon-rejection': item.type === 'rejection',
              'icon-exit': item.type === 'exit_event',
              'icon-default': !['trade', 'rejection', 'exit_event'].includes(item.type),
            }">
              <span class="material-symbols-outlined" style="font-size:16px;">
                {{ item.type === 'trade' ? 'swap_vert' : item.type === 'rejection' ? 'block' : item.type === 'exit_event' ? 'logout' : 'circle' }}
              </span>
            </div>
            <div class="kg-activity-content">
              <div class="kg-activity-title">
                <span class="kg-activity-type">{{ item.type }}</span>
                <span v-if="item.symbol" class="kg-activity-symbol">{{ item.symbol }}</span>
                <span v-if="item.direction" class="kg-activity-dir" :style="item.direction === 'BUY' ? 'color:var(--tp-success)' : 'color:var(--tp-danger)'">
                  {{ item.direction }}
                </span>
              </div>
              <div v-if="item.detail" class="kg-activity-detail">{{ item.detail }}</div>
            </div>
            <div class="kg-activity-time">{{ fmtTime(item.timestamp) }}</div>
          </div>
        </div>
      </div>

      <!-- Section 4: Self-Refinement Status -->
      <div class="tp-card">
        <h4>Self-Refinement Status</h4>
        <p class="chart-desc">Knowledge graph learning progression and integration status.</p>
        <div class="kg-refinement-grid">
          <!-- Phase Indicator -->
          <div class="kg-refinement-item">
            <div class="kg-refinement-label">Current Phase</div>
            <div class="kg-phase-indicator">
              <div class="kg-phase-step" :class="{ 'phase-active': graphPhase >= 1, 'phase-current': graphPhase === 1 }">
                <span class="phase-num">1</span>
                <span class="phase-name">Recording</span>
              </div>
              <div class="kg-phase-connector" :class="{ 'connector-active': graphPhase >= 2 }"></div>
              <div class="kg-phase-step" :class="{ 'phase-active': graphPhase >= 2, 'phase-current': graphPhase === 2 }">
                <span class="phase-num">2</span>
                <span class="phase-name">Learning</span>
              </div>
              <div class="kg-phase-connector" :class="{ 'connector-active': graphPhase >= 3 }"></div>
              <div class="kg-phase-step" :class="{ 'phase-active': graphPhase >= 3, 'phase-current': graphPhase === 3 }">
                <span class="phase-num">3</span>
                <span class="phase-name">Recommending</span>
              </div>
            </div>
            <div class="kg-phase-label">{{ phaseLabel }}</div>
          </div>

          <!-- Feature flags -->
          <div class="kg-flags-row">
            <div class="kg-flag-card">
              <div class="kg-flag-title">Graph Features Active</div>
              <div class="kg-flag-value" :class="graphFeaturesActive ? 'flag-yes' : 'flag-no'">
                {{ graphFeaturesActive ? 'Yes' : 'No' }}
              </div>
              <div class="kg-flag-desc">Node/edge recording to Neo4j</div>
            </div>
            <div class="kg-flag-card">
              <div class="kg-flag-title">Graph Router Signal</div>
              <div class="kg-flag-value" :class="graphRouterSignal ? 'flag-yes' : 'flag-no'">
                {{ graphRouterSignal ? 'Yes' : 'No' }}
              </div>
              <div class="kg-flag-desc">Graph-based entry recommendations</div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.kg-page { padding: 1.5rem 1.5rem 2rem; }

/* Header */
.kg-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1.25rem;
  padding-left: 1.15rem;
  padding-right: 1.15rem;
}
.kg-header h1 { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em; margin: 0; }
.kg-subtitle { font-size: 0.8rem; color: var(--tp-text-dim); margin: 0.1rem 0 0; }
.stat-sub { font-size: 0.7rem; color: var(--tp-text-dim); }
.kg-loading { text-align: center; padding: 3rem; color: var(--tp-text-dim); }

/* Status pill */
.kg-status-pill {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.35rem 0.85rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.pill-connected { background: rgba(34, 197, 94, 0.12); color: var(--tp-success); }
.pill-disconnected { background: rgba(239, 68, 68, 0.12); color: var(--tp-danger); }
.kg-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.dot-green { background: var(--tp-success); box-shadow: 0 0 6px var(--tp-success); }
.dot-red { background: var(--tp-danger); box-shadow: 0 0 6px var(--tp-danger); }

/* Health indicator inline */
.kg-health-indicator {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 0.35rem;
  vertical-align: middle;
}
.ind-green { background: var(--tp-success); box-shadow: 0 0 8px var(--tp-success); }
.ind-red { background: var(--tp-danger); box-shadow: 0 0 8px var(--tp-danger); }

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
.table-responsive { overflow-x: auto; }

/* Node Breakdown Table */
.kg-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.kg-table thead th {
  text-align: left;
  padding: 0.55rem 0.75rem;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--tp-text-dim);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.kg-table tbody td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}
.kg-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.02);
}
.kg-count-cell {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--tp-text);
}

/* Node badges */
.kg-node-badge {
  display: inline-block;
  padding: 0.15rem 0.55rem;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.badge-trades { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
.badge-symbols { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
.badge-strategies { background: rgba(168, 85, 247, 0.15); color: #c084fc; }
.badge-regimes { background: rgba(245, 158, 11, 0.15); color: #fbbf24; }
.badge-conditions { background: rgba(234, 179, 8, 0.15); color: #facc15; }
.badge-news { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.badge-rejectedsignals { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.badge-exitevents { background: rgba(236, 72, 153, 0.15); color: #f472b6; }
.badge-ictpartials { background: rgba(14, 165, 233, 0.15); color: #38bdf8; }
.badge-confluencebreakdowns { background: rgba(139, 92, 246, 0.15); color: #a78bfa; }

/* Section header with live badge */
.kg-section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.kg-live-badge {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--tp-success);
  padding: 0.2rem 0.55rem;
  border-radius: 4px;
  background: rgba(34, 197, 94, 0.1);
}
.kg-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--tp-success);
  animation: kg-pulse 1.5s ease-in-out infinite;
}
@keyframes kg-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* Empty state */
.kg-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 2rem 0;
}
.empty-desc { font-size: 0.78rem; color: var(--tp-text-dim); margin: 0; }

/* Activity list */
.kg-activity-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.kg-activity-item {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.55rem 0.65rem;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.015);
  transition: background 0.15s ease;
}
.kg-activity-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

/* Activity icons */
.kg-activity-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  min-width: 30px;
  border-radius: 6px;
}
.icon-trade { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
.icon-rejection { background: rgba(239, 68, 68, 0.12); color: var(--tp-danger); }
.icon-exit { background: rgba(245, 158, 11, 0.12); color: var(--tp-warning); }
.icon-default { background: rgba(255, 255, 255, 0.05); color: var(--tp-text-dim); }

.kg-activity-content { flex: 1; min-width: 0; }
.kg-activity-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.78rem;
  font-weight: 600;
}
.kg-activity-type {
  text-transform: capitalize;
}
.kg-activity-symbol {
  font-weight: 700;
  color: var(--tp-text);
}
.kg-activity-dir {
  font-size: 0.68rem;
  font-weight: 700;
}
.kg-activity-detail {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
  margin-top: 0.1rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kg-activity-time {
  font-size: 0.68rem;
  color: var(--tp-text-dim);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* Self-Refinement */
.kg-refinement-grid {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.kg-refinement-item {}
.kg-refinement-label {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--tp-text-dim);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.65rem;
}

/* Phase indicator */
.kg-phase-indicator {
  display: flex;
  align-items: center;
  gap: 0;
  margin-bottom: 0.5rem;
}
.kg-phase-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
  padding: 0.6rem 1rem;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  transition: all 0.2s ease;
  min-width: 90px;
}
.kg-phase-step.phase-active {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.2);
}
.kg-phase-step.phase-current {
  background: rgba(99, 102, 241, 0.15);
  border-color: rgba(99, 102, 241, 0.4);
  box-shadow: 0 0 12px rgba(99, 102, 241, 0.15);
}
.phase-num {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 0.7rem;
  font-weight: 800;
  background: rgba(255, 255, 255, 0.06);
  color: var(--tp-text-dim);
}
.phase-active .phase-num {
  background: var(--tp-primary);
  color: #fff;
}
.phase-name {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--tp-text-dim);
}
.phase-active .phase-name {
  color: var(--tp-text);
}
.phase-current .phase-name {
  color: #818cf8;
}
.kg-phase-connector {
  width: 28px;
  height: 2px;
  background: rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}
.connector-active {
  background: var(--tp-primary);
}
.kg-phase-label {
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--tp-text);
}

/* Feature flags row */
.kg-flags-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.85rem;
}
@media (max-width: 480px) {
  .kg-flags-row { grid-template-columns: 1fr; }
}
.kg-flag-card {
  padding: 0.85rem 1rem;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
}
.kg-flag-title {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--tp-text-dim);
  margin-bottom: 0.3rem;
}
.kg-flag-value {
  font-size: 1.15rem;
  font-weight: 800;
  margin-bottom: 0.2rem;
}
.flag-yes { color: var(--tp-success); }
.flag-no { color: var(--tp-danger); }
.kg-flag-desc {
  font-size: 0.65rem;
  color: var(--tp-text-dim);
}
</style>
