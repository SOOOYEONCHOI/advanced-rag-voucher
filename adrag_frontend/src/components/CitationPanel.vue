<template>
  <!-- Mobile backdrop -->
  <Teleport to="body">
    <div v-if="isMobile && isOpen" class="sp-backdrop" @click="$emit('close')"></div>
  </Teleport>

  <SpreadsheetViewer ref="spreadsheetViewerRef" @toast="(...args) => $emit('toast', ...args)" />

  <div
    class="sources-panel"
    :class="{
      'is-open': isOpen,
      'is-mobile': isMobile,
    }"
    :style="panelStyle"
  >
    <!-- Header -->
    <div class="rp-header">
      <div class="rp-header-left">
        <span class="rp-title">참고 문서</span>
        <!-- 2026.04.08(sooyeon.choi) 추가 - 단일 카드 포커스 시 전체 보기 버튼 표시 -->
        <button v-if="!showAll && citations.length > 1" class="btn-view-all" @click="setShowAll(true)"><i class="fa-solid fa-list-ul"></i> 전체 보기</button>
      </div>
      <button class="sp-close-btn" @click="$emit('close')">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>

    <!-- 2026.10.27(woojin.jung) 수정 - 답변 순번 없이 현재 출처가 속한 질문과 답변 정보를 패널 상단에 표시 -->
    <div v-if="sourceMessageIndex >= 0" class="source-context">
      <div class="source-context-copy">
        <span class="source-context-label"> 현재 답변 · 참고 문서 {{ citations.length }}개 </span>
        <strong :title="sourceQuestion">{{ sourceQuestion || '사용자 질문 정보 없음' }}</strong>
      </div>
      <button type="button" class="source-context-link" @click="$emit('scrollToAnswer')">답변으로 이동 <i class="fa-solid fa-arrow-up"></i></button>
    </div>

    <!-- Content -->
    <div class="rp-content">
      <!-- Empty state -->
      <div v-if="citations.length === 0" class="empty-state">
        <i class="fa-regular fa-folder-open"></i>
        <p>답변의 <strong>[참조 번호]</strong>를 클릭하면<br />해당 문서의 내용을 미리 볼 수 있습니다.</p>
      </div>

      <!-- Source cards -->
      <div
        v-for="c in visibleCitations"
        :key="c.citation_id"
        class="source-card"
        :class="{
          active: !showAll && c.citation_id == selectedCitationId,
          unreferenced: !c.referenced_in_answer,
        }"
        @click="selectCard(c.citation_id)"
      >
        <!-- Card header: badge + icon + filename -->
        <div class="sc-header">
          <span class="sc-badge">{{ c.citation_id }}</span>
          <i :class="fileIconClass(c.document_type, c.original_filename)" :style="{ color: fileIconColor(c.document_type, c.original_filename) }"></i>
          <span class="sc-filename">{{ displayName(c) }}</span>
        </div>

        <!-- 2026.08.27(sooyeon.choi) 추가 - spreadsheet 시트명/셀 범위 표시 -->
        <div v-if="c.document_type === 'spreadsheet' && (c.sheet_name || c.source_range)" class="sc-location">
          {{ [c.sheet_name, c.source_range].filter(Boolean).join(' / ') }}
        </div>

        <!-- Document preview with highlight -->
        <!-- 2026.04.08(sooyeon.choi) 추가 - highlight_text 기반 특정 문장 강조 렌더링 -->
        <div class="doc-preview" v-if="c.chunk_text" @click="onPreviewClick" v-html="buildHighlightedHtml(c.chunk_text, c.highlight_text, c.document_type)"></div>

        <template v-if="linkedImages(c).length">
          <div class="sc-images-title"><i class="fa-regular fa-image"></i> 연결된 이미지 {{ linkedImages(c).length }}장</div>
          <div class="sc-images">
            <button
              v-for="(image, imageIndex) in linkedImages(c)"
              :key="image.resource_id"
              type="button"
              class="sc-image"
              :title="`${image.title || '연결 이미지'} 원본 보기`"
              @click.stop="openLinkedImages(c, imageIndex)"
            >
              <span class="sc-image-preview"><AuthenticatedImage :resource-id="image.resource_id" :alt="image.title || '연결 이미지'" /></span>
              <span>{{ image.title || '연결 이미지' }}</span>
            </button>
          </div>
        </template>
        <div v-else-if="resourcesLoading[getCitationDocumentId(c)]" class="sc-images-loading"><i class="fa-solid fa-circle-notch fa-spin"></i> 연결 이미지 확인 중</div>

        <!-- 2026.10.23(woojin.jung) 수정 - 스프레드시트 출처에 원본 시트 보기 및 Excel 다운로드 동작 추가 -->
        <div v-if="isSpreadsheetCitation(c)" class="sc-document-actions">
          <button type="button" class="primary" :disabled="Boolean(spreadsheetPendingKey)" @click.stop="openSpreadsheet(c)">
            <i :class="spreadsheetPendingKey === `view-${c.citation_id}` ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-arrow-up-right-from-square'"></i>
            원본 시트에서 보기
          </button>
          <button type="button" :disabled="Boolean(spreadsheetPendingKey)" @click.stop="downloadSpreadsheet(c)">
            <i :class="spreadsheetPendingKey === `download-${c.citation_id}` ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-download'"></i>
            Excel 다운로드
          </button>
        </div>

        <!-- Page navigation button -->
        <button v-if="displayPageNumber(c) != null" class="scroll-to-btn" @click.stop="openOriginalDocument(c)">
          페이지 {{ displayPageNumber(c) }} 로 이동 <i class="fa-solid fa-arrow-right"></i>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { authConfig, http } from '../api/http';
import { chatApi } from '../api/chatApi';
import AuthenticatedImage from './AuthenticatedImage.vue';
import SpreadsheetViewer from './SpreadsheetViewer.vue';

const props = defineProps({
  citations: {
    type: Array,
    default: () => [],
  },
  selectedCitationId: {
    type: [String, Number],
    default: null,
  },
  isOpen: {
    type: Boolean,
    default: false,
  },
  collectionName: {
    type: String,
    default: '',
  },
  panelWidth: {
    type: Number,
    default: 380,
  },
  sourceQuestion: {
    type: String,
    default: '',
  },
  sourceAnswerTime: {
    type: String,
    default: '',
  },
  sourceMessageIndex: {
    type: Number,
    default: -1,
  },
});

const emit = defineEmits(['close', 'selectCitation', 'toast', 'openImages', 'scrollToAnswer']);

// 2026.11.03(woojin.jung) 수정 - 태블릿 세로도 모바일과 같이 하단 시트로 표시 (가로는 데스크톱과 동일)
const MOBILE_LAYOUT_QUERY = '(max-width: 768px), (max-width: 1024px) and (orientation: portrait), (max-width: 1024px) and (max-height: 500px)';
const isMobile = ref(false);
// 2026.04.08(sooyeon.choi) 추가 - 단일 포커스 / 전체 보기 토글 상태
const showAll = ref(false);
const documentResources = ref({});
const resourcesLoading = ref({});
const spreadsheetViewerRef = ref(null);
const spreadsheetPendingKey = ref('');

const panelStyle = computed(() => {
  if (!props.isOpen || isMobile.value) return {};
  return {
    width: `${props.panelWidth}px`,
  };
});

// selectedCitationId가 바뀌면 단일 포커스 모드로 전환
watch(
  () => props.selectedCitationId,
  (citationId) => {
    if (citationId != null) showAll.value = false;
  }
);

// 표시할 카드 목록: 전체 보기 OR 선택된 카드만
const visibleCitations = computed(() => {
  if (showAll.value || !props.selectedCitationId) return props.citations;
  return props.citations.filter((c) => c.citation_id == props.selectedCitationId);
});

const selectCard = (citationId) => {
  emit('selectCitation', citationId);
  showAll.value = false;
};

const setShowAll = (value) => {
  showAll.value = value;
  // 2026.10.26(woojin.jung) 수정 - 전체 보기에서는 특정 참고 문서의 선택 강조 상태 해제
  if (value) emit('selectCitation', null);
};

defineExpose({ setShowAll });

const checkMobile = () => {
  isMobile.value = window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
};

// 2026.04.08(sooyeon.choi) 추가 - chunk_text 내 highlight_text 구간을 <mark>로 감싸 반환
const buildHighlightedHtml = (chunkText, highlightText, documentType) => {
  // 2026.08.27(sooyeon.choi) 추가 - Excel display_markdown을 안전한 HTML 표로 렌더링
  if (documentType === 'spreadsheet') {
    // 2026.08.27(sooyeon.choi) 추가 - 단계 8 resource marker를 조회 버튼으로 치환
    return DOMPurify.sanitize(marked.parse(replaceResourceMarkers(chunkText)), {
      ADD_ATTR: ['data-resource-id'],
    });
  }
  const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const escapedChunk = escape(chunkText);

  if (!highlightText) return escapedChunk;

  const escapedHL = escape(highlightText);
  const pattern = new RegExp(`(${escapedHL.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'i');
  return escapedChunk.replace(pattern, '<mark class="hl">$1</mark>');
};

// 2026.08.27(sooyeon.choi) 추가 - ⟦RESOURCE:{id}⟧ marker를 클릭 가능한 버튼으로 변환
const RESOURCE_MARKER_PATTERN = /⟦RESOURCE:([A-Za-z0-9_-]{1,160})⟧/g;

const replaceResourceMarkers = (text) => {
  return (text || '').replace(RESOURCE_MARKER_PATTERN, (_, resourceId) => {
    return `<button type="button" class="sc-resource" data-resource-id="${resourceId}">첨부 리소스 보기</button>`;
  });
};

const onPreviewClick = async (event) => {
  const button = event.target.closest?.('.sc-resource');
  const resourceId = button?.dataset?.resourceId;
  if (!resourceId) return;
  try {
    const res = await http.get(`/spreadsheet-resources/${encodeURIComponent(resourceId)}`, authConfig({ responseType: 'blob' }));
    const blobUrl = window.URL.createObjectURL(new Blob([res.data], { type: res.data.type }));
    window.open(blobUrl, '_blank', 'noopener,noreferrer');
    window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60000);
  } catch (e) {
    console.error('리소스 조회 실패:', e);
    emit('toast', '첨부 리소스를 열 수 없습니다.', 'error');
  }
};

const fileIconClass = (documentType, filename) => {
  const ext = (filename || '').split('.').pop().toLowerCase();
  if (documentType === 'spreadsheet' || ['xlsx', 'xlsm', 'xltx', 'xltm'].includes(ext)) return 'fa-regular fa-file-excel';
  if (documentType === 'pdf' || ext === 'pdf') return 'fa-regular fa-file-pdf';
  if (['html', 'htm'].includes(ext)) return 'fa-solid fa-earth-americas';
  return 'fa-regular fa-file-lines';
};

const fileIconColor = (documentType, filename) => {
  const ext = (filename || '').split('.').pop().toLowerCase();
  if (documentType === 'spreadsheet' || ['xlsx', 'xlsm', 'xltx', 'xltm'].includes(ext)) return '#16a34a';
  if (documentType === 'pdf' || ext === 'pdf') return '#ef4444';
  if (['html', 'htm'].includes(ext)) return '#3b82f6';
  return '#64748b';
};

const displayName = (citation) => {
  return citation.original_filename || citation.document_name || '';
};

const isSpreadsheetCitation = (citation) => {
  const extension = displayName(citation).split('.').pop()?.toLowerCase();
  return citation?.document_type === 'spreadsheet' || ['xlsx', 'xlsm', 'xltx', 'xltm', 'xls'].includes(extension);
};

// 2026.07.10(sooeyon.choi) 추가 - 매핑된 매뉴얼 citation은 표시용 원본 PDF 기준 페이지 표출
const displayPageNumber = (citation) => {
  return citation?.manual_display_mapped ? citation.display_page_number : citation?.page_number;
};

const getCitationDocumentId = (citation) => {
  return citation?.document_id || citation?.doc_id || citation?.file_id || citation?.source_document_id || citation?.metadata?.document_id || citation?.metadata?.doc_id || null;
};

// 2026.10.22(woojin.jung) 수정 - 인용 resource_ids와 표시 가능 여부를 기준으로 출처별 연결 이미지만 선별
const linkedImages = (citation) => {
  const documentId = getCitationDocumentId(citation);
  const allowedIds = new Set(citation?.resource_ids || []);
  if (!documentId || allowedIds.size === 0) return [];
  return (documentResources.value[documentId] || [])
    .filter((resource) => allowedIds.has(resource.resource_id) && resource.displayable === true && (resource.resource_type === 'image' || String(resource.mime_type || '').startsWith('image/')))
    .map((resource) => ({
      ...resource,
      document_id: documentId,
      original_filename: displayName(citation),
      context_no: citation.citation_id,
    }));
};

// 2026.10.22(woojin.jung) 수정 - 출처 패널이 열릴 때 문서별 이미지 리소스를 중복 없이 조회
const loadLinkedResources = async () => {
  const documentIds = [
    ...new Set(
      props.citations
        .filter((citation) => citation?.resource_ids?.length)
        .map(getCitationDocumentId)
        .filter(Boolean)
    ),
  ];
  await Promise.all(
    documentIds.map(async (documentId) => {
      if (documentResources.value[documentId] || resourcesLoading.value[documentId]) return;
      resourcesLoading.value = { ...resourcesLoading.value, [documentId]: true };
      try {
        const response = await chatApi.documentSpreadsheetResources(documentId);
        documentResources.value = { ...documentResources.value, [documentId]: response.data?.resources || [] };
      } catch (error) {
        console.error('문서 연결 이미지 조회 실패:', error);
        documentResources.value = { ...documentResources.value, [documentId]: [] };
      } finally {
        resourcesLoading.value = { ...resourcesLoading.value, [documentId]: false };
      }
    })
  );
};

const openLinkedImages = (citation, index) => {
  emit('openImages', { images: linkedImages(citation), index, citation, citations: props.citations });
};

watch(
  [() => props.citations, () => props.isOpen],
  ([, isOpen]) => {
    if (isOpen) loadLinkedResources();
  },
  { deep: true, immediate: true }
);

const resolveDocumentIdByFilename = async (citation) => {
  const filename = displayName(citation);
  if (!filename) return null;

  const res = await http.get(
    '/ingest/documents',
    authConfig({
      params: props.collectionName ? { collection_name: props.collectionName } : {},
    })
  );
  const documents = res.data.documents || [];
  const found = documents.find((doc) => {
    const candidates = [doc.filename, doc.original_filename, doc.document_name].filter(Boolean);
    return candidates.some((name) => name === filename);
  });

  return found?.document_id || null;
};

// 2026.10.23(woojin.jung) 수정 - 기존 document_id 및 파일명 보완 조회를 공통 사용해 Excel 원본 동작 연결
const resolveSpreadsheetDocumentId = async (citation) => {
  const existingId = getCitationDocumentId(citation);
  if (existingId) return existingId;
  try {
    return await resolveDocumentIdByFilename(citation);
  } catch (error) {
    console.error('원본 Excel 문서 ID 조회 실패:', error);
    return null;
  }
};

const runSpreadsheetAction = async (action, citation) => {
  if (spreadsheetPendingKey.value) return;
  spreadsheetPendingKey.value = `${action}-${citation.citation_id}`;
  try {
    const documentId = await resolveSpreadsheetDocumentId(citation);
    if (!documentId) {
      emit('toast', '원본 Excel 문서 정보를 찾을 수 없습니다.', 'error');
      return;
    }
    if (action === 'view') await spreadsheetViewerRef.value?.open(citation, documentId);
    else await spreadsheetViewerRef.value?.download(citation, documentId);
  } finally {
    spreadsheetPendingKey.value = '';
  }
};

const openSpreadsheet = (citation) => runSpreadsheetAction('view', citation);
const downloadSpreadsheet = (citation) => runSpreadsheetAction('download', citation);

// 2026.05.26(woojin.jung) 추가 - 참고 문서 원본 보기 기능 (새 탭에서 PDF 열기)
// 2026.07.10(sooeyon.choi) 추가 - 매핑된 매뉴얼 citation은 표시용 원본 PDF 파일 열기
const openManualDisplayDocument = async (citation) => {
  const filename = citation?.display_filename;
  const page = Number(citation?.display_page_number) || 1;
  if (!filename) return false;

  const res = await http.get(`/ingest/manual-display/file/${encodeURIComponent(filename)}`, authConfig({ responseType: 'blob' }));
  const blobUrl = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
  window.open(`${blobUrl}#page=${page}`, '_blank', 'noopener,noreferrer');
  window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60000);
  return true;
};

const openOriginalDocument = async (citation) => {
  if (citation?.manual_display_mapped) {
    try {
      if (await openManualDisplayDocument(citation)) return;
    } catch (e) {
      console.error('매뉴얼 표시용 PDF 열기 실패:', e);
      emit('toast', '매뉴얼 표시용 PDF를 열 수 없습니다.', 'error');
      return;
    }
  }

  let documentId = getCitationDocumentId(citation);

  if (!documentId) {
    try {
      documentId = await resolveDocumentIdByFilename(citation);
    } catch (e) {
      console.error('원본 문서 ID 조회 실패:', e);
    }
  }

  if (!documentId) {
    emit('toast', '원본 문서 정보를 찾을 수 없습니다.', 'error');
    return;
  }

  try {
    const res = await http.get(`/ingest/documents/${encodeURIComponent(documentId)}/file`, authConfig({ responseType: 'blob' }));
    const blobUrl = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
    const page = Number(citation.page_number) || 1;
    window.open(`${blobUrl}#page=${page}`, '_blank', 'noopener,noreferrer');
    window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60000);
  } catch (e) {
    console.error('원본 문서 열기 실패:', e);
    emit('toast', '원본 문서를 열 수 없습니다.', 'error');
  }
};

let mediaQuery = null;

onMounted(() => {
  mediaQuery = window.matchMedia(MOBILE_LAYOUT_QUERY);
  checkMobile();
  mediaQuery.addEventListener('change', checkMobile);
});

onUnmounted(() => {
  if (mediaQuery) {
    mediaQuery.removeEventListener('change', checkMobile);
  }
});
</script>

<style scoped>
/* ── Panel base: inline flex child (채팅 옆에 나란히) ── */
.sources-panel {
  width: 0;
  min-width: 0;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  border-left: 0 solid #e5e7eb;
  overflow: hidden;
  flex-shrink: 0;
  transition:
    width 0.3s ease,
    border-left-width 0.3s ease;
}

.sources-panel.is-open {
  width: 380px;
  border-left-width: 1px;
}

/* ── Mobile: bottom sheet (모바일만 fixed overlay 유지) ── */
.sources-panel.is-mobile {
  position: fixed;
  width: 100%;
  top: auto;
  bottom: 0;
  left: 0;
  right: 0;
  max-height: 70vh;
  border-radius: 16px 16px 0 0;
  border-left: none;
  transform: translateY(100%);
  transition: transform 0.3s ease;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.15);
  z-index: 100;
}

.sources-panel.is-mobile.is-open {
  width: 100%;
  transform: translateY(0);
}

/* ── Backdrop ── */
.sp-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 99;
}

/* ── Header ── */
.rp-header {
  height: 60px;
  padding: 0 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e5e7eb;
  background: #ffffff;
  flex-shrink: 0;
}

.rp-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.rp-title {
  font-weight: 600;
  font-size: 0.95rem;
  color: #1e293b;
}

.btn-view-all {
  border: 1px solid #cbd5e1;
  background: white;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  cursor: pointer;
  color: #475569;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn-view-all:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.sp-close-btn {
  background: none;
  border: none;
  font-size: 1rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 6px;
  border-radius: 4px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sp-close-btn:hover {
  background: #f1f5f9;
  color: #475569;
}

.source-context {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 10px;
  padding: 10px 1rem;
  border-bottom: 1px solid #dbeafe;
  background: #eff6ff;
}

.source-context-copy {
  min-width: 0;
  flex: 1;
}

.source-context-label {
  display: block;
  margin-bottom: 3px;
  color: #2563eb;
  font-size: 0.7rem;
  font-weight: 700;
}

.source-context-copy strong {
  display: block;
  overflow: hidden;
  color: #1e3a5f;
  font-size: 0.8rem;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-context-link {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 5px;
  padding: 6px 8px;
  border: 1px solid #93c5fd;
  border-radius: 6px;
  background: #fff;
  color: #1d4ed8;
  font: inherit;
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
}

.source-context-link:hover {
  background: #dbeafe;
}

.sources-panel.is-mobile .source-context {
  padding: 9px 0.75rem;
}

/* 2026.11.04(woojin.jung) 수정 - 하단 시트에서도 "답변으로 이동" 문구가 보이도록(아이콘만 남던 문제) */
.sources-panel.is-mobile .source-context-link {
  min-height: 32px;
  padding: 0 8px;
  white-space: nowrap;
}

/* ── Scrollable content ── */
.rp-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

/* ── Empty state ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #94a3b8;
  text-align: center;
  font-size: 0.9rem;
  padding: 2rem;
}

.empty-state i {
  font-size: 2.5rem;
  margin-bottom: 1rem;
  color: #cbd5e1;
}

/* ── Source card ── */
.source-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  margin-bottom: 1rem;
  cursor: pointer;
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
  overflow: hidden;
}

.source-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.03);
}

.source-card.active {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.source-card.unreferenced {
  opacity: 0.7;
}

/* ── Card header ── */
.sc-header {
  padding: 0.75rem;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid #f1f5f9;
  background: #f8fafc;
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.sc-badge {
  background: #e0f2fe;
  color: #0369a1;
  font-size: 0.7rem;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 700;
  flex-shrink: 0;
}

.sc-filename {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 2026.08.27(sooyeon.choi) 추가 - spreadsheet 원본 위치 */
.sc-location {
  padding: 0 0.75rem 0.5rem;
  color: #64748b;
  font-size: 0.75rem;
}

/* 2026.08.27(sooyeon.choi) 추가 - 단계 8 resource marker 버튼 */
.doc-preview :deep(.sc-resource) {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  margin: 0.25rem 0.25rem 0 0;
  padding: 0.15rem 0.5rem;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #f8fafc;
  color: #0f766e;
  font-size: 0.72rem;
  cursor: pointer;
}

.doc-preview :deep(.sc-resource:hover) {
  background: #ecfeff;
  border-color: #14b8a6;
}

/* ── Doc preview ── */
.doc-preview {
  padding: 0.75rem;
  font-size: 0.8rem;
  line-height: 1.6;
  color: #64748b;
  background: #ffffff;
  word-break: break-word;
}

.doc-preview :deep(table) {
  width: 100%;
  border-collapse: collapse;
}

.doc-preview :deep(th),
.doc-preview :deep(td) {
  padding: 0.35rem 0.5rem;
  border: 1px solid #dbe2ea;
  text-align: left;
}

/* 2026.04.08(sooyeon.choi) 추가 - 쿼리 관련 문장 노란색 하이라이트 */
.doc-preview :deep(.hl) {
  background-color: #fef08a;
  color: #000;
  padding: 0 2px;
  border-radius: 2px;
  font-weight: 500;
}

.sc-images-title {
  padding: 0.15rem 0.75rem 0.45rem;
  color: #64748b;
  font-size: 0.75rem;
  font-weight: 600;
}

.sc-images {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  padding: 0 0.75rem 0.75rem;
}

.sc-image {
  min-width: 0;
  padding: 0;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #fff;
  color: #475569;
  cursor: zoom-in;
  text-align: left;
}

.sc-image:hover {
  border-color: #60a5fa;
}

.sc-image-preview {
  display: block;
  height: 72px;
}

.sc-image > span:last-child {
  display: block;
  padding: 5px 7px 7px;
  overflow: hidden;
  font-size: 0.7rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sc-images-loading {
  padding: 0.4rem 0.75rem 0.75rem;
  color: #94a3b8;
  font-size: 0.72rem;
}

/* 2026.10.23(woojin.jung) 수정 - 참고 문서 카드의 Excel 원본 보기 및 다운로드 버튼 스타일 추가 */
.sc-document-actions {
  display: flex;
  gap: 7px;
  padding: 0.75rem;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}

.sc-document-actions button {
  display: inline-flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 0;
  padding: 0.48rem 0.55rem;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  color: #475569;
  font: inherit;
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
}

.sc-document-actions button.primary {
  border-color: #16a34a;
  color: #15803d;
}

.sc-document-actions button:hover:not(:disabled) {
  border-color: #16a34a;
  background: #f0fdf4;
  color: #15803d;
}

.sc-document-actions button:disabled {
  opacity: 0.55;
  cursor: wait;
}

/* ── Page button ── */
.scroll-to-btn {
  display: block;
  width: 100%;
  text-align: center;
  padding: 6px;
  font-size: 0.75rem;
  color: #3b82f6;
  background: #f0f9ff;
  border: none;
  border-top: 1px solid #e0f2fe;
  cursor: pointer;
  transition: background 0.15s;
}

.scroll-to-btn:hover {
  background: #e0f2fe;
}

/* ── Pulse animation (active card 포커스 시) ── */
@keyframes highlightPulse {
  0% {
    box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4);
  }
  70% {
    box-shadow: 0 0 0 6px rgba(59, 130, 246, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(59, 130, 246, 0);
  }
}

.source-card.active {
  animation: highlightPulse 0.8s ease-out;
}
</style>
