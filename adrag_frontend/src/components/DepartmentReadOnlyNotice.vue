<template>
  <!-- 2026.11.23(woojin.jung) 추가 - 비활성 부서의 운영관리자: 읽기 전용 안내(문서 관리·대화 주제 설정·부서 사용자 권한 공용) -->
  <div v-if="authStore.departmentReadOnly" class="dept-readonly-notice" role="status">
    <i class="fa-solid fa-lock"></i>
    <div>
      <strong>소속 부서<template v-if="authStore.departmentName">({{ authStore.departmentName }})</template>가 비활성화되어 조회만 할 수 있습니다.</strong>
      문서 업로드·수정·삭제, 대화 주제·시작 화면 질문 변경, 사용자 권한 변경이 제한됩니다. 다시 사용하려면 관리자에게 문의하세요.
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue';
import { useAuthStore } from '../stores/authStore';

const authStore = useAuthStore();

// 화면에 들어올 때 서버 기준으로 부서 활성 여부를 다시 맞춘다(로그인 중 관리자가 부서를 비활성화한 경우)
onMounted(() => {
  if (authStore.hasUser) authStore.syncUser();
});
</script>

<style scoped>
.dept-readonly-notice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border: 1px solid #fcd34d;
  border-radius: 8px;
  color: #92400e;
  background: #fffbeb;
  font-size: 13px;
  line-height: 1.5;
}

.dept-readonly-notice > i {
  margin-top: 3px;
  color: #d97706;
}

.dept-readonly-notice strong {
  display: block;
  color: #78350f;
}
</style>
