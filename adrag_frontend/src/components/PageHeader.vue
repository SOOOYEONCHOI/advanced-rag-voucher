<template>
  <header class="page-header">
    <div class="page-header-left">
      <button class="page-header-menu" :class="{ visible: showMenu }" type="button" aria-label="메뉴 열기" @click="$emit('openSidebar')">
        <i class="fa-solid fa-bars"></i>
      </button>
      <div class="page-header-text">
        <h1>
          <slot name="title">{{ title }}</slot>
        </h1>
        <p v-if="description || $slots.description">
          <slot name="description">{{ description }}</slot>
        </p>
      </div>
    </div>
    <slot name="actions"></slot>
  </header>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    default: '',
  },
  description: {
    type: String,
    default: '',
  },
  // 2026.11.04(woojin.jung) 추가 - 넓은 화면에서도 메뉴 버튼 표시(사이드바가 접혔을 때)
  showMenu: {
    type: Boolean,
    default: false,
  },
});

defineEmits(['openSidebar']);
</script>

<style scoped>
.page-header {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.75rem 2rem;
  border-bottom: 1px solid #e2e8f0;
  background: #fff;
}
.page-header-left {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.75rem;
}
.page-header-text {
  min-width: 0;
}
.page-header-menu {
  display: none;
  flex-shrink: 0;
  padding: 6px;
  border: 0;
  border-radius: 6px;
  color: #64748b;
  background: none;
  font-size: 1.1rem;
  cursor: pointer;
}
.page-header-menu.visible {
  display: flex;
}
.page-header-menu:hover {
  color: #1e293b;
  background: #f1f5f9;
}
h1 {
  margin: 0 0 0.2rem;
  overflow: hidden;
  color: #0f172a;
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.25;
  text-overflow: ellipsis;
}
p {
  margin: 0;
  overflow: hidden;
  color: #64748b;
  font-size: 0.85rem;
  line-height: 1.45;
  text-overflow: ellipsis;
}
/* 2026.11.03(woojin.jung) 수정 - 태블릿 가로는 데스크톱, 세로는 모바일 레이아웃(사이드바 숨김) */
@media (max-width: 768px), (max-width: 1024px) and (orientation: portrait), (max-width: 1024px) and (max-height: 500px) {
  .page-header {
    padding: 1.25rem 1.5rem;
  }
  .page-header-menu {
    display: flex;
  }
}
@media (max-width: 768px) {
  .page-header {
    padding: 1rem;
  }
  h1 {
    margin: 0;
    font-size: 1.1rem;
    white-space: nowrap;
  }
  p {
    display: none;
  }
}
</style>
