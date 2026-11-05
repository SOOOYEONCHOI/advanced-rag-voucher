<template>
  <transition name="app-toast">
    <div v-if="message" class="app-toast" :class="[type, { 'admin-position': adminPosition }]" role="status" aria-live="polite">
      <i :class="type === 'success' ? 'fa-solid fa-circle-check' : 'fa-solid fa-circle-exclamation'"></i>
      <span>{{ message }}</span>
      <button class="app-toast-close" type="button" aria-label="알림 닫기" @click="$emit('close')">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>
  </transition>
</template>

<script>
export default {
  name: 'AppToast',
  emits: ['close'],
  props: {
    message: { type: String, default: '' },
    type: { type: String, default: 'success' },
    adminPosition: { type: Boolean, default: false },
  },
};
</script>

<style scoped>
.app-toast {
  position: fixed;
  top: 5rem;
  left: 50%;
  transform: translateX(-50%);
  width: min(calc(100vw - 2rem), 520px);
  min-height: 52px;
  padding: 1rem 1.25rem;
  border-radius: 12px;
  font-size: 0.95rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 10px;
  line-height: 1.45;
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.18);
  z-index: 300;
}
.app-toast.admin-position {
  left: calc(260px + (100vw - 260px) / 2);
}
.app-toast > i {
  font-size: 1.1rem;
  flex-shrink: 0;
}
/* 2026.08.03(sooyeon.choi) 수정 - 명시적 개행과 긴 평가 메시지 자동 줄바꿈 지원 */
.app-toast > span {
  flex: 1;
  min-width: 0;
  white-space: pre-line;
  overflow-wrap: anywhere;
  word-break: keep-all;
}
.app-toast.success {
  background: #f0fdf4;
  color: #16a34a;
  border: 1px solid #bbf7d0;
}
.app-toast.error {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
}
.app-toast-close {
  background: none;
  border: none;
  cursor: pointer;
  color: inherit;
  font-size: 1rem;
  padding: 4px;
  margin-left: auto;
  flex-shrink: 0;
}
.app-toast-enter-active,
.app-toast-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.app-toast-enter-from,
.app-toast-leave-to {
  opacity: 0;
  transform: translate(-50%, -12px);
}
@media (max-width: 768px) {
  .app-toast {
    align-items: flex-start;
  }
  .app-toast.admin-position {
    left: 50%;
  }
}
</style>
