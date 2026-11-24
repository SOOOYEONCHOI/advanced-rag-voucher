import { adminAuthConfig, authConfig, getAccessToken, http } from './http';

export const authApi = {
  loginUser(payload) {
    return http.post('/auth/login', payload);
  },

  registerUser(payload) {
    return http.post('/auth/register', payload, adminAuthConfig());
  },

  getMe(config = {}) {
    return http.get('/auth/me', authConfig(config));
  },

  // 2026.11.13(woojin.jung) 추가 - 일반 사용자 본인 비밀번호 변경
  changePassword(payload) {
    return http.post('/auth/password', payload, authConfig());
  },

  logoutUser() {
    const token = getAccessToken();
    if (!token) return Promise.resolve();
    return http.post('/auth/logout', {}, authConfig());
  },
};
