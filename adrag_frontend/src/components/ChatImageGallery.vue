<template>
  <section v-if="images.length" class="image-section" aria-label="관련 이미지">
    <!-- 2026.11.06(sooyeon.choi) 수정 - 출처 사진이 더 있으면 "표시 / 전체" 장수와 "전체 N장 보기"(출처 패널) 표시 -->
    <div class="image-section-title">
      <i class="fa-regular fa-images"></i> 관련 이미지 <span>{{ hasMore ? `${images.length} / 전체 ${total}` : images.length }}</span>
      <button v-if="hasMore" type="button" class="image-more" @click="$emit('openSources', images[0])">전체 {{ total }}장 보기 <i class="fa-solid fa-chevron-right"></i></button>
    </div>
    <div class="image-grid">
      <button v-for="(image, index) in images" :key="image.resource_id || index" type="button" class="image-card" @click="$emit('open', index)">
        <span class="image-num">{{ index + 1 }}</span>
        <span class="image-preview"><AuthenticatedImage :resource-id="image.resource_id" :alt="image.title || `관련 이미지 ${index + 1}`" /></span>
        <span class="image-card-meta">
          <b>{{ image.title || `관련 이미지 ${index + 1}` }}</b>
          <span>{{ locationLabel(image) }}</span>
        </span>
      </button>
    </div>
  </section>
</template>

<script setup>
import AuthenticatedImage from './AuthenticatedImage.vue';

import { computed } from 'vue';

// 2026.11.06(sooyeon.choi) 수정 - total(출처 사진 전체 장수)·openSources 추가
const props = defineProps({ images: { type: Array, default: () => [] }, total: { type: Number, default: 0 } });
defineEmits(['open', 'openSources']);

const hasMore = computed(() => props.total > props.images.length);

// 2026.11.06(sooyeon.choi) 수정 - 출처 기준 사진은 출처 번호 [n]을 앞에 붙여 참고 문서 카드와 연결
const locationLabel = (image) => {
  const range = [image.from_cell, image.to_cell].filter(Boolean).join('–');
  const location = [image.sheet_name, range].filter(Boolean).join(' · ') || image.original_filename || '첨부 이미지';
  return image.citation_id ? `[${image.citation_id}] ${location}` : location;
};
</script>

<style scoped>
.image-section {
  margin-top: 1.35rem;
  padding-top: 1rem;
  border-top: 1px solid #e2e8f0;
}
.image-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 0.65rem;
  color: #475569;
  font-size: 0.84rem;
  font-weight: 700;
}
.image-section-title span {
  padding: 1px 6px;
  border-radius: 999px;
  background: #dbeafe;
  color: #2563eb;
  font-size: 0.68rem;
}
/* 2026.11.06(sooyeon.choi) 추가 - "전체 N장 보기" 버튼 */
.image-more {
  margin-left: auto;
  padding: 2px 4px;
  border: 0;
  background: none;
  color: #2563eb;
  font: inherit;
  font-size: 0.74rem;
  font-weight: 600;
  cursor: pointer;
}
.image-more:hover {
  text-decoration: underline;
}
.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
}
.image-card {
  position: relative;
  display: flex;
  min-width: 0;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #fff;
  color: inherit;
  cursor: zoom-in;
  text-align: left;
  font: inherit;
  transition:
    border-color 0.15s,
    box-shadow 0.15s,
    transform 0.15s;
}
.image-card:hover {
  border-color: #60a5fa;
  box-shadow: 0 5px 16px rgba(37, 99, 235, 0.12);
  transform: translateY(-1px);
}
.image-preview {
  display: block;
  height: 112px;
}
.image-num {
  position: absolute;
  /* z-index: 1; */
  top: 7px;
  right: 7px;
  display: flex;
  width: 22px;
  height: 22px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #2563eb;
  color: white;
  font-size: 0.68rem;
  font-weight: 700;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.25);
}
.image-card-meta {
  display: block;
  min-width: 0;
  padding: 7px 9px 9px;
}
.image-card-meta b,
.image-card-meta span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.image-card-meta b {
  color: #1e293b;
  font-size: 0.78rem;
}
.image-card-meta span {
  margin-top: 2px;
  color: #64748b;
  font-size: 0.7rem;
}
@media (max-width: 560px) {
  .image-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .image-preview {
    height: 96px;
  }
}
</style>
