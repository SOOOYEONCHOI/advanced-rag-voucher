// 2026.11.06(sooyeon.choi) 수정 - UI-12 이전 버전 복원(R1-5, SC-06, VR-01·VR-06). 목업 admin_UI-12_이전버전복원_20261104_v0.2 기준
//   - 버전 이력에서 이전 버전 1개 선택 → 하단 [선택 버전 복원] → 확인창 → [이 버전으로 복원]에서만 POST(행 선택·확인창은 서버 요청 없음)
//   - 선택 가능 여부·불가 사유는 서버 응답(can_restore·restore_block_reason)만 사용한다(역할명으로 판단하지 않음)
//   - 접수 후 GET /ingest/jobs/{job_id}를 2초 간격(장애 시 최대 5초)으로 확인. 창을 닫아도 확인은 계속되고 목록 pending_operation으로 새로고침 후에도 이어간다
//   - 같은 확인 클릭의 네트워크 재전송은 같은 멱등 키, 실패 후 [다시 시도]는 최신 이력 재조회 → 확인창 → 새 키
//   - 성공을 예측해 화면 값을 먼저 바꾸지 않는다. 완료·실패 시 목록·이력·열린 적용 이력을 다시 읽는다
//   - 권한: 문서를 볼 수 있는 사용자면 복원 가능(관리자 전용 아님, D-22 변경). 볼 수 없으면 서버가 404
//   근거: docs/design/문서_이전버전_복원_화면영역별_API_명세_v1.1.md
import { computed, onScopeDispose, reactive, ref, watch } from 'vue';

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_INTERVAL_MS = 5000;
const SUBMIT_NETWORK_RETRIES = 2;
const ACTIVATIONS_PAGE_SIZE = 20;

// 서버 오류 → { status, code, message }. detail은 문자열(기존 API)·{code,message}(복원 API)·배열(요청 검증 오류) 중 하나
export const restoreErrorInfo = (error, fallback = '요청을 처리하지 못했습니다.') => {
  const status = error?.response?.status ?? null;
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return { status, code: null, message: detail };
  if (Array.isArray(detail)) return { status, code: 'INVALID_REQUEST', message: detail[0]?.msg || fallback };
  if (detail && typeof detail === 'object') return { status, code: detail.code || null, message: detail.message || fallback };
  return { status, code: null, message: status ? fallback : '서버에 연결하지 못했습니다. 잠시 후 상태를 다시 확인합니다.' };
};

// 멱등 키. 사내망 http 접속에서는 crypto.randomUUID가 없을 수 있어 getRandomValues로 대신 만든다
export const newIdempotencyKey = () => {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0'));
  return `${h.slice(0, 4).join('')}-${h.slice(4, 6).join('')}-${h.slice(6, 8).join('')}-${h.slice(8, 10).join('')}-${h.slice(10).join('')}`;
};

// 진행창 3줄(목업) ↔ current_step. 값: done / on / wait
export const restoreStepStates = (step) => {
  if (step === 'activate') return ['done', 'done', 'on'];
  if (step === 'validate' || step === 'snapshot') return ['done', 'on', 'wait'];
  if (step === 'completed') return ['done', 'done', 'done'];
  return ['on', 'wait', 'wait'];
};

// 적용 이력 한 줄 문구(명세 7절)
export const activationText = (a) => {
  const actor = a.activated_by_name || a.activated_by || '시스템';
  const label = {
    restore: `v${a.from_version_no} → v${a.to_version_no} 복원`,
    replace: `새 버전 v${a.to_version_no} 적용`,
    upload: `최초 v${a.to_version_no} 적용`,
    baseline: `v${a.to_version_no} 기준 상태 등록`,
  }[a.operation_type] || `v${a.to_version_no} 적용`;
  return `${a.activated_at || '-'} · ${actor} · ${label}`;
};

// 선택을 초기화하고 이력을 다시 보여 줄 업무 오류
const RELOAD_HISTORY_CODES = new Set([
  'STATE_CHANGED', 'JOB_IN_PROGRESS', 'ALREADY_ACTIVE', 'VERSION_NOT_FOUND', 'FEATURE_DISABLED',
  'VERSION_NOT_RESTORABLE', 'PROFILE_UNKNOWN', 'MODEL_UNSUPPORTED', 'METADATA_MISSING', 'VERIFICATION_REQUIRED',
  'VECTOR_MISSING', 'SOURCE_MISSING', 'RESOURCE_MISSING', 'VECTOR_INTEGRITY_MISMATCH',
]);

export const useVersionRestore = ({
  api, documents, loadDocuments, showAlert, versions, pollIntervalMs = POLL_INTERVAL_MS, maxPollIntervalMs = POLL_MAX_INTERVAL_MS,
}) => {
  const { historyTarget, historyData, openVersionHistory, reloadVersionHistory, isVersionPending } = versions;

  // ── C. 버전 선택(로컬 상태, 서버에 저장하지 않음) ──
  const selectedVersionNo = ref(null);

  // ── D·E. 확인·진행·결과 대화상자. stage: confirm / progress / success / failure ──
  const restoreDialog = reactive({
    stage: null, documentId: null, productModel: '', fromVersionNo: null, fromFilename: '', targetVersionNo: null,
    targetFilename: '', nextVersionNo: null, jobId: null, step: 'queued', result: null, error: '', currentVersionNo: null,
    submitError: '', checking: false,
  });
  const restoreSubmitting = ref(false);
  let pendingRequest = null; // 응답을 받지 못한 접수 요청(같은 키로 다시 보냄)

  // ── 진행 중 복원 작업: document_id → { jobId, fromVersionNo, targetVersionNo, delay } ──
  const restoreJobs = reactive({});
  const timers = {};
  let disposed = false;

  // ── 목록 위 상태 줄(#pageStatus). { type: info|success|error, text } ──
  const pageStatus = ref(null);

  // ── F. 적용 이력 ──
  const activations = reactive({ key: '', items: [], loading: false, error: '', next: null, loaded: false });

  const docById = (documentId) => (documents.value || []).find((d) => d.document_id === documentId) || null;

  // ── 목록 잠금: 최신본 변경 처리 중 + 복원 등 서버 점유(pending_operation) + 이 화면에서 접수한 복원 ──
  const isDocumentBusy = (doc) => Boolean(isVersionPending(doc) || doc?.pending_operation || restoreJobs[doc?.document_id]);
  const restorePendingOf = (doc) => {
    const job = restoreJobs[doc?.document_id];
    if (job) return job.targetVersionNo;
    return doc?.pending_operation?.operation_type === 'restore' ? doc.pending_operation.target_version_no : null;
  };

  // ── B. 이력 화면 계산값 ──
  const restoreSupported = computed(() => Boolean(historyData.value?.restore_supported));
  const historyDocBusy = computed(() => Boolean(historyTarget.value && restoreJobs[historyTarget.value.document_id]));
  const canSelectVersion = (item) => Boolean(
    restoreSupported.value && historyData.value?.can_restore && item?.can_restore && !item.is_active && !historyDocBusy.value,
  );
  // 불가 사유는 기능이 켜졌을 때만, 현재 적용 행은 표시하지 않는다(서버가 문서 단위 사유를 각 행에 복사해 준다)
  const versionBlockReason = (item) => {
    if (!restoreSupported.value || !item || item.is_active || canSelectVersion(item)) return '';
    if (historyDocBusy.value) return '다른 작업이 진행 중입니다.';
    return item.restore_block_reason || '';
  };
  const selectedVersion = computed(() => (historyData.value?.versions || []).find((v) => v.version_no === selectedVersionNo.value) || null);
  const selectionValid = computed(() => Boolean(selectedVersion.value && canSelectVersion(selectedVersion.value)));
  const historyNotice = computed(() => {
    const data = historyData.value;
    if (!data || !data.restore_supported || data.restore_block_code === 'FEATURE_DISABLED') {
      return '현재 적용 중인 버전만 검색과 질의응답에 사용됩니다.';
    }
    if (data.restore_block_code === 'JOB_IN_PROGRESS' || historyDocBusy.value) {
      const op = data.pending_operation?.operation_type || (historyDocBusy.value ? 'restore' : null);
      return op === 'restore' ? '복원 작업이 진행 중입니다. 완료 후 다시 확인하세요.' : '최신본 변경 작업이 진행 중입니다. 완료 후 복원할 수 있습니다.';
    }
    return '현재 적용 중인 버전만 RAG 검색·답변에 사용됩니다. 이전 버전 복원 시 검색 데이터와 출처도 함께 전환됩니다.';
  });

  // 이력 응답이 새로 오거나 문서가 바뀌면 선택 초기화
  watch(historyData, () => { selectedVersionNo.value = null; }, { flush: 'sync' });

  const selectVersion = (item) => {
    if (canSelectVersion(item)) selectedVersionNo.value = item.version_no;
  };

  const resetDialog = () => {
    Object.assign(restoreDialog, {
      stage: null, documentId: null, productModel: '', fromVersionNo: null, fromFilename: '', targetVersionNo: null,
      targetFilename: '', nextVersionNo: null, jobId: null, step: 'queued', result: null, error: '', currentVersionNo: null,
      submitError: '', checking: false,
    });
  };

  // 같은 이력 응답만으로 확인창을 채운다(별도 서버 요청 없음)
  const openRestoreConfirm = () => {
    if (!selectionValid.value) return;
    const data = historyData.value;
    const target = selectedVersion.value;
    pendingRequest = null;
    Object.assign(restoreDialog, {
      stage: 'confirm', documentId: data.document_id, productModel: data.product_model || historyTarget.value?.product_model || '',
      fromVersionNo: data.current_version_no, fromFilename: data.current_original_filename || '',
      targetVersionNo: target.version_no, targetFilename: target.original_filename || '', nextVersionNo: data.next_version_no ?? null,
      jobId: null, step: 'queued', result: null, error: '', currentVersionNo: null, submitError: '', checking: false,
    });
  };
  const cancelRestoreConfirm = () => {
    if (restoreSubmitting.value) return;
    resetDialog();
  };

  // ── 작업 확인 ──
  const schedule = (documentId) => {
    clearTimeout(timers[documentId]);
    const job = restoreJobs[documentId];
    if (disposed || !job) return;
    timers[documentId] = setTimeout(() => pollRestore(documentId), job.delay);
  };
  const trackRestore = (documentId, jobId, fromVersionNo, targetVersionNo) => {
    if (!jobId || restoreJobs[documentId]?.jobId === jobId) return;
    restoreJobs[documentId] = { jobId, fromVersionNo, targetVersionNo, delay: pollIntervalMs };
    schedule(documentId);
  };
  const isForeground = (jobId) => restoreDialog.stage === 'progress' && restoreDialog.jobId === jobId;

  async function pollRestore(documentId) {
    const job = restoreJobs[documentId];
    if (!job || disposed) return;
    try {
      const res = await api.getIngestJob(job.jobId);
      if (disposed || restoreJobs[documentId]?.jobId !== job.jobId) return;
      const data = res.data || {};
      job.delay = pollIntervalMs;
      if (isForeground(job.jobId)) {
        restoreDialog.step = data.current_step || restoreDialog.step;
        restoreDialog.checking = false;
      }
      if (data.status === 'completed' || data.status === 'failed') {
        delete restoreJobs[documentId];
        await finishRestore(documentId, job, data);
        return;
      }
    } catch (error) {
      if (disposed) return;
      // 다른 사용자 작업(403)·없는 작업(404)은 확인을 멈추고 목록으로 상태를 본다. 그 외 일시 장애는 작업 실패가 아니다
      if ([403, 404].includes(error?.response?.status)) {
        delete restoreJobs[documentId];
        if (isForeground(job.jobId)) resetDialog();
        await loadDocuments();
        return;
      }
      job.delay = Math.min(maxPollIntervalMs, job.delay * 2);
      if (isForeground(job.jobId)) restoreDialog.checking = true;
    }
    schedule(documentId);
  }

  const reloadActivationsIfOpen = async (documentId) => {
    if (activations.loaded && activations.key.startsWith(`${documentId}:`)) await loadActivations(true);
  };

  async function finishRestore(documentId, job, data) {
    const success = data.status === 'completed';
    await loadDocuments();
    if (disposed) return;
    const current = docById(documentId)?.version_no ?? (success ? data.result?.current_version_no : job.fromVersionNo);
    if (historyTarget.value?.document_id === documentId) await reloadVersionHistory();
    await reloadActivationsIfOpen(documentId);
    if (disposed) return;
    pageStatus.value = success
      ? { type: 'success', text: `v${job.targetVersionNo}으로 복원되었습니다. 검색과 질의응답에 반영되었습니다.` }
      : { type: 'error', text: `복원 실패 · 현재 v${current}을 유지합니다. 버전 이력에서 다시 시도하세요.` };
    if (isForeground(job.jobId)) {
      Object.assign(restoreDialog, {
        stage: success ? 'success' : 'failure', step: data.current_step || restoreDialog.step, result: data.result || null,
        error: data.error || '복원을 완료하지 못했습니다.', currentVersionNo: current, checking: false,
      });
    } else {
      showAlert(success ? `v${job.targetVersionNo} 복원 완료` : '복원 실패 · 기존 버전 유지', success ? 'success' : 'error');
    }
  }

  // ── D. 복원 접수 ──
  const handleSubmitError = async (info) => {
    const documentId = restoreDialog.documentId;
    if (info.status === 404 && !info.code) {
      // 문서가 없거나 볼 수 없음 → 이력창 닫고 목록 갱신
      resetDialog();
      versions.closeVersionHistory();
      showAlert(info.message || '문서를 찾을 수 없습니다.', 'error');
      await loadDocuments();
      return;
    }
    if (RELOAD_HISTORY_CODES.has(info.code)) {
      resetDialog();
      showAlert(info.message, 'error');
      if (historyTarget.value?.document_id === documentId) await reloadVersionHistory();
      if (['ALREADY_ACTIVE', 'JOB_IN_PROGRESS'].includes(info.code)) await loadDocuments();
      return;
    }
    // IDEMPOTENCY_KEY_REUSED·503·기타: 확인창에 남긴다(자동으로 새 키를 만들어 실행하지 않음)
    restoreDialog.submitError = info.message;
  };

  const submitRestore = async () => {
    if (restoreDialog.stage !== 'confirm' || restoreSubmitting.value) return;
    const documentId = restoreDialog.documentId;
    if (restoreJobs[documentId]) return;
    if (!pendingRequest) {
      pendingRequest = {
        documentId,
        versionNo: restoreDialog.targetVersionNo,
        body: {
          expected_current_version_no: historyData.value?.current_version_no,
          expected_activation_revision: historyData.value?.activation_revision,
          idempotency_key: newIdempotencyKey(),
        },
      };
    }
    const request = pendingRequest;
    restoreSubmitting.value = true;
    restoreDialog.submitError = '';
    try {
      let res = null;
      for (let attempt = 0; ; attempt += 1) {
        try {
          res = await api.restoreDocumentVersion(request.documentId, request.versionNo, request.body);
          break;
        } catch (error) {
          // 응답을 받지 못한 경우만 같은 키·같은 본문으로 다시 보낸다
          if (error?.response || attempt >= SUBMIT_NETWORK_RETRIES) throw error;
        }
      }
      if (disposed) return;
      pendingRequest = null;
      const data = res.data || {};
      Object.assign(restoreDialog, { stage: 'progress', jobId: data.job_id, step: data.current_step || 'queued' });
      trackRestore(documentId, data.job_id, data.from_version_no ?? request.body.expected_current_version_no, data.target_version_no ?? request.versionNo);
      // 같은 키 재전송에 이미 끝난 작업(200)이 오면 바로 결과를 확인한다
      if (data.status === 'completed' || data.status === 'failed') {
        clearTimeout(timers[documentId]);
        await pollRestore(documentId);
      } else {
        await loadDocuments();
      }
    } catch (error) {
      if (disposed) return;
      const info = restoreErrorInfo(error, '복원 요청을 접수하지 못했습니다.');
      if (error?.response) pendingRequest = null; // 서버가 답했으면 다음 클릭은 새 요청
      await handleSubmitError(info);
    } finally {
      if (!disposed) restoreSubmitting.value = false;
    }
  };

  // ── E. 진행·결과 대화상자 동작 ──
  // [닫고 계속하기]·Esc: 창만 닫는다(작업 취소 아님). 확인은 계속하고 목록 위 상태 줄로 알린다
  const backgroundRestore = () => {
    if (restoreDialog.stage !== 'progress') return;
    pageStatus.value = { type: 'info', text: `v${restoreDialog.targetVersionNo} 복원 처리 중 · 현재 v${restoreDialog.fromVersionNo}으로 서비스 중` };
    resetDialog();
    versions.closeVersionHistory();
  };
  const ensureHistoryOpen = async (documentId) => {
    if (historyTarget.value?.document_id === documentId) return;
    const doc = docById(documentId);
    if (doc) await openVersionHistory(doc);
  };
  // 성공 [버전 이력 확인]·실패 [버전 이력으로]
  const closeRestoreResult = async () => {
    const documentId = restoreDialog.documentId;
    resetDialog();
    if (documentId) await ensureHistoryOpen(documentId);
  };
  // 실패 [다시 시도]: 최신 이력 재조회 → 대상이 아직 선택 가능하면 확인창(새 키), 아니면 이력에서 사유 확인
  const retryRestore = async () => {
    const { documentId, targetVersionNo } = restoreDialog;
    resetDialog();
    await ensureHistoryOpen(documentId);
    await reloadVersionHistory();
    if (disposed) return;
    const target = (historyData.value?.versions || []).find((v) => v.version_no === targetVersionNo);
    if (target && canSelectVersion(target)) {
      selectedVersionNo.value = target.version_no;
      openRestoreConfirm();
    } else if (historyData.value) {
      showAlert(versionBlockReason(target) || `v${targetVersionNo}은 지금 복원할 수 없습니다.`, 'error');
    }
  };
  const restoreTitle = computed(() => ({
    confirm: '이전 버전으로 복원',
    progress: '이전 버전을 복원하고 있습니다',
    success: '이전 버전으로 복원했습니다',
    failure: '복원을 완료하지 못했습니다',
  }[restoreDialog.stage] || ''));
  const restoreStepLabel = (index, state) => {
    if (index === 0) return '복원 요청 접수';
    if (index === 1) return `v${restoreDialog.targetVersionNo}의 검색 데이터와 원본 확인 중`;
    return state === 'on' ? '적용 버전 전환 중' : '적용 버전 전환 대기';
  };

  const onRestoreEscape = () => {
    if (restoreDialog.stage === 'progress') backgroundRestore();
    else if (restoreDialog.stage === 'confirm') cancelRestoreConfirm();
    else if (restoreDialog.stage) closeRestoreResult();
  };

  // 목록을 다시 읽을 때 서버에 복원 점유가 있으면 확인을 이어간다(새로고침 복원)
  const syncPendingRestores = (docs) => {
    for (const doc of docs || []) {
      const op = doc.pending_operation;
      if (op?.operation_type === 'restore' && op.job_id && !restoreJobs[doc.document_id]) {
        trackRestore(doc.document_id, op.job_id, doc.version_no, op.target_version_no);
        pageStatus.value = { type: 'info', text: `v${op.target_version_no} 복원 처리 중 · 현재 v${doc.version_no}으로 서비스 중` };
      }
    }
  };

  // ── F. 적용 이력: 처음 펼칠 때 조회, 같은 문서·같은 적용 순번이면 재사용 ──
  const activationKey = () => {
    const data = historyData.value;
    return data ? `${data.document_id}:${data.activation_revision ?? ''}` : '';
  };
  let activationRequest = 0;
  async function loadActivations(force = false, more = false) {
    const key = more ? activations.key : activationKey();
    if (!key) return;
    if (!force && !more && activations.loaded && activations.key === key) return;
    const documentId = key.split(':')[0];
    const request = ++activationRequest;
    activations.loading = true;
    activations.error = '';
    try {
      const params = { limit: ACTIVATIONS_PAGE_SIZE };
      if (more && activations.next != null) params.before_activation_id = activations.next;
      const res = await api.documentActivations(documentId, params);
      if (disposed || request !== activationRequest) return;
      const items = res.data?.activations || [];
      activations.items = more ? [...activations.items, ...items] : items;
      activations.next = res.data?.next_before_activation_id ?? null;
      activations.key = key;
      activations.loaded = true;
    } catch (error) {
      if (disposed || request !== activationRequest) return;
      activations.error = restoreErrorInfo(error, '적용 이력을 불러오지 못했습니다.').message;
    } finally {
      if (!disposed && request === activationRequest) activations.loading = false;
    }
  }
  const onActivationsToggle = (event) => {
    if (event?.target?.open) loadActivations();
  };
  const loadMoreActivations = () => {
    if (activations.next != null && !activations.loading) loadActivations(false, true);
  };
  // 다른 문서 이력을 열면 적용 이력 초기화
  watch(() => historyTarget.value?.document_id, (id, prev) => {
    if (id !== prev) {
      activationRequest += 1;
      Object.assign(activations, { key: '', items: [], loading: false, error: '', next: null, loaded: false });
    }
  });

  onScopeDispose(() => {
    disposed = true;
    Object.values(timers).forEach(clearTimeout);
  });

  return {
    // 목록
    isDocumentBusy, restorePendingOf, pageStatus, syncPendingRestores, restoreJobs,
    // 이력·선택
    restoreSupported, canSelectVersion, versionBlockReason, selectedVersionNo, selectedVersion, selectionValid, historyNotice,
    selectVersion,
    // 확인·진행·결과
    restoreDialog, restoreSubmitting, openRestoreConfirm, cancelRestoreConfirm, submitRestore, backgroundRestore,
    closeRestoreResult, retryRestore, onRestoreEscape, restoreStepStates, restoreTitle, restoreStepLabel,
    // 적용 이력
    activations, onActivationsToggle, loadMoreActivations, activationText,
  };
};
