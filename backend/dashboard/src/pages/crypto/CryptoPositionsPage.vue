<script setup>
import { ref, computed } from 'vue'
import { usePolling } from '@/composables/usePolling'
import api from '@/services/api'
import SectionNav from '@/components/SectionNav.vue'

const cryptoLinks = [
  { to: '/crypto', label: 'Dashboard' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/logs', label: 'Logs' },
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
  <div class="tp-page">
    <SectionNav :links="cryptoLinks" />
    
    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 2rem;">
      <div>
        <h1 style="font-size: 2.25rem; font-weight: 900; letter-spacing: -0.02em;">Crypto Positions</h1>
        <p style="color: var(--tp-text-muted); margin-top: 0.25rem;">Trading Pro Platform</p>
      </div>
      <div>
        <label style="display: flex; align-items: center; gap: 0.5rem; color: var(--tp-text-muted); font-size: 0.9rem; margin-bottom: 0; cursor: pointer;">
          <input v-model="showClosed" type="checkbox" role="switch" style="margin: 0;" />
          Show closed positions
        </label>
      </div>
    </div>

    <div class="tp-stats-grid" style="margin-bottom: 2rem; grid-template-columns: repeat(auto-fit, minmax(200px, 300px));">
      <div class="tp-stat-card">
        <div class="stat-label">Total P&amp;L</div>
        <div class="stat-value" :style="{ color: totalPnl >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
          {{ totalPnl >= 0 ? '+' : '' }}${{ totalPnl.toFixed(2) }}
        </div>
      </div>
    </div>

    <div class="tp-card">
      <div style="overflow-x: auto;">
        <table class="tp-table">
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
              <td colspan="10" style="text-align: center; color: var(--tp-text-dim); padding: 2rem;">
                No positions found.
              </td>
            </tr>
            <tr v-for="p in positions" :key="p.id">
              <td style="font-weight: 600;">{{ p.symbol }}</td>
              <td>
                <span class="tp-badge" :class="p.side === 'LONG' ? 'tp-badge-success' : 'tp-badge-danger'">
                  {{ p.side }}
                </span>
              </td>
              <td style="font-weight: 500;">${{ fmtPrice(p.entry_price) }}</td>
              <td style="font-weight: 500;">{{ p.close_price ? '$' + fmtPrice(p.close_price) : '-' }}</td>
              <td style="font-weight: 500;">{{ fmtPrice(p.size) }}</td>
              <td>{{ p.leverage }}x</td>
              <td>
                <span style="font-weight: 700;" :style="{ color: Number(p.pnl_usd ?? 0) >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
                  {{ Number(p.pnl_usd ?? 0) >= 0 ? '+' : '' }}${{ fmtPrice(p.pnl_usd) }}
                </span>
              </td>
              <td>
                <span class="tp-badge" :class="p.status === 'OPEN' ? 'tp-badge-success' : 'tp-badge-neutral'">
                  <span v-if="p.status === 'OPEN'" class="pulse-dot"></span>
                  {{ p.status }}
                </span>
              </td>
              <td>{{ p.close_reason ?? '-' }}</td>
              <td style="font-size: 0.75rem; color: var(--tp-text-dim);">{{ fmtDate(p.opened_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
