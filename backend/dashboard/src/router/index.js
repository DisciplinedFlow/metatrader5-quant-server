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

  // --- AI Brain ---
  {
    path: '/ai-brain',
    component: () => import('@/pages/AIBrainPage.vue'),
  },

  // --- ML Learning Pipeline ---
  {
    path: '/ml',
    component: () => import('@/pages/MLBrainPage.vue'),
  },

  // --- Knowledge Brain ---
  {
    path: '/forex/knowledge',
    component: () => import('@/pages/KnowledgeBrainPage.vue'),
  },

  // --- Performance Analytics ---
  {
    path: '/forex/performance',
    component: () => import('@/pages/PerformancePage.vue'),
  },
  { path: '/performance', redirect: '/forex/performance' },

  // --- Settings ---
  {
    path: '/settings',
    component: () => import('@/pages/SettingsPage.vue'),
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
