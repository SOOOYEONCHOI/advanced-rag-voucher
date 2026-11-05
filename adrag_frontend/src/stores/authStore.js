import { defineStore } from 'pinia';
import { authApi } from '../api/authApi';
import { DEFAULT_UI_TYPE, normalizeUiType } from '../constants/uiTypes';

const emptyUser = () => ({ user_id: '', user_name: '', token_type: '', ui_type: DEFAULT_UI_TYPE });

const clearAdminSession = () => {
  sessionStorage.removeItem('admin_token');
  sessionStorage.removeItem('admin_id');
  sessionStorage.removeItem('admin_name');
};

const clearUserSession = () => {
  sessionStorage.removeItem('user_token');
  sessionStorage.removeItem('user_id');
  sessionStorage.removeItem('user_name');
};

const isAdminLoginResponse = (data) => {
  const role = data?.role || data?.user_role || data?.token_type;
  return data?.is_admin === true || role === 'admin' || role === 'admin_access' || role === 'superuser' || !!data?.admin_id;
};

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: emptyUser(),
    session: {
      isAdmin: !!sessionStorage.getItem('admin_token'),
      hasUser: !!sessionStorage.getItem('user_token'),
      displayName:
        sessionStorage.getItem('admin_name') ||
        sessionStorage.getItem('user_name') ||
        sessionStorage.getItem('user_id') ||
        '',
    },
  }),

  getters: {
    isAdmin: (state) => state.session.isAdmin,
    hasUser: (state) => state.session.hasUser,
    displayName: (state) => state.session.displayName,
  },

  actions: {
    refreshSession() {
      this.session = {
        isAdmin: !!sessionStorage.getItem('admin_token'),
        hasUser: !!sessionStorage.getItem('user_token'),
        displayName:
          sessionStorage.getItem('admin_name') ||
          sessionStorage.getItem('user_name') ||
          sessionStorage.getItem('user_id') ||
          '',
      };
    },

    async syncUser() {
      const token = sessionStorage.getItem('user_token') || sessionStorage.getItem('admin_token');
      if (!token) {
        this.user = emptyUser();
        this.refreshSession();
        return;
      }

      try {
        const res = await authApi.getMe({ timeout: 5000 });
        this.user = res.data?.user_id
          ? { ...res.data, ui_type: normalizeUiType(res.data.ui_type) }
          : emptyUser();
      } catch {
        this.user = emptyUser();
      }
      this.refreshSession();
    },

    async login(userId, password) {
      clearAdminSession();
      clearUserSession();

      const res = await authApi.loginUser({ user_id: userId, password });
      const data = res.data || {};
      const token = data.access_token || data.token || data.accessToken;
      const loginId = data.user_id || data.admin_id || userId;
      const loginName = data.user_name || data.admin_name || loginId;

      sessionStorage.setItem('user_token', token);
      sessionStorage.setItem('user_id', loginId);
      sessionStorage.setItem('user_name', loginName);

      let profile = {};
      try {
        const me = await authApi.getMe({ timeout: 5000 });
        profile = me.data || {};
        this.user = profile.user_id
          ? { ...profile, ui_type: normalizeUiType(profile.ui_type) }
          : { ...emptyUser(), user_id: loginId, user_name: loginName, token_type: data.token_type || '' };
      } catch {
        this.user = { ...emptyUser(), user_id: loginId, user_name: loginName, token_type: data.token_type || '' };
      }

      if (isAdminLoginResponse({ ...data, ...profile })) {
        clearUserSession();
        sessionStorage.setItem('admin_token', token);
        sessionStorage.setItem('admin_id', profile.user_id || profile.admin_id || loginId);
        sessionStorage.setItem('admin_name', profile.user_name || profile.admin_name || loginName);
        this.refreshSession();
        return { role: 'admin' };
      }

      this.refreshSession();
      return { role: 'user' };
    },

    async logoutAny() {
      try {
        await authApi.logoutUser();
      } catch {
        /* 토큰 만료 등 무시 */
      }

      clearAdminSession();
      clearUserSession();
      this.user = emptyUser();
      this.refreshSession();
    },

    async logoutAdminOnly() {
      try {
        await authApi.logoutUser();
      } catch {
        /* ignore */
      } finally {
        clearAdminSession();
        this.refreshSession();
      }
    },
  },
});
