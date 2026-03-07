// Live bot activity logs

export default async function render(app) {
    app.innerHTML = `
        <h2>Bot Logs</h2>
        <div style="display:flex;gap:1rem;align-items:center;margin-bottom:1rem;">
            <label style="margin:0;">
                Lines
                <select id="log-lines">
                    <option value="100">100</option>
                    <option value="200" selected>200</option>
                    <option value="500">500</option>
                    <option value="1000">1000</option>
                </select>
            </label>
            <label style="margin:0;display:flex;align-items:center;gap:0.4rem;">
                <input type="checkbox" id="log-autoscroll" checked role="switch">
                Auto-scroll
            </label>
            <small id="log-status" style="margin-left:auto;color:var(--pico-muted-color);"></small>
        </div>
        <pre id="log-viewer" class="log-viewer"></pre>
    `;

    const viewer = document.getElementById('log-viewer');
    const statusEl = document.getElementById('log-status');
    const linesSelect = document.getElementById('log-lines');
    const autoScrollCheck = document.getElementById('log-autoscroll');

    function colorize(line) {
        const trimmed = line.trimEnd();
        if (!trimmed) return '';
        const span = document.createElement('span');
        span.textContent = trimmed;
        if (trimmed.startsWith('ERROR')) {
            span.className = 'log-error';
        } else if (trimmed.startsWith('WARNING')) {
            span.className = 'log-warning';
        } else if (trimmed.startsWith('INFO')) {
            span.className = 'log-info';
        }
        return span;
    }

    async function refresh() {
        const lines = linesSelect.value;
        try {
            const data = await api.django(`v1/logs/?lines=${lines}`);
            viewer.innerHTML = '';
            if (!data.logs || data.logs.length === 0) {
                viewer.textContent = 'No log entries yet. Waiting for bot activity...';
                statusEl.textContent = 'Empty log';
                return;
            }
            const frag = document.createDocumentFragment();
            for (const line of data.logs) {
                const el = colorize(line);
                if (el) {
                    frag.appendChild(el);
                    frag.appendChild(document.createTextNode('\n'));
                }
            }
            viewer.appendChild(frag);
            statusEl.textContent = `${data.logs.length} lines -- updated ${new Date().toLocaleTimeString()}`;
            if (autoScrollCheck.checked) {
                viewer.scrollTop = viewer.scrollHeight;
            }
        } catch (err) {
            statusEl.textContent = `Error: ${err.message}`;
        }
    }

    await refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
}
