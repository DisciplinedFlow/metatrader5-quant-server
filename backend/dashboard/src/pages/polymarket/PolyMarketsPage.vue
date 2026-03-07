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

const markets = ref([])
const showAll = ref(false)

const filtered = computed(() => {
  if (showAll.value) return markets.value
  return markets.value.filter((m) => m.status === 'active')
})

async function refresh() {
  const [result] = await Promise.allSettled([api.getPolymarketMarkets()])
  if (result.status === 'fulfilled') {
    markets.value = result.value.results ?? result.value
  }
}

function fmtPct(val) {
  if (val == null) return '-'
  return (Number(val) * 100).toFixed(1) + '%'
}

function fmtPrice(val) {
  if (val == null) return '-'
  return Number(val).toFixed(2)
}

function fmtDate(val) {
  if (!val) return '-'
  return new Date(val).toLocaleDateString()
}

function evColor(ev) {
  if (ev == null) return ''
  const pct = Number(ev) * 100
  if (pct > 5) return 'var(--ins-color)'
  if (pct < -5) return 'var(--del-color)'
  return ''
}

usePolling(refresh, 10000)
</script>

<template>
  <SectionNav :links="polyLinks" />
  <h2>Polymarket Markets</h2>
  <p>
    <label>
      <input v-model="showAll" type="checkbox" role="switch" />
      Show all markets
    </label>
  </p>
  <figure>
    <table>
      <thead>
        <tr>
          <th>Question</th>
          <th>Category</th>
          <th>Market Price</th>
          <th>Model Prob</th>
          <th>EV</th>
          <th>End Date</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="filtered.length === 0">
          <td colspan="7">No markets found.</td>
        </tr>
        <tr v-for="m in filtered" :key="m.id">
          <td>{{ m.question }}</td>
          <td>{{ m.category ?? '-' }}</td>
          <td>{{ fmtPrice(m.market_price) }}</td>
          <td>{{ fmtPct(m.model_probability) }}</td>
          <td>
            <mark
              v-if="m.expected_value != null"
              :style="{ background: evColor(m.expected_value), color: evColor(m.expected_value) ? '#fff' : '' }"
            >
              {{ fmtPct(m.expected_value) }}
            </mark>
            <template v-else>-</template>
          </td>
          <td>{{ fmtDate(m.end_date) }}</td>
          <td>
            <mark :class="m.status === 'active' ? '' : 'secondary'">
              {{ m.status }}
            </mark>
          </td>
        </tr>
      </tbody>
    </table>
  </figure>
</template>
