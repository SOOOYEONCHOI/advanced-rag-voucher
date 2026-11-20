<!-- 2026.11.13(woojin.jung) 추가 - 일반 사용자 비밀번호 변경 대화상자 (docs/chat_UI-비밀번호변경_20261113.html) -->
<template>
  <Teleport to="body">
    <div v-if="open" class="pw-backdrop">
      <section ref="dialogEl" class="pw-dialog" role="dialog" aria-modal="true" aria-labelledby="pwDialogTitle" tabindex="-1" @keydown="onKeydown">
        <header class="pw-head">
          <div>
            <h2 id="pwDialogTitle">비밀번호 변경</h2>
            <p>{{ userId }} 계정의 비밀번호를 변경합니다.</p>
          </div>
          <button class="pw-icon-btn" type="button" aria-label="닫기" :disabled="loading" @click="close">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </header>

        <form id="pwChangeForm" class="pw-body" novalidate @submit.prevent="submit">
          <!-- 브라우저 비밀번호 관리자가 계정을 인식하도록 숨은 아이디 필드 -->
          <input type="text" name="username" :value="userId" autocomplete="username" hidden readonly />

          <div class="pw-group">
            <label for="pwCurrent">현재 비밀번호</label>
            <div class="pw-field">
              <input
                id="pwCurrent"
                ref="currentEl"
                v-model="current"
                :type="show.current ? 'text' : 'password'"
                autocomplete="current-password"
                :class="{ invalid: currentError }"
                :disabled="loading"
                aria-describedby="pwCurrentMsg pwCapsMsg"
                @input="currentError = ''"
                @keydown="checkCaps"
                @keyup="checkCaps"
              />
              <button class="pw-toggle" type="button" :aria-label="show.current ? '비밀번호 숨기기' : '비밀번호 표시'" @click="show.current = !show.current">
                <i :class="show.current ? 'fa-regular fa-eye-slash' : 'fa-regular fa-eye'"></i>
              </button>
            </div>
            <p v-if="currentError" id="pwCurrentMsg" class="pw-msg error"><i class="fa-solid fa-circle-exclamation"></i>{{ currentError }}</p>
            <p v-if="capsLock" id="pwCapsMsg" class="pw-msg warn"><i class="fa-solid fa-triangle-exclamation"></i>Caps Lock이 켜져 있습니다.</p>
          </div>

          <div class="pw-group">
            <label for="pwNew">새 비밀번호</label>
            <div class="pw-field">
              <input
                id="pwNew"
                v-model="next"
                :type="show.next ? 'text' : 'password'"
                autocomplete="new-password"
                :class="{ invalid: nextError || tooLong }"
                :disabled="loading"
                aria-describedby="pwRules pwNewMsg"
                @input="nextError = ''"
              />
              <button class="pw-toggle" type="button" :aria-label="show.next ? '비밀번호 숨기기' : '비밀번호 표시'" @click="show.next = !show.next">
                <i :class="show.next ? 'fa-regular fa-eye-slash' : 'fa-regular fa-eye'"></i>
              </button>
            </div>
            <ul id="pwRules" class="pw-rules" aria-live="polite">
              <li v-for="rule in ruleStates" :key="rule.label" :class="rule.state">
                <i :class="rule.state === 'ok' ? 'fa-solid fa-check' : rule.state === 'fail' ? 'fa-solid fa-xmark' : 'fa-regular fa-circle'"></i>{{ rule.label }}
              </li>
            </ul>
            <p v-if="nextError || tooLong" id="pwNewMsg" class="pw-msg error"><i class="fa-solid fa-circle-exclamation"></i>{{ nextError || PASSWORD_TOO_LONG_TEXT }}</p>
          </div>

          <div class="pw-group">
            <label for="pwConfirm">새 비밀번호 확인</label>
            <div class="pw-field">
              <input
                id="pwConfirm"
                v-model="confirm"
                :type="show.confirm ? 'text' : 'password'"
                autocomplete="new-password"
                :class="{ invalid: confirmMismatch }"
                :disabled="loading"
                aria-describedby="pwConfirmMsg"
                @blur="confirmTouched = true"
              />
              <button class="pw-toggle" type="button" :aria-label="show.confirm ? '비밀번호 숨기기' : '비밀번호 표시'" @click="show.confirm = !show.confirm">
                <i :class="show.confirm ? 'fa-regular fa-eye-slash' : 'fa-regular fa-eye'"></i>
              </button>
            </div>
            <p v-if="confirmMismatch" id="pwConfirmMsg" class="pw-msg error"><i class="fa-solid fa-circle-exclamation"></i>새 비밀번호와 일치하지 않습니다.</p>
          </div>

          <p v-if="formError" class="pw-msg error"><i class="fa-solid fa-circle-exclamation"></i>{{ formError }}</p>
        </form>

        <footer class="pw-foot">
          <p class="pw-note">변경하면 모든 기기에서 로그아웃되며<br />새 비밀번호로 다시 로그인해야 합니다.</p>
          <div class="pw-actions">
            <button class="pw-btn-cancel" type="button" :disabled="loading" @click="close">취소</button>
            <!-- form 밖(하단)에 있지만 form 속성으로 연결 → 입력 칸에서 Enter로 제출 -->
            <button class="pw-btn-submit" type="submit" form="pwChangeForm" :disabled="!canSubmit">
              <template v-if="loading"><i class="fa-solid fa-circle-notch fa-spin"></i>변경 중...</template>
              <template v-else>변경하기</template>
            </button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { authApi } from '../api/authApi';
import { PASSWORD_RULES, PASSWORD_TOO_LONG_TEXT, isPasswordTooLong } from '../constants/passwordPolicy';
import { useAuthStore } from '../stores/authStore';
import { handleDialogKeydown, restoreFocus } from '../utils/dialogKeydown';

const props = defineProps({
  open: { type: Boolean, default: false },
  userId: { type: String, default: '' },
});
const emit = defineEmits(['close']);

const router = useRouter();
const authStore = useAuthStore();

const dialogEl = ref(null);
const currentEl = ref(null);
const current = ref('');
const next = ref('');
const confirm = ref('');
const show = reactive({ current: false, next: false, confirm: false });
const confirmTouched = ref(false);
const capsLock = ref(false);
const loading = ref(false);
const currentError = ref('');
const nextError = ref('');
const formError = ref('');
let opener = null;

const ruleStates = computed(() =>
  PASSWORD_RULES.map((rule) => ({
    label: rule.label,
    state: !next.value ? '' : rule.test(next.value, { userId: props.userId, currentPassword: current.value }) ? 'ok' : 'fail',
  })),
);
const tooLong = computed(() => isPasswordTooLong(next.value));
const confirmMismatch = computed(() => confirmTouched.value && !!confirm.value && confirm.value !== next.value);
const canSubmit = computed(
  () => !loading.value && !!current.value && ruleStates.value.every((rule) => rule.state === 'ok') && !tooLong.value && confirm.value === next.value,
);

// 열 때마다 초기화(이전 입력을 남기지 않음)
const reset = () => {
  current.value = next.value = confirm.value = '';
  Object.assign(show, { current: false, next: false, confirm: false });
  confirmTouched.value = capsLock.value = loading.value = false;
  currentError.value = nextError.value = formError.value = '';
};

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return;
    opener = document.activeElement;
    reset();
    await nextTick();
    currentEl.value?.focus();
  },
);

const close = () => {
  if (loading.value) return;
  emit('close');
  reset();
  restoreFocus(opener);
};

const onKeydown = (event) => handleDialogKeydown(event, close);
const checkCaps = (event) => {
  if (event.getModifierState) capsLock.value = event.getModifierState('CapsLock');
};

const submit = async () => {
  if (!canSubmit.value) return;
  loading.value = true;
  formError.value = '';
  try {
    await authApi.changePassword({ current_password: current.value, new_password: next.value });
  } catch (err) {
    loading.value = false;
    const detail = err.response?.data?.detail;
    const message = (typeof detail === 'string' ? detail : detail?.message) || '비밀번호 변경에 실패했습니다. 잠시 후 다시 시도해 주세요.';
    if (detail?.field === 'current_password') {
      currentError.value = message;
      await nextTick();
      currentEl.value?.select();
      currentEl.value?.focus();
    } else if (detail?.field === 'new_password') {
      nextError.value = message;
    } else {
      formError.value = message;
    }
    return;
  }
  // 변경 전 토큰은 서버에서 무효가 되므로 바로 로그아웃하고 로그인 화면으로 이동
  await authStore.logoutAny();
  loading.value = false;
  emit('close');
  router.replace({ path: '/login', query: { reason: 'password_changed' } });
};
</script>

<style scoped>
.pw-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(15, 23, 42, 0.5);
}
.pw-dialog {
  width: 100%;
  max-width: 440px;
  max-height: calc(100dvh - 32px);
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.25);
  color: #0f172a;
  font-family: inherit;
  text-align: left;
  outline: none;
}
.pw-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.25rem 1.5rem 1rem;
  border-bottom: 1px solid #e2e8f0;
}
.pw-head h2 {
  margin: 0 0 0.2rem;
  color: #0f172a;
  font-size: 1.05rem;
}
.pw-head p {
  margin: 0;
  color: #64748b;
  font-size: 0.8rem;
  word-break: break-all;
}
.pw-icon-btn {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 8px;
  background: none;
  color: #64748b;
  font-size: 1rem;
  cursor: pointer;
}
.pw-icon-btn:hover:not(:disabled) {
  background: #f1f5f9;
  color: #0f172a;
}
.pw-body {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 1.25rem 1.5rem;
  overflow-y: auto;
}
.pw-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pw-group label {
  font-size: 0.78rem;
  font-weight: 600;
  color: #374151;
}
.pw-field {
  position: relative;
}
.pw-field input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #d1d5db;
  border-radius: 7px;
  padding: 0.6rem 2.6rem 0.6rem 0.7rem;
  font: inherit;
  font-size: 0.88rem;
  color: #374151;
  outline: none;
  background: #fff;
}
.pw-field input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}
.pw-field input.invalid {
  border-color: #ef4444;
}
.pw-field input.invalid:focus {
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.12);
}
.pw-field input:disabled {
  background: #f8fafc;
  color: #94a3b8;
}
.pw-toggle {
  position: absolute;
  top: 50%;
  right: 4px;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: #94a3b8;
  cursor: pointer;
}
.pw-toggle:hover {
  color: #475569;
}
.pw-msg {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 0.76rem;
}
.pw-msg.error {
  color: #dc2626;
}
.pw-msg.warn {
  color: #b45309;
}
.pw-rules {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin: 2px 0 0;
  padding: 0;
  list-style: none;
  font-size: 0.76rem;
  color: #94a3b8;
}
.pw-rules li {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pw-rules li i {
  width: 12px;
  text-align: center;
}
.pw-rules li.ok {
  color: #16a34a;
}
.pw-rules li.fail {
  color: #dc2626;
}
.pw-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1.5rem 1.25rem;
  border-top: 1px solid #e2e8f0;
}
.pw-note {
  margin: 0;
  color: #64748b;
  font-size: 0.76rem;
  line-height: 1.4;
}
.pw-actions {
  display: flex;
  flex-shrink: 0;
  gap: 0.5rem;
}
.pw-btn-cancel {
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: #fff;
  color: #374151;
  padding: 0.55rem 1rem;
  font: inherit;
  font-size: 0.85rem;
  cursor: pointer;
}
.pw-btn-cancel:hover:not(:disabled) {
  background: #f8fafc;
}
.pw-btn-submit {
  display: flex;
  align-items: center;
  gap: 6px;
  border: none;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  padding: 0.55rem 1.1rem;
  font: inherit;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
}
.pw-btn-submit:hover:not(:disabled) {
  background: #1d4ed8;
}
.pw-btn-submit:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
@media (max-width: 768px) {
  .pw-head,
  .pw-body {
    padding-left: 1rem;
    padding-right: 1rem;
  }
  .pw-foot {
    flex-direction: column;
    align-items: stretch;
    padding: 1rem;
  }
  .pw-actions > * {
    flex: 1;
    justify-content: center;
  }
}
</style>
