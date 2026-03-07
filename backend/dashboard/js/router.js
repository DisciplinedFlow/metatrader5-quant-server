// Hash-based router with lazy page loading

const app = document.getElementById('app');

const routes = {
    '/dashboard': () => import('./pages/dashboard.js'),
    '/positions': () => import('./pages/positions.js'),
    '/order': () => import('./pages/order.js'),
    '/history': () => import('./pages/history.js'),
    '/chart': () => import('./pages/chart.js'),
    '/logs': () => import('./pages/logs.js'),
    '/strategies': () => import('./pages/strategies.js'),
};

let currentCleanup = null;

async function navigate() {
    const hash = window.location.hash.slice(1) || '/dashboard';

    // Highlight active nav link
    document.querySelectorAll('[data-nav]').forEach(a => {
        a.classList.toggle('active-nav', a.getAttribute('href') === `#${hash}`);
    });

    const loader = routes[hash];
    if (!loader) {
        app.innerHTML = '<article><h2>404</h2><p>Page not found.</p></article>';
        return;
    }

    // Cleanup previous page if needed
    if (currentCleanup) {
        currentCleanup();
        currentCleanup = null;
    }

    app.innerHTML = '<p aria-busy="true">Loading...</p>';

    try {
        const mod = await loader();
        const cleanup = await mod.default(app);
        if (typeof cleanup === 'function') {
            currentCleanup = cleanup;
        }
    } catch (err) {
        console.error('Page load error:', err);
        app.innerHTML = `<article><h2>Error</h2><p>${err.message}</p></article>`;
    }
}

window.addEventListener('hashchange', navigate);

// Auth form handler
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const username = form.username.value;
    const password = form.password.value;

    try {
        await window.api.login(username, password);
        updateAuthUI();
        window.toast.success('Logged in successfully');
    } catch (err) {
        window.toast.error(`Login failed: ${err.message}`);
    }
});

function updateAuthUI() {
    const authStatus = document.getElementById('auth-status');
    if (window.api.isAuthenticated() || localStorage.getItem('django_basic')) {
        authStatus.innerHTML = `
            <span class="auth-label">Authenticated</span>
            <button class="secondary outline" id="logout-btn">Logout</button>
        `;
        document.getElementById('logout-btn').addEventListener('click', () => {
            window.api.clearToken();
            localStorage.removeItem('django_basic');
            updateAuthUI();
            window.toast.info('Logged out');
        });
    } else {
        authStatus.innerHTML = `
            <form id="login-form" role="group">
                <input type="text" name="username" placeholder="Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit" class="secondary">Login</button>
            </form>
        `;
        document.getElementById('login-form').addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const f = ev.target;
            try {
                await window.api.login(f.username.value, f.password.value);
                updateAuthUI();
                window.toast.success('Logged in successfully');
            } catch (err) {
                window.toast.error(`Login failed: ${err.message}`);
            }
        });
    }
}

// Init
updateAuthUI();
navigate();
