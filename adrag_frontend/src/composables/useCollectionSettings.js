import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import { storeToRefs } from 'pinia';
import { collectionApi } from '../api/collectionApi';
import { useAuthStore } from '../stores/authStore';
import { useNavigationLock } from './useNavigationLock';

// 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면 추천 질문 최대 개수·길이 (백엔드 StartQuestionService와 동일)
export const MAX_RECOMMENDED_QUESTIONS = 5;
export const MAX_QUESTION_LENGTH = 100;
const MAX_COLLECTIONS = 10;

// 2026.11.12(woojin.jung) 추가 - 중복 판정용: 공백·문장부호를 지우고 소문자로 (백엔드 normalize_question과 동일 기준)
const normalizeQuestion = (text) =>
  String(text || '')
    .replace(/[^\p{L}\p{N}\p{M}]+/gu, '')
    .toLowerCase();

// 2026.11.12(woojin.jung) 추가 - 저장된 값(saved)과 편집 중인 값(draft)을 나눠 변경 여부를 비교로 계산
const emptyValues = () => ({ name: '', desc: '', recommended: [], hidden: [] });
const cloneValues = (v) => ({ name: v.name, desc: v.desc, recommended: [...v.recommended], hidden: [...v.hidden] });
const sameList = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

export const useCollectionSettings = ({ router }) => {
  const authStore = useAuthStore();
  const { isAdmin, displayName } = storeToRefs(authStore);

  const collections = ref([]);
  const deleteTarget = ref(null);
  const sidebarOpen = ref(false);
  const alertMessage = ref('');
  const alertType = ref('success');
  // 2026.11.12(woojin.jung) 수정 - 목록 + 상세(탭) 화면: 선택한 대화 주제·탭·모바일 상세 표시 여부
  const isSavingCollection = ref(false);
  const selectedKey = ref(null);
  const activeTab = ref('basic');
  const mobileDetail = ref(false);
  const unsavedDialog = ref(null); // { resolve } — 저장하지 않은 변경 확인 대화상자
  let tmpKey = 0;

  // 2026.07.22(sychoi) 추가 - 헤더 배지는 "저장 완료된" 대화 주제만 집계한다.
  // collections에는 addCollection()이 push한 미저장 신규 슬롯(collection_id=null, _isNew=true)도
  // 포함되므로 collections.length를 그대로 쓰면 추가 버튼만 눌러도 카운트가 올라간다.
  const savedCollectionCount = computed(() => collections.value.filter((collection) => collection.collection_id != null && !collection._isNew).length);

  useNavigationLock(isSavingCollection, '대화 주제를 저장하는 중에는 다른 화면으로 이동할 수 없습니다.');

  const showAlert = (msg, type = 'success') => {
    alertMessage.value = msg;
    alertType.value = type;
    setTimeout(() => {
      alertMessage.value = '';
    }, 4000);
  };

  const keyOf = (col) => col.collection_id ?? col._key;
  const currentCollection = computed(() => collections.value.find((col) => keyOf(col) === selectedKey.value) || null);

  // 2026.11.12(woojin.jung) 추가 - 변경 영역(기본 정보 / 시작 화면 질문) 계산. 원래 값으로 되돌리면 변경 없음
  const changesOf = (col) => {
    if (!col) return { basic: false, faq: false, any: false };
    const s = col._saved;
    const d = col._draft;
    const basic = d.name.trim() !== s.name || d.desc.trim() !== s.desc;
    const faq = !sameList(d.recommended.map((q) => q.trim()), s.recommended) || !sameList(d.hidden, s.hidden);
    return { basic, faq, any: col._isNew || basic || faq };
  };
  const currentChanges = computed(() => changesOf(currentCollection.value));
  const hasUnsavedChanges = computed(() => collections.value.some((col) => changesOf(col).any));

  // 2026.11.12(woojin.jung) 추가 - 대화 주제별 채팅 시작 화면 질문(추천 질문·숨긴 질문·많이 찾는 질문) 반영
  const applyStartQuestions = (col, data) => {
    col._saved.recommended = [...(data.recommended || [])];
    col._saved.hidden = [...(data.hidden || [])];
    col._draft.recommended = [...col._saved.recommended];
    col._draft.hidden = [...col._saved.hidden];
    col._popular = data.popular || [];
    col._popularDays = data.popular_days ?? 30;
    col._faqLoaded = true;
  };

  const loadStartQuestions = async (col) => {
    try {
      const res = await collectionApi.getStartQuestions(col.collection_id);
      applyStartQuestions(col, res.data);
    } catch {
      col._faqLoaded = false;
    }
  };

  const toItem = (c) => {
    const saved = { ...emptyValues(), name: c.collection_name ?? '', desc: c.collection_desc ?? '' };
    return {
      ...c,
      _isNew: false,
      _saved: saved,
      _draft: cloneValues(saved),
      _touched: false,
      _faqLoaded: false,
      _popular: [],
      _popularDays: 30,
      _newQuestion: '',
    };
  };

  const loadCollections = async () => {
    try {
      const res = await collectionApi.list();
      collections.value = (res.data.collections || []).map(toItem);
      // 2026.11.12(woojin.jung) 추가 - 시작 화면 질문 설정을 불러온다
      // 2026.11.23(woojin.jung) 수정 - 비활성 부서(읽기 전용)도 미리보기로 볼 수 있게 조회 범위 전체를 불러온다(실패 시 미리보기만 숨김)
      await Promise.all(collections.value.map(loadStartQuestions));
      if (!currentCollection.value) selectedKey.value = collections.value[0] ? keyOf(collections.value[0]) : null;
    } catch {
      showAlert('대화 주제 목록을 불러오지 못했습니다.', 'error');
    }
  };

  // 2026.11.12(woojin.jung) 추가 - 저장하지 않은 변경이 있으면 [저장 안 함 / 계속 편집 / 저장 후 이동]을 묻는다 (true = 이동 가능)
  const confirmLeave = () => {
    if (!currentChanges.value.any) return Promise.resolve(true);
    return new Promise((resolve) => {
      unsavedDialog.value = { resolve };
    });
  };
  const resolveUnsaved = async (choice) => {
    const dialog = unsavedDialog.value;
    if (!dialog) return;
    unsavedDialog.value = null;
    if (choice === 'discard') {
      discardChanges();
      dialog.resolve(true);
    } else if (choice === 'save') {
      dialog.resolve(await saveCollection());
    } else {
      dialog.resolve(false);
    }
  };

  const selectCollection = async (col) => {
    if (keyOf(col) === selectedKey.value) {
      mobileDetail.value = true;
      return;
    }
    if (!(await confirmLeave())) return;
    selectedKey.value = keyOf(col);
    activeTab.value = 'basic';
    mobileDetail.value = true;
  };

  // 2026.11.12(woojin.jung) 추가 - 많이 찾는 질문 중 숨긴 질문·추천 질문과 같은 질문을 뺀 노출 예정 목록 (편집 중인 값 기준)
  const visiblePopular = (col) => {
    if (!col) return [];
    const excluded = new Set([...col._draft.hidden, ...col._draft.recommended].map(normalizeQuestion));
    return col._popular.filter((item) => !excluded.has(normalizeQuestion(item.question)));
  };

  // 2026.11.12(woojin.jung) 추가 - 추천 질문 추가·순서 변경·삭제, 많이 찾는 질문 숨기기 (하단 저장 바로 함께 저장)
  const addRecommendedQuestion = (col) => {
    const question = col._newQuestion.trim();
    if (!question || col._draft.recommended.length >= MAX_RECOMMENDED_QUESTIONS) return;
    if (col._draft.recommended.some((q) => normalizeQuestion(q) === normalizeQuestion(question))) {
      showAlert('이미 등록된 추천 질문입니다.', 'error');
      return;
    }
    col._draft.recommended.push(question);
    col._newQuestion = '';
  };

  const moveRecommendedQuestion = (col, index, offset) => {
    const list = col._draft.recommended;
    const target = index + offset;
    if (target < 0 || target >= list.length) return;
    [list[index], list[target]] = [list[target], list[index]];
  };

  const removeRecommendedQuestion = (col, index) => {
    col._draft.recommended.splice(index, 1);
  };

  const hidePopularQuestion = (col, question) => {
    if (!col._draft.hidden.includes(question)) col._draft.hidden.push(question);
  };

  const unhidePopularQuestion = (col, question) => {
    col._draft.hidden = col._draft.hidden.filter((q) => q !== question);
  };

  const addCollection = async () => {
    // 2026.07.22(sychoi) 수정 - 슬롯 전체 길이가 아니라 "저장 완료된" 개수 기준으로 제한
    // (헤더 배지 savedCollectionCount와 동일 기준. 초과 저장은 백엔드 max_collections가 최종 차단)
    if (savedCollectionCount.value >= MAX_COLLECTIONS || collections.value.some((c) => c._isNew)) return;
    // 2026.11.12(woojin.jung) 수정 - 새 대화 주제는 목록 끝에 추가하고 바로 상세(기본 정보)를 연다. 질문도 만들기 전에 등록 가능
    if (!(await confirmLeave())) return;
    const key = `new-${++tmpKey}`;
    collections.value.push({
      collection_id: null,
      collection_name: '',
      collection_desc: '',
      document_count: 0,
      can_update: true,
      can_delete: true,
      _key: key,
      _isNew: true,
      _saved: emptyValues(),
      _draft: emptyValues(),
      _touched: false,
      _faqLoaded: true,
      _popular: [],
      _popularDays: 30,
      _newQuestion: '',
    });
    selectedKey.value = key;
    activeTab.value = 'basic';
    mobileDetail.value = true;
  };

  const discardChanges = () => {
    const col = currentCollection.value;
    if (!col) return;
    if (col._isNew) {
      collections.value = collections.value.filter((c) => c !== col);
      selectedKey.value = collections.value[0] ? keyOf(collections.value[0]) : null;
      mobileDetail.value = false;
      return;
    }
    col._draft = cloneValues(col._saved);
    col._newQuestion = '';
    col._touched = false;
  };

  // 2026.11.12(woojin.jung) 수정 - 하단 저장 바: 바뀐 영역(기본 정보·시작 화면 질문)만 저장, 새 대화 주제는 생성 후 질문까지 저장
  const saveCollection = async () => {
    const col = currentCollection.value;
    if (!col || isSavingCollection.value) return false;
    const name = col._draft.name.trim();
    if (!name) {
      col._touched = true;
      activeTab.value = 'basic';
      showAlert('유효한 대화 주제 이름을 입력해주세요.', 'error');
      return false;
    }

    const changes = changesOf(col);
    const payload = { name, description: col._draft.desc.trim(), topic_name: name };
    const questions = { recommended: col._draft.recommended.map((q) => q.trim()).filter(Boolean), hidden: col._draft.hidden };
    let collectionId = col.collection_id;
    isSavingCollection.value = true;
    try {
      if (col._isNew) {
        const res = await collectionApi.create(payload);
        collectionId = res.data.collection_id;
        // 생성은 끝났으므로 질문 저장이 실패해도 목록에는 저장된 대화 주제로 남긴다
        col._isNew = false;
        col.collection_id = collectionId;
        col.collection_name = payload.name;
        col._saved.name = payload.name;
        col._saved.desc = payload.description;
        selectedKey.value = collectionId;
        if (questions.recommended.length) await collectionApi.saveStartQuestions(collectionId, questions);
        showAlert(`대화 주제 "${name}"이(가) 생성되었습니다.`, 'success');
      } else {
        if (changes.basic) {
          await collectionApi.update(collectionId, payload);
          col.collection_name = payload.name;
          col._saved.name = payload.name;
          col._saved.desc = payload.description;
        }
        if (changes.faq) await collectionApi.saveStartQuestions(collectionId, questions);
        showAlert(`대화 주제 "${name}"이(가) 수정되었습니다.`, 'success');
      }
      await loadCollections();
      selectedKey.value = collectionId;
      return true;
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || '저장에 실패했습니다.';
      showAlert(detail, 'error');
      return false;
    } finally {
      isSavingCollection.value = false;
    }
  };

  const confirmDelete = (col) => {
    if (isSavingCollection.value || !col) return;
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
      // 2026.11.12(woojin.jung) 추가 - 삭제 후 목록 화면·첫 번째 대화 주제로 이동
      selectedKey.value = null;
      mobileDetail.value = false;
      await loadCollections();
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || '삭제에 실패했습니다.';
      showAlert(detail, 'error');
      deleteTarget.value = null;
    }
  };

  const logout = async () => {
    if (isSavingCollection.value) return;
    // 2026.11.12(woojin.jung) 추가 - 저장하지 않은 변경이 있으면 로그아웃 전에 확인
    if (!(await confirmLeave())) return;
    await authStore.logoutAny();
    router.push('/login');
  };

  // 2026.11.12(woojin.jung) 추가 - 저장하지 않은 변경이 있을 때 다른 메뉴 이동·새로고침·창 닫기 확인
  onBeforeRouteLeave(() => confirmLeave());
  const handleBeforeUnload = (event) => {
    if (!hasUnsavedChanges.value) return;
    event.preventDefault();
    event.returnValue = '';
  };

  onMounted(() => {
    window.addEventListener('beforeunload', handleBeforeUnload);
    loadCollections();
  });
  onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload));

  return {
    isAdmin,
    displayName,
    collections,
    deleteTarget,
    sidebarOpen,
    alertMessage,
    alertType,
    isSavingCollection,
    savedCollectionCount,
    maxCollections: MAX_COLLECTIONS,
    addCollection,
    saveCollection,
    confirmDelete,
    doDelete,
    logout,
    // 2026.11.12(woojin.jung) 추가 - 목록 + 상세(탭) + 하단 저장 바
    selectedKey,
    activeTab,
    mobileDetail,
    currentCollection,
    currentChanges,
    changesOf,
    keyOf,
    selectCollection,
    discardChanges,
    unsavedDialog,
    resolveUnsaved,
    // 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면 질문 설정
    maxRecommendedQuestions: MAX_RECOMMENDED_QUESTIONS,
    maxQuestionLength: MAX_QUESTION_LENGTH,
    visiblePopular,
    addRecommendedQuestion,
    moveRecommendedQuestion,
    removeRecommendedQuestion,
    hidePopularQuestion,
    unhidePopularQuestion,
  };
};
