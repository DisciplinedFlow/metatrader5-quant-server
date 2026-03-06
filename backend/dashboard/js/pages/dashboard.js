// Dashboard overview: account snapshot + positions summary

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
