// API wrapper for MT5 Flask and Django backends

const api = {
    getToken() {
        return localStorage.getItem('django_token');
    },

    setToken(token) {
        localStorage.setItem('django_token', token);
    },

    clearToken() {
        localStorage.removeItem('django_token');
    },

    isAuthenticated() {
        return !!this.getToken();
    },

    async _fetch(url, options = {}) {
        const defaults = {
            headers: { 'Content-Type': 'application/json' },
        };
        const merged = { ...defaults, ...options };
        merged.headers = { ...defaults.headers, ...options.headers };

        const resp = await fetch(url, merged);
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.error || data.detail || `HTTP ${resp.status}`);
        }
        return data;
    },

    // --- MT5 Flask API (no auth) ---

    mt5(path, options) {
        return this._fetch(`/api/mt5/${path}`, options);
    },

    getPositions(magic) {
        const qs = magic != null ? `?magic=${magic}` : '';
        return this.mt5(`get_positions${qs}`);
    },

    positionsTotal() {
        return this.mt5('positions_total');
    },

    symbolInfoTick(symbol) {
        return this.mt5(`symbol_info_tick/${encodeURIComponent(symbol)}`);
    },

    symbolInfo(symbol) {
        return this.mt5(`symbol_info/${encodeURIComponent(symbol)}`);
    },

    closePosition(position) {
        return this.mt5('close_position', {
            method: 'POST',
            body: JSON.stringify({ position }),
        });
    },

    closeAllPositions(orderType, magic) {
        const body = {};
        if (orderType) body.order_type = orderType;
        if (magic != null) body.magic = magic;
        return this.mt5('close_all_positions', {
            method: 'POST',
            body: JSON.stringify(body),
        });
    },

    modifySlTp(position, sl, tp) {
        return this.mt5('modify_sl_tp', {
            method: 'POST',
            body: JSON.stringify({ position, sl, tp }),
        });
    },

    sendOrder(orderData) {
        return this.mt5('order', {
            method: 'POST',
            body: JSON.stringify(orderData),
        });
    },

    fetchDataPos(symbol, timeframe = 'M1', numBars = 100) {
        return this.mt5(`fetch_data_pos?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&num_bars=${numBars}`);
    },

    fetchDataRange(symbol, timeframe, start, end) {
        const params = new URLSearchParams({ symbol, timeframe, start, end });
        return this.mt5(`fetch_data_range?${params}`);
    },

    historyDealsGet(fromDate, toDate, position) {
        const params = new URLSearchParams({ from_date: fromDate, to_date: toDate, position });
        return this.mt5(`history_deals_get?${params}`);
    },

    historyOrdersGet(ticket) {
        return this.mt5(`history_orders_get?ticket=${ticket}`);
    },

    getDealFromTicket(ticket) {
        return this.mt5(`get_deal_from_ticket?ticket=${ticket}`);
    },

    getOrderFromTicket(ticket) {
        return this.mt5(`get_order_from_ticket?ticket=${ticket}`);
    },

    getSymbols() {
        return this.mt5('symbols_get');
    },

    // --- Django API (token auth) ---

    django(path, options = {}) {
        const token = this.getToken();
        if (token) {
            options.headers = { ...options.headers, Authorization: `Token ${token}` };
        }
        return this._fetch(`/api/django/${path}`, options);
    },

    async login(username, password) {
        // Try DRF's obtain_auth_token first, fall back to session auth
        try {
            const data = await this._fetch('/api/django/api-token-auth/', {
                method: 'POST',
                body: JSON.stringify({ username, password }),
            });
            this.setToken(data.token);
            return data;
        } catch {
            // If token auth endpoint doesn't exist, try session login
            const data = await this._fetch('/api/django/v1/send_market_order/', {
                method: 'OPTIONS',
            }).catch(() => null);
            // Store credentials for basic auth fallback
            const token = btoa(`${username}:${password}`);
            localStorage.setItem('django_basic', token);
            return { token: 'basic' };
        }
    },

    djangoSendMarketOrder(orderData) {
        const headers = {};
        const basic = localStorage.getItem('django_basic');
        if (basic) headers.Authorization = `Basic ${basic}`;
        return this.django('v1/send_market_order/', {
            method: 'POST',
            body: JSON.stringify(orderData),
            headers,
        });
    },

    djangoModifySlTp(data) {
        const headers = {};
        const basic = localStorage.getItem('django_basic');
        if (basic) headers.Authorization = `Basic ${basic}`;
        return this.django('v1/modify_sl_tp/', {
            method: 'POST',
            body: JSON.stringify(data),
            headers,
        });
    },

    // --- Strategy API ---

    getStrategies() {
        return this.django('v1/strategies/');
    },

    activateStrategy(id) {
        const headers = {};
        const basic = localStorage.getItem('django_basic');
        if (basic) headers.Authorization = `Basic ${basic}`;
        return this.django(`v1/strategies/${id}/activate/`, {
            method: 'POST',
            headers,
        });
    },

    runBacktest(id) {
        const headers = {};
        const basic = localStorage.getItem('django_basic');
        if (basic) headers.Authorization = `Basic ${basic}`;
        return this.django(`v1/strategies/${id}/backtest/`, {
            method: 'POST',
            headers,
        });
    },

    getBacktestResults(id) {
        return this.django(`v1/strategies/${id}/backtest-results/`);
    },
};

export default api;
window.api = api;
