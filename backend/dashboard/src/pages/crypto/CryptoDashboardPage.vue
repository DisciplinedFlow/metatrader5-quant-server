<script setup>
import { ref } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'

const cryptoLinks = [
  { to: '/crypto', label: 'Dashboard' },
  { to: '/crypto/positions', label: 'Positions' },
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
  <SectionNav :links="cryptoLinks" />
  <h2>Crypto Dashboard</h2>
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
      <header>Total P&amp;L</header>
      <p>
        <strong :style="{ color: totalPnl >= 0 ? 'var(--ins-color)' : 'var(--del-color)' }">
          ${{ fmt(totalPnl) }}
        </strong>
      </p>
    </article>
  </div>

  <article v-if="positions.length">
    <header>Open Positions</header>
    <figure>
      <table>
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
            <td>{{ p.symbol }}</td>
            <td>
              <mark :class="p.side === 'LONG' ? '' : 'secondary'">{{ p.side }}</mark>
            </td>
            <td>${{ fmt(p.entry_price) }}</td>
            <td>{{ fmt(p.size) }}</td>
          </tr>
        </tbody>
      </table>
    </figure>
  </article>

  <div style="display: flex; gap: 0.75rem; margin-top: 1rem;">
    <RouterLink to="/crypto/positions" role="button" class="outline" style="margin-bottom: 0; width: auto;">View All Positions</RouterLink>
    <RouterLink to="/crypto/strategy" role="button" class="outline" style="margin-bottom: 0; width: auto;">Strategy Config</RouterLink>
  </div>
</template>
