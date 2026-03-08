<script setup>
import { ref, computed } from 'vue'
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
  <div class="tp-page">
    <SectionNav :links="polyLinks" />
    
    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 2rem;">
      <div>
        <h1 style="font-size: 2.25rem; font-weight: 900; letter-spacing: -0.02em;">Polymarket Markets</h1>
        <p style="color: var(--tp-text-muted); margin-top: 0.25rem;">Trading Pro Platform</p>
      </div>
      <div>
        <label style="display: flex; align-items: center; gap: 0.5rem; color: var(--tp-text-muted); font-size: 0.9rem; margin-bottom: 0; cursor: pointer;">
          <input v-model="showAll" type="checkbox" role="switch" style="margin: 0;" />
          Show all markets
        </label>
      </div>
    </div>

    <div class="tp-card">
      <div style="overflow-x: auto;">
        <table class="tp-table">
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
              <td colspan="7" style="text-align: center; color: var(--tp-text-dim); padding: 2rem;">
                No markets found.
              </td>
            </tr>
            <tr v-for="m in filtered" :key="m.id">
              <td style="font-weight: 600;">{{ m.question }}</td>
              <td>
                <span v-if="m.category" class="tp-badge tp-badge-neutral">{{ m.category }}</span>
                <span v-else>-</span>
              </td>
              <td style="font-weight: 500;">${{ fmtPrice(m.market_price) }}</td>
              <td style="font-weight: 500;">{{ fmtPct(m.model_probability) }}</td>
              <td>
                <span
                  v-if="m.expected_value != null"
                  class="tp-badge"
                  :style="{ 
                    background: evColor(m.expected_value).includes('ins-color') ? 'rgba(34, 197, 94, 0.1)' : evColor(m.expected_value).includes('del-color') ? 'rgba(239, 68, 68, 0.1)' : 'rgba(100, 116, 139, 0.1)', 
                    color: evColor(m.expected_value).includes('ins-color') ? 'var(--tp-success)' : evColor(m.expected_value).includes('del-color') ? 'var(--tp-danger)' : 'var(--tp-text-dim)',
                    border: '1px solid transparent'
                  }"
                >
                  {{ fmtPct(m.expected_value) }}
                </span>
                <span v-else class="tp-badge tp-badge-neutral">-</span>
              </td>
              <td style="font-size: 0.75rem; color: var(--tp-text-dim);">{{ fmtDate(m.end_date) }}</td>
              <td>
                <span class="tp-badge" :class="m.status === 'active' ? 'tp-badge-success' : 'tp-badge-neutral'">
                  <span v-if="m.status === 'active'" class="pulse-dot"></span>
                  {{ m.status }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
