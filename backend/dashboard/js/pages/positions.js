// Active positions with close & modify actions

export default async function render(app) {
    app.innerHTML = `
        <h2>Active Positions</h2>
        <div style="display:flex;gap:.5rem;margin-bottom:1rem;">
            <button id="refresh-pos" class="outline">Refresh</button>
            <button id="close-all" class="outline secondary">Close All</button>
        </div>
        <div id="positions-content"><p aria-busy="true">Loading...</p></div>

        <dialog id="modify-dialog">
            <article>
                <header>Modify SL/TP</header>
                <form id="modify-form">
                    <input type="hidden" name="ticket">
                    <label>Stop Loss <input type="number" name="sl" step="any"></label>
                    <label>Take Profit <input type="number" name="tp" step="any"></label>
                    <footer>
                        <button type="button" class="secondary" id="modify-cancel">Cancel</button>
                        <button type="submit">Apply</button>
                    </footer>
                </form>
            </article>
        </dialog>
    `;

    let interval;

    async function loadPositions() {
        const el = document.getElementById('positions-content');
        try {
            const data = await window.api.getPositions();
            const positions = Array.isArray(data) ? data : (data.positions || []);

            if (positions.length === 0) {
                el.innerHTML = '<p>No open positions</p>';
                return;
            }

            el.innerHTML = `
                <figure>
                <table>
                    <thead>
                        <tr>
                            <th>Ticket</th><th>Symbol</th><th>Type</th>
                            <th>Volume</th><th>Open</th><th>Current</th>
                            <th>SL</th><th>TP</th><th>Swap</th><th>Profit</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${positions.map(p => `
                            <tr>
                                <td>${p.ticket}</td>
                                <td>${p.symbol}</td>
                                <td>${p.type === 0 ? 'BUY' : 'SELL'}</td>
                                <td>${p.volume}</td>
                                <td>${p.price_open}</td>
                                <td>${p.price_current}</td>
                                <td>${p.sl || '-'}</td>
                                <td>${p.tp || '-'}</td>
                                <td>${p.swap?.toFixed(2) || '0.00'}</td>
                                <td class="${p.profit >= 0 ? 'profit' : 'loss'}">${p.profit?.toFixed(2)}</td>
                                <td>
                                    <button class="outline close-btn" data-ticket="${p.ticket}" data-type="${p.type}" data-symbol="${p.symbol}" data-volume="${p.volume}">Close</button>
                                    <button class="outline secondary modify-btn" data-ticket="${p.ticket}" data-sl="${p.sl || ''}" data-tp="${p.tp || ''}">Modify</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
                </figure>
            `;

            // Close buttons
            el.querySelectorAll('.close-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Close this position?')) return;
                    btn.setAttribute('aria-busy', 'true');
                    try {
                        await window.api.closePosition({
                            ticket: parseInt(btn.dataset.ticket),
                            type: parseInt(btn.dataset.type),
                            symbol: btn.dataset.symbol,
                            volume: parseFloat(btn.dataset.volume),
                        });
                        window.toast.success('Position closed');
                        loadPositions();
                    } catch (err) {
                        window.toast.error(`Close failed: ${err.message}`);
                    }
                    btn.removeAttribute('aria-busy');
                });
            });

            // Modify buttons
            el.querySelectorAll('.modify-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const dialog = document.getElementById('modify-dialog');
                    const form = document.getElementById('modify-form');
                    form.ticket.value = btn.dataset.ticket;
                    form.sl.value = btn.dataset.sl;
                    form.tp.value = btn.dataset.tp;
                    dialog.showModal();
                });
            });
        } catch (err) {
            el.innerHTML = `<p>Error: ${err.message}</p>`;
        }
    }

    // Modify dialog handlers
    document.getElementById('modify-cancel').addEventListener('click', () => {
        document.getElementById('modify-dialog').close();
    });

    document.getElementById('modify-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const ticket = parseInt(form.ticket.value);
        const sl = form.sl.value ? parseFloat(form.sl.value) : undefined;
        const tp = form.tp.value ? parseFloat(form.tp.value) : undefined;

        try {
            await window.api.modifySlTp(ticket, sl, tp);
            window.toast.success('SL/TP modified');
            document.getElementById('modify-dialog').close();
            loadPositions();
        } catch (err) {
            window.toast.error(`Modify failed: ${err.message}`);
        }
    });

    document.getElementById('refresh-pos').addEventListener('click', loadPositions);

    document.getElementById('close-all').addEventListener('click', async () => {
        if (!confirm('Close ALL positions?')) return;
        try {
            await window.api.closeAllPositions();
            window.toast.success('All positions closed');
            loadPositions();
        } catch (err) {
            window.toast.error(`Close all failed: ${err.message}`);
        }
    });

    await loadPositions();
    interval = setInterval(loadPositions, 5000);

    return () => clearInterval(interval);
}
