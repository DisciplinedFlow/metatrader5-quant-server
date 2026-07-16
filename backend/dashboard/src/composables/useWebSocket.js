/**
 * WebSocket composable for real-time dashboard updates.
 *
 * Connects to the standalone WebSocket relay server (port 8001).
 * Falls back gracefully — existing HTTP polling continues to work
 * even if the WS connection is unavailable.
 *
 * Usage:
 *   const { connected, on, off } = useWebSocket()
 *   on('trade_opened', (data) => { ... })
 *   on('trade_closed', (data) => { ... })
 *   on('position_update', (data) => { ... })
 *   on('bot_status', (data) => { ... })
 *   on('news_alert', (data) => { ... })
 */
import { ref, onMounted, onUnmounted } from 'vue'

// Resolve WS URL: use same hostname as the page, port 8001
const WS_PORT = 8001
const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss' : 'ws'
const WS_URL = `${WS_PROTOCOL}://${window.location.hostname}:${WS_PORT}`

// Reconnect settings
const RECONNECT_BASE_MS = 2000
const RECONNECT_MAX_MS = 30000

export function useWebSocket() {
  const connected = ref(false)
  const lastMessage = ref(null)
  const listeners = new Map()
  let ws = null
  let reconnectTimer = null
  let reconnectAttempts = 0
  let destroyed = false

  /**
   * Compute backoff delay with jitter.
   */
  function _backoff() {
    const delay = Math.min(
      RECONNECT_BASE_MS * Math.pow(1.5, reconnectAttempts),
      RECONNECT_MAX_MS
    )
    // Add 0-500ms jitter to avoid thundering herd
    return delay + Math.random() * 500
  }

  /**
   * Establish the WebSocket connection.
   */
  function connect() {
    if (destroyed) return

    try {
      ws = new WebSocket(WS_URL)

      ws.onopen = () => {
        connected.value = true
        reconnectAttempts = 0
        console.log('[WS] Connected to', WS_URL)
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          lastMessage.value = msg

          // Dispatch to event-specific listeners
          const eventName = msg.event
          if (eventName && listeners.has(eventName)) {
            listeners.get(eventName).forEach((cb) => {
              try {
                cb(msg.data)
              } catch (e) {
                console.warn(`[WS] Listener error for '${eventName}':`, e)
              }
            })
          }

          // Also dispatch to wildcard '*' listeners
          if (listeners.has('*')) {
            listeners.get('*').forEach((cb) => {
              try {
                cb(msg)
              } catch (e) {
                console.warn('[WS] Wildcard listener error:', e)
              }
            })
          }
        } catch (e) {
          console.warn('[WS] Failed to parse message:', e)
        }
      }

      ws.onclose = () => {
        connected.value = false
        if (!destroyed) {
          const delay = _backoff()
          reconnectAttempts++
          console.log(`[WS] Disconnected. Reconnecting in ${Math.round(delay)}ms (attempt ${reconnectAttempts})`)
          reconnectTimer = setTimeout(connect, delay)
        }
      }

      ws.onerror = (err) => {
        // onclose will fire after onerror, handling reconnect
        console.warn('[WS] Connection error:', err)
      }
    } catch (e) {
      console.warn('[WS] Failed to create WebSocket:', e)
      if (!destroyed) {
        const delay = _backoff()
        reconnectAttempts++
        reconnectTimer = setTimeout(connect, delay)
      }
    }
  }

  /**
   * Register a callback for a specific event type.
   * Use '*' to listen to all events (receives the full message object).
   */
  function on(event, callback) {
    if (!listeners.has(event)) {
      listeners.set(event, [])
    }
    listeners.get(event).push(callback)
  }

  /**
   * Unregister a callback for a specific event type.
   */
  function off(event, callback) {
    const cbs = listeners.get(event)
    if (cbs) {
      const idx = cbs.indexOf(callback)
      if (idx >= 0) cbs.splice(idx, 1)
    }
  }

  onMounted(() => {
    connect()
  })

  onUnmounted(() => {
    destroyed = true
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (ws) {
      ws.onclose = null  // Prevent reconnect on intentional close
      ws.close()
    }
  })

  return { connected, lastMessage, on, off }
}
