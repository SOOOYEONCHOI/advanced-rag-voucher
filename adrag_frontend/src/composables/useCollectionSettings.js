import { computed, onMounted, ref } from 'vue';
import { storeToRefs } from 'pinia';
import { collectionApi } from '../api/collectionApi';
import { useAuthStore } from '../stores/authStore';
import { useNavigationLock } from './useNavigationLock';

export const useCollectionSettings = ({ router }) => {
  const authStore = useAuthStore();
  const { isAdmin, displayName } = storeToRefs(authStore);

  const collections = ref([]);
  const isAdding = ref(false);
  const deleteTarget = ref(null);
  const sidebarOpen = ref(false);
  const alertMessage = ref('');
  const alertType = ref('success');
  const isSavingCollection = computed(() => collections.value.some((collection) => collection._saving));

  // 2026.07.22(sychoi) 추가 - 헤더 배지는 "저장 완료된" 대화 주제만 집계한다.
  // collections에는 addCollection()이 push한 미저장 신규 슬롯(collection_id=null, _isNew=true)도
  // 포함되므로 collections.length를 그대로 쓰면 추가 버튼만 눌러도 카운트가 올라간다.
  const savedCollectionCount = computed(() => collections.value.filter((collection) => collection.collection_id != null && !collection._isNew).length);

  useNavigationLock(isSavingCollection, '대화 주제를 저장하는 중에는 다른 화면으로 이동할 수 없습니다.');

  const logout = async () => {
    if (isSavingCollection.value) return;
    await authStore.logoutAny();
    router.push('/login');
  };

  const showAlert = (msg, type = 'success') => {
    alertMessage.value = msg;
    alertType.value = type;
    setTimeout(() => {
      alertMessage.value = '';
    }, 4000);
  };

  const loadCollections = async () => {
    try {
      const res = await collectionApi.list();
      const list = res.data.collections || [];
      collections.value = list.map((c) => ({
        ...c,
        _editName: c.collection_name ?? '',
        _editDescription: c.collection_desc ?? '',
        _saving: false,
      }));
    } catch {
      showAlert('대화 주제 목록을 불러오지 못했습니다.', 'error');
    }
  };

  const addCollection = async () => {
    // 2026.07.22(sychoi) 수정 - 슬롯 전체 길이가 아니라 "저장 완료된" 개수 기준으로 제한
    // (헤더 배지 savedCollectionCount와 동일 기준. 초과 저장은 백엔드 max_collections=5가 최종 차단)
    if (savedCollectionCount.value >= 5 || isAdding.value) return;
    isAdding.value = true;
    collections.value.push({
      collection_id: null,
      collection_name: '',
      collection_desc: '',
      document_count: 0,
      created_at: '',
      updated_at: '',
      _editName: '',
      _editDescription: '',
      _saving: false,
      _isNew: true,
    });
    isAdding.value = false;
  };

  const saveCollection = async (col) => {
    const name = col._editName.trim();
    if (!name) {
      showAlert('유효한 대화 주제 이름을 입력해주세요.', 'error');
      return;
    }

    col._saving = true;
    try {
      if (col._isNew || col.collection_id === null) {
        await collectionApi.create({
          name,
          description: col._editDescription.trim(),
          topic_name: name,
        });
        showAlert(`대화 주제 "${name}"이(가) 생성되었습니다.`, 'success');
      } else {
        await collectionApi.update(col.collection_id, {
          name,
          description: col._editDescription.trim(),
          topic_name: name,
        });
        showAlert(`대화 주제 "${name}"이(가) 수정되었습니다.`, 'success');
      }
      await loadCollections();
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || '저장에 실패했습니다.';
      showAlert(detail, 'error');
    } finally {
      col._saving = false;
    }
  };

  const confirmDelete = (col) => {
    if (isSavingCollection.value) return;
    if (col._isNew || col.collection_id === null) {
      collections.value = collections.value.filter((c) => c !== col);
      return;
    }
    deleteTarget.value = col;
  };

  const doDelete = async () => {
    if (isSavingCollection.value) return;
    const col = deleteTarget.value;
    if (!col) return;

    try {
      await collectionApi.remove(col.collection_id);
      showAlert(`대화 주제 "${col.collection_name}"이(가) 삭제되었습니다.`, 'success');
      deleteTarget.value = null;
      await loadCollections();
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || '삭제에 실패했습니다.';
      showAlert(detail, 'error');
      deleteTarget.value = null;
    }
  };

  onMounted(() => {
    loadCollections();
  });

  return {
    isAdmin,
    displayName,
    collections,
    isAdding,
    deleteTarget,
    sidebarOpen,
    alertMessage,
    alertType,
    isSavingCollection,
    savedCollectionCount,
    loadCollections,
    addCollection,
    saveCollection,
    confirmDelete,
    doDelete,
    logout,
  };
};
