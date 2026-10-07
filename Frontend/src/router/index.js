import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'agent-chat',
      component: () => import('@/views/AgentChatView.vue'),
      meta: { title: 'Agent 对话' },
    },
    {
      path: '/tasks',
      name: 'test-center',
      component: () => import('@/views/TestCenterView.vue'),
      meta: { title: '测试中心' },
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/HistoryView.vue'),
      meta: { title: '测试历史' },
    },
    {
      path: '/apis',
      name: 'api-plan',
      component: () => import('@/views/ApiPlanView.vue'),
      meta: { title: 'API 测试规划' },
    },
  ],
})

export default router
