<script setup>
defineProps({
  positions: { type: Array, required: true },
  showActions: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'modify'])
</script>

<template>
  <div v-if="positions.length === 0" style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 4rem 2rem; text-align: center;">
    <div style="width: 4rem; height: 4rem; border-radius: 50%; background: var(--tp-bg-surface); display: flex; align-items: center; justify-content: center; margin-bottom: 1rem;">
      <span class="material-symbols-outlined" style="font-size: 2rem; color: var(--tp-text-dim);">inventory_2</span>
    </div>
    <p style="font-weight: 600; font-size: 1rem; color: var(--tp-text); margin-bottom: 0.25rem;">No open positions</p>
    <p style="font-size: 0.85rem; color: var(--tp-text-dim);">Your active trades will appear here once executed.</p>
  </div>
  <figure v-else style="margin: 0; overflow-x: auto;">
    <table class="tp-table">
      <thead>
        <tr>
          <th>Ticket</th>
          <th>Symbol</th>
          <th>Type</th>
          <th>Volume</th>
          <th>Open Price</th>
          <th>Current</th>
          <th>SL</th>
          <th>TP</th>
          <th v-if="showActions">Swap</th>
          <th>Profit</th>
          <th v-if="showActions">Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in positions" :key="p.ticket">
          <td>{{ p.ticket }}</td>
          <td><strong>{{ p.symbol }}</strong></td>
          <td>
            <span class="tp-badge" :class="p.type === 0 ? 'tp-badge-success' : 'tp-badge-danger'">
              {{ p.type === 0 ? 'BUY' : 'SELL' }}
            </span>
          </td>
          <td>{{ p.volume }}</td>
          <td>{{ p.price_open }}</td>
          <td>{{ p.price_current }}</td>
          <td style="color: var(--tp-text-dim);">{{ p.sl || '-' }}</td>
          <td style="color: var(--tp-text-dim);">{{ p.tp || '-' }}</td>
          <td v-if="showActions" style="color: var(--tp-text-dim);">{{ p.swap?.toFixed(2) || '0.00' }}</td>
          <td :class="p.profit >= 0 ? 'profit' : 'loss'">
            {{ p.profit >= 0 ? '+' : '' }}{{ p.profit?.toFixed(2) }}
          </td>
          <td v-if="showActions" style="display: flex; gap: 0.5rem;">
            <button class="tp-btn tp-btn-danger" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;" @click="emit('close', p)">Close</button>
            <button class="tp-btn tp-btn-outline" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;" @click="emit('modify', p)">Modify</button>
          </td>
        </tr>
      </tbody>
    </table>
  </figure>
</template>
