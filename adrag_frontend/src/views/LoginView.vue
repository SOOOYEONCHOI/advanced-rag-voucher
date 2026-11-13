<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">
        <img :src="loginLogo" alt="WeRAG" class="login-brand-logo" />
        <p>아이디로 로그인하세요</p>
      </div>

      <form @submit.prevent="handleLogin" class="login-form">
        <div class="form-group">
          <label for="userId">아이디</label>
          <div class="input-wrap">
            <i class="fa-solid fa-user"></i>
            <input id="userId" v-model="userId" type="text" placeholder="아이디" autocomplete="username" :disabled="isLoading" required />
          </div>
        </div>

        <div class="form-group">
          <label for="password">비밀번호</label>
          <div class="input-wrap">
            <i class="fa-solid fa-lock"></i>
            <input id="password" v-model="password" :type="showPassword ? 'text' : 'password'" placeholder="비밀번호" autocomplete="current-password" :disabled="isLoading" required />
            <button type="button" class="btn-toggle-pw" @click="showPassword = !showPassword" tabindex="-1">
              <i :class="showPassword ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye'"></i>
            </button>
          </div>
        </div>

        <div v-if="errorMsg" class="error-msg"><i class="fa-solid fa-circle-exclamation"></i> {{ errorMsg }}</div>

        <button type="submit" class="btn-login" :disabled="isLoading || !userId.trim() || !password">
          <span v-if="isLoading"><i class="fa-solid fa-spinner fa-spin"></i> 로그인 중...</span>
          <span v-else><i class="fa-solid fa-right-to-bracket"></i> 로그인</span>
        </button>
      </form>
    </div>
  </div>
</template>

<script>
import { ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '../stores/authStore';
import loginLogo from '../assets/brand/logo-rag-b.png';

export default {
  setup() {
    const router = useRouter();
    const route = useRoute();
    const authStore = useAuthStore();

    const userId = ref('');
    const password = ref('');
    const showPassword = ref(false);
    const isLoading = ref(false);
    const errorMsg = ref('');

    const handleLogin = async () => {
      errorMsg.value = '';

      // 2026.07.23(sychoi) 추가 - 클라이언트 선검증: 잘못된 요청을 서버로 보내지 않는다.
      // (로그인에서는 비밀번호 길이 정책을 검사하지 않는다 — 정책은 가입 시에만 적용)
      const trimmedId = userId.value.trim();
      if (!trimmedId || !password.value) {
        errorMsg.value = '아이디와 비밀번호를 입력해주세요.';
        return;
      }

      isLoading.value = true;
      try {
        const result = await authStore.login(trimmedId, password.value);

        if (result.role === 'admin') {
          const redirect = route.query.redirect;
          // 2026.07.23(sychoi) 수정 - RAG 평가 화면 경로 추가 (로그인 후 원래 화면으로 복귀)
          const allowedAdminPaths = ['/admin/users', '/admin/statistics', '/admin/eval/datasets', '/admin/eval/runs', '/admin/eval/dashboard'];
          router.push(typeof redirect === 'string' && allowedAdminPaths.includes(redirect) ? redirect : '/admin/users');
          return;
        }

        // /admin 하위 경로로의 redirect는 무시하고 /chat으로
        const redirect = route.query.redirect;
        router.push(redirect && !redirect.startsWith('/admin') ? redirect : '/chat');
      } catch (err) {
        // 2026.07.23(sychoi) 수정 - 422 검증 오류의 detail은 배열이며 제출한 입력값이 echo되어 있다.
        // 그대로 출력하면 원문 JSON과 비밀번호가 화면에 노출되므로 문자열일 때만 사용한다.
        const detail = err.response?.data?.detail;
        errorMsg.value = (typeof detail === 'string' && detail) || (Array.isArray(detail) ? '아이디와 비밀번호를 확인해주세요.' : '') || '아이디 또는 비밀번호가 올바르지 않습니다.';
        password.value = '';
      } finally {
        isLoading.value = false;
      }
    };

    return { userId, password, showPassword, isLoading, errorMsg, handleLogin, loginLogo };
  },
};
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.login-card {
  background: white;
  border-radius: 16px;
  padding: 2.5rem 2rem;
  width: 100%;
  max-width: 400px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.login-logo {
  text-align: center;
  margin-bottom: 2rem;
}

.login-brand-logo {
  display: block;
  width: min(250px, 100%);
  height: auto;
  object-fit: contain;
  margin: 0 auto 0.75rem;
  image-rendering: auto;
}

.login-logo p {
  font-size: 0.875rem;
  color: #64748b;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.form-group label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #374151;
}

.input-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.input-wrap > i:first-child {
  position: absolute;
  left: 0.85rem;
  color: #94a3b8;
  font-size: 0.9rem;
  pointer-events: none;
}

.input-wrap input {
  width: 100%;
  padding: 0.7rem 2.5rem 0.7rem 2.4rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.95rem;
  color: #1e293b;
  outline: none;
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
  background: #f8fafc;
}

.input-wrap input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  background: white;
}

.input-wrap input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-toggle-pw {
  position: absolute;
  right: 0.75rem;
  background: none;
  border: none;
  cursor: pointer;
  color: #94a3b8;
  font-size: 0.9rem;
  padding: 4px;
}
.btn-toggle-pw:hover {
  color: #475569;
}

.error-msg {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
  border-radius: 8px;
  padding: 0.65rem 0.85rem;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-login {
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.8rem;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
  margin-top: 0.25rem;
}
.btn-login:hover:not(:disabled) {
  background: #1d4ed8;
}
.btn-login:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
.login-page {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
.login-card {
  margin: auto;
}
@media (max-width: 480px) {
  .login-card {
    padding: 2rem 1.25rem;
  }
  .btn-toggle-pw {
    right: 0.25rem;
    width: 40px;
    height: 40px;
    padding: 0;
  }
}
</style>
