<template>
  <div v-if="isOpen" class="sidebar-overlay" @click="$emit('close')"></div>

  <aside class="sidebar" :class="{ open: isOpen }">
    <div class="sidebar-top">
      <div class="logo-area">
        <img :src="sidebarLogo" alt="WeRAG" class="sidebar-brand-logo" />
      </div>
      <button class="btn-close-sidebar" @click="$emit('close')">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>

    <nav class="nav-menu">
      <div class="nav-section-title">관리</div>
      <router-link
        to="/admin"
        v-if="!isAdmin"
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
        v-if="!isAdmin"
        class="nav-item"
        :class="{ active: activePage === 'collections', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-database"></i>
        대화 주제 설정
      </router-link>
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
      <router-link
        to="/settings/ui-integration"
        v-if="!isAdmin"
        class="nav-item"
        :class="{ active: activePage === 'ui-integration', disabled: navigationLocked }"
        :aria-disabled="navigationLocked"
        @click.capture="blockNavigation"
      >
        <i class="fa-solid fa-puzzle-piece"></i>
        UI 연동 방식
      </router-link>
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
      <div class="admin-info" v-if="displayName">
        <i :class="isAdmin ? 'fa-solid fa-user-shield' : 'fa-solid fa-user'"></i>
        <span>{{ displayName }}</span>
      </div>
      <button class="btn-logout" :disabled="navigationLocked" @click="$emit('logout')">
        <i class="fa-solid fa-right-from-bracket"></i>
        로그아웃
      </button>
      <router-link v-if="!isAdmin" to="/chat" class="back-link" :class="{ disabled: navigationLocked }" :aria-disabled="navigationLocked" @click.capture="blockNavigation">
        <i class="fa-solid fa-arrow-left"></i>
        챗봇으로 돌아가기
      </router-link>
    </div>
  </aside>
</template>

<script setup>
import sidebarLogo from '../assets/brand/werag-logo-dark.png';

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

defineEmits(['close', 'logout']);

const blockNavigation = (event) => {
  if (!props.navigationLocked) return;
  event.preventDefault();
  event.stopImmediatePropagation();
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
  min-width: 0;
}
.sidebar-brand-logo {
  display: block;
  width: 75%;
  max-width: 100%;
  height: auto;
  object-fit: contain;
  mix-blend-mode: lighten;
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
.admin-info {
  font-size: 0.78rem;
  color: #94a3b8;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 0.5rem;
  margin-bottom: 0.5rem;
  min-width: 0;
}
.admin-info span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.btn-logout {
  background: none;
  border: 1px solid #475569;
  color: #94a3b8;
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  font-size: 0.82rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s;
}
.btn-logout:hover {
  background: #3b1f1f;
  border-color: #ef4444;
  color: #ef4444;
}
.btn-logout:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.back-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0.6rem 0.5rem;
  color: #94a3b8;
  text-decoration: none;
  font-size: 0.85rem;
  border-radius: 6px;
}
.back-link:hover {
  color: white;
  background: #334155;
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
