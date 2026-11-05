// 2026.10.19(sooyeon.choi) 추가 - 문서 목록 [최신본 변경]·[버전 이력]
//   - 최신본 변경: 문서 행에서 새 파일을 골라 접수 → 서버가 처리·검증을 마친 뒤에만 다음 버전으로 전환한다.
//     처리 중에는 기존 최신본으로 검색·답변하고, 실패하면 기존 최신본을 유지한다(화면은 결과만 안내).
//   - 접수한 작업은 기존 작업 조회 API로 3초마다 확인하고, 끝나면 목록을 다시 읽는다.
//     새로고침 후에도 목록의 pending_job_id로 확인을 이어간다(본인·관리자 작업만 조회 가능).
//   - 버전 이력: 실제 버전 목록 조회.
import { onScopeDispose, reactive, ref } from 'vue';

const POLL_INTERVAL_MS = 3000;
const errorDetail = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' ? detail : (error?.message || fallback);
};

export const VERSION_STATUS_LABELS = {
  active: '적용 중',
  retired: '이전 버전',
  building: '처리 중',
  ready: '전환 대기',
  failed: '처리 실패',
};

export const useDocumentVersions = ({ api, loadDocuments, showAlert, pollIntervalMs = POLL_INTERVAL_MS }) => {
  // ── 최신본 변경 대화상자 ──
  const replaceTarget = ref(null);
  const replaceFile = ref(null);
  const replaceSubmitting = ref(false);
  const replaceError = ref('');

  // ── 처리 중 작업 확인 ──
  const versionJobs = reactive({}); // document_id → { jobId, versionNo, filename }
  let timer = null;
  let disposed = false;

  // ── 버전 이력 대화상자 ──
  const historyTarget = ref(null);
  const historyItems = ref([]);
  const historyLoading = ref(false);
  const historyError = ref('');

  const isVersionPending = (doc) => Boolean(doc?.pending_version_no || versionJobs[doc?.document_id]);
  const pendingVersionNo = (doc) => versionJobs[doc?.document_id]?.versionNo || doc?.pending_version_no || null;

  const openReplaceDialog = (doc) => {
    if (!doc?.can_edit || isVersionPending(doc)) return;
    replaceTarget.value = doc;
    replaceFile.value = null;
    replaceError.value = '';
  };
  const closeReplaceDialog = () => {
    if (replaceSubmitting.value) return;
    replaceTarget.value = null;
    replaceFile.value = null;
    replaceError.value = '';
  };
  const onReplaceFileChange = (event) => {
    replaceFile.value = event.target.files?.[0] || null;
    replaceError.value = '';
  };

  const schedulePoll = () => {
    clearTimeout(timer);
    if (disposed || !Object.keys(versionJobs).length) return;
    timer = setTimeout(pollJobs, pollIntervalMs);
  };

  const trackJob = (documentId, jobId, versionNo, filename) => {
    if (!jobId || versionJobs[documentId]?.jobId === jobId) return;
    versionJobs[documentId] = { jobId, versionNo, filename };
    schedulePoll();
  };

  async function pollJobs() {
    const entries = Object.entries(versionJobs);
    const messages = []; // 목록을 다시 읽은 뒤 안내(안내 시점에 목록이 이미 새 버전)
    await Promise.all(entries.map(async ([documentId, job]) => {
      try {
        const res = await api.getIngestJob(job.jobId);
        if (disposed) return;
        const status = res.data?.status;
        if (status === 'completed') {
          delete versionJobs[documentId];
          messages.push([`"${job.filename}" 최신본이 v${job.versionNo}(으)로 변경되었습니다.`, 'success']);
        } else if (status === 'failed') {
          delete versionJobs[documentId];
          messages.push([`최신본 변경 실패(v${job.versionNo}): ${res.data?.error || '처리 중 오류'} — 기존 최신본을 그대로 사용합니다.`, 'error']);
        }
      } catch (error) {
        // 다른 사용자가 접수한 작업(403)·없는 작업(404)은 확인을 멈추고 목록 새로고침으로 상태를 본다
        if ([403, 404].includes(error?.response?.status)) {
          delete versionJobs[documentId];
        }
      }
    }));
    if (disposed) return;
    if (messages.length) {
      await loadDocuments();
      if (disposed) return;
      messages.forEach(([message, type]) => showAlert(message, type));
    }
    schedulePoll();
  }

  // 목록을 다시 읽을 때 처리 중인 본인 작업은 확인을 이어간다(새로고침 복원)
  const syncPendingJobs = (docs) => {
    for (const doc of docs || []) {
      if (doc.pending_job_id && doc.can_edit) {
        trackJob(doc.document_id, doc.pending_job_id, doc.pending_version_no, doc.filename);
      }
    }
  };

  const submitReplace = async () => {
    const doc = replaceTarget.value;
    if (!doc || !replaceFile.value || replaceSubmitting.value) return;
    replaceSubmitting.value = true;
    replaceError.value = '';
    try {
      const data = new FormData();
      data.append('file', replaceFile.value);
      const res = await api.replaceDocumentVersion(doc.document_id, data);
      if (disposed) return;
      const { job_id: jobId, version_no: versionNo } = res.data || {};
      doc.pending_version_no = versionNo;
      doc.pending_job_id = jobId;
      trackJob(doc.document_id, jobId, versionNo, replaceFile.value.name);
      replaceSubmitting.value = false;
      closeReplaceDialog();
      showAlert(`최신본 변경(v${versionNo})이 접수되었습니다. 처리가 끝나면 다음 버전으로 적용됩니다.`, 'success');
    } catch (error) {
      if (disposed) return;
      replaceError.value = errorDetail(error, '최신본 변경을 접수하지 못했습니다.');
    } finally {
      if (!disposed) replaceSubmitting.value = false;
    }
  };

  let historyRequest = 0; // 늦게 도착한 이전 조회 결과는 버린다
  const openVersionHistory = async (doc) => {
    if (!doc) return;
    const request = ++historyRequest;
    historyTarget.value = doc;
    historyItems.value = [];
    historyError.value = '';
    historyLoading.value = true;
    try {
      const res = await api.documentVersions(doc.document_id);
      if (disposed || request !== historyRequest) return;
      historyItems.value = res.data?.versions || [];
    } catch (error) {
      if (disposed || request !== historyRequest) return;
      historyError.value = errorDetail(error, '버전 이력을 불러오지 못했습니다.');
    } finally {
      if (!disposed && request === historyRequest) historyLoading.value = false;
    }
  };
  const closeVersionHistory = () => {
    historyRequest += 1;
    historyTarget.value = null;
    historyItems.value = [];
    historyError.value = '';
  };

  onScopeDispose(() => {
    disposed = true;
    clearTimeout(timer);
  });

  return {
    replaceTarget, replaceFile, replaceSubmitting, replaceError,
    openReplaceDialog, closeReplaceDialog, onReplaceFileChange, submitReplace,
    versionJobs, isVersionPending, pendingVersionNo, syncPendingJobs,
    historyTarget, historyItems, historyLoading, historyError, openVersionHistory, closeVersionHistory,
    versionStatusLabel: (status) => VERSION_STATUS_LABELS[status] || status,
  };
};
