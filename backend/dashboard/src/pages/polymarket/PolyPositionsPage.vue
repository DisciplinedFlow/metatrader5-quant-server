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
  <div class="tp-page">
    <SectionNav :links="polyLinks" />
    
    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 2rem;">
      <div>
        <h1 style="font-size: 2.25rem; font-weight: 900; letter-spacing: -0.02em;">Polymarket Positions</h1>
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
              <td colspan="9" style="text-align: center; color: var(--tp-text-dim); padding: 2rem;">
                No positions found.
              </td>
            </tr>
            <tr v-for="p in positions" :key="p.id">
              <td style="font-weight: 600;">{{ p.market_question ?? p.market ?? '-' }}</td>
              <td>
                <span class="tp-badge" :class="p.side === 'YES' ? 'tp-badge-success' : 'tp-badge-danger'">
                  {{ p.side }}
                </span>
              </td>
              <td style="font-weight: 500;">${{ fmtPrice(p.entry_price) }}</td>
              <td style="font-weight: 500;">${{ fmtPrice(p.current_price) }}</td>
              <td style="font-weight: 500;">{{ fmtPrice(p.shares) }}</td>
              <td style="font-weight: 500;">${{ fmtPrice(p.cost) }}</td>
              <td>
                <div style="display: flex; flex-direction: column;">
                  <span style="font-weight: 700;" :style="{ color: Number(p.pnl ?? 0) >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
                    {{ Number(p.pnl ?? 0) >= 0 ? '+' : '' }}${{ fmtPrice(p.pnl) }}
                  </span>
                </div>
              </td>
              <td>
                <span class="tp-badge" :class="p.status === 'open' ? 'tp-badge-success' : 'tp-badge-neutral'">
                  <span v-if="p.status === 'open'" class="pulse-dot"></span>
                  {{ p.status }}
                </span>
              </td>
              <td style="font-size: 0.75rem; color: var(--tp-text-dim);">{{ fmtDate(p.opened_at ?? p.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
