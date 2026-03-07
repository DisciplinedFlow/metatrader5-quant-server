// Trade history: deals and orders with lookup

export default async function render(app) {
    const now = new Date();
    const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    const fmtDate = d => d.toISOString().slice(0, 16);

    app.innerHTML = `
        <h2>Trade History</h2>
        <article>
            <header>Lookup by Ticket</header>
            <form id="ticket-form" class="grid" style="align-items:end;">
                <label>
                    Ticket
                    <input type="number" name="ticket" required placeholder="Order/Deal ticket">
                </label>
                <label>
                    Type
                    <select name="lookup_type">
                        <option value="deal">Deal</option>
                        <option value="order">Order</option>
                    </select>
                </label>
                <button type="submit">Lookup</button>
            </form>
            <pre id="ticket-result" style="display:none;"></pre>
        </article>

        <article>
            <header>Deals History (by Position)</header>
            <form id="deals-form" class="grid" style="align-items:end;">
                <label>
                    From
                    <input type="datetime-local" name="from_date" value="${fmtDate(weekAgo)}">
                </label>
                <label>
                    To
                    <input type="datetime-local" name="to_date" value="${fmtDate(now)}">
                </label>
                <label>
                    Position
                    <input type="number" name="position" required placeholder="Position ticket">
                </label>
                <button type="submit">Search</button>
            </form>
            <div id="deals-result"></div>
        </article>

        <article>
            <header>Orders History (by Ticket)</header>
            <form id="orders-form" class="grid" style="align-items:end;">
                <label>
                    Ticket
                    <input type="number" name="ticket" required placeholder="Order ticket">
                </label>
                <button type="submit">Search</button>
            </form>
            <div id="orders-result"></div>
        </article>
    `;

    // Ticket lookup
    document.getElementById('ticket-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const ticket = form.ticket.value;
        const type = form.lookup_type.value;
        const resultEl = document.getElementById('ticket-result');

        try {
            const data = type === 'deal'
                ? await window.api.getDealFromTicket(ticket)
                : await window.api.getOrderFromTicket(ticket);
            resultEl.style.display = '';
            resultEl.textContent = JSON.stringify(data, null, 2);
        } catch (err) {
            resultEl.style.display = '';
            resultEl.textContent = `Error: ${err.message}`;
        }
    });

    // Deals history
    document.getElementById('deals-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const el = document.getElementById('deals-result');
        el.innerHTML = '<p aria-busy="true">Searching...</p>';

        try {
            const from = new Date(form.from_date.value).toISOString();
            const to = new Date(form.to_date.value).toISOString();
            const position = form.position.value;

            const deals = await window.api.historyDealsGet(from, to, position);
            if (!deals || deals.length === 0) {
                el.innerHTML = '<p>No deals found</p>';
                return;
            }

            const keys = Object.keys(deals[0]);
            el.innerHTML = `
                <figure>
                <table>
                    <thead><tr>${keys.map(k => `<th>${k}</th>`).join('')}</tr></thead>
                    <tbody>
                        ${deals.map(d => `<tr>${keys.map(k => `<td>${d[k] ?? ''}</td>`).join('')}</tr>`).join('')}
                    </tbody>
                </table>
                </figure>
            `;
        } catch (err) {
            el.innerHTML = `<p>Error: ${err.message}</p>`;
        }
    });

    // Orders history
    document.getElementById('orders-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const el = document.getElementById('orders-result');
        el.innerHTML = '<p aria-busy="true">Searching...</p>';

        try {
            const orders = await window.api.historyOrdersGet(form.ticket.value);
            if (!orders || orders.length === 0) {
                el.innerHTML = '<p>No orders found</p>';
                return;
            }

            const keys = Object.keys(orders[0]);
            el.innerHTML = `
                <figure>
                <table>
                    <thead><tr>${keys.map(k => `<th>${k}</th>`).join('')}</tr></thead>
                    <tbody>
                        ${orders.map(o => `<tr>${keys.map(k => `<td>${o[k] ?? ''}</td>`).join('')}</tr>`).join('')}
                    </tbody>
                </table>
                </figure>
            `;
        } catch (err) {
            el.innerHTML = `<p>Error: ${err.message}</p>`;
        }
    });
}
