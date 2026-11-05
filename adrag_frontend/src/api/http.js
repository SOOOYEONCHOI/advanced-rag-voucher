import axios from 'axios';

export const http = axios.create({
  baseURL: '/api',
});

export const getAccessToken = () => sessionStorage.getItem('admin_token') || sessionStorage.getItem('user_token');

export const getAdminToken = () => sessionStorage.getItem('admin_token');

export const getAuthHeaders = () => {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export const getAdminAuthHeaders = () => {
  const token = getAdminToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export const authConfig = (config = {}) => ({
  ...config,
  headers: {
    ...(config.headers || {}),
    ...getAuthHeaders(),
  },
});

export const adminAuthConfig = (config = {}) => ({
  ...config,
  headers: {
    ...(config.headers || {}),
    ...getAdminAuthHeaders(),
  },
});
