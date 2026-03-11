<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})

const BAND_CONFIG = {
  skip:     { label: 'Skip (0-3)',     color: '#6b7280', bg: 'rgba(107,114,128,0.15)' },
  reduced:  { label: 'Reduced (4-6)',  color: '#f59e0b', bg: 'rgba(245,158,11,0.15)' },
  full:     { label: 'Full (7-8)',     color: '#22c55e', bg: 'rgba(34,197,94,0.15)' },
  enhanced: { label: 'Enhanced (9+)',  color: '#8b5cf6', bg: 'rgba(139,92,246,0.15)' },
}

const bands = computed(() => {
  if (!props.data) return []
  const bc = props.data.band_counts || {}
  const bw = props.data.band_winrates || {}
  const total = props.data.total_scored || 0
  return Object.entries(BAND_CONFIG).map(([key, cfg]) => ({
    key,
    ...cfg,
    count: bc[key] || 0,
    pct: total > 0 ? ((bc[key] || 0) / total * 100) : 0,
    winrate: bw[key],
  }))
})

const distributionBars = computed(() => {
  if (!props.data) return []
  const dist = props.data.distribution || {}
  const maxCount = Math.max(1, ...Object.values(dist))
  return Object.entries(dist).map(([score, count]) => {
    const s = parseInt(score, 10)
    let color = '#6b7280'
    if (s >= 9) color = '#8b5cf6'
    else if (s >= 7) color = '#22c55e'
    else if (s >= 4) color = '#f59e0b'
    return {
      score: s,
      count,
      pct: (count / maxCount) * 100,
      color,
    }
  })
})
</script>

<template>
  <div class="tp-card confluence-widget">
    <div class="widget-header">
      <h3>
        <span class="material-symbols-outlined" style="color:var(--tp-primary);font-size:20px">layers</span>
        Confluence Scores
      </h3>
      <span v-if="data" class="avg-badge">
        Avg: {{ data.avg_score }}
      </span>
    </div>

    <div v-if="loading && !data" class="widget-loading">
      <p>Loading...</p>
    </div>

    <template v-else-if="data && data.total_scored > 0">
      <!-- Distribution Bar Chart -->
      <div class="dist-chart">
        <div v-for="bar in distributionBars" :key="bar.score" class="dist-col">
          <div class="dist-bar-wrap">
            <div
              class="dist-bar"
              :style="{ height: Math.max(2, bar.pct) + '%', background: bar.color }"
              :title="`Score ${bar.score}: ${bar.count} trades`"
            ></div>
          </div>
          <span class="dist-label">{{ bar.score }}</span>
        </div>
      </div>

      <!-- Band Breakdown -->
      <div class="band-grid">
        <div v-for="band in bands" :key="band.key" class="band-item" :style="{ borderLeftColor: band.color }">
          <div class="band-top">
            <span class="band-name">{{ band.label }}</span>
            <span class="band-count" :style="{ color: band.color }">{{ band.count }}</span>
          </div>
          <div class="band-bottom">
            <div class="band-bar-track">
              <div class="band-bar-fill" :style="{ width: band.pct + '%', background: band.color }"></div>
            </div>
            <span v-if="band.winrate !== null && band.winrate !== undefined" class="band-wr">
              {{ band.winrate }}% WR
            </span>
            <span v-else class="band-wr band-wr-na">--</span>
          </div>
        </div>
      </div>

      <p class="widget-footer">{{ data.total_scored }} scored trades</p>
    </template>

    <div v-else class="widget-empty">
      <span class="material-symbols-outlined" style="font-size:1.5rem;color:var(--tp-text-dim)">layers</span>
      <p>No confluence data yet</p>
    </div>
  </div>
</template>

<style scoped>
.confluence-widget {
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

.avg-badge {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--tp-primary);
  background: rgba(99, 102, 241, 0.1);
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
}

/* Distribution bar chart */
.dist-chart {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 3.5rem;
  margin-bottom: 1rem;
  padding: 0 2px;
}

.dist-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
}

.dist-bar-wrap {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
}

.dist-bar {
  width: 100%;
  border-radius: 2px 2px 0 0;
  min-height: 2px;
  transition: height 0.3s ease;
}

.dist-label {
  font-size: 0.6rem;
  color: var(--tp-text-dim);
  margin-top: 2px;
  font-weight: 600;
}

/* Band breakdown */
.band-grid {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.band-item {
  border-left: 3px solid;
  padding: 0.35rem 0.5rem 0.35rem 0.6rem;
  background: var(--tp-bg-surface);
  border-radius: 0 var(--tp-radius-sm) var(--tp-radius-sm) 0;
}

.band-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.2rem;
}

.band-name {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--tp-text);
}

.band-count {
  font-size: 0.85rem;
  font-weight: 800;
  font-family: 'Inter', monospace;
}

.band-bottom {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.band-bar-track {
  flex: 1;
  height: 4px;
  background: var(--tp-border);
  border-radius: 2px;
  overflow: hidden;
}

.band-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}

.band-wr {
  font-size: 0.65rem;
  font-weight: 700;
  color: var(--tp-text-dim);
  white-space: nowrap;
  min-width: 3.5rem;
  text-align: right;
}

.band-wr-na {
  color: var(--tp-border);
}

.widget-footer {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
  text-align: center;
  margin-top: 0.75rem;
  margin-bottom: 0;
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
