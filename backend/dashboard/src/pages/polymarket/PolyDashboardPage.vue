<script setup>
import { ref } from 'vue'
import { usePolling } from '@/composables/usePolling'
import SectionNav from '@/components/SectionNav.vue'
import api from '@/services/api'

const polyLinks = [
  { to: '/polymarket', label: 'Dashboard' },
  { to: '/polymarket/markets', label: 'Markets' },
  { to: '/polymarket/positions', label: 'Positions' },
  { to: '/polymarket/logs', label: 'Logs' },
  { to: '/polymarket/strategy', label: 'Strategy' },
]

const botPaused = ref(false)
const botStatusLoading = ref(false)
const syncLoading = ref(false)
const openPositions = ref(0)
const totalInvested = ref(0)
const totalPnl = ref(0)

async function refresh() {
  const [botResult, dashResult] = await Promise.allSettled([
    api.getPolymarketBotStatus(),
    api.getPolymarketDashboard(),
  ])
  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }
  if (dashResult.status === 'fulfilled') {
    const d = dashResult.value
    openPositions.value = d.open_positions ?? 0
    totalInvested.value = d.total_invested ?? 0
    totalPnl.value = d.total_pnl ?? 0
  }
}

async function toggleBot() {
  botStatusLoading.value = true
  try {
    const resp = await api.setPolymarketBotPaused(!botPaused.value)
    botPaused.value = resp.paused
  } catch (err) {
    console.error('Bot toggle error:', err)
  }
  botStatusLoading.value = false
}

async function syncMarkets() {
  syncLoading.value = true
  try {
    await api.syncPolymarketMarkets()
  } catch (err) {
    console.error('Sync error:', err)
  }
  syncLoading.value = false
}

function fmt(val) {
  return Number(val).toFixed(2)
}

usePolling(refresh, 10000)
</script>

<template>
  <div class="tp-page">
    <SectionNav :links="polyLinks" />
    
    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 2rem;">
      <div>
        <h1 style="font-size: 2.25rem; font-weight: 900; letter-spacing: -0.02em;">Polymarket Dashboard</h1>
        <p style="color: var(--tp-text-muted); margin-top: 0.25rem;">Trading Pro Platform</p>
      </div>
      <div style="display: flex; gap: 0.75rem;">
        <button class="tp-btn tp-btn-outline" :disabled="syncLoading" @click="syncMarkets">
          <span class="material-symbols-outlined">sync</span>
          Sync Markets
        </button>
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
          <RouterLink to="/polymarket/positions" class="tp-btn tp-btn-outline" style="width: 100%">
            View Positions
          </RouterLink>
        </div>
      </div>

      <div class="tp-stat-card">
        <div class="stat-label">Total Invested</div>
        <div class="stat-value">${{ fmt(totalInvested) }}</div>
        <div style="margin-top: 1rem;">
          <RouterLink to="/polymarket/markets" class="tp-btn tp-btn-outline" style="width: 100%">
            View Markets
          </RouterLink>
        </div>
      </div>

      <div class="tp-stat-card">
        <div class="stat-label">Total P&amp;L</div>
        <div class="stat-value" :style="{ color: totalPnl >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
          {{ totalPnl >= 0 ? '+' : '' }}${{ fmt(totalPnl) }}
        </div>
        <div style="margin-top: 0.25rem; font-size: 0.85rem; font-weight: 700;" :style="{ color: totalPnl >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
          {{ totalPnl >= 0 ? '+' : '' }}{{ totalInvested > 0 ? ((totalPnl / totalInvested) * 100).toFixed(2) : '0.00' }}% <span style="color: var(--tp-text-dim); font-weight: 500;">all time</span>
        </div>
      </div>
    </div>
  </div>
</template>
