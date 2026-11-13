// 2026.04.01(sooyeon.choi) 수정 - 멀티컬렉션 관리 기능 추가
// 2026.04.09(sooyeon.choi) 수정 - 통합 로그인 및 네비게이션 가드 추가
// 2026.06.17(sooyeon.choi) 수정: /admin/login 라우트를 제거하고 /login으로 통합
import { createRouter, createWebHistory } from 'vue-router';
import ChatView from '../views/ChatView.vue';
import AdminView from '../views/AdminView.vue';
import CollectionSettingsView from '../views/CollectionSettingsView.vue';
import LoginView from '../views/LoginView.vue';
import UserPermissionsView from '../views/UserPermissionsView.vue';
import StatisticsView from '../views/StatisticsView.vue';
import AdminStatisticsView from '../views/AdminStatisticsView.vue';
import UiIntegrationSettingsView from '../views/UiIntegrationSettingsView.vue';
// 2026.07.22(sychoi) 추가 - RAG 평가 실행 화면
import EvalRunView from '../views/EvalRunView.vue';
// 2026.07.22(sychoi) 추가 - RAG 평가 테스트셋 생성/검수 화면
import EvalDatasetView from '../views/EvalDatasetView.vue';
// 2026.07.22(sychoi) 추가 - RAG 평가 추이/비교 대시보드
import EvalDashboardView from '../views/EvalDashboardView.vue';

export const ADMIN_HOME_PATH = '/admin/users';

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/chat', component: ChatView, meta: { requiresUserAuth: true } },
  { path: '/statistics', component: StatisticsView, meta: { requiresUserAuth: true } },
  { path: '/settings/ui-integration', component: UiIntegrationSettingsView, meta: { requiresUserAuth: true } },
  { path: '/login', component: LoginView, meta: { public: true } },
  // 문서 관리·컬렉션 설정: 일반 사용자 전용 관리 화면
  { path: '/admin', component: AdminView, meta: { requiresAnyAuth: true } },
  { path: '/admin/statistics', component: AdminStatisticsView, meta: { requiresAdminAuth: true } },
  { path: '/admin/collections', component: CollectionSettingsView, meta: { requiresAnyAuth: true } },
  // 사용자 권한: 관리자 전용
  { path: '/admin/users', component: UserPermissionsView, meta: { requiresAdminAuth: true } },
  // 2026.07.22(sychoi) 추가 - RAG 평가 (관리자 전용)
  { path: '/admin/eval/datasets', component: EvalDatasetView, meta: { requiresAdminAuth: true } },
  { path: '/admin/eval/runs', component: EvalRunView, meta: { requiresAdminAuth: true } },
  { path: '/admin/eval/dashboard', component: EvalDashboardView, meta: { requiresAdminAuth: true } },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to, _from, next) => {
  const hasAdmin = !!sessionStorage.getItem('admin_token');
  const hasUser = !!sessionStorage.getItem('user_token');

  // 관리자는 사용자 권한과 관리자 통계 화면만 사용
  if (hasAdmin && to.path === '/chat') return next(ADMIN_HOME_PATH);

  // 관리자 전용 페이지
  if (to.meta.requiresAdminAuth) {
    if (hasAdmin) return next();
    if (hasUser) return next({ path: '/chat', query: { access_denied: '1' } });
    return next({ path: '/login', query: { redirect: to.fullPath } });
  }

  // 일반 사용자 전용 페이지
  if (to.meta.requiresUserAuth) {
    if (hasUser) return next();
    if (hasAdmin) return next(ADMIN_HOME_PATH);
    return next({ path: '/login', query: { redirect: to.fullPath } });
  }

  // 로그인 사용자(관리자 or 일반) 접근 페이지
  if (to.meta.requiresAnyAuth) {
    if (hasAdmin) return next(ADMIN_HOME_PATH);
    if (hasUser) return next();
    return next({ path: '/login', query: { redirect: to.fullPath } });
  }

  next();
});

export default router;
