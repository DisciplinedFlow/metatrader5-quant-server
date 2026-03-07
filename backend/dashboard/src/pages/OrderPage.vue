<script setup>
import { reactive, ref, watch } from 'vue'
import { useToast } from '@/composables/useToast'
import SymbolSelect from '@/components/SymbolSelect.vue'
import api from '@/services/api'

const toast = useToast()

const form = reactive({
  symbol: 'EURUSD',
  volume: 0.01,
  type: 'BUY',
  deviation: 20,
  sl: '',
  tp: '',
  magic: 0,
  comment: '',
})

const tickPreview = ref(null)
const orderResult = ref(null)
const submitting = ref(false)

async function updateTick() {
  if (!form.symbol) return
  try {
    tickPreview.value = await api.symbolInfoTick(form.symbol)
  } catch {
    tickPreview.value = null
  }
}

watch(() => form.symbol, updateTick, { immediate: true })

async function handleSubmit() {
  submitting.value = true
  const orderData = {
    symbol: form.symbol.trim(),
    volume: parseFloat(form.volume),
    type: form.type,
    deviation: parseInt(form.deviation),
    magic: parseInt(form.magic),
    comment: form.comment,
  }
  if (form.sl) orderData.sl = parseFloat(form.sl)
  if (form.tp) orderData.tp = parseFloat(form.tp)

  try {
    const result = await api.sendOrder(orderData)
    toast.success('Order executed successfully')
    orderResult.value = result
  } catch (err) {
    toast.error(`Order failed: ${err.message}`)
  }
  submitting.value = false
}
</script>

<template>
  <h2>Place Market Order</h2>
  <article>
    <form @submit.prevent="handleSubmit">
      <div class="grid">
        <label>
          Symbol
          <SymbolSelect v-model="form.symbol" />
        </label>
        <label>
          Volume (lots)
          <input v-model.number="form.volume" type="number" min="0.01" step="0.01" required>
        </label>
      </div>
      <div class="grid">
        <label>
          Order Type
          <select v-model="form.type" required>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </label>
        <label>
          Deviation (pts)
          <input v-model.number="form.deviation" type="number" min="0">
        </label>
      </div>
      <div class="grid">
        <label>
          Stop Loss (price)
          <input v-model="form.sl" type="number" step="any" placeholder="Optional">
        </label>
        <label>
          Take Profit (price)
          <input v-model="form.tp" type="number" step="any" placeholder="Optional">
        </label>
      </div>
      <div class="grid">
        <label>
          Magic Number
          <input v-model.number="form.magic" type="number" min="0">
        </label>
        <label>
          Comment
          <input v-model="form.comment" type="text" placeholder="Optional">
        </label>
      </div>
      <div v-if="tickPreview">
        <small>
          Bid: <strong>{{ tickPreview.bid }}</strong> |
          Ask: <strong>{{ tickPreview.ask }}</strong> |
          Spread: {{ ((tickPreview.ask - tickPreview.bid) * 100000).toFixed(1) }} pts
        </small>
      </div>
      <button type="submit" :aria-busy="submitting" :disabled="submitting">Send Order</button>
    </form>
  </article>

  <article v-if="orderResult">
    <header>Order Result</header>
    <pre>{{ JSON.stringify(orderResult, null, 2) }}</pre>
  </article>
</template>
