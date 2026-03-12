const api = {
  async _fetch(url, options = {}) {
    const defaults = {
      headers: { 'Content-Type': 'application/json' },
    }
    const merged = { ...defaults, ...options }
    merged.headers = { ...defaults.headers, ...options.headers }

    const resp = await fetch(url, merged)
    const data = await resp.json()
    if (!resp.ok) {
      throw new Error(data.error || data.detail || `HTTP ${resp.status}`)
    }
    return data
  },

  // --- MT5 Flask API ---

  mt5(path, options) {
    return this._fetch(`/api/mt5/${path}`, options)
  },

  getPositions(magic) {
    const qs = magic != null ? `?magic=${magic}` : ''
    return this.mt5(`get_positions${qs}`)
  },

  positionsTotal() {
    return this.mt5('positions_total')
  },

  symbolInfoTick(symbol) {
    return this.mt5(`symbol_info_tick/${encodeURIComponent(symbol)}`)
  },

  symbolInfo(symbol) {
    return this.mt5(`symbol_info/${encodeURIComponent(symbol)}`)
  },

  closePosition(position) {
    return this.mt5('close_position', {
      method: 'POST',
      body: JSON.stringify({ position }),
    })
  },

  closeAllPositions(orderType, magic) {
    const body = {}
    if (orderType) body.order_type = orderType
    if (magic != null) body.magic = magic
    return this.mt5('close_all_positions', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },

  modifySlTp(position, sl, tp) {
    return this.mt5('modify_sl_tp', {
      method: 'POST',
      body: JSON.stringify({ position, sl, tp }),
    })
  },

  sendOrder(orderData) {
    return this.mt5('order', {
      method: 'POST',
      body: JSON.stringify(orderData),
    })
  },

  fetchDataPos(symbol, timeframe = 'M1', numBars = 100) {
    return this.mt5(`fetch_data_pos?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&num_bars=${numBars}`)
  },

  fetchDataRange(symbol, timeframe, start, end) {
    const params = new URLSearchParams({ symbol, timeframe, start, end })
    return this.mt5(`fetch_data_range?${params}`)
  },

  historyDealsGet(fromDate, toDate, position) {
    const params = new URLSearchParams({ from_date: fromDate, to_date: toDate, position })
    return this.mt5(`history_deals_get?${params}`)
  },

  historyOrdersGet(ticket) {
    return this.mt5(`history_orders_get?ticket=${ticket}`)
  },

  getDealFromTicket(ticket) {
    return this.mt5(`get_deal_from_ticket?ticket=${ticket}`)
  },

  getOrderFromTicket(ticket) {
    return this.mt5(`get_order_from_ticket?ticket=${ticket}`)
  },

  getSymbols() {
    return this.mt5('symbols_get')
  },

  // --- Django API ---

  django(path, options = {}) {
    return this._fetch(`/api/django/${path}`, options)
  },

  getForexTrades(params = '') {
    return this.django(`v1/trades/?market_type=FOREX&ordering=-entry_time${params}`)
  },

  djangoSendMarketOrder(orderData) {
    return this.django('v1/send_market_order/', {
      method: 'POST',
      body: JSON.stringify(orderData),
    })
  },

  djangoModifySlTp(data) {
    return this.django('v1/modify_sl_tp/', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  // --- Bot Control API ---

  getBotStatus() {
    return this.django('v1/bot/status/')
  },

  setBotPaused(paused) {
    return this.django('v1/bot/status/', {
      method: 'POST',
      body: JSON.stringify({ paused }),
    })
  },

  // --- Strategy API ---

  getStrategies() {
    return this.django('v1/strategies/')
  },

  activateStrategy(id) {
    return this.django(`v1/strategies/${id}/activate/`, {
      method: 'POST',
    })
  },

  runBacktest(id) {
    return this.django(`v1/strategies/${id}/backtest/`, {
      method: 'POST',
    })
  },

  getBacktestResults(id) {
    return this.django(`v1/strategies/${id}/backtest-results/`)
  },

  getBacktestDetail(strategyId, backtestId) {
    return this.django(`v1/strategies/${strategyId}/backtest-results/${backtestId}/`)
  },

  // --- Custom Strategy API ---

  getCustomStrategies(domain) {
    const qs = domain ? `?domain=${domain}` : ''
    return this.django(`v1/custom-strategies/${qs}`)
  },

  getCustomStrategy(id) {
    return this.django(`v1/custom-strategies/${id}/`)
  },

  createCustomStrategy(data) {
    return this.django('v1/custom-strategies/', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  updateCustomStrategy(id, data) {
    return this.django(`v1/custom-strategies/${id}/`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  deleteCustomStrategy(id) {
    return this.django(`v1/custom-strategies/${id}/`, {
      method: 'DELETE',
    })
  },

  runCustomBacktest(id) {
    return this.django(`v1/custom-strategies/${id}/backtest/`, {
      method: 'POST',
    })
  },

  activateCustomStrategy(id) {
    return this.django(`v1/custom-strategies/${id}/activate/`, {
      method: 'POST',
    })
  },

  fetchYahooData(symbol, period = '60d', interval = '5m') {
    return this.django(`v1/yahoo-data/?symbol=${encodeURIComponent(symbol)}&period=${period}&interval=${interval}`)
  },

  // --- Crypto API ---

  getCryptoBotStatus() {
    return this.django('v1/crypto/bot/status/')
  },

  setCryptoBotPaused(paused) {
    return this.django('v1/crypto/bot/status/', {
      method: 'POST',
      body: JSON.stringify({ paused }),
    })
  },

  getCryptoDashboard() {
    return this.django('v1/crypto/dashboard/')
  },

  getCryptoPositions(status) {
    const qs = status ? `?status=${status}` : ''
    return this.django(`v1/crypto/positions/${qs}`)
  },

  getCryptoTrades() {
    return this.django('v1/crypto/trades/')
  },

  getCryptoLogs(lines = 200) {
    return this.django(`v1/crypto/logs/?lines=${lines}`)
  },

  getCryptoBacktests() {
    return this.django('v1/crypto/backtests/')
  },

  getCryptoBacktest(id) {
    return this.django(`v1/crypto/backtests/${id}/`)
  },

  runCryptoBacktest() {
    return this.django('v1/crypto/backtests/run/', {
      method: 'POST',
    })
  },

  getCryptoStrategyConfig() {
    return this.django('v1/crypto/strategy/')
  },

  updateCryptoStrategyConfig(data) {
    return this.django('v1/crypto/strategy/', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  getCryptoWallet() {
    return this.django('v1/crypto/wallet/')
  },

  // --- AI Brain API ---

  getAIBrainStatus() {
    return this.django('v1/ai-brain/')
  },

  setAIBrainEnabled(enabled, runNow = false) {
    return this.django('v1/ai-brain/', {
      method: 'POST',
      body: JSON.stringify({ enabled, run_now: runNow }),
    })
  },

  getAIBrainLogs(lines = 200) {
    return this.django(`v1/ai-brain/logs/?lines=${lines}`)
  },

  // --- Market Pulse API ---

  getMarketPulse() {
    return this.django('v1/market-pulse/')
  },

  // --- ICT Scanner API ---

  getICTScanResults(limit = 10) {
    return this.django(`v1/ict/scan/?limit=${limit}`)
  },

  // --- ML Learning Pipeline API ---

  getMLStatus() {
    return this.django('v1/ml/status/')
  },

  getMLPredictions(limit = 50) {
    return this.django(`v1/ml/predictions/?limit=${limit}`)
  },

  // --- Confluence Scores API ---

  getConfluenceScores(limit = 200) {
    return this.django(`v1/confluence-scores/?limit=${limit}`)
  },

  // --- HMM Regime API ---

  getHMMRegimes() {
    return this.django('v1/hmm-regimes/')
  },
}

export default api
