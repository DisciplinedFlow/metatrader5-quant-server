import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  // Root redirect
  {
    path: '/',
    redirect: '/forex',
  },

  // Backwards-compat redirects for old routes
  { path: '/dashboard', redirect: '/forex' },
  { path: '/positions', redirect: '/forex/positions' },
  { path: '/order', redirect: '/forex/order' },
  { path: '/history', redirect: '/forex/history' },
  { path: '/chart', redirect: '/forex/chart' },
  { path: '/logs', redirect: '/forex/logs' },
  { path: '/strategies', redirect: '/forex/strategy' },

  // --- Forex ---
  {
    path: '/forex',
    component: () => import('@/pages/DashboardPage.vue'),
  },
  {
    path: '/forex/positions',
    component: () => import('@/pages/PositionsPage.vue'),
  },
  {
    path: '/forex/order',
    component: () => import('@/pages/OrderPage.vue'),
  },
  {
    path: '/forex/history',
    component: () => import('@/pages/HistoryPage.vue'),
  },
  {
    path: '/forex/chart',
    component: () => import('@/pages/ChartPage.vue'),
  },
  {
    path: '/forex/logs',
    component: () => import('@/pages/LogsPage.vue'),
  },
  {
    path: '/forex/strategy',
    component: () => import('@/pages/StrategiesPage.vue'),
  },

  // --- Polymarket ---
  {
    path: '/polymarket',
    component: () => import('@/pages/polymarket/PolyDashboardPage.vue'),
  },
  {
    path: '/polymarket/markets',
    component: () => import('@/pages/polymarket/PolyMarketsPage.vue'),
  },
  {
    path: '/polymarket/positions',
    component: () => import('@/pages/polymarket/PolyPositionsPage.vue'),
  },
  {
    path: '/polymarket/logs',
    component: () => import('@/pages/polymarket/PolyLogsPage.vue'),
  },
  {
    path: '/polymarket/strategy',
    component: () => import('@/pages/polymarket/PolyStrategyPage.vue'),
  },

  // --- Crypto ---
  {
    path: '/crypto',
    component: () => import('@/pages/crypto/CryptoDashboardPage.vue'),
  },
  {
    path: '/crypto/positions',
    component: () => import('@/pages/crypto/CryptoPositionsPage.vue'),
  },
  {
    path: '/crypto/logs',
    component: () => import('@/pages/crypto/CryptoLogsPage.vue'),
  },
  {
    path: '/crypto/strategy',
    component: () => import('@/pages/crypto/CryptoStrategyPage.vue'),
  },

  // Catch-all
  {
    path: '/:pathMatch(.*)*',
    component: () => import('@/pages/NotFoundPage.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
