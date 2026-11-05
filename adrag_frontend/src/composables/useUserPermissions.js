import { computed, onMounted, ref } from 'vue';
import { adminApi } from '../api/adminApi';
import { useAuthStore } from '../stores/authStore';

const SECURITY_LABELS = {
  public: '공개',
  internal: '부서 내부',
  confidential: '대외비',
  restricted: '비밀',
};

const normalizeCollectionId = (collection) =>
  typeof collection === 'string' ? collection : collection.qdrant_name || collection.collection_name || collection.topic_name || collection.name;

const getErrorMessage = (error, fallback) => {
  const detail = error.response?.data?.detail;
  return (typeof detail === 'string' ? detail : detail?.message) || fallback;
};

const getUserDepartment = (user) =>
  user._department ??
  (user.department?.name ||
    user.department ||
    user.department_name ||
    user.dept_name ||
    user.dept_id ||
    user.metadata_filters?.department ||
    user.metadata_filters?.dept ||
    '');

export const useUserPermissions = ({ router }) => {
  const authStore = useAuthStore();

  const adminName = computed(() => authStore.displayName);
  const sidebarOpen = ref(false);
  const users = ref([]);
  const departments = ref([]);
  const logs = ref([]);
  const allCollections = ref([]);
  const serverSummary = ref({ total_users: 0, active_departments: 0, unassigned_users: 0 });
  const activeTab = ref('users');
  const searchQuery = ref('');
  const departmentFilter = ref('');
  const departmentSearchQuery = ref('');
  const loading = ref(false);
  const loadError = ref('');
  const toast = ref({ visible: false, message: '', type: 'success' });
  const savingUsers = ref(new Set());
  const savedUsers = ref(new Set());
  const showAddModal = ref(false);
  const showPermissionModal = ref(false);
  const showDepartmentModal = ref(false);
  const showEditUserModal = ref(false);
  const addLoading = ref(false);
  const addError = ref('');
  const newUser = ref({ user_id: '', user_name: '', password: '', department: '' });
  const addTouched = ref({ user_id: false, user_name: false, password: false });
  const permissionTarget = ref(null);
  const permissionDraft = ref({ collections: [], securityLevel: 'internal', docTypes: '' });
  const departmentTarget = ref(null);
  const departmentDraft = ref({ id: '', name: '', categories: [], active: true });
  const departmentModalLoading = ref(false);
  const departmentSaving = ref(false);
  const departmentModalError = ref('');
  const editUserTarget = ref(null);
  const editUserDraft = ref({ name: '', department: '', active: true });

  let toastTimer = null;

  const addFieldErrors = computed(() => {
    const userId = newUser.value.user_id.trim();
    const userName = newUser.value.user_name.trim();
    const password = newUser.value.password;
    const errors = {};

    if (!userId) {
      errors.user_id = '아이디를 입력해주세요.';
    } else if (userId.length < 3 || userId.length > 50) {
      errors.user_id = '아이디는 3~50자로 입력해주세요.';
    } else if (!/^[A-Za-z0-9_.-]+$/.test(userId)) {
      errors.user_id = '아이디는 영문, 숫자, 점, -, _만 사용할 수 있습니다.';
    }

    if (userName.length > 50) {
      errors.user_name = '이름은 50자 이하로 입력해주세요.';
    }

    if (!newUser.value.department) {
      errors.department = '소속 부서를 선택해주세요.';
    }

    if (!password) {
      errors.password = '비밀번호를 입력해주세요.';
    } else if (password.length < 6) {
      errors.password = '비밀번호는 6자 이상 입력해주세요.';
    }

    return errors;
  });

  const isNewUserValid = computed(() => Object.keys(addFieldErrors.value).length === 0);

  const collectionOptions = computed(() =>
    allCollections.value.map((collection) => ({
      id: normalizeCollectionId(collection),
      name: typeof collection === 'string' ? collection : collection.collection_name || collection.topic_name || collection.name || normalizeCollectionId(collection),
      createdBy: typeof collection === 'string' ? '' : collection.created_by || '',
    }))
  );

  const departmentOptions = computed(() =>
    departments.value.filter((department) => department.active).map((department) => department.name).sort((a, b) => a.localeCompare(b, 'ko'))
  );

  const departmentRows = computed(() =>
    departments.value.map((department) => ({
      ...department,
      userCount: users.value.filter((user) => getUserDepartment(user) === department.name).length,
      categoryNames: department.categories.map(collectionNameById),
    }))
  );

  const filteredUsers = computed(() => {
    const query = searchQuery.value.trim().toLowerCase();
    return users.value.filter((user) => {
      const department = getUserDepartment(user) || '미지정';
      const haystack = `${user.user_id || ''} ${user.user_name || ''}`.toLowerCase();
      const matchesQuery = !query || haystack.includes(query);
      const matchesDepartment =
        !departmentFilter.value ||
        (departmentFilter.value === '__unassigned__' ? !getUserDepartment(user) : department === departmentFilter.value);
      return matchesQuery && matchesDepartment;
    });
  });

  const filteredDepartments = computed(() => {
    const query = departmentSearchQuery.value.trim().toLowerCase();
    return departmentRows.value.filter((department) => !query || department.name.toLowerCase().includes(query));
  });

  const summary = computed(() => ({
    totalUsers: serverSummary.value.total_users,
    activeDepartments: serverSummary.value.active_departments,
    unassignedUsers: serverSummary.value.unassigned_users,
  }));

  const resetAddModal = () => {
    addLoading.value = false;
    addError.value = '';
    newUser.value = { user_id: '', user_name: '', password: '', department: '' };
    addTouched.value = { user_id: false, user_name: false, password: false };
  };

  const showToast = (message, type = 'success') => {
    if (toastTimer) clearTimeout(toastTimer);
    toast.value = { visible: true, message, type };
    toastTimer = setTimeout(() => {
      toast.value.visible = false;
    }, 2500);
  };

  const touchAddField = (field) => {
    addTouched.value = { ...addTouched.value, [field]: true };
  };

  const openAddModal = () => {
    resetAddModal();
    showAddModal.value = true;
  };

  const closeAddModal = () => {
    showAddModal.value = false;
    resetAddModal();
  };

  const logout = async () => {
    await authStore.logoutAdminOnly();
    router.push('/login');
  };

  const createUser = async () => {
    const userId = newUser.value.user_id.trim();
    const password = newUser.value.password;
    const selectedDepartment = newUser.value.department;
    addTouched.value = { user_id: true, user_name: true, password: true };
    if (addLoading.value || !isNewUserValid.value) return;

    addError.value = '';
    addLoading.value = true;
    try {
      const department = departments.value.find((item) => item.name === selectedDepartment);
      const body = {
        login_id: userId,
        name: newUser.value.user_name.trim() || userId,
        department_id: department?.id,
        password,
        // UI 연동 방식은 신규 사용자가 로그인한 뒤 최초 1회 직접 확정한다.
        ui_type: null,
        ui_type_configured: false,
      };
      await adminApi.createUser(body);
      closeAddModal();
      showToast('사용자가 추가되었습니다.');
      await loadUsers();
    } catch (err) {
      addError.value = getErrorMessage(err, '사용자 추가에 실패했습니다.');
    } finally {
      addLoading.value = false;
    }
  };

  const collectionNameById = (id) => {
    const collection = collectionOptions.value.find((item) => item.id === id);
    return collection?.name || id;
  };

  const userDepartment = (user) => getUserDepartment(user);
  const userDisplayName = (user) => user.user_name || user.user_id || '-';
  const userInitial = (user) => userDisplayName(user).slice(0, 1).toUpperCase();
  const securityLabel = (level) => SECURITY_LABELS[level] || level || '부서 내부';
  const userCollections = (user) => {
    const department = departments.value.find((item) => item.name === getUserDepartment(user));
    if (!department) return [];
    return (user._selectedCollections || []).filter((id) => department.categories.includes(id)).map(collectionNameById);
  };
  const userBlockedCount = (user) => {
    const department = departments.value.find((item) => item.name === getUserDepartment(user));
    if (!department) return 0;
    return department.categories.filter((id) => !(user._selectedCollections || []).includes(id)).length;
  };

  const openDepartmentModal = async (department = null) => {
    departmentTarget.value = department;
    departmentModalError.value = '';
    departmentDraft.value = department
      ? { id: department.id, name: department.name, categories: [...department.categories], active: department.active }
      : { id: `D${String(departments.value.length + 1).padStart(3, '0')}`, name: '', categories: [], active: true };
    showDepartmentModal.value = true;
    departmentModalLoading.value = true;
    try {
      await loadTopics();
      if (department) {
        const { data } = await adminApi.department(department.id);
        const detail = data.department || data;
        departmentDraft.value = {
          id: detail.id || detail.department_id || department.id,
          name: detail.name || detail.department_name || department.name,
          categories: [...(detail.topic_names || detail.topics || department.categories || [])].map(normalizeCollectionId),
          active: detail.is_active !== false,
        };
      }
    } catch (err) {
      departmentModalError.value = getErrorMessage(err, '부서 정보를 불러오지 못했습니다.');
    } finally {
      departmentModalLoading.value = false;
    }
  };

  const closeDepartmentModal = () => {
    showDepartmentModal.value = false;
    departmentTarget.value = null;
    departmentModalError.value = '';
  };

  const saveDepartmentDraft = async () => {
    const name = departmentDraft.value.name.trim();
    if (!name) return showToast('부서명을 입력해주세요.', 'error');
    if (departments.value.some((item) => item.id !== departmentDraft.value.id && item.name.toLowerCase() === name.toLowerCase())) {
      return showToast('이미 등록된 부서명입니다.', 'error');
    }
    const isEditing = Boolean(departmentTarget.value);
    departmentSaving.value = true;
    try {
      const payload = { name, topic_names: [...departmentDraft.value.categories] };
      if (departmentTarget.value) {
        payload.is_active = departmentDraft.value.active;
        await adminApi.updateDepartment(departmentDraft.value.id, payload);
      } else {
        await adminApi.createDepartment(payload);
      }
      closeDepartmentModal();
      showToast(`부서가 ${isEditing ? '수정' : '추가'}되었습니다.`);
      await loadAll();
    } catch (err) {
      showToast(getErrorMessage(err, '부서 저장에 실패했습니다.'), 'error');
    } finally {
      departmentSaving.value = false;
    }
  };

  // 2026.07.22(sychoi) 추가 - 부서명 입력에서 Enter로 추가/저장 실행
  // 저장 버튼의 :disabled 조건과 동일하게 막아 중복 제출·로딩 중 실행을 방지한다.
  const handleDepartmentNameEnter = () => {
    if (departmentModalLoading.value || departmentSaving.value) return;
    if (!departmentDraft.value.name.trim()) return;
    saveDepartmentDraft();
  };

  const toggleDepartment = async (department) => {
    try {
      await adminApi.updateDepartment(department.id, { is_active: !department.active });
      showToast(`${department.name} 부서를 ${department.active ? '비활성화' : '활성화'}했습니다.`);
      await loadAll();
    } catch (err) {
      showToast(getErrorMessage(err, '부서 상태 변경에 실패했습니다.'), 'error');
    }
  };

  const openEditUserModal = (user) => {
    editUserTarget.value = user;
    editUserDraft.value = { name: userDisplayName(user), department: getUserDepartment(user), active: user._isActive !== false };
    showEditUserModal.value = true;
  };

  const closeEditUserModal = () => {
    showEditUserModal.value = false;
    editUserTarget.value = null;
  };

  const saveEditUserDraft = async () => {
    if (!editUserTarget.value) return;
    const department = departments.value.find((item) => item.name === editUserDraft.value.department);
    try {
      await adminApi.updateUser(editUserTarget.value.user_id, {
        name: editUserDraft.value.name.trim() || editUserTarget.value.user_id,
        department_id: department?.id,
        is_active: editUserDraft.value.active,
      });
      closeEditUserModal();
      showToast('사용자 정보가 수정되었습니다.');
      await loadAll();
    } catch (err) {
      showToast(getErrorMessage(err, '사용자 정보 수정에 실패했습니다.'), 'error');
    }
  };

  const openPermissionModal = async (user) => {
    permissionTarget.value = user;
    permissionDraft.value = {
      collections: [...(user._selectedCollections || [])],
      securityLevel: user.max_security_level || 'internal',
      docTypes: user._docTypes || '',
    };
    showPermissionModal.value = true;
    try {
      const { data } = await adminApi.userPermissions(user.user_id);
      permissionDraft.value.collections = (data.department_topics || []).filter(
        (topic) => !(data.blocked_topics || []).includes(topic)
      );
    } catch (err) {
      showToast(getErrorMessage(err, '사용자 권한을 불러오지 못했습니다.'), 'error');
    }
  };

  const permissionCollectionOptions = computed(() => {
    const department = departments.value.find((item) => item.name === getUserDepartment(permissionTarget.value || {}));
    if (!department) return [];
    return collectionOptions.value.filter((collection) => department.categories.includes(collection.id));
  });

  const closePermissionModal = () => {
    showPermissionModal.value = false;
    permissionTarget.value = null;
    permissionDraft.value = { collections: [], securityLevel: 'internal', docTypes: '' };
  };

  const savePermissionDraft = async () => {
    if (!permissionTarget.value) return;
    const user = permissionTarget.value;
    const department = departments.value.find((item) => item.name === getUserDepartment(user));
    const selected = new Set(permissionDraft.value.collections);
    const blockedTopics = (department?.categories || []).filter((topic) => !selected.has(topic));
    const saved = await saveUser(user, blockedTopics);
    if (saved) closePermissionModal();
  };

  const loadTopics = async () => {
    try {
      const res = await adminApi.topics();
      const topics = Array.isArray(res.data) ? res.data : res.data.topics || res.data.items || [];
      allCollections.value = topics;
    } catch (err) {
      allCollections.value = [];
      throw err;
    }
  };

  const loadDepartments = async () => {
    const res = await adminApi.departments();
    departments.value = (res.data || []).map((department) => ({
      ...department,
      categories: department.topic_names || [],
      active: department.is_active !== false,
      userCount: department.user_count || 0,
    }));
  };

  const loadSummary = async () => {
    const res = await adminApi.summary();
    serverSummary.value = res.data;
  };

  const loadUsers = async () => {
    const res = await adminApi.users({ page: 1, size: 100 });
    users.value = (res.data.items || res.data.users || []).map((user) => ({
      ...user,
      user_id: user.id || user.user_id,
      user_name: user.name || user.user_name,
      _selectedCollections: user.effective_topics || user.accessible_collections || [],
      _blockedTopics: user.blocked_topics || [],
      _docTypes: (user.allowed_document_types || []).join(','),
      _metadataFilters: user.metadata_filters || {},
      _department: getUserDepartment(user),
      _isActive: user.is_active !== false,
    }));
  };

  const loadLogs = async () => {
    try {
      const res = await adminApi.logs(20);
      logs.value = res.data.logs || [];
    } catch {
      logs.value = [];
    }
  };

  const loadAll = async () => {
    loading.value = true;
    loadError.value = '';
    try {
      await Promise.all([loadTopics(), loadDepartments(), loadSummary(), loadUsers(), loadLogs()]);
    } catch (err) {
      loadError.value = getErrorMessage(err, '사용자 권한 정보를 불러오지 못했습니다.');
      showToast(loadError.value, 'error');
    } finally {
      loading.value = false;
    }
  };

  const saveUser = async (user, blockedTopics = user._blockedTopics || []) => {
    const uid = user.user_id;
    savingUsers.value = new Set([...savingUsers.value, uid]);
    savedUsers.value.delete(uid);

    try {
      await adminApi.saveUserPermissions(uid, { blocked_topics: blockedTopics });
      savedUsers.value = new Set([...savedUsers.value, uid]);
      showToast(`${userDisplayName(user)} 권한이 저장되었습니다.`);
      setTimeout(() => {
        savedUsers.value.delete(uid);
        savedUsers.value = new Set(savedUsers.value);
      }, 2500);
      await loadUsers();
      return true;
    } catch (err) {
      showToast(getErrorMessage(err, '권한 저장에 실패했습니다.'), 'error');
      return false;
    } finally {
      savingUsers.value.delete(uid);
      savingUsers.value = new Set(savingUsers.value);
    }
  };

  onMounted(() => {
    loadAll();
  });

  return {
    adminName,
    sidebarOpen,
    logout,
    users,
    logs,
    allCollections,
    collectionOptions,
    departmentOptions,
    departments,
    departmentRows,
    filteredUsers,
    filteredDepartments,
    summary,
    activeTab,
    searchQuery,
    departmentFilter,
    departmentSearchQuery,
    loading,
    loadError,
    loadAll,
    saveUser,
    showAddModal,
    openAddModal,
    closeAddModal,
    addLoading,
    addError,
    newUser,
    addTouched,
    addFieldErrors,
    isNewUserValid,
    touchAddField,
    createUser,
    toast,
    savingUsers,
    savedUsers,
    showPermissionModal,
    permissionTarget,
    permissionDraft,
    openPermissionModal,
    closePermissionModal,
    savePermissionDraft,
    userDepartment,
    userDisplayName,
    userInitial,
    securityLabel,
    userCollections,
    collectionNameById,
    userBlockedCount,
    permissionCollectionOptions,
    showDepartmentModal,
    departmentTarget,
    departmentDraft,
    departmentModalLoading,
    departmentSaving,
    departmentModalError,
    openDepartmentModal,
    closeDepartmentModal,
    saveDepartmentDraft,
    handleDepartmentNameEnter,
    toggleDepartment,
    showEditUserModal,
    editUserTarget,
    editUserDraft,
    openEditUserModal,
    closeEditUserModal,
    saveEditUserDraft,
  };
};
