<template>
  <div v-if="isOpen" class="sidebar-overlay" @click="$emit('close')"></div>

  <aside class="sidebar" :class="{ open: isOpen, collapsed }">
    <div class="sidebar-top">
      <div class="logo-area">
        <img :src="sidebarLogo" alt="WeRAG" class="sidebar-brand-logo" />
      </div>
      <button class="btn-close-sidebar" @click="$emit('close')">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>

    <div class="history-section">
      <div class="history-group-title">대화 주제</div>
      <div v-if="!collectionsLoaded" class="history-loading">
        <i class="fa-solid fa-circle-notch fa-spin"></i>
      </div>
      <div v-else-if="chatCollections.length === 0" class="history-empty">접근 가능한 대화 주제가 없습니다.</div>
      <div v-for="col in chatCollections" :key="col.qdrant_name" class="history-item" :class="{ active: selectedCollection === col.qdrant_name }" @click="$emit('selectCollection', col)">
        <i class="fa-solid fa-comments" style="color: #94a3b8; flex-shrink: 0"></i>
        <span class="history-item-text">{{ col.collection_name }}</span>
      </div>
    </div>

    <div class="auth-card">
      <div class="auth-title">채팅 사용자</div>
      <div v-if="authUser.user_id" class="auth-user">
        <div class="auth-name">{{ authUser.user_id || authUser.user_name }}</div>
        <div class="auth-sub">{{ authUser.token_type === 'admin_access' ? '관리자 세션' : '로그인됨' }}</div>
        <!-- 2026.11.13(woojin.jung) 수정 - 로그아웃 옆에 비밀번호 변경(일반 사용자만) -->
        <div class="auth-actions">
          <button v-if="authUser.token_type !== 'admin_access'" class="auth-btn secondary" type="button" @click="passwordDialogOpen = true">
            <i class="fa-solid fa-key"></i>
            비밀번호 변경
          </button>
          <button class="auth-btn secondary" @click="$emit('logout')">로그아웃</button>
        </div>
      </div>
      <div v-else class="auth-form">
        <router-link to="/login?redirect=/chat" class="auth-btn auth-btn-link">
          <i class="fa-solid fa-right-to-bracket"></i>
          로그인하기
        </router-link>
        <div class="auth-hint">계정이 없으면 관리자에게 문의하세요.</div>
      </div>
    </div>

    <div class="links-section">
      <router-link to="/admin" class="link-item">
        <i class="fa-solid fa-shield-halved"></i>
        관리 콘솔
      </router-link>
    </div>
  </aside>

  <ChangePasswordDialog :open="passwordDialogOpen" :userId="authUser.user_id || ''" @close="passwordDialogOpen = false" />
</template>

<script setup>
import { ref } from 'vue';
import sidebarLogo from '../assets/brand/logo-rag-w.png';
import ChangePasswordDialog from './ChangePasswordDialog.vue';

const passwordDialogOpen = ref(false);

defineProps({
  isOpen: {
    type: Boolean,
    default: false,
  },
  // 2026.11.04(woojin.jung) 추가 - 넓은 화면에서 접힘 여부(모바일은 isOpen 사용)
  collapsed: {
    type: Boolean,
    default: false,
  },
  collectionsLoaded: {
    type: Boolean,
    default: false,
  },
  chatCollections: {
    type: Array,
    default: () => [],
  },
  selectedCollection: {
    type: String,
    default: '',
  },
  authUser: {
    type: Object,
    default: () => ({}),
  },
});

defineEmits(['close', 'selectCollection', 'logout']);
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
  transition:
    transform 0.25s ease,
    margin-left 0.25s ease,
    visibility 0.25s;
  box-sizing: border-box;
}
.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
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
/* 2026.11.04(woojin.jung) 수정 - 넓은 화면에서도 닫기(접기) 버튼 표시 */
.sidebar.collapsed {
  margin-left: -260px;
  visibility: hidden;
}
.btn-close-sidebar {
  display: flex;
  background: none;
  border: none;
  color: #94a3b8;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 4px;
}
.history-section {
  flex: 1;
  overflow-y: auto;
}
.history-group-title {
  font-size: 0.75rem;
  color: #94a3b8;
  margin-bottom: 0.5rem;
  margin-top: 0.5rem;
  padding-left: 0.5rem;
}
.history-loading,
.history-empty {
  font-size: 0.82rem;
  color: #64748b;
  padding: 0.5rem;
}
.history-item {
  padding: 0.7rem 0.75rem;
  border-radius: 8px;
  cursor: pointer;
  color: #cbd5e1;
  font-size: 0.88rem;
  margin-bottom: 2px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: background 0.15s;
}
.history-item:hover {
  background: #334155;
  color: white;
}
.history-item.active {
  background: #334155;
  color: white;
  font-weight: 500;
}
.history-item-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.auth-card {
  border: 1px solid #334155;
  border-radius: 10px;
  padding: 0.75rem;
  background: #0f172a;
  margin-top: auto;
  margin-bottom: 0.75rem;
}
.auth-title {
  font-size: 0.78rem;
  color: #94a3b8;
  margin-bottom: 0.5rem;
}
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.auth-btn {
  flex: 1;
  border: none;
  border-radius: 8px;
  padding: 0.55rem 0.75rem;
  background: #2563eb;
  color: white;
  font-size: 0.8rem;
  cursor: pointer;
  box-sizing: border-box;
}
.auth-btn.secondary {
  background: #334155;
}
/* 2026.11.13(woojin.jung) 추가 - 비밀번호 변경·로그아웃 버튼 나란히 */
.auth-actions {
  display: flex;
  gap: 0.4rem;
}
.auth-actions .auth-btn {
  white-space: nowrap;
}
.auth-actions .auth-btn i {
  margin-right: 4px;
}
.auth-btn.secondary:hover {
  background: #475569;
}
.auth-btn-link {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  text-decoration: none;
  width: 100%;
  box-sizing: border-box;
}
.auth-hint,
.auth-sub {
  font-size: 0.75rem;
  color: #94a3b8;
}
.auth-user {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.auth-name {
  font-size: 0.9rem;
  font-weight: 600;
}
.links-section {
  border-top: 1px solid #334155;
  padding-top: 1rem;
  margin-top: 1rem;
}
.link-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0.6rem 0.5rem;
  color: #94a3b8;
  text-decoration: none;
  font-size: 0.85rem;
}
.link-item:hover {
  color: white;
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
    width: 260px;
  }
  .sidebar.collapsed {
    margin-left: 0;
    visibility: visible;
  }
  .sidebar.open {
    transform: translateX(0);
  }
  .sidebar-overlay {
    display: block;
  }
}
</style>
