// Dashboard overview: account snapshot + positions summary + market sessions

const SESSIONS = [
    // Forex sessions (UTC hours)
    { name: 'Sydney',    openUTC: 22, closeUTC: 7,  color: '#42a5f5', assets: 'AUD, NZD pairs' },
    { name: 'Tokyo',     openUTC: 0,  closeUTC: 9,  color: '#ab47bc', assets: 'JPY pairs' },
    { name: 'London',    openUTC: 8,  closeUTC: 17, color: '#26a69a', assets: 'EUR, GBP, CHF pairs' },
    { name: 'New York',  openUTC: 13, closeUTC: 22, color: '#ef5350', assets: 'USD, CAD pairs' },
    // Commodity sessions (UTC hours, Mon-Fri)
    { name: 'COMEX',  openUTC: 23, closeUTC: 22, color: '#ffa726', assets: 'XAUUSD, XAGUSD, XAUEUR', nearly24h: true, breakStartUTC: 22, breakEndUTC: 23 },
    { name: 'NYMEX',  openUTC: 23, closeUTC: 22, color: '#8d6e63', assets: 'NG, WTI, BRN', nearly24h: true, breakStartUTC: 22, breakEndUTC: 23 },
];

function isSessionOpen(session, nowUTC) {
    const h = nowUTC.getUTCHours();
    const m = nowUTC.getUTCMinutes();
    const now = h + m / 60;
    const day = nowUTC.getUTCDay(); // 0=Sun, 6=Sat

    // Forex closed on weekends (Sat 00:00 to Sun 22:00 UTC roughly)
    if (!session.nearly24h && (day === 6 || (day === 0 && now < 22))) {
        return false;
    }
    // Commodities closed on weekends (Sat 00:00 to Sun 23:00 UTC)
    if (session.nearly24h && (day === 6 || (day === 0 && now < 23))) {
        return false;
    }

    if (session.nearly24h) {
        // Open 23:00 Sun - 22:00 Fri, with 1h daily break 22:00-23:00
        if (day === 5 && now >= 22) return false; // Friday after 22:00 = closed
        if (now >= session.breakStartUTC && now < session.breakEndUTC) return false;
        return true;
    }

    if (session.openUTC < session.closeUTC) {
        return now >= session.openUTC && now < session.closeUTC;
    }
    // Wraps midnight (e.g. Sydney 22:00-07:00)
    return now >= session.openUTC || now < session.closeUTC;
}

function formatSessionTime(hour) {
    return `${String(hour).padStart(2, '0')}:00`;
}

function getLocalTime(utcHour) {
    const d = new Date();
    d.setUTCHours(utcHour, 0, 0, 0);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function renderSessionBar(session, nowUTC) {
    const open = isSessionOpen(session, nowUTC);
    const statusDot = open
        ? '<span style="color:#26a69a;font-size:1.1em;">&#9679;</span>'
        : '<span style="color:#555;font-size:1.1em;">&#9679;</span>';

    // Calculate bar position on 24h timeline
    let barLeft, barWidth;
    if (session.nearly24h) {
        // Nearly 24h sessions: show as full bar with a small gap for the break
        barLeft = 0;
        barWidth = 100;
    } else if (session.openUTC < session.closeUTC) {
        barLeft = (session.openUTC / 24) * 100;
        barWidth = ((session.closeUTC - session.openUTC) / 24) * 100;
    } else {
        // Wraps midnight — render as two bars via CSS, but approximate with one
        barLeft = (session.openUTC / 24) * 100;
        barWidth = ((24 - session.openUTC + session.closeUTC) / 24) * 100;
    }

    const timeLabel = session.nearly24h
        ? `23:00 - 22:00 UTC (1h break)`
        : `${formatSessionTime(session.openUTC)} - ${formatSessionTime(session.closeUTC)} UTC`;

    const localLabel = session.nearly24h
        ? `${getLocalTime(23)} - ${getLocalTime(22)} local`
        : `${getLocalTime(session.openUTC)} - ${getLocalTime(session.closeUTC)} local`;

    return `
        <div class="session-row">
            <div class="session-label">
                ${statusDot}
                <strong style="color:${session.color}">${session.name}</strong>
                <span class="session-status">${open ? 'OPEN' : 'CLOSED'}</span>
            </div>
            <div class="session-timeline">
                <div class="session-bar" style="left:${barLeft}%;width:${barWidth}%;background:${session.color};opacity:${open ? 0.9 : 0.25};"></div>
                <div class="session-now" style="left:${(nowUTC.getUTCHours() + nowUTC.getUTCMinutes() / 60) / 24 * 100}%"></div>
            </div>
            <div class="session-meta">
                <small>${timeLabel}</small>
                <small class="session-local">${localLabel}</small>
                <small class="session-assets">${session.assets}</small>
            </div>
        </div>
    `;
}

function renderMarketSessions() {
    const now = new Date();
    const utcStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' });

    // Hour markers for timeline
    const hours = [0, 3, 6, 9, 12, 15, 18, 21];
    const hourMarkers = hours.map(h =>
        `<span style="left:${(h / 24) * 100}%">${String(h).padStart(2, '0')}</span>`
    ).join('');

    return `
        <article id="market-sessions">
            <header>Market Sessions <small style="float:right;">UTC: ${utcStr}</small></header>
            <div class="sessions-container">
                <div class="timeline-hours">${hourMarkers}</div>
                ${SESSIONS.map(s => renderSessionBar(s, now)).join('')}
            </div>
        </article>
    `;
}

export default async function render(app) {
    app.innerHTML = `
        <h2>Account Overview</h2>
        <div class="grid">
            <article id="positions-summary">
                <header>Open Positions</header>
                <p aria-busy="true">Loading...</p>
            </article>
            <article id="tick-info">
                <header>Market Tick (EURUSD)</header>
                <p aria-busy="true">Loading...</p>
            </article>
        </div>
        ${renderMarketSessions()}
        <article id="positions-table-card">
            <header>Active Positions</header>
            <div id="dash-positions"></div>
        </article>
    `;

    let interval;

    async function refresh() {
        try {
            const [positions, tick] = await Promise.allSettled([
                window.api.getPositions(),
                window.api.symbolInfoTick('EURUSD'),
            ]);

            // Positions summary
            const summaryEl = document.getElementById('positions-summary');
            if (positions.status === 'fulfilled') {
                const pos = Array.isArray(positions.value) ? positions.value : (positions.value.positions || []);
                const totalProfit = pos.reduce((s, p) => s + (p.profit || 0), 0);
                const totalSwap = pos.reduce((s, p) => s + (p.swap || 0), 0);
                summaryEl.innerHTML = `
                    <header>Open Positions</header>
                    <dl>
                        <dt>Count</dt><dd>${pos.length}</dd>
                        <dt>Total Profit</dt><dd class="${totalProfit >= 0 ? 'profit' : 'loss'}">${totalProfit.toFixed(2)}</dd>
                        <dt>Total Swap</dt><dd>${totalSwap.toFixed(2)}</dd>
                    </dl>
                `;
            } else {
                summaryEl.innerHTML = `<header>Open Positions</header><p>Failed to load</p>`;
            }

            // Tick info
            const tickEl = document.getElementById('tick-info');
            if (tick.status === 'fulfilled') {
                const t = tick.value;
                tickEl.innerHTML = `
                    <header>Market Tick (EURUSD)</header>
                    <dl>
                        <dt>Bid</dt><dd>${t.bid}</dd>
                        <dt>Ask</dt><dd>${t.ask}</dd>
                        <dt>Spread</dt><dd>${((t.ask - t.bid) * 100000).toFixed(1)} pts</dd>
                        <dt>Last</dt><dd>${t.last || 'N/A'}</dd>
                    </dl>
                `;
            } else {
                tickEl.innerHTML = `<header>Market Tick</header><p>Failed to load</p>`;
            }

            // Update market sessions (live clock)
            const sessionsEl = document.getElementById('market-sessions');
            if (sessionsEl) {
                const parent = sessionsEl.parentElement;
                const newHtml = renderMarketSessions();
                const temp = document.createElement('div');
                temp.innerHTML = newHtml;
                parent.replaceChild(temp.firstElementChild, sessionsEl);
            }

            // Positions table
            const tableEl = document.getElementById('dash-positions');
            if (positions.status === 'fulfilled') {
                const pos = Array.isArray(positions.value) ? positions.value : (positions.value.positions || []);
                if (pos.length === 0) {
                    tableEl.innerHTML = '<p>No open positions</p>';
                } else {
                    tableEl.innerHTML = `
                        <figure>
                        <table>
                            <thead>
                                <tr>
                                    <th>Ticket</th><th>Symbol</th><th>Type</th>
                                    <th>Volume</th><th>Open Price</th><th>Current</th>
                                    <th>SL</th><th>TP</th><th>Profit</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${pos.map(p => `
                                    <tr>
                                        <td>${p.ticket}</td>
                                        <td>${p.symbol}</td>
                                        <td>${p.type === 0 ? 'BUY' : 'SELL'}</td>
                                        <td>${p.volume}</td>
                                        <td>${p.price_open}</td>
                                        <td>${p.price_current}</td>
                                        <td>${p.sl || '-'}</td>
                                        <td>${p.tp || '-'}</td>
                                        <td class="${p.profit >= 0 ? 'profit' : 'loss'}">${p.profit?.toFixed(2)}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                        </figure>
                    `;
                }
            }
        } catch (err) {
            console.error('Dashboard refresh error:', err);
        }
    }

    await refresh();
    interval = setInterval(refresh, 5000);

    return () => clearInterval(interval);
}
