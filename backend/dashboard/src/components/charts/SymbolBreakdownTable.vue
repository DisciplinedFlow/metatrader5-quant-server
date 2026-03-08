<script setup>
import { computed } from 'vue'

const props = defineProps({
  breakdown: { type: Object, default: () => ({}) },
})

const rows = computed(() => {
  return Object.entries(props.breakdown)
    .map(([symbol, stats]) => ({ symbol, ...stats }))
    .sort((a, b) => b.pnl - a.pnl)
})

const maxWinRate = computed(() => {
  if (!rows.value.length) return 1
  return Math.max(...rows.value.map(r => r.win_rate || 0), 0.01)
})
</script>

<template>
  <figure v-if="rows.length" style="overflow-x: auto;">
    <table role="grid" style="min-width: 500px;">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Trades</th>
          <th>Wins</th>
          <th>Losses</th>
          <th>Win Rate</th>
          <th>PnL</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.symbol">
          <td><strong>{{ r.symbol }}</strong></td>
          <td>{{ r.total }}</td>
          <td style="color: var(--tp-success);">{{ r.wins }}</td>
          <td style="color: var(--tp-danger);">{{ r.losses }}</td>
          <td>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <div
                style="height: 8px; border-radius: 4px; background: var(--tp-success);"
                :style="{ width: ((r.win_rate || 0) / maxWinRate * 100) + '%', minWidth: '4px' }"
              ></div>
              <span>{{ ((r.win_rate || 0) * 100).toFixed(1) }}%</span>
            </div>
          </td>
          <td :style="{ color: r.pnl >= 0 ? 'var(--tp-success)' : 'var(--tp-danger)' }">
            {{ (r.pnl * 100).toFixed(3) }}%
          </td>
        </tr>
      </tbody>
    </table>
  </figure>
  <p v-else class="secondary" style="text-align:center;">No symbol breakdown data available.</p>
</template>
