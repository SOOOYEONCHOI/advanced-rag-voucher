// 2026.11.09(woojin.jung) 추가 - 문서 이전 버전 복원(UI-12, 08_이전버전복원_목업_가이드 A~F 영역)
//   B 버전 이력: GET /ingest/documents/{id}/versions — 가능 여부(can_restore·restore_block_*)는 서버 값만 본다.
//   C 버전 선택: API 없음. selectedVersionNo 하나만 로컬 보관, 응답을 새로 받으면 초기화.
//   D 복원 확인: POST .../versions/{no}/restore — 클릭 시 idempotency_key 1회 생성, 응답 없이 끊기면 같은 키로 재전송.
//   E 진행·결과: GET /ingest/jobs/{job_id} 2초 간격(장애 시 5초까지), completed/failed에서 멈추고 A·B·(열었으면 F) 재조회.
//     새로고침 후에는 목록의 pending_operation으로 폴링을 이어간다(localStorage 불필요).
//   F 적용 이력: GET .../activations?limit=20&before_activation_id= — 처음 펼칠 때 호출, 같은 문서·같은 activation_revision이면 재사용.
import { computed, onScopeDispose, reactive, ref } from 'vue';

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_INTERVAL_MS = 5000;
const ACTIVATION_PAGE_SIZE = 20;

// 진행창 3줄 ↔ current_step (done / on / wait)
const STEP_LINES = {
  queued: ['on', 'wait', 'wait'],
  validate: ['done', 'on', 'wait'],
  snapshot: ['done', 'on', 'wait'],
  activate: ['done', 'done', 'on'],
};

const STATUS_LABELS = { active: '현재 적용 중', retired: '보관됨', building: '처리 중', ready: '전환 대기', failed: '처리 실패' };

// 다시 조회해 화면을 서버 상태에 맞춰야 하는 복원 접수 오류(확인창을 닫고 이력에 안내)
const REFRESH_CODES = new Set([
  'VERSION_NOT_FOUND', 'FEATURE_DISABLED', 'STATE_CHANGED', 'JOB_IN_PROGRESS', 'ALREADY_ACTIVE',
  'IDEMPOTENCY_KEY_REUSED', 'RESTORE_RETRY_REQUIRES_NEW_REQUEST',
  'VERSION_NOT_RESTORABLE', 'PROFILE_UNKNOWN', 'MODEL_UNSUPPORTED', 'METADATA_MISSING', 'VERIFICATION_REQUIRED',
  'VECTOR_MISSING', 'SOURCE_MISSING', 'RESOURCE_MISSING', 'VECTOR_INTEGRITY_MISMATCH',
]);

// 숫자 끝자리 받침에 맞춘 조사(v3으로·v2로, v3을·v2를)
const lastDigit = (n) => Number(String(n).slice(-1));
export const josaRo = (n) => ([0, 3, 6].includes(lastDigit(n)) ? '으로' : '로');
export const josaEul = (n) => ([0, 1, 3, 6, 7, 8].includes(lastDigit(n)) ? '을' : '를');

export const formatMegabytes = (bytes) => (bytes == null ? null : `${(bytes / 1048576).toFixed(1)} MB`);

export const versionStatusLabel = (status) => STATUS_LABELS[status] || status;

export const restoreStepLines = (step) => STEP_LINES[step] || STEP_LINES.activate;

export const activationText = (a) => {
  const who = a.operation_type === 'baseline' ? '시스템' : a.activated_by_name ?? a.activated_by ?? '시스템';
  const phrase = {
    restore: `v${a.from_version_no} → v${a.to_version_no} 적용`,
    replace: `새 버전 v${a.to_version_no} 적용`,
    upload: `최초 v${a.to_version_no} 적용`,
    baseline: `v${a.to_version_no} 기준 상태 등록`,
  }[a.operation_type] || a.operation_type;
  return `${a.activated_at || '-'} · ${who} · ${phrase}`;
};

// 복원 API 업무 오류 {"detail":{"code","message"}}, 기존 API의 문자열 detail, 검증 오류의 배열 detail을 함께 처리
const parseApiError = (error) => {
  const status = error?.response?.status ?? null;
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) return { status, code: 'INVALID_REQUEST', message: '요청 형식이 올바르지 않습니다.' };
  if (detail && typeof detail === 'object') return { status, code: detail.code || null, message: detail.message || '' };
  return { status, code: null, message: typeof detail === 'string' ? detail : '' };
};

const newIdempotencyKey = () => {
  try {
    return crypto.randomUUID();
  } catch {
    return `restore-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }
};

const isActiveOperation = (op) => Boolean(op && ['queued', 'running'].includes(op.status));

export const useDocumentVersionRestore = ({ api, documents, loadDocuments, showAlert }) => {
  // ── B 버전 이력 ──
  const historyDoc = ref(null); // 이력을 연 목록 행
  const history = ref(null); // GET versions 응답
  const historyState = ref('idle'); // loading | error | ready
  const historyNotice = ref(''); // 접수 오류 등 경고 안내(비어 있으면 응답 기준 기본 문구)
  // ── C 버전 선택 ──
  const selectedVersionNo = ref(null);
  // ── D·E 복원 확인/진행/결과 창 ──
  const restoreDialog = ref(null);
  // ── E 처리 중 복원 작업(document_id → 작업)과 페이지 상단 결과 ──
  const restoreJobs = reactive({});
  const restoreResults = reactive({});
  // ── F 적용 이력 ──
  const activations = reactive({ open: false, loading: false, loaded: false, error: '', items: [], next: null, key: '' });

  let historyRequest = 0;
  let activationRequest = 0;
  let pollTimer = null;
  let pollDelay = POLL_INTERVAL_MS;
  let lastListWatch = 0;
  let disposed = false;

  const findDocument = (documentId) => (documents.value || []).find((d) => d.document_id === documentId);
  const docLabel = (doc) => doc?.product_model || doc?.filename || '';

  // ── A 목록 행 상태 ──
  const isRestorePending = (doc) => Boolean(restoreJobs[doc?.document_id] || (isActiveOperation(doc?.pending_operation) && doc.pending_operation.operation_type === 'restore'));
  // pending_operation(queued/running)이 있으면 [최신본 변경]·[삭제] 비활성
  const isDocumentBusy = (doc) => Boolean(isActiveOperation(doc?.pending_operation) || restoreJobs[doc?.document_id]);
  // 2026.11.09(woojin.jung) 추가 - 목록 "현재 버전" 칸 복원 처리 중 배지(최신본 변경 배지와 같은 자리)
  const restoreTargetNo = (doc) => restoreJobs[doc?.document_id]?.target ?? doc?.pending_operation?.target_version_no ?? null;

  // ── B 버전 이력 ──
  const isSelectable = (version) => Boolean(history.value?.can_restore && version && !version.is_active && version.can_restore);
  const selectedVersion = computed(() => (history.value?.versions || []).find((v) => v.version_no === selectedVersionNo.value && isSelectable(v)) || null);

  const historyNoticeText = computed(() => {
    if (historyNotice.value) return historyNotice.value;
    const h = history.value;
    if (h?.restore_block_code === 'JOB_IN_PROGRESS') {
      return h.pending_operation?.operation_type === 'restore' ? '버전 적용 작업이 진행 중입니다.' : '새 버전 등록 작업이 진행 중입니다. 완료 후 다른 버전을 적용할 수 있습니다.';
    }
    if (!h || !h.restore_supported) return '현재 적용 중인 버전만 검색과 질의응답에 사용됩니다.';
    return '현재 적용 중인 버전만 RAG 검색·답변에 사용됩니다. 다른 버전을 적용하면 검색 데이터와 출처도 함께 전환됩니다.';
  });

  const closeHistory = () => {
    historyRequest += 1;
    activationRequest += 1;
    historyDoc.value = null;
    history.value = null;
    historyState.value = 'idle';
    historyNotice.value = '';
    selectedVersionNo.value = null;
    activations.open = false;
    activations.loading = false;
  };

  // 문서가 없거나 볼 수 없음(코드 없는 404) → 이력창 닫고 목록 갱신
  const handleDocumentGone = (message) => {
    restoreDialog.value = null;
    closeHistory();
    showAlert(message || '해당 문서를 찾을 수 없습니다.', 'error');
    loadDocuments();
  };

  const loadHistory = async () => {
    const doc = historyDoc.value;
    if (!doc) return;
    const request = ++historyRequest;
    historyState.value = 'loading';
    selectedVersionNo.value = null; // 응답을 새로 받으면 선택 초기화
    try {
      const res = await api.documentVersions(doc.document_id);
      if (disposed || request !== historyRequest) return;
      history.value = res.data || null;
      historyState.value = 'ready';
    } catch (error) {
      if (disposed || request !== historyRequest) return;
      const { status, code, message } = parseApiError(error);
      if (status === 404 && !code) {
        handleDocumentGone(message);
        return;
      }
      historyState.value = 'error'; // 실패를 빈 목록으로 그리지 않음
    }
  };

  const openHistory = (doc) => {
    if (!doc) return;
    historyDoc.value = doc;
    history.value = null;
    historyNotice.value = '';
    activations.open = false;
    loadHistory();
  };

  // ── C 버전 선택 ──
  const selectVersion = (version) => {
    if (!isSelectable(version)) return;
    selectedVersionNo.value = version.version_no;
    historyNotice.value = '';
  };

  // ── D 복원 확인 ── 확인창 값은 B 응답만 사용
  const openRestoreConfirm = () => {
    const h = history.value;
    const row = selectedVersion.value;
    if (!h || !row || restoreJobs[h.document_id]) return;
    restoreDialog.value = {
      stage: 'confirm',
      documentId: h.document_id,
      productModel: h.product_model || historyDoc.value?.product_model || '',
      target: row.version_no,
      current: h.current_version_no,
      currentFilename: h.current_original_filename,
      targetFilename: row.original_filename,
      nextVersionNo: h.next_version_no,
      expectedRevision: h.activation_revision,
      idempotencyKey: null,
      submitting: false,
      error: '',
      jobId: null,
      from: h.current_version_no,
      step: 'queued',
      pollFailed: false,
      result: null,
      keptVersionNo: null,
    };
  };

  const closeRestoreDialog = () => {
    const dialog = restoreDialog.value;
    if (!dialog || dialog.submitting) return;
    restoreDialog.value = null;
  };

  const schedulePoll = (delay = pollDelay) => {
    clearTimeout(pollTimer);
    pollTimer = null;
    if (disposed || !Object.keys(restoreJobs).length) return;
    pollTimer = setTimeout(pollRestoreJobs, delay);
  };

  const trackRestore = (documentId, job) => {
    if (!job.jobId || restoreJobs[documentId]?.jobId === job.jobId) return;
    delete restoreResults[documentId];
    restoreJobs[documentId] = { listOnly: false, pollFailed: false, ...job };
    pollDelay = POLL_INTERVAL_MS;
    if (!pollTimer) schedulePoll();
  };

  const submitRestore = async () => {
    const dialog = restoreDialog.value;
    if (!dialog || dialog.stage !== 'confirm' || dialog.submitting || restoreJobs[dialog.documentId]) return;
    dialog.submitting = true; // 클릭 즉시 비활성(중복 클릭 방지)
    dialog.error = '';
    dialog.idempotencyKey ||= newIdempotencyKey();
    try {
      const res = await api.restoreDocumentVersion(dialog.documentId, dialog.target, {
        expected_current_version_no: dialog.current,
        expected_activation_revision: dialog.expectedRevision,
        idempotency_key: dialog.idempotencyKey,
      });
      if (disposed) return;
      const data = res.data || {};
      const from = data.from_version_no ?? dialog.current;
      const target = data.target_version_no ?? dialog.target;
      Object.assign(dialog, { stage: 'progress', submitting: false, jobId: data.job_id, from, target, step: data.current_step || 'queued' });
      trackRestore(dialog.documentId, {
        jobId: data.job_id, target, from, step: data.current_step || 'queued', label: docLabel(findDocument(dialog.documentId) || historyDoc.value),
      });
      if (historyDoc.value?.document_id === dialog.documentId) loadHistory(); // 진행 중 상태(JOB_IN_PROGRESS) 반영
    } catch (error) {
      if (disposed) return;
      handleSubmitError(dialog, error);
    }
  };

  function handleSubmitError(dialog, error) {
    dialog.submitting = false;
    if (!error?.response) {
      // HTTP 타임아웃·연결 끊김: 접수 여부를 알 수 없으므로 같은 키를 유지해 재전송(같은 job_id로 응답)
      dialog.error = '서버 응답을 받지 못했습니다. 다시 누르면 같은 요청으로 접수 여부를 확인합니다.';
      return;
    }
    const { status, code, message } = parseApiError(error);
    if (status === 404 && !code) {
      handleDocumentGone(message);
      return;
    }
    if (REFRESH_CODES.has(code)) {
      // 선택 초기화 후 이력 재조회 · 사용자가 다시 확인(예상값을 고쳐 자동 재실행·새 키 자동 생성 금지)
      restoreDialog.value = null;
      historyNotice.value = message || '버전 상태가 변경되었습니다. 버전 이력을 다시 확인하세요.';
      loadHistory();
      if (['JOB_IN_PROGRESS', 'ALREADY_ACTIVE', 'STATE_CHANGED'].includes(code)) loadDocuments();
      return;
    }
    if (code === 'INVALID_REQUEST') {
      dialog.idempotencyKey = null;
      dialog.error = message || '요청 형식이 올바르지 않습니다.';
      return;
    }
    // 503 DEPENDENCY_UNAVAILABLE·5xx 등 일시 장애: 같은 키로 다시 시도할 수 있게 둔다
    dialog.error = message || '버전 적용을 요청하지 못했습니다. 잠시 후 다시 시도하세요.';
  }

  // ── E 진행 ──
  async function pollRestoreJobs() {
    pollTimer = null;
    const finished = [];
    let pollFailed = false;
    let listWatch = false;
    await Promise.all(Object.entries(restoreJobs).map(async ([documentId, job]) => {
      if (job.listOnly) {
        listWatch = true;
        return;
      }
      try {
        const res = await api.getIngestJob(job.jobId);
        if (disposed || restoreJobs[documentId] !== job) return;
        const data = res.data || {};
        job.pollFailed = false;
        job.step = data.current_step || job.step;
        if (data.from_version_no != null) job.from = data.from_version_no;
        if (data.status === 'completed' || data.status === 'failed') finished.push([documentId, job, data]);
      } catch (error) {
        if (disposed || restoreJobs[documentId] !== job) return;
        const status = error?.response?.status;
        if (status === 403) {
          // 다른 사용자가 접수한 복원은 작업 조회 권한이 없다 → 목록의 pending_operation으로 끝났는지 확인
          job.listOnly = true;
          listWatch = true;
        } else if (status === 404) {
          // 작업이 없어짐: 결과를 단정하지 않고 목록·이력 재조회로 현재 상태를 보여 준다
          delete restoreJobs[documentId];
          listWatch = true;
          lastListWatch = 0;
          if (restoreDialog.value?.jobId === job.jobId) restoreDialog.value = null;
          if (historyDoc.value?.document_id === documentId) loadHistory();
          return;
        } else {
          // HTTP 타임아웃·폴링 장애는 작업 실패가 아님(상태 확인 중으로 두고 재시도)
          job.pollFailed = true;
          pollFailed = true;
        }
      }
      const dialog = restoreDialog.value;
      if (dialog?.stage === 'progress' && dialog.jobId === job.jobId) Object.assign(dialog, { step: job.step, from: job.from, pollFailed: job.pollFailed });
    }));
    if (disposed) return;

    const now = Date.now();
    if (finished.length || (listWatch && now - lastListWatch >= POLL_MAX_INTERVAL_MS)) {
      lastListWatch = now;
      await loadDocuments(); // 목록 재조회 → syncPendingRestores가 끝난 다른 사용자 복원을 정리
      if (disposed) return;
    }
    for (const [documentId, job, data] of finished) await finishRestore(documentId, job, data);
    if (disposed) return;

    pollDelay = pollFailed ? Math.min(pollDelay * 1.5, POLL_MAX_INTERVAL_MS) : POLL_INTERVAL_MS;
    schedulePoll();
  }

  async function finishRestore(documentId, job, data) {
    delete restoreJobs[documentId];
    const success = data.status === 'completed';
    const historyOpen = historyDoc.value?.document_id === documentId;
    if (historyOpen) {
      await loadHistory();
      if (disposed) return;
      if (activations.open) loadActivations({ force: true });
    }
    // 실패의 "유지 버전"은 재조회한 version_no(from_version_no 아님)
    const kept = (historyOpen && history.value?.current_version_no) || findDocument(documentId)?.version_no || job.from;

    // 2026.11.09(woojin.jung) 수정 - 결과는 한 곳에만 안내: 진행창이 열려 있으면 창에서, 닫았으면 페이지 상단에서(토스트 중복 제거)
    const dialog = restoreDialog.value;
    if (dialog?.stage === 'progress' && dialog.jobId === job.jobId) {
      Object.assign(dialog, success
        ? { stage: 'success', result: data.result || {} }
        : { stage: 'failure', error: data.error || '버전 적용 처리 중 오류가 발생했습니다.', keptVersionNo: kept });
      return;
    }
    restoreResults[documentId] = success
      ? { type: 'success', label: job.label, text: `v${job.target}${josaRo(job.target)} 적용되었습니다. 검색과 질의응답에 반영되었습니다.` }
      : { type: 'error', label: job.label, text: `버전 적용 실패(v${job.target}) · 현재 v${kept}${josaEul(kept)} 유지합니다. 버전 이력에서 다시 시도하세요.` };
  }

  // 2026.11.09(woojin.jung) 추가 - 페이지 상단 복원 결과 닫기
  const dismissResult = (documentId) => {
    delete restoreResults[documentId];
  };

  // 목록을 다시 읽을 때 처리 중인 복원은 폴링을 이어간다(새로고침 복원)
  const syncPendingRestores = (docs) => {
    for (const doc of docs || []) {
      const op = doc.pending_operation;
      const tracked = restoreJobs[doc.document_id];
      if (isActiveOperation(op) && op.operation_type === 'restore') {
        if (!tracked || tracked.jobId !== op.job_id) {
          trackRestore(doc.document_id, { jobId: op.job_id, target: op.target_version_no, from: doc.version_no, step: op.current_step, label: docLabel(doc) });
        }
      } else if (tracked?.listOnly) {
        // 조회 권한 없는 복원이 끝남 — 목록은 이미 최신. 결과는 알 수 없어 안내 없이 정리
        delete restoreJobs[doc.document_id];
        if (historyDoc.value?.document_id === doc.document_id) loadHistory();
      } else if (
        // 2026.11.09(woojin.jung) 추가 - 열린 이력 창이 "작업 진행 중"인데 목록상 작업이 끝났으면(최신본 변경 완료 등) 이력을 다시 읽어 복원을 열어 준다
        historyDoc.value?.document_id === doc.document_id &&
        historyState.value === 'ready' &&
        history.value?.restore_block_code === 'JOB_IN_PROGRESS' &&
        !isActiveOperation(op) &&
        !doc.pending_version_no &&
        !tracked
      ) {
        loadHistory();
      }
    }
  };

  // [닫고 계속하기]·Esc = 창만 닫기(작업 취소 아님) → 페이지 상단 상태 표시 + 폴링 계속
  const continueInBackground = () => {
    restoreDialog.value = null;
    closeHistory();
  };

  // [버전 이력 확인]
  const completeRestore = () => {
    const dialog = restoreDialog.value;
    restoreDialog.value = null;
    if (dialog && historyDoc.value?.document_id !== dialog.documentId) {
      const doc = findDocument(dialog.documentId);
      if (doc) openHistory(doc);
    }
  };

  // [다시 시도] = 이력 재조회 → 선택 가능 확인 → 확인창 → 새 idempotency_key로 POST(/jobs/{id}/retry 사용 금지)
  const retryRestore = async () => {
    const dialog = restoreDialog.value;
    if (!dialog) return;
    const target = dialog.target;
    await loadHistory();
    if (disposed || restoreDialog.value !== dialog) return;
    const row = (history.value?.versions || []).find((v) => v.version_no === target);
    if (historyState.value === 'ready' && isSelectable(row)) {
      selectedVersionNo.value = target;
      openRestoreConfirm();
    } else {
      restoreDialog.value = null;
    }
  };

  // 페이지 상단(#pageStatus): 창을 닫은 뒤 진행 중 안내, 끝나면 결과
  const pageStatuses = computed(() => {
    const dialog = restoreDialog.value;
    const items = [];
    for (const [documentId, job] of Object.entries(restoreJobs)) {
      if (dialog?.documentId === documentId) continue; // 진행창이 열려 있으면 창에서 보여 준다
      const current = findDocument(documentId)?.version_no ?? job.from;
      items.push({ kind: 'restore', documentId, type: 'info', running: true, label: job.label, text: `v${job.target} 적용 처리 중 · 현재 v${current}${josaRo(current)} 서비스 중` });
    }
    for (const [documentId, result] of Object.entries(restoreResults)) {
      if (!restoreJobs[documentId]) items.push({ kind: 'restore', documentId, running: false, ...result });
    }
    return items;
  });

  // ── F 적용 이력 ──
  const activationKey = () => `${historyDoc.value?.document_id}:${history.value?.activation_revision ?? ''}`;

  async function loadActivations({ more = false, force = false } = {}) {
    const doc = historyDoc.value;
    if (!doc) return;
    const key = activationKey();
    if (!more && !force && activations.loaded && activations.key === key) return; // 같은 문서·같은 revision → 재사용
    if (more && (activations.loading || activations.next == null)) return;
    const request = ++activationRequest;
    activations.loading = true;
    activations.error = '';
    if (!more) Object.assign(activations, { items: [], next: null, loaded: false });
    try {
      const params = { limit: ACTIVATION_PAGE_SIZE };
      if (more) params.before_activation_id = activations.next;
      const res = await api.documentActivations(doc.document_id, params);
      if (disposed || request !== activationRequest) return;
      const page = res.data?.activations || [];
      activations.items = more ? activations.items.concat(page) : page;
      activations.next = res.data?.next_before_activation_id ?? null;
      activations.loaded = true;
      activations.key = key;
    } catch {
      if (disposed || request !== activationRequest) return;
      activations.error = '적용 이력을 불러오지 못했습니다.';
    } finally {
      if (!disposed && request === activationRequest) activations.loading = false;
    }
  }

  const toggleActivations = (open) => {
    activations.open = open;
    if (open) loadActivations();
  };

  onScopeDispose(() => {
    disposed = true;
    clearTimeout(pollTimer);
  });

  return {
    // A
    isRestorePending, isDocumentBusy, restoreTargetNo, syncPendingRestores, pageStatuses, dismissResult,
    // B·C
    historyDoc, history, historyState, historyNoticeText, historyNotice, selectedVersionNo, selectedVersion,
    openHistory, closeHistory, loadHistory, isSelectable, selectVersion,
    // D·E
    restoreDialog, restoreJobs, openRestoreConfirm, closeRestoreDialog, submitRestore,
    continueInBackground, completeRestore, retryRestore,
    // F
    activations, toggleActivations, loadActivations,
  };
};
