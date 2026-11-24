<template>
  <div v-if="isOpen" class="sidebar-overlay" @click="$emit('close')"></div>

  <aside class="sidebar" :class="{ open: isOpen }">
    <div class="sidebar-top" :class="{ 'has-back': !isAdmin }">
      <div class="logo-area">
        <img :src="sidebarLogo" alt="WeRAG" class="sidebar-brand-logo" />
      </div>
      <button class="btn-close-sidebar" @click="$emit('close')">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>

    <!-- 2026.11.13(woojin.jung) 수정 - 하단 링크를 로고 아래 버튼으로 변경(메뉴 항목과 구분되도록 강조) -->
    <router-link v-if="!isAdmin" to="/chat" class="back-link" :class="{ disabled: navigationLocked }" :aria-disabled="navigationLocked" @click.capture="blockNavigation">
      <i class="fa-solid fa-comments back-link-icon" aria-hidden="true"></i>
      <span class="back-link-text">챗봇으로 돌아가기</span>
      <i class="fa-solid fa-arrow-right back-link-arrow" aria-hidden="true"></i>
    </router-link>

    <nav class="nav-menu">
      <!-- 2026.11.20(woojin.jung) 수정 - 역할별 메뉴: 관리자 / 부서 운영관리자(챗봇 관리) / 일반 사용자(내 활동 현황만) -->
      <div class="nav-section-title" v-if="isAdmin || isManager">{{ isAdmin ? '관리' : '챗봇 관리' }}</div>
      <router-link
        to="/admin"
        v-if="isManager"
        class="nav-item"
        :class="{ active: activePage === 'documents', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-file-arrow-up"></i>
        문서 관리
      </router-link>
      <router-link
        to="/admin/collections"
        v-if="isManager"
        class="nav-item"
        :class="{ active: activePage === 'collections', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-database"></i>
        대화 주제 설정
      </router-link>
      <router-link
        to="/admin/members"
        v-if="isManager"
        class="nav-item"
        :class="{ active: activePage === 'members', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-users-gear"></i>
        부서 사용자 권한
      </router-link>
      <div class="nav-section-title" :class="{ 'nav-section-gap': isManager }" v-if="!isAdmin">{{ isManager ? '현황 및 설정' : '현황' }}</div>
      <router-link
        to="/statistics"
        v-if="!isAdmin"
        class="nav-item"
        :class="{ active: activePage === 'statistics', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-chart-bar"></i>
        내 활동 현황
      </router-link>
      <!-- <router-link
        to="/settings/ui-integration"
        v-if="!isAdmin"
        class="nav-item"
        :class="{ active: activePage === 'ui-integration', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-puzzle-piece"></i>
        챗봇 연동 설정
      </router-link> -->
      <router-link
        v-if="isAdmin"
        to="/admin/users"
        class="nav-item"
        :class="{ active: activePage === 'users', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-user-lock"></i>
        사용자 권한
      </router-link>
      <router-link
        to="/admin/statistics"
        v-if="isAdmin"
        class="nav-item"
        :class="{ active: activePage === 'statistics', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-chart-bar"></i>
        통계 대시보드
      </router-link>
      <!-- 2026.07.22(sychoi) 추가 - RAG 평가 섹션 (관리자 전용) -->
      <div class="nav-section-title nav-section-gap" v-if="isAdmin">RAG 평가</div>
      <router-link
        to="/admin/eval/datasets"
        v-if="isAdmin"
        class="nav-item"
        :class="{ active: activePage === 'eval-datasets', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-pen"></i>
        평가 데이터셋
      </router-link>
      <router-link
        to="/admin/eval/runs"
        v-if="isAdmin"
        class="nav-item"
        :class="{ active: activePage === 'eval', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-compass"></i>
        평가 실행
      </router-link>
      <router-link
        to="/admin/eval/dashboard"
        v-if="isAdmin"
        class="nav-item"
        :class="{ active: activePage === 'eval-dashboard', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-chart-line"></i>
        평가 대시보드
      </router-link>
    </nav>

    <div class="sidebar-footer">
      <!-- 2026.11.13(woojin.jung) 수정 - 사용자 정보·로그아웃 버튼을 계정 메뉴로 통합(비밀번호 변경은 일반 사용자만) -->
      <div ref="accountEl" class="account">
        <div v-if="menuOpen" id="sidebarAccountMenu" class="account-menu" role="menu" aria-label="계정 메뉴" @keydown="onMenuKeydown">
          <template v-if="!isAdmin">
            <button class="account-menu-item" type="button" role="menuitem" @click="openPasswordDialog">
              <i class="fa-solid fa-key"></i>
              비밀번호 변경
            </button>
            <div class="account-menu-divider" role="separator"></div>
          </template>
          <button class="account-menu-item danger" type="button" role="menuitem" @click="logout">
            <i class="fa-solid fa-right-from-bracket"></i>
            로그아웃
          </button>
        </div>
        <button
          ref="triggerEl"
          class="account-trigger"
          :class="{ open: menuOpen }"
          type="button"
          aria-haspopup="menu"
          aria-controls="sidebarAccountMenu"
          :aria-expanded="menuOpen"
          :disabled="navigationLocked"
          @click="menuOpen = !menuOpen"
        >
          <span class="account-avatar" aria-hidden="true">{{ avatarInitial }}</span>
          <span class="account-text">
            <span class="account-name">{{ displayName || '사용자' }}</span>
            <span class="account-role">{{ roleLabel }}</span>
          </span>
          <i class="fa-solid fa-chevron-up account-caret" aria-hidden="true"></i>
        </button>
      </div>
    </div>
  </aside>

  <ChangePasswordDialog v-if="!isAdmin" :open="passwordDialogOpen" :userId="sessionUserId" @close="passwordDialogOpen = false" />
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import sidebarLogo from '../assets/brand/logo-rag-w.png';
import ChangePasswordDialog from './ChangePasswordDialog.vue';

const passwordDialogOpen = ref(false);
const sessionUserId = sessionStorage.getItem('user_id') || '';
// 2026.11.20(woojin.jung) 추가 - 부서 운영관리자 여부·부서명(로그인 시 세션에 저장, 실제 권한은 서버가 판단)
const sessionRole = sessionStorage.getItem('user_role') || 'user';
const sessionDepartment = sessionStorage.getItem('user_department_name') || '';

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false,
  },
  activePage: {
    type: String,
    default: 'documents',
  },
  isAdmin: {
    type: Boolean,
    default: false,
  },
  displayName: {
    type: String,
    default: '',
  },
  navigationLocked: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['close', 'logout']);

const isManager = computed(() => !props.isAdmin && sessionRole === 'manager');
const roleLabel = computed(() => {
  if (props.isAdmin) return '관리자';
  const role = isManager.value ? '운영관리자' : '일반 사용자';
  return sessionDepartment ? `${sessionDepartment} · ${role}` : role;
});

const blockNavigation = (event) => {
  if (!props.navigationLocked) return;
  event.preventDefault();
  event.stopImmediatePropagation();
};

// 2026.11.13(woojin.jung) 추가 - 계정 메뉴(바깥 클릭·Esc로 닫기, ↑↓로 항목 이동)
const menuOpen = ref(false);
const accountEl = ref(null);
const triggerEl = ref(null);
const avatarInitial = computed(() => (props.displayName || '?').slice(0, 1).toUpperCase());

const onDocumentPointerDown = (event) => {
  if (!accountEl.value?.contains(event.target)) menuOpen.value = false;
};
watch(menuOpen, async (open) => {
  if (!open) {
    document.removeEventListener('pointerdown', onDocumentPointerDown);
    return;
  }
  document.addEventListener('pointerdown', onDocumentPointerDown);
  await nextTick();
  accountEl.value?.querySelector('[role="menuitem"]')?.focus();
});
watch(
  () => props.navigationLocked,
  (locked) => {
    if (locked) menuOpen.value = false;
  }
);
onBeforeUnmount(() => document.removeEventListener('pointerdown', onDocumentPointerDown));

const onMenuKeydown = (event) => {
  if (event.key === 'Escape') {
    event.preventDefault();
    menuOpen.value = false;
    triggerEl.value?.focus();
    return;
  }
  if (event.key === 'Tab') {
    menuOpen.value = false;
    return;
  }
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
  event.preventDefault();
  const items = [...accountEl.value.querySelectorAll('[role="menuitem"]')];
  const step = event.key === 'ArrowDown' ? 1 : -1;
  items[(items.indexOf(document.activeElement) + step + items.length) % items.length].focus();
};

const openPasswordDialog = () => {
  menuOpen.value = false;
  triggerEl.value?.focus(); // 대화상자를 닫으면 계정 버튼으로 포커스가 돌아오도록
  passwordDialogOpen.value = true;
};
const logout = () => {
  menuOpen.value = false;
  emit('logout');
};
</script>

<style scoped>
.sidebar {
  width: 260px !important;
  background: #1e293b;
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  padding: 1rem;
  flex-shrink: 0;
  transition: transform 0.25s ease;
  box-sizing: border-box;
}
.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2rem;
  padding: 0 0.5rem;
}
.logo-area {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
}
.sidebar-brand-logo {
  display: block;
  width: 140px;
  max-width: 100%;
  height: auto;
  object-fit: contain;
  object-position: left center;
  image-rendering: auto;
}
.btn-close-sidebar {
  display: none;
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 4px;
}
.btn-close-sidebar:hover {
  color: white;
}
.nav-section-title {
  font-size: 0.7rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 0 0.5rem;
  margin-bottom: 0.5rem;
}
/* 화면 높이가 낮을 때 메뉴만 스크롤 */
.nav-menu {
  min-height: 0;
  overflow-y: auto;
}
/* 2026.07.22(sychoi) 추가 - 섹션 구분 여백 (RAG 평가 섹션) */
.nav-section-gap {
  margin-top: 1.25rem;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0.65rem 0.75rem;
  border-radius: 8px;
  cursor: pointer;
  color: #94a3b8;
  font-size: 0.875rem;
  margin-bottom: 2px;
  transition: all 0.15s;
  text-decoration: none;
}
.nav-item.active {
  background: #334155;
  color: white;
}
.nav-item.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.nav-item:not(.active):not(.disabled):hover {
  background: #334155;
  color: #e2e8f0;
}
.sidebar-footer {
  margin-top: auto;
  border-top: 1px solid #334155;
  padding-top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
/* 2026.11.13(woojin.jung) 추가 - 계정 메뉴(아바타·이름 버튼 + 위로 열리는 메뉴) */
.account {
  position: relative;
}
.account-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 0.5rem;
  border: 1px solid transparent;
  border-radius: 10px;
  background: none;
  color: #e2e8f0;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.15s,
    border-color 0.15s;
}
.account-trigger:hover:not(:disabled),
.account-trigger.open {
  background: #334155;
}
.account-trigger:focus-visible {
  outline: none;
  border-color: #60a5fa;
}
.account-trigger:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.account-avatar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #2563eb;
  color: #fff;
  font-size: 0.85rem;
  font-weight: 600;
}
.account-text {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  line-height: 1.3;
}
.account-name {
  overflow: hidden;
  font-size: 0.85rem;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.account-role {
  color: #94a3b8;
  font-size: 0.72rem;
  margin-top: 3px;
}
.account-caret {
  flex-shrink: 0;
  color: #94a3b8;
  font-size: 0.7rem;
  transition: transform 0.15s;
}
/* 메뉴가 위로 열리므로 닫힘=위(⌃), 열림=아래(⌄, 닫기) */
.account-trigger.open .account-caret {
  transform: rotate(180deg);
}
.account-menu {
  position: absolute;
  right: 0;
  bottom: calc(100% + 6px);
  left: 0;
  z-index: 10;
  padding: 4px;
  border: 1px solid #334155;
  border-radius: 10px;
  background: #0f172a;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
}
.account-menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 0;
  border-radius: 6px;
  background: none;
  color: #cbd5e1;
  font: inherit;
  font-size: 0.84rem;
  text-align: left;
  cursor: pointer;
}
.account-menu-item i {
  width: 14px;
  color: #94a3b8;
  text-align: center;
}
.account-menu-item:hover,
.account-menu-item:focus-visible {
  outline: none;
  background: #1e293b;
  color: #fff;
}
.account-menu-item.danger,
.account-menu-item.danger i {
  color: #f87171;
}
.account-menu-item.danger:hover,
.account-menu-item.danger:focus-visible {
  background: #3b1f1f;
  color: #fca5a5;
}
.account-menu-divider {
  height: 1px;
  margin: 4px 6px;
  background: #334155;
}
/* 2026.11.13(woojin.jung) 수정 - 로고 아래 작은 회색 링크(텍스트가 로고 시작선에 맞도록 좌우 여백 조정) */
.sidebar-top.has-back {
  margin-bottom: 1rem;
}
.back-link {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 1.5rem;
  padding: 0.65rem 0.75rem;
  border: 1px solid #475569;
  border-radius: 10px;
  background: rgba(148, 163, 184, 0.06);
  color: #cbd5e1;
  font-size: 0.875rem;
  font-weight: 500;
  text-decoration: none;
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s;
}
.back-link-icon,
.back-link-arrow {
  color: #64748b;
  transition: color 0.15s;
}
/* 아이콘에만 포인트 색 — 메뉴 항목(회색 아이콘)과 구분 */
.back-link-icon {
  color: #60a5fa;
}
.back-link-text {
  flex: 1;
  min-width: 0;
}
.back-link-arrow {
  font-size: 0.75rem;
  transition:
    color 0.15s,
    transform 0.15s;
}
.back-link:hover:not(.disabled) {
  border-color: #64748b;
  background: #334155;
  color: #fff;
}
.back-link:hover:not(.disabled) .back-link-arrow {
  color: #e2e8f0;
}
.back-link:focus-visible {
  outline: none;
  border-color: #60a5fa;
}
.back-link:hover:not(.disabled) .back-link-arrow {
  transform: translateX(3px);
}
.back-link.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.sidebar-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 40;
}

/* 2026.11.03(woojin.jung) 수정 - 태블릿 가로는 데스크톱, 세로는 모바일 레이아웃(사이드바 숨김) */
@media (max-width: 768px), (max-width: 1024px) and (orientation: portrait), (max-width: 1024px) and (max-height: 500px) {
  .sidebar {
    max-width: 85vw;
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 50;
    transform: translateX(-100%);
    width: 280px;
  }
  .sidebar.open {
    transform: translateX(0);
  }
  .sidebar-overlay {
    display: block;
  }
  .btn-close-sidebar {
    display: flex;
  }
}
</style>
