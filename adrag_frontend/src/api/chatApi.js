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

  // 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면 질문(추천 질문·많이 찾는 질문) 조회
  startQuestions(collectionName) {
    return http.get('/query/start-questions', authConfig({ params: { collection_name: collectionName } }));
  },

  // 2026.06.24(woojin.jung) 추가 - 채팅 응답 좋아요/싫어요 저장 및 취소
  // 2026.11.05(woojin.jung) 수정 - 피드백 사유(reasons)·의견(comment) 함께 저장
  submitFeedback(logId, feedback, { reasons = [], comment = null } = {}) {
    return http.patch(`/query/${logId}/feedback`, { feedback, reasons, comment }, authConfig());
  },

  // 2026.10.22(woojin.jung) 수정 - 출처 문서에 연결된 스프레드시트 이미지 목록 조회 API 추가
  documentSpreadsheetResources(documentId) {
    return http.get(`/documents/${encodeURIComponent(documentId)}/spreadsheet-resources`, authConfig());
  },

  // 2026.10.22(woojin.jung) 수정 - 인증 헤더를 포함해 이미지 원본을 Blob으로 조회
  spreadsheetResource(resourceId) {
    return http.get(`/spreadsheet-resources/${encodeURIComponent(resourceId)}`, authConfig({ responseType: 'blob' }));
  },

  // 2026.10.28(woojin.jung) 수정 - 외부 연결 제거 안전 사본 생성을 위해 인증된 원본 문서를 ArrayBuffer로 조회
  spreadsheetDocumentFile(documentId) {
    return http.get(`/ingest/documents/${encodeURIComponent(documentId)}/file`, authConfig({ responseType: 'arraybuffer' }));
  },

  // 2026.10.28(woojin.jung) 추가 - LibreOffice가 원본 형태로 렌더링한 단일 시트 근거 강조 PDF 조회
  spreadsheetSheetPreview(documentId, sheetName, sourceRange) {
    return http.get(
      `/ingest/documents/${encodeURIComponent(documentId)}/sheet-preview`,
      authConfig({
        // 2026.10.28(woojin.jung) 수정 - 이전 PDF 캐시 대신 현재 근거 범위의 최신 미리보기를 항상 조회
        params: { sheet_name: sheetName, source_range: sourceRange, _ts: Date.now() },
        responseType: 'blob',
        timeout: 150000,
      })
    );
  },
};
