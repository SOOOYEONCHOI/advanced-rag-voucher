import { authConfig, http } from './http';

export const collectionApi = {
  list(config = {}) {
    return http.get('/collections', authConfig(config));
  },

  listAll() {
    return http.get('/collections', authConfig({ params: { include_all: true } }));
  },

  create(payload) {
    return http.post('/collections', payload, authConfig());
  },

  update(collectionId, payload) {
    return http.put(`/collections/${collectionId}`, payload, authConfig());
  },

  remove(collectionId) {
    return http.delete(`/collections/${collectionId}`, authConfig());
  },
};
