<script setup>
import { ref, computed } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'

const cryptoLinks = [
  { to: '/crypto', label: 'Dashboard' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/strategy', label: 'Strategy' },
]

const positions = ref([])
const showClosed = ref(false)

const statusFilter = computed(() => (showClosed.value ? 'closed' : 'open'))

const totalPnl = computed(() =>
  positions.value.reduce((sum, p) => sum + Number(p.pnl_usd ?? 0), 0),
)

async function refresh() {
  const [result] = await Promise.allSettled([
    api.getCryptoPositions(statusFilter.value),
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
  <SectionNav :links="cryptoLinks" />
  <h2>Crypto Positions</h2>
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
          <th>Symbol</th>
          <th>Side</th>
          <th>Entry Price</th>
          <th>Close Price</th>
          <th>Size</th>
          <th>Leverage</th>
          <th>P&amp;L</th>
          <th>Status</th>
          <th>Reason</th>
          <th>Opened</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="positions.length === 0">
          <td colspan="10">No positions found.</td>
        </tr>
        <tr v-for="p in positions" :key="p.id">
          <td>{{ p.symbol }}</td>
          <td>
            <mark :class="p.side === 'LONG' ? '' : 'secondary'">{{ p.side }}</mark>
          </td>
          <td>${{ fmtPrice(p.entry_price) }}</td>
          <td>{{ p.close_price ? '$' + fmtPrice(p.close_price) : '-' }}</td>
          <td>{{ fmtPrice(p.size) }}</td>
          <td>{{ p.leverage }}x</td>
          <td>
            <strong :style="{ color: Number(p.pnl_usd ?? 0) >= 0 ? 'var(--ins-color)' : 'var(--del-color)' }">
              ${{ fmtPrice(p.pnl_usd) }}
            </strong>
          </td>
          <td>
            <mark :class="p.status === 'OPEN' ? '' : 'secondary'">{{ p.status }}</mark>
          </td>
          <td>{{ p.close_reason ?? '-' }}</td>
          <td>{{ fmtDate(p.opened_at) }}</td>
        </tr>
      </tbody>
    </table>
  </figure>
</template>
