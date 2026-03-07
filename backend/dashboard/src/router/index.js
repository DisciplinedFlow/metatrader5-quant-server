import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    component: () => import('@/pages/DashboardPage.vue'),
  },
  {
    path: '/positions',
    component: () => import('@/pages/PositionsPage.vue'),
  },
  {
    path: '/order',
    component: () => import('@/pages/OrderPage.vue'),
  },
  {
    path: '/history',
    component: () => import('@/pages/HistoryPage.vue'),
  },
  {
    path: '/chart',
    component: () => import('@/pages/ChartPage.vue'),
  },
  {
    path: '/logs',
    component: () => import('@/pages/LogsPage.vue'),
  },
  {
    path: '/strategies',
    component: () => import('@/pages/StrategiesPage.vue'),
  },
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
