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

  // 2026.11.12(woojin.jung) 추가 - 대화 주제별 채팅 시작 화면 질문(추천 질문·숨긴 질문·많이 찾는 질문) 조회/저장
  getStartQuestions(collectionId) {
    return http.get(`/collections/${collectionId}/start-questions`, authConfig());
  },

  saveStartQuestions(collectionId, payload) {
    return http.put(`/collections/${collectionId}/start-questions`, payload, authConfig());
  },
};
