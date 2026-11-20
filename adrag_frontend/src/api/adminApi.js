import { adminAuthConfig, authConfig, http } from './http';

export const adminApi = {
  uploadDocument(formData, config = {}) {
    return http.post('/ingest/upload', formData, authConfig({
      ...config,
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 1800000,
    }));
  },

  // 2026.10.16(sooyeon.choi) 추가 - 엑셀 처리 방식(excel_parse_mode) 조회: backend면 엑셀은 전용 처리기로 처리
  ingestOptions(config = {}) {
    return http.get('/ingest/options', authConfig({ timeout: 15000, ...config }));
  },

  getIngestJob(jobId, config = {}) {
    return http.get(`/ingest/jobs/${encodeURIComponent(jobId)}`, authConfig({ timeout: 15000, ...config }));
  },

  retryIngestJob(jobId, config = {}) {
    return http.post(`/ingest/jobs/${encodeURIComponent(jobId)}/retry`, null, authConfig({ timeout: 15000, ...config }));
  },

  documents(params = {}) {
    return http.get('/ingest/documents', authConfig({ params }));
  },

  // 2026.06.18(sooyeon.choi) 수정 - /ingest/collections 호출 제거, collectionApi.list()로 통일
  deleteDocument(documentId) {
    return http.delete(`/ingest/documents/${encodeURIComponent(documentId)}`, authConfig());
  },

  // 2026.10.19(sooyeon.choi) 추가 - 문서 모델명 수정. 모델명만 바꾸며 재처리하지 않는다.
  updateDocumentModelName(documentId, productModel) {
    return http.patch(`/ingest/documents/${encodeURIComponent(documentId)}/model-name`, { product_model: productModel }, authConfig());
  },

  // 2026.10.19(sooyeon.choi) 추가 - 최신본 변경 접수: 처리 완료·검증 후에만 다음 버전으로 전환
  replaceDocumentVersion(documentId, formData, config = {}) {
    return http.post(`/ingest/documents/${encodeURIComponent(documentId)}/versions`, formData, authConfig({
      ...config,
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 1800000,
    }));
  },

  // 2026.10.19(sooyeon.choi) 추가 - 버전 이력 조회
  documentVersions(documentId) {
    return http.get(`/ingest/documents/${encodeURIComponent(documentId)}/versions`, authConfig({ timeout: 15000 }));
  },

  // 2026.11.09(woojin.jung) 추가 - 이전 버전 복원 접수(202 job_id). 본문 expected_current_version_no·expected_activation_revision·idempotency_key
  restoreDocumentVersion(documentId, versionNo, payload) {
    return http.post(
      `/ingest/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionNo)}/restore`,
      payload,
      authConfig({ timeout: 15000 }),
    );
  },

  // 2026.11.09(woojin.jung) 추가 - 적용 이력 조회(최신순, limit·before_activation_id 커서)
  documentActivations(documentId, params = {}) {
    return http.get(`/ingest/documents/${encodeURIComponent(documentId)}/activations`, authConfig({ params, timeout: 15000 }));
  },

  documentFile(documentId) {
    return http.get(`/ingest/documents/${encodeURIComponent(documentId)}/file`, authConfig({ responseType: 'blob' }));
  },

  drawingResult(documentId, versionNo, config = {}) {
    return http.get(
      `/ingest/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionNo)}/drawing-result`,
      authConfig({ timeout: 30000, ...config }),
    );
  },

  completeDrawingReview(documentId, versionNo, payload = {}, config = {}) {
    return http.post(
      `/ingest/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionNo)}/drawing-review`,
      payload,
      authConfig({ timeout: 15000, ...config }),
    );
  },

  cancelDrawingReview(documentId, versionNo, config = {}) {
    return http.delete(
      `/ingest/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionNo)}/drawing-review`,
      authConfig({ timeout: 15000, ...config }),
    );
  },

  summary() {
    return http.get('/admin/summary', adminAuthConfig());
  },

  departments(params = {}) {
    return http.get('/admin/departments', adminAuthConfig({ params }));
  },

  department(departmentId) {
    return http.get(`/admin/departments/${encodeURIComponent(departmentId)}`, adminAuthConfig());
  },

  createDepartment(payload) {
    return http.post('/admin/departments', payload, adminAuthConfig());
  },

  updateDepartment(departmentId, payload) {
    return http.put(`/admin/departments/${encodeURIComponent(departmentId)}`, payload, adminAuthConfig());
  },

  topics() {
    return http.get('/admin/topics', adminAuthConfig());
  },

  users(params = {}) {
    return http.get('/admin/users', adminAuthConfig({ params }));
  },

  user(userId) {
    return http.get(`/admin/users/${encodeURIComponent(userId)}`, adminAuthConfig());
  },

  createUser(payload) {
    return http.post('/admin/users', payload, adminAuthConfig());
  },

  updateUser(userId, payload) {
    return http.put(`/admin/users/${encodeURIComponent(userId)}`, payload, adminAuthConfig());
  },

  userPermissions(userId) {
    return http.get(`/admin/users/${encodeURIComponent(userId)}/permissions`, adminAuthConfig());
  },

  logs(limit = 20) {
    return http.get('/admin/logs', adminAuthConfig({ params: { limit } }));
  },

  saveUserPermissions(userId, payload) {
    return http.put(`/admin/users/${encodeURIComponent(userId)}/permissions`, payload, adminAuthConfig());
  },
};
