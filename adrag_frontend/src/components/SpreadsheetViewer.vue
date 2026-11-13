<template>
  <Teleport to="body">
    <div v-if="isOpen" class="sheet-viewer-overlay" role="dialog" aria-modal="true" aria-label="원본 Excel 시트 보기" @click.self="close">
      <section class="sheet-viewer">
        <header class="sheet-viewer-header">
          <div class="excel-app-icon"><i class="fa-solid fa-file-excel"></i></div>
          <div class="sheet-viewer-title">
            <b>{{ filename }}</b>
            <span>{{ locationLabel }}</span>
          </div>
          <button type="button" class="sheet-download-btn" :disabled="downloading" @click="downloadCurrent">
            <i :class="downloading ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-download'"></i>
            <span>Excel 다운로드</span>
          </button>
          <button ref="closeButton" type="button" class="sheet-close-btn" aria-label="닫기" @click="close"><span>닫기</span><i class="fa-solid fa-xmark"></i></button>
        </header>

        <div v-if="loading" class="sheet-viewer-status" role="status">
          <i class="fa-solid fa-circle-notch fa-spin"></i>
          <strong>원본 시트를 PDF로 변환하고 있습니다.</strong>
          <span>이미지와 도형이 많은 문서는 잠시 시간이 걸릴 수 있습니다.</span>
        </div>
        <div v-else-if="errorMessage" class="sheet-viewer-status error" role="alert">
          <i class="fa-solid fa-file-circle-xmark"></i>
          <strong>{{ errorMessage }}</strong>
          <button type="button" @click="reload"><i class="fa-solid fa-rotate-right"></i> 다시 시도</button>
        </div>

        <!-- 2026.10.28(woojin.jung) 수정 - SheetJS 재구성 대신 LibreOffice가 렌더링한 해당 시트 PDF만 표시 -->
        <iframe
          v-else-if="previewUrl"
          class="sheet-preview-frame"
          :src="`${previewUrl}#page=1&zoom=page-width&toolbar=1&navpanes=0`"
          :title="`${filename} ${citation?.sheet_name || ''} 시트 미리보기`"
        ></iframe>

        <footer v-if="previewUrl && !loading && !errorMessage" class="sheet-viewer-footer">
          <i class="fa-regular fa-circle-info info"></i>
          <span>원본 시트 형식을 유지한 PDF에 답변 근거 범위를 강조했습니다.</span>
          <button type="button" class="preview-new-window" @click="openPreviewInNewWindow"><i class="fa-solid fa-up-right-from-square"></i> 새 창에서 보기</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { chatApi } from '../api/chatApi';
import { createSafeExcelCopy } from '../utils/sanitizeExcelWorkbook';

const emit = defineEmits(['toast']);
const isOpen = ref(false);
const loading = ref(false);
const downloading = ref(false);
const errorMessage = ref('');
const previewUrl = ref('');
const citation = ref(null);
const documentId = ref('');
const filename = ref('');
const closeButton = ref(null);
let loadVersion = 0;

const locationLabel = computed(() => [citation.value?.sheet_name, citation.value?.source_range].filter(Boolean).join(' · ') || '원본 Excel');

const revokePreviewUrl = () => {
  if (!previewUrl.value) return;
  window.URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = '';
};

// 2026.10.28(woojin.jung) 추가 - 인증된 단일 시트 근거 강조 PDF를 Blob URL로 표시
const loadCurrent = async () => {
  const version = ++loadVersion;
  loading.value = true;
  errorMessage.value = '';
  revokePreviewUrl();
  try {
    const sheetName = citation.value?.sheet_name;
    const sourceRange = String(citation.value?.source_range || '')
      .replace(/^.*!/, '')
      .replace(/\$/g, '')
      .replace(/\s+/g, '');
    if (!sheetName || !sourceRange) throw new Error('SHEET_LOCATION_REQUIRED');
    const response = await chatApi.spreadsheetSheetPreview(documentId.value, sheetName, sourceRange);
    if (version !== loadVersion) return;
    previewUrl.value = window.URL.createObjectURL(response.data);
  } catch (error) {
    if (version !== loadVersion) return;
    console.error('원본 Excel 시트 미리보기 조회 실패:', error);
    if (error.message === 'SHEET_LOCATION_REQUIRED') errorMessage.value = '시트명 또는 답변 근거 범위가 없습니다.';
    else if (error.response?.status === 403) errorMessage.value = '원본 Excel 열람 권한이 없습니다.';
    else if (error.response?.status === 404) errorMessage.value = '원본 시트를 찾을 수 없습니다.';
    else if (error.response?.status === 504) errorMessage.value = '시트 변환 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.';
    else errorMessage.value = '원본 시트 미리보기를 생성할 수 없습니다.';
  } finally {
    if (version === loadVersion) loading.value = false;
  }
};

const open = async (targetCitation, targetDocumentId) => {
  citation.value = targetCitation;
  documentId.value = targetDocumentId;
  filename.value = targetCitation?.original_filename || targetCitation?.document_name || '원본 문서.xlsx';
  isOpen.value = true;
  document.body.classList.add('sheet-viewer-open');
  await nextTick();
  closeButton.value?.focus();
  await loadCurrent();
};

const close = () => {
  isOpen.value = false;
  loadVersion += 1;
  revokePreviewUrl();
  document.body.classList.remove('sheet-viewer-open');
};

const reload = () => loadCurrent();
const openPreviewInNewWindow = () => {
  // 2026.10.28(woojin.jung) 수정 - 새 창에서도 강조 근거가 있는 첫 페이지를 너비에 맞춰 즉시 표시
  if (previewUrl.value) window.open(`${previewUrl.value}#page=1&zoom=page-width`, '_blank', 'noopener,noreferrer');
};

const excelMimeType = (targetFilename) => {
  const extension = String(targetFilename || '')
    .split('.')
    .pop()
    ?.toLowerCase();
  if (extension === 'xls') return 'application/vnd.ms-excel';
  if (extension === 'xlsm') return 'application/vnd.ms-excel.sheet.macroEnabled.12';
  return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
};

// 2026.10.28(woojin.jung) 수정 - PDF 미리보기 전환 후에도 외부 연결을 제거한 안전한 Excel 사본 다운로드 유지
const downloadWorkbook = async (targetCitation, targetDocumentId) => {
  if (downloading.value) return;
  downloading.value = true;
  try {
    const targetFilename = targetCitation?.original_filename || targetCitation?.document_name || '원본 문서.xlsx';
    const response = await chatApi.spreadsheetDocumentFile(targetDocumentId);
    const safeFileData = await createSafeExcelCopy(response.data, targetFilename);
    const contentType = response.headers?.['content-type'] || excelMimeType(targetFilename);
    const blobUrl = window.URL.createObjectURL(new Blob([safeFileData], { type: contentType }));
    const anchor = document.createElement('a');
    anchor.href = blobUrl;
    anchor.download = targetFilename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000);
  } catch (error) {
    console.error('Excel 다운로드 실패:', error);
    const message =
      error.message === 'SAFE_COPY_UNSUPPORTED_FORMAT'
        ? '사본 다운로드는 XLSX·XLSM 형식만 지원합니다.'
        : error.response?.status === 403
          ? '원본 Excel 다운로드 권한이 없습니다.'
          : 'Excel 사본을 생성할 수 없습니다.';
    emit('toast', message, 'error');
  } finally {
    downloading.value = false;
  }
};

const downloadCurrent = () => downloadWorkbook(citation.value, documentId.value);
const onKeydown = (event) => {
  if (isOpen.value && event.key === 'Escape') close();
};

defineExpose({ open, download: downloadWorkbook });
onMounted(() => document.addEventListener('keydown', onKeydown));
onBeforeUnmount(() => {
  loadVersion += 1;
  revokePreviewUrl();
  document.removeEventListener('keydown', onKeydown);
  document.body.classList.remove('sheet-viewer-open');
});
</script>

<style scoped>
.sheet-viewer-overlay {
  position: fixed;
  z-index: 320;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.68);
  backdrop-filter: blur(2px);
}
.sheet-viewer {
  display: flex;
  width: min(1180px, 96vw);
  height: min(880px, 94vh);
  height: min(880px, 94dvh);
  flex-direction: column;
  overflow: hidden;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.32);
}
.sheet-viewer-header {
  display: flex;
  min-height: 76px;
  align-items: center;
  gap: 14px;
  padding: 0.9rem 1.25rem;
  border-bottom: 1px solid #e2e8f0;
}
.excel-app-icon {
  display: flex;
  width: 44px;
  height: 48px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  background: linear-gradient(135deg, #22c55e, #047857);
  color: #fff;
  font-size: 1.55rem;
  box-shadow: 0 4px 10px rgba(5, 150, 105, 0.22);
}
.sheet-viewer-title {
  flex: 1;
  min-width: 0;
}
.sheet-viewer-title b,
.sheet-viewer-title span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sheet-viewer-title b {
  color: #0f172a;
  font-size: 1.05rem;
}
.sheet-viewer-title span {
  margin-top: 3px;
  color: #64748b;
  font-size: 0.82rem;
}
.sheet-download-btn,
.sheet-close-btn {
  display: inline-flex;
  height: 38px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 0.85rem;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: #fff;
  color: #334155;
  font: inherit;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}
.sheet-download-btn {
  border-color: #16a34a;
  color: #15803d;
}
.sheet-download-btn:hover:not(:disabled) {
  background: #f0fdf4;
}
.sheet-download-btn:disabled {
  opacity: 0.5;
  cursor: wait;
}
.sheet-viewer-status {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #64748b;
}
.sheet-viewer-status > i {
  color: #16a34a;
  font-size: 2rem;
}
.sheet-viewer-status strong {
  color: #334155;
}
.sheet-viewer-status span {
  font-size: 0.8rem;
}
.sheet-viewer-status.error > i {
  color: #dc2626;
}
.sheet-viewer-status button {
  padding: 7px 11px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
}
.sheet-preview-frame {
  flex: 1;
  width: 100%;
  min-height: 0;
  border: 0;
  background: #e5e7eb;
}
.sheet-viewer-footer {
  display: flex;
  min-height: 54px;
  align-items: center;
  gap: 8px;
  padding: 0 1rem;
  border-top: 1px solid #e2e8f0;
  color: #64748b;
  font-size: 0.78rem;
}
.sheet-viewer-footer .info {
  color: #2563eb;
  font-size: 1rem;
}
.preview-new-window {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: auto;
  padding: 6px 9px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  color: #475569;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
@media (max-width: 640px) {
  .sheet-viewer-overlay {
    padding: 8px;
  }
  .sheet-viewer {
    width: 100%;
    height: 96vh;
    height: 96dvh;
  }
  .sheet-viewer-header {
    min-height: 64px;
    padding: 0.65rem;
    gap: 8px;
  }
  .excel-app-icon {
    width: 36px;
    height: 40px;
    font-size: 1.2rem;
  }
  .sheet-viewer-title b {
    font-size: 0.88rem;
  }
  .sheet-download-btn span,
  .sheet-close-btn span {
    display: none;
  }
  .sheet-download-btn,
  .sheet-close-btn {
    width: 38px;
    padding: 0;
  }
  .sheet-viewer-footer > span {
    display: none;
  }
}
</style>

<style>
body.sheet-viewer-open {
  overflow: hidden;
}
</style>
