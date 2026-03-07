<script setup>
defineProps({
  positions: { type: Array, required: true },
  showActions: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'modify'])
</script>

<template>
  <p v-if="positions.length === 0">No open positions</p>
  <figure v-else>
    <table>
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
          <td>{{ p.symbol }}</td>
          <td>{{ p.type === 0 ? 'BUY' : 'SELL' }}</td>
          <td>{{ p.volume }}</td>
          <td>{{ p.price_open }}</td>
          <td>{{ p.price_current }}</td>
          <td>{{ p.sl || '-' }}</td>
          <td>{{ p.tp || '-' }}</td>
          <td v-if="showActions">{{ p.swap?.toFixed(2) || '0.00' }}</td>
          <td :class="p.profit >= 0 ? 'profit' : 'loss'">{{ p.profit?.toFixed(2) }}</td>
          <td v-if="showActions">
            <button class="outline" @click="emit('close', p)">Close</button>
            <button class="outline secondary" @click="emit('modify', p)">Modify</button>
          </td>
        </tr>
      </tbody>
    </table>
  </figure>
</template>
