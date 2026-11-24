// 2026.11.20(woojin.jung) 수정 - 부서 운영관리자 역할 + 부서 패널 화면
//   (docs/admin_UI-역할분리_부서운영관리자_20261120.html)
//   - admin  : 왼쪽 부서 목록 + 부서 요약 + 사용자 표. 운영관리자는 부서당 1명, 운영관리자를 먼저 등록해야 일반 사용자 등록 가능.
//   - manager: 같은 부서 요약 + 표를 자기 부서로 고정(일반 사용자 권한 설정만).
import { computed, onMounted, ref } from 'vue';
import { adminApi } from '../api/adminApi';
import { managerApi } from '../api/managerApi';
import { useAuthStore } from '../stores/authStore';
import { PASSWORD_RULE_TEXT, PASSWORD_TOO_LONG_TEXT, isPasswordPolicyMet, isPasswordTooLong } from '../constants/passwordPolicy';

const getErrorMessage = (error, fallback) => {
  const detail = error.response?.data?.detail;
  return (typeof detail === 'string' ? detail : detail?.message) || fallback;
};

const normalizeDepartment = (department) => ({
  ...department,
  categories: department.topic_names || [],
  active: department.is_active !== false,
  userCount: department.user_count || 0,
  activeUserCount: department.active_user_count || 0,
  blockedUserCount: department.blocked_user_count || 0,
  manager: department.manager || null,
});

const normalizeUser = (user) => ({
  user_id: user.id || user.user_id,
  user_name: user.name || user.user_name,
  role: user.role || 'user',
  departmentId: user.department?.id || '',
  departmentName: user.department?.name || '',
  effectiveTopics: user.effective_topics || [],
  blockedCount: user.blocked_count || 0,
  isActive: user.is_active !== false,
});

export const useUserPermissions = ({ router, route, mode = 'admin' }) => {
  const authStore = useAuthStore();
  const isAdminMode = mode === 'admin';

  const adminName = computed(() => authStore.displayName);
  const sidebarOpen = ref(false);
  const users = ref([]);
  const departments = ref([]);
  const myDepartment = ref(null);
  const allCollections = ref([]);
  const serverSummary = ref({ total_users: 0, active_users: 0, active_departments: 0, managed_departments: 0 });
  const searchQuery = ref('');
  const roleFilter = ref('');
  const statusFilter = ref('');
  const departmentSearchQuery = ref('');
  const loading = ref(false);
  const loadError = ref('');
  const toast = ref({ visible: false, message: '', type: 'success' });
  const savingUsers = ref(new Set());

  let toastTimer = null;
  const showToast = (message, type = 'success') => {
    if (toastTimer) clearTimeout(toastTimer);
    toast.value = { visible: true, message, type };
    toastTimer = setTimeout(() => {
      toast.value.visible = false;
    }, 2500);
  };

  // ── 부서 선택 (주소 쿼리 ?dept= 로 유지, 빈 값 = 전체) ──────────────────────
  const selectedDepartmentId = computed(() => (isAdminMode ? String(route.query.dept || '') : myDepartment.value?.id || ''));
  const selectDepartment = (departmentId) => {
    router.replace({ query: departmentId ? { ...route.query, dept: departmentId } : {} });
  };

  const activeDepartments = computed(() => departments.value.filter((department) => department.active));
  const panelDepartments = computed(() => {
    const query = departmentSearchQuery.value.trim().toLowerCase();
    return departments.value.filter((department) => !query || department.name.toLowerCase().includes(query));
  });
  const departmentById = (id) => departments.value.find((department) => department.id === id) || null;

  const selectedDepartment = computed(() => (isAdminMode ? departmentById(selectedDepartmentId.value) : myDepartment.value));
  const noManagerDepartments = computed(() => activeDepartments.value.filter((department) => !department.manager));
  const summary = computed(() => ({
    totalUsers: serverSummary.value.total_users || 0,
    activeUsers: serverSummary.value.active_users || 0,
    activeDepartments: serverSummary.value.active_departments || 0,
    managedDepartments: serverSummary.value.managed_departments || 0,
  }));

  const filteredUsers = computed(() => {
    const query = searchQuery.value.trim().toLowerCase();
    return users.value.filter((user) => {
      if (isAdminMode && selectedDepartmentId.value && user.departmentId !== selectedDepartmentId.value) return false;
      if (query && !`${user.user_id} ${user.user_name}`.toLowerCase().includes(query)) return false;
      if (roleFilter.value && user.role !== roleFilter.value) return false;
      if (statusFilter.value === 'active' && !user.isActive) return false;
      if (statusFilter.value === 'inactive' && user.isActive) return false;
      if (statusFilter.value === 'blocked' && !user.blockedCount) return false;
      return true;
    });
  });

  const userDisplayName = (user) => user?.user_name || user?.user_id || '-';
  const userInitial = (user) => userDisplayName(user).slice(0, 1).toUpperCase();

  // ── 불러오기 ───────────────────────────────────────────────────────────
  // 2026.11.23(woojin.jung) 수정 - 부서 수정 창에서 그 부서 대화 주제만 불러온다(다른 부서 주제는 허용해도 검색에 쓰이지 않음)
  const loadTopics = async (departmentId) => {
    const res = await adminApi.topics({ department_id: departmentId });
    allCollections.value = Array.isArray(res.data) ? res.data : res.data.topics || res.data.items || [];
  };

  const loadDepartments = async () => {
    if (isAdminMode) {
      const res = await adminApi.departments();
      departments.value = (res.data || []).map(normalizeDepartment);
    } else {
      const res = await managerApi.department();
      myDepartment.value = normalizeDepartment(res.data);
    }
  };

  const loadSummary = async () => {
    const res = await adminApi.summary();
    serverSummary.value = res.data;
  };

  const loadUsers = async () => {
    const res = isAdminMode ? await adminApi.users({ page: 1, size: 100 }) : await managerApi.members({ page: 1, size: 100 });
    users.value = (res.data.items || []).map(normalizeUser);
  };

  const loadAll = async () => {
    loading.value = true;
    loadError.value = '';
    try {
      const tasks = [loadDepartments(), loadUsers()];
      if (isAdminMode) tasks.push(loadSummary());
      await Promise.all(tasks);
    } catch (err) {
      loadError.value = getErrorMessage(err, '사용자 권한 정보를 불러오지 못했습니다.');
      showToast(loadError.value, 'error');
    } finally {
      loading.value = false;
    }
  };

  // ── 사용자 추가 (관리자) ──────────────────────────────────────────────────
  const showAddModal = ref(false);
  // '' | 'department'(활성 부서 없음) | 'manager'(운영관리자가 있는 부서 없음)
  const addPrerequisite = ref('');
  const addLoading = ref(false);
  const addError = ref('');
  const newUser = ref({ user_id: '', user_name: '', password: '', departmentId: '' });
  const addTouched = ref({ user_id: false, user_name: false, password: false });

  const newUserDepartment = computed(() => departmentById(newUser.value.departmentId));
  // 운영관리자가 없는 부서 → 운영관리자만, 있는 부서 → 일반 사용자만(부서당 1명)
  const newUserRole = computed(() => (newUserDepartment.value && !newUserDepartment.value.manager ? 'manager' : 'user'));

  const departmentOptionLabel = (department) =>
    `${department.name} · ${department.manager ? `운영관리자 ${department.manager.name}` : '운영관리자 없음'}`;

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
    if (userName.length > 50) errors.user_name = '이름은 50자 이하로 입력해주세요.';
    if (!newUser.value.departmentId) errors.department = '소속 부서를 선택해주세요.';
    if (!password) {
      errors.password = '비밀번호를 입력해주세요.';
    } else if (!isPasswordPolicyMet(password)) {
      // 2026.11.13(woojin.jung) 수정 - 비밀번호 규칙 강화(6자 → 영문·숫자 포함 8자)
      errors.password = `비밀번호는 ${PASSWORD_RULE_TEXT}으로 입력해주세요.`;
    } else if (isPasswordTooLong(password)) {
      errors.password = PASSWORD_TOO_LONG_TEXT;
    } else if (password === userId) {
      errors.password = '아이디와 같은 비밀번호는 사용할 수 없습니다.';
    }
    return errors;
  });
  const isNewUserValid = computed(() => Object.keys(addFieldErrors.value).length === 0);

  const resetAddModal = (departmentId = '') => {
    addLoading.value = false;
    addError.value = '';
    newUser.value = { user_id: '', user_name: '', password: '', departmentId };
    addTouched.value = { user_id: false, user_name: false, password: false };
  };

  const openAddModal = (departmentId = selectedDepartmentId.value) => {
    if (activeDepartments.value.length === 0) {
      addPrerequisite.value = 'department';
      return;
    }
    const preset = departmentById(departmentId);
    if (!preset && noManagerDepartments.value.length === activeDepartments.value.length) {
      addPrerequisite.value = 'manager';
      return;
    }
    const fallback = activeDepartments.value.find((department) => department.manager) || activeDepartments.value[0];
    resetAddModal(preset?.active ? preset.id : fallback.id);
    showAddModal.value = true;
  };

  // 운영관리자 선등록 안내 → 운영관리자가 없는 첫 부서로 사용자 추가(운영관리자 역할)
  const openManagerRegistration = (departmentId = '') => {
    addPrerequisite.value = '';
    resetAddModal(departmentId || noManagerDepartments.value[0]?.id || '');
    showAddModal.value = true;
  };

  const closeAddPrerequisite = () => {
    addPrerequisite.value = '';
  };

  const closeAddModal = () => {
    showAddModal.value = false;
    resetAddModal();
  };

  const touchAddField = (field) => {
    addTouched.value = { ...addTouched.value, [field]: true };
  };

  const createUser = async () => {
    addTouched.value = { user_id: true, user_name: true, password: true };
    if (addLoading.value || !isNewUserValid.value) return;
    const userId = newUser.value.user_id.trim();
    addError.value = '';
    addLoading.value = true;
    try {
      await adminApi.createUser({
        login_id: userId,
        name: newUser.value.user_name.trim() || userId,
        department_id: newUser.value.departmentId,
        password: newUser.value.password,
        role: newUserRole.value,
        // UI 연동 방식은 신규 사용자가 로그인한 뒤 최초 1회 직접 확정한다.
        ui_type: null,
      });
      const isManager = newUserRole.value === 'manager';
      const departmentId = newUser.value.departmentId;
      closeAddModal();
      showToast(isManager ? '부서 운영관리자가 등록되었습니다.' : '사용자가 추가되었습니다.');
      await loadAll();
      if (isAdminMode) selectDepartment(departmentId);
    } catch (err) {
      addError.value = getErrorMessage(err, '사용자 추가에 실패했습니다.');
    } finally {
      addLoading.value = false;
    }
  };

  // ── 정보 수정 (관리자) ─────────────────────────────────────────────────────
  const showEditUserModal = ref(false);
  const editUserTarget = ref(null);
  const editUserDraft = ref({ name: '', departmentId: '', active: true });
  const editTargetIsManager = computed(() => editUserTarget.value?.role === 'manager');
  // 일반 사용자는 운영관리자가 있는 부서로만 이동할 수 있다
  const editDepartmentOptions = computed(() =>
    activeDepartments.value.filter((department) => department.manager || department.id === editUserTarget.value?.departmentId)
  );

  const openEditUserModal = (user) => {
    editUserTarget.value = user;
    editUserDraft.value = { name: userDisplayName(user), departmentId: user.departmentId, active: user.isActive };
    showEditUserModal.value = true;
  };

  const closeEditUserModal = () => {
    showEditUserModal.value = false;
    editUserTarget.value = null;
  };

  const saveEditUserDraft = async () => {
    const target = editUserTarget.value;
    if (!target) return;
    const payload = { name: editUserDraft.value.name.trim() || target.user_id };
    if (!editTargetIsManager.value) {
      payload.department_id = editUserDraft.value.departmentId || undefined;
      payload.is_active = editUserDraft.value.active;
    }
    try {
      await adminApi.updateUser(target.user_id, payload);
      closeEditUserModal();
      showToast('사용자 정보가 수정되었습니다.');
      await loadAll();
    } catch (err) {
      showToast(getErrorMessage(err, '사용자 정보 수정에 실패했습니다.'), 'error');
    }
  };

  // ── 운영관리자 변경 (관리자) ──────────────────────────────────────────────────
  const showChangeManagerModal = ref(false);
  const changeManagerTarget = ref(null);
  const changeManagerDraft = ref({ newManagerId: '', previousAction: 'demote' });
  const changeManagerSaving = ref(false);
  const changeManagerError = ref('');
  const successorOptions = computed(() =>
    users.value.filter((user) => user.departmentId === changeManagerTarget.value?.id && user.role === 'user' && user.isActive)
  );

  const openChangeManagerModal = (department) => {
    changeManagerTarget.value = department;
    changeManagerError.value = '';
    changeManagerDraft.value = { newManagerId: '', previousAction: 'demote' };
    changeManagerDraft.value.newManagerId = successorOptions.value[0]?.user_id || '';
    showChangeManagerModal.value = true;
  };

  const closeChangeManagerModal = () => {
    showChangeManagerModal.value = false;
    changeManagerTarget.value = null;
  };

  const saveChangeManager = async () => {
    const department = changeManagerTarget.value;
    if (!department || !changeManagerDraft.value.newManagerId || changeManagerSaving.value) return;
    changeManagerSaving.value = true;
    changeManagerError.value = '';
    try {
      await adminApi.changeDepartmentManager(department.id, {
        new_manager_id: changeManagerDraft.value.newManagerId,
        previous_action: changeManagerDraft.value.previousAction,
      });
      closeChangeManagerModal();
      showToast(`${department.name} 운영관리자가 변경되었습니다.`);
      await loadAll();
    } catch (err) {
      changeManagerError.value = getErrorMessage(err, '운영관리자 변경에 실패했습니다.');
    } finally {
      changeManagerSaving.value = false;
    }
  };

  // ── 권한 설정 (관리자·운영관리자 공용) ────────────────────────────────────────
  const showPermissionModal = ref(false);
  const permissionTarget = ref(null);
  const permissionTopics = ref([]);
  const permissionDraft = ref([]);
  const permissionLoading = ref(false);
  // 2026.11.23(woojin.jung) 추가 - 비활성 부서의 운영관리자는 권한 조회만(관리자는 비활성 부서도 수정 가능)
  const permissionReadOnly = computed(() => !isAdminMode && !!selectedDepartment.value && !selectedDepartment.value.active);
  // 2026.11.23(woojin.jung) 추가 - 부서 주제를 모두 체크 해제한 상태(저장 시 전체 차단)
  const blocksAllTopics = computed(
    () => !permissionLoading.value && permissionTopics.value.length > 0 && permissionDraft.value.length === 0
  );

  const openPermissionModal = async (user) => {
    permissionTarget.value = user;
    permissionTopics.value = [];
    permissionDraft.value = [];
    showPermissionModal.value = true;
    permissionLoading.value = true;
    try {
      const { data } = isAdminMode ? await adminApi.userPermissions(user.user_id) : await managerApi.memberPermissions(user.user_id);
      const blocked = new Set(data.blocked_topics || []);
      permissionTopics.value = data.department_topics || [];
      permissionDraft.value = permissionTopics.value.filter((topic) => !blocked.has(topic));
    } catch (err) {
      showToast(getErrorMessage(err, '사용자 권한을 불러오지 못했습니다.'), 'error');
    } finally {
      permissionLoading.value = false;
    }
  };

  const closePermissionModal = () => {
    showPermissionModal.value = false;
    permissionTarget.value = null;
  };

  const savePermissionDraft = async () => {
    const user = permissionTarget.value;
    if (!user || savingUsers.value.has(user.user_id)) return;
    const selected = new Set(permissionDraft.value);
    const payload = { blocked_topics: permissionTopics.value.filter((topic) => !selected.has(topic)) };
    savingUsers.value = new Set([...savingUsers.value, user.user_id]);
    try {
      if (isAdminMode) await adminApi.saveUserPermissions(user.user_id, payload);
      else await managerApi.saveMemberPermissions(user.user_id, payload);
      closePermissionModal();
      showToast(`${userDisplayName(user)} 권한이 저장되었습니다.`);
      await loadAll();
    } catch (err) {
      showToast(getErrorMessage(err, '권한 저장에 실패했습니다.'), 'error');
    } finally {
      savingUsers.value.delete(user.user_id);
      savingUsers.value = new Set(savingUsers.value);
    }
  };

  // ── 부서 추가·수정·사용 여부 (관리자) ─────────────────────────────────────────
  const showDepartmentModal = ref(false);
  const departmentTarget = ref(null);
  const departmentDraft = ref({ id: '', name: '', categories: [], active: true });
  const departmentModalLoading = ref(false);
  const departmentSaving = ref(false);
  const departmentModalError = ref('');
  // 활성 부서가 없어 사용자 추가 전에 부서부터 만든 경우: 저장 후 운영관리자 등록으로 이어간다
  const resumeAddAfterDepartment = ref(false);

  // 2026.11.23(woojin.jung) 수정 - 이미 허용된 주제(대화 주제가 지워졌거나 예전에 지정한 것)도 해제할 수 있게 함께 보여 준다
  const collectionOptions = computed(() => {
    const names = allCollections.value.map((collection) => (typeof collection === 'string' ? collection : collection.topic_name || collection.name));
    return [...new Set([...names, ...departmentDraft.value.categories])].map((id) => ({ id, name: id }));
  });

  const openDepartmentModal = async (department = null, shouldResumeUserAdd = false) => {
    resumeAddAfterDepartment.value = shouldResumeUserAdd;
    addPrerequisite.value = '';
    departmentTarget.value = department;
    departmentModalError.value = '';
    departmentDraft.value = department
      ? { id: department.id, name: department.name, categories: [...department.categories], active: department.active }
      : { id: `D${String(departments.value.length + 1).padStart(3, '0')}`, name: '', categories: [], active: true };
    showDepartmentModal.value = true;
    departmentModalLoading.value = true;
    allCollections.value = [];
    try {
      if (department) {
        await loadTopics(department.id);
        const { data } = await adminApi.department(department.id);
        departmentDraft.value = {
          id: data.id || department.id,
          name: data.name || department.name,
          categories: [...(data.topic_names || department.categories || [])],
          active: data.is_active !== false,
        };
      }
    } catch (err) {
      departmentModalError.value = getErrorMessage(err, '부서 정보를 불러오지 못했습니다.');
    } finally {
      departmentModalLoading.value = false;
    }
  };

  const closeDepartmentModal = ({ preserveUserAddFlow = false } = {}) => {
    showDepartmentModal.value = false;
    departmentTarget.value = null;
    departmentModalError.value = '';
    if (!preserveUserAddFlow) resumeAddAfterDepartment.value = false;
  };

  const saveDepartmentDraft = async () => {
    const name = departmentDraft.value.name.trim();
    if (!name) return showToast('부서명을 입력해주세요.', 'error');
    if (departments.value.some((item) => item.id !== departmentDraft.value.id && item.name.toLowerCase() === name.toLowerCase())) {
      return showToast('이미 등록된 부서명입니다.', 'error');
    }
    const isEditing = Boolean(departmentTarget.value);
    const shouldResumeUserAdd = !isEditing && resumeAddAfterDepartment.value;
    departmentSaving.value = true;
    try {
      const payload = { name, topic_names: [...departmentDraft.value.categories] };
      let savedId = departmentDraft.value.id;
      if (isEditing) {
        payload.is_active = departmentDraft.value.active;
        await adminApi.updateDepartment(departmentDraft.value.id, payload);
      } else {
        const { data } = await adminApi.createDepartment(payload);
        savedId = data.id;
      }
      closeDepartmentModal({ preserveUserAddFlow: shouldResumeUserAdd });
      showToast(`부서가 ${isEditing ? '수정' : '추가'}되었습니다.`);
      await loadAll();
      selectDepartment(savedId);
      if (shouldResumeUserAdd) {
        resumeAddAfterDepartment.value = false;
        openManagerRegistration(savedId);
      }
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

  // 2026.11.23(woojin.jung) 수정 - 비활성화는 영향(운영관리자 읽기 전용·부서원 주제 차단)을 확인한 뒤 실행, 활성화는 바로
  const deactivateTarget = ref(null);
  const confirmDeactivate = async () => {
    const department = deactivateTarget.value;
    deactivateTarget.value = null;
    if (department) await updateDepartmentActive(department);
  };
  const toggleDepartment = (department) => {
    if (department.active) {
      deactivateTarget.value = department;
      return;
    }
    return updateDepartmentActive(department);
  };

  const updateDepartmentActive = async (department) => {
    try {
      await adminApi.updateDepartment(department.id, { is_active: !department.active });
      showToast(`${department.name} 부서를 ${department.active ? '비활성화' : '활성화'}했습니다.`);
      await loadAll();
    } catch (err) {
      showToast(getErrorMessage(err, '부서 상태 변경에 실패했습니다.'), 'error');
    }
  };

  const logout = async () => {
    if (isAdminMode) await authStore.logoutAdminOnly();
    else await authStore.logoutAny();
    router.push('/login');
  };

  onMounted(loadAll);

  return {
    isAdminMode,
    adminName,
    sidebarOpen,
    logout,
    loading,
    loadError,
    loadAll,
    toast,
    // 부서
    departments,
    panelDepartments,
    activeDepartments,
    departmentSearchQuery,
    selectedDepartmentId,
    selectedDepartment,
    selectDepartment,
    noManagerDepartments,
    summary,
    // 사용자 표
    users,
    filteredUsers,
    searchQuery,
    roleFilter,
    statusFilter,
    userDisplayName,
    userInitial,
    savingUsers,
    // 사용자 추가
    showAddModal,
    addPrerequisite,
    openAddModal,
    openManagerRegistration,
    closeAddPrerequisite,
    closeAddModal,
    addLoading,
    addError,
    newUser,
    newUserDepartment,
    newUserRole,
    departmentOptionLabel,
    addTouched,
    addFieldErrors,
    isNewUserValid,
    touchAddField,
    createUser,
    // 정보 수정
    showEditUserModal,
    editUserTarget,
    editUserDraft,
    editTargetIsManager,
    editDepartmentOptions,
    openEditUserModal,
    closeEditUserModal,
    saveEditUserDraft,
    // 운영관리자 변경
    showChangeManagerModal,
    changeManagerTarget,
    changeManagerDraft,
    changeManagerSaving,
    changeManagerError,
    successorOptions,
    openChangeManagerModal,
    closeChangeManagerModal,
    saveChangeManager,
    // 권한 설정
    showPermissionModal,
    permissionTarget,
    permissionTopics,
    permissionDraft,
    permissionLoading,
    blocksAllTopics,
    permissionReadOnly,
    openPermissionModal,
    closePermissionModal,
    savePermissionDraft,
    // 부서 추가·수정
    collectionOptions,
    deactivateTarget,
    confirmDeactivate,
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
  };
};
