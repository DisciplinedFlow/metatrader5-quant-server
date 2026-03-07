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
  <h2>Trade History</h2>

  <article>
    <header>Lookup by Ticket</header>
    <form class="grid" style="align-items:end;" @submit.prevent="lookupTicket">
      <label>
        Ticket
        <input v-model="ticketNum" type="number" required placeholder="Order/Deal ticket">
      </label>
      <label>
        Type
        <select v-model="lookupType">
          <option value="deal">Deal</option>
          <option value="order">Order</option>
        </select>
      </label>
      <button type="submit">Lookup</button>
    </form>
    <pre v-if="ticketResult">{{ JSON.stringify(ticketResult, null, 2) }}</pre>
    <p v-if="ticketError">Error: {{ ticketError }}</p>
  </article>

  <article>
    <header>Deals History (by Position)</header>
    <form class="grid" style="align-items:end;" @submit.prevent="searchDeals">
      <label>
        From
        <input v-model="fromDate" type="datetime-local">
      </label>
      <label>
        To
        <input v-model="toDate" type="datetime-local">
      </label>
      <label>
        Position
        <input v-model="dealsPosition" type="number" required placeholder="Position ticket">
      </label>
      <button type="submit">Search</button>
    </form>
    <p v-if="dealsLoading" aria-busy="true">Searching...</p>
    <p v-else-if="dealsError">{{ dealsError }}</p>
    <figure v-else-if="deals">
      <table>
        <thead><tr><th v-for="k in dealKeys" :key="k">{{ k }}</th></tr></thead>
        <tbody>
          <tr v-for="(d, i) in deals" :key="i">
            <td v-for="k in dealKeys" :key="k">{{ d[k] ?? '' }}</td>
          </tr>
        </tbody>
      </table>
    </figure>
  </article>

  <article>
    <header>Orders History (by Ticket)</header>
    <form class="grid" style="align-items:end;" @submit.prevent="searchOrders">
      <label>
        Ticket
        <input v-model="ordersTicket" type="number" required placeholder="Order ticket">
      </label>
      <button type="submit">Search</button>
    </form>
    <p v-if="ordersLoading" aria-busy="true">Searching...</p>
    <p v-else-if="ordersError">{{ ordersError }}</p>
    <figure v-else-if="orders">
      <table>
        <thead><tr><th v-for="k in orderKeys" :key="k">{{ k }}</th></tr></thead>
        <tbody>
          <tr v-for="(o, i) in orders" :key="i">
            <td v-for="k in orderKeys" :key="k">{{ o[k] ?? '' }}</td>
          </tr>
        </tbody>
      </table>
    </figure>
  </article>
</template>
