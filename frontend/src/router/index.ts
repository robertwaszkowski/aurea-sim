/**
 * router/index.ts
 *
 * Routes for the AureaSim dashboard.
 */

import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: () => import('@/pages/Dashboard.vue'),
    },
    {
      path: '/projects/:name',
      component: () => import('@/pages/ProjectView.vue'),
      props: true,
    },
    {
      path: '/diagrams',
      component: () => import('@/pages/Diagrams.vue'),
    },
    {
      path: '/settings',
      component: () => import('@/pages/Settings.vue'),
    },
  ],
})

export default router
