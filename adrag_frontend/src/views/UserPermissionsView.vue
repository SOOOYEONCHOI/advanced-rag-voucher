<template>
  <!-- 2026.11.20(woojin.jung) 수정 - 부서 운영관리자 역할 + 부서 패널(왼쪽 부서 목록 · 부서 요약 · 부서 사용자 표)
       관리자(/admin/users)와 부서 운영관리자(/admin/members, 자기 부서 고정)가 같은 화면을 쓴다 -->
  <div class="admin-layout">
    <AdminSidebar :isOpen="sidebarOpen" :activePage="isAdminMode ? 'users' : 'members'" :isAdmin="isAdminMode" :displayName="adminName" @close="sidebarOpen = false" @logout="logout" />

    <main class="admin-main">
      <PageHeader
        :title="isAdminMode ? '사용자 권한 관리' : '부서 사용자 권한'"
        :description="isAdminMode ? '부서를 고르면 그 부서의 운영관리자 · 허용 주제 · 사용자를 함께 봅니다.' : `${selectedDepartment?.name || '소속 부서'} 사용자의 대화 주제 접근 권한을 관리합니다.`"
        @openSidebar="sidebarOpen = true"
      >
        <template #actions>
          <!-- 2026.11.23(woojin.jung) 수정 - 휴대폰 너비에서 버튼 줄을 따로 두는 건 [사용자 추가]가 있는 관리자 화면만(운영관리자는 새로고침만 제목 옆에) -->
          <div class="header-actions" :class="{ 'header-actions-full': isAdminMode }">
            <button v-if="isAdminMode" class="btn btn-primary" type="button" @click="openAddModal()">
              <i class="fa-solid fa-user-plus"></i>
              사용자 추가
            </button>
            <button class="icon-button" type="button" aria-label="새로고침" :disabled="loading" @click="loadAll">
              <i class="fa-solid fa-rotate-right" :class="{ spin: loading }"></i>
            </button>
          </div>
        </template>
      </PageHeader>

      <section class="admin-content">
        <!-- 2026.11.23(woojin.jung) 추가 - 비활성 부서의 운영관리자: 읽기 전용 안내(관리자 화면에는 표시되지 않음) -->
        <DepartmentReadOnlyNotice v-if="!isAdminMode" />
        <div v-if="loadError" class="notice error">
          <i class="fa-solid fa-circle-exclamation"></i>
          {{ loadError }}
        </div>

        <div class="model-banner">
          <span>🔒</span>
          <div v-if="isAdminMode">
            <strong>등록 순서</strong> 부서 등록 → <b>부서 운영관리자 1명</b> 등록 → 일반 사용자 등록. 부서에 허용된 대화 주제 안에서 개인 권한의 체크를 해제하면 해당 사용자에게만 검색이 차단됩니다.
            개인 권한은 각 부서 운영관리자도 설정할 수 있습니다.
          </div>
          <div v-else>
            <strong>부서 사용자 권한이란?</strong> {{ selectedDepartment?.name || '소속 부서' }}에 허용된 대화 주제 안에서 사용자별로 접근을 막을 수 있습니다. 사용자 추가·정보 수정과 부서 허용 주제
            변경은 관리자에게 요청하세요.
          </div>
        </div>

        <select v-if="isAdminMode" class="select dept-select-mobile" :value="selectedDepartmentId" aria-label="부서 선택" @change="selectDepartment($event.target.value)">
          <option value="">전체 ({{ users.length }})</option>
          <option v-for="department in departments" :key="department.id" :value="department.id">
            {{ department.name }} ({{ department.userCount }}){{ department.active && !department.manager ? ' ⚠' : '' }}
          </option>
        </select>

        <div :class="{ 'dept-layout': isAdminMode }">
          <!-- 왼쪽 부서 목록 (관리자) -->
          <aside v-if="isAdminMode" class="dept-panel" aria-label="부서 목록">
            <div class="dept-panel-head">
              <div class="dept-panel-title">
                부서
                <button type="button" @click="openDepartmentModal()"><i class="fa-solid fa-plus"></i> 부서 추가</button>
              </div>
              <!-- 2026.11.23(woojin.jung) 수정 - 검색칸에 돋보기 아이콘 -->
              <div class="dept-search">
                <i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i>
                <input v-model="departmentSearchQuery" class="input" type="search" placeholder="부서 검색" aria-label="부서 검색" />
              </div>
            </div>
            <ul class="dept-list">
              <li>
                <button class="dept-item" :class="{ active: !selectedDepartmentId }" type="button" @click="selectDepartment('')">
                  <i class="fa-solid fa-layer-group"></i>
                  <span class="dept-name">전체</span>
                  <span class="dept-count">{{ users.length }}</span>
                </button>
              </li>
              <li class="dept-divider" role="separator"></li>
              <li v-for="department in panelDepartments" :key="department.id">
                <button class="dept-item" :class="{ active: selectedDepartmentId === department.id, inactive: !department.active }" type="button" @click="selectDepartment(department.id)">
                  <i class="fa-solid fa-building"></i>
                  <span class="dept-name">{{ department.name }}</span>
                  <i v-if="department.active && !department.manager" class="fa-solid fa-triangle-exclamation dept-warn" title="운영관리자 미지정" aria-label="운영관리자 미지정"></i>
                  <span class="dept-count">{{ department.userCount }}</span>
                </button>
              </li>
              <li v-if="panelDepartments.length === 0" class="dept-empty">{{ departments.length ? '검색 결과가 없습니다.' : '등록된 부서가 없습니다.' }}</li>
            </ul>
          </aside>

          <section class="card">
            <!-- 전체 요약 -->
            <div v-if="isAdminMode && !selectedDepartmentId" class="dept-head">
              <div class="dept-head-top">
                <h3><i class="fa-solid fa-layer-group"></i> 전체 부서</h3>
              </div>
              <div class="dept-facts">
                <div class="dept-fact">
                  <span>전체 사용자</span><strong>{{ summary.totalUsers.toLocaleString('ko-KR') }}명</strong> · 활성 {{ summary.activeUsers.toLocaleString('ko-KR') }}
                </div>
                <div class="dept-fact">
                  <span>활성 부서</span><strong>{{ summary.activeDepartments }}개</strong> · 운영관리자 등록 {{ summary.managedDepartments }}개
                </div>
                <div class="dept-fact" :class="{ warn: noManagerDepartments.length }">
                  <span>운영관리자 미지정 부서</span>
                  <strong>{{ noManagerDepartments.length }}개</strong>
                  <template v-if="noManagerDepartments.length">
                    ·
                    <template v-for="(department, index) in noManagerDepartments" :key="department.id">
                      <button class="link-btn" type="button" @click="selectDepartment(department.id)">{{ department.name }}</button>{{ index < noManagerDepartments.length - 1 ? ', ' : '' }}
                    </template>
                    <br /><small>일반 사용자 등록 불가</small>
                  </template>
                </div>
              </div>
            </div>

            <!-- 부서 요약 -->
            <div v-else-if="selectedDepartment" class="dept-head">
              <div class="dept-head-top">
                <h3>
                  <i class="fa-solid fa-building"></i> {{ selectedDepartment.name }} <small>{{ selectedDepartment.id }}</small>
                  <span v-if="!selectedDepartment.active" class="status inactive">미사용</span>
                </h3>
                <div v-if="isAdminMode" class="dept-head-actions">
                  <!-- 2026.11.23(woojin.jung) 수정 - [사용자 추가]는 페이지 상단 버튼 하나로 통일(선택한 부서가 미리 선택되어 열림) -->
                  <button v-if="selectedDepartment.manager" class="btn btn-outline btn-sm" type="button" @click="openChangeManagerModal(selectedDepartment)">
                    <i class="fa-solid fa-user-gear"></i> 운영관리자 변경
                  </button>
                  <button v-else class="btn btn-primary btn-sm" type="button" :disabled="!selectedDepartment.active" @click="openManagerRegistration(selectedDepartment.id)">
                    <i class="fa-solid fa-user-gear"></i> 운영관리자 등록
                  </button>
                  <button class="btn btn-outline btn-sm" type="button" @click="openDepartmentModal(selectedDepartment)"><i class="fa-solid fa-pen"></i> 부서 수정</button>
                  <button class="table-btn" :class="{ danger: selectedDepartment.active }" type="button" @click="toggleDepartment(selectedDepartment)">
                    {{ selectedDepartment.active ? '비활성화' : '활성화' }}
                  </button>
                </div>
              </div>
              <!-- 2026.11.23(woojin.jung) 수정 - 운영관리자 화면에서는 운영관리자 = 본인이라 운영관리자 칸을 숨긴다 -->
              <div class="dept-facts" :class="{ 'two-col': !isAdminMode }">
                <div v-if="isAdminMode && selectedDepartment.manager" class="dept-fact">
                  <span>운영관리자 (부서당 1명)</span>
                  <strong>{{ selectedDepartment.manager.name }}</strong>
                  <template v-if="selectedDepartment.manager.id !== selectedDepartment.manager.name"> · {{ selectedDepartment.manager.id }}</template>
                </div>
                <div v-else-if="isAdminMode" class="dept-fact warn">
                  <span>운영관리자</span>
                  <strong><i class="fa-solid fa-triangle-exclamation"></i> 미지정</strong>
                  <template v-if="isAdminMode && selectedDepartment.active">
                    · <button class="link-btn" type="button" @click="openManagerRegistration(selectedDepartment.id)">운영관리자 등록</button>
                  </template>
                  <br /><small>일반 사용자 등록 불가</small>
                </div>
                <div class="dept-fact">
                  <span>허용 대화 주제</span>
                  <div v-if="selectedDepartment.categories.length" class="topic-cell">
                    <span v-for="topic in selectedDepartment.categories" :key="topic" class="topic-badge">{{ topic }}</span>
                  </div>
                  <strong v-else class="fact-empty">설정된 주제 없음</strong>
                </div>
                <div class="dept-fact">
                  <span>{{ isAdminMode ? '인원' : '일반 사용자' }}</span>
                  <strong>{{ selectedDepartment.userCount }}명</strong> · 활성 {{ selectedDepartment.activeUserCount }} · 개인 차단
                  {{ selectedDepartment.blockedUserCount }}
                </div>
              </div>
            </div>

            <!-- 사용자 표 -->
            <div class="card-head">
              <div class="card-title">
                <i class="fa-solid" :class="isAdminMode ? 'fa-user-lock' : 'fa-users-gear'"></i>
                {{ isAdminMode ? (selectedDepartmentId ? '부서 사용자' : '전체 사용자') : `${selectedDepartment?.name || ''} 일반 사용자` }}
              </div>
              <div class="filters">
                <input v-model="searchQuery" class="input" type="search" placeholder="이름 또는 아이디 검색" />
                <select v-if="isAdminMode" v-model="roleFilter" class="select" aria-label="역할">
                  <option value="">모든 역할</option>
                  <option value="manager">부서 운영관리자</option>
                  <option value="user">일반 사용자</option>
                </select>
                <select v-model="statusFilter" class="select" aria-label="상태">
                  <option value="">모든 상태</option>
                  <option value="active">활성</option>
                  <option value="inactive">비활성</option>
                  <option value="blocked">개인 차단 있음</option>
                </select>
              </div>
            </div>

            <div v-if="isAdminMode && selectedDepartment && !selectedDepartment.manager && selectedDepartment.userCount === 0" class="empty-steps">
              <i class="fa-solid fa-user-gear empty-steps-icon"></i>
              <strong>아직 이 부서에 사용자가 없습니다</strong>
              <ol class="step-list">
                <li class="done">
                  <span class="step-no"><i class="fa-solid fa-check"></i></span>부서 등록
                </li>
                <li class="current"><span class="step-no">2</span>부서 운영관리자 등록 (부서당 1명) <em>현재 단계</em></li>
                <li><span class="step-no">3</span>일반 사용자 등록</li>
              </ol>
              <div>
                <button class="btn btn-primary" type="button" :disabled="!selectedDepartment.active" @click="openManagerRegistration(selectedDepartment.id)">
                  <i class="fa-solid fa-user-gear"></i> 운영관리자 등록
                </button>
              </div>
            </div>
            <div v-else-if="filteredUsers.length === 0" class="empty-state">표시할 사용자가 없습니다.</div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>사용자</th>
                    <th v-if="isAdminMode && !selectedDepartmentId">소속 부서</th>
                    <th v-if="isAdminMode">역할</th>
                    <th>실질 접근 대화 주제 <small>(부서 권한 − 개인 차단)</small></th>
                    <th>상태</th>
                    <th>관리</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="user in filteredUsers" :key="user.user_id" :class="{ 'row-pinned': user.role === 'manager' }">
                    <td>
                      <div class="user-cell">
                        <div class="avatar">{{ userInitial(user) }}</div>
                        <div>
                          <div class="user-name">{{ userDisplayName(user) }}</div>
                          <div v-if="user.user_id !== userDisplayName(user)" class="user-id">{{ user.user_id }}</div>
                        </div>
                      </div>
                    </td>
                    <!-- 2026.11.23(woojin.jung) 추가 - data-label: 휴대폰 너비에서 행을 카드로 쌓을 때 항목 이름 -->
                    <td v-if="isAdminMode && !selectedDepartmentId" data-label="소속 부서">
                      <span v-if="user.departmentName" class="department"><i class="fa-solid fa-building"></i> {{ user.departmentName }}</span>
                      <span v-else class="department empty"><i class="fa-solid fa-triangle-exclamation"></i> 미지정</span>
                    </td>
                    <td v-if="isAdminMode" data-label="역할">
                      <span v-if="user.role === 'manager'" class="role-badge manager"><i class="fa-solid fa-user-gear"></i> 부서 운영관리자</span>
                      <span v-else class="role-badge user">일반 사용자</span>
                    </td>
                    <td data-label="접근 대화 주제">
                      <div v-if="user.effectiveTopics.length" class="topic-cell">
                        <span v-for="topic in user.effectiveTopics" :key="topic" class="topic-badge">{{ topic }}</span>
                      </div>
                      <span v-else class="topic-empty">접근 주제 없음</span>
                      <div v-if="user.blockedCount" class="exception-flag">{{ user.blockedCount }}건 개인 차단</div>
                    </td>
                    <td data-label="상태">
                      <span class="status" :class="{ inactive: !user.isActive }">{{ user.isActive ? '활성' : '비활성' }}</span>
                    </td>
                    <td class="td-actions">
                      <div class="row-actions">
                        <button v-if="isAdminMode" class="table-btn primary" type="button" @click="openEditUserModal(user)">정보 수정</button>
                        <!-- 2026.11.23(woojin.jung) 수정 - 운영관리자는 부서 주제 전체를 관리하므로 개인 권한 설정 대상이 아니다 -->
                        <button v-if="user.role !== 'manager'" class="table-btn primary" type="button" @click="openPermissionModal(user)">
                          {{ permissionReadOnly ? '권한 보기' : '권한 설정' }}
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </section>
    </main>

    <!-- 선등록 안내: 활성 부서 없음 / 운영관리자가 있는 부서 없음 -->
    <div v-if="addPrerequisite" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="add-user-prerequisite-title">
      <section class="modal prerequisite-modal">
        <div class="modal-head">
          <div>
            <h2 id="add-user-prerequisite-title">{{ addPrerequisite === 'department' ? '먼저 부서를 등록해주세요' : '먼저 부서 운영관리자를 등록해주세요' }}</h2>
            <p>
              {{ addPrerequisite === 'department' ? '사용자를 추가하려면 소속으로 지정할 활성 부서가 필요합니다.' : '일반 사용자는 운영관리자가 등록된 부서에만 추가할 수 있습니다.' }}
            </p>
          </div>
          <button class="close" type="button" aria-label="닫기" @click="closeAddPrerequisite">×</button>
        </div>
        <div class="modal-body">
          <div class="prerequisite-message">
            <span class="prerequisite-icon">
              <i class="fa-solid" :class="addPrerequisite === 'department' ? 'fa-building-circle-exclamation' : 'fa-user-gear'"></i>
            </span>
            <div>
              <strong>{{ addPrerequisite === 'department' ? '등록된 활성 부서가 없습니다.' : '운영관리자가 등록된 부서가 없습니다.' }}</strong>
              <ol class="step-list">
                <li :class="addPrerequisite === 'department' ? 'current' : 'done'">
                  <span class="step-no"><i v-if="addPrerequisite !== 'department'" class="fa-solid fa-check"></i><template v-else>1</template></span>
                  부서 등록 <em v-if="addPrerequisite === 'department'">현재 단계</em>
                </li>
                <li :class="{ current: addPrerequisite === 'manager' }"><span class="step-no">2</span>부서 운영관리자 등록 (부서당 1명) <em v-if="addPrerequisite === 'manager'">현재 단계</em></li>
                <li><span class="step-no">3</span>일반 사용자 등록</li>
              </ol>
            </div>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" type="button" @click="closeAddPrerequisite">취소</button>
          <button v-if="addPrerequisite === 'department'" class="btn btn-primary" type="button" @click="openDepartmentModal(null, true)">
            <i class="fa-solid fa-building"></i>
            부서 등록하기
          </button>
          <button v-else class="btn btn-primary" type="button" @click="openManagerRegistration()">
            <i class="fa-solid fa-user-gear"></i>
            운영관리자 등록하기
          </button>
        </div>
      </section>
    </div>

    <!-- 사용자 추가: 부서를 고르면 역할이 정해진다(운영관리자 없음 → 운영관리자, 있음 → 일반 사용자) -->
    <div v-if="showAddModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="add-user-title">
      <section class="modal">
        <div class="modal-head">
          <div>
            <h2 id="add-user-title">사용자 추가</h2>
            <p>소속 부서를 먼저 선택하면 등록할 수 있는 역할이 정해집니다.</p>
          </div>
          <button class="close" type="button" aria-label="닫기" @click="closeAddModal">×</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="field full">
              <label>소속 부서 <span class="required">*</span></label>
              <select v-model="newUser.departmentId" :disabled="addLoading">
                <option v-for="department in activeDepartments" :key="department.id" :value="department.id">{{ departmentOptionLabel(department) }}</option>
              </select>
              <span v-if="newUserDepartment && !newUserDepartment.manager" class="dept-option-hint warn">
                <i class="fa-solid fa-triangle-exclamation"></i> 이 부서에는 아직 운영관리자가 없습니다.
              </span>
              <span v-else-if="newUserDepartment" class="dept-option-hint ok">
                <i class="fa-solid fa-circle-check"></i> 운영관리자 {{ newUserDepartment.manager.name }} ({{ newUserDepartment.manager.id }})
              </span>
            </div>
            <div class="field full">
              <label>역할 <span class="required">*</span></label>
              <div class="role-choice">
                <div class="role-choice-item" :class="newUserRole === 'manager' ? 'selected' : 'locked'">
                  <i class="fa-solid" :class="newUserRole === 'manager' ? 'fa-user-gear' : 'fa-lock'"></i>
                  <div>
                    <strong>부서 운영관리자</strong>
                    <small>{{
                      newUserRole === 'manager' ? '문서·대화 주제·시작 화면 질문 관리, 부서 사용자 주제 권한 관리' : '이미 등록되어 있습니다. 교체는 부서 화면의 [운영관리자 변경]에서 합니다.'
                    }}</small>
                  </div>
                </div>
                <div class="role-choice-item" :class="newUserRole === 'user' ? 'selected' : 'locked'">
                  <i class="fa-solid" :class="newUserRole === 'user' ? 'fa-user' : 'fa-lock'"></i>
                  <div>
                    <strong>일반 사용자</strong>
                    <small>{{ newUserRole === 'user' ? '챗봇 대화와 내 활동 현황만 사용합니다.' : '운영관리자를 먼저 등록해야 선택할 수 있습니다.' }}</small>
                  </div>
                </div>
              </div>
              <small class="field-note">선택한 부서의 허용 대화 주제가 기본 접근 범위가 됩니다.</small>
            </div>
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
              <label>비밀번호 <span class="required">*</span></label>
              <input
                v-model="newUser.password"
                type="password"
                placeholder="영문·숫자 포함 8자 이상"
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

    <!-- 권한 설정 (관리자·운영관리자 공용) -->
    <div v-if="showPermissionModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="permission-title">
      <section class="modal wide">
        <div class="modal-head">
          <div>
            <h2 id="permission-title">{{ userDisplayName(permissionTarget) }} {{ permissionReadOnly ? '권한 보기' : '권한 설정' }}</h2>
            <p>{{ permissionTarget?.departmentName || selectedDepartment?.name || '소속 부서 없음' }}</p>
          </div>
          <button class="close" type="button" aria-label="닫기" @click="closePermissionModal">×</button>
        </div>
        <div class="modal-body">
          <div class="perm-summary">
            <i class="fa-solid fa-database"></i>
            {{ permissionTarget?.departmentName || selectedDepartment?.name || '소속 부서' }}에 허용된 대화 주제 중 이 사용자가 접근 가능한 항목을 선택합니다.
          </div>
          <!-- 2026.11.23(woojin.jung) 추가 - 권한은 차단 목록으로 저장되므로 새 주제는 기본 허용된다 -->
          <p v-if="!permissionReadOnly" class="field-note">체크를 해제한 주제만 차단됩니다. 앞으로 부서에 새로 추가되는 대화 주제는 이 사용자에게도 기본으로 허용됩니다.</p>
          <div class="perm-section">
            <div class="perm-section-head">접근 가능 대화 주제</div>
            <div v-if="permissionLoading" class="topic-loading"><i class="fa-solid fa-spinner spin"></i> 권한을 불러오는 중입니다.</div>
            <div v-else-if="permissionTopics.length === 0" class="perm-box empty-dept">
              <p class="perm-hint">소속 부서에 허용된 대화 주제가 없습니다.{{ isAdminMode ? ' 먼저 부서 수정에서 설정해주세요.' : ' 관리자에게 요청하세요.' }}</p>
            </div>
            <div v-else class="permission-options">
              <label v-for="topic in permissionTopics" :key="topic" class="permission-option">
                <input v-model="permissionDraft" type="checkbox" :value="topic" :disabled="permissionReadOnly" />
                <span>{{ topic }}</span>
              </label>
            </div>
          </div>
          <!-- 2026.11.23(woojin.jung) 추가 - 모든 주제 차단 시 경고(저장 버튼 문구로 한 번 더 확인) -->
          <div v-if="blocksAllTopics && !permissionReadOnly" class="notice error">
            <i class="fa-solid fa-triangle-exclamation"></i>
            모든 대화 주제가 차단되어 이 사용자는 챗봇에서 질문할 수 있는 주제가 없게 됩니다.
          </div>
        </div>
        <div class="modal-actions">
          <!-- 2026.11.23(woojin.jung) 수정 - 비활성 부서(운영관리자)는 조회만: 저장 버튼 숨김 -->
          <button class="btn btn-secondary" type="button" @click="closePermissionModal">{{ permissionReadOnly ? '닫기' : '취소' }}</button>
          <button
            v-if="!permissionReadOnly"
            class="btn"
            :class="blocksAllTopics ? 'btn-danger' : 'btn-primary'"
            type="button"
            :disabled="permissionLoading || (permissionTarget && savingUsers.has(permissionTarget.user_id))"
            @click="savePermissionDraft"
          >
            {{ blocksAllTopics ? '전체 차단하고 저장' : '저장' }}
          </button>
        </div>
      </section>
    </div>

    <!-- 정보 수정 (관리자) -->
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
              <label>역할</label>
              <div class="readonly-field">
                <span v-if="editTargetIsManager" class="role-badge manager"><i class="fa-solid fa-user-gear"></i> 부서 운영관리자</span>
                <span v-else class="role-badge user">일반 사용자</span>
                <span class="readonly-sub">· {{ editUserTarget?.departmentName || '부서 미지정' }}</span>
              </div>
            </div>
            <div class="field full">
              <label>소속 부서</label>
              <select v-model="editUserDraft.departmentId" :disabled="editTargetIsManager">
                <option v-if="!editUserDraft.departmentId" value="">미지정</option>
                <option v-for="department in editDepartmentOptions" :key="department.id" :value="department.id">{{ department.name }}</option>
              </select>
              <small class="field-note">
                {{
                  editTargetIsManager
                    ? '운영관리자는 부서를 옮기거나 비활성화할 수 없습니다. 먼저 부서 화면의 [운영관리자 변경]으로 후임을 지정하세요.'
                    : '운영관리자가 등록된 부서로만 옮길 수 있습니다. 기존 개인 차단 중 새 부서에 없는 항목은 자동 삭제됩니다.'
                }}
              </small>
            </div>
            <div class="switch-row field full">
              <div class="switch-label">
                <strong>계정 활성화</strong>
                <small>{{ editTargetIsManager ? '운영관리자 계정은 변경 후에 비활성화할 수 있습니다.' : '비활성화하면 해당 사용자의 로그인이 차단됩니다.' }}</small>
              </div>
              <button
                class="switch"
                type="button"
                aria-label="계정 활성화"
                :aria-pressed="editUserDraft.active"
                :disabled="editTargetIsManager"
                @click="editUserDraft.active = !editUserDraft.active"
              ></button>
            </div>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" type="button" @click="closeEditUserModal">취소</button><button class="btn btn-primary" type="button" @click="saveEditUserDraft">저장</button>
        </div>
      </section>
    </div>

    <!-- 운영관리자 변경 (관리자): 후임 지정과 기존 처리를 한 번에 -->
    <div v-if="showChangeManagerModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="change-manager-title">
      <section class="modal wide">
        <div class="modal-head">
          <div>
            <h2 id="change-manager-title">{{ changeManagerTarget?.name }} 운영관리자 변경</h2>
            <p>부서당 운영관리자는 1명입니다. 후임을 지정하면 기존 운영관리자는 함께 변경됩니다.</p>
          </div>
          <button class="close" type="button" aria-label="닫기" @click="closeChangeManagerModal">×</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="field full">
              <label>현재 운영관리자</label>
              <div class="readonly-field">
                <div class="avatar">{{ (changeManagerTarget?.manager?.name || '?').slice(0, 1) }}</div>
                <div>
                  <div class="user-name">{{ changeManagerTarget?.manager?.name }}</div>
                  <div class="user-id">{{ changeManagerTarget?.manager?.id }}</div>
                </div>
              </div>
            </div>
            <div class="field full">
              <label>새 운영관리자 <span class="required">*</span></label>
              <select v-model="changeManagerDraft.newManagerId" :disabled="changeManagerSaving || successorOptions.length === 0">
                <option v-if="successorOptions.length === 0" value="">선택할 수 있는 사용자가 없습니다</option>
                <option v-for="user in successorOptions" :key="user.user_id" :value="user.user_id">{{ userDisplayName(user) }} ({{ user.user_id }})</option>
              </select>
              <small class="field-note">같은 부서의 활성 일반 사용자 중에서 선택합니다. 새 계정이 필요하면 먼저 일반 사용자로 추가한 뒤 지정하세요.</small>
            </div>
            <div class="field full">
              <label>기존 운영관리자({{ changeManagerTarget?.manager?.name }}) 처리 <span class="required">*</span></label>
              <div class="role-choice">
                <button class="role-choice-item" :class="{ selected: changeManagerDraft.previousAction === 'demote' }" type="button" @click="changeManagerDraft.previousAction = 'demote'">
                  <i class="fa-solid fa-user"></i>
                  <div><strong>일반 사용자로 변경</strong><small>계속 챗봇을 사용합니다.</small></div>
                </button>
                <button class="role-choice-item" :class="{ selected: changeManagerDraft.previousAction === 'deactivate' }" type="button" @click="changeManagerDraft.previousAction = 'deactivate'">
                  <i class="fa-solid fa-user-slash"></i>
                  <div><strong>계정 비활성화</strong><small>퇴사·이동 등으로 로그인을 막습니다.</small></div>
                </button>
              </div>
            </div>
          </div>
          <div class="notice">
            <i class="fa-solid fa-circle-info"></i>
            {{ changeManagerTarget?.name }}의 대화 주제·문서와 사용자 권한은 새 운영관리자가 그대로 이어서 관리합니다. (수정 권한은 부서 기준)
          </div>
          <div v-if="changeManagerError" class="notice error"><i class="fa-solid fa-circle-exclamation"></i> {{ changeManagerError }}</div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" type="button" :disabled="changeManagerSaving" @click="closeChangeManagerModal">취소</button>
          <button class="btn btn-primary" type="button" :disabled="changeManagerSaving || !changeManagerDraft.newManagerId" @click="saveChangeManager">
            {{ changeManagerSaving ? '변경 중...' : '변경' }}
          </button>
        </div>
      </section>
    </div>

    <!-- 2026.11.23(woojin.jung) 추가 - 부서 비활성화 확인(운영관리자 읽기 전용 + 부서원 챗봇 주제 차단으로 이어짐) -->
    <div v-if="deactivateTarget" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="deactivate-title">
      <section class="modal">
        <div class="modal-head">
          <div>
            <h2 id="deactivate-title">{{ deactivateTarget.name }} 부서를 비활성화할까요?</h2>
            <p>계정과 문서·대화 주제는 지워지지 않고, 다시 활성화하면 그대로 돌아옵니다.</p>
          </div>
          <button class="close" type="button" aria-label="닫기" @click="deactivateTarget = null">×</button>
        </div>
        <div class="modal-body">
          <ul class="deactivate-effects">
            <li><i class="fa-solid fa-lock"></i><span>부서 운영관리자는 문서·대화 주제·사용자 권한을 <b>조회만</b> 할 수 있습니다.</span></li>
            <li><i class="fa-solid fa-comment-slash"></i><span>부서원 {{ deactivateTarget.userCount }}명은 챗봇에서 이 부서 대화 주제를 쓸 수 없습니다.</span></li>
            <li><i class="fa-solid fa-user-plus"></i><span>이 부서에는 사용자를 추가할 수 없습니다.</span></li>
          </ul>
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" type="button" @click="deactivateTarget = null">취소</button>
          <button class="btn btn-danger" type="button" @click="confirmDeactivate">비활성화</button>
        </div>
      </section>
    </div>

    <!-- 부서 추가·수정 (관리자) -->
    <div v-if="showDepartmentModal" class="modal-backdrop" role="dialog" aria-modal="true">
      <section class="modal wide">
        <div class="modal-head">
          <div>
            <h2>{{ departmentTarget ? '부서 수정' : '부서 추가' }}</h2>
            <p v-if="departmentTarget">허용 대화 주제를 줄이면 해당 대화 주제의 개인 차단이 자동 정리됩니다.</p>
            <!-- 2026.11.23(woojin.jung) 수정 - 대화 주제는 운영관리자가 만들면 부서 허용 주제에 자동 추가된다 -->
            <p v-else>부서명을 입력합니다. 대화 주제는 부서 운영관리자가 만들면 자동으로 허용됩니다.</p>
          </div>
          <button class="close" type="button" @click="closeDepartmentModal">×</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="field"><label>부서 ID</label><input v-model="departmentDraft.id" disabled /></div>
            <div class="field">
              <label>부서명 <span class="required">*</span></label
              ><input v-model="departmentDraft.name" placeholder="예: 설비관리팀" :disabled="departmentModalLoading || departmentSaving" @keyup.enter="handleDepartmentNameEnter" />
            </div>
            <div v-if="departmentTarget" class="field full">
              <!-- 2026.11.23(woojin.jung) 수정 - 역할 개편 후 기준(이 부서 대화 주제 중 부서원이 챗봇에서 쓸 주제) -->
              <label>허용 대화 주제 <span class="cat-role-note">챗봇 검색 범위</span></label>
              <p class="permission-grid-label">이 부서의 대화 주제 중 부서원이 챗봇에서 사용할 주제를 고릅니다.</p>
              <div v-if="departmentModalLoading" class="topic-loading"><i class="fa-solid fa-spinner spin"></i> 대화 주제를 불러오는 중입니다.</div>
              <div v-else-if="collectionOptions.length" class="permission-options">
                <label v-for="collection in collectionOptions" :key="collection.id" class="permission-option"
                  ><input v-model="departmentDraft.categories" type="checkbox" :value="collection.id" :disabled="departmentSaving" /><span>{{ collection.name }}</span></label
                >
              </div>
              <div v-else class="topic-loading">이 부서에 등록된 대화 주제가 없습니다. 부서 운영관리자가 대화 주제를 만들면 여기에 표시됩니다.</div>
              <p class="perm-hint topic-impact">{{ collectionOptions.length }}개 중 {{ departmentDraft.categories.length }}개 주제를 허용합니다.</p>
            </div>
            <label v-if="departmentTarget" class="switch-row field full"
              ><span><strong>부서 사용</strong><small>미사용 처리하면 운영관리자는 조회만 할 수 있고, 부서원은 챗봇 대화 주제를 쓸 수 없습니다.</small></span
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
          <div v-if="!departmentTarget" class="form-hint">
            <small>부서명 중복은 허용되지 않습니다. 부서를 만든 뒤 운영관리자를 먼저 등록해야 일반 사용자를 추가할 수 있습니다.</small>
          </div>
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
import { useRoute, useRouter } from 'vue-router';
import AdminSidebar from '../components/AdminSidebar.vue';
import AppToast from '../components/AppToast.vue';
import DepartmentReadOnlyNotice from '../components/DepartmentReadOnlyNotice.vue';
import PageHeader from '../components/PageHeader.vue';
import { useUserPermissions } from '../composables/useUserPermissions';

export default {
  components: { AdminSidebar, AppToast, DepartmentReadOnlyNotice, PageHeader },
  props: {
    // 2026.11.20(woojin.jung) 추가 - admin: 사용자 권한 관리 / manager: 부서 사용자 권한(자기 부서 고정)
    mode: { type: String, default: 'admin' },
  },
  setup(props) {
    const router = useRouter();
    const route = useRoute();
    return useUserPermissions({ router, route, mode: props.mode });
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

/* 2026.11.23(woojin.jung) 추가 - 표가 좁을 때 부서·상태·버튼 글자가 두 줄로 찌그러지지 않게(줄바꿈은 주제 칸이 흡수) */
.department,
.status,
.table-btn {
  white-space: nowrap;
}

.admin-content {
  flex: 1;
  padding: 24px 32px 40px;
  overflow-y: auto;
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

/* 2026.11.23(woojin.jung) 수정 - 사용자 표 높이를 고정하고 넘치는 행은 안에서 스크롤, 머리글은 상단 고정 */
.table-wrap {
  max-height: 520px;
  overflow: auto;
}

.table-wrap thead th {
  position: sticky;
  top: 0;
  z-index: 1;
}

table {
  width: 100%;
  min-width: 900px; /* 2026.11.23(woojin.jung) 수정 - 970 → 900: 부서 패널 옆에서 1536px 화면에 가로 스크롤 없이 들어가도록 */
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

.btn-danger {
  color: #fff;
  background: #dc2626;
}

/* 2026.11.23(woojin.jung) 추가 - 부서 비활성화 확인 창의 영향 목록 */
.deactivate-effects {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  color: #334155;
  font-size: 13px;
  line-height: 1.5;
  list-style: none;
}

.deactivate-effects li {
  display: flex;
  gap: 10px;
}

.deactivate-effects i {
  width: 16px;
  margin-top: 3px;
  color: #d97706;
  text-align: center;
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
  margin: 7px 0 14px 0;
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

.prerequisite-message {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  padding: 16px;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  color: #1e3a8a;
  background: #eff6ff;
}

.prerequisite-icon {
  display: grid;
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 50%;
  color: #1d4ed8;
  background: #dbeafe;
}

.prerequisite-message strong {
  display: block;
  margin-bottom: 5px;
  font-size: 14px;
}

.prerequisite-message p {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
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

  .header-actions-full {
    width: 100%;
  }

  /* 2026.11.23(woojin.jung) 추가 - 휴대폰 너비: 사용자 표를 카드로 쌓아 가로 스크롤 없이 [권한 설정]까지 보이게 */
  .table-wrap {
    max-height: none;
  }

  .table-wrap table {
    min-width: 0;
  }

  .table-wrap thead {
    display: none;
  }

  .table-wrap tbody tr {
    display: block;
    padding: 14px 16px;
    border-bottom: 1px solid #e2e8f0;
  }

  .table-wrap tbody tr:last-child {
    border-bottom: 0;
  }

  .table-wrap tbody td {
    display: block;
    padding: 4px 0;
    border-bottom: 0;
  }

  .table-wrap tbody td[data-label] {
    display: grid;
    grid-template-columns: 84px minmax(0, 1fr);
    column-gap: 10px;
    align-items: start;
  }

  .table-wrap tbody td[data-label]::before {
    padding-top: 3px;
    color: #94a3b8;
    font-size: 12px;
    content: attr(data-label);
  }

  .table-wrap tbody td[data-label] > * {
    grid-column: 2;
    justify-self: start;
  }

  .table-wrap tbody td.td-actions .row-actions {
    justify-content: flex-end;
    padding-top: 6px;
  }

  .table-wrap .topic-cell {
    max-width: none;
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
  .table-btn {
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

/* 2026.11.20(woojin.jung) 추가 - 부서 운영관리자 역할 + 부서 패널(왼쪽 부서 목록 · 부서 요약) */
.dept-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

/* 2026.11.23(woojin.jung) 수정 - 부서 패널 다듬기: 제목 행과 검색칸 간격, 검색 아이콘, 목록 간격, 오른쪽 카드와 같은 그림자 */
.dept-panel {
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.dept-panel-head {
  padding: 14px 14px 12px;
  border-bottom: 1px solid #e2e8f0;
}

.dept-search {
  position: relative;
}

.dept-search i {
  position: absolute;
  top: 50%;
  left: 11px;
  color: #94a3b8;
  font-size: 12px;
  transform: translateY(-50%);
  pointer-events: none;
}

.dept-panel-head .input {
  width: 100%;
  height: 36px;
  padding-left: 31px;
}

.dept-panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

/* 2026.11.23(woojin.jung) 수정 - [부서 추가]가 글자 링크처럼 묻혀 보여 테두리 있는 작은 버튼으로 */
.dept-panel-title button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  color: #1d4ed8;
  background: #eff6ff;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.dept-panel-title button:hover {
  border-color: #93c5fd;
  background: #dbeafe;
}

.link-btn {
  padding: 0;
  border: 0;
  color: #2563eb;
  background: none;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.dept-list {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 8px;
  list-style: none;
}

.dept-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 9px 10px;
  border: 0;
  border-radius: 6px;
  color: #334155;
  background: none;
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.dept-item:hover {
  background: #f8fafc;
}

.dept-item.active {
  color: #1d4ed8;
  background: #eff6ff;
  font-weight: 700;
}

.dept-item.inactive {
  opacity: 0.55;
}

.dept-item i {
  width: 14px;
  color: #94a3b8;
  text-align: center;
}

.dept-item.active i {
  color: #2563eb;
}

.dept-item .dept-warn {
  color: #d97706;
  font-size: 11px;
}

.dept-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dept-count {
  min-width: 26px;
  padding: 1px 7px;
  border-radius: 999px;
  color: #64748b;
  background: #f1f5f9;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
}

.dept-item.active .dept-count {
  color: #1d4ed8;
  background: #dbeafe;
}

.dept-divider {
  height: 1px;
  margin: 6px 4px;
  background: #f1f5f9;
}

.dept-empty {
  padding: 10px;
  color: #94a3b8;
  font-size: 12px;
}

.dept-select-mobile {
  display: none;
}

.dept-head {
  padding: 16px 18px;
  border-bottom: 1px solid #f1f5f9;
}

.dept-head-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.dept-head h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: #0f172a;
  font-size: 16px;
}

.dept-head h3 > i {
  color: #64748b;
}

.dept-head h3 small {
  color: #94a3b8;
  font-family: Consolas, monospace;
  font-size: 11px;
  font-weight: 500;
}

.dept-head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.dept-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.dept-facts.two-col {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

/* 2026.11.23(woojin.jung) 수정 - 부서마다 주제 수가 달라 카드 높이가 바뀌지 않도록 높이 고정, 넘치면 카드 안에서 스크롤 */
.dept-fact {
  box-sizing: border-box;
  height: 92px;
  overflow-y: auto;
  padding: 10px 12px;
  border-radius: 8px;
  color: #64748b;
  background: #f8fafc;
  font-size: 12px;
}

.dept-fact > span {
  display: block;
  margin-bottom: 4px;
}

.dept-fact strong {
  color: #0f172a;
  font-size: 13px;
}

.dept-fact small {
  color: #94a3b8;
  font-size: 11px;
}

.dept-fact .topic-cell {
  margin-top: 2px;
}

.dept-fact .fact-empty {
  color: #94a3b8;
  font-weight: 500;
}

.dept-fact.warn {
  color: #92400e;
  background: #fffbeb;
}

.dept-fact.warn strong {
  color: #b45309;
}

.btn-sm {
  min-height: 32px;
  padding: 6px 10px;
  font-size: 12px;
}

.row-pinned td {
  background: #fffdf5;
}

.role-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.role-badge.manager {
  color: #92400e;
  background: #fef3c7;
}

.role-badge.user {
  color: #475569;
  background: #f1f5f9;
}

.role-choice {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.role-choice-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  color: #334155;
  background: #fff;
  font: inherit;
  font-size: 13px;
  text-align: left;
}

button.role-choice-item {
  cursor: pointer;
}

.role-choice-item i {
  margin-top: 2px;
  color: #64748b;
}

.role-choice-item strong {
  display: block;
  margin-bottom: 2px;
  color: #0f172a;
}

.role-choice-item small {
  display: block;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.role-choice-item.selected {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.role-choice-item.selected i {
  color: #2563eb;
}

.role-choice-item.locked {
  opacity: 0.5;
  background: #f8fafc;
}

.dept-option-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.dept-option-hint.warn {
  color: #d97706;
}

.dept-option-hint.ok {
  color: #16a34a;
}

.readonly-field {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 13px;
}

.readonly-sub {
  color: #64748b;
  font-size: 12px;
}

.field-note {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.step-list {
  display: grid;
  gap: 8px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.step-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #334155;
  font-size: 13px;
}

.step-no {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  color: #475569;
  background: #e2e8f0;
  font-size: 11px;
  font-weight: 700;
}

.step-list li.done .step-no {
  color: #15803d;
  background: #dcfce7;
}

.step-list li.current {
  color: #0f172a;
  font-weight: 700;
}

.step-list li.current .step-no {
  color: #fff;
  background: #2563eb;
}

.step-list li.current em {
  margin-left: auto;
  padding-left: 12px;
  color: #2563eb;
  font-size: 11px;
  font-style: normal;
}

.empty-steps {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 28px 20px;
  color: #0f172a;
  font-size: 13px;
  text-align: center;
}

.empty-steps-icon {
  color: #d97706;
  font-size: 22px;
}

.empty-steps .step-list {
  margin: 6px 0 8px;
  text-align: left;
}

@media (max-width: 1024px) {
  .dept-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .dept-panel {
    display: none;
  }

  .dept-select-mobile {
    display: block;
    width: 100%;
    margin-bottom: 12px;
  }

  .dept-facts,
  .dept-facts.two-col {
    grid-template-columns: minmax(0, 1fr);
  }

  .dept-head-top {
    flex-direction: column;
  }
}

@media (max-width: 768px) {
  .role-choice {
    grid-template-columns: 1fr;
  }
}

/* 2026.11.23(woojin.jung) 수정 - 반응형 점검 보완 */
@media (max-width: 1024px) {
  .dept-panel {
    display: block;
  }

  .dept-panel-head {
    border-bottom: 0;
  }

  .dept-panel-head .input,
  .dept-list {
    display: none;
  }

  .dept-panel-title {
    margin-bottom: 0;
  }

  .dept-panel-title button {
    min-height: 32px;
  }

  .dept-fact {
    height: auto;
    max-height: 140px;
  }

  .card-head {
    flex-wrap: wrap;
  }

  .card-title {
    flex-shrink: 0;
  }
}

@media (max-width: 768px) {
  .step-list li.current em {
    white-space: nowrap;
  }
}
</style>
