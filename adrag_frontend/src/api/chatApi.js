import { authConfig, http } from './http';

export const chatApi = {
  health(config = {}) {
    return http.get('/health', config);
  },

  loadedModel(config = {}) {
    return http.get('/chat/models', config);
  },

  queryCollections() {
    return http.get('/query/collections', authConfig());
  },

  history(collectionName) {
    return http.get('/query/history', authConfig({ params: { collection_name: collectionName } }));
  },

  models(collectionName) {
    return http.get('/models', { params: { collection_name: collectionName } });
  },

  userLlmSetting(collectionName) {
    return http.get('/user/llm-settings', authConfig({ params: { collection_name: collectionName } }));
  },

  saveUserLlmSetting(payload) {
    return http.post('/user/llm-settings', payload, authConfig());
  },

  send(payload) {
    return http.post('/query/', payload, authConfig({ timeout: 120000 }));
  },

  reset(collectionName) {
    return http.post('/query/reset', { collection_name: collectionName }, authConfig());
  },

  // 2026.06.24(woojin.jung) 추가 - 채팅 응답 좋아요/싫어요 저장 및 취소
  submitFeedback(logId, feedback) {
    return http.patch(`/query/${logId}/feedback`, { feedback }, authConfig());
  },

  // 2026.10.22(woojin.jung) 수정 - 출처 문서에 연결된 스프레드시트 이미지 목록 조회 API 추가
  documentSpreadsheetResources(documentId) {
    return http.get(`/documents/${encodeURIComponent(documentId)}/spreadsheet-resources`, authConfig());
  },

  // 2026.10.22(woojin.jung) 수정 - 인증 헤더를 포함해 이미지 원본을 Blob으로 조회
  spreadsheetResource(resourceId) {
    return http.get(`/spreadsheet-resources/${encodeURIComponent(resourceId)}`, authConfig({ responseType: 'blob' }));
  },

  // 2026.10.23(woojin.jung) 수정 - SheetJS 파싱을 위해 인증된 원본 문서를 ArrayBuffer로 조회
  spreadsheetDocumentFile(documentId) {
    return http.get(`/ingest/documents/${encodeURIComponent(documentId)}/file`, authConfig({ responseType: 'arraybuffer' }));
  },
};
