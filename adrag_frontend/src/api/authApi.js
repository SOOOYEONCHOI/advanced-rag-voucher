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

  logoutUser() {
    const token = getAccessToken();
    if (!token) return Promise.resolve();
    return http.post('/auth/logout', {}, authConfig());
  },
};
