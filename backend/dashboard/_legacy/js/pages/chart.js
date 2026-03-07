// TradingView Lightweight Charts candlestick view

export default async function render(app) {
    app.innerHTML = `
        <h2>Chart</h2>
        <form id="chart-controls" class="grid" style="align-items:end;">
            <label>
                Symbol
                <select name="symbol" id="chart-symbol-select">
                    <option value="EURUSD">EURUSD</option>
                </select>
            </label>
            <label>
                Timeframe
                <select name="timeframe">
                    <option value="M1">M1</option>
                    <option value="M5">M5</option>
                    <option value="M15">M15</option>
                    <option value="M30">M30</option>
                    <option value="H1" selected>H1</option>
                    <option value="H4">H4</option>
                    <option value="D1">D1</option>
                    <option value="W1">W1</option>
                </select>
            </label>
            <label>
                Bars
                <input type="number" name="num_bars" value="200" min="10" max="1000">
            </label>
            <button type="submit">Load</button>
        </form>
        <div id="chart-container"></div>
    `;

    let chart = null;
    let candleSeries = null;
    let volumeSeries = null;

    function createChart() {
        const container = document.getElementById('chart-container');
        container.innerHTML = '';

        chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 500,
            layout: {
                background: { color: '#1a1a2e' },
                textColor: '#e0e0e0',
            },
            grid: {
                vertLines: { color: '#2a2a4a' },
                horzLines: { color: '#2a2a4a' },
            },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            timeScale: { timeVisible: true, secondsVisible: false },
        });

        // Lightweight Charts v5 API: addSeries(Type, options)
        candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderDownColor: '#ef5350',
            borderUpColor: '#26a69a',
            wickDownColor: '#ef5350',
            wickUpColor: '#26a69a',
        });

        volumeSeries = chart.addSeries(LightweightCharts.HistogramSeries, {
            color: '#385263',
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
        });
        chart.priceScale('volume').applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
        });

        // Resize handler
        const observer = new ResizeObserver(() => {
            chart.applyOptions({ width: container.clientWidth });
        });
        observer.observe(container);

        return observer;
    }

    let resizeObserver = createChart();

    // Populate symbol dropdown from MT5
    try {
        const symbols = await window.api.getSymbols();
        const sel = document.getElementById('chart-symbol-select');
        sel.innerHTML = symbols.map(s =>
            `<option value="${s}"${s === 'EURUSD' ? ' selected' : ''}>${s}</option>`
        ).join('');
    } catch (err) {
        console.warn('Failed to load symbols:', err);
    }

    async function loadChart() {
        const form = document.getElementById('chart-controls');
        const symbol = form.symbol.value.trim();
        const timeframe = form.timeframe.value;
        const numBars = parseInt(form.num_bars.value);

        if (!symbol) return;

        try {
            const data = await window.api.fetchDataPos(symbol, timeframe, numBars);

            const candles = data.map(d => ({
                time: Math.floor(new Date(d.time).getTime() / 1000),
                open: d.open,
                high: d.high,
                low: d.low,
                close: d.close,
            }));

            const volumes = data.map(d => ({
                time: Math.floor(new Date(d.time).getTime() / 1000),
                value: d.tick_volume || d.real_volume || 0,
                color: d.close >= d.open ? '#26a69a80' : '#ef535080',
            }));

            candleSeries.setData(candles);
            volumeSeries.setData(volumes);
            chart.timeScale().fitContent();
        } catch (err) {
            window.toast.error(`Chart error: ${err.message}`);
        }
    }

    document.getElementById('chart-controls').addEventListener('submit', (e) => {
        e.preventDefault();
        loadChart();
    });

    await loadChart();

    return () => {
        if (resizeObserver) resizeObserver.disconnect();
        if (chart) chart.remove();
    };
}
