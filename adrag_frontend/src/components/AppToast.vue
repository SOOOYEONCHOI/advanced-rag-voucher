<template>
  <transition name="app-toast">
    <div v-if="message" class="app-toast" :class="[type, { 'admin-position': adminPosition }]" role="status" aria-live="polite">
      <i class="app-toast-icon" :class="type === 'success' ? 'fa-solid fa-circle-check' : 'fa-solid fa-circle-exclamation'"></i>
      <span class="app-toast-text">{{ message }}</span>
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
  width: max-content;
  max-width: min(calc(100vw - 2rem), 520px);
  padding: 15px 10px 15px 16px;
  border-radius: 24px;
  background: #ffffff;
  color: #0f172a;
  border: 1px solid #e2e8f0;
  font-size: 1rem;
  font-weight: 500;
  letter-spacing: -0.01em;
  display: flex;
  align-items: center;
  gap: 10px;
  line-height: 1.45;
  box-shadow:
    0 12px 32px rgba(15, 23, 42, 0.12),
    0 2px 6px rgba(15, 23, 42, 0.05);
  z-index: 300;
}
.app-toast.admin-position {
  left: calc(260px + (100vw - 260px) / 2);
}
.app-toast-icon {
  font-size: 1.2rem;
  flex-shrink: 0;
}
.app-toast.success .app-toast-icon {
  color: #22c55e;
}
.app-toast.error .app-toast-icon {
  color: #ef4444;
}
/* 2026.08.03(sooyeon.choi) 수정 - 명시적 개행과 긴 평가 메시지 자동 줄바꿈 지원 */
.app-toast-text {
  flex: 1;
  min-width: 0;
  white-space: pre-line;
  overflow-wrap: anywhere;
  word-break: keep-all;
}
.app-toast-close {
  background: none;
  border: none;
  cursor: pointer;
  color: #94a3b8;
  font-size: 0.85rem;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: 4px;
  flex-shrink: 0;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}
.app-toast-close:hover {
  background: #f1f5f9;
  color: #475569;
}
.app-toast-enter-active,
.app-toast-leave-active {
  transition:
    opacity 0.25s ease,
    transform 0.25s ease;
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
