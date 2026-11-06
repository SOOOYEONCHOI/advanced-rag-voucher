// 2026.11.06(sooyeon.choi) 수정 - UI-12 이전 버전 복원(R1-5, SC-06): 선택 → 확인 → 접수(멱등 키) → 진행 확인 → 완료/실패, 오류 처리, 새로고침 복원, 적용 이력
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'vite';
import { effectScope, ref } from 'vue';

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const historyResponse = (overrides = {}) => ({
  document_id: 'doc-1',
  product_model: '조립 공정 A',
  collection_display_name: '제조 작업표준',
  current_original_filename: 'v3.xlsx',
  current_version_no: 3,
  activation_revision: 3,
  total_versions: 3,
  next_version_no: 4,
  restore_supported: true,
  can_restore: true,
  restore_block_code: null,
  restore_block_reason: null,
  pending_operation: null,
  versions: [
    { version_no: 3, status: 'active', is_active: true, original_filename: 'v3.xlsx', can_restore: false, restore_block_code: 'ALREADY_ACTIVE', restore_block_reason: '현재 적용 중인 버전입니다.' },
    { version_no: 2, status: 'retired', is_active: false, original_filename: 'v2.xlsx', can_restore: true, restore_block_code: null, restore_block_reason: null },
    { version_no: 1, status: 'retired', is_active: false, original_filename: 'v1.xlsx', can_restore: false, restore_block_code: 'VECTOR_MISSING', restore_block_reason: '보관된 벡터 데이터가 없어 복원할 수 없습니다.' },
  ],
  ...overrides,
});

const setup = async (server, apiOverrides = {}) => {
  const { useDocumentVersions } = await server.ssrLoadModule('/src/composables/useDocumentVersions.js');
  const { useVersionRestore } = await server.ssrLoadModule('/src/composables/useVersionRestore.js');
  const state = { history: historyResponse(), job: { status: 'running', current_step: 'snapshot' }, posts: [], reloads: 0, activationCalls: [] };
  const documents = ref([{ document_id: 'doc-1', version_no: 3, product_model: '조립 공정 A', filename: 'v3.xlsx' }]);
  const alerts = [];
  const api = {
    async documentVersions() { return { data: state.history }; },
    async restoreDocumentVersion(documentId, versionNo, body) {
      state.posts.push({ documentId, versionNo, body });
      return { status: 202, data: { job_id: 'job-r1', operation_type: 'restore', status: 'queued', current_step: 'queued', document_id: documentId, from_version_no: 3, target_version_no: versionNo } };
    },
    async getIngestJob(jobId) { return { data: { job_id: jobId, ...state.job } }; },
    async documentActivations(documentId, params) {
      state.activationCalls.push(params);
      return { data: { document_id: documentId, activations: [{ activation_id: 9, operation_type: 'replace', from_version_no: 2, to_version_no: 3, activated_by_name: '데모', activated_at: '2026-11-03 14:20:00' }], next_before_activation_id: null } };
    },
    ...apiOverrides,
  };
  const scope = effectScope();
  const result = scope.run(() => {
    const loadDocuments = async () => { state.reloads += 1; };
    const versions = useDocumentVersions({ api, loadDocuments, showAlert: (m, t) => alerts.push([t, m]) });
    const restore = useVersionRestore({ api, documents, loadDocuments, showAlert: (m, t) => alerts.push([t, m]), versions, pollIntervalMs: 5, maxPollIntervalMs: 20 });
    return { versions, restore };
  });
  return { ...result, state, documents, alerts, api, scope };
};

test('selection is local, only valid rows are selectable, confirm uses history response', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    const { versions, restore, state, scope } = await setup(server);
    await versions.openVersionHistory({ document_id: 'doc-1' });
    const [v3, v2, v1] = versions.historyItems.value;
    assert.equal(restore.canSelectVersion(v3), false);
    assert.equal(restore.canSelectVersion(v1), false);
    assert.equal(restore.canSelectVersion(v2), true);
    assert.equal(restore.versionBlockReason(v3), ''); // 현재 적용 행은 사유 표시 없음
    assert.match(restore.versionBlockReason(v1), /벡터/);
    restore.selectVersion(v1);
    assert.equal(restore.selectedVersionNo.value, null);
    restore.selectVersion(v2);
    assert.equal(restore.selectedVersionNo.value, 2);
    assert.equal(restore.selectionValid.value, true);
    assert.equal(state.posts.length, 0); // 선택만으로 요청하지 않음
    restore.openRestoreConfirm();
    assert.equal(restore.restoreDialog.stage, 'confirm');
    assert.equal(restore.restoreDialog.fromVersionNo, 3);
    assert.equal(restore.restoreDialog.targetFilename, 'v2.xlsx');
    assert.equal(restore.restoreDialog.nextVersionNo, 4);
    restore.cancelRestoreConfirm();
    assert.equal(restore.restoreDialog.stage, null);
    assert.equal(state.posts.length, 0);
    // 새 응답이면 선택 초기화
    await versions.reloadVersionHistory();
    assert.equal(restore.selectedVersionNo.value, null);
    scope.stop();
  } finally {
    await server.close();
  }
});

// 2026.11.06(sooyeon.choi) 수정 - 권한 변경(D-22): 관리자 사유 없음. 문서 단위 사유는 진행 중 작업(JOB_IN_PROGRESS)으로 확인
test('busy documents: rows carry server reasons, nothing selectable', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    const { versions, restore, state, scope } = await setup(server);
    const reason = '다른 작업이 진행 중입니다.';
    state.history = historyResponse({
      can_restore: false, restore_block_code: 'JOB_IN_PROGRESS', restore_block_reason: reason,
      pending_operation: { job_id: 'job-x', operation_type: 'replace', status: 'running', current_step: 'embed', target_version_no: 4 },
      versions: historyResponse().versions.map((v) => (v.is_active ? v : { ...v, can_restore: false, restore_block_code: 'JOB_IN_PROGRESS', restore_block_reason: reason })),
    });
    await versions.openVersionHistory({ document_id: 'doc-1' });
    assert.match(restore.historyNotice.value, /최신본 변경 작업이 진행 중/);
    for (const item of versions.historyItems.value) assert.equal(restore.canSelectVersion(item), false);
    assert.equal(restore.versionBlockReason(versions.historyItems.value[1]), reason);
    // 기능 꺼짐(기존 백엔드 응답): 복원 UI 없음, 사유 표시 없음
    state.history = { document_id: 'doc-1', current_version_no: 3, versions: historyResponse().versions.map(({ version_no, status, is_active }) => ({ version_no, status, is_active })) };
    await versions.reloadVersionHistory();
    assert.equal(restore.restoreSupported.value, false);
    assert.equal(restore.versionBlockReason(versions.historyItems.value[1]), '');
    scope.stop();
  } finally {
    await server.close();
  }
});

test('restore submits once with idempotency key, polls steps and completes with reloads', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    const { versions, restore, state, documents, scope } = await setup(server);
    await versions.openVersionHistory({ document_id: 'doc-1' });
    restore.selectVersion(versions.historyItems.value[1]);
    restore.openRestoreConfirm();
    await Promise.all([restore.submitRestore(), restore.submitRestore()]); // 중복 클릭
    assert.equal(state.posts.length, 1);
    const { body, versionNo } = state.posts[0];
    assert.equal(versionNo, 2);
    assert.equal(body.expected_current_version_no, 3);
    assert.equal(body.expected_activation_revision, 3);
    assert.match(body.idempotency_key, /^[0-9a-f-]{36}$/);
    assert.equal(restore.restoreDialog.stage, 'progress');
    assert.ok(restore.isDocumentBusy(documents.value[0]));
    await wait(20);
    assert.equal(restore.restoreDialog.step, 'snapshot');
    assert.deepEqual(restore.restoreStepStates('snapshot'), ['done', 'on', 'wait']);
    // 완료 → 목록 재조회(서버 값으로 갱신) → 성공 화면
    documents.value = [{ document_id: 'doc-1', version_no: 2 }];
    state.history = historyResponse({ current_version_no: 2, activation_revision: 4 });
    state.job = { status: 'completed', current_step: 'completed', result: { current_version_no: 2, original_filename: 'v2.xlsx', total_pages: 16, chunk_count: 112, activated_by_name: '작업자' } };
    await wait(30);
    assert.equal(restore.restoreDialog.stage, 'success');
    assert.equal(restore.restoreDialog.result.activated_by_name, '작업자');
    assert.equal(restore.pageStatus.value.type, 'success');
    assert.ok(state.reloads >= 2);
    assert.equal(restore.isDocumentBusy(documents.value[0]), false);
    scope.stop();
  } finally {
    await server.close();
  }
});

test('network loss resends same key; server errors reset or stay per code', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    let failures = 1;
    let mode = 'network';
    const keys = [];
    const { versions, restore, alerts, scope } = await setup(server, {
      async restoreDocumentVersion(documentId, versionNo, body) {
        keys.push(body.idempotency_key);
        if (mode === 'network' && failures-- > 0) throw new Error('Network Error');
        if (mode === 'state') throw { response: { status: 409, data: { detail: { code: 'STATE_CHANGED', message: '현재 적용 버전이 변경되었습니다.' } } } };
        if (mode === 'reused') throw { response: { status: 409, data: { detail: { code: 'IDEMPOTENCY_KEY_REUSED', message: '키 재사용' } } } };
        return { data: { job_id: 'job-x', status: 'queued', current_step: 'queued', from_version_no: 3, target_version_no: versionNo } };
      },
    });
    await versions.openVersionHistory({ document_id: 'doc-1' });
    restore.selectVersion(versions.historyItems.value[1]);
    restore.openRestoreConfirm();
    await restore.submitRestore();
    assert.equal(keys.length, 2);
    assert.equal(keys[0], keys[1]); // 응답 유실 재전송은 같은 키
    assert.equal(restore.restoreDialog.stage, 'progress');
    restore.backgroundRestore(); // 창만 닫고 계속
    assert.equal(restore.restoreDialog.stage, null);
    assert.equal(restore.pageStatus.value.type, 'info');
    scope.stop();

    // STATE_CHANGED: 확인창 닫고 이력 재조회·선택 초기화
    const second = await setup(server, {
      async restoreDocumentVersion() { throw { response: { status: 409, data: { detail: { code: 'STATE_CHANGED', message: '현재 적용 버전이 변경되었습니다.' } } } }; },
    });
    await second.versions.openVersionHistory({ document_id: 'doc-1' });
    second.restore.selectVersion(second.versions.historyItems.value[1]);
    second.restore.openRestoreConfirm();
    await second.restore.submitRestore();
    assert.equal(second.restore.restoreDialog.stage, null);
    assert.equal(second.restore.selectedVersionNo.value, null);
    assert.ok(second.alerts.some(([t, m]) => t === 'error' && m.includes('변경')));
    second.scope.stop();

    // IDEMPOTENCY_KEY_REUSED: 확인창에 오류로 남고 자동 재실행 없음
    mode = 'reused';
    const third = await setup(server, {
      async restoreDocumentVersion() { throw { response: { status: 409, data: { detail: { code: 'IDEMPOTENCY_KEY_REUSED', message: '키 재사용' } } } }; },
    });
    await third.versions.openVersionHistory({ document_id: 'doc-1' });
    third.restore.selectVersion(third.versions.historyItems.value[1]);
    third.restore.openRestoreConfirm();
    await third.restore.submitRestore();
    assert.equal(third.restore.restoreDialog.stage, 'confirm');
    assert.equal(third.restore.restoreDialog.submitError, '키 재사용');
    third.scope.stop();
    assert.ok(alerts);
  } finally {
    await server.close();
  }
});

test('failure keeps current version from reloaded list; retry uses a new key after re-check', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    const { versions, restore, state, scope } = await setup(server);
    await versions.openVersionHistory({ document_id: 'doc-1' });
    restore.selectVersion(versions.historyItems.value[1]);
    restore.openRestoreConfirm();
    await restore.submitRestore();
    state.job = { status: 'failed', current_step: 'snapshot', error: '검색 데이터 확인 중 연결이 끊어졌습니다.', error_code: 'DEPENDENCY_UNAVAILABLE' };
    await wait(30);
    assert.equal(restore.restoreDialog.stage, 'failure');
    assert.equal(restore.restoreDialog.currentVersionNo, 3);
    assert.match(restore.restoreDialog.error, /연결/);
    const firstKey = state.posts[0].body.idempotency_key;
    await restore.retryRestore();
    assert.equal(restore.restoreDialog.stage, 'confirm');
    state.job = { status: 'running', current_step: 'validate' };
    await restore.submitRestore();
    assert.notEqual(state.posts[1].body.idempotency_key, firstKey);
    scope.stop();
  } finally {
    await server.close();
  }
});

test('page refresh resumes restore from pending_operation; activations load once and format lines', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    const { versions, restore, state, documents, alerts, scope } = await setup(server);
    const doc = { document_id: 'doc-1', version_no: 3, pending_operation: { job_id: 'job-r9', operation_type: 'restore', status: 'running', current_step: 'activate', target_version_no: 1 } };
    documents.value = [doc];
    restore.syncPendingRestores(documents.value);
    assert.equal(restore.restorePendingOf(doc), 1);
    assert.ok(restore.isDocumentBusy(doc));
    state.job = { status: 'completed', current_step: 'completed', result: { current_version_no: 1 } };
    await wait(30);
    assert.ok(alerts.some(([t, m]) => t === 'success' && m.includes('v1 복원 완료')));

    await versions.openVersionHistory({ document_id: 'doc-1' });
    restore.onActivationsToggle({ target: { open: true } });
    await wait(5);
    restore.onActivationsToggle({ target: { open: true } });
    await wait(5);
    assert.equal(state.activationCalls.length, 1); // 같은 문서·같은 적용 순번이면 재사용
    assert.equal(restore.activationText(restore.activations.items[0]), '2026-11-03 14:20:00 · 데모 · 새 버전 v3 적용');
    assert.equal(restore.activationText({ operation_type: 'restore', from_version_no: 3, to_version_no: 1, activated_at: 't' }), 't · 시스템 · v3 → v1 복원');
    assert.equal(restore.activationText({ operation_type: 'baseline', to_version_no: 2, activated_at: 't' }), 't · 시스템 · v2 기준 상태 등록');
    scope.stop();
  } finally {
    await server.close();
  }
});

test('error detail parsing handles string, object and array', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    const { restoreErrorInfo, newIdempotencyKey } = await server.ssrLoadModule('/src/composables/useVersionRestore.js');
    assert.deepEqual(restoreErrorInfo({ response: { status: 404, data: { detail: '없음' } } }), { status: 404, code: null, message: '없음' });
    assert.equal(restoreErrorInfo({ response: { status: 409, data: { detail: { code: 'ALREADY_ACTIVE', message: 'm' } } } }).code, 'ALREADY_ACTIVE');
    assert.equal(restoreErrorInfo({ response: { status: 422, data: { detail: [{ msg: 'field required' }] } } }).message, 'field required');
    assert.equal(restoreErrorInfo(new Error('x')).status, null);
    assert.notEqual(newIdempotencyKey(), newIdempotencyKey());
  } finally {
    await server.close();
  }
});
