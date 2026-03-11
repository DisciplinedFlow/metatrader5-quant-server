<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})

const REGIME_COLORS = {
  TRENDING:  { color: '#22c55e', bg: 'rgba(34,197,94,0.15)',  icon: 'trending_up' },
  RANGING:   { color: '#f59e0b', bg: 'rgba(245,158,11,0.15)', icon: 'swap_horiz' },
  VOLATILE:  { color: '#ef4444', bg: 'rgba(239,68,68,0.15)',  icon: 'bolt' },
  UNKNOWN:   { color: '#6b7280', bg: 'rgba(107,114,128,0.15)', icon: 'help' },
}

const DIRECTION_ARROWS = {
  UP: { icon: 'arrow_upward', color: '#22c55e' },
  DOWN: { icon: 'arrow_downward', color: '#ef4444' },
  NEUTRAL: { icon: 'remove', color: '#6b7280' },
}

const consensus = computed(() => {
  if (!props.data?.consensus) return null
  const c = props.data.consensus
  const regime = c.dominant_regime || 'UNKNOWN'
  const cfg = REGIME_COLORS[regime] || REGIME_COLORS.UNKNOWN
  return {
    regime,
    pct: c.consensus_pct ? Math.round(c.consensus_pct * 100) : 0,
    votes: c.weighted_votes || {},
    ...cfg,
  }
})

const pairs = computed(() => {
  if (!props.data?.per_pair) return []
  return Object.entries(props.data.per_pair).map(([symbol, info]) => {
    const label = info.label || 'UNKNOWN'
    const cfg = REGIME_COLORS[label] || REGIME_COLORS.UNKNOWN
    const dir = info.direction || 'NEUTRAL'
    const dirCfg = DIRECTION_ARROWS[dir] || DIRECTION_ARROWS.NEUTRAL
    return {
      symbol,
      label,
      confidence: info.confidence ? Math.round(info.confidence * 100) : 0,
      direction: dir,
      dirIcon: dirCfg.icon,
      dirColor: dirCfg.color,
      atrOverride: info.atr_override || false,
      ...cfg,
    }
  })
})
</script>

<template>
  <div class="tp-card hmm-widget">
    <div class="widget-header">
      <h3>
        <span class="material-symbols-outlined" style="color:var(--tp-primary);font-size:20px">analytics</span>
        HMM Regime
      </h3>
      <span v-if="consensus" class="consensus-badge" :style="{ color: consensus.color, background: consensus.bg }">
        {{ consensus.regime }}
      </span>
    </div>

    <div v-if="loading && !data" class="widget-loading">
      <p>Loading...</p>
    </div>

    <template v-else-if="data">
      <!-- Consensus bar -->
      <div v-if="consensus" class="consensus-section">
        <div class="consensus-meta">
          <span class="consensus-label">Market Consensus</span>
          <span class="consensus-pct">{{ consensus.pct }}% agreement</span>
        </div>
        <div class="consensus-bar-track">
          <div
            class="consensus-bar-fill"
            :style="{ width: consensus.pct + '%', background: consensus.color }"
          ></div>
        </div>
        <div v-if="Object.keys(consensus.votes).length" class="consensus-votes">
          <span
            v-for="(count, regime) in consensus.votes"
            :key="regime"
            class="vote-chip"
            :style="{ color: (REGIME_COLORS[regime] || REGIME_COLORS.UNKNOWN).color, background: (REGIME_COLORS[regime] || REGIME_COLORS.UNKNOWN).bg }"
          >
            {{ regime }} ({{ count }})
          </span>
        </div>
      </div>

      <!-- Per-pair list -->
      <div class="pair-list">
        <div v-for="pair in pairs" :key="pair.symbol" class="pair-row">
          <span class="pair-symbol">{{ pair.symbol }}</span>
          <div class="pair-right">
            <span
              class="regime-badge"
              :style="{ color: pair.color, background: pair.bg }"
            >
              <span class="material-symbols-outlined regime-icon">{{ pair.icon }}</span>
              {{ pair.label }}
            </span>
            <span
              class="dir-badge"
              :style="{ color: pair.dirColor }"
              :title="'Direction: ' + pair.direction"
            >
              <span class="material-symbols-outlined dir-icon">{{ pair.dirIcon }}</span>
            </span>
            <span class="pair-conf" :title="'Confidence: ' + pair.confidence + '%'">{{ pair.confidence }}%</span>
            <span v-if="pair.atrOverride" class="atr-flag" title="ATR override to VOLATILE">ATR</span>
          </div>
        </div>
      </div>

      <div v-if="pairs.length === 0 && !consensus" class="widget-empty">
        <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">analytics</span>
        <p>Waiting for HMM scan...</p>
      </div>
    </template>

    <div v-else class="widget-empty">
      <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">analytics</span>
      <p>No regime data available</p>
    </div>
  </div>
</template>

<style scoped>
.hmm-widget {
  padding: 1.25rem;
}

.widget-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.widget-header h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  font-weight: 700;
  margin: 0;
}

.consensus-badge {
  font-size: 0.7rem;
  font-weight: 800;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  letter-spacing: 0.03em;
}

/* Consensus section */
.consensus-section {
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--tp-border);
}

.consensus-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.35rem;
}

.consensus-label {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--tp-text);
}

.consensus-pct {
  font-size: 0.65rem;
  font-weight: 700;
  color: var(--tp-text-dim);
}

.consensus-bar-track {
  height: 6px;
  background: var(--tp-border);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.consensus-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.consensus-votes {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.vote-chip {
  font-size: 0.6rem;
  font-weight: 700;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}

/* Per-pair list */
.pair-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.pair-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.5rem;
  background: var(--tp-bg-surface);
  border-radius: var(--tp-radius-sm);
  transition: background 0.15s;
}

.pair-row:hover {
  background: var(--tp-border);
}

.pair-symbol {
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--tp-text);
  font-family: 'Inter', monospace;
  min-width: 4.5rem;
}

.pair-right {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.regime-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  font-size: 0.62rem;
  font-weight: 800;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  letter-spacing: 0.02em;
}

.regime-icon {
  font-size: 12px !important;
}

.dir-badge {
  display: inline-flex;
  align-items: center;
}

.dir-icon {
  font-size: 14px !important;
}

.pair-conf {
  font-size: 0.65rem;
  font-weight: 700;
  color: var(--tp-text-dim);
  min-width: 2.2rem;
  text-align: right;
  font-family: 'Inter', monospace;
}

.atr-flag {
  font-size: 0.55rem;
  font-weight: 800;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.12);
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  letter-spacing: 0.05em;
}

.widget-loading, .widget-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem 1rem;
  gap: 0.35rem;
  color: var(--tp-text-dim);
  font-size: 0.8rem;
  text-align: center;
}
</style>
