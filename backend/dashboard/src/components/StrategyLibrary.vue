<script setup>
import { ref, computed } from 'vue'
import api from '@/services/api'

const props = defineProps({
  domain: { type: String, required: true },
})

const strategies = ref([])
const loading = ref(true)
const expandedId = ref(null)
const filter = ref('all') // 'all', 'trading', 'training', 'visualization'

async function loadStrategies() {
  loading.value = true
  try {
    const result = await api.getCustomStrategies(props.domain)
    strategies.value = Array.isArray(result) ? result : (result.results || [])
  } catch (err) {
    console.error('Failed to load strategies:', err)
  }
  loading.value = false
}

const filtered = computed(() => {
  if (filter.value === 'all') return strategies.value
  return strategies.value.filter(s => {
    const def = s.definition || {}
    if (filter.value === 'trading') return !def.is_training && !def.is_visualization
    if (filter.value === 'training') return def.is_training
    if (filter.value === 'visualization') return def.is_visualization
    return true
  })
})

const tradingCount = computed(() => strategies.value.filter(s => !s.definition?.is_training && !s.definition?.is_visualization).length)
const trainingCount = computed(() => strategies.value.filter(s => s.definition?.is_training).length)
const vizCount = computed(() => strategies.value.filter(s => s.definition?.is_visualization).length)

function toggleExpand(id) {
  expandedId.value = expandedId.value === id ? null : id
}

function getStrategyIcon(def) {
  if (def?.is_training) return 'school'
  if (def?.is_visualization) return 'visibility'
  const type = def?.cvd_type || ''
  if (type === 'absorption') return 'shield'
  if (type === 'lack_of_participants') return 'trending_down'
  if (type === 'multi_timeframe' || type === 'multi_market') return 'stacked_line_chart'
  if (type === 'extremes') return 'pin_drop'
  if (type.includes('spot') || type.includes('futures') || type.includes('yes_vs_no')) return 'compare_arrows'
  if (type === 'real_time_leading') return 'bolt'
  return 'analytics'
}

function getTypeLabel(def) {
  if (def?.is_training) return 'Training'
  if (def?.is_visualization) return 'Visualization'
  return 'Trading'
}

function getTypeBadgeClass(def) {
  if (def?.is_training) return 'tp-badge-info'
  if (def?.is_visualization) return 'tp-badge-neutral'
  return 'tp-badge-success'
}

function getConfidenceStars(def) {
  const type = def?.cvd_type
  if (type === 'absorption' || type === 'lack_of_participants' || type === 'pattern_training') return 4
  if (type === 'multi_timeframe' || type === 'extremes' || type === 'real_time_leading') return 3
  return 2
}

loadStrategies()
</script>

<template>
  <div class="strategy-library">
    <div class="library-header">
      <h3 class="library-title">
        <span class="material-symbols-outlined" style="font-size: 1.25rem;">menu_book</span>
        Strategy Library
      </h3>
      <span class="library-count">{{ strategies.length }} strategies</span>
    </div>

    <div class="library-filters">
      <button class="filter-btn" :class="{ active: filter === 'all' }" @click="filter = 'all'">
        All ({{ strategies.length }})
      </button>
      <button class="filter-btn" :class="{ active: filter === 'trading' }" @click="filter = 'trading'">
        Trading ({{ tradingCount }})
      </button>
      <button class="filter-btn" :class="{ active: filter === 'training' }" @click="filter = 'training'">
        Training ({{ trainingCount }})
      </button>
      <button class="filter-btn" :class="{ active: filter === 'visualization' }" @click="filter = 'visualization'">
        Visual ({{ vizCount }})
      </button>
    </div>

    <div v-if="loading" style="padding: 2rem; text-align: center; color: var(--tp-text-dim);">
      Loading strategies...
    </div>

    <div v-else-if="!filtered.length" style="padding: 2rem; text-align: center; color: var(--tp-text-dim);">
      No strategies found.
    </div>

    <div v-else class="strategy-list">
      <div
        v-for="s in filtered"
        :key="s.id"
        class="strategy-item"
        :class="{ expanded: expandedId === s.id }"
      >
        <div class="strategy-summary" @click="toggleExpand(s.id)">
          <div class="strategy-icon">
            <span class="material-symbols-outlined">{{ getStrategyIcon(s.definition) }}</span>
          </div>
          <div class="strategy-info">
            <div class="strategy-name">{{ s.name }}</div>
            <div class="strategy-desc">{{ s.description }}</div>
          </div>
          <div class="strategy-meta">
            <span class="tp-badge" :class="getTypeBadgeClass(s.definition)">
              {{ getTypeLabel(s.definition) }}
            </span>
            <span class="confidence-stars" :title="getConfidenceStars(s.definition) + '/4 confidence'">
              <span v-for="i in 4" :key="i" :class="{ filled: i <= getConfidenceStars(s.definition) }">&#9733;</span>
            </span>
          </div>
          <span class="material-symbols-outlined expand-icon">
            {{ expandedId === s.id ? 'expand_less' : 'expand_more' }}
          </span>
        </div>

        <div v-if="expandedId === s.id" class="strategy-details">
          <!-- Indicators -->
          <div v-if="s.definition?.indicators?.length" class="detail-section">
            <h4>Indicators</h4>
            <div class="indicator-tags">
              <span v-for="(ind, i) in s.definition.indicators" :key="i" class="indicator-tag">
                {{ ind.type }}
                <span v-if="ind.params?.source" class="tag-detail">{{ ind.params.source }}</span>
                <span v-if="ind.params?.lookback" class="tag-detail">lb:{{ ind.params.lookback }}</span>
              </span>
            </div>
          </div>

          <!-- Config summary -->
          <div v-if="s.definition?.timeframe || s.definition?.pairs" class="detail-section">
            <h4>Configuration</h4>
            <div class="config-grid">
              <div v-if="s.definition.timeframe" class="config-item">
                <span class="config-label">Timeframe</span>
                <span class="config-value">{{ s.definition.timeframe }}</span>
              </div>
              <div v-if="s.definition.timeframes" class="config-item">
                <span class="config-label">MTF</span>
                <span class="config-value">{{ s.definition.timeframes.join(', ') }}</span>
              </div>
              <div v-if="s.definition.pairs" class="config-item">
                <span class="config-label">Pairs</span>
                <span class="config-value">{{ s.definition.pairs.join(', ') }}</span>
              </div>
              <div v-if="s.definition.min_win_rate" class="config-item">
                <span class="config-label">Min Win Rate</span>
                <span class="config-value">{{ (s.definition.min_win_rate * 100).toFixed(0) }}%</span>
              </div>
            </div>
          </div>

          <!-- Entry Rules -->
          <div v-if="s.definition?.entry_rules" class="detail-section">
            <h4>Entry Rules</h4>
            <div v-for="(rules, side) in s.definition.entry_rules" :key="side" class="entry-side">
              <span class="side-label" :class="side.includes('long') || side.includes('yes') ? 'side-long' : 'side-short'">
                {{ side.replace('_', ' ').toUpperCase() }}
              </span>
              <div v-for="(rule, i) in rules" :key="i" class="rule-text">
                {{ rule.description }}
              </div>
            </div>
          </div>

          <!-- Exit Rules -->
          <div v-if="s.definition?.exit_rules" class="detail-section">
            <h4>Exit Rules</h4>
            <div class="config-grid">
              <div class="config-item">
                <span class="config-label">Type</span>
                <span class="config-value">{{ s.definition.exit_rules.type?.replace('_', ' ') }}</span>
              </div>
              <div v-for="(val, key) in s.definition.exit_rules.params" :key="key" class="config-item">
                <span class="config-label">{{ key.replace(/_/g, ' ') }}</span>
                <span class="config-value">{{ val }}</span>
              </div>
            </div>
          </div>

          <!-- Trading Rules -->
          <div v-if="s.definition?.rules?.length" class="detail-section">
            <h4>Rules</h4>
            <ol class="rules-list">
              <li v-for="(rule, i) in s.definition.rules" :key="i">{{ rule }}</li>
            </ol>
          </div>

          <!-- Training Rules -->
          <div v-if="s.definition?.training_rules?.length" class="detail-section">
            <h4>Training Steps</h4>
            <ol class="rules-list">
              <li v-for="(rule, i) in s.definition.training_rules" :key="i">{{ rule }}</li>
            </ol>
          </div>

          <!-- Visualization Rules -->
          <div v-if="s.definition?.visualization_rules?.length" class="detail-section">
            <h4>Setup Guide</h4>
            <ol class="rules-list">
              <li v-for="(rule, i) in s.definition.visualization_rules" :key="i">{{ rule }}</li>
            </ol>
          </div>

          <!-- Warnings -->
          <div v-if="s.definition?.warnings?.length" class="detail-section warnings">
            <h4>Warnings</h4>
            <ul class="warnings-list">
              <li v-for="(w, i) in s.definition.warnings" :key="i">{{ w }}</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.strategy-library {
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius);
  background: var(--tp-bg-card);
  overflow: hidden;
}

.library-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--tp-border);
}

.library-title {
  font-size: 1.1rem;
  font-weight: 700;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.library-count {
  font-size: 0.8rem;
  color: var(--tp-text-dim);
  font-weight: 500;
}

.library-filters {
  display: flex;
  gap: 0.25rem;
  padding: 0.75rem 1.5rem;
  border-bottom: 1px solid var(--tp-border);
  overflow-x: auto;
}

.filter-btn {
  background: none;
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  color: var(--tp-text-muted);
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.35rem 0.75rem;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.filter-btn:hover {
  border-color: var(--tp-primary);
  color: var(--tp-primary);
}

.filter-btn.active {
  background: var(--tp-primary);
  border-color: var(--tp-primary);
  color: #fff;
}

.strategy-list {
  max-height: 600px;
  overflow-y: auto;
}

.strategy-item {
  border-bottom: 1px solid var(--tp-border);
}

.strategy-item:last-child {
  border-bottom: none;
}

.strategy-summary {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.5rem;
  cursor: pointer;
  transition: background 0.15s ease;
}

.strategy-summary:hover {
  background: var(--tp-bg-hover);
}

.strategy-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--tp-radius-sm);
  background: var(--tp-bg-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.strategy-icon .material-symbols-outlined {
  font-size: 20px;
  color: var(--tp-primary);
}

.strategy-info {
  flex: 1;
  min-width: 0;
}

.strategy-name {
  font-weight: 700;
  font-size: 0.9rem;
  margin-bottom: 0.2rem;
}

.strategy-desc {
  font-size: 0.78rem;
  color: var(--tp-text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.strategy-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.35rem;
  flex-shrink: 0;
}

.confidence-stars {
  font-size: 0.75rem;
  letter-spacing: 1px;
}

.confidence-stars span {
  color: var(--tp-border-light);
}

.confidence-stars span.filled {
  color: var(--tp-warning);
}

.expand-icon {
  color: var(--tp-text-dim);
  flex-shrink: 0;
}

.strategy-details {
  padding: 0 1.5rem 1.25rem;
  border-top: 1px solid var(--tp-border);
  background: var(--tp-bg-surface);
}

.detail-section {
  padding-top: 1rem;
}

.detail-section h4 {
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--tp-text-muted);
  margin: 0 0 0.5rem;
}

.indicator-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.indicator-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: var(--tp-bg-card);
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  padding: 0.25rem 0.6rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--tp-primary);
}

.tag-detail {
  color: var(--tp-text-dim);
  font-weight: 400;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.5rem;
}

.config-item {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.config-label {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
  text-transform: capitalize;
}

.config-value {
  font-size: 0.8rem;
  font-weight: 600;
}

.entry-side {
  margin-bottom: 0.75rem;
}

.side-label {
  display: inline-block;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.15rem 0.5rem;
  border-radius: var(--tp-radius-sm);
  margin-bottom: 0.35rem;
}

.side-long {
  background: rgba(52, 211, 153, 0.15);
  color: var(--tp-success);
}

.side-short {
  background: rgba(248, 113, 113, 0.15);
  color: var(--tp-danger);
}

.rule-text {
  font-size: 0.8rem;
  color: var(--tp-text-muted);
  padding-left: 0.5rem;
  border-left: 2px solid var(--tp-border);
  margin-top: 0.25rem;
}

.rules-list {
  margin: 0;
  padding-left: 1.25rem;
  font-size: 0.8rem;
  color: var(--tp-text-muted);
  line-height: 1.6;
}

.warnings {
  margin-top: 0.5rem;
}

.warnings h4 {
  color: var(--tp-warning);
}

.warnings-list {
  margin: 0;
  padding-left: 1.25rem;
  font-size: 0.78rem;
  color: var(--tp-warning);
  line-height: 1.6;
}

@media (max-width: 640px) {
  .strategy-summary {
    padding: 0.75rem 1rem;
    gap: 0.75rem;
  }

  .strategy-icon {
    width: 32px;
    height: 32px;
  }

  .strategy-icon .material-symbols-outlined {
    font-size: 16px;
  }

  .strategy-meta {
    display: none;
  }

  .strategy-details {
    padding: 0 1rem 1rem;
  }

  .config-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
