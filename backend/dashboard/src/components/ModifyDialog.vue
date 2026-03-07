<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  ticket: { type: Number, default: 0 },
  currentSl: { type: [Number, String], default: '' },
  currentTp: { type: [Number, String], default: '' },
})

const emit = defineEmits(['update:show', 'submit'])

const dialogRef = ref(null)
const sl = ref('')
const tp = ref('')

watch(() => props.show, (val) => {
  if (val) {
    sl.value = props.currentSl || ''
    tp.value = props.currentTp || ''
    dialogRef.value?.showModal()
  } else {
    dialogRef.value?.close()
  }
})

function handleClose() {
  emit('update:show', false)
}

function handleSubmit() {
  emit('submit', {
    ticket: props.ticket,
    sl: sl.value ? parseFloat(sl.value) : undefined,
    tp: tp.value ? parseFloat(tp.value) : undefined,
  })
  emit('update:show', false)
}
</script>

<template>
  <dialog ref="dialogRef" @close="handleClose">
    <article>
      <header>Modify SL/TP</header>
      <form @submit.prevent="handleSubmit">
        <label>Stop Loss <input v-model="sl" type="number" step="any"></label>
        <label>Take Profit <input v-model="tp" type="number" step="any"></label>
        <footer>
          <button type="button" class="secondary" @click="handleClose">Cancel</button>
          <button type="submit">Apply</button>
        </footer>
      </form>
    </article>
  </dialog>
</template>
