// 2026.07.22(sychoi) 추가 - RAG 평가: 테스트셋 생성/검토 화면 로직 (P4)
// 2026.07.23(sychoi) 수정 - v2 재설계: 한글 라벨 매핑, 페이지네이션 연결, 근거 원문 펼침,
//   미검출 우선 검수 필터, ①축(expected_behavior/tags) 편집 지원
import { storeToRefs } from 'pinia';
import { computed, onBeforeUnmount, ref } from 'vue';
import { useRouter } from 'vue-router';
import { evalApi } from '../api/evalApi';
import { collectionApi } from '../api/collectionApi';
import { useAuthStore } from '../stores/authStore';

const POLL_INTERVAL_MS = 3000;

const DATASET_STATUS_LABELS = {
  generating: '생성 중', review: '검토 중', finalized: '확정됨', failed: '실패',
};
const QUESTION_TYPE_LABELS = {
  factual: '사실형', procedural: '절차형', comparative: '비교형', multihop: '멀티홉',
};
const REVIEW_STATUS_LABELS = {
  pending: '대기', approved: '승인', edited: '수정됨', rejected: '반려',
};
// ①축 — 기대 동작(가드레일/거절 평가 분기). 자동 생성물은 전부 'answer'이므로
// 거절 케이스는 검수자가 지정해야 KPI(거절 적합성)를 측정할 수 있다.
export const EXPECTED_BEHAVIOR_OPTIONS = [
  { value: 'answer', label: '정상 답변' },
  { value: 'not_enough_info', label: '근거 없음(거절)' },
  { value: 'guardrail', label: '가드레일 차단' },
  { value: 'permission_denied', label: '권한 차단' },
];

// ①축 — 한국어 검색 취약 세그먼트 태그 (생성기가 자동 부여, 검수자가 보정)
export const AVAILABLE_TAGS = [
  { value: 'legal_reference', label: '법령·조문' },
  { value: 'abbreviation', label: '약어' },
  { value: 'compound_term', label: '복합명사' },
  { value: 'near_miss', label: '유사문서 혼동' },
  { value: 'unanswerable', label: '답변 불가' },
];

export const useEvalDatasets = () => {
  const router = useRouter();
  const authStore = useAuthStore();
  const { isAdmin, displayName } = storeToRefs(authStore);

  const sidebarOpen = ref(false);
  const isLoading = ref(false);
  const loadError = ref('');

  const datasets = ref([]);
  const selectedDataset = ref(null);
  const downloadingDatasetId = ref(null);

  const qaItems = ref([]);
  const qaTotal = ref(0);
  const qaPage = ref(1);
  const qaPageSize = ref(20);
  const statusFilter = ref('');
  const typeFilter = ref('');
  const undetectedOnly = ref(false);   // self_valid_rank == null 우선 검수
  const selectedQaIds = ref([]);
  const selectedScopeTotal = ref(0);
  const isSelectingAll = ref(false);
  const editingItem = ref(null);

  const showCreateModal = ref(false);
  const deleteDatasetTarget = ref(null);
  const isDeletingDataset = ref(false);
  const collections = ref([]);
  const createForm = ref({ name: '', collection_id: null, target_count: 30, llm_backend: 'vllm' });

  const goldsets = ref([]);
  const finalizeNote = ref('');

  // 2026.07.23(sychoi) 추가 - 다른 관리자 화면과 동일한 AppToast 알림 (useUserPermissions 패턴)
  const toast = ref({ visible: false, message: '', type: 'success' });
  let toastTimer = null;
  const showToast = (message, type = 'success') => {
    if (toastTimer) clearTimeout(toastTimer);
    toast.value = { visible: true, message, type };
    toastTimer = setTimeout(() => { toast.value.visible = false; }, 2500);
  };

  let pollTimer = null;

  const isGenerating = computed(() => selectedDataset.value?.status === 'generating');
  const qaTotalPages = computed(() => Math.max(1, Math.ceil(qaTotal.value / qaPageSize.value)));
  const generateProgress = computed(() => {
    const d = selectedDataset.value;
    if (!d || !d.progress_total) return 0;
    return Math.round((d.progress_done / d.progress_total) * 100);
  });

  // 미검출 필터는 서버가 지원하지 않으므로 현재 페이지 기준 클라이언트 필터
  const displayQaItems = computed(() =>
    undetectedOnly.value ? qaItems.value.filter((i) => i.self_valid_rank == null) : qaItems.value
  );

  const isAllSelected = computed(() => {
    return selectedScopeTotal.value > 0
      && selectedQaIds.value.length === selectedScopeTotal.value;
  });
  const approvedCount = computed(() => selectedDataset.value?.approved_count ?? 0);
  const datasetItemCount = computed(() => selectedDataset.value?.item_count ?? qaTotal.value);
  const undetectedCount = computed(() => qaItems.value.filter((i) => i.self_valid_rank == null).length);

  const toggleSelectAll = async () => {
    if (isAllSelected.value) {
      selectedQaIds.value = [];
      selectedScopeTotal.value = 0;
      return;
    }
    if (!selectedDataset.value) return;

    isSelectingAll.value = true;
    try {
      const pageSize = 200;
      const params = {
        status: statusFilter.value || undefined,
        type: typeFilter.value || undefined,
        page: 1,
        pageSize,
      };
      const { data: firstPage } = await evalApi.listQaItems(
        selectedDataset.value.dataset_id,
        params
      );
      const totalPages = Math.ceil((firstPage.total || 0) / pageSize);
      const remainingPages = await Promise.all(
        Array.from({ length: Math.max(0, totalPages - 1) }, (_, index) =>
          evalApi.listQaItems(selectedDataset.value.dataset_id, {
            ...params,
            page: index + 2,
          })
        )
      );
      const allItems = [
        ...(firstPage.items || []),
        ...remainingPages.flatMap(({ data }) => data.items || []),
      ];
      const filteredItems = undetectedOnly.value
        ? allItems.filter((item) => item.self_valid_rank == null)
        : allItems;
      selectedQaIds.value = filteredItems.map((item) => item.qa_id);
      selectedScopeTotal.value = selectedQaIds.value.length;
      if (!filteredItems.length) {
        showToast('선택 가능한 QA 항목이 없습니다.');
      }
    } catch (e) {
      showToast(e.response?.data?.detail || '전체 QA 항목을 선택하지 못했습니다.', 'error');
    } finally {
      isSelectingAll.value = false;
    }
  };

  const loadDatasets = async () => {
    isLoading.value = true;
    loadError.value = '';
    try {
      const { data } = await evalApi.listDatasets();
      datasets.value = data.items || [];
      const currentId = selectedDataset.value?.dataset_id;
      const current = datasets.value.find((dataset) => dataset.dataset_id === currentId);
      const generating = current?.status === 'generating'
        ? current
        : datasets.value.find((dataset) => dataset.status === 'generating');

      // 최초 진입 또는 새 생성 요청 직후에는 생성 중인 데이터셋을 자동 선택해
      // 사용자가 목록 행을 누르지 않아도 진행률을 바로 볼 수 있게 한다.
      if (generating && generating.dataset_id !== currentId) {
        await selectDataset(generating);
      } else if (current) {
        selectedDataset.value = current;
      }
    } catch (e) {
      loadError.value = e.response?.data?.detail || '데이터셋 목록을 불러오지 못했습니다.';
    } finally {
      isLoading.value = false;
    }
  };

  const loadCollections = async () => {
    try {
      const { data } = await collectionApi.listAll();
      collections.value = data.collections || data.items || data || [];
    } catch {
      collections.value = [];
    }
  };

  const responseFilename = (contentDisposition, fallback) => {
    const utf8Match = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match) {
      try {
        return decodeURIComponent(utf8Match[1]);
      } catch {
        return fallback;
      }
    }
    const asciiMatch = contentDisposition?.match(/filename="?([^";]+)"?/i);
    return asciiMatch?.[1] || fallback;
  };

  const blobErrorDetail = async (error) => {
    const data = error.response?.data;
    if (!(data instanceof Blob)) return data?.detail;
    try {
      return JSON.parse(await data.text()).detail;
    } catch {
      return null;
    }
  };

  const downloadApprovedExcel = async (dataset) => {
    if (!dataset || (dataset.approved_count ?? 0) < 1 || downloadingDatasetId.value !== null) return;
    downloadingDatasetId.value = dataset.dataset_id;
    try {
      const response = await evalApi.downloadApprovedDataset(dataset.dataset_id);
      const blob = response.data instanceof Blob
        ? response.data
        : new Blob([response.data], { type: response.headers['content-type'] });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = responseFilename(
        response.headers['content-disposition'],
        `eval_dataset_${dataset.dataset_id}.xlsx`,
      );
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      showToast((await blobErrorDetail(error)) || '승인 QA Excel 다운로드에 실패했습니다.', 'error');
    } finally {
      downloadingDatasetId.value = null;
    }
  };

  const selectDataset = async (dataset) => {
    selectedDataset.value = dataset;
    qaPage.value = 1;
    selectedQaIds.value = [];
    selectedScopeTotal.value = 0;
    await Promise.all([loadQaItems(), loadGoldsets()]);
    startPollingIfGenerating();
  };

  const loadQaItems = async () => {
    if (!selectedDataset.value) return;
    try {
      const { data } = await evalApi.listQaItems(selectedDataset.value.dataset_id, {
        status: statusFilter.value || undefined,
        type: typeFilter.value || undefined,
        page: qaPage.value,
        pageSize: qaPageSize.value,
      });
      qaItems.value = (data.items || []).map((item) => ({
        ...item,
        tags_parsed: safeParse(item.tags, []),
        gold_chunk_texts_parsed: safeParse(item.gold_chunk_texts, []),
        source_meta: safeParse(item.source_meta_json, {}),
        expanded: false,
      }));
      qaTotal.value = data.total || 0;
    } catch (e) {
      loadError.value = e.response?.data?.detail || 'QA 목록을 불러오지 못했습니다.';
    }
  };

  const goToPage = async (page) => {
    const target = Math.min(Math.max(1, page), qaTotalPages.value);
    if (target === qaPage.value) return;
    qaPage.value = target;
    await loadQaItems();
  };

  const applyFilters = async () => {
    qaPage.value = 1;
    selectedQaIds.value = [];
    selectedScopeTotal.value = 0;
    await loadQaItems();
  };

  const toggleExpand = (item) => {
    item.expanded = !item.expanded;
  };

  const loadGoldsets = async () => {
    if (!selectedDataset.value) return;
    try {
      const { data } = await evalApi.listGoldsets(selectedDataset.value.dataset_id);
      goldsets.value = data.items || [];
    } catch {
      goldsets.value = [];
    }
  };

  const refreshSelectedDataset = async () => {
    if (!selectedDataset.value) return;
    try {
      const { data } = await evalApi.getDataset(selectedDataset.value.dataset_id);
      selectedDataset.value = { ...selectedDataset.value, ...data };
      if (data.status !== 'generating') {
        stopPolling();
        await Promise.all([loadQaItems(), loadDatasets()]);
      }
    } catch {
      stopPolling();
    }
  };

  const startPollingIfGenerating = () => {
    stopPolling();
    if (isGenerating.value) pollTimer = setInterval(refreshSelectedDataset, POLL_INTERVAL_MS);
  };

  const stopPolling = () => {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  };

  const createDataset = async () => {
    if (!createForm.value.name || !createForm.value.collection_id) {
      loadError.value = '이름과 컬렉션을 입력하세요.';
      return;
    }
    // 2026.07.24(sychoi) 수정 - OpenAI 키는 gen_config로 보내지 않는다.
    //   백엔드가 관리자 저장 키(평가 전용)를 리졸브한다. (미저장 시 400 → 뷰에서 선차단)
    try {
      await evalApi.createDataset({
        name: createForm.value.name,
        collection_id: createForm.value.collection_id,
        gen_config: {
          target_count: Number(createForm.value.target_count) || 30,
          llm_backend: createForm.value.llm_backend,
        },
      });
      showCreateModal.value = false;
      createForm.value = { name: '', collection_id: null, target_count: 30, llm_backend: 'vllm' };
      await loadDatasets();
    } catch (e) {
      loadError.value = e.response?.data?.detail || '데이터셋 생성 요청에 실패했습니다.';
    }
  };

  const approveItem = async (item) => {
    try {
      await evalApi.approveQaItem(item.qa_id);
      item.review_status = 'approved';
      await loadDatasets();
      showToast('QA 항목을 승인했습니다.');
    } catch (e) {
      showToast(e.response?.data?.detail || '승인에 실패했습니다.', 'error');
    }
  };
  const rejectItem = async (item) => {
    try {
      await evalApi.rejectQaItem(item.qa_id);
      item.review_status = 'rejected';
      await loadDatasets();
      showToast('QA 항목을 반려했습니다.');
    } catch (e) {
      showToast(e.response?.data?.detail || '반려에 실패했습니다.', 'error');
    }
  };
  const bulkApprove = async () => {
    const count = selectedQaIds.value.length;
    if (!count) return;
    try {
      await evalApi.bulkReview(selectedQaIds.value, 'approve');
      selectedQaIds.value = [];
      selectedScopeTotal.value = 0;
      await Promise.all([loadQaItems(), loadDatasets()]);
      showToast(`${count}건을 일괄 승인했습니다.`);
    } catch (e) {
      showToast(e.response?.data?.detail || '일괄 승인에 실패했습니다.', 'error');
    }
  };
  const bulkReject = async () => {
    const count = selectedQaIds.value.length;
    if (!count) return;
    try {
      await evalApi.bulkReview(selectedQaIds.value, 'reject');
      selectedQaIds.value = [];
      selectedScopeTotal.value = 0;
      await Promise.all([loadQaItems(), loadDatasets()]);
      showToast(`${count}건을 일괄 반려했습니다.`);
    } catch (e) {
      showToast(e.response?.data?.detail || '일괄 반려에 실패했습니다.', 'error');
    }
  };

  // ①축 필드까지 편집 대상에 포함 (백엔드 PATCH /eval/items/{id}가 지원)
  const startEdit = (item) => {
    editingItem.value = {
      qa_id: item.qa_id,
      question: item.question,
      gold_answer: item.gold_answer,
      expected_behavior: item.expected_behavior || 'answer',
      tags: [...(item.tags_parsed || [])],
    };
  };
  const toggleEditTag = (tag) => {
    if (!editingItem.value) return;
    const idx = editingItem.value.tags.indexOf(tag);
    if (idx >= 0) editingItem.value.tags.splice(idx, 1);
    else editingItem.value.tags.push(tag);
  };
  const saveEdit = async () => {
    if (!editingItem.value) return;
    const { qa_id, question, gold_answer, expected_behavior, tags } = editingItem.value;
    try {
      await evalApi.updateQaItem(qa_id, { question, gold_answer, expected_behavior, tags });
      editingItem.value = null;
      await Promise.all([loadQaItems(), loadDatasets()]);
      showToast('QA 항목을 수정했습니다.');
    } catch (e) {
      showToast(e.response?.data?.detail || 'QA 수정에 실패했습니다.', 'error');
    }
  };
  const cancelEdit = () => { editingItem.value = null; };

  const finalizeDataset = async () => {
    if (!selectedDataset.value) return;
    const datasetName = selectedDataset.value.name;
    try {
      const { data } = await evalApi.finalizeDataset(selectedDataset.value.dataset_id, finalizeNote.value);
      finalizeNote.value = '';
      await Promise.all([loadGoldsets(), loadDatasets()]);
      // 2026.07.23(sychoi) 수정 - window.alert → AppToast 알림으로 통일
      // 2026.07.23(sychoi) 수정 - 내부 ID(#n) 대신 '데이터셋명 + 골드셋 버전'으로 식별
      //   (loadGoldsets() 이후이므로 새 골드셋의 version을 목록에서 조회 가능)
      const created = goldsets.value.find((g) => g.goldset_id === data.goldset_id);
      const label = created
        ? `'${created.dataset_name || datasetName}' 골드셋 v${created.version}`
        : `'${datasetName}' 골드셋`;
      // 2026.08.03(sooyeon.choi) 수정 - 완료 결과와 후속 안내를 분리해 표시
      showToast(`${label} 확정 완료.\n'평가 실행' 화면에서 사용할 수 있습니다.`);
      return data.goldset_id;
    } catch (e) {
      showToast(e.response?.data?.detail || '골드셋 확정에 실패했습니다.', 'error');
    }
  };

  // 생성 중에는 삭제 차단 + 영향 범위를 명시해 확인
  const deleteDataset = (dataset) => {
    if (dataset.status === 'generating') return;
    deleteDatasetTarget.value = dataset;
  };

  const closeDeleteDatasetModal = () => {
    if (!isDeletingDataset.value) deleteDatasetTarget.value = null;
  };

  const confirmDeleteDataset = async () => {
    const dataset = deleteDatasetTarget.value;
    if (!dataset || isDeletingDataset.value) return;
    isDeletingDataset.value = true;
    try {
      await evalApi.deleteDataset(dataset.dataset_id);
      if (selectedDataset.value?.dataset_id === dataset.dataset_id) {
        selectedDataset.value = null;
        qaItems.value = [];
        goldsets.value = [];
      }
      deleteDatasetTarget.value = null;
      await loadDatasets();
      showToast(`'${dataset.name}' 데이터셋을 삭제했습니다.`);
    } catch (e) {
      showToast(e.response?.data?.detail || '데이터셋 삭제에 실패했습니다.', 'error');
    } finally {
      isDeletingDataset.value = false;
    }
  };

  const logout = async () => {
    await authStore.logoutAny();
    router.push('/login');
  };

  const safeParse = (value, fallback) => {
    if (!value) return fallback;
    try {
      return typeof value === 'string' ? JSON.parse(value) : value;
    } catch {
      return fallback;
    }
  };

  const statusLabel = (s) => DATASET_STATUS_LABELS[s] || s;
  const typeLabel = (t) => QUESTION_TYPE_LABELS[t] || t;
  const reviewLabel = (s) => REVIEW_STATUS_LABELS[s] || s;
  const tagLabel = (t) => AVAILABLE_TAGS.find((x) => x.value === t)?.label || t;
  const behaviorLabel = (b) => EXPECTED_BEHAVIOR_OPTIONS.find((x) => x.value === b)?.label || b;
  // 2026.07.23(sychoi) 수정 - 날짜/시각 전체 표시 (예: 2026-07-23 10:24:43)
  // 저장 형식이 '2026-07-23T10:24:43+09:00'(KST)이므로 앞 19자를 잘라 T를 공백으로 치환한다.
  const formatDate = (v, len = 19) => (v || '').slice(0, len).replace('T', ' ');

  onBeforeUnmount(() => {
    stopPolling();
    if (toastTimer) clearTimeout(toastTimer);
  });

  return {
    isAdmin, displayName, sidebarOpen, isLoading, loadError, toast,
    datasets, selectedDataset, downloadingDatasetId, isGenerating, generateProgress,
    qaItems, displayQaItems, qaTotal, qaPage, qaPageSize, qaTotalPages,
    statusFilter, typeFilter, undetectedOnly, undetectedCount,
    selectedQaIds, isAllSelected, isSelectingAll, toggleSelectAll, editingItem,
    approvedCount, datasetItemCount, showCreateModal, collections, createForm, goldsets, finalizeNote,
    deleteDatasetTarget, isDeletingDataset,
    loadDatasets, loadCollections, selectDataset, downloadApprovedExcel, loadQaItems, applyFilters, goToPage, toggleExpand,
    createDataset, approveItem, rejectItem, bulkApprove, bulkReject,
    startEdit, toggleEditTag, saveEdit, cancelEdit, finalizeDataset, deleteDataset,
    closeDeleteDatasetModal, confirmDeleteDataset, logout,
    statusLabel, typeLabel, reviewLabel, tagLabel, behaviorLabel, formatDate,
    EXPECTED_BEHAVIOR_OPTIONS, AVAILABLE_TAGS,
  };
};
