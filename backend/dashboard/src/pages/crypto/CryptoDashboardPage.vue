<script setup>
import { ref } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'

const cryptoLinks = [
  { to: '/crypto', label: 'Dashboard' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/logs', label: 'Logs' },
  { to: '/crypto/strategy', label: 'Strategy' },
]

const botPaused = ref(false)
const botStatusLoading = ref(false)
const openPositions = ref(0)
const totalPnl = ref(0)
const positions = ref([])

async function refresh() {
  const [botResult, dashResult] = await Promise.allSettled([
    api.getCryptoBotStatus(),
    api.getCryptoDashboard(),
  ])
  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }
  if (dashResult.status === 'fulfilled') {
    const d = dashResult.value
    openPositions.value = d.open_positions ?? 0
    totalPnl.value = d.total_pnl ?? 0
    positions.value = d.positions ?? []
  }
}

async function toggleBot() {
  botStatusLoading.value = true
  try {
    const resp = await api.setCryptoBotPaused(!botPaused.value)
    botPaused.value = resp.paused
  } catch (err) {
    console.error('Bot toggle error:', err)
  }
  botStatusLoading.value = false
}

function fmt(val) {
  return Number(val).toFixed(2)
}

usePolling(refresh, 10000)
</script>

<template>
  <div class="tp-page">
    <SectionNav :links="cryptoLinks" />
    
    <div class="page-header">
      <div>
        <h1 class="page-title">Crypto Dashboard</h1>
        <p style="color: var(--tp-text-muted); margin-top: 0.25rem;">Trading Pro Platform</p>
      </div>
    </div>

    <div class="tp-stats-grid" style="margin-bottom: 2rem;">
      <div class="tp-stat-card">
        <div class="stat-label">Bot Status</div>
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <div class="stat-value">{{ botPaused ? 'Paused' : 'Active' }}</div>
          <span v-if="!botPaused" class="tp-badge tp-badge-success">
            <span class="pulse-dot"></span> Running
          </span>
          <span v-else class="tp-badge tp-badge-warning">
            Stopped
          </span>
        </div>
        <div style="margin-top: 1rem;">
          <button class="tp-btn" :class="botPaused ? 'tp-btn-success' : 'tp-btn-outline'" style="width: 100%" :disabled="botStatusLoading" @click="toggleBot">
            <span class="material-symbols-outlined">{{ botPaused ? 'play_arrow' : 'pause' }}</span>
            {{ botPaused ? 'Resume Bot' : 'Pause Bot' }}
          </button>
        </div>
      </div>
      
      <div class="tp-stat-card">
        <div class="stat-label">Open Positions</div>
        <div class="stat-value">{{ openPositions }}</div>
        <div style="margin-top: 1rem;">
          <RouterLink to="/crypto/positions" class="tp-btn tp-btn-outline" style="width: 100%">
            View Positions
          </RouterLink>
        </div>
      </div>

      <div class="tp-stat-card">
        <div class="stat-label">Total P&amp;L</div>
        <div class="stat-value" :style="{ color: totalPnl >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
          {{ totalPnl >= 0 ? '+' : '' }}${{ fmt(totalPnl) }}
        </div>
        <div style="margin-top: 1rem;">
          <RouterLink to="/crypto/strategy" class="tp-btn tp-btn-outline" style="width: 100%">
            Strategy Config
          </RouterLink>
        </div>
      </div>
    </div>

    <div v-if="positions.length" class="tp-card" style="margin-bottom: 1.5rem;">
      <div style="padding: 1rem 1.5rem; border-bottom: 1px solid var(--tp-border);">
        <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0;">Open Positions</h3>
      </div>
      <div style="overflow-x: auto;">
        <table class="tp-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Entry Price</th>
              <th>Size</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in positions" :key="p.symbol">
              <td style="font-weight: 600;">{{ p.symbol }}</td>
              <td>
                <span class="tp-badge" :class="p.side === 'LONG' ? 'tp-badge-success' : 'tp-badge-danger'">
                  {{ p.side }}
                </span>
              </td>
              <td style="font-weight: 500;">${{ fmt(p.entry_price) }}</td>
              <td style="font-weight: 500;">{{ fmt(p.size) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 2rem;
  flex-wrap: wrap;
  gap: 1rem;
}
.page-title {
  font-size: 2.25rem;
  font-weight: 900;
  letter-spacing: -0.02em;
}
@media (max-width: 480px) {
  .page-title {
    font-size: 1.75rem;
  }
}
</style>
