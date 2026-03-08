<script setup>
import { ref, computed } from 'vue'
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

const now = new Date()
const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
const fmtDate = (d) => d.toISOString().slice(0, 16)

const ticketNum = ref('')
const lookupType = ref('deal')
const ticketResult = ref(null)
const ticketError = ref('')

const fromDate = ref(fmtDate(weekAgo))
const toDate = ref(fmtDate(now))
const dealsPosition = ref('')
const deals = ref(null)
const dealsLoading = ref(false)
const dealsError = ref('')

const ordersTicket = ref('')
const orders = ref(null)
const ordersLoading = ref(false)
const ordersError = ref('')

const dealKeys = computed(() => deals.value?.length ? Object.keys(deals.value[0]) : [])
const orderKeys = computed(() => orders.value?.length ? Object.keys(orders.value[0]) : [])

// Active section tab
const activeSection = ref('ticket')

async function lookupTicket() {
  ticketError.value = ''
  try {
    const data = lookupType.value === 'deal'
      ? await api.getDealFromTicket(ticketNum.value)
      : await api.getOrderFromTicket(ticketNum.value)
    ticketResult.value = data
  } catch (err) {
    ticketError.value = err.message
    ticketResult.value = null
  }
}

async function searchDeals() {
  dealsLoading.value = true
  dealsError.value = ''
  try {
    const from = new Date(fromDate.value).toISOString()
    const to = new Date(toDate.value).toISOString()
    const result = await api.historyDealsGet(from, to, dealsPosition.value)
    deals.value = result && result.length ? result : null
    if (!deals.value) dealsError.value = 'No deals found'
  } catch (err) {
    dealsError.value = err.message
    deals.value = null
  }
  dealsLoading.value = false
}

async function searchOrders() {
  ordersLoading.value = true
  ordersError.value = ''
  try {
    const result = await api.historyOrdersGet(ordersTicket.value)
    orders.value = result && result.length ? result : null
    if (!orders.value) ordersError.value = 'No orders found'
  } catch (err) {
    ordersError.value = err.message
    orders.value = null
  }
  ordersLoading.value = false
}
</script>

<template>
  <SectionNav :links="forexLinks" />
  <div class="tp-page history-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <h1>Trade History</h1>
        <p>Manage and search your past trading activity across all markets.</p>
      </div>
    </div>

    <!-- Search Type Tabs -->
    <div class="tp-tabs">
      <button :class="{ active: activeSection === 'ticket' }" @click="activeSection = 'ticket'">
        <span class="material-symbols-outlined tab-icon">confirmation_number</span> Lookup by Ticket
      </button>
      <button :class="{ active: activeSection === 'deals' }" @click="activeSection = 'deals'">
        <span class="material-symbols-outlined tab-icon">swap_horiz</span> Deals History
      </button>
      <button :class="{ active: activeSection === 'orders' }" @click="activeSection = 'orders'">
        <span class="material-symbols-outlined tab-icon">receipt_long</span> Orders History
      </button>
    </div>

    <!-- Ticket Lookup Section -->
    <div v-if="activeSection === 'ticket'" class="section-card tp-card">
      <div class="card-inner">
        <h3 class="section-title">
          <span class="material-symbols-outlined" style="color:var(--tp-primary)">search</span>
          Lookup by Ticket
        </h3>
        <form class="search-form" @submit.prevent="lookupTicket">
          <div class="form-row">
            <div class="field">
              <label class="tp-label">Ticket Number</label>
              <input v-model="ticketNum" type="number" required placeholder="Order/Deal ticket" class="tp-input" />
            </div>
            <div class="field" style="max-width: 160px;">
              <label class="tp-label">Type</label>
              <select v-model="lookupType" class="tp-select">
                <option value="deal">Deal</option>
                <option value="order">Order</option>
              </select>
            </div>
            <div class="field field-btn">
              <button type="submit" class="tp-btn tp-btn-primary search-btn">
                <span class="material-symbols-outlined" style="font-size:18px">search</span>
                Lookup
              </button>
            </div>
          </div>
        </form>
        <!-- Result -->
        <div v-if="ticketResult" class="result-block">
          <pre class="result-pre">{{ JSON.stringify(ticketResult, null, 2) }}</pre>
        </div>
        <div v-if="ticketError" class="error-msg">
          <span class="material-symbols-outlined" style="font-size:16px">error</span>
          {{ ticketError }}
        </div>
      </div>
    </div>

    <!-- Deals History Section -->
    <div v-if="activeSection === 'deals'" class="section-card tp-card">
      <div class="card-inner">
        <h3 class="section-title">
          <span class="material-symbols-outlined" style="color:var(--tp-primary)">swap_horiz</span>
          Deals History (by Position)
        </h3>
        <form class="search-form" @submit.prevent="searchDeals">
          <div class="form-row">
            <div class="field">
              <label class="tp-label">From</label>
              <input v-model="fromDate" type="datetime-local" class="tp-input" />
            </div>
            <div class="field">
              <label class="tp-label">To</label>
              <input v-model="toDate" type="datetime-local" class="tp-input" />
            </div>
            <div class="field">
              <label class="tp-label">Position Ticket</label>
              <input v-model="dealsPosition" type="number" required placeholder="Position ticket" class="tp-input" />
            </div>
            <div class="field field-btn">
              <button type="submit" class="tp-btn tp-btn-primary search-btn">
                <span class="material-symbols-outlined" style="font-size:18px">search</span>
                Search
              </button>
            </div>
          </div>
        </form>

        <!-- Loading -->
        <div v-if="dealsLoading" class="loading-msg">
          <span class="material-symbols-outlined spinning">hourglass_empty</span> Searching...
        </div>
        <div v-else-if="dealsError" class="error-msg">
          <span class="material-symbols-outlined" style="font-size:16px">error</span>
          {{ dealsError }}
        </div>

        <!-- Deals Table -->
        <div v-else-if="deals" class="table-wrapper">
          <table class="tp-table">
            <thead>
              <tr>
                <th v-for="k in dealKeys" :key="k">{{ k }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(d, i) in deals" :key="i">
                <td v-for="k in dealKeys" :key="k">{{ d[k] ?? '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Orders History Section -->
    <div v-if="activeSection === 'orders'" class="section-card tp-card">
      <div class="card-inner">
        <h3 class="section-title">
          <span class="material-symbols-outlined" style="color:var(--tp-primary)">receipt_long</span>
          Orders History (by Ticket)
        </h3>
        <form class="search-form" @submit.prevent="searchOrders">
          <div class="form-row">
            <div class="field">
              <label class="tp-label">Order Ticket</label>
              <input v-model="ordersTicket" type="number" required placeholder="Order ticket" class="tp-input" />
            </div>
            <div class="field field-btn">
              <button type="submit" class="tp-btn tp-btn-primary search-btn">
                <span class="material-symbols-outlined" style="font-size:18px">search</span>
                Search
              </button>
            </div>
          </div>
        </form>

        <div v-if="ordersLoading" class="loading-msg">
          <span class="material-symbols-outlined spinning">hourglass_empty</span> Searching...
        </div>
        <div v-else-if="ordersError" class="error-msg">
          <span class="material-symbols-outlined" style="font-size:16px">error</span>
          {{ ordersError }}
        </div>

        <!-- Orders Table -->
        <div v-else-if="orders" class="table-wrapper">
          <table class="tp-table">
            <thead>
              <tr>
                <th v-for="k in orderKeys" :key="k">{{ k }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(o, i) in orders" :key="i">
                <td v-for="k in orderKeys" :key="k">{{ o[k] ?? '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-page {
  padding: 2rem 1rem;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 2rem;
}
.page-header h1 {
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin-bottom: 0.35rem;
}
.section-card {
  margin-bottom: 1.5rem;
}
.card-inner {
  padding: 1.5rem;
}
.section-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  font-weight: 700;
  margin-bottom: 1.25rem;
}
.search-form {
  margin-bottom: 1.25rem;
}
.form-row {
  display: flex;
  gap: 1rem;
  align-items: flex-end;
  flex-wrap: wrap;
}
.form-row .field {
  flex: 1;
  min-width: 140px;
}
.field-btn {
  max-width: 140px;
  padding-bottom: 0;
}
.search-btn {
  height: 2.75rem;
  width: 100%;
}
.table-wrapper {
  overflow-x: auto;
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius-sm);
}
.result-block {
  margin-top: 1rem;
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
.error-msg {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.75rem 1rem;
  background: rgba(239,68,68,0.05);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: var(--tp-radius-sm);
  color: var(--tp-danger);
  font-size: 0.85rem;
  margin-top: 0.75rem;
}
.loading-msg {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  color: var(--tp-text-muted);
  font-size: 0.9rem;
}
.tab-icon {
  font-size: 18px;
  margin-right: 0.25rem;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.spinning {
  animation: spin 1.5s linear infinite;
}
</style>
