import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { storeToRefs } from 'pinia';
import { adminApi } from '../api/adminApi';
import { collectionApi } from '../api/collectionApi';
import { useAuthStore } from '../stores/authStore';
import { docTypeLabel, docTypeSourceLabel, formatFileSize, formatTime } from '../utils/textFormat';
import { useNavigationLock } from './useNavigationLock';
import { modelNameError, useDocumentUpload } from './useDocumentUpload';
import { useDocumentVersions } from './useDocumentVersions';

const DOCUMENT_TYPE_OPTIONS = [
  { value: 'auto', label: '자동', description: '파일 형식과 문서 구조를 분석하여 적절한 청킹 방식을 자동 적용합니다.' },
  { value: 'general', label: '일반 문서', description: '제목과 문단 흐름을 기준으로 일반 문서 청킹을 적용합니다.' },
  { value: 'manual', label: '매뉴얼', description: '메뉴 경로와 화면 단위를 기준으로 매뉴얼 청킹을 적용합니다.' },
  { value: 'law', label: '법령', description: '장·절·조·항 및 별표·별지 구조를 기준으로 법령 청킹을 적용합니다.' },
  { value: 'spreadsheet', label: '스프레드시트', description: '시트·표·헤더·행 구조를 보존하는 스프레드시트 청킹을 적용합니다.' },
];

export const useAdminDocuments = ({ router }) => {
  const authStore = useAuthStore();
  const { isAdmin, displayName } = storeToRefs(authStore);

  const fileInput = ref(null);
  const isDragging = ref(false);
  const uploadError = ref(null);
  const alertMessage = ref('');
  const alertType = ref('success');
  const documents = ref([]);
  const collections = ref([]);
  const collectionsForFilter = ref([]);
  const filterCollection = ref('');
  const sidebarOpen = ref(false);
  const registeredCollections = ref([]);
  const deleteDocTarget = ref(null);
  const deletingId = ref(null);
  // 2026.10.20(woojin.jung) 수정 - 모델명·파일명을 한 컬럼으로 합쳐 기본 너비 확대
  const filenameColumnWidth = ref(340);
  const openingDocId = ref(null);
  // 2026.10.19(sooyeon.choi) 추가 - 문서 목록 모델명 인라인 수정 상태
  const editingModelId = ref(null);
  const editingModelValue = ref('');
  const modelEditError = ref('');
  const savingModelId = ref(null);

  const form = reactive({
    collectionName: '',
    parserType: 'docling',
    documentType: 'auto',
    chunkSize: null,
    // 2026.10.19(sooyeon.choi) 수정 - 공통 제품 모델 입력 제거(파일별 모델명으로 전환, useDocumentUpload의 item.productModel)
  });

  const selectedDocumentTypeDescription = computed(() => DOCUMENT_TYPE_OPTIONS.find((option) => option.value === form.documentType)?.description || '');

  const upload = useDocumentUpload({
    form,
    api: adminApi,
    onCompleted: async () => {
      await Promise.all([loadDocuments(), loadCollections()]);
    },
    // 2026.10.02(woojin.jung) 수정 - 일괄 처리가 모두 끝나면 결과를 토스트로 안내
    onSettled: ({ completed, failed, rejected, unknown }) => {
      const problems = failed + rejected + unknown;
      showAlert(problems ? `문서 처리 완료 ${completed}개 · 확인 필요 ${problems}개` : `문서 ${completed}개 처리가 완료되었습니다.`, problems ? 'error' : 'success');
    },
  });
  const { isUploading } = upload;
  // 2026.10.02(woojin.jung) 수정 - 상태 확인 버튼 명칭 변경(자동 확인 중지)에 맞춰 안내 문구 수정
  useNavigationLock(isUploading, '문서 업로드 및 처리 확인 중입니다. 이동하려면 파일 전송 후 처리 현황의 "자동 확인 중지"를 누르세요. 서버의 문서 처리는 계속됩니다.');

  let filenameResizeState = null;
  let disposed = false;

  const showAlert = (message, type = 'success') => {
    alertMessage.value = message;
    alertType.value = type;
    setTimeout(() => {
      alertMessage.value = '';
    }, 4000);
  };

  const filenameColumnStyle = computed(() => ({
    '--filename-column-width': `${filenameColumnWidth.value}px`,
  }));

  const splitCollectionDisplay = (collectionName) => {
    const value = String(collectionName || '');
    const separatorIndex = value.indexOf('_');

    if (separatorIndex <= 0) {
      return {
        topic: value || '-',
        user: '-',
      };
    }

    return {
      topic: value.slice(separatorIndex + 1) || value,
      user: value.slice(0, separatorIndex),
    };
  };

  const collectionTopicLabel = (collectionName) => splitCollectionDisplay(collectionName).topic;

  const logout = async () => {
    if (isUploading.value) return;
    await authStore.logoutAny();
    router.push('/login');
  };

  const openFilePicker = () => {
    if (isUploading.value) return;
    fileInput.value?.click();
  };

  const onDragOver = () => {
    if (isUploading.value) return;
    isDragging.value = true;
  };

  const onFileChange = (e) => {
    upload.addFiles(e.target.files);
    e.target.value = '';
  };

  const onDrop = (e) => {
    isDragging.value = false;
    upload.addFiles(e.dataTransfer.files);
  };

  const loadDocuments = async () => {
    if (disposed) return;
    try {
      const params = filterCollection.value ? { collection_name: filterCollection.value } : {};
      const res = await adminApi.documents(params);
      if (disposed) return;
      documents.value = res.data.documents || [];
      // 2026.10.19(sooyeon.choi) 추가 - 새로고침·필터 변경으로 편집 중인 문서가 목록에서 빠지면 편집 종료
      if (editingModelId.value && !documents.value.some((doc) => doc.document_id === editingModelId.value)) {
        editingModelId.value = null;
        modelEditError.value = '';
      }
      // 2026.10.19(sooyeon.choi) 추가 - 최신본 변경 처리 중인 본인 작업은 상태 확인을 이어간다(새로고침 복원)
      versions.syncPendingJobs(documents.value);
    } catch {
      if (disposed) return;
      documents.value = [];
    }
  };

  // 2026.10.19(sooyeon.choi) 추가 - [최신본 변경]·[버전 이력]
  const versions = useDocumentVersions({ api: adminApi, loadDocuments, showAlert });

  const loadCollections = async () => {
    if (disposed) return;
    try {
      // 2026.06.18(sooyeon.choi) 수정 - /collections 기준으로 통일하고 Qdrant에 존재하는 항목만 표시
      const res = await collectionApi.list();
      if (disposed) return;
      const availableCollections = res.data.collections || [];
      registeredCollections.value = availableCollections;
      collectionsForFilter.value = availableCollections;
      collections.value = availableCollections.map((collection) => collection.qdrant_name);
    } catch {
      if (disposed) return;
      collections.value = [];
      collectionsForFilter.value = [];
      registeredCollections.value = [];
    }
  };

  // 2026.06.18(sooyeon.choi) 수정 - 중복 컬렉션 조회 제거
  const loadRegisteredCollections = loadCollections;

  const confirmDeleteDoc = (doc) => {
    uploadError.value = null;
    deleteDocTarget.value = doc;
  };

  const doDeleteDoc = async () => {
    const doc = deleteDocTarget.value;
    if (!doc) return;
    deleteDocTarget.value = null;
    deletingId.value = doc.document_id;

    try {
      const res = await adminApi.deleteDocument(doc.document_id);
      if (res.data?.remaining_vector_count !== 0) {
        throw new Error('Qdrant 벡터 삭제가 완료되지 않았습니다.');
      }
      await loadDocuments();
      await loadCollections();
      uploadError.value = null;
      showAlert(`문서 "${doc.filename}"이(가) 삭제되었습니다.`, 'success');
    } catch (err) {
      uploadError.value = err.response?.data?.detail || err.message || '문서 삭제에 실패했습니다.';
    } finally {
      deletingId.value = null;
    }
  };

  // 2026.10.19(sooyeon.choi) 추가 - 모델명 수정: 저장 성공 시에만 목록 값 반영, 실패 시 입력값·오류 유지, 취소 시 기존 값
  const startModelEdit = (doc) => {
    if (!doc?.can_edit || savingModelId.value) return;
    editingModelId.value = doc.document_id;
    editingModelValue.value = doc.product_model || '';
    modelEditError.value = '';
  };

  const cancelModelEdit = () => {
    if (savingModelId.value) return;
    editingModelId.value = null;
    editingModelValue.value = '';
    modelEditError.value = '';
  };

  const saveModelEdit = async (doc) => {
    if (!doc || savingModelId.value) return;
    const error = modelNameError(editingModelValue.value);
    if (error) {
      modelEditError.value = error;
      return;
    }
    savingModelId.value = doc.document_id;
    modelEditError.value = '';
    try {
      const res = await adminApi.updateDocumentModelName(doc.document_id, editingModelValue.value.trim());
      if (disposed) return;
      doc.product_model = res.data.product_model;
      doc.updated_at = res.data.updated_at || doc.updated_at;
      editingModelId.value = null;
      editingModelValue.value = '';
      showAlert('모델명을 저장했습니다.', 'success');
    } catch (err) {
      if (disposed) return;
      const detail = err.response?.data?.detail;
      modelEditError.value = typeof detail === 'string' ? detail : err.message || '모델명을 저장하지 못했습니다.';
    } finally {
      if (!disposed) savingModelId.value = null;
    }
  };

  const stopFilenameResize = () => {
    if (!filenameResizeState) return;
    window.removeEventListener('mousemove', onFilenameResizeMove);
    window.removeEventListener('mouseup', stopFilenameResize);
    filenameResizeState = null;
  };

  const onFilenameResizeMove = (event) => {
    if (!filenameResizeState) return;
    const delta = event.clientX - filenameResizeState.startX;
    filenameColumnWidth.value = Math.min(560, Math.max(160, filenameResizeState.startWidth + delta));
  };

  const startFilenameResize = (event) => {
    event.preventDefault();
    stopFilenameResize();
    filenameResizeState = {
      startX: event.clientX,
      startWidth: filenameColumnWidth.value,
    };
    window.addEventListener('mousemove', onFilenameResizeMove);
    window.addEventListener('mouseup', stopFilenameResize);
  };

  const startFilenameResizeFromHeader = (event) => {
    // 2026.10.19(sooyeon.choi) 수정 - 첫 컬럼이 모델명이 되어 파일명 헤더를 클래스로 찾는다
    const filenameHeader = event.currentTarget?.querySelector('.doc-table th.th-filename');
    if (!filenameHeader || !filenameHeader.contains(event.target)) return;

    const rect = filenameHeader.getBoundingClientRect();
    if (rect.right - event.clientX > 10) return;
    startFilenameResize(event);
  };

  const openOriginalDocument = async (doc) => {
    if (!doc?.document_id || openingDocId.value) return;
    openingDocId.value = doc.document_id;

    try {
      const res = await adminApi.documentFile(doc.document_id);
      const contentType = res.headers?.['content-type'] || 'application/octet-stream';
      const blobUrl = window.URL.createObjectURL(new Blob([res.data], { type: contentType }));
      window.open(blobUrl, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60000);
    } catch (err) {
      uploadError.value = err.response?.data?.detail || err.message || '원본 문서를 열 수 없습니다.';
    } finally {
      openingDocId.value = null;
    }
  };

  onMounted(async () => {
    await loadCollections();
    await loadDocuments();
  });

  onBeforeUnmount(() => {
    disposed = true;
    stopFilenameResize();
  });

  return {
    ...upload,
    fileInput,
    isDragging,
    isUploading,
    uploadError,
    alertMessage,
    alertType,
    documents,
    collections,
    collectionsForFilter,
    filterCollection,
    form,
    documentTypeOptions: DOCUMENT_TYPE_OPTIONS,
    selectedDocumentTypeDescription,
    sidebarOpen,
    registeredCollections,
    openFilePicker,
    onDragOver,
    onFileChange,
    onDrop,
    loadDocuments,
    loadCollections,
    loadRegisteredCollections,
    formatFileSize,
    formatTime,
    docTypeLabel,
    docTypeSourceLabel,
    collectionTopicLabel,
    deleteDocTarget,
    deletingId,
    filenameColumnStyle,
    openingDocId,
    confirmDeleteDoc,
    doDeleteDoc,
    startFilenameResize,
    startFilenameResizeFromHeader,
    openOriginalDocument,
    // 2026.10.19(sooyeon.choi) 추가 - 모델명 인라인 수정
    editingModelId,
    editingModelValue,
    modelEditError,
    savingModelId,
    startModelEdit,
    cancelModelEdit,
    saveModelEdit,
    // 2026.10.19(sooyeon.choi) 추가 - 최신본 변경·버전 이력
    ...versions,
    isAdmin,
    displayName,
    logout,
  };
};
