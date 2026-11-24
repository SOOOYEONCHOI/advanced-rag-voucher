// 2026.11.20(woojin.jung) 추가 - 부서 운영관리자: 자기 부서 사용자 권한 API(부서는 서버가 계정 기준으로 판단)
import { authConfig, http } from './http';

export const managerApi = {
  department() {
    return http.get('/manager/department', authConfig());
  },

  members(params = {}) {
    return http.get('/manager/members', authConfig({ params }));
  },

  memberPermissions(userId) {
    return http.get(`/manager/members/${encodeURIComponent(userId)}/permissions`, authConfig());
  },

  saveMemberPermissions(userId, payload) {
    return http.put(`/manager/members/${encodeURIComponent(userId)}/permissions`, payload, authConfig());
  },
};
