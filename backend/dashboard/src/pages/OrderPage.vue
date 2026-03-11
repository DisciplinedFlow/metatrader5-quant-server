<script setup>
import { reactive, ref, watch } from 'vue'
import { useToast } from '@/composables/useToast'
import SymbolSelect from '@/components/SymbolSelect.vue'
import SectionNav from '@/components/SectionNav.vue'
import api from '@/services/api'

const forexLinks = [
  { to: '/forex', label: 'Overview' },
  { to: '/forex/positions', label: 'Positions' },
  { to: '/forex/order', label: 'Order' },
  { to: '/forex/history', label: 'History' },
  { to: '/forex/chart', label: 'Chart' },
  { to: '/forex/logs', label: 'Logs' },
  { to: '/forex/strategy', label: 'Strategies' },
]

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
  <SectionNav :links="forexLinks" />
  <div class="tp-page order-page">
    <div class="order-wrapper">
      <!-- Order Card -->
      <div class="tp-card order-card">
        <!-- Header -->
        <div class="order-header">
          <h1>Place Order</h1>
          <p class="order-subtitle">{{ form.symbol }} Market Order</p>
        </div>

        <form @submit.prevent="handleSubmit">
          <!-- Buy / Sell Toggle -->
          <div class="side-toggle">
            <button type="button" class="side-btn side-buy" :class="{ active: form.type === 'BUY' }" @click="form.type = 'BUY'">
              Buy
            </button>
            <button type="button" class="side-btn side-sell" :class="{ active: form.type === 'SELL' }" @click="form.type = 'SELL'">
              Sell
            </button>
          </div>

          <!-- Symbol -->
          <div class="field">
            <label class="tp-label">Symbol</label>
            <SymbolSelect v-model="form.symbol" class="tp-select" />
          </div>

          <!-- Volume & Deviation -->
          <div class="field-row">
            <div class="field">
              <label class="tp-label">Volume (lots)</label>
              <div class="tp-input-group">
                <input v-model.number="form.volume" type="number" min="0.01" step="0.01" class="tp-input" required />
                <span class="suffix">lots</span>
              </div>
            </div>
            <div class="field">
              <label class="tp-label">Deviation (pts)</label>
              <input v-model.number="form.deviation" type="number" min="0" class="tp-input" />
            </div>
          </div>

          <!-- SL & TP -->
          <div class="field-row">
            <div class="field">
              <label class="tp-label">Stop Loss (price)</label>
              <input v-model="form.sl" type="number" step="any" placeholder="Optional" class="tp-input" />
            </div>
            <div class="field">
              <label class="tp-label">Take Profit (price)</label>
              <input v-model="form.tp" type="number" step="any" placeholder="Optional" class="tp-input" />
            </div>
          </div>

          <!-- Magic & Comment -->
          <div class="field-row">
            <div class="field">
              <label class="tp-label">Magic Number</label>
              <input v-model.number="form.magic" type="number" min="0" class="tp-input" />
            </div>
            <div class="field">
              <label class="tp-label">Comment</label>
              <input v-model="form.comment" type="text" placeholder="Optional" class="tp-input" />
            </div>
          </div>

          <!-- Tick Preview -->
          <div v-if="tickPreview" class="tick-bar">
            <span class="material-symbols-outlined" style="font-size:16px;color:var(--tp-primary)">info</span>
            <span>
              Bid: <strong>{{ tickPreview.bid }}</strong> &nbsp;|&nbsp;
              Ask: <strong>{{ tickPreview.ask }}</strong> &nbsp;|&nbsp;
              Spread: <strong>{{ ((tickPreview.ask - tickPreview.bid) * 100000).toFixed(1) }} pts</strong>
            </span>
          </div>

          <!-- Action Buttons -->
          <div class="action-row">
            <button
              type="submit"
              class="tp-btn action-btn"
              :class="form.type === 'BUY' ? 'tp-btn-success' : 'tp-btn-danger'"
              :aria-busy="submitting"
              :disabled="submitting"
            >
              <span class="material-symbols-outlined" style="font-size:18px">
                {{ form.type === 'BUY' ? 'trending_up' : 'trending_down' }}
              </span>
              {{ form.type === 'BUY' ? 'Buy / Long' : 'Sell / Short' }}
            </button>
          </div>
        </form>
      </div>

      <!-- Order Result -->
      <div v-if="orderResult" class="tp-card result-card">
        <div class="result-header">
          <span class="material-symbols-outlined" style="color:var(--tp-success)">check_circle</span>
          <h3>Order Result</h3>
        </div>
        <pre class="result-pre">{{ JSON.stringify(orderResult, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.order-page {
  display: flex;
  justify-content: center;
  padding: 1.5rem 1rem;
}
.order-wrapper {
  width: 100%;
  max-width: 460px;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.order-card {
  padding: 1.5rem;
}
.order-header {
  margin-bottom: 1rem;
}
.order-header h1 {
  font-size: 1.25rem;
  font-weight: 800;
  margin-bottom: 0.15rem;
}
.order-subtitle {
  font-size: 0.8rem;
}

/* Side toggle — compact segmented control */
.side-toggle {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.side-btn {
  flex: 1;
  padding: 0.4rem 0;
  font-family: var(--tp-font);
  font-size: 0.8rem;
  font-weight: 700;
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  background: transparent;
  color: var(--tp-text-dim);
  cursor: pointer;
  transition: all 0.15s ease;
}
.side-buy.active {
  background: rgba(34, 197, 94, 0.12);
  border-color: var(--tp-success);
  color: var(--tp-success);
}
.side-sell.active {
  background: rgba(239, 68, 68, 0.12);
  border-color: var(--tp-danger);
  color: var(--tp-danger);
}
.side-btn:hover:not(.active) {
  background: var(--tp-bg-hover);
  color: var(--tp-text);
}

/* Compact inputs */
.order-card :deep(.tp-input),
.order-card :deep(.tp-select) {
  height: 2.25rem;
  font-size: 0.85rem;
}

.field {
  margin-bottom: 0.75rem;
  flex: 1;
}
.field-row {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 0;
}
.tick-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: rgba(13,127,242,0.05);
  border: 1px solid rgba(13,127,242,0.2);
  border-radius: var(--tp-radius-sm);
  font-size: 0.78rem;
  color: var(--tp-text-muted);
  margin-bottom: 1rem;
}
.tick-bar strong {
  color: var(--tp-text);
}
.action-row {
  display: flex;
  gap: 0.75rem;
}
.action-btn {
  flex: 1;
  height: 2.5rem;
  font-size: 0.88rem;
  border-radius: var(--tp-radius-sm);
}
.result-card {
  padding: 1.25rem;
}
.result-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.result-header h3 {
  font-size: 1rem;
  font-weight: 700;
}
.result-pre {
  background: var(--tp-bg-surface);
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
  padding: 1rem;
  font-size: 0.8rem;
  color: var(--tp-text-muted);
  overflow-x: auto;
  margin: 0;
}
</style>
