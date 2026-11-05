<template>
  <Teleport to="body">
    <div v-if="open && currentImage" class="image-viewer-overlay" role="dialog" aria-modal="true" aria-label="이미지 원본 보기" @click.self="$emit('close')">
      <div class="image-viewer">
        <header>
          <span class="viewer-number">{{ currentIndex + 1 }}</span>
          <b>{{ currentImage.title || '관련 이미지' }}</b>
          <span class="viewer-count">{{ currentIndex + 1 }} / {{ images.length }}</span>
          <button ref="closeButton" type="button" class="icon-button" aria-label="닫기" @click="$emit('close')"><i class="fa-solid fa-xmark"></i></button>
        </header>
        <div class="viewer-stage">
          <AuthenticatedImage :key="currentImage.resource_id" :resource-id="currentImage.resource_id" :alt="currentImage.title || '관련 이미지'" />
          <button v-if="images.length > 1" type="button" class="nav prev" aria-label="이전 이미지" @click="move(-1)"><i class="fa-solid fa-chevron-left"></i></button>
          <button v-if="images.length > 1" type="button" class="nav next" aria-label="다음 이미지" @click="move(1)"><i class="fa-solid fa-chevron-right"></i></button>
        </div>
        <footer>
          <div class="viewer-meta">
            <b>{{ currentImage.title || '관련 이미지' }}</b>
            <span>{{ sourceLabel }}</span>
            <p v-if="currentImage.surrounding_text">{{ currentImage.surrounding_text }}</p>
          </div>
          <div class="viewer-actions">
            <!-- <button v-if="canLocate" type="button" @click="$emit('locate', currentImage)"><i class="fa-solid fa-location-dot"></i> 문서 위치</button> -->
            <button type="button" :disabled="openingOriginal" @click="openOriginal">
              <i :class="openingOriginal ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-arrow-up-right-from-square'" style="margin-right: 0.3rem"></i> 사진 원본 열기
            </button>
          </div>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch, onMounted, onBeforeUnmount } from 'vue';
import { chatApi } from '../api/chatApi';
import AuthenticatedImage from './AuthenticatedImage.vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  images: { type: Array, default: () => [] },
  index: { type: Number, default: 0 },
  canLocate: { type: Boolean, default: false },
});
const emit = defineEmits(['close', 'change', 'locate', 'toast']);
const closeButton = ref(null);
const openingOriginal = ref(false);
const currentIndex = computed(() => Math.min(Math.max(props.index, 0), Math.max(props.images.length - 1, 0)));
const currentImage = computed(() => props.images[currentIndex.value] || null);
const sourceLabel = computed(() => {
  const image = currentImage.value || {};
  const range = [image.from_cell, image.to_cell].filter(Boolean).join('–');
  return [image.original_filename, image.sheet_name, range].filter(Boolean).join(' · ');
});

const move = (offset) => {
  if (props.images.length < 2) return;
  emit('change', (currentIndex.value + offset + props.images.length) % props.images.length);
};

// 2026.10.22(woojin.jung) 수정 - 인증이 필요한 이미지 원본을 Blob URL로 만들어 새 탭에서 열기
const openOriginal = async () => {
  if (!currentImage.value || openingOriginal.value) return;
  openingOriginal.value = true;
  try {
    const response = await chatApi.spreadsheetResource(currentImage.value.resource_id);
    const url = window.URL.createObjectURL(response.data);
    window.open(url, '_blank', 'noopener,noreferrer');
    window.setTimeout(() => window.URL.revokeObjectURL(url), 60000);
  } catch (error) {
    emit('toast', error.response?.status === 403 ? '이미지 열람 권한이 없습니다.' : '이미지 원본을 열 수 없습니다.', 'error');
  } finally {
    openingOriginal.value = false;
  }
};

const onKeydown = (event) => {
  if (!props.open) return;
  if (event.key === 'Escape') emit('close');
  if (event.key === 'ArrowLeft') move(-1);
  if (event.key === 'ArrowRight') move(1);
};

watch(
  () => props.open,
  async (open) => {
    document.body.classList.toggle('image-viewer-open', open);
    if (open) {
      await nextTick();
      closeButton.value?.focus();
    }
  }
);
onMounted(() => document.addEventListener('keydown', onKeydown));
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown);
  document.body.classList.remove('image-viewer-open');
});
</script>

<style scoped>
.image-viewer-overlay {
  position: fixed;
  z-index: 300;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(15, 23, 42, 0.72);
  backdrop-filter: blur(2px);
}
.image-viewer {
  display: flex;
  width: min(900px, 96vw);
  height: min(630px, 94vh);
  height: min(630px, 94dvh);
  max-height: 94vh;
  max-height: 94dvh;
  flex-direction: column;
  overflow: hidden;
  border-radius: 16px;
  background: white;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.32);
}
header {
  display: flex;
  min-height: 58px;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid #e5e7eb;
}
header b {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: #1e293b;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.viewer-number {
  display: flex;
  width: 25px;
  height: 25px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #2563eb;
  color: white;
  font-size: 0.72rem;
  font-weight: 700;
}
.viewer-count {
  color: #64748b;
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
}
.icon-button {
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
}
.icon-button:hover {
  background: #f1f5f9;
}
.viewer-stage {
  position: relative;
  display: flex;
  min-height: 260px;
  height: min(62vh, 620px);
  align-items: center;
  justify-content: center;
  padding: 16px 64px;
  overflow: hidden;
  background: #e9eef5;
}
.viewer-stage :deep(.authenticated-image) {
  align-items: center;
  justify-content: center;
  background: transparent;
}
.viewer-stage :deep(img) {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
  box-shadow: 0 3px 16px rgba(15, 23, 42, 0.16);
}
.nav {
  position: absolute;
  top: 50%;
  display: flex;
  width: 42px;
  height: 42px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 50%;
  background: rgba(15, 23, 42, 0.68);
  color: white;
  cursor: pointer;
  transform: translateY(-50%);
}
.nav:hover {
  background: #2563eb;
}
.nav.prev {
  left: 12px;
}
.nav.next {
  right: 12px;
}
footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 16px 16px;
}
.viewer-meta {
  min-width: 0;
  color: #334155;
  font-size: 0.85rem;
}
.viewer-meta b,
.viewer-meta span {
  display: block;
}
.viewer-meta span {
  margin-top: 2px;
  color: #64748b;
  font-size: 0.78rem;
}
.viewer-meta p {
  margin: 6px 0 0;
  color: #475569;
  font-size: 0.8rem;
  line-height: 1.5;
}
.viewer-actions {
  display: flex;
  flex-shrink: 0;
  gap: 7px;
}
.viewer-actions button {
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: white;
  color: #334155;
  cursor: pointer;
  font-size: 0.78rem;
}
.viewer-actions button:hover:not(:disabled) {
  border-color: #60a5fa;
  color: #2563eb;
}
.viewer-actions button:disabled {
  opacity: 0.55;
}
@media (max-width: 640px) {
  .image-viewer-overlay {
    padding: 8px;
  }
  .viewer-stage {
    height: 55vh;
    padding: 10px 46px;
  }
  footer {
    flex-direction: column;
  }
  .viewer-actions {
    width: 100%;
  }
  .viewer-actions button {
    flex: 1;
  }
}
</style>

<style>
body.image-viewer-open {
  overflow: hidden;
}
</style>
