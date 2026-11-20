// 2026.10.19(sooyeon.choi) 추가 - 문서 목록 [최신본 변경]·[버전 이력]
//   - 최신본 변경: 문서 행에서 새 파일을 골라 접수 → 서버가 처리·검증을 마친 뒤에만 다음 버전으로 전환한다.
//     처리 중에는 기존 최신본으로 검색·답변하고, 실패하면 기존 최신본을 유지한다(화면은 결과만 안내).
//   - 접수한 작업은 기존 작업 조회 API로 3초마다 확인하고, 끝나면 목록을 다시 읽는다.
//     새로고침 후에도 목록의 pending_job_id로 확인을 이어간다(본인·관리자 작업만 조회 가능).
//   - 버전 이력·이전 버전 복원은 useDocumentVersionRestore.js(2026.11.09 woojin.jung)로 이동.
//   - 2026.11.09(woojin.jung) 수정 - 진행·결과 안내를 이전 버전 복원과 같은 방식(페이지 상단 상태 줄, 결과는 닫기 전까지 유지)으로 통일
import { computed, nextTick, onScopeDispose, reactive, ref } from 'vue';
import { josaEul, josaRo } from './useDocumentVersionRestore';
import { handleDialogKeydown, restoreFocus } from '../utils/dialogKeydown';

const POLL_INTERVAL_MS = 3000;
// 2026.11.09(woojin.jung) 추가 - 작업을 직접 확인할 수 없는 처리 중 문서(다른 사용자 작업 등)는 목록 재조회로 완료를 확인
const LIST_WATCH_INTERVAL_MS = 5000;
const errorDetail = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' ? detail : (error?.message || fallback);
};

const fileExtension = (name) => (name || '').split('.').pop().toLowerCase();
const SPREADSHEET_EXTENSIONS = new Set(['xlsx', 'xlsm', 'xltx', 'xltm', 'xls']);
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'tiff', 'bmp', 'webp']);
const fileKind = (name) => {
  const ext = fileExtension(name);
  if (ext === 'pdf') return 'PDF';
  if (SPREADSHEET_EXTENSIONS.has(ext)) return 'Excel';
  if (IMAGE_EXTENSIONS.has(ext)) return '이미지';
  if (['doc', 'docx'].includes(ext)) return 'Word';
  if (['ppt', 'pptx'].includes(ext)) return 'PowerPoint';
  return ext.toUpperCase();
};

// validateFile(file) → 오류 문구('' = 통과). 새 문서 업로드와 같은 확장자·크기 규칙(useDocumentUpload.replacementFileError)
export const useDocumentVersions = ({ api, documents, loadDocuments, validateFile = () => '', pollIntervalMs = POLL_INTERVAL_MS }) => {
  // ── 최신본 변경 대화상자 ──
  const replaceTarget = ref(null);
  const replaceFile = ref(null);
  const replaceSubmitting = ref(false);
  const replaceError = ref('');
  // 2026.11.09(woojin.jung) 추가 - 새 파일이 등록될 버전 번호(복원 뒤에는 현재 버전+1이 아닐 수 있다). 조회 실패 시 null
  const replaceNextVersionNo = ref(null);
  let replaceReturnFocus = null;

  // ── 처리 중 작업 확인 ──
  const versionJobs = reactive({}); // document_id → { jobId, versionNo, filename }
  const replaceResults = reactive({}); // document_id → 페이지 상단 결과 { type, label, text }
  let timer = null;
  let listTimer = null;
  const unwatchableJobs = new Set(); // 조회가 막힌(403·404) 작업 — 다시 추적하지 않고 목록 재조회로만 확인
  let disposed = false;

  const findDocument = (documentId) => (documents.value || []).find((d) => d.document_id === documentId);
  const docLabel = (doc) => doc?.product_model || doc?.filename || '';

  const isVersionPending = (doc) => Boolean(doc?.pending_version_no || versionJobs[doc?.document_id]);
  const pendingVersionNo = (doc) => versionJobs[doc?.document_id]?.versionNo || doc?.pending_version_no || null;

  const openReplaceDialog = (doc) => {
    if (!doc?.can_edit || isVersionPending(doc)) return;
    replaceReturnFocus = document.activeElement;
    replaceTarget.value = doc;
    replaceFile.value = null;
    replaceError.value = '';
    replaceNextVersionNo.value = null;
    loadNextVersionNo(doc);
  };
  const loadNextVersionNo = async (doc) => {
    try {
      const res = await api.documentVersions(doc.document_id);
      if (!disposed && replaceTarget.value === doc) replaceNextVersionNo.value = res.data?.next_version_no ?? null;
    } catch {
      // 번호 안내만 빠진다(접수는 서버가 번호를 정한다)
    }
  };
  const closeReplaceDialog = () => {
    if (replaceSubmitting.value) return;
    replaceTarget.value = null;
    replaceFile.value = null;
    replaceError.value = '';
    replaceNextVersionNo.value = null;
    // 2026.11.09(woojin.jung) 추가 - 닫으면 창을 연 버튼으로 포커스를 되돌린다(이력·복원 창과 동일)
    const returnFocus = replaceReturnFocus;
    replaceReturnFocus = null;
    nextTick(() => restoreFocus(returnFocus));
  };
  // 2026.11.09(woojin.jung) 수정 - 고르는 즉시 새 문서 업로드와 같은 규칙으로 검사(올린 뒤에 거절되지 않게)
  const onReplaceFileChange = (event) => {
    const file = event.target.files?.[0] || null;
    const error = validateFile(file);
    replaceFile.value = error ? null : file;
    replaceError.value = error;
    if (error) event.target.value = ''; // 같은 파일을 다시 골라도 change가 일어나게
  };
  // 2026.11.09(woojin.jung) 추가 - 안내 문구를 버전 번호로 표시("다음 버전"은 현재 적용 버전 기준인지 알 수 없어 혼동)
  //   예) v1 적용 중·v4까지 있음 → v5로 등록, v2~v4는 이력에 그대로 남는다
  const replaceHint = computed(() => {
    const target = replaceTarget.value;
    if (!target) return '';
    const current = target.version_no ?? 1;
    const next = replaceNextVersionNo.value;
    const kept = `처리 중에는 지금 적용 중인 v${current}${josaRo(current)} 검색·답변하고, 실패하면 v${current}${josaEul(current)} 그대로 유지합니다.`;
    if (!next) return `새 파일은 새 버전으로 등록되고, 처리가 완료되면 새 버전으로 적용됩니다. ${kept}`;
    const skipped = next - current > 1 ? ` 기존 v1~v${next - 1} 버전은 버전 이력에 그대로 남습니다.` : '';
    return `새 파일은 v${next}${josaRo(next)} 등록되고, 처리가 완료되면 v${next}${josaRo(next)} 적용됩니다. ${kept}${skipped}`;
  });
  // 2026.11.09(woojin.jung) 추가 - 기존 파일과 형식이 다르면 알림(막지는 않음, 문서 유형은 서버가 자동 판별)
  const replaceFormatWarning = computed(() => {
    const target = replaceTarget.value;
    const file = replaceFile.value;
    if (!target || !file) return '';
    const before = fileKind(target.filename);
    const after = fileKind(file.name);
    return before === after ? '' : `기존 파일은 ${before}, 새 파일은 ${after}입니다. 같은 문서의 새 버전이 맞는지 확인하세요.`;
  });

  // 2026.11.09(woojin.jung) 추가 - Esc로 닫기·Tab 포커스를 창 안에 유지(이력·복원 창과 동일)
  const onReplaceKeydown = (event) => handleDialogKeydown(event, closeReplaceDialog);

  const schedulePoll = () => {
    clearTimeout(timer);
    if (disposed || !Object.keys(versionJobs).length) return;
    timer = setTimeout(pollJobs, pollIntervalMs);
  };

  const trackJob = (documentId, jobId, versionNo, filename) => {
    if (!jobId || versionJobs[documentId]?.jobId === jobId) return;
    delete replaceResults[documentId];
    versionJobs[documentId] = { jobId, versionNo, filename };
    schedulePoll();
  };

  async function pollJobs() {
    const entries = Object.entries(versionJobs);
    const finished = []; // 목록을 다시 읽은 뒤 결과 안내(유지 버전은 재조회한 version_no)
    let untracked = false; // 확인을 멈춘 작업이 생기면 목록 재조회로 넘긴다
    await Promise.all(entries.map(async ([documentId, job]) => {
      try {
        const res = await api.getIngestJob(job.jobId);
        if (disposed) return;
        const status = res.data?.status;
        if (status === 'completed' || status === 'failed') {
          delete versionJobs[documentId];
          finished.push([documentId, job, res.data]);
        }
      } catch (error) {
        // 다른 사용자가 접수한 작업(403)·없는 작업(404)은 확인을 멈추고 목록 새로고침으로 상태를 본다
        if ([403, 404].includes(error?.response?.status)) {
          delete versionJobs[documentId];
          unwatchableJobs.add(job.jobId);
          untracked = true;
        }
      }
    }));
    if (disposed) return;
    if (finished.length || untracked) {
      await loadDocuments();
      if (disposed) return;
    }
    for (const [documentId, job, data] of finished) {
      const doc = findDocument(documentId);
      const label = docLabel(doc) || job.filename;
      const n = job.versionNo;
      if (data.status === 'completed') {
        replaceResults[documentId] = { type: 'success', label, text: `새 버전 v${n}${josaRo(n)} 적용되었습니다. 검색과 질의응답에 반영되었습니다.` };
      } else {
        const kept = doc?.version_no ?? '-';
        const reason = data.error ? ` 사유: ${data.error}` : '';
        replaceResults[documentId] = { type: 'error', label, text: `새 버전 등록 실패(v${n}) · 현재 v${kept}${josaEul(kept)} 유지합니다.${reason}` };
      }
    }
    schedulePoll();
  }

  // 목록을 다시 읽을 때 처리 중인 본인 작업은 확인을 이어간다(새로고침 복원)
  const syncPendingJobs = (docs) => {
    for (const doc of docs || []) {
      if (doc.pending_job_id && doc.can_edit && !unwatchableJobs.has(doc.pending_job_id)) {
        trackJob(doc.document_id, doc.pending_job_id, doc.pending_version_no, doc.filename);
      }
    }
    // 2026.11.09(woojin.jung) 추가 - 직접 확인하지 않는 처리 중 문서가 남아 있으면 잠시 뒤 목록을 다시 읽는다
    //   (다시 읽으면 이 함수가 다시 불려 처리 중 문서가 없어질 때까지 이어진다)
    clearTimeout(listTimer);
    listTimer = null;
    if (disposed) return;
    if ((docs || []).some((doc) => doc.pending_version_no && !versionJobs[doc.document_id])) {
      listTimer = setTimeout(loadDocuments, LIST_WATCH_INTERVAL_MS);
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
      // 접수 안내는 페이지 상단 "처리 중" 상태 줄로 대신한다(복원과 동일)
      closeReplaceDialog();
    } catch (error) {
      if (disposed) return;
      replaceError.value = errorDetail(error, '새 버전 등록을 접수하지 못했습니다.');
    } finally {
      if (!disposed) replaceSubmitting.value = false;
    }
  };

  // 2026.11.09(woojin.jung) 추가 - 페이지 상단 상태 줄: 처리 중(다른 사용자 작업 포함)·결과
  const replaceStatuses = computed(() => {
    const items = [];
    for (const doc of documents.value || []) {
      if (!isVersionPending(doc)) continue;
      const current = doc.version_no ?? 1;
      items.push({
        kind: 'replace', documentId: doc.document_id, type: 'info', running: true, label: docLabel(doc),
        text: `새 버전 v${pendingVersionNo(doc)} 등록 처리 중 · 현재 v${current}${josaRo(current)} 서비스 중`,
      });
    }
    for (const [documentId, result] of Object.entries(replaceResults)) {
      if (!versionJobs[documentId]) items.push({ kind: 'replace', documentId, running: false, ...result });
    }
    return items;
  });

  const dismissReplaceResult = (documentId) => {
    delete replaceResults[documentId];
  };

  onScopeDispose(() => {
    disposed = true;
    clearTimeout(timer);
    clearTimeout(listTimer);
  });

  return {
    replaceTarget, replaceFile, replaceSubmitting, replaceError, replaceNextVersionNo, replaceFormatWarning, replaceHint,
    openReplaceDialog, closeReplaceDialog, onReplaceFileChange, onReplaceKeydown, submitReplace,
    versionJobs, isVersionPending, pendingVersionNo, syncPendingJobs,
    replaceStatuses, dismissReplaceResult,
  };
};
