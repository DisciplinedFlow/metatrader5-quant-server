// Place market order form

export default async function render(app) {
    app.innerHTML = `
        <h2>Place Market Order</h2>
        <article>
            <form id="order-form">
                <div class="grid">
                    <label>
                        Symbol
                        <select name="symbol" id="order-symbol-select" required>
                            <option value="EURUSD">EURUSD</option>
                        </select>
                    </label>
                    <label>
                        Volume (lots)
                        <input type="number" name="volume" value="0.01" min="0.01" step="0.01" required>
                    </label>
                </div>
                <div class="grid">
                    <label>
                        Order Type
                        <select name="type" required>
                            <option value="BUY">BUY</option>
                            <option value="SELL">SELL</option>
                        </select>
                    </label>
                    <label>
                        Deviation (pts)
                        <input type="number" name="deviation" value="20" min="0">
                    </label>
                </div>
                <div class="grid">
                    <label>
                        Stop Loss (price)
                        <input type="number" name="sl" step="any" placeholder="Optional">
                    </label>
                    <label>
                        Take Profit (price)
                        <input type="number" name="tp" step="any" placeholder="Optional">
                    </label>
                </div>
                <div class="grid">
                    <label>
                        Magic Number
                        <input type="number" name="magic" value="0" min="0">
                    </label>
                    <label>
                        Comment
                        <input type="text" name="comment" placeholder="Optional">
                    </label>
                </div>
                <div id="tick-preview"></div>
                <button type="submit" id="order-submit">Send Order</button>
            </form>
        </article>
        <article id="order-result" style="display:none;">
            <header>Order Result</header>
            <pre id="order-result-content"></pre>
        </article>
    `;

    const form = document.getElementById('order-form');
    const symbolSelect = document.getElementById('order-symbol-select');
    const tickPreview = document.getElementById('tick-preview');

    // Populate symbol dropdown from MT5
    try {
        const symbols = await window.api.getSymbols();
        symbolSelect.innerHTML = symbols.map(s =>
            `<option value="${s}"${s === 'EURUSD' ? ' selected' : ''}>${s}</option>`
        ).join('');
    } catch (err) {
        console.warn('Failed to load symbols:', err);
    }

    async function updateTick() {
        const symbol = symbolSelect.value;
        if (!symbol) return;
        try {
            const tick = await window.api.symbolInfoTick(symbol);
            tickPreview.innerHTML = `
                <small>Bid: <strong>${tick.bid}</strong> | Ask: <strong>${tick.ask}</strong> | Spread: ${((tick.ask - tick.bid) * 100000).toFixed(1)} pts</small>
            `;
        } catch {
            tickPreview.innerHTML = '<small>Could not fetch tick data</small>';
        }
    }

    symbolSelect.addEventListener('change', updateTick);
    updateTick();

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = document.getElementById('order-submit');
        submitBtn.setAttribute('aria-busy', 'true');
        submitBtn.disabled = true;

        const orderData = {
            symbol: form.symbol.value.trim(),
            volume: parseFloat(form.volume.value),
            type: form.type.value,
            deviation: parseInt(form.deviation.value),
            magic: parseInt(form.magic.value),
            comment: form.comment.value,
        };
        if (form.sl.value) orderData.sl = parseFloat(form.sl.value);
        if (form.tp.value) orderData.tp = parseFloat(form.tp.value);

        try {
            const result = await window.api.sendOrder(orderData);
            window.toast.success('Order executed successfully');
            const resultEl = document.getElementById('order-result');
            resultEl.style.display = '';
            document.getElementById('order-result-content').textContent = JSON.stringify(result, null, 2);
        } catch (err) {
            window.toast.error(`Order failed: ${err.message}`);
        }

        submitBtn.removeAttribute('aria-busy');
        submitBtn.disabled = false;
    });
}
