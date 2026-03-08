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
  <div class="tp-page">
    <SectionNav :links="forexLinks" />
    
    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 2rem;">
      <div>
        <h1 style="font-size: 2.25rem; font-weight: 900; letter-spacing: -0.02em;">Active Positions</h1>
        <p style="color: var(--tp-text-muted); margin-top: 0.25rem;">Forex &amp; CFD Trading</p>
      </div>
      <div style="display: flex; gap: 0.75rem;">
        <button class="tp-btn tp-btn-outline" @click="refresh">
          <span class="material-symbols-outlined" style="font-size:18px">refresh</span>
          Refresh
        </button>
        <button class="tp-btn tp-btn-danger" @click="handleCloseAll">
          <span class="material-symbols-outlined" style="font-size:18px">close</span>
          Close All
        </button>
      </div>
    </div>

    <div class="tp-card" style="padding: 0;">
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
