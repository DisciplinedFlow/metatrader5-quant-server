<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { usePolling } from '@/composables/usePolling'
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
  { to: '/forex/performance', label: 'Performance' },
]

const trades = ref([])
const loading = ref(true)

async function fetchTrades() {
  try {
    const data = await api.getForexTrades()
    trades.value = data.results || data || []
  } catch (err) {
    console.error('Performance: fetch error', err)
  } finally {
    loading.value = false
  }
}

onMounted(fetchTrades)
usePolling(fetchTrades, 60000)

/* ═══ COMPUTED ANALYTICS ═══ */

const closedTrades = computed(() =>
  trades.value
    .filter(t => t.close_time && t.pnl != null)
    .sort((a, b) => new Date(a.close_time) - new Date(b.close_time))
)

const openTrades = computed(() =>
  trades.value.filter(t => !t.close_time)
)

// Equity curve
const equityCurve = computed(() => {
  let cum = 0
  return closedTrades.value.map(t => {
    cum += t.pnl
    return { pnl: t.pnl, cumulative: cum, symbol: t.symbol, time: t.close_time, strategy: t.strategy }
  })
})

// Hero stats
const stats = computed(() => {
  const ct = closedTrades.value
  if (!ct.length) return { total: 0, wins: 0, losses: 0, totalPnl: 0, winRate: 0, bestTrade: 0, worstTrade: 0, avgWin: 0, avgLoss: 0, profitFactor: 0, maxDrawdown: 0, bestPair: '—', worstPair: '—', expectancy: 0 }

  const wins = ct.filter(t => t.pnl > 0)
  const losses = ct.filter(t => t.pnl <= 0)
  const totalPnl = ct.reduce((s, t) => s + t.pnl, 0)
  const winRate = ct.length ? (wins.length / ct.length * 100) : 0
  const bestTrade = Math.max(...ct.map(t => t.pnl))
  const worstTrade = Math.min(...ct.map(t => t.pnl))
  const avgWin = wins.length ? wins.reduce((s, t) => s + t.pnl, 0) / wins.length : 0
  const avgLoss = losses.length ? Math.abs(losses.reduce((s, t) => s + t.pnl, 0) / losses.length) : 0
  const profitFactor = avgLoss > 0 ? (wins.reduce((s, t) => s + t.pnl, 0) / Math.abs(losses.reduce((s, t) => s + t.pnl, 0))) : 0
  const expectancy = ct.length ? totalPnl / ct.length : 0

  // Max drawdown
  let peak = 0, maxDD = 0, cum = 0
  for (const t of ct) {
    cum += t.pnl
    if (cum > peak) peak = cum
    const dd = peak - cum
    if (dd > maxDD) maxDD = dd
  }

  // Best/worst pair
  const bySymbol = {}
  ct.forEach(t => {
    if (!bySymbol[t.symbol]) bySymbol[t.symbol] = 0
    bySymbol[t.symbol] += t.pnl
  })
  const entries = Object.entries(bySymbol)
  const bestPair = entries.length ? entries.sort((a, b) => b[1] - a[1])[0][0] : '—'
  const worstPair = entries.length ? entries.sort((a, b) => a[1] - b[1])[0][0] : '—'

  return { total: ct.length, wins: wins.length, losses: losses.length, totalPnl, winRate, bestTrade, worstTrade, avgWin, avgLoss, profitFactor, maxDrawdown: maxDD, bestPair, worstPair, expectancy }
})

// Daily breakdown
const dailyData = computed(() => {
  const ct = closedTrades.value
  const byDay = {}
  ct.forEach(t => {
    const day = t.close_time.split('T')[0]
    if (!byDay[day]) byDay[day] = { trades: [], wins: 0, losses: 0, pnl: 0, best: -Infinity, worst: Infinity }
    byDay[day].trades.push(t)
    byDay[day].pnl += t.pnl
    if (t.pnl > 0) byDay[day].wins++
    else byDay[day].losses++
    if (t.pnl > byDay[day].best) byDay[day].best = t.pnl
    if (t.pnl < byDay[day].worst) byDay[day].worst = t.pnl
  })

  let cumulative = 0, peak = 0
  return Object.entries(byDay).sort(([a], [b]) => a.localeCompare(b)).map(([day, d]) => {
    cumulative += d.pnl
    if (cumulative > peak) peak = cumulative
    const dd = peak - cumulative
    const wr = d.trades.length ? (d.wins / d.trades.length * 100) : 0
    const dayName = new Date(day + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short' })
    const dayLabel = new Date(day + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    return { day, dayLabel, dayName, total: d.trades.length, wins: d.wins, losses: d.losses, pnl: d.pnl, cumulative, drawdown: dd, best: d.best, worst: d.worst, winRate: wr }
  })
})

// Symbol breakdown
const symbolData = computed(() => {
  const ct = closedTrades.value
  const bySymbol = {}
  ct.forEach(t => {
    if (!bySymbol[t.symbol]) bySymbol[t.symbol] = { wins: 0, losses: 0, pnl: 0, count: 0 }
    bySymbol[t.symbol].count++
    bySymbol[t.symbol].pnl += t.pnl
    if (t.pnl > 0) bySymbol[t.symbol].wins++
    else bySymbol[t.symbol].losses++
  })
  return Object.entries(bySymbol)
    .map(([symbol, d]) => ({ symbol, ...d, avg: d.pnl / d.count, wr: d.count ? (d.wins / d.count * 100) : 0 }))
    .sort((a, b) => b.pnl - a.pnl)
})

// Strategy breakdown
const strategyData = computed(() => {
  const ct = closedTrades.value
  const byStrat = {}
  ct.forEach(t => {
    const name = t.strategy || 'Unknown'
    if (!byStrat[name]) byStrat[name] = { wins: 0, losses: 0, pnl: 0, count: 0 }
    byStrat[name].count++
    byStrat[name].pnl += t.pnl
    if (t.pnl > 0) byStrat[name].wins++
    else byStrat[name].losses++
  })
  return Object.entries(byStrat)
    .map(([strategy, d]) => {
      const shortName = strategy.replace(/^CVD_/, '')
      return { strategy: shortName, fullName: strategy, ...d, avg: d.pnl / d.count, wr: d.count ? (d.wins / d.count * 100) : 0 }
    })
    .sort((a, b) => b.pnl - a.pnl)
})

// Hourly heatmap
const hourlyData = computed(() => {
  const ct = closedTrades.value
  const byHour = {}
  for (let h = 0; h < 24; h++) byHour[h] = { wins: 0, losses: 0, pnl: 0, count: 0 }
  ct.forEach(t => {
    const hour = new Date(t.entry_time).getUTCHours()
    byHour[hour].count++
    byHour[hour].pnl += t.pnl
    if (t.pnl > 0) byHour[hour].wins++
    else byHour[hour].losses++
  })
  const maxPnl = Math.max(...Object.values(byHour).map(h => Math.abs(h.pnl)), 1)
  return Object.entries(byHour).map(([hour, d]) => ({
    hour: parseInt(hour),
    ...d,
    wr: d.count ? (d.wins / d.count * 100) : 0,
    intensity: Math.abs(d.pnl) / maxPnl
  }))
})

// Risk-adjusted metrics
const riskMetrics = computed(() => {
  const ct = closedTrades.value
  if (ct.length < 2) return { sharpe: 0, sortino: 0, calmar: 0, recoveryFactor: 0, avgRRR: 0, kellyPct: 0 }
  const returns = ct.map(t => t.pnl)
  const mean = returns.reduce((s, r) => s + r, 0) / returns.length
  const variance = returns.reduce((s, r) => s + (r - mean) ** 2, 0) / (returns.length - 1)
  const stdDev = Math.sqrt(variance)
  const sharpe = stdDev > 0 ? (mean / stdDev) * Math.sqrt(252) : 0
  const downside = returns.filter(r => r < 0)
  const downsideDev = Math.sqrt(downside.length > 0 ? downside.reduce((s, r) => s + r ** 2, 0) / downside.length : 0)
  const sortino = downsideDev > 0 ? (mean / downsideDev) * Math.sqrt(252) : 0
  const totalReturn = returns.reduce((s, r) => s + r, 0)
  const calmar = stats.value.maxDrawdown > 0 ? totalReturn / stats.value.maxDrawdown : 0
  const recoveryFactor = calmar
  const wins = ct.filter(t => t.pnl > 0)
  const losses = ct.filter(t => t.pnl < 0)
  const avgWin = wins.length ? wins.reduce((s, t) => s + t.pnl, 0) / wins.length : 0
  const avgLoss = losses.length ? Math.abs(losses.reduce((s, t) => s + t.pnl, 0) / losses.length) : 0
  const avgRRR = avgLoss > 0 ? avgWin / avgLoss : 0
  const wr = ct.length ? wins.length / ct.length : 0
  const kelly = avgLoss > 0 && avgRRR > 0 ? (wr - ((1 - wr) / avgRRR)) * 100 : 0
  return { sharpe, sortino, calmar, recoveryFactor, avgRRR, kellyPct: Math.max(0, kelly) }
})

// Direction analysis (BUY vs SELL)
const directionData = computed(() => {
  const ct = closedTrades.value
  const calc = (arr) => {
    const w = arr.filter(t => t.pnl > 0)
    const pnl = arr.reduce((s, t) => s + t.pnl, 0)
    return { count: arr.length, wins: w.length, losses: arr.length - w.length, pnl, wr: arr.length ? (w.length / arr.length * 100) : 0, avg: arr.length ? pnl / arr.length : 0 }
  }
  return {
    buy: calc(ct.filter(t => t.type === 'BUY' || t.type === 'ORDER_TYPE_BUY')),
    sell: calc(ct.filter(t => t.type === 'SELL' || t.type === 'ORDER_TYPE_SELL')),
  }
})

// Streak analysis
const streakData = computed(() => {
  const ct = closedTrades.value
  if (!ct.length) return { current: 0, currentType: 'none', maxWin: 0, maxLoss: 0, avgWinStreak: 0, avgLossStreak: 0, pWinAfterWin: 0, pWinAfterLoss: 0 }
  let maxWin = 0, maxLoss = 0, streak = 0, prevWin = null
  const winStreaks = [], lossStreaks = []
  let wAW = 0, tAW = 0, wAL = 0, tAL = 0
  for (let i = 0; i < ct.length; i++) {
    const isWin = ct[i].pnl > 0
    if (i > 0) { if (ct[i-1].pnl > 0) { tAW++; if (isWin) wAW++ } else { tAL++; if (isWin) wAL++ } }
    if (prevWin === null || isWin === prevWin) { streak++ } else {
      if (prevWin) { if (streak > maxWin) maxWin = streak; winStreaks.push(streak) }
      else { if (streak > maxLoss) maxLoss = streak; lossStreaks.push(streak) }
      streak = 1
    }
    prevWin = isWin
  }
  if (prevWin) { if (streak > maxWin) maxWin = streak; winStreaks.push(streak) }
  else { if (streak > maxLoss) maxLoss = streak; lossStreaks.push(streak) }
  const currentType = ct[ct.length-1].pnl > 0 ? 'win' : 'loss'
  let current = 0
  for (let i = ct.length - 1; i >= 0; i--) {
    if ((currentType === 'win' && ct[i].pnl > 0) || (currentType === 'loss' && ct[i].pnl <= 0)) current++; else break
  }
  return { current, currentType, maxWin, maxLoss,
    avgWinStreak: winStreaks.length ? winStreaks.reduce((s,v) => s+v, 0) / winStreaks.length : 0,
    avgLossStreak: lossStreaks.length ? lossStreaks.reduce((s,v) => s+v, 0) / lossStreaks.length : 0,
    pWinAfterWin: tAW ? (wAW / tAW * 100) : 0, pWinAfterLoss: tAL ? (wAL / tAL * 100) : 0 }
})

// Trade duration analysis
const durationData = computed(() => {
  const ct = closedTrades.value.filter(t => t.entry_time && t.close_time)
  if (!ct.length) return { avgAll: 0, avgWinner: 0, avgLoser: 0, longestWin: 0, longestLoss: 0 }
  const dur = t => (new Date(t.close_time) - new Date(t.entry_time)) / 60000
  const wins = ct.filter(t => t.pnl > 0).map(dur)
  const losses = ct.filter(t => t.pnl <= 0).map(dur)
  const all = ct.map(dur)
  return {
    avgAll: all.reduce((s,d) => s+d, 0) / all.length,
    avgWinner: wins.length ? wins.reduce((s,d) => s+d, 0) / wins.length : 0,
    avgLoser: losses.length ? losses.reduce((s,d) => s+d, 0) / losses.length : 0,
    longestWin: wins.length ? Math.max(...wins) : 0,
    longestLoss: losses.length ? Math.max(...losses) : 0,
  }
})

// MFE/MAE analysis
const mfeMaeData = computed(() => {
  const ct = closedTrades.value
  const withMfe = ct.filter(t => t.max_profit != null)
  const withMae = ct.filter(t => t.max_drawdown != null)
  if (!withMfe.length && !withMae.length) return null
  const mfeWins = withMfe.filter(t => t.pnl > 0)
  const mfeLosses = withMfe.filter(t => t.pnl <= 0)
  const avgMfeWin = mfeWins.length ? mfeWins.reduce((s,t) => s + (t.max_profit||0), 0) / mfeWins.length : 0
  const avgMfeLoss = mfeLosses.length ? mfeLosses.reduce((s,t) => s + (t.max_profit||0), 0) / mfeLosses.length : 0
  const maeWins = withMae.filter(t => t.pnl > 0)
  const maeLosses = withMae.filter(t => t.pnl <= 0)
  const avgMaeWin = maeWins.length ? maeWins.reduce((s,t) => s + Math.abs(t.max_drawdown||0), 0) / maeWins.length : 0
  const avgMaeLoss = maeLosses.length ? maeLosses.reduce((s,t) => s + Math.abs(t.max_drawdown||0), 0) / maeLosses.length : 0
  const avgMfe = withMfe.length ? withMfe.reduce((s,t) => s + (t.max_profit||0), 0) / withMfe.length : 0
  const avgMae = withMae.length ? withMae.reduce((s,t) => s + Math.abs(t.max_drawdown||0), 0) / withMae.length : 0
  const edgeRatio = avgMae > 0 ? avgMfe / avgMae : 0
  const capTrades = withMfe.filter(t => t.pnl > 0 && t.max_profit > 0)
  const avgCapture = capTrades.length ? capTrades.reduce((s,t) => s + (t.pnl / t.max_profit), 0) / capTrades.length * 100 : 0
  return { mfeCount: withMfe.length, maeCount: withMae.length, avgMfeWin, avgMfeLoss, avgMaeWin, avgMaeLoss, edgeRatio, avgCapture, avgMfe, avgMae }
})

// Day-of-week breakdown
const dayOfWeekData = computed(() => {
  const ct = closedTrades.value
  const names = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']
  const byDay = {}
  names.forEach((n,i) => { byDay[i] = { name: n, wins: 0, losses: 0, pnl: 0, count: 0 } })
  ct.forEach(t => {
    const d = new Date(t.entry_time).getUTCDay()
    byDay[d].count++; byDay[d].pnl += t.pnl
    if (t.pnl > 0) byDay[d].wins++; else byDay[d].losses++
  })
  const maxP = Math.max(...Object.values(byDay).map(d => Math.abs(d.pnl)), 1)
  return Object.values(byDay).map(d => ({ ...d, wr: d.count ? (d.wins/d.count*100) : 0, avg: d.count ? d.pnl/d.count : 0, intensity: Math.abs(d.pnl)/maxP }))
})

// Session performance
const sessionData = computed(() => {
  const ct = closedTrades.value
  const sessions = [
    { name: 'Asia', start: 0, end: 8 },
    { name: 'London', start: 8, end: 16 },
    { name: 'New York', start: 13, end: 21 },
    { name: 'LDN/NY Overlap', start: 13, end: 16 },
  ]
  return sessions.map(s => {
    const trades = ct.filter(t => { const h = new Date(t.entry_time).getUTCHours(); return h >= s.start && h < s.end })
    const w = trades.filter(t => t.pnl > 0)
    const pnl = trades.reduce((sum, t) => sum + t.pnl, 0)
    return { name: s.name, count: trades.length, wins: w.length, losses: trades.length - w.length, pnl, wr: trades.length ? (w.length/trades.length*100) : 0, avg: trades.length ? pnl/trades.length : 0 }
  })
})

// Closing reason breakdown
const closingReasonData = computed(() => {
  const ct = closedTrades.value
  const byR = {}
  ct.forEach(t => {
    const r = t.closing_reason || 'Unknown'
    if (!byR[r]) byR[r] = { wins: 0, losses: 0, pnl: 0, count: 0 }
    byR[r].count++; byR[r].pnl += t.pnl
    if (t.pnl > 0) byR[r].wins++; else byR[r].losses++
  })
  return Object.entries(byR).map(([reason, d]) => ({ reason, ...d, wr: d.count ? (d.wins/d.count*100) : 0, avg: d.count ? d.pnl/d.count : 0 })).sort((a,b) => b.count - a.count)
})

// Position management stats
const managementData = computed(() => {
  const ct = closedTrades.value
  const be = ct.filter(t => t.breakeven_moved)
  const partial = ct.filter(t => t.partial_closed)
  const withAtr = ct.filter(t => t.entry_atr != null && t.entry_atr > 0)
  const withVol = ct.filter(t => t.position_size_usd != null && t.position_size_usd > 0)
  const calc = arr => ({ count: arr.length, wins: arr.filter(t => t.pnl > 0).length, pnl: arr.reduce((s,t) => s + t.pnl, 0) })
  return {
    be: { ...calc(be), wr: be.length ? (be.filter(t => t.pnl > 0).length / be.length * 100) : 0 },
    partial: { ...calc(partial), wr: partial.length ? (partial.filter(t => t.pnl > 0).length / partial.length * 100) : 0 },
    avgAtr: withAtr.length ? withAtr.reduce((s,t) => s + t.entry_atr, 0) / withAtr.length : 0,
    avgAtrWin: withAtr.filter(t => t.pnl > 0).length ? withAtr.filter(t => t.pnl > 0).reduce((s,t) => s + t.entry_atr, 0) / withAtr.filter(t => t.pnl > 0).length : 0,
    avgAtrLoss: withAtr.filter(t => t.pnl <= 0).length ? withAtr.filter(t => t.pnl <= 0).reduce((s,t) => s + t.entry_atr, 0) / withAtr.filter(t => t.pnl <= 0).length : 0,
    avgSize: withVol.length ? withVol.reduce((s,t) => s + t.position_size_usd, 0) / withVol.length : 0,
    atrCount: withAtr.length, volCount: withVol.length,
  }
})

// Top insights
const insights = computed(() => {
  const results = []
  const sd = symbolData.value
  const st = strategyData.value
  const hd = hourlyData.value

  // Worst pair
  const worst = sd[sd.length - 1]
  if (worst && worst.pnl < -50) {
    results.push({ type: 'danger', icon: 'warning', title: `${worst.symbol} bleeding`, text: `${worst.symbol} is down $${Math.abs(worst.pnl).toFixed(0)} across ${worst.count} trades (${worst.wr.toFixed(0)}% WR). Consider reducing exposure.` })
  }

  // Best pair
  const best = sd[0]
  if (best && best.pnl > 0) {
    results.push({ type: 'success', icon: 'trending_up', title: `${best.symbol} is your edge`, text: `+$${best.pnl.toFixed(0)} from ${best.count} trades at ${best.wr.toFixed(0)}% WR. Avg $${best.avg.toFixed(2)}/trade.` })
  }

  // Worst strategy
  const worstStrat = st[st.length - 1]
  if (worstStrat && worstStrat.pnl < -50) {
    results.push({ type: 'danger', icon: 'block', title: `Kill ${worstStrat.strategy}`, text: `Down $${Math.abs(worstStrat.pnl).toFixed(0)} across ${worstStrat.count} trades. ${worstStrat.wr.toFixed(0)}% WR — not viable.` })
  }

  // Best hour
  const bestHour = [...hd].sort((a, b) => b.pnl - a.pnl)[0]
  if (bestHour && bestHour.pnl > 0) {
    results.push({ type: 'success', icon: 'schedule', title: `${String(bestHour.hour).padStart(2, '0')}:00 UTC is peak`, text: `+$${bestHour.pnl.toFixed(0)} from ${bestHour.count} trades at ${bestHour.wr.toFixed(0)}% WR.` })
  }

  // Worst hour
  const worstHour = [...hd].sort((a, b) => a.pnl - b.pnl)[0]
  if (worstHour && worstHour.pnl < -50) {
    results.push({ type: 'danger', icon: 'dangerous', title: `${String(worstHour.hour).padStart(2, '0')}:00 UTC is toxic`, text: `-$${Math.abs(worstHour.pnl).toFixed(0)} from ${worstHour.count} trades. Block this hour.` })
  }

  // Profit factor
  if (stats.value.profitFactor > 0) {
    const pf = stats.value.profitFactor
    results.push({ type: pf >= 1.2 ? 'success' : pf >= 0.8 ? 'warning' : 'danger', icon: 'balance', title: `Profit Factor: ${pf.toFixed(2)}`, text: `Avg win: $${stats.value.avgWin.toFixed(2)} vs avg loss: $${stats.value.avgLoss.toFixed(2)}. Expectancy: $${stats.value.expectancy.toFixed(2)}/trade.` })
  }

  // Streak insight
  const sk = streakData.value
  if (sk.current >= 3 && sk.currentType === 'loss') {
    results.push({ type: 'danger', icon: 'local_fire_department', title: `${sk.current}-trade losing streak`, text: `Max loss streak: ${sk.maxLoss}. P(win after loss): ${sk.pWinAfterLoss.toFixed(0)}%. Consider reducing size.` })
  } else if (sk.current >= 4 && sk.currentType === 'win') {
    results.push({ type: 'success', icon: 'whatshot', title: `${sk.current}-trade win streak!`, text: `P(win after win): ${sk.pWinAfterWin.toFixed(0)}%. Max win streak: ${sk.maxWin}. Momentum is strong.` })
  }

  // Direction bias
  const dir = directionData.value
  if (dir.buy.count > 5 && dir.sell.count > 5 && Math.abs(dir.buy.wr - dir.sell.wr) > 15) {
    const better = dir.buy.wr > dir.sell.wr ? 'BUY' : 'SELL'
    const worse = better === 'BUY' ? 'SELL' : 'BUY'
    const bWr = better === 'BUY' ? dir.buy.wr : dir.sell.wr
    results.push({ type: 'warning', icon: 'swap_vert', title: `${better} bias detected`, text: `${better} WR: ${bWr.toFixed(0)}% vs ${worse} WR: ${(better === 'BUY' ? dir.sell.wr : dir.buy.wr).toFixed(0)}%. Consider filtering ${worse} signals.` })
  }

  // Session dominance
  const sess = sessionData.value.filter(s => s.count >= 5)
  const bestSess = sess.sort((a,b) => b.avg - a.avg)[0]
  if (bestSess && bestSess.avg > 0.5) {
    results.push({ type: 'success', icon: 'public', title: `${bestSess.name} is your session`, text: `$${bestSess.avg.toFixed(2)}/trade avg across ${bestSess.count} trades at ${bestSess.wr.toFixed(0)}% WR.` })
  }

  // Duration insight
  const dd = durationData.value
  if (dd.avgWinner > 0 && dd.avgLoser > 0 && dd.avgLoser > dd.avgWinner * 1.5) {
    results.push({ type: 'warning', icon: 'timer', title: 'Losers held too long', text: `Avg loser: ${fmtDuration(dd.avgLoser)} vs avg winner: ${fmtDuration(dd.avgWinner)}. Cut losses faster.` })
  }

  // MFE capture
  const mfe = mfeMaeData.value
  if (mfe && mfe.avgCapture > 0 && mfe.avgCapture < 40) {
    results.push({ type: 'warning', icon: 'trending_flat', title: `Only capturing ${mfe.avgCapture.toFixed(0)}% of moves`, text: `Edge ratio: ${mfe.edgeRatio.toFixed(2)}. Winners reach $${mfe.avgMfeWin.toFixed(2)} MFE but close at avg $${stats.value.avgWin.toFixed(2)}.` })
  }

  return results
})

/* ═══ CANVAS CHARTS ═══ */

const equityCanvas = ref(null)
const dailyCanvas = ref(null)

function getThemeColors() {
  const style = getComputedStyle(document.documentElement)
  return {
    text: style.getPropertyValue('--tp-text').trim() || '#f1f5f9',
    dim: style.getPropertyValue('--tp-text-dim').trim() || '#94a3b8',
    border: style.getPropertyValue('--tp-border').trim() || '#1e293b',
    success: style.getPropertyValue('--tp-success').trim() || '#34d399',
    danger: style.getPropertyValue('--tp-danger').trim() || '#f87171',
    primary: style.getPropertyValue('--tp-primary').trim() || '#3b82f6',
    surface: style.getPropertyValue('--tp-bg-surface').trim() || '#0f172a',
  }
}

function drawEquityCurve() {
  const canvas = equityCanvas.value
  if (!canvas || !equityCurve.value.length) return
  const ctx = canvas.getContext('2d')
  const c = getThemeColors()
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = rect.width * dpr
  canvas.height = rect.height * dpr
  ctx.scale(dpr, dpr)
  const w = rect.width, h = rect.height

  const pad = { top: 24, right: 16, bottom: 28, left: 56 }
  const cw = w - pad.left - pad.right
  const ch = h - pad.top - pad.bottom

  const pts = [0, ...equityCurve.value.map(p => p.cumulative)]
  const minV = Math.min(...pts) * 1.05
  const maxV = Math.max(0, ...pts) * 1.05 || 50
  const range = maxV - minV || 1

  const sx = i => pad.left + (i / (pts.length - 1)) * cw
  const sy = v => pad.top + (1 - (v - minV) / range) * ch

  // Grid lines
  ctx.strokeStyle = c.border
  ctx.lineWidth = 0.5
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (ch / 4) * i
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke()
    const val = maxV - (range / 4) * i
    ctx.fillStyle = c.dim
    ctx.font = '10px system-ui'
    ctx.textAlign = 'right'
    ctx.fillText(`$${val.toFixed(0)}`, pad.left - 8, y + 3)
  }

  // Zero line
  const zy = sy(0)
  ctx.strokeStyle = c.dim
  ctx.lineWidth = 0.8
  ctx.setLineDash([4, 4])
  ctx.beginPath(); ctx.moveTo(pad.left, zy); ctx.lineTo(w - pad.right, zy); ctx.stroke()
  ctx.setLineDash([])

  // Area fill
  ctx.beginPath()
  ctx.moveTo(sx(0), sy(pts[0]))
  pts.forEach((v, i) => ctx.lineTo(sx(i), sy(v)))
  ctx.lineTo(sx(pts.length - 1), sy(0))
  ctx.lineTo(sx(0), sy(0))
  ctx.closePath()
  const lastVal = pts[pts.length - 1]
  const grad = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom)
  grad.addColorStop(0, lastVal >= 0 ? 'rgba(52,211,153,0.12)' : 'rgba(248,113,113,0.12)')
  grad.addColorStop(1, 'transparent')
  ctx.fillStyle = grad
  ctx.fill()

  // Line
  ctx.beginPath()
  ctx.moveTo(sx(0), sy(pts[0]))
  pts.forEach((v, i) => ctx.lineTo(sx(i), sy(v)))
  ctx.strokeStyle = lastVal >= 0 ? c.success : c.danger
  ctx.lineWidth = 2
  ctx.lineJoin = 'round'
  ctx.stroke()

  // End dot
  const lx = sx(pts.length - 1), ly = sy(lastVal)
  ctx.beginPath()
  ctx.arc(lx, ly, 4, 0, Math.PI * 2)
  ctx.fillStyle = lastVal >= 0 ? c.success : c.danger
  ctx.fill()

  // End value
  ctx.font = 'bold 11px system-ui'
  ctx.fillStyle = lastVal >= 0 ? c.success : c.danger
  ctx.textAlign = 'right'
  ctx.fillText(`$${lastVal.toFixed(0)}`, lx - 8, ly - 8)
}

function drawDailyBars() {
  const canvas = dailyCanvas.value
  const days = dailyData.value
  if (!canvas || !days.length) return
  const ctx = canvas.getContext('2d')
  const c = getThemeColors()
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = rect.width * dpr
  canvas.height = rect.height * dpr
  ctx.scale(dpr, dpr)
  const w = rect.width, h = rect.height

  const pad = { top: 20, right: 16, bottom: 32, left: 48 }
  const cw = w - pad.left - pad.right
  const ch = h - pad.top - pad.bottom

  const maxAbs = Math.max(...days.map(d => Math.abs(d.pnl)), 1) * 1.2
  const barW = Math.min(cw / days.length, 60)
  const gap = barW * 0.25
  const zy = pad.top + ch / 2

  // Zero line
  ctx.strokeStyle = c.dim
  ctx.lineWidth = 0.8
  ctx.setLineDash([4, 4])
  ctx.beginPath(); ctx.moveTo(pad.left, zy); ctx.lineTo(w - pad.right, zy); ctx.stroke()
  ctx.setLineDash([])

  days.forEach((d, i) => {
    const x = pad.left + (cw / days.length) * i + (cw / days.length - barW + gap) / 2
    const barH = (Math.abs(d.pnl) / maxAbs) * (ch / 2)
    const isPos = d.pnl >= 0

    // Bar
    const radius = 3
    ctx.fillStyle = isPos ? c.success : c.danger
    ctx.globalAlpha = 0.85
    if (isPos) {
      ctx.beginPath()
      ctx.moveTo(x + radius, zy - barH)
      ctx.lineTo(x + barW - gap - radius, zy - barH)
      ctx.quadraticCurveTo(x + barW - gap, zy - barH, x + barW - gap, zy - barH + radius)
      ctx.lineTo(x + barW - gap, zy)
      ctx.lineTo(x, zy)
      ctx.lineTo(x, zy - barH + radius)
      ctx.quadraticCurveTo(x, zy - barH, x + radius, zy - barH)
      ctx.fill()
    } else {
      ctx.beginPath()
      ctx.moveTo(x, zy)
      ctx.lineTo(x + barW - gap, zy)
      ctx.lineTo(x + barW - gap, zy + barH - radius)
      ctx.quadraticCurveTo(x + barW - gap, zy + barH, x + barW - gap - radius, zy + barH)
      ctx.lineTo(x + radius, zy + barH)
      ctx.quadraticCurveTo(x, zy + barH, x, zy + barH - radius)
      ctx.fill()
    }
    ctx.globalAlpha = 1

    // Value
    ctx.font = '10px system-ui'
    ctx.textAlign = 'center'
    ctx.fillStyle = isPos ? c.success : c.danger
    const valY = isPos ? zy - barH - 6 : zy + barH + 14
    ctx.fillText(`$${d.pnl.toFixed(0)}`, x + (barW - gap) / 2, valY)

    // Label
    ctx.fillStyle = c.dim
    ctx.font = '10px system-ui'
    ctx.fillText(d.dayLabel, x + (barW - gap) / 2, h - 8)
  })

  // Y axis
  ctx.fillStyle = c.dim
  ctx.font = '10px system-ui'
  ctx.textAlign = 'right'
  ctx.fillText('$0', pad.left - 8, zy + 3)
}

watch([closedTrades], () => {
  nextTick(() => {
    drawEquityCurve()
    drawDailyBars()
  })
}, { flush: 'post' })

onMounted(() => {
  nextTick(() => {
    drawEquityCurve()
    drawDailyBars()
  })
  window.addEventListener('resize', () => { drawEquityCurve(); drawDailyBars() })
})

/* ═══ HELPERS ═══ */
function pnlClass(v) { return v > 0 ? 'val-pos' : v < 0 ? 'val-neg' : '' }
function fmtPnl(v) { return (v >= 0 ? '+' : '') + '€' + v.toFixed(2) }
function wrColor(wr) {
  if (wr >= 55) return 'var(--tp-success)'
  if (wr >= 45) return 'var(--tp-text-dim)'
  return 'var(--tp-danger)'
}
function fmtDuration(minutes) {
  if (minutes < 60) return `${Math.round(minutes)}m`
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`
  return `${Math.floor(minutes / 1440)}d ${Math.floor((minutes % 1440) / 60)}h`
}
function metricColor(val, goodAbove, badBelow) {
  if (val >= goodAbove) return 'var(--tp-success)'
  if (val <= badBelow) return 'var(--tp-danger)'
  return 'var(--tp-warning)'
}
</script>

<template>
  <SectionNav :links="forexLinks" />
  <div class="tp-page perf-page">

    <!-- Loading state -->
    <div v-if="loading" class="perf-loading">
      <span class="material-symbols-outlined spin">autorenew</span>
      <span>Loading analytics...</span>
    </div>

    <template v-else>

    <!-- ═══ HEADER ═══ -->
    <div class="perf-header" style="--stagger:0">
      <div class="perf-header-left">
        <h1>Performance</h1>
        <span class="perf-subtitle">{{ stats.total }} trades &middot; {{ dailyData.length }} days &middot; {{ symbolData.length }} pairs</span>
      </div>
      <div class="perf-header-right">
        <span class="perf-live-tag">
          <span class="pulse-dot-sm"></span>
          Live Data
        </span>
      </div>
    </div>

    <!-- ═══ HERO STATS ═══ -->
    <div class="hero-grid">
      <div class="tp-stat-card hero-stat" style="--stagger:1">
        <div class="stat-icon-wrap stat-icon-pnl">
          <span class="material-symbols-outlined">account_balance</span>
        </div>
        <div class="stat-label">Total P&L</div>
        <div class="stat-value" :class="pnlClass(stats.totalPnl)">{{ fmtPnl(stats.totalPnl) }}</div>
        <div class="stat-sub">{{ stats.expectancy >= 0 ? '+' : '' }}&euro;{{ stats.expectancy.toFixed(2) }}/trade</div>
      </div>

      <div class="tp-stat-card hero-stat" style="--stagger:2">
        <div class="stat-icon-wrap stat-icon-wr">
          <span class="material-symbols-outlined">target</span>
        </div>
        <div class="stat-label">Win Rate</div>
        <div class="stat-value">{{ stats.winRate.toFixed(1) }}%</div>
        <div class="stat-sub">{{ stats.wins }}W / {{ stats.losses }}L</div>
      </div>

      <div class="tp-stat-card hero-stat" style="--stagger:3">
        <div class="stat-icon-wrap stat-icon-dd">
          <span class="material-symbols-outlined">trending_down</span>
        </div>
        <div class="stat-label">Max Drawdown</div>
        <div class="stat-value val-neg">-&euro;{{ stats.maxDrawdown.toFixed(2) }}</div>
        <div class="stat-sub">Peak-to-trough</div>
      </div>

      <div class="tp-stat-card hero-stat" style="--stagger:4">
        <div class="stat-icon-wrap stat-icon-pf">
          <span class="material-symbols-outlined">balance</span>
        </div>
        <div class="stat-label">Profit Factor</div>
        <div class="stat-value" :class="stats.profitFactor >= 1 ? 'val-pos' : 'val-neg'">{{ stats.profitFactor.toFixed(2) }}</div>
        <div class="stat-sub">Avg win &euro;{{ stats.avgWin.toFixed(2) }}</div>
      </div>

      <div class="tp-stat-card hero-stat" style="--stagger:5">
        <div class="stat-icon-wrap stat-icon-best">
          <span class="material-symbols-outlined">emoji_events</span>
        </div>
        <div class="stat-label">Best Pair</div>
        <div class="stat-value val-pos">{{ stats.bestPair }}</div>
        <div class="stat-sub" v-if="symbolData.length">+&euro;{{ symbolData[0]?.pnl?.toFixed(2) }}</div>
      </div>

      <div class="tp-stat-card hero-stat" style="--stagger:6">
        <div class="stat-icon-wrap stat-icon-worst">
          <span class="material-symbols-outlined">heart_broken</span>
        </div>
        <div class="stat-label">Worst Pair</div>
        <div class="stat-value val-neg">{{ stats.worstPair }}</div>
        <div class="stat-sub" v-if="symbolData.length">&euro;{{ symbolData[symbolData.length - 1]?.pnl?.toFixed(2) }}</div>
      </div>
    </div>

    <!-- ═══ CHARTS ROW ═══ -->
    <div class="charts-row">
      <div class="tp-card chart-card" style="--stagger:7">
        <div class="card-accent accent-equity"></div>
        <h3 class="card-title">
          <span class="material-symbols-outlined" style="font-size:18px">show_chart</span>
          Equity Curve
        </h3>
        <canvas ref="equityCanvas" class="perf-canvas" height="220"></canvas>
      </div>
      <div class="tp-card chart-card" style="--stagger:8">
        <div class="card-accent accent-daily"></div>
        <h3 class="card-title">
          <span class="material-symbols-outlined" style="font-size:18px">bar_chart</span>
          Daily P&L
        </h3>
        <canvas ref="dailyCanvas" class="perf-canvas" height="220"></canvas>
      </div>
    </div>

    <!-- ═══ DAILY BREAKDOWN TABLE ═══ -->
    <div class="tp-card table-card" style="--stagger:9">
      <div class="card-accent accent-table"></div>
      <h3 class="card-title table-card-title">
        <span class="material-symbols-outlined" style="font-size:18px">calendar_month</span>
        Daily Breakdown
      </h3>
      <div class="table-scroll">
        <table class="tp-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Day</th>
              <th class="num">Trades</th>
              <th class="num">W</th>
              <th class="num">L</th>
              <th style="min-width:120px">Win Rate</th>
              <th class="num">Day P&L</th>
              <th class="num">Cumulative</th>
              <th class="num">Drawdown</th>
              <th class="num">Best</th>
              <th class="num">Worst</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in dailyData" :key="d.day" :class="{ 'row-blow': d.pnl < -200 }">
              <td class="td-bold">{{ d.dayLabel }}</td>
              <td class="td-dim">{{ d.dayName }}</td>
              <td class="num">{{ d.total }}</td>
              <td class="num val-pos">{{ d.wins }}</td>
              <td class="num val-neg">{{ d.losses }}</td>
              <td>
                <div class="wr-bar">
                  <div class="wr-track">
                    <div class="wr-fill" :style="{ width: d.winRate + '%', background: wrColor(d.winRate) }"></div>
                  </div>
                  <span class="wr-val" :style="{ color: wrColor(d.winRate) }">{{ d.winRate.toFixed(0) }}%</span>
                </div>
              </td>
              <td class="num" :class="pnlClass(d.pnl)">{{ fmtPnl(d.pnl) }}</td>
              <td class="num" :class="pnlClass(d.cumulative)">{{ fmtPnl(d.cumulative) }}</td>
              <td class="num" :class="d.drawdown > 100 ? 'val-neg' : ''">{{ d.drawdown > 0 ? '$' + d.drawdown.toFixed(0) : '—' }}</td>
              <td class="num val-pos">+&euro;{{ d.best.toFixed(2) }}</td>
              <td class="num val-neg">&euro;{{ d.worst.toFixed(2) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ═══ SYMBOL + STRATEGY ROW ═══ -->
    <div class="detail-row">
      <!-- Symbol Performance -->
      <div class="tp-card table-card" style="--stagger:10">
        <div class="card-accent accent-symbol"></div>
        <h3 class="card-title table-card-title">
          <span class="material-symbols-outlined" style="font-size:18px">currency_exchange</span>
          Pair Performance
        </h3>
        <div class="table-scroll">
          <table class="tp-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th class="num">Trades</th>
                <th class="num">W / L</th>
                <th style="min-width:110px">Win Rate</th>
                <th class="num">Total P&L</th>
                <th class="num">Avg P&L</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in symbolData" :key="s.symbol">
                <td class="td-bold">{{ s.symbol }}</td>
                <td class="num">{{ s.count }}</td>
                <td class="num"><span class="val-pos">{{ s.wins }}</span><span class="td-dim"> / </span><span class="val-neg">{{ s.losses }}</span></td>
                <td>
                  <div class="wr-bar">
                    <div class="wr-track">
                      <div class="wr-fill" :style="{ width: s.wr + '%', background: wrColor(s.wr) }"></div>
                    </div>
                    <span class="wr-val" :style="{ color: wrColor(s.wr) }">{{ s.wr.toFixed(0) }}%</span>
                  </div>
                </td>
                <td class="num" :class="pnlClass(s.pnl)">{{ fmtPnl(s.pnl) }}</td>
                <td class="num" :class="pnlClass(s.avg)">{{ fmtPnl(s.avg) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Strategy Performance -->
      <div class="tp-card table-card" style="--stagger:11">
        <div class="card-accent accent-strat"></div>
        <h3 class="card-title table-card-title">
          <span class="material-symbols-outlined" style="font-size:18px">psychology</span>
          Strategy Performance
        </h3>
        <div class="table-scroll">
          <table class="tp-table">
            <thead>
              <tr>
                <th>Strategy</th>
                <th class="num">Trades</th>
                <th style="min-width:100px">Win Rate</th>
                <th class="num">Total P&L</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in strategyData" :key="s.fullName">
                <td class="td-strat" :title="s.fullName">{{ s.strategy }}</td>
                <td class="num">{{ s.count }}</td>
                <td>
                  <div class="wr-bar">
                    <div class="wr-track">
                      <div class="wr-fill" :style="{ width: s.wr + '%', background: wrColor(s.wr) }"></div>
                    </div>
                    <span class="wr-val" :style="{ color: wrColor(s.wr) }">{{ s.wr.toFixed(0) }}%</span>
                  </div>
                </td>
                <td class="num" :class="pnlClass(s.pnl)">{{ fmtPnl(s.pnl) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ═══ HOURLY HEATMAP ═══ -->
    <div class="tp-card heatmap-card" style="--stagger:12">
      <div class="card-accent accent-heatmap"></div>
      <h3 class="card-title table-card-title">
        <span class="material-symbols-outlined" style="font-size:18px">schedule</span>
        Hourly P&L Heatmap
        <span class="heatmap-sub">UTC</span>
      </h3>
      <div class="heatmap-grid">
        <div
          v-for="h in hourlyData" :key="h.hour"
          class="heatmap-cell"
          :class="{ 'cell-positive': h.pnl > 0, 'cell-negative': h.pnl < 0, 'cell-best': h === [...hourlyData].sort((a,b) => b.pnl - a.pnl)[0] && h.pnl > 0, 'cell-worst': h === [...hourlyData].sort((a,b) => a.pnl - b.pnl)[0] && h.pnl < -50 }"
          :style="{ '--cell-intensity': h.intensity }"
        >
          <span class="cell-hour">{{ String(h.hour).padStart(2, '0') }}</span>
          <span class="cell-pnl" :class="pnlClass(h.pnl)">{{ h.pnl >= 0 ? '+' : '' }}&euro;{{ h.pnl.toFixed(0) }}</span>
          <span class="cell-wr">{{ h.count ? h.wr.toFixed(0) + '%' : '—' }}</span>
          <span class="cell-count">{{ h.count }}t</span>
        </div>
      </div>
      <div class="heatmap-legend">
        <span class="heatmap-legend-item"><span class="legend-dot" style="background:var(--tp-success)"></span> Profitable</span>
        <span class="heatmap-legend-item"><span class="legend-dot" style="background:var(--tp-danger)"></span> Loss</span>
        <span class="heatmap-legend-item"><span class="legend-dot" style="background:var(--tp-success);box-shadow:0 0 6px var(--tp-success)"></span> Best hour</span>
        <span class="heatmap-legend-item"><span class="legend-dot" style="background:var(--tp-danger);box-shadow:0 0 6px var(--tp-danger)"></span> Worst hour</span>
      </div>
    </div>

    <!-- ═══ INSIGHTS ═══ -->
    <div class="insights-grid" v-if="insights.length">
      <div
        v-for="(insight, idx) in insights" :key="idx"
        class="insight-card"
        :class="'insight-' + insight.type"
        :style="{ '--stagger': 13 + idx }"
      >
        <div class="insight-icon">
          <span class="material-symbols-outlined">{{ insight.icon }}</span>
        </div>
        <div class="insight-body">
          <div class="insight-title">{{ insight.title }}</div>
          <div class="insight-text">{{ insight.text }}</div>
        </div>
      </div>
    </div>

    <!-- ═══ RECENT TRADES SPARKLINE ═══ -->
    <div class="tp-card sparkline-card" style="--stagger:19">
      <div class="card-accent accent-spark"></div>
      <h3 class="card-title table-card-title">
        <span class="material-symbols-outlined" style="font-size:18px">timeline</span>
        Last 50 Trades
      </h3>
      <div class="sparkline-row">
        <div
          v-for="(t, i) in closedTrades.slice(-50)" :key="i"
          class="spark-bar"
          :class="t.pnl >= 0 ? 'spark-win' : 'spark-loss'"
          :style="{ height: Math.min(100, Math.max(12, Math.abs(t.pnl) * 2.5)) + '%' }"
          :title="`${t.symbol} ${fmtPnl(t.pnl)}`"
        ></div>
      </div>
    </div>

    <!-- ═══ RISK-ADJUSTED METRICS ═══ -->
    <div class="risk-grid" style="--stagger:20">
      <div class="tp-stat-card hero-stat risk-stat">
        <div class="stat-icon-wrap" style="background:rgba(59,130,246,0.1);color:var(--tp-primary)">
          <span class="material-symbols-outlined">query_stats</span>
        </div>
        <div class="stat-label">Sharpe Ratio</div>
        <div class="stat-value" :style="{ color: metricColor(riskMetrics.sharpe, 1, 0) }">{{ riskMetrics.sharpe.toFixed(2) }}</div>
        <div class="stat-sub">Annualized risk-adj return</div>
      </div>
      <div class="tp-stat-card hero-stat risk-stat" style="--stagger:21">
        <div class="stat-icon-wrap" style="background:rgba(139,92,246,0.1);color:#8b5cf6">
          <span class="material-symbols-outlined">shield</span>
        </div>
        <div class="stat-label">Sortino Ratio</div>
        <div class="stat-value" :style="{ color: metricColor(riskMetrics.sortino, 1.5, 0) }">{{ riskMetrics.sortino.toFixed(2) }}</div>
        <div class="stat-sub">Downside-only risk</div>
      </div>
      <div class="tp-stat-card hero-stat risk-stat" style="--stagger:22">
        <div class="stat-icon-wrap" style="background:rgba(6,182,212,0.1);color:#06b6d4">
          <span class="material-symbols-outlined">speed</span>
        </div>
        <div class="stat-label">Calmar Ratio</div>
        <div class="stat-value" :style="{ color: metricColor(riskMetrics.calmar, 1, 0) }">{{ riskMetrics.calmar.toFixed(2) }}</div>
        <div class="stat-sub">Return / Max DD</div>
      </div>
      <div class="tp-stat-card hero-stat risk-stat" style="--stagger:23">
        <div class="stat-icon-wrap" style="background:rgba(251,191,36,0.1);color:var(--tp-warning)">
          <span class="material-symbols-outlined">casino</span>
        </div>
        <div class="stat-label">Kelly Criterion</div>
        <div class="stat-value" :style="{ color: metricColor(riskMetrics.kellyPct, 10, 0) }">{{ riskMetrics.kellyPct.toFixed(1) }}%</div>
        <div class="stat-sub">Optimal bet size</div>
      </div>
      <div class="tp-stat-card hero-stat risk-stat" style="--stagger:24">
        <div class="stat-icon-wrap" style="background:rgba(52,211,153,0.1);color:var(--tp-success)">
          <span class="material-symbols-outlined">swap_horiz</span>
        </div>
        <div class="stat-label">Avg R:R</div>
        <div class="stat-value" :style="{ color: metricColor(riskMetrics.avgRRR, 1.5, 0.8) }">{{ riskMetrics.avgRRR.toFixed(2) }}</div>
        <div class="stat-sub">Win size / Loss size</div>
      </div>
      <div class="tp-stat-card hero-stat risk-stat" style="--stagger:25">
        <div class="stat-icon-wrap" style="background:rgba(244,63,94,0.1);color:#f43f5e">
          <span class="material-symbols-outlined">restart_alt</span>
        </div>
        <div class="stat-label">Recovery Factor</div>
        <div class="stat-value" :style="{ color: metricColor(riskMetrics.recoveryFactor, 1, 0) }">{{ riskMetrics.recoveryFactor.toFixed(2) }}</div>
        <div class="stat-sub">Net P&L / Max DD</div>
      </div>
    </div>

    <!-- ═══ DIRECTION + STREAK ROW ═══ -->
    <div class="detail-row" style="margin-bottom:0.875rem">
      <!-- Direction Analysis -->
      <div class="tp-card table-card" style="--stagger:26">
        <div class="card-accent" style="background:linear-gradient(90deg,#3b82f6,transparent 60%)"></div>
        <h3 class="card-title table-card-title">
          <span class="material-symbols-outlined" style="font-size:18px">swap_vert</span>
          Direction Analysis
        </h3>
        <div class="dir-grid">
          <div class="dir-card dir-buy">
            <div class="dir-label">BUY</div>
            <div class="dir-stats">
              <span class="dir-count">{{ directionData.buy.count }} trades</span>
              <span class="dir-wr" :style="{ color: wrColor(directionData.buy.wr) }">{{ directionData.buy.wr.toFixed(1) }}% WR</span>
            </div>
            <div class="dir-pnl" :class="pnlClass(directionData.buy.pnl)">{{ fmtPnl(directionData.buy.pnl) }}</div>
            <div class="dir-avg">{{ fmtPnl(directionData.buy.avg) }}/trade</div>
            <div class="dir-bar">
              <div class="dir-bar-fill dir-bar-win" :style="{ width: directionData.buy.wr + '%' }"></div>
            </div>
          </div>
          <div class="dir-card dir-sell">
            <div class="dir-label">SELL</div>
            <div class="dir-stats">
              <span class="dir-count">{{ directionData.sell.count }} trades</span>
              <span class="dir-wr" :style="{ color: wrColor(directionData.sell.wr) }">{{ directionData.sell.wr.toFixed(1) }}% WR</span>
            </div>
            <div class="dir-pnl" :class="pnlClass(directionData.sell.pnl)">{{ fmtPnl(directionData.sell.pnl) }}</div>
            <div class="dir-avg">{{ fmtPnl(directionData.sell.avg) }}/trade</div>
            <div class="dir-bar">
              <div class="dir-bar-fill dir-bar-win" :style="{ width: directionData.sell.wr + '%' }"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Streak Analysis -->
      <div class="tp-card table-card" style="--stagger:27">
        <div class="card-accent" style="background:linear-gradient(90deg,#f59e0b,transparent 60%)"></div>
        <h3 class="card-title table-card-title">
          <span class="material-symbols-outlined" style="font-size:18px">local_fire_department</span>
          Streak Analysis
        </h3>
        <div class="streak-grid">
          <div class="streak-item">
            <span class="streak-label">Current</span>
            <span class="streak-val" :class="streakData.currentType === 'win' ? 'val-pos' : 'val-neg'">
              {{ streakData.current }} {{ streakData.currentType === 'win' ? 'W' : 'L' }}
            </span>
          </div>
          <div class="streak-item">
            <span class="streak-label">Max Win Streak</span>
            <span class="streak-val val-pos">{{ streakData.maxWin }}</span>
          </div>
          <div class="streak-item">
            <span class="streak-label">Max Loss Streak</span>
            <span class="streak-val val-neg">{{ streakData.maxLoss }}</span>
          </div>
          <div class="streak-item">
            <span class="streak-label">Avg Win Streak</span>
            <span class="streak-val">{{ streakData.avgWinStreak.toFixed(1) }}</span>
          </div>
          <div class="streak-item">
            <span class="streak-label">Avg Loss Streak</span>
            <span class="streak-val">{{ streakData.avgLossStreak.toFixed(1) }}</span>
          </div>
          <div class="streak-divider"></div>
          <div class="streak-item streak-wide">
            <span class="streak-label">P(Win | prev Win)</span>
            <span class="streak-val" :style="{ color: wrColor(streakData.pWinAfterWin) }">{{ streakData.pWinAfterWin.toFixed(1) }}%</span>
          </div>
          <div class="streak-item streak-wide">
            <span class="streak-label">P(Win | prev Loss)</span>
            <span class="streak-val" :style="{ color: wrColor(streakData.pWinAfterLoss) }">{{ streakData.pWinAfterLoss.toFixed(1) }}%</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ DURATION + MFE/MAE ROW ═══ -->
    <div class="detail-row" style="margin-bottom:0.875rem">
      <!-- Trade Duration -->
      <div class="tp-card table-card" style="--stagger:28">
        <div class="card-accent" style="background:linear-gradient(90deg,#06b6d4,transparent 60%)"></div>
        <h3 class="card-title table-card-title">
          <span class="material-symbols-outlined" style="font-size:18px">timer</span>
          Trade Duration
        </h3>
        <div class="duration-grid">
          <div class="duration-item">
            <span class="duration-label">Avg All</span>
            <span class="duration-val">{{ fmtDuration(durationData.avgAll) }}</span>
          </div>
          <div class="duration-item">
            <span class="duration-label">Avg Winner</span>
            <span class="duration-val val-pos">{{ fmtDuration(durationData.avgWinner) }}</span>
          </div>
          <div class="duration-item">
            <span class="duration-label">Avg Loser</span>
            <span class="duration-val val-neg">{{ fmtDuration(durationData.avgLoser) }}</span>
          </div>
          <div class="duration-item">
            <span class="duration-label">Longest Win</span>
            <span class="duration-val">{{ fmtDuration(durationData.longestWin) }}</span>
          </div>
          <div class="duration-item">
            <span class="duration-label">Longest Loss</span>
            <span class="duration-val">{{ fmtDuration(durationData.longestLoss) }}</span>
          </div>
        </div>
      </div>

      <!-- MFE/MAE Analysis -->
      <div class="tp-card table-card" style="--stagger:29" v-if="mfeMaeData">
        <div class="card-accent" style="background:linear-gradient(90deg,#f43f5e,transparent 60%)"></div>
        <h3 class="card-title table-card-title">
          <span class="material-symbols-outlined" style="font-size:18px">analytics</span>
          MFE / MAE Analysis
          <span class="heatmap-sub">{{ mfeMaeData.mfeCount }} trades</span>
        </h3>
        <div class="mfe-grid">
          <div class="mfe-item">
            <span class="mfe-label">Avg MFE (Winners)</span>
            <span class="mfe-val val-pos">&euro;{{ mfeMaeData.avgMfeWin.toFixed(2) }}</span>
          </div>
          <div class="mfe-item">
            <span class="mfe-label">Avg MFE (Losers)</span>
            <span class="mfe-val">&euro;{{ mfeMaeData.avgMfeLoss.toFixed(2) }}</span>
          </div>
          <div class="mfe-item">
            <span class="mfe-label">Avg MAE (Winners)</span>
            <span class="mfe-val">&euro;{{ mfeMaeData.avgMaeWin.toFixed(2) }}</span>
          </div>
          <div class="mfe-item">
            <span class="mfe-label">Avg MAE (Losers)</span>
            <span class="mfe-val val-neg">&euro;{{ mfeMaeData.avgMaeLoss.toFixed(2) }}</span>
          </div>
          <div class="mfe-divider"></div>
          <div class="mfe-item mfe-wide">
            <span class="mfe-label">Edge Ratio (MFE/MAE)</span>
            <span class="mfe-val" :style="{ color: metricColor(mfeMaeData.edgeRatio, 1.5, 0.8) }">{{ mfeMaeData.edgeRatio.toFixed(2) }}</span>
          </div>
          <div class="mfe-item mfe-wide">
            <span class="mfe-label">Capture Efficiency</span>
            <span class="mfe-val" :style="{ color: metricColor(mfeMaeData.avgCapture, 50, 25) }">{{ mfeMaeData.avgCapture.toFixed(1) }}%</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ DAY-OF-WEEK HEATMAP ═══ -->
    <div class="tp-card heatmap-card" style="--stagger:30">
      <div class="card-accent" style="background:linear-gradient(90deg,#a855f7,transparent 60%)"></div>
      <h3 class="card-title table-card-title">
        <span class="material-symbols-outlined" style="font-size:18px">date_range</span>
        Day-of-Week Performance
        <span class="heatmap-sub">UTC entry time</span>
      </h3>
      <div class="dow-grid">
        <div
          v-for="d in dayOfWeekData" :key="d.name"
          class="dow-cell"
          :class="{ 'cell-positive': d.pnl > 0, 'cell-negative': d.pnl < 0 }"
          :style="{ '--cell-intensity': d.intensity }"
        >
          <span class="dow-name">{{ d.name }}</span>
          <span class="dow-pnl" :class="pnlClass(d.pnl)">{{ d.pnl >= 0 ? '+' : '' }}&euro;{{ d.pnl.toFixed(0) }}</span>
          <span class="dow-wr" :style="{ color: wrColor(d.wr) }">{{ d.count ? d.wr.toFixed(0) + '%' : '—' }}</span>
          <span class="dow-count">{{ d.count }}t &middot; &euro;{{ d.avg.toFixed(2) }}/t</span>
        </div>
      </div>
    </div>

    <!-- ═══ SESSION + CLOSING REASON ROW ═══ -->
    <div class="detail-row" style="margin-bottom:0.875rem">
      <!-- Session Performance -->
      <div class="tp-card table-card" style="--stagger:31">
        <div class="card-accent" style="background:linear-gradient(90deg,#10b981,transparent 60%)"></div>
        <h3 class="card-title table-card-title">
          <span class="material-symbols-outlined" style="font-size:18px">public</span>
          Session Performance
        </h3>
        <div class="table-scroll">
          <table class="tp-table">
            <thead>
              <tr>
                <th>Session</th>
                <th class="num">Trades</th>
                <th class="num">W / L</th>
                <th style="min-width:100px">Win Rate</th>
                <th class="num">Total P&L</th>
                <th class="num">Avg/Trade</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in sessionData" :key="s.name">
                <td class="td-bold">{{ s.name }}</td>
                <td class="num">{{ s.count }}</td>
                <td class="num"><span class="val-pos">{{ s.wins }}</span><span class="td-dim"> / </span><span class="val-neg">{{ s.losses }}</span></td>
                <td>
                  <div class="wr-bar">
                    <div class="wr-track"><div class="wr-fill" :style="{ width: s.wr + '%', background: wrColor(s.wr) }"></div></div>
                    <span class="wr-val" :style="{ color: wrColor(s.wr) }">{{ s.wr.toFixed(0) }}%</span>
                  </div>
                </td>
                <td class="num" :class="pnlClass(s.pnl)">{{ fmtPnl(s.pnl) }}</td>
                <td class="num" :class="pnlClass(s.avg)">{{ fmtPnl(s.avg) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Closing Reason -->
      <div class="tp-card table-card" style="--stagger:32">
        <div class="card-accent" style="background:linear-gradient(90deg,#ef4444,transparent 60%)"></div>
        <h3 class="card-title table-card-title">
          <span class="material-symbols-outlined" style="font-size:18px">exit_to_app</span>
          Exit Reason Breakdown
        </h3>
        <div class="table-scroll">
          <table class="tp-table">
            <thead>
              <tr>
                <th>Reason</th>
                <th class="num">Trades</th>
                <th style="min-width:100px">Win Rate</th>
                <th class="num">Total P&L</th>
                <th class="num">Avg/Trade</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in closingReasonData" :key="r.reason">
                <td class="td-bold">{{ r.reason }}</td>
                <td class="num">{{ r.count }}</td>
                <td>
                  <div class="wr-bar">
                    <div class="wr-track"><div class="wr-fill" :style="{ width: r.wr + '%', background: wrColor(r.wr) }"></div></div>
                    <span class="wr-val" :style="{ color: wrColor(r.wr) }">{{ r.wr.toFixed(0) }}%</span>
                  </div>
                </td>
                <td class="num" :class="pnlClass(r.pnl)">{{ fmtPnl(r.pnl) }}</td>
                <td class="num" :class="pnlClass(r.avg)">{{ fmtPnl(r.avg) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ═══ POSITION MANAGEMENT STATS ═══ -->
    <div class="tp-card table-card" style="--stagger:33">
      <div class="card-accent" style="background:linear-gradient(90deg,#64748b,transparent 60%)"></div>
      <h3 class="card-title table-card-title">
        <span class="material-symbols-outlined" style="font-size:18px">tune</span>
        Position Management
      </h3>
      <div class="mgmt-grid">
        <div class="mgmt-section">
          <h4 class="mgmt-section-title">Breakeven Moves</h4>
          <div class="mgmt-row">
            <span>Total</span><span class="mgmt-val">{{ managementData.be.count }}</span>
          </div>
          <div class="mgmt-row">
            <span>Win Rate</span><span class="mgmt-val" :style="{ color: wrColor(managementData.be.wr) }">{{ managementData.be.wr.toFixed(0) }}%</span>
          </div>
          <div class="mgmt-row">
            <span>P&L</span><span class="mgmt-val" :class="pnlClass(managementData.be.pnl)">{{ fmtPnl(managementData.be.pnl) }}</span>
          </div>
        </div>
        <div class="mgmt-section">
          <h4 class="mgmt-section-title">Partial Closes</h4>
          <div class="mgmt-row">
            <span>Total</span><span class="mgmt-val">{{ managementData.partial.count }}</span>
          </div>
          <div class="mgmt-row">
            <span>Win Rate</span><span class="mgmt-val" :style="{ color: wrColor(managementData.partial.wr) }">{{ managementData.partial.wr.toFixed(0) }}%</span>
          </div>
          <div class="mgmt-row">
            <span>P&L</span><span class="mgmt-val" :class="pnlClass(managementData.partial.pnl)">{{ fmtPnl(managementData.partial.pnl) }}</span>
          </div>
        </div>
        <div class="mgmt-section">
          <h4 class="mgmt-section-title">Volatility (ATR)</h4>
          <div class="mgmt-row">
            <span>Avg ATR</span><span class="mgmt-val">{{ managementData.avgAtr.toFixed(5) }}</span>
          </div>
          <div class="mgmt-row">
            <span>ATR (Winners)</span><span class="mgmt-val val-pos">{{ managementData.avgAtrWin.toFixed(5) }}</span>
          </div>
          <div class="mgmt-row">
            <span>ATR (Losers)</span><span class="mgmt-val val-neg">{{ managementData.avgAtrLoss.toFixed(5) }}</span>
          </div>
        </div>
        <div class="mgmt-section" v-if="managementData.volCount > 0">
          <h4 class="mgmt-section-title">Position Sizing</h4>
          <div class="mgmt-row">
            <span>Avg Size</span><span class="mgmt-val">&euro;{{ managementData.avgSize.toFixed(0) }}</span>
          </div>
          <div class="mgmt-row">
            <span>Trades w/ data</span><span class="mgmt-val">{{ managementData.volCount }}</span>
          </div>
        </div>
      </div>
    </div>

    </template>
  </div>
</template>

<style scoped>
/* ══════════════════════════════════════════════════
   PERFORMANCE ANALYTICS — Intelligence Briefing
   ══════════════════════════════════════════════════ */

:global(.container:has(.perf-page)) {
  max-width: 1600px !important;
}

.perf-page {
  max-width: 1600px;
  padding: 0.75rem 1.25rem 3rem;
}

/* ═══ STAGGER REVEAL ═══ */
@keyframes perf-enter {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}

.hero-stat, .risk-stat, .chart-card, .table-card, .heatmap-card, .insight-card, .sparkline-card, .perf-header, .risk-grid {
  animation: perf-enter 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
  animation-delay: calc(var(--stagger, 0) * 0.05s);
}

/* ═══ LOADING ═══ */
.perf-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  min-height: 60vh;
  color: var(--tp-text-dim);
  font-size: 0.9rem;
}

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 1s linear infinite; }

/* ═══ HEADER ═══ */
.perf-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 1.25rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--tp-border);
}

.perf-header h1 {
  font-size: 1.6rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  margin: 0;
}

.perf-subtitle {
  font-size: 0.78rem;
  color: var(--tp-text-dim);
  margin-top: 2px;
  display: block;
}

.perf-live-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--tp-success);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.pulse-dot-sm {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--tp-success);
  animation: pulse-glow 2s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(52,211,153,0.5); }
  50% { opacity: 0.6; box-shadow: 0 0 0 4px rgba(52,211,153,0); }
}

/* ═══ HERO STATS ═══ */
.hero-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0.875rem;
  margin-bottom: 1.25rem;
}

.hero-stat {
  position: relative;
  padding: 1.1rem 1rem;
}

.stat-icon-wrap {
  width: 32px; height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 0.6rem;
}

.stat-icon-wrap .material-symbols-outlined { font-size: 18px; }

.stat-icon-pnl { background: rgba(52,211,153,0.1); color: var(--tp-success); }
.stat-icon-wr { background: rgba(59,130,246,0.1); color: var(--tp-primary); }
.stat-icon-dd { background: rgba(248,113,113,0.1); color: var(--tp-danger); }
.stat-icon-pf { background: rgba(251,191,36,0.1); color: var(--tp-warning); }
.stat-icon-best { background: rgba(52,211,153,0.1); color: var(--tp-success); }
.stat-icon-worst { background: rgba(248,113,113,0.1); color: var(--tp-danger); }

.hero-stat .stat-label {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--tp-text-dim);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.2rem;
}

.hero-stat .stat-value {
  font-size: 1.35rem;
  font-weight: 800;
  color: var(--tp-text);
  letter-spacing: -0.02em;
}

.hero-stat .stat-sub {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
  margin-top: 0.15rem;
}

/* ═══ CARD ACCENTS ═══ */
.card-accent {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  border-radius: var(--tp-radius) var(--tp-radius) 0 0;
  pointer-events: none;
}

.accent-equity { background: linear-gradient(90deg, var(--tp-success), transparent 60%); }
.accent-daily { background: linear-gradient(90deg, var(--tp-primary), transparent 60%); }
.accent-table { background: linear-gradient(90deg, var(--tp-primary), transparent 60%); }
.accent-symbol { background: linear-gradient(90deg, #f59e0b, transparent 60%); }
.accent-strat { background: linear-gradient(90deg, #8b5cf6, transparent 60%); }
.accent-heatmap { background: linear-gradient(90deg, #06b6d4, transparent 60%); }
.accent-spark { background: linear-gradient(90deg, #64748b, transparent 60%); }

/* ═══ CHARTS ═══ */
.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.875rem;
  margin-bottom: 0.875rem;
}

.chart-card {
  position: relative;
  padding: 1.1rem;
}

.chart-card .card-title {
  font-size: 0.85rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.75rem;
}

.perf-canvas {
  width: 100%;
  display: block;
}

/* ═══ TABLES ═══ */
.table-card {
  position: relative;
  padding: 1.1rem;
  margin-bottom: 0.875rem;
}

.table-card-title {
  font-size: 0.85rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.75rem;
}

.table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.num { text-align: right; font-variant-numeric: tabular-nums; }
.td-bold { font-weight: 700; }
.td-dim { color: var(--tp-text-dim); }

.td-strat {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.82rem;
}

.val-pos { color: var(--tp-success) !important; }
.val-neg { color: var(--tp-danger) !important; }

.row-blow { background: rgba(248,113,113,0.04); }

/* Win rate bars */
.wr-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.wr-track {
  flex: 1;
  height: 5px;
  background: var(--tp-bg-hover);
  border-radius: 3px;
  overflow: hidden;
}

.wr-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.5s ease;
}

.wr-val {
  width: 34px;
  text-align: right;
  font-size: 0.75rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

/* ═══ DETAIL ROW ═══ */
.detail-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.875rem;
  align-items: start;
}

.detail-row .table-card { margin-bottom: 0; }

/* ═══ HEATMAP ═══ */
.heatmap-card {
  position: relative;
  padding: 1.1rem;
  margin-top: 0.875rem;
  margin-bottom: 0.875rem;
}

.heatmap-sub {
  font-size: 0.65rem;
  font-weight: 500;
  color: var(--tp-text-dim);
  margin-left: 4px;
}

.heatmap-grid {
  display: grid;
  grid-template-columns: repeat(24, 1fr);
  gap: 4px;
}

.heatmap-cell {
  background: var(--tp-bg-hover);
  border-radius: 6px;
  padding: 8px 2px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  cursor: default;
}

.heatmap-cell:hover {
  transform: translateY(-2px);
  z-index: 2;
}

.cell-positive {
  background: rgba(52,211,153, calc(0.06 + var(--cell-intensity, 0) * 0.14));
}

.cell-negative {
  background: rgba(248,113,113, calc(0.06 + var(--cell-intensity, 0) * 0.14));
}

.cell-best {
  box-shadow: inset 0 0 0 1px var(--tp-success);
}

.cell-worst {
  box-shadow: inset 0 0 0 1px var(--tp-danger);
}

.cell-hour {
  font-size: 0.65rem;
  font-weight: 700;
  color: var(--tp-text-dim);
  letter-spacing: 0.02em;
}

.cell-pnl {
  font-size: 0.7rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.cell-wr {
  font-size: 0.6rem;
  color: var(--tp-text-dim);
}

.cell-count {
  font-size: 0.55rem;
  color: var(--tp-text-dim);
  opacity: 0.7;
}

.heatmap-legend {
  display: flex;
  gap: 1rem;
  margin-top: 0.75rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--tp-border);
}

.heatmap-legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.7rem;
  color: var(--tp-text-dim);
}

.legend-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
}

/* ═══ INSIGHTS ═══ */
.insights-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 0.75rem;
  margin-bottom: 0.875rem;
}

.insight-card {
  display: flex;
  gap: 0.75rem;
  padding: 1rem 1.1rem;
  border-radius: var(--tp-radius);
  border: 1px solid var(--tp-border);
  background: var(--tp-bg-glass);
  backdrop-filter: var(--tp-glass-blur);
  -webkit-backdrop-filter: var(--tp-glass-blur);
}

.insight-success {
  border-left: 3px solid var(--tp-success);
}

.insight-danger {
  border-left: 3px solid var(--tp-danger);
}

.insight-warning {
  border-left: 3px solid var(--tp-warning);
}

.insight-icon {
  width: 32px; height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.insight-success .insight-icon { background: rgba(52,211,153,0.1); color: var(--tp-success); }
.insight-danger .insight-icon { background: rgba(248,113,113,0.1); color: var(--tp-danger); }
.insight-warning .insight-icon { background: rgba(251,191,36,0.1); color: var(--tp-warning); }

.insight-icon .material-symbols-outlined { font-size: 18px; }

.insight-title {
  font-size: 0.82rem;
  font-weight: 700;
  margin-bottom: 2px;
}

.insight-text {
  font-size: 0.75rem;
  color: var(--tp-text-dim);
  line-height: 1.4;
}

/* ═══ SPARKLINE ═══ */
.sparkline-card {
  position: relative;
  padding: 1.1rem;
}

.sparkline-row {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 64px;
  padding-top: 4px;
}

.spark-bar {
  flex: 1;
  min-width: 3px;
  border-radius: 2px 2px 0 0;
  transition: opacity 0.15s;
}

.spark-win { background: var(--tp-success); opacity: 0.7; }
.spark-loss { background: var(--tp-danger); opacity: 0.7; }
.spark-bar:hover { opacity: 1 !important; }

/* ═══ RISK GRID ═══ */
.risk-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0.875rem;
  margin-bottom: 1.25rem;
  margin-top: 1.25rem;
}

/* ═══ DIRECTION ANALYSIS ═══ */
.dir-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.dir-card {
  padding: 0.9rem;
  border-radius: var(--tp-radius-sm);
  background: var(--tp-bg-hover);
  border: 1px solid var(--tp-border);
}

.dir-label {
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  margin-bottom: 0.5rem;
}

.dir-buy .dir-label { color: var(--tp-success); }
.dir-sell .dir-label { color: var(--tp-danger); }

.dir-stats {
  display: flex;
  justify-content: space-between;
  font-size: 0.72rem;
  margin-bottom: 0.35rem;
}

.dir-count { color: var(--tp-text-dim); }

.dir-wr { font-weight: 700; }

.dir-pnl {
  font-size: 1.15rem;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.dir-avg {
  font-size: 0.7rem;
  color: var(--tp-text-dim);
  margin-bottom: 0.5rem;
}

.dir-bar {
  height: 4px;
  background: var(--tp-border);
  border-radius: 2px;
  overflow: hidden;
}

.dir-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s ease;
}

.dir-bar-win { background: var(--tp-success); }

/* ═══ STREAK ANALYSIS ═══ */
.streak-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.6rem;
}

.streak-item {
  display: flex;
  flex-direction: column;
  padding: 0.6rem 0.7rem;
  background: var(--tp-bg-hover);
  border-radius: var(--tp-radius-sm);
  border: 1px solid var(--tp-border);
}

.streak-wide {
  grid-column: span 1;
}

.streak-divider {
  grid-column: 1 / -1;
  height: 1px;
  background: var(--tp-border);
  margin: 0.1rem 0;
}

.streak-label {
  font-size: 0.65rem;
  color: var(--tp-text-dim);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 0.2rem;
}

.streak-val {
  font-size: 1.1rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

/* ═══ DURATION ═══ */
.duration-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.6rem;
}

.duration-item {
  display: flex;
  flex-direction: column;
  padding: 0.6rem 0.7rem;
  background: var(--tp-bg-hover);
  border-radius: var(--tp-radius-sm);
  border: 1px solid var(--tp-border);
}

.duration-label {
  font-size: 0.65rem;
  color: var(--tp-text-dim);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 0.2rem;
}

.duration-val {
  font-size: 1rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

/* ═══ MFE/MAE ═══ */
.mfe-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.6rem;
}

.mfe-item {
  display: flex;
  flex-direction: column;
  padding: 0.6rem 0.7rem;
  background: var(--tp-bg-hover);
  border-radius: var(--tp-radius-sm);
  border: 1px solid var(--tp-border);
}

.mfe-wide {
  grid-column: span 1;
}

.mfe-divider {
  grid-column: 1 / -1;
  height: 1px;
  background: var(--tp-border);
  margin: 0.1rem 0;
}

.mfe-label {
  font-size: 0.65rem;
  color: var(--tp-text-dim);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 0.2rem;
}

.mfe-val {
  font-size: 1rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

/* ═══ DAY-OF-WEEK ═══ */
.dow-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6px;
}

.dow-cell {
  background: var(--tp-bg-hover);
  border-radius: 8px;
  padding: 12px 6px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  cursor: default;
}

.dow-cell:hover {
  transform: translateY(-2px);
  z-index: 2;
}

.dow-cell.cell-positive {
  background: rgba(52,211,153, calc(0.06 + var(--cell-intensity, 0) * 0.14));
}

.dow-cell.cell-negative {
  background: rgba(248,113,113, calc(0.06 + var(--cell-intensity, 0) * 0.14));
}

.dow-name {
  font-size: 0.75rem;
  font-weight: 800;
  color: var(--tp-text-dim);
  letter-spacing: 0.04em;
}

.dow-pnl {
  font-size: 0.9rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.dow-wr {
  font-size: 0.7rem;
  font-weight: 700;
}

.dow-count {
  font-size: 0.6rem;
  color: var(--tp-text-dim);
  opacity: 0.8;
}

/* ═══ MANAGEMENT GRID ═══ */
.mgmt-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.875rem;
}

.mgmt-section {
  padding: 0.8rem;
  background: var(--tp-bg-hover);
  border-radius: var(--tp-radius-sm);
  border: 1px solid var(--tp-border);
}

.mgmt-section-title {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--tp-text-dim);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0 0 0.5rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--tp-border);
}

.mgmt-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.3rem 0;
  font-size: 0.78rem;
}

.mgmt-row span:first-child {
  color: var(--tp-text-dim);
}

.mgmt-val {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

/* ═══ RESPONSIVE ═══ */
@media (max-width: 1200px) {
  .hero-grid, .risk-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 900px) {
  .hero-grid, .risk-grid { grid-template-columns: repeat(2, 1fr); }
  .charts-row { grid-template-columns: 1fr; }
  .detail-row { grid-template-columns: 1fr; }
  .heatmap-grid { grid-template-columns: repeat(12, 1fr); }
  .dow-grid { grid-template-columns: repeat(4, 1fr); }
  .streak-grid { grid-template-columns: repeat(2, 1fr); }
  .duration-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 640px) {
  .hero-grid, .risk-grid { grid-template-columns: 1fr; }
  .heatmap-grid { grid-template-columns: repeat(8, 1fr); }
  .dow-grid { grid-template-columns: repeat(3, 1fr); }
  .dir-grid { grid-template-columns: 1fr; }
  .mfe-grid { grid-template-columns: 1fr; }
  .perf-header h1 { font-size: 1.2rem; }
}
</style>
