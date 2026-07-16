// Shared constants and utilities for crypto dashboard pages

export const cryptoLinks = [
  { to: '/crypto', label: 'Overview' },
  { to: '/crypto/positions', label: 'Positions' },
  { to: '/crypto/history', label: 'History' },
  { to: '/crypto/chart', label: 'Chart' },
  { to: '/crypto/logs', label: 'Logs' },
  { to: '/crypto/strategy', label: 'Strategies' },
]

export const COIN_COLORS = {
  BTC: '#f7931a', ETH: '#627eea', SOL: '#9945ff', AVAX: '#e84142',
  DOGE: '#c2a633', ARB: '#28a0f0', MATIC: '#8247e5', LINK: '#2a5ada',
  OP: '#ff0420', SUI: '#4da2ff', XAU: '#d4af37', XAG: '#c0c0c0', WTI: '#8b5e3c',
}

export function fmt(val, decimals = 2) {
  if (val == null) return '-'
  return Number(val).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function fmtPrice(val) {
  if (val == null) return '-'
  const n = Number(val)
  if (n >= 1000) return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (n >= 1) return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
  return n.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 6 })
}

export function fmtTime(val) {
  if (!val) return '-'
  const d = new Date(val)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) + ' ' +
    d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

export function duration(open, close) {
  if (!open || !close) return '-'
  const ms = new Date(close) - new Date(open)
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  const rm = mins % 60
  if (hrs < 24) return `${hrs}h ${rm}m`
  return `${Math.floor(hrs / 24)}d ${hrs % 24}h`
}
