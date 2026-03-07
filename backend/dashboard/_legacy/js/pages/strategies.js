export default async function strategies(container) {
    let refreshInterval = null;

    async function render() {
        let strategiesData = [];
        try {
            const resp = await window.api.getStrategies();
            strategiesData = resp.results || resp;
        } catch (err) {
            container.innerHTML = `<article><h2>Error</h2><p>${err.message}</p></article>`;
            return;
        }

        let html = '<h2>Strategy Management</h2><div class="grid">';

        for (const s of strategiesData) {
            const badge = s.is_active
                ? '<mark>ACTIVE</mark>'
                : '<span class="secondary">Inactive</span>';

            let backtestHtml = '<p>No backtest results yet.</p>';
            if (s.latest_backtest) {
                const bt = s.latest_backtest;
                const passedBadge = bt.passed
                    ? '<mark>PASS</mark>'
                    : '<mark class="secondary">FAIL</mark>';
                const runTime = new Date(bt.run_time).toLocaleString();
                backtestHtml = `
                    <table>
                        <tbody>
                            <tr><td>Status</td><td>${passedBadge}</td></tr>
                            <tr><td>Win Rate</td><td>${(bt.win_rate * 100).toFixed(1)}%</td></tr>
                            <tr><td>Total Trades</td><td>${bt.total_trades}</td></tr>
                            <tr><td>Wins / Losses</td><td>${bt.winning_trades} / ${bt.losing_trades}</td></tr>
                            <tr><td>Total PnL</td><td>${bt.total_pnl != null ? (bt.total_pnl * 100).toFixed(3) + '%' : 'N/A'}</td></tr>
                            <tr><td>Profit Factor</td><td>${bt.profit_factor != null ? bt.profit_factor.toFixed(2) : 'N/A'}</td></tr>
                            <tr><td>Avg Win</td><td>${bt.avg_win != null ? (bt.avg_win * 100).toFixed(3) + '%' : 'N/A'}</td></tr>
                            <tr><td>Avg Loss</td><td>${bt.avg_loss != null ? (bt.avg_loss * 100).toFixed(3) + '%' : 'N/A'}</td></tr>
                            <tr><td>Data Source</td><td>${bt.data_source || 'MT5'}${bt.data_source === 'YAHOO' ? ' (' + bt.period_days + 'd)' : ''}</td></tr>
                            <tr><td>Run Time</td><td>${runTime}</td></tr>
                        </tbody>
                    </table>
                `;
            }

            const activateBtn = s.is_active
                ? ''
                : `<button class="outline" data-activate="${s.id}">Activate</button>`;

            const backtestBtn = s.name === 'SCALPING'
                ? `<button class="outline secondary" data-backtest="${s.id}">Run Backtest</button>`
                : '';

            html += `
                <article>
                    <header>
                        <strong>${s.name}</strong> ${badge}
                    </header>
                    <p>${s.description || ''}</p>
                    <details>
                        <summary>Latest Backtest</summary>
                        ${backtestHtml}
                    </details>
                    <footer>
                        ${activateBtn}
                        ${backtestBtn}
                    </footer>
                </article>
            `;
        }

        html += '</div>';
        container.innerHTML = html;

        // Bind activate buttons
        container.querySelectorAll('[data-activate]').forEach(btn => {
            btn.addEventListener('click', async () => {
                btn.setAttribute('aria-busy', 'true');
                try {
                    await window.api.activateStrategy(btn.dataset.activate);
                    window.toast.success('Strategy activated');
                    await render();
                } catch (err) {
                    window.toast.error(`Activation failed: ${err.message}`);
                } finally {
                    btn.removeAttribute('aria-busy');
                }
            });
        });

        // Bind backtest buttons
        container.querySelectorAll('[data-backtest]').forEach(btn => {
            btn.addEventListener('click', async () => {
                btn.setAttribute('aria-busy', 'true');
                try {
                    await window.api.runBacktest(btn.dataset.backtest);
                    window.toast.success('Backtest started — results will appear shortly');
                } catch (err) {
                    window.toast.error(`Backtest failed: ${err.message}`);
                } finally {
                    btn.removeAttribute('aria-busy');
                }
            });
        });
    }

    await render();
    refreshInterval = setInterval(render, 10000);

    // Cleanup function
    return () => {
        if (refreshInterval) clearInterval(refreshInterval);
    };
}
