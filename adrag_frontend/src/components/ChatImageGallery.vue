<template>
  <section v-if="images.length" class="image-section" aria-label="관련 이미지">
    <div class="image-section-title">
      <i class="fa-regular fa-images"></i> 관련 이미지 <span>{{ images.length }}</span>
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

defineProps({ images: { type: Array, default: () => [] } });
defineEmits(['open']);

const locationLabel = (image) => {
  const range = [image.from_cell, image.to_cell].filter(Boolean).join('–');
  return [image.sheet_name, range].filter(Boolean).join(' · ') || image.original_filename || '첨부 이미지';
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
