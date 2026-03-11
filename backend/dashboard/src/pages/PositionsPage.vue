<script setup>
import { ref } from 'vue'
import { usePositionsStore } from '@/stores/positions'
import { usePolling } from '@/composables/usePolling'
import { useToast } from '@/composables/useToast'
import PositionsTable from '@/components/PositionsTable.vue'
import ModifyDialog from '@/components/ModifyDialog.vue'
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

const positionsStore = usePositionsStore()
const toast = useToast()

const showModify = ref(false)
const modifyTicket = ref(0)
const modifySl = ref('')
const modifyTp = ref('')

async function refresh() {
  try {
    await positionsStore.fetchPositions()
  } catch (err) {
    console.error('Positions refresh error:', err)
  }
}

usePolling(refresh, 5000)

async function handleClose(position) {
  if (!confirm('Close this position?')) return
  try {
    await api.closePosition({
      ticket: position.ticket,
      type: position.type,
      symbol: position.symbol,
      volume: position.volume,
    })
    toast.success('Position closed')
    await positionsStore.fetchPositions()
  } catch (err) {
    toast.error(`Close failed: ${err.message}`)
  }
}

async function handleCloseAll() {
  if (!confirm('Close ALL positions?')) return
  try {
    await api.closeAllPositions()
    toast.success('All positions closed')
    await positionsStore.fetchPositions()
  } catch (err) {
    toast.error(`Close all failed: ${err.message}`)
  }
}

function handleModify(position) {
  modifyTicket.value = position.ticket
  modifySl.value = position.sl || ''
  modifyTp.value = position.tp || ''
  showModify.value = true
}

async function handleModifySubmit({ ticket, sl, tp }) {
  try {
    await api.modifySlTp(ticket, sl, tp)
    toast.success('SL/TP modified')
    await positionsStore.fetchPositions()
  } catch (err) {
    toast.error(`Modify failed: ${err.message}`)
  }
}
</script>

<template>
  <SectionNav :links="forexLinks" />
  <div class="tp-page positions-page">
    <div class="page-header">
      <div>
        <h1>Active Positions</h1>
        <p class="page-subtitle">Forex & CFD Trading</p>
      </div>
      <div class="header-actions">
        <button class="tp-btn tp-btn-outline" @click="refresh">
          <span class="material-symbols-outlined" style="font-size:16px">refresh</span>
          Refresh
        </button>
        <button class="tp-btn tp-btn-danger" @click="handleCloseAll">
          <span class="material-symbols-outlined" style="font-size:16px">close</span>
          Close All
        </button>
      </div>
    </div>

    <div class="tp-card positions-card">
      <PositionsTable
        :positions="positionsStore.positions"
        :show-actions="true"
        @close="handleClose"
        @modify="handleModify"
      />
    </div>

    <ModifyDialog
      v-model:show="showModify"
      :ticket="modifyTicket"
      :current-sl="modifySl"
      :current-tp="modifyTp"
      @submit="handleModifySubmit"
    />
  </div>
</template>

<style scoped>
.positions-page {
  padding: 1.5rem 1.5rem 2rem;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.25rem;
}
.page-header h1 {
  font-size: 1.25rem;
  font-weight: 800;
  letter-spacing: -0.02em;
}
.page-subtitle {
  font-size: 0.8rem;
  color: var(--tp-text-dim);
  margin-top: 0.15rem;
}
.header-actions {
  display: flex;
  gap: 0.5rem;
}
.positions-card {
  padding: 0;
  overflow: hidden;
}
</style>
