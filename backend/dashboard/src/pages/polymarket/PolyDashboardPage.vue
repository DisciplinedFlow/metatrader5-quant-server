<script setup>
import { ref } from 'vue'
import { usePolling } from '@/composables/usePolling'
import SectionNav from '@/components/SectionNav.vue'
import api from '@/services/api'

const polyLinks = [
  { to: '/polymarket', label: 'Dashboard' },
  { to: '/polymarket/markets', label: 'Markets' },
  { to: '/polymarket/positions', label: 'Positions' },
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
  <SectionNav :links="polyLinks" />
  <h2>Polymarket Dashboard</h2>
  <div class="grid">
    <article>
      <header>Bot Status</header>
      <dl>
        <dt>Status</dt>
        <dd>
          <mark :class="botPaused ? 'secondary' : ''">
            {{ botPaused ? 'PAUSED' : 'RUNNING' }}
          </mark>
        </dd>
      </dl>
      <button
        :class="botPaused ? '' : 'outline secondary'"
        :aria-busy="botStatusLoading"
        style="width: auto; padding: 0.5rem 1rem; margin-bottom: 0;"
        @click="toggleBot"
      >
        {{ botPaused ? 'Resume Bot' : 'Pause Bot' }}
      </button>
    </article>
    <article>
      <header>Open Positions</header>
      <p><strong>{{ openPositions }}</strong></p>
    </article>
    <article>
      <header>Total Invested</header>
      <p><strong>${{ fmt(totalInvested) }}</strong></p>
    </article>
    <article>
      <header>Total P&amp;L</header>
      <p>
        <strong :style="{ color: totalPnl >= 0 ? 'var(--ins-color)' : 'var(--del-color)' }">
          ${{ fmt(totalPnl) }}
        </strong>
      </p>
    </article>
  </div>
  <div style="display: flex; gap: 0.75rem; margin-top: 1rem;">
    <button :aria-busy="syncLoading" @click="syncMarkets" style="margin-bottom: 0; width: auto;">Sync Markets</button>
    <RouterLink to="/polymarket/markets" role="button" class="outline" style="margin-bottom: 0; width: auto;">View Markets</RouterLink>
    <RouterLink to="/polymarket/positions" role="button" class="outline" style="margin-bottom: 0; width: auto;">View Positions</RouterLink>
  </div>
</template>
