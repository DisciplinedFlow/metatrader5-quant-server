<script setup>
import { ref, computed } from 'vue'
import { usePolling } from '@/composables/usePolling'
import SectionNav from '@/components/SectionNav.vue'
import api from '@/services/api'

const polyLinks = [
  { to: '/polymarket', label: 'Dashboard' },
  { to: '/polymarket/markets', label: 'Markets' },
  { to: '/polymarket/positions', label: 'Positions' },
  { to: '/polymarket/strategy', label: 'Strategy' },
]

const positions = ref([])
const showClosed = ref(false)

const statusFilter = computed(() => (showClosed.value ? 'closed' : 'open'))

const totalPnl = computed(() =>
  positions.value.reduce((sum, p) => sum + Number(p.pnl ?? 0), 0),
)

async function refresh() {
  const [result] = await Promise.allSettled([
    api.getPolymarketPositions(statusFilter.value),
  ])
  if (result.status === 'fulfilled') {
    positions.value = result.value.results ?? result.value
  }
}

function fmtPrice(val) {
  if (val == null) return '-'
  return Number(val).toFixed(2)
}

function fmtDate(val) {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

usePolling(refresh, 10000)
</script>

<template>
  <SectionNav :links="polyLinks" />
  <h2>Polymarket Positions</h2>
  <article>
    <header>Total P&amp;L</header>
    <p>
      <strong :style="{ color: totalPnl >= 0 ? 'var(--ins-color)' : 'var(--del-color)' }">
        ${{ totalPnl.toFixed(2) }}
      </strong>
    </p>
  </article>
  <p>
    <label>
      <input v-model="showClosed" type="checkbox" role="switch" />
      Show closed positions
    </label>
  </p>
  <figure>
    <table>
      <thead>
        <tr>
          <th>Market</th>
          <th>Side</th>
          <th>Entry Price</th>
          <th>Current Price</th>
          <th>Shares</th>
          <th>Cost</th>
          <th>P&amp;L</th>
          <th>Status</th>
          <th>Opened</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="positions.length === 0">
          <td colspan="9">No positions found.</td>
        </tr>
        <tr v-for="p in positions" :key="p.id">
          <td>{{ p.market_question ?? p.market ?? '-' }}</td>
          <td>
            <mark :class="p.side === 'YES' ? '' : 'secondary'">
              {{ p.side }}
            </mark>
          </td>
          <td>{{ fmtPrice(p.entry_price) }}</td>
          <td>{{ fmtPrice(p.current_price) }}</td>
          <td>{{ fmtPrice(p.shares) }}</td>
          <td>${{ fmtPrice(p.cost) }}</td>
          <td>
            <strong :style="{ color: Number(p.pnl ?? 0) >= 0 ? 'var(--ins-color)' : 'var(--del-color)' }">
              ${{ fmtPrice(p.pnl) }}
            </strong>
          </td>
          <td>
            <mark :class="p.status === 'open' ? '' : 'secondary'">
              {{ p.status }}
            </mark>
          </td>
          <td>{{ fmtDate(p.opened_at ?? p.created_at) }}</td>
        </tr>
      </tbody>
    </table>
  </figure>
</template>
