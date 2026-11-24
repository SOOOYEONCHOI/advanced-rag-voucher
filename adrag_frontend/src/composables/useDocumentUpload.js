import { computed, onScopeDispose, ref, watch } from 'vue';

export const MAX_UPLOAD_FILES = 10;
const OOXML_EXTENSIONS = new Set(['xlsx', 'xlsm', 'xltx', 'xltm']);
const SUPPORTED_EXTENSIONS = new Set(['pdf', 'docx', 'doc', 'pptx', 'ppt', ...OOXML_EXTENSIONS, 'png', 'jpg', 'jpeg', 'tiff', 'bmp', 'webp']);
// 2026.10.02(woojin.jung) 수정 - 문서별 진행 막대를 처리 단계 스텝 인디케이터로 변경
export const UPLOAD_STEPS = [
  { key: 'prepare', label: '파일 준비', jobSteps: ['validate', 'parse'] },
  { key: 'chunk', label: '파싱·청킹', jobSteps: ['chunk'] },
  { key: 'embed', label: '임베딩', jobSteps: ['embed'] },
  { key: 'index', label: '저장', jobSteps: ['index'] },
];
export const DRAWING_UPLOAD_STEPS = [
  { key: 'prepare', label: '파일 준비', jobSteps: ['queued', 'validate', 'parse'] },
  { key: 'convert', label: '변환·보정', jobSteps: ['drawing_convert'] },
  { key: 'extract', label: '항목 추출', jobSteps: ['drawing_extract'] },
  { key: 'render', label: '도면 이미지', jobSteps: ['drawing_render'] },
  { key: 'store', label: '저장', jobSteps: ['drawing_store'] },
];
const DRAWING_ERROR_MESSAGES = {
  E_UNSUPPORTED_FORMAT: '도면 파일 형식이 아니거나 지원하지 않는 버전입니다.',
  E_CONVERT_FAILED: 'DWG를 변환하지 못했습니다. 원본을 CAD 프로그램에서 다시 저장(AutoCAD 2000~2018 형식)한 뒤 올려 주세요.',
  E_CONVERT_TIMEOUT: '변환 시간이 초과되었습니다. 도면이 너무 크면 나눠서 올려 주세요.',
  E_DXF_LOAD: '도면을 읽지 못했습니다. 원본 파일을 확인해 주세요.',
  E_EMPTY_DRAWING: '도면에 내용이 없습니다.',
};
const isPending = (item) => ['queued', 'running'].includes(item.status);
const canSubmit = (item) => ['selected', 'rejected'].includes(item.status);
const createClientId = () => {
  // getRandomValues also works on the existing LAN HTTP deployment.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};
// 2026.10.19(sooyeon.choi) 추가 - 파일별 모델명: 파일명에서 마지막 확장자만 뺀 기본값, 앞뒤 공백 제외 1~100자
//   서버(app/ingest/model_name.py)·Alembic 0004 백필과 같은 규칙. 길이는 문자(코드 포인트) 수로 센다.
export const MAX_MODEL_NAME_LENGTH = 100;
export const defaultModelName = (filename) =>
  String(filename || '')
    .replace(/\.[^.]+$/, '')
    .trim();
export const modelNameError = (value) => {
  const trimmed = String(value ?? '').trim();
  // 2026.10.20(woojin.jung) 수정 - 화면 용어 '모델명' → '모델명'(저장 키 product_model은 유지)
  if (!trimmed) return '모델명을 입력하세요.';
  if (Array.from(trimmed).length > MAX_MODEL_NAME_LENGTH) return `모델명은 ${MAX_MODEL_NAME_LENGTH}자 이하여야 합니다.`;
  return '';
};
const errorMessage = (error) => {
  const detail = error.response?.data?.detail;
  return typeof detail === 'string' ? detail : error.message || '요청 처리에 실패했습니다.';
};

// 2026.10.02(woojin.jung) 수정 - 일괄 처리 종료 시 결과 알림용 onSettled 콜백 추가
export const useDocumentUpload = ({ form, api, onCompleted, onSettled }) => {
  const uploadItems = ref([]);
  const selectionMessage = ref('');
  const isSubmitting = ref(false);
  const isMonitoring = ref(false);
  const monitorPaused = ref(false);
  const authBlocked = ref(false);
  const now = ref(Date.now());
  let disposed = false;
  let timer = null;
  let monitorController = null;
  const lifetimeController = new AbortController();

  const pendingItems = computed(() => uploadItems.value.filter(isPending));
  const submissionItems = computed(() => uploadItems.value.filter(canSubmit));

  // 2026.10.16(sooyeon.choi) 추가 - 서버가 엑셀 전용 처리기(backend 모드)를 쓰면 해당 확장자는
  //   문서 유형·파서 선택과 관계없이 전용 처리기로 처리된다. 조회 실패 시 기존 동작(docling) 유지.
  const excelIngestExtensions = ref([]);
  const drawingIngestExtensions = ref([]);
  const drawingMaxUploadMb = ref(100);
  // 2026.10.19(sooyeon.choi) 추가 - 문서 목록 [최신본 변경] 사용 여부(서버 설정, 조회 실패 시 켜 둠 — 서버가 다시 검사)
  const versionReplaceEnabled = ref(true);
  const loadIngestOptions = async () => {
    if (!api.ingestOptions) return;
    try {
      const res = await api.ingestOptions();
      excelIngestExtensions.value = res.data?.excel_ingest_extensions || [];
      drawingIngestExtensions.value = (res.data?.drawing_ingest_extensions || []).map((ext) => String(ext).toLowerCase());
      drawingMaxUploadMb.value = Number(res.data?.drawing_max_upload_mb) || 100;
      versionReplaceEnabled.value = res.data?.version_replace_enabled !== false;
    } catch {
      excelIngestExtensions.value = [];
      drawingIngestExtensions.value = [];
    }
  };
  loadIngestOptions();
  const fileExtension = (name) => (name || '').split('.').pop().toLowerCase();
  const isExcelIngestFile = (item) => excelIngestExtensions.value.includes(fileExtension(item.filename));
  const isDrawingFile = (item) => drawingIngestExtensions.value.includes(fileExtension(item.filename));
  const hasExcelIngestFile = computed(() => submissionItems.value.some(isExcelIngestFile));
  const allExcelIngestFiles = computed(() => submissionItems.value.length > 0 && submissionItems.value.every(isExcelIngestFile));
  const hasDrawingFile = computed(() => submissionItems.value.some(isDrawingFile));
  const allDrawingFiles = computed(() => submissionItems.value.length > 0 && submissionItems.value.every(isDrawingFile));
  const drawingEnabled = computed(() => drawingIngestExtensions.value.length > 0);
  const acceptedExtensions = computed(() => {
    const extensions = new Set([...SUPPORTED_EXTENSIONS, ...excelIngestExtensions.value, ...drawingIngestExtensions.value]);
    return [...extensions].map((ext) => `.${ext}`).join(',');
  });
  const isUploading = computed(() => isSubmitting.value || uploadItems.value.some((item) => item.retrying) || (isMonitoring.value && pendingItems.value.length > 0));
  const totalFileSize = computed(() => uploadItems.value.reduce((total, item) => total + item.size, 0));
  const summary = computed(() => {
    const count = (status) => uploadItems.value.filter((item) => item.status === status).length;
    return {
      total: uploadItems.value.length,
      submitted: uploadItems.value.filter((item) => item.jobId).length,
      selected: count('selected'),
      uploading: count('uploading'),
      queued: count('queued'),
      running: count('running'),
      completed: count('completed'),
      failed: count('failed'),
      rejected: count('rejected'),
      unknown: count('submission_unknown'),
      review: uploadItems.value.filter((item) => item.status === 'completed' && item.result?.drawing?.needs_review).length,
    };
  });
  const hasLongWait = computed(() => pendingItems.value.some((item) => now.value - item.submittedAt >= 1800000));
  // 2026.10.02(woojin.jung) 수정 - 중복 요약 문구를 0이 아닌 항목만 보여주는 요약 칩과 상태별 분할 막대로 통합
  const summaryChips = computed(() =>
    [
      { key: 'running', label: '처리 중', count: summary.value.running + summary.value.uploading },
      { key: 'queued', label: '대기', count: summary.value.queued + summary.value.selected },
      { key: 'failed', label: '실패', count: summary.value.failed + summary.value.rejected },
      { key: 'unknown', label: '확인 필요', count: summary.value.unknown },
      { key: 'review', label: '검수 필요', count: summary.value.review },
    ].filter((chip) => chip.count > 0)
  );
  const progressSegments = computed(() => {
    const total = summary.value.total || 1;
    return [
      { key: 'completed', count: summary.value.completed },
      { key: 'failed', count: summary.value.failed + summary.value.rejected + summary.value.unknown },
      { key: 'running', count: summary.value.running + summary.value.uploading },
    ]
      .filter((segment) => segment.count > 0)
      .map((segment) => ({ ...segment, width: (segment.count / total) * 100 }));
  });
  const uploadStepIndex = (item) => {
    const steps = stepsFor(item);
    if (item.status === 'completed') return steps.length;
    if (!['running', 'failed'].includes(item.status)) return -1;
    return Math.max(
      0,
      steps.findIndex((step) => step.jobSteps.includes(item.currentStep))
    );
  };
  const uploadStepState = (item, index) => {
    const current = uploadStepIndex(item);
    if (index < current) return 'done';
    if (index > current) return 'todo';
    return item.status === 'failed' ? 'error' : 'active';
  };
  const hasRowActions = computed(() => uploadItems.value.some((item) => ['selected', 'rejected', 'failed'].includes(item.status)));
  const progressAnimated = (item) => item.status === 'uploading' || (item.status === 'running' && isMonitoring.value && !authBlocked.value && !item.monitorError && !item.monitorBlocked);
  const uploadStateLabel = (item) => {
    if (isPending(item)) {
      if (authBlocked.value) return '인증 확인 필요';
      if (item.monitorError || item.monitorBlocked) return '상태 확인 지연';
      if (!isMonitoring.value) return '자동 확인 꺼짐';
    }
    // 2026.10.02(woojin.jung) 수정 - 내부 상태명(접수 거절·접수 미확정)을 사용자 용어로 변경
    if (item.status === 'completed' && item.result?.drawing?.needs_review) return '완료 · 확인 필요';
    return (
      { selected: '전송 전', uploading: '전송 중', queued: '대기', running: '처리 중', completed: '완료', failed: '실패', rejected: '업로드 거부', submission_unknown: '확인 필요' }[item.status] ||
      '확인 필요'
    );
  };

  const validationError = (item) => {
    if (!canSubmit(item)) return '';
    const ext = item.filename.split('.').pop().toLowerCase();
    if (isDrawingFile(item)) {
      return item.size > drawingMaxUploadMb.value * 1024 * 1024 ? `도면 파일은 ${drawingMaxUploadMb.value} MiB 이하여야 합니다.` : '';
    }
    // 2026.10.16(sooyeon.choi) 추가 - 엑셀 전용 처리기 대상은 문서 유형·파서 조건을 보지 않는다.
    if (isExcelIngestFile(item)) {
      return item.size > 100 * 1024 * 1024 ? 'Excel 파일은 100 MiB 이하여야 합니다.' : '';
    }
    if (ext === 'xls') return 'XLS 파일은 XLSX 형식으로 변환한 뒤 업로드하세요.';
    if (!SUPPORTED_EXTENSIONS.has(ext)) return `지원하지 않는 파일 형식: .${ext}`;
    if (form.parserType === 'pdfplumber' && ext !== 'pdf') return 'pdfplumber는 PDF 파일만 지원합니다.';
    if (OOXML_EXTENSIONS.has(ext)) {
      if (item.size > 100 * 1024 * 1024) return 'Excel 파일은 100 MiB 이하여야 합니다.';
      if (['law', 'manual', 'general'].includes(form.documentType)) {
        return "Excel 파일은 문서 유형을 '자동' 또는 '스프레드시트'로 선택하세요.";
      }
    } else if (form.documentType === 'spreadsheet') {
      return '스프레드시트 유형은 XLSX, XLSM, XLTX, XLTM 파일만 지원합니다.';
    }
    return '';
  };
  // 2026.11.09(woojin.jung) 추가 - [최신본 변경] 새 파일 검사(전송 전에 막을 수 있는 것만).
  //   서버는 기존 문서의 파서·문서 유형이 새 파일과 맞지 않으면 기본값(docling·자동)으로 바꾸므로 그 조건은 보지 않는다.
  const replacementFileError = (file) => {
    if (!file) return '';
    const ext = fileExtension(file.name);
    const tooLarge = file.size > 100 * 1024 * 1024 ? 'Excel 파일은 100 MiB 이하여야 합니다.' : '';
    if (drawingIngestExtensions.value.includes(ext)) {
      return file.size > drawingMaxUploadMb.value * 1024 * 1024 ? `도면 파일은 ${drawingMaxUploadMb.value} MiB 이하여야 합니다.` : '';
    }
    if (excelIngestExtensions.value.includes(ext)) return tooLarge;
    if (ext === 'xls') return 'XLS 파일은 XLSX 형식으로 변환한 뒤 업로드하세요.';
    if (!SUPPORTED_EXTENSIONS.has(ext)) return `지원하지 않는 파일 형식: .${ext}`;
    return OOXML_EXTENSIONS.has(ext) ? tooLarge : '';
  };
  const documentTypeCompatibilityError = computed(() => (submissionItems.value.some((item) => validationError(item)) ? '파일별 오류를 확인하고 파일 또는 공통 옵션을 수정하세요.' : ''));
  // 2026.10.19(sooyeon.choi) 추가 - 파일별 모델명 검증(전송 전·접수 거절 행만 수정·검증, 처리 중 행은 잠금)
  const canEditModel = (item) => canSubmit(item) && !isUploading.value;
  const modelError = (item) => (canSubmit(item) ? modelNameError(item.productModel) : '');
  const hasModelError = computed(() => submissionItems.value.some((item) => modelError(item)));
  // 2026.10.20(woojin.jung) 추가 - 파일명 기본값에서 바뀐 모델명만 [파일명으로 되돌리기] 노출
  const isModelNameEdited = (item) => String(item.productModel ?? '').trim() !== defaultModelName(item.filename);
  const resetModelName = (item) => {
    if (canEditModel(item)) item.productModel = defaultModelName(item.filename);
  };
  const canUpload = computed(() => submissionItems.value.length > 0 && !isUploading.value && Boolean(form.collectionName) && !documentTypeCompatibilityError.value && !hasModelError.value);

  const addFiles = (files) => {
    if (isUploading.value) return;
    const key = (file) => JSON.stringify([file.name, file.size, file.lastModified]);
    const seen = new Set(uploadItems.value.map((item) => key(item.file)));
    const additions = [];
    let duplicates = 0;
    for (const file of Array.from(files)) {
      if (seen.has(key(file))) {
        duplicates++;
        continue;
      }
      seen.add(key(file));
      additions.push(file);
    }
    if (uploadItems.value.length + additions.length > MAX_UPLOAD_FILES) {
      selectionMessage.value = '최대 10개까지 선택할 수 있습니다. 이번에 추가한 파일은 반영하지 않았습니다.';
      return;
    }
    uploadItems.value.push(
      ...additions.map((file) => ({
        clientId: createClientId(),
        file,
        filename: file.name,
        size: file.size,
        // 2026.10.19(sooyeon.choi) 추가 - 파일별 모델명 기본값(업로드 전 행마다 수정 가능)
        productModel: defaultModelName(file.name),
        status: 'selected',
        jobId: null,
        currentStep: null,
        result: null,
        error: null,
        monitorError: null,
        monitorBlocked: false,
        retrying: false,
        submittedAt: null,
      }))
    );
    selectionMessage.value = duplicates ? `이미 선택된 파일 ${duplicates}개를 제외했습니다.` : '';
  };
  const removeFile = (clientId) => {
    if (isUploading.value) return;
    uploadItems.value = uploadItems.value.filter((item) => item.clientId !== clientId || !canSubmit(item));
  };

  const stopMonitoring = () => {
    monitorPaused.value = true;
    isMonitoring.value = false;
    clearTimeout(timer);
    monitorController?.abort();
    monitorController = null;
  };

  const startMonitoring = () => {
    if (disposed || isMonitoring.value) return;
    monitorPaused.value = false;
    authBlocked.value = false;
    pendingItems.value.forEach((item) => {
      item.monitorBlocked = false;
    });
    const controller = new AbortController();
    monitorController = controller;
    isMonitoring.value = true;
    const poll = async () => {
      const items = pendingItems.value.filter((item) => !item.monitorBlocked);
      const results = await Promise.allSettled(items.map((item) => api.getIngestJob(item.jobId, { signal: controller.signal })));
      if (disposed || controller.signal.aborted) return;
      now.value = Date.now();
      let completed = false;
      results.forEach((result, index) => {
        const item = items[index];
        if (result.status === 'fulfilled') {
          const job = result.value.data;
          item.status = job.status;
          item.currentStep = job.current_step;
          item.result = job.result;
          item.error = DRAWING_ERROR_MESSAGES[job.error_code] || job.error;
          item.errorCode = job.error_code || null;
          item.monitorError = null;
          completed ||= job.status === 'completed';
        } else {
          const status = result.reason.response?.status;
          item.monitorError = errorMessage(result.reason);
          if (status === 401) authBlocked.value = true;
          if ([403, 404].includes(status)) item.monitorBlocked = true;
        }
      });
      if (completed) await onCompleted();
      if (disposed || controller.signal.aborted) return;
      if (authBlocked.value || (!isSubmitting.value && !pendingItems.value.some((item) => !item.monitorBlocked))) {
        stopMonitoring();
        if (!authBlocked.value && !pendingItems.value.length) onSettled?.(summary.value);
        return;
      }
      timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 0);
  };

  const clearFile = () => {
    if (isUploading.value || pendingItems.value.length) return;
    stopMonitoring();
    uploadItems.value = [];
    selectionMessage.value = '';
  };

  // 2026.10.06(woojin.jung) 수정 - 대화 주제 변경 시 처리가 끝난 문서 목록을 비워 초기 화면으로 전환
  // (아직 전송 전인 파일과 처리 중인 문서는 유지)
  watch(
    () => form.collectionName,
    () => {
      if (isUploading.value) return;
      const remaining = uploadItems.value.filter((item) => canSubmit(item) || isPending(item));
      if (remaining.length === uploadItems.value.length) return;
      uploadItems.value = remaining;
      selectionMessage.value = '';
      if (!pendingItems.value.length) stopMonitoring();
    }
  );

  const uploadDocument = async () => {
    if (!canUpload.value || disposed) return;
    isSubmitting.value = true;
    authBlocked.value = false;
    monitorPaused.value = false;
    const options = { ...form };
    const items = [...submissionItems.value];
    try {
      for (const item of items) {
        if (disposed || authBlocked.value) break;
        item.status = 'uploading';
        item.error = null;
        const data = new FormData();
        data.append('file', item.file);
        data.append('collection_name', options.collectionName);
        data.append('parser_type', options.parserType);
        data.append('document_type', options.documentType || 'auto');
        if (options.chunkSize) data.append('chunk_size', options.chunkSize);
        // 2026.10.19(sooyeon.choi) 수정 - 공통 제품 모델 대신 이 파일 행의 모델명을 전송 시작 시점 값으로 확정해 보낸다.
        //   접수 거절 후 재전송은 수정한 행 값을, 서버 작업 재시도는 서버에 저장된 원래 요청값을 쓴다.
        item.productModel = String(item.productModel ?? '').trim();
        data.append('product_model', item.productModel);
        try {
          const response = await api.uploadDocument(data, { signal: lifetimeController.signal });
          if (disposed) return;
          if (!response.data?.job_id) throw new Error('접수 응답에서 작업 ID를 확인할 수 없습니다.');
          item.jobId = response.data.job_id;
          item.status = 'queued';
          item.currentStep = 'queued';
          item.submittedAt = Date.now();
          if (!monitorPaused.value) startMonitoring();
        } catch (error) {
          if (disposed) return;
          const status = error.response?.status;
          item.status = [400, 401, 403, 413, 415, 422, 429].includes(status) ? 'rejected' : 'submission_unknown';
          item.error = errorMessage(error);
          if (status === 401) {
            authBlocked.value = true;
            stopMonitoring();
          }
        }
      }
    } finally {
      if (!disposed) isSubmitting.value = false;
    }
  };

  const retryIngestJob = async (item) => {
    if (disposed || isSubmitting.value || item.retrying || item.status !== 'failed') return;
    item.retrying = true;
    item.monitorError = null;
    try {
      await api.retryIngestJob(item.jobId, { signal: lifetimeController.signal });
      if (disposed) return;
      item.status = 'queued';
      item.currentStep = 'queued';
      item.error = null;
      item.submittedAt = Date.now();
      startMonitoring();
    } catch (error) {
      if (disposed) return;
      item.monitorError = errorMessage(error);
      // A retry response may be lost after the server accepted it. Reconcile by GET.
      try {
        const response = await api.getIngestJob(item.jobId, { signal: lifetimeController.signal });
        if (disposed) return;
        const job = response.data;
        item.status = job.status;
        item.currentStep = job.current_step;
        item.result = job.result;
        item.error = DRAWING_ERROR_MESSAGES[job.error_code] || job.error;
        item.errorCode = job.error_code || null;
        if (isPending(item)) startMonitoring();
        if (job.status === 'completed') await onCompleted();
      } catch (lookupError) {
        if (!disposed) item.monitorError = `현재 상태 확인 실패: ${errorMessage(lookupError)}`;
      }
    } finally {
      if (!disposed) item.retrying = false;
    }
  };

  // 2026.10.02(woojin.jung) 수정 - 상태 배지와 중복되던 단계 문구를 배지 옆 보조 설명으로만 사용
  const uploadStatusLabel = (item) => {
    if (['running', 'failed'].includes(item.status)) {
      const steps = stepsFor(item);
      const index = uploadStepIndex(item);
      return `${steps[index].label} 단계${item.status === 'failed' ? '에서 실패' : ''} (${index + 1}/${steps.length})`;
    }
    if (item.status === 'completed' && isDrawingItem(item)) return '도면 추출 결과 저장 완료';
    return (
      {
        selected: '업로드 시작 시 전송됩니다',
        uploading: '서버로 파일 전송 중',
        queued: '앞선 문서 처리 후 시작',
        completed: '검색 데이터 저장 완료',
        rejected: '파일 또는 옵션을 확인하세요',
        submission_unknown: '서버 접수 여부를 확인하지 못했습니다',
      }[item.status] || ''
    );
  };

  function isDrawingItem(item) {
    return isDrawingFile(item) || item.result?.doc_type === 'drawing';
  }

  function stepsFor(item) {
    return isDrawingItem(item) ? DRAWING_UPLOAD_STEPS : UPLOAD_STEPS;
  }

  onScopeDispose(() => {
    disposed = true;
    stopMonitoring();
    lifetimeController.abort();
  });

  return {
    uploadItems,
    selectionMessage,
    isSubmitting,
    isMonitoring,
    isUploading,
    authBlocked,
    totalFileSize,
    summary,
    hasLongWait,
    pendingItems,
    submissionItems,
    canUpload,
    documentTypeCompatibilityError,
    validationError,
    replacementFileError,
    addFiles,
    removeFile,
    clearFile,
    uploadDocument,
    startMonitoring,
    stopMonitoring,
    retryIngestJob,
    uploadStatusLabel,
    uploadSteps: UPLOAD_STEPS,
    stepsFor,
    isDrawingItem,
    summaryChips,
    progressSegments,
    uploadStepState,
    hasRowActions,
    progressAnimated,
    uploadStateLabel,
    // 2026.10.16(sooyeon.choi) 추가 - 엑셀 전용 처리기 안내·파서 선택 비활성용 상태
    excelIngestExtensions,
    hasExcelIngestFile,
    allExcelIngestFiles,
    drawingIngestExtensions,
    drawingMaxUploadMb,
    drawingEnabled,
    hasDrawingFile,
    allDrawingFiles,
    acceptedExtensions,
    // 2026.10.19(sooyeon.choi) 추가 - 파일별 모델명 입력·검증
    canEditModel,
    modelError,
    hasModelError,
    isModelNameEdited,
    resetModelName,
    // 2026.10.19(sooyeon.choi) 추가 - 최신본 변경 사용 여부
    versionReplaceEnabled,
  };
};
