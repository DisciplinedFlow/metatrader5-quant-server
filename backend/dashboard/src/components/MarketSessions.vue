<script setup>
import { ref, onBeforeUnmount } from 'vue'

const SESSIONS = [
  { name: 'Sydney',   openUTC: 22, closeUTC: 7,  color: '#42a5f5', assets: 'AUD, NZD pairs' },
  { name: 'Tokyo',    openUTC: 0,  closeUTC: 9,  color: '#ab47bc', assets: 'JPY pairs' },
  { name: 'London',   openUTC: 8,  closeUTC: 17, color: '#26a69a', assets: 'EUR, GBP, CHF pairs' },
  { name: 'New York', openUTC: 13, closeUTC: 22, color: '#ef5350', assets: 'USD, CAD pairs' },
  { name: 'COMEX',    openUTC: 23, closeUTC: 22, color: '#ffa726', assets: 'XAUUSD, XAGUSD, XAUEUR', nearly24h: true, breakStartUTC: 22, breakEndUTC: 23 },
  { name: 'NYMEX',    openUTC: 23, closeUTC: 22, color: '#8d6e63', assets: 'NG, WTI, BRN', nearly24h: true, breakStartUTC: 22, breakEndUTC: 23 },
]

const HOURS = [0, 3, 6, 9, 12, 15, 18, 21, 24]

const now = ref(new Date())
const timer = setInterval(() => { now.value = new Date() }, 1000)
onBeforeUnmount(() => clearInterval(timer))

function isSessionOpen(session) {
  const h = now.value.getUTCHours()
  const m = now.value.getUTCMinutes()
  const t = h + m / 60
  const day = now.value.getUTCDay()

  if (!session.nearly24h && (day === 6 || (day === 0 && t < 22))) return false
  if (session.nearly24h && (day === 6 || (day === 0 && t < 23))) return false

  if (session.nearly24h) {
    if (day === 5 && t >= 22) return false
    if (t >= session.breakStartUTC && t < session.breakEndUTC) return false
    return true
  }

  if (session.openUTC < session.closeUTC) return t >= session.openUTC && t < session.closeUTC
  return t >= session.openUTC || t < session.closeUTC
}

function barStyle(session) {
  let left, width
  if (session.nearly24h) {
    left = 0; width = 100
  } else if (session.openUTC < session.closeUTC) {
    left = (session.openUTC / 24) * 100
    width = ((session.closeUTC - session.openUTC) / 24) * 100
  } else {
    left = (session.openUTC / 24) * 100
    width = ((24 - session.openUTC + session.closeUTC) / 24) * 100
  }
  const open = isSessionOpen(session)
  return { left: `${left}%`, width: `${width}%`, background: session.color, opacity: open ? 0.9 : 0.25 }
}

function nowPosition() {
  return (now.value.getUTCHours() + now.value.getUTCMinutes() / 60) / 24 * 100
}

function formatUTC(hour) {
  return `${String(hour).padStart(2, '0')}:00`
}

function getLocalTime(utcHour) {
  const d = new Date()
  d.setUTCHours(utcHour, 0, 0, 0)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function timeLabel(s) {
  return s.nearly24h ? '23:00 - 22:00 UTC (1h break)' : `${formatUTC(s.openUTC)} - ${formatUTC(s.closeUTC)} UTC`
}

function localLabel(s) {
  return s.nearly24h
    ? `${getLocalTime(23)} - ${getLocalTime(22)} local`
    : `${getLocalTime(s.openUTC)} - ${getLocalTime(s.closeUTC)} local`
}

const utcStr = ref('')
setInterval(() => {
  utcStr.value = now.value.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' })
}, 1000)
utcStr.value = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' })
</script>

<template>
  <article>
    <header>Market Sessions <small style="float:right;">UTC: {{ utcStr }}</small></header>
    <div class="sessions-container">
      <div class="timeline-hours">
        <span v-for="h in HOURS" :key="h" :style="{ left: `${(h / 24) * 100}%` }">
          {{ String(h).padStart(2, '0') }}
        </span>
      </div>
      <div v-for="s in SESSIONS" :key="s.name" class="session-row">
        <div class="session-label">
          <span :style="{ color: isSessionOpen(s) ? '#26a69a' : '#555', fontSize: '1.1em' }">&#9679;</span>
          <strong :style="{ color: s.color }">{{ s.name }}</strong>
          <span class="session-status">{{ isSessionOpen(s) ? 'OPEN' : 'CLOSED' }}</span>
        </div>
        <div class="session-timeline">
          <div class="session-bar" :style="barStyle(s)"></div>
          <div class="session-now" :style="{ left: `${nowPosition()}%` }"></div>
        </div>
        <div class="session-meta">
          <small>{{ timeLabel(s) }}</small>
          <small class="session-local">{{ localLabel(s) }}</small>
          <small class="session-assets">{{ s.assets }}</small>
        </div>
      </div>
    </div>
  </article>
</template>
