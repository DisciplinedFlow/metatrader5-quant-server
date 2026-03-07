<script setup>
import { ref } from 'vue'
import { usePositionsStore } from '@/stores/positions'
import { usePolling } from '@/composables/usePolling'
import PositionsTable from '@/components/PositionsTable.vue'
import MarketSessions from '@/components/MarketSessions.vue'
import SectionNav from '@/components/SectionNav.vue'
import api from '@/services/api'

const forexLinks = [
  { to: '/forex', label: 'Overview' },
  { to: '/forex/positions', label: 'Positions' },
  { to: '/forex/order', label: 'Order' },
  { to: '/forex/history', label: 'History' },
  { to: '/forex/chart', label: 'Chart' },
  { to: '/forex/logs', label: 'Logs' },
  { to: '/forex/strategy', label: 'Strategies' },
]

const positionsStore = usePositionsStore()
const tick = ref(null)
const tickError = ref(false)
const posError = ref(false)
const botPaused = ref(false)
const botStatusLoading = ref(false)

async function refresh() {
  const [posResult, tickResult, botResult] = await Promise.allSettled([
    positionsStore.fetchPositions(),
    api.symbolInfoTick('EURUSD'),
    api.getBotStatus(),
  ])

  posError.value = posResult.status === 'rejected'
  if (tickResult.status === 'fulfilled') {
    tick.value = tickResult.value
    tickError.value = false
  } else {
    tickError.value = true
  }
  if (botResult.status === 'fulfilled') {
    botPaused.value = botResult.value.paused
  }
}

async function toggleBot() {
  botStatusLoading.value = true
  try {
    const resp = await api.setBotPaused(!botPaused.value)
    botPaused.value = resp.paused
  } catch (err) {
    console.error('Bot toggle error:', err)
  }
  botStatusLoading.value = false
}

usePolling(refresh, 5000)
</script>

<template>
  <SectionNav :links="forexLinks" />
  <h2>Account Overview</h2>
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
        @click="toggleBot"
      >
        {{ botPaused ? 'Resume Bot' : 'Pause Bot' }}
      </button>
    </article>

    <article>
      <header>Open Positions</header>
      <template v-if="!posError">
        <dl>
          <dt>Count</dt><dd>{{ positionsStore.positions.length }}</dd>
          <dt>Total Profit</dt>
          <dd :class="positionsStore.totalProfit >= 0 ? 'profit' : 'loss'">
            {{ positionsStore.totalProfit.toFixed(2) }}
          </dd>
          <dt>Total Swap</dt><dd>{{ positionsStore.totalSwap.toFixed(2) }}</dd>
        </dl>
      </template>
      <p v-else>Failed to load</p>
    </article>

    <article>
      <header>Market Tick (EURUSD)</header>
      <template v-if="tick && !tickError">
        <dl>
          <dt>Bid</dt><dd>{{ tick.bid }}</dd>
          <dt>Ask</dt><dd>{{ tick.ask }}</dd>
          <dt>Spread</dt><dd>{{ ((tick.ask - tick.bid) * 100000).toFixed(1) }} pts</dd>
          <dt>Last</dt><dd>{{ tick.last || 'N/A' }}</dd>
        </dl>
      </template>
      <p v-else-if="tickError">Failed to load</p>
      <p v-else aria-busy="true">Loading...</p>
    </article>
  </div>

  <MarketSessions />

  <article>
    <header>Active Positions</header>
    <PositionsTable :positions="positionsStore.positions" />
  </article>
</template>
