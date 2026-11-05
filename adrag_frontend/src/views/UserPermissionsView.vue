<template>
  <div class="admin-layout">
    <AdminSidebar :isOpen="sidebarOpen" activePage="users" :isAdmin="true" :displayName="adminName" @close="sidebarOpen = false" @logout="logout" />

    <main class="admin-main">
      <PageHeader title="사용자 권한 관리" description="사용자 기본정보, 소속 부서, RAG 접근 권한을 관리합니다." @openSidebar="sidebarOpen = true">
        <template #actions>
          <div class="header-actions">
            <button class="btn btn-primary" type="button" @click="openAddModal">
              <i class="fa-solid fa-user-plus"></i>
              사용자 추가
            </button>
            <button class="btn btn-outline" type="button" @click="openDepartmentModal()">
              <i class="fa-solid fa-building"></i>
              부서 추가
            </button>
            <button class="icon-button" type="button" aria-label="새로고침" :disabled="loading" @click="loadAll">
              <i class="fa-solid fa-rotate-right" :class="{ spin: loading }"></i>
            </button>
          </div>
        </template>
      </PageHeader>

      <section class="admin-content">
        <div class="summary" aria-label="사용자 및 부서 요약">
          <article class="summary-card">
            <span>전체 사용자</span>
            <strong>{{ summary.totalUsers.toLocaleString('ko-KR') }}명</strong>
          </article>
          <article class="summary-card success">
            <span>활성 부서</span>
            <strong>{{ summary.activeDepartments.toLocaleString('ko-KR') }}개</strong>
          </article>
          <article class="summary-card warning">
            <span>부서 미지정</span>
            <strong>{{ summary.unassignedUsers.toLocaleString('ko-KR') }}명</strong>
          </article>
        </div>

        <div v-if="loadError" class="notice error">
          <i class="fa-solid fa-circle-exclamation"></i>
          {{ loadError }}
        </div>

        <div class="model-banner">
          <span>🔒</span>
          <div>
            <strong>대화 주제란?</strong> 부서에 허용된 대화 주제 안에서만 AI와 대화하고 문서를 올릴 수 있습니다. 개인 권한에서 체크를 해제하면 해당 사용자에게만 검색과 컬렉션 생성이 차단됩니다.
          </div>
        </div>

        <div class="tabs" role="tablist" aria-label="사용자 권한 관리 탭">
          <button class="tab-btn" type="button" :class="{ active: activeTab === 'users' }" @click="activeTab = 'users'">사용자 관리</button>
          <button class="tab-btn" type="button" :class="{ active: activeTab === 'departments' }" @click="activeTab = 'departments'">부서 관리</button>
        </div>

        <section v-if="activeTab === 'users'" class="card">
          <div class="card-head">
            <div class="card-title">
              <i class="fa-solid fa-user-lock"></i>
              사용자 목록
            </div>
            <div class="filters">
              <input v-model="searchQuery" class="input" type="search" placeholder="이름 또는 아이디 검색" />
              <select v-model="departmentFilter" class="select">
                <option value="">모든 부서</option>
                <option v-for="department in departmentOptions" :key="department" :value="department">{{ department }}</option>
                <option value="__unassigned__">미지정</option>
              </select>
            </div>
          </div>

          <div v-if="filteredUsers.length === 0" class="empty-state">표시할 사용자가 없습니다.</div>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>사용자</th>
                  <th>소속 부서</th>
                  <th>실질 접근 대화 주제 <small>(부서 권한 − 개인 차단)</small></th>
                  <th>상태</th>
                  <th>관리</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in filteredUsers" :key="user.user_id">
                  <td>
                    <div class="user-cell">
                      <div class="avatar">{{ userInitial(user) }}</div>
                      <div>
                        <div class="user-name">{{ userDisplayName(user) }}</div>
                        <div class="user-id">{{ user.user_id }}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span v-if="userDepartment(user)" class="department">
                      <i class="fa-solid fa-building"></i>
                      {{ userDepartment(user) }}
                    </span>
                    <span v-else class="department empty">
                      <i class="fa-solid fa-triangle-exclamation"></i>
                      미지정
                    </span>
                  </td>
                  <td>
                    <div v-if="userCollections(user).length" class="topic-cell">
                      <span v-for="collection in userCollections(user)" :key="collection" class="topic-badge">{{ collection }}</span>
                    </div>
                    <span v-else class="topic-empty">접근 주제 없음</span>
                    <div v-if="userBlockedCount(user)" class="exception-flag">{{ userBlockedCount(user) }}건 개인 차단</div>
                  </td>
                  <td>
                    <span class="status" :class="{ inactive: user._isActive === false }">{{ user._isActive === false ? '비활성' : '활성' }}</span>
                  </td>
                  <td>
                    <div class="row-actions">
                      <button class="table-btn primary" type="button" @click="openEditUserModal(user)">정보 수정</button>
                      <button class="table-btn primary" type="button" @click="openPermissionModal(user)">권한 설정</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-else class="card">
          <div class="card-head">
            <div class="card-title">
              <i class="fa-solid fa-building"></i>
              부서 관리
            </div>
            <div class="filters">
              <input v-model="departmentSearchQuery" class="input" type="search" placeholder="부서명 검색" />
              <!-- <button class="btn btn-primary" type="button" @click="openDepartmentModal()">
                <i class="fa-solid fa-plus"></i>
                부서 추가
              </button> -->
            </div>
          </div>

          <div v-if="filteredDepartments.length === 0" class="empty-state">등록된 부서 정보가 없습니다.</div>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>부서 ID</th>
                  <th>부서명</th>
                  <th>사용자 수</th>
                  <th>기본 접근 주제</th>
                  <th>사용 여부</th>
                  <th>관리</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="department in filteredDepartments" :key="department.name">
                  <td class="security">{{ department.id }}</td>
                  <td>
                    <span class="department">{{ department.name }}</span>
                  </td>
                  <td>{{ department.userCount.toLocaleString('ko-KR') }}명</td>
                  <td>
                    <div v-if="department.categories.length" class="topic-cell">
                      <span v-for="category in department.categoryNames" :key="category" class="topic-badge">{{ category }}</span>
                    </div>
                    <span v-else class="topic-empty">설정된 주제 없음</span>
                  </td>
                  <td>
                    <span class="status" :class="{ inactive: !department.active }">{{ department.active ? '사용' : '미사용' }}</span>
                  </td>
                  <td>
                    <div class="row-actions">
                      <button class="table-btn primary" type="button" @click="openDepartmentModal(department)">수정</button>
                      <button class="table-btn" :class="{ danger: department.active }" type="button" @click="toggleDepartment(department)">{{ department.active ? '비활성화' : '활성화' }}</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="notice">
            <i class="fa-solid fa-circle-info"></i>
            부서와 허용 대화 주제 변경은 즉시 권한 계산에 반영됩니다.
          </div>
        </section>
      </section>
    </main>

    <div v-if="showAddModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="add-user-title">
      <section class="modal">
        <div class="modal-head">
          <div>
            <h2 id="add-user-title">사용자 추가</h2>
            <p>사용자 계정과 소속 부서를 등록합니다.</p>
          </div>
          <button class="close" type="button" aria-label="닫기" @click="closeAddModal">×</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="field">
              <label>아이디 <span class="required">*</span></label>
              <input
                v-model="newUser.user_id"
                type="text"
                placeholder="3~50자"
                :disabled="addLoading"
                :class="{ invalid: addTouched.user_id && addFieldErrors.user_id }"
                @input="touchAddField('user_id')"
                @blur="touchAddField('user_id')"
              />
              <small v-if="addTouched.user_id && addFieldErrors.user_id" class="field-error">{{ addFieldErrors.user_id }}</small>
            </div>
            <div class="field">
              <label>이름</label>
              <input
                v-model="newUser.user_name"
                type="text"
                placeholder="미입력 시 ID 사용"
                :disabled="addLoading"
                :class="{ invalid: addTouched.user_name && addFieldErrors.user_name }"
                @input="touchAddField('user_name')"
                @blur="touchAddField('user_name')"
              />
              <small v-if="addTouched.user_name && addFieldErrors.user_name" class="field-error">{{ addFieldErrors.user_name }}</small>
            </div>
            <div class="field full">
              <label>소속 부서</label>
              <select v-model="newUser.department" :disabled="addLoading">
                <option value="">부서 선택</option>
                <option v-for="department in departmentOptions" :key="department" :value="department">{{ department }}</option>
              </select>
              <small>선택한 부서의 허용 대화 주제가 기본 접근 범위가 됩니다.</small>
            </div>
            <div class="field full">
              <label>비밀번호 <span class="required">*</span></label>
              <input
                v-model="newUser.password"
                type="password"
                placeholder="6자 이상"
                :disabled="addLoading"
                :class="{ invalid: addTouched.password && addFieldErrors.password }"
                @input="touchAddField('password')"
                @blur="touchAddField('password')"
                @keydown.enter.prevent="createUser"
              />
              <small v-if="addTouched.password && addFieldErrors.password" class="field-error">{{ addFieldErrors.password }}</small>
            </div>
          </div>
          <div v-if="addError" class="notice error">{{ addError }}</div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" type="button" :disabled="addLoading" @click="closeAddModal">취소</button>
          <button class="btn btn-primary" type="button" :disabled="addLoading || !isNewUserValid" @click="createUser">
            {{ addLoading ? '추가 중...' : '저장' }}
          </button>
        </div>
      </section>
    </div>

    <div v-if="showPermissionModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="permission-title">
      <section class="modal wide">
        <div class="modal-head">
          <div>
            <h2 id="permission-title">{{ userDisplayName(permissionTarget || {}) }} 권한 설정</h2>
            <p>{{ userDepartment(permissionTarget || {}) || '소속 부서 없음' }}</p>
          </div>
          <button class="close" type="button" aria-label="닫기" @click="closePermissionModal">×</button>
        </div>
        <div class="modal-body">
          <div v-if="!userDepartment(permissionTarget || {})" class="perm-warning">
            <i class="fa-solid fa-triangle-exclamation"></i>
            이 사용자는 소속 부서가 없습니다. 현재는 사용자별 접근 주제만 저장할 수 있습니다.
          </div>

          <div class="perm-summary">
            <i class="fa-solid fa-database"></i>
            전사 등록된 RAG 대화 주제 중 이 사용자가 접근 가능한 항목을 선택합니다.
          </div>

          <div class="perm-section">
            <div class="perm-section-head">접근 가능 대화 주제</div>
            <div v-if="permissionCollectionOptions.length === 0" class="perm-box empty-dept">
              <p class="perm-hint">소속 부서에 허용된 대화 주제가 없습니다. 먼저 부서 관리에서 설정해주세요.</p>
            </div>
            <div v-else class="permission-options">
              <label v-for="collection in permissionCollectionOptions" :key="collection.id" class="permission-option">
                <input v-model="permissionDraft.collections" type="checkbox" :value="collection.id" />
                <span>{{ collection.name }}</span>
              </label>
            </div>
          </div>

          <div class="form-grid compact">
            <div class="field">
              <label>보안등급</label>
              <select v-model="permissionDraft.securityLevel">
                <option value="public">공개</option>
                <option value="internal">부서 내부</option>
                <option value="confidential">대외비</option>
                <option value="restricted">비밀</option>
              </select>
            </div>
            <div class="field">
              <label>문서유형</label>
              <input v-model="permissionDraft.docTypes" type="text" placeholder="예: law,manual" />
            </div>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" type="button" @click="closePermissionModal">취소</button>
          <button class="btn btn-primary" type="button" :disabled="permissionTarget && savingUsers.has(permissionTarget.user_id)" @click="savePermissionDraft">저장</button>
        </div>
      </section>
    </div>

    <div v-if="showEditUserModal" class="modal-backdrop" role="dialog" aria-modal="true">
      <section class="modal">
        <div class="modal-head">
          <div>
            <h2>사용자 정보 수정</h2>
            <p>이름, 소속 부서, 계정 상태를 설정합니다.</p>
          </div>
          <button class="close" type="button" @click="closeEditUserModal">×</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="field"><label>아이디</label><input :value="editUserTarget?.user_id" disabled /></div>
            <div class="field"><label>이름</label><input v-model="editUserDraft.name" /></div>
            <div class="field full">
              <label>소속 부서</label>
              <select v-model="editUserDraft.department">
                <option value="">미지정</option>
                <option v-for="department in departmentOptions" :key="department" :value="department">{{ department }}</option>
              </select>
              <small style="color: #64848b; font-size: 11px; line-height: 1.45; margin-top: 4px"
                >부서를 변경하면 새 부서 대화 주제 기준으로 접근 범위가 즉시 재계산됩니다. 기존 개인 차단 중 새 부서에 없는 항목은 자동 삭제됩니다.</small
              >
            </div>
            <div class="switch-row field full">
              <div class="switch-label">
                <strong>계정 활성화</strong>
                <small>비활성화하면 해당 사용자의 로그인이 차단됩니다.</small>
              </div>
              <button class="switch" type="button" aria-label="계정 활성화" :aria-pressed="editUserDraft.active" @click="editUserDraft.active = !editUserDraft.active"></button>
            </div>
          </div>
          <!-- <div class="notice"><i class="fa-solid fa-circle-info"></i> 부서 변경 시 새 부서에 없는 개인 차단 주제는 자동으로 정리됩니다.</div> -->
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" type="button" @click="closeEditUserModal">취소</button><button class="btn btn-primary" type="button" @click="saveEditUserDraft">저장</button>
        </div>
      </section>
    </div>

    <div v-if="showDepartmentModal" class="modal-backdrop" role="dialog" aria-modal="true">
      <section class="modal wide">
        <div class="modal-head">
          <div>
            <h2>{{ departmentTarget ? '부서 수정' : '부서 추가' }}</h2>
            <p v-if="departmentTarget">허용 대화 주제를 줄이면 해당 대화 주제의 개인 차단이 자동 정리됩니다.</p>
            <p v-else>부서명과 허용 대화 주제를 설정합니다.</p>
          </div>
          <button class="close" type="button" @click="closeDepartmentModal">×</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="field"><label>부서 ID</label><input v-model="departmentDraft.id" disabled /></div>
            <div class="field">
              <label>부서명 <span class="required">*</span></label
              ><input
                v-model="departmentDraft.name"
                placeholder="예: 설비관리팀"
                :disabled="departmentModalLoading || departmentSaving"
                @keyup.enter="handleDepartmentNameEnter"
              />
            </div>
            <div v-if="departmentTarget" class="field full">
              <label>허용 대화 주제 <span class="cat-role-note">검색 + 컬렉션 생성 범위</span></label>
              <p class="permission-grid-label">이 부서 소속 사용자의 검색 및 컬렉션 생성 범위</p>
              <div v-if="departmentModalLoading" class="topic-loading"><i class="fa-solid fa-spinner spin"></i> 대화 주제를 불러오는 중입니다.</div>
              <div v-else-if="collectionOptions.length" class="permission-options">
                <label v-for="collection in collectionOptions" :key="collection.id" class="permission-option"
                  ><input v-model="departmentDraft.categories" type="checkbox" :value="collection.id" :disabled="departmentSaving" /><span>{{ collection.name }}</span></label
                >
              </div>
              <div v-else class="topic-loading">등록된 대화 주제가 없습니다.</div>
              <p class="perm-hint topic-impact">{{ collectionOptions.length }}개 중 {{ departmentDraft.categories.length }}개 주제를 허용합니다.</p>
            </div>
            <label v-if="departmentTarget" class="switch-row field full"
              ><span><strong>부서 사용</strong><small>미사용 처리하면 사용자 배정 목록에서 숨깁니다.</small></span
              ><button
                class="switch"
                type="button"
                aria-label="부서 사용"
                :aria-pressed="departmentDraft.active"
                :disabled="departmentModalLoading || departmentSaving"
                @click.prevent="departmentDraft.active = !departmentDraft.active"
              ></button
            ></label>
          </div>
          <div v-if="departmentModalError" class="notice error"><i class="fa-solid fa-circle-exclamation"></i> {{ departmentModalError }}</div>
          <!-- <div v-if="departmentTarget" class="notice">
            <i class="fa-solid fa-circle-info"></i>
            부서에서 제거한 주제는 소속 사용자의 개인 차단 목록에서도 자동으로 제거됩니다.
          </div> -->
          <div v-if="!departmentTarget" class="form-hint"><small>부서명 중복은 허용되지 않습니다. 소속 사용자가 대화 주제를 생성하면 부서 권한에 자동으로 반영됩니다.</small></div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" type="button" :disabled="departmentSaving" @click="closeDepartmentModal">취소</button
          ><button class="btn btn-primary" type="button" :disabled="departmentModalLoading || departmentSaving || !departmentDraft.name.trim()" @click="saveDepartmentDraft">
            {{ departmentSaving ? '저장 중...' : departmentTarget ? '저장' : '추가' }}
          </button>
        </div>
      </section>
    </div>

    <AppToast :message="toast.visible ? toast.message : ''" :type="toast.type" admin-position @close="toast.visible = false" />
  </div>
</template>

<script>
import { useRouter } from 'vue-router';
import AdminSidebar from '../components/AdminSidebar.vue';
import AppToast from '../components/AppToast.vue';
import PageHeader from '../components/PageHeader.vue';
import { useUserPermissions } from '../composables/useUserPermissions';

export default {
  components: { AdminSidebar, AppToast, PageHeader },
  setup() {
    const router = useRouter();
    return useUserPermissions({ router });
  },
};
</script>

<style scoped>
* {
  box-sizing: border-box;
}

.admin-layout {
  display: flex;
  height: 100dvh;
  overflow: hidden;
  background: #f1f5f9;
  color: #0f172a;
  font-family: Inter, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
}

.admin-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.header-actions,
.filters,
.row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.admin-content {
  flex: 1;
  padding: 24px 32px 40px;
  overflow-y: auto;
}

.summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}

.summary-card {
  padding: 17px 18px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.summary-card span {
  color: #64748b;
  font-size: 12px;
}

.summary-card strong {
  display: block;
  margin-top: 7px;
  font-size: 22px;
}

.summary-card.success strong {
  color: #15803d;
}

.summary-card.warning strong {
  color: #d97706;
}

.model-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 20px;
  padding: 13px 16px;
  border: 1px solid #c7d2fe;
  border-radius: 8px;
  color: #3730a3;
  background: #eef2ff;
  font-size: 13px;
  line-height: 1.6;
}

.model-banner strong {
  display: block;
}

.tabs {
  display: inline-flex;
  gap: 6px;
  padding: 5px;
  margin-bottom: 18px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
}

.tab-btn {
  min-width: 120px;
  padding: 9px 14px;
  border: 0;
  border-radius: 8px;
  color: #64748b;
  background: transparent;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
}

.tab-btn.active {
  color: #1d4ed8;
  background: #eff6ff;
}

.card {
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border-bottom: 1px solid #e2e8f0;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
}

.input,
.select,
.field input,
.field select {
  height: 38px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #334155;
  background: #fff;
  outline: none;
}

.input {
  width: 220px;
  padding: 0 12px;
}

.select {
  min-width: 150px;
  padding: 0 32px 0 11px;
}

.input:focus,
.select:focus,
.field input:focus,
.field select:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 970px;
  border-collapse: collapse;
}

th,
td {
  padding: 14px 16px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
  vertical-align: middle;
  font-size: 13px;
}

th {
  color: #475569;
  background: #f8fafc;
  font-weight: 600;
}

th small {
  display: block;
  margin-top: 3px;
  color: #94a3b8;
  font-weight: 400;
}

tbody tr:hover {
  background: #f8fafc;
}

tbody tr:last-child td {
  border-bottom: 0;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 11px;
}

.avatar {
  display: grid;
  flex: 0 0 36px;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 50%;
  color: #1d4ed8;
  background: #dbeafe;
  font-weight: 700;
}

.user-name {
  font-weight: 700;
}

.user-id {
  margin-top: 3px;
  color: #94a3b8;
  font-size: 12px;
}

.department {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  border-radius: 999px;
  color: #1e40af;
  background: #eff6ff;
  font-weight: 600;
  font-size: 12px;
}

.department.empty {
  color: #92400e;
  background: #fffbeb;
}

.topic-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  max-width: 320px;
}

.topic-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 999px;
  color: #475569;
  background: #f1f5f9;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.topic-empty,
.empty-state {
  color: #94a3b8;
  font-size: 13px;
}

.exception-flag {
  margin-top: 6px;
  color: #dc2626;
  font-size: 11px;
  font-weight: 600;
}

.empty-state {
  padding: 34px 20px;
  text-align: center;
}

.security {
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 12px;
}

.status::before {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
  content: '';
}

.status.inactive {
  color: #94a3b8;
}

.status.inactive::before {
  background: #94a3b8;
}

.btn,
.icon-button,
.table-btn {
  border: 0;
  cursor: pointer;
  font: inherit;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 38px;
  padding: 8px 13px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 13px;
}

.btn-primary {
  color: #fff;
  background: #2563eb;
}

.btn-secondary {
  color: #334155;
  background: #f1f5f9;
}

.btn-outline {
  border: 1px solid #cbd5e1;
  color: #334155;
  background: #fff;
}

.table-btn.danger {
  color: #dc2626;
}

.switch-row.field {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 13px;
}

.switch-row.field > :first-child {
  min-width: 0;
  text-align: left;
}

.switch-row span,
.switch-row small {
  display: block;
}

.switch-label strong {
  display: block;
  margin-bottom: 3px;
  font-size: 13px;
}

.switch-label small {
  color: #64748b;
  font-size: 11px;
}

.switch {
  position: relative;
  flex: 0 0 auto;
  width: 40px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: #2563eb;
  cursor: pointer;
}

.switch::after {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: right 0.15s ease;
  content: '';
}

.switch[aria-pressed='false'] {
  background: #cbd5e1;
}

.switch[aria-pressed='false']::after {
  right: 21px;
}

.switch:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 2px;
}

.switch-row input[type='checkbox'] {
  width: 18px;
  height: 18px;
}

.icon-button {
  display: inline-grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #64748b;
  background: #fff;
}

.table-btn {
  padding: 7px 9px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  color: #334155;
  background: #fff;
  font-size: 12px;
}

.table-btn.primary {
  border-color: #bfdbfe;
  color: #1d4ed8;
  background: #eff6ff;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.notice {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  color: #1e40af;
  background: #eff6ff;
  font-size: 12px;
  line-height: 1.55;
}

.notice.error {
  margin: 0 0 14px;
  border-color: #fecaca;
  color: #b91c1c;
  background: #fff1f2;
}

.form-hint {
  margin-top: 12px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.45;
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(2px);
}

.modal {
  width: min(500px, 100%);
  overflow: hidden;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.24);
}

.modal.wide {
  width: min(500px, 100%);
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 21px 22px 15px;
  border-bottom: 1px solid #e2e8f0;
}

.modal-head h2 {
  margin: 0 0 5px;
  font-size: 18px;
}

.modal-head p {
  margin: 0;
  color: #64748b;
  font-size: 12px;
}

.close {
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  color: #64748b;
  background: #f1f5f9;
  font-size: 18px;
  cursor: pointer;
}

.modal-body {
  padding: 20px 22px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 15px 12px;
}

.form-grid.compact {
  margin-top: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.field.full {
  grid-column: 1 / -1;
}

.field label {
  color: #334155;
  font-size: 12px;
  font-weight: 700;
}

.field input,
.field select {
  width: 100%;
  padding: 0 11px;
}

.field input.invalid {
  border-color: #ef4444;
  background: #fff7f7;
}

.required,
.field-error {
  color: #dc2626;
}

.field-error {
  font-size: 11px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 15px 22px 20px;
  border-top: 1px solid #e2e8f0;
}

.perm-summary,
.perm-warning {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 11px 13px;
  margin-bottom: 16px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
}

.perm-summary {
  color: #475569;
  background: #f8fafc;
}

.perm-warning {
  border: 1px solid #fde68a;
  color: #92400e;
  background: #fffbeb;
}

.perm-section-head {
  margin-bottom: 9px;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

.permission-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.permission-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  color: #334155;
  background: #fff;
  font-size: 12.5px;
}

.permission-option input {
  flex: 0 0 auto;
  width: 15px;
  height: 15px;
  accent-color: #2563eb;
}

.perm-box {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 13px;
  background: #fff;
}

.perm-box.empty-dept {
  background: #f8fafc;
}

.perm-hint {
  margin: 0;
  color: #94a3b8;
  font-size: 11px;
}

.cat-role-note {
  display: inline-flex;
  align-items: center;
  margin-left: 6px;
  padding: 2px 8px;
  border-radius: 4px;
  color: #15803d;
  background: #f0fdf4;
  font-size: 10.5px;
  font-weight: 600;
}

.permission-grid-label {
  margin: 0;
  color: #64748b;
  font-size: 11.5px;
}

.topic-loading {
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  color: #64748b;
  background: #f8fafc;
  font-size: 12px;
  text-align: center;
}

.topic-impact {
  margin-top: 2px;
}

.switch:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.mobile-only {
  display: none;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 900px) {
  .summary {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .card-head {
    align-items: stretch;
    flex-direction: column;
  }

  .admin-content {
    padding-right: 18px;
    padding-left: 18px;
  }

  .header-actions,
  .filters {
    flex-wrap: wrap;
  }

  .input,
  .select {
    width: 100%;
  }

  .tabs {
    width: 100%;
  }

  .tab-btn {
    flex: 1;
    min-width: 0;
  }

  .form-grid,
  .permission-options {
    grid-template-columns: 1fr;
  }

  .field.full {
    grid-column: auto;
  }

  .mobile-only {
    display: inline-grid;
  }
}

/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
.modal {
  display: flex;
  flex-direction: column;
  max-height: calc(100dvh - 32px);
}

.modal-head,
.modal-actions {
  flex-shrink: 0;
}

.modal-body {
  min-height: 0;
  overflow-y: auto;
}

@media (max-width: 768px) {
  .admin-layout :deep(.page-header) {
    flex-wrap: wrap;
  }

  .header-actions {
    width: 100%;
  }

  .admin-content {
    padding: 16px 16px 32px;
  }

  .modal-backdrop {
    padding: 16px;
  }

  .modal-head,
  .modal-body {
    padding-right: 16px;
    padding-left: 16px;
  }

  .modal-actions {
    padding: 12px 16px 16px;
  }

  .close {
    width: 40px;
    height: 40px;
  }

  .btn,
  .icon-button,
  .table-btn,
  .tab-btn {
    min-height: 40px;
  }

  .icon-button {
    width: 40px;
  }

  .input,
  .select {
    height: 40px;
  }
}
</style>
