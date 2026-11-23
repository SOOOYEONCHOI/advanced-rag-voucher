// 2026.07.22(sychoi) 추가 - RAG 평가 자동화 API (evaluation 연동)
import { adminAuthConfig, http } from './http';

export const evalApi = {
  // ── 데이터셋 (테스트셋 생성/검수) ─────────────────────
  createDataset(payload) {
    return http.post('/eval/datasets', payload, adminAuthConfig());
  },
  listDatasets() {
    return http.get('/eval/datasets', adminAuthConfig());
  },
  getDataset(datasetId) {
    return http.get(`/eval/datasets/${datasetId}`, adminAuthConfig());
  },
  deleteDataset(datasetId) {
    return http.delete(`/eval/datasets/${datasetId}`, adminAuthConfig());
  },
  downloadApprovedDataset(datasetId) {
    return http.get(`/eval/datasets/${datasetId}/approved-items.xlsx`, adminAuthConfig({
      responseType: 'blob',
    }));
  },
  // 2026.11.19(sooyeon.choi) 추가 - 시험 데이터셋(질의·정답 근거·요약) Excel
  downloadTestset(datasetId) {
    return http.get(`/eval/datasets/${datasetId}/test-set.xlsx`, adminAuthConfig({
      responseType: 'blob',
    }));
  },
  listQaItems(datasetId, { status, type, page = 1, pageSize = 50 } = {}) {
    return http.get(`/eval/datasets/${datasetId}/items`, adminAuthConfig({
      params: { status, type, page, page_size: pageSize },
    }));
  },
  updateQaItem(qaId, payload) {
    return http.patch(`/eval/items/${qaId}`, payload, adminAuthConfig());
  },
  approveQaItem(qaId) {
    return http.post(`/eval/items/${qaId}/approve`, null, adminAuthConfig());
  },
  // 2026.11.19(sooyeon.choi) 추가 - '검색 확인 필요' 문항을 같은 조항(섹션)으로 다시 생성
  regenerateQaItem(qaId) {
    return http.post(`/eval/items/${qaId}/regenerate`, null, adminAuthConfig());
  },
  rejectQaItem(qaId) {
    return http.post(`/eval/items/${qaId}/reject`, null, adminAuthConfig());
  },
  bulkReview(qaIds, action) {
    return http.post('/eval/items/bulk-review', { qa_ids: qaIds, action }, adminAuthConfig());
  },
  // 2026.11.20(sooyeon.choi) 수정 - 합본 데이터셋 만들기(확정 데이터셋 2개 이상, 고른 순서대로)
  mergeDatasets({ name, datasetIds }) {
    return http.post('/eval/datasets/merge', { name, dataset_ids: datasetIds }, adminAuthConfig());
  },
  // 2026.11.23(sooyeon.choi) 추가 - 질의ID 접두어 변경(확정 데이터셋 포함, 빈 값이면 Q)
  updateQueryIdPrefix(datasetId, queryIdPrefix) {
    return http.patch(`/eval/datasets/${datasetId}/query-id-prefix`, { query_id_prefix: queryIdPrefix }, adminAuthConfig());
  },
  finalizeDataset(datasetId, note = '') {
    return http.post(`/eval/datasets/${datasetId}/finalize`, { note }, adminAuthConfig());
  },
  searchChunks(q, collectionName, topK = 10) {
    return http.get('/eval/chunks/search', adminAuthConfig({
      params: { q, collection_name: collectionName, top_k: topK },
    }));
  },

  // ── 데이터셋 생성용 설정 (OpenAI 키 1회 저장, 관리자 계정 단위) ───────
  getOpenAIKeyStatus() {
    return http.get('/eval/settings/dataset-generation/openai-key', adminAuthConfig());
  },
  saveOpenAIKey(openaiApiKey) {
    return http.put('/eval/settings/dataset-generation/openai-key', { openai_api_key: openaiApiKey }, adminAuthConfig());
  },
  deleteOpenAIKey() {
    return http.delete('/eval/settings/dataset-generation/openai-key', adminAuthConfig());
  },
  // 2026.11.18(sooyeon.choi) 추가 - 데이터셋 생성용 vLLM 모델 목록(모델명·기본 여부·켜짐 여부)
  getGenerationModels() {
    return http.get('/eval/settings/dataset-generation/models', adminAuthConfig());
  },

  // ── 골드셋 ─────────────────────────────────────────
  listGoldsets(datasetId) {
    return http.get('/eval/goldsets', adminAuthConfig({ params: { dataset_id: datasetId } }));
  },
  importGoldset(payload) {
    return http.post('/eval/goldsets/import', payload, adminAuthConfig());
  },

  // ── 평가 실행 ──────────────────────────────────────
  createRun(payload) {
    return http.post('/eval/runs', payload, adminAuthConfig());
  },
  listRuns(goldsetId, limit = 50) {
    return http.get('/eval/runs', adminAuthConfig({ params: { goldset_id: goldsetId, limit } }));
  },
  getRun(runId) {
    return http.get(`/eval/runs/${runId}`, adminAuthConfig());
  },
  downloadRunExcel(runId) {
    return http.get(`/eval/runs/${runId}/results.xlsx`, adminAuthConfig({
      responseType: 'blob',
    }));
  },
  cancelRun(runId) {
    return http.post(`/eval/runs/${runId}/cancel`, null, adminAuthConfig());
  },
  deleteRun(runId) {
    return http.delete(`/eval/runs/${runId}`, adminAuthConfig());
  },
  // 2026.11.20(sooyeon.choi) 수정 - law: 합본 실행 법령 필터
  listRunResults(runId, { status, type, law, page = 1, pageSize = 50 } = {}) {
    return http.get(`/eval/runs/${runId}/results`, adminAuthConfig({
      params: { status, type, law, page, page_size: pageSize },
    }));
  },

  // ── 원본 문서 파일 (상세 모달의 참조문서 열기 — 기존 ingest 엔드포인트 재사용) ──
  async getDocumentFile(documentId) {
    const res = await http.get(
      `/ingest/documents/${encodeURIComponent(documentId)}/file`,
      adminAuthConfig({ responseType: 'blob' }),
    );
    return new Blob([res.data], { type: 'application/pdf' });
  },

  // ── 대시보드 — P5에서 UI 연결 ───────────────────────
  trend(metricKeys, collectionId, limit = 20) {
    return http.get('/eval/dashboard/trend', adminAuthConfig({
      params: { metric_keys: metricKeys.join(','), collection_id: collectionId, limit },
    }));
  },
  compare(runIds) {
    return http.get('/eval/dashboard/compare', adminAuthConfig({
      params: { run_ids: runIds.join(',') },
    }));
  },
};
