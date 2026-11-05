<template>
  <span class="authenticated-image" :class="{ loading, failed: Boolean(errorMessage) }">
    <img v-if="objectUrl" :src="objectUrl" :alt="alt" />
    <span v-else class="image-placeholder" role="status">
      <i :class="errorMessage ? 'fa-regular fa-image' : 'fa-solid fa-circle-notch fa-spin'"></i>
      <span>{{ errorMessage || '이미지 불러오는 중' }}</span>
    </span>
  </span>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import { chatApi } from '../api/chatApi';

const props = defineProps({
  resourceId: { type: String, required: true },
  alt: { type: String, default: '' },
});

const objectUrl = ref('');
const loading = ref(false);
const errorMessage = ref('');
let requestVersion = 0;

const revokeUrl = () => {
  if (!objectUrl.value) return;
  window.URL.revokeObjectURL(objectUrl.value);
  objectUrl.value = '';
};

// 2026.10.22(woojin.jung) 수정 - 보호된 이미지 API를 Blob으로 받아 화면 표시용 Object URL 생성
const loadImage = async () => {
  const version = ++requestVersion;
  revokeUrl();
  errorMessage.value = '';
  loading.value = true;
  try {
    const response = await chatApi.spreadsheetResource(props.resourceId);
    if (version !== requestVersion) return;
    objectUrl.value = window.URL.createObjectURL(response.data);
  } catch (error) {
    if (version !== requestVersion) return;
    const status = error.response?.status;
    errorMessage.value = status === 403 ? '열람 권한 없음' : status === 404 ? '이미지 없음' : '불러오기 실패';
  } finally {
    if (version === requestVersion) loading.value = false;
  }
};

watch(() => props.resourceId, loadImage, { immediate: true });
// 2026.10.22(woojin.jung) 수정 - 컴포넌트 해제 시 Object URL을 회수해 이미지 메모리 누수 방지
onBeforeUnmount(() => {
  requestVersion += 1;
  revokeUrl();
});
</script>

<style scoped>
.authenticated-image {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #f1f5f9;
}

img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.image-placeholder {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 72px;
  color: #94a3b8;
  font-size: 0.72rem;
}

.failed .image-placeholder {
  color: #64748b;
}
</style>
