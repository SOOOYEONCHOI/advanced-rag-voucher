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
          <button type="button" class="sheet-download-btn" :disabled="loading || !workbook" @click="downloadCurrent">
            <i :class="downloading ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-download'"></i>
            <span>원본 Excel 다운로드</span>
          </button>
          <button ref="closeButton" type="button" class="sheet-close-btn" aria-label="닫기" @click="close"><span>닫기</span><i class="fa-solid fa-xmark"></i></button>
        </header>

        <div v-if="loading" class="sheet-viewer-status" role="status">
          <i class="fa-solid fa-circle-notch fa-spin"></i>
          <strong>원본 Excel을 불러오는 중...</strong>
          <span>파일 크기에 따라 잠시 시간이 걸릴 수 있습니다.</span>
        </div>
        <div v-else-if="errorMessage" class="sheet-viewer-status error" role="alert">
          <i class="fa-solid fa-file-circle-xmark"></i>
          <strong>{{ errorMessage }}</strong>
          <button type="button" @click="reload"><i class="fa-solid fa-rotate-right"></i> 다시 시도</button>
        </div>

        <template v-else-if="workbook">
          <nav class="sheet-tabs" role="tablist" aria-label="워크시트 목록">
            <button
              v-for="sheetName in workbook.SheetNames"
              :key="sheetName"
              type="button"
              class="sheet-tab"
              :class="{ active: sheetName === activeSheetName }"
              role="tab"
              :aria-selected="sheetName === activeSheetName"
              @click="selectSheet(sheetName)"
            >
              {{ sheetName }}
            </button>
          </nav>

          <div class="sheet-toolbar">
            <div class="sheet-address">{{ selectedAddress }}</div>
            <span class="sheet-formula-label">fx</span>
            <div class="sheet-formula" :title="selectedValue">{{ selectedValue }}</div>
          </div>

          <div ref="gridWrap" class="sheet-grid-wrap">
            <table
              class="sheet-grid"
              :style="{
                '--sheet-font-size': `${0.76 * zoom}rem`,
              }"
              aria-label="Excel 시트 미리보기"
            >
              <colgroup>
                <col class="row-number-column" />
                <col v-for="column in gridColumns" :key="column.index" :style="{ width: `${column.width * zoom}px` }" />
              </colgroup>
              <thead>
                <tr>
                  <th class="corner"></th>
                  <th v-for="column in gridColumns" :key="column.index" scope="col">{{ column.label }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in gridRows" :key="row.index" :style="{ height: `${row.height * zoom}px` }">
                  <th scope="row" class="row-head">{{ row.index + 1 }}</th>
                  <td
                    v-for="cell in row.cells"
                    v-show="!cell.skip"
                    :key="cell.address"
                    :class="cell.classes"
                    :style="cell.style"
                    :rowspan="cell.rowspan"
                    :colspan="cell.colspan"
                    :title="cell.display"
                    @click="selectCell(cell)"
                  >
                    {{ cell.display }}
                    <span v-if="cell.images.length" class="sheet-cell-images" :style="cell.imageStyle">
                      <AuthenticatedImage v-for="image in cell.images" :key="image.resource_id" :resource-id="image.resource_id" :alt="image.title || 'Excel 삽입 이미지'" />
                    </span>
                    <span v-if="cell.isFirstEvidence" class="evidence-label">답변 근거 범위</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <footer class="sheet-viewer-footer">
            <i class="fa-regular fa-circle-info info"></i>
            <span>답변에 사용된 원본 셀 범위를 강조하고 있습니다.</span>
            <div class="sheet-zoom-controls">
              <button type="button" aria-label="축소" :disabled="zoom <= 0.8" @click="changeZoom(-0.1)"><i class="fa-solid fa-minus"></i></button>
              <span>{{ Math.round(zoom * 100) }}%</span>
              <button type="button" aria-label="확대" :disabled="zoom >= 1.4" @click="changeZoom(0.1)"><i class="fa-solid fa-plus"></i></button>
            </div>
          </footer>
        </template>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { chatApi } from '../api/chatApi';
import { createSafeExcelCopy } from '../utils/sanitizeExcelWorkbook';
import AuthenticatedImage from './AuthenticatedImage.vue';

const emit = defineEmits(['toast']);
const isOpen = ref(false);
const loading = ref(false);
const downloading = ref(false);
const errorMessage = ref('');
const workbook = ref(null);
const originalFileData = ref(null);
const originalContentType = ref('');
const sheetResources = ref([]);
const activeSheetName = ref('');
const citation = ref(null);
const documentId = ref('');
const filename = ref('');
const selectedAddress = ref('');
const selectedValue = ref('');
const zoom = ref(1);
const closeButton = ref(null);
const gridWrap = ref(null);
let loadVersion = 0;

const XLSXApi = () => window.XLSX;
const activeSheet = computed(() => workbook.value?.Sheets?.[activeSheetName.value] || null);
const locationLabel = computed(() => [citation.value?.sheet_name, citation.value?.source_range].filter(Boolean).join(' 시트 · ') || '원본 Excel');

const sheetUsedRange = (sheet) => {
  const XLSX = XLSXApi();
  if (!XLSX || !sheet?.['!ref']) return { s: { r: 0, c: 0 }, e: { r: 30, c: 12 } };
  return XLSX.utils.decode_range(sheet['!ref']);
};

const columnWidth = (sheet, column) => {
  const definition = sheet?.['!cols']?.[column];
  return Math.min(320, Math.max(48, Number(definition?.wpx) || (Number(definition?.wch) ? Number(definition.wch) * 7 + 12 : 96)));
};

const rowHeight = (sheet, row) => {
  const definition = sheet?.['!rows']?.[row];
  return Math.min(240, Math.max(24, Number(definition?.hpx) || (Number(definition?.hpt) ? Number(definition.hpt) * (96 / 72) : 31)));
};

const parseResourceCell = (value) => {
  const XLSX = XLSXApi();
  if (!XLSX || !value) return null;
  try {
    return XLSX.utils.decode_cell(String(value).replace(/\$/g, ''));
  } catch {
    return null;
  }
};

// 2026.10.23(woojin.jung) 수정 - 셀 범위와 행 전용 범위를 SheetJS 좌표로 정규화
const citationRange = computed(() => {
  const XLSX = XLSXApi();
  const raw = String(citation.value?.source_range || '')
    .trim()
    .replace(/^.*!/, '')
    .replace(/\$/g, '');
  if (!XLSX || !raw || activeSheetName.value !== citation.value?.sheet_name) return null;
  const used = sheetUsedRange(activeSheet.value);
  const rowOnly = raw.match(/^(\d+)\s*:\s*(\d+)$/);
  if (rowOnly) {
    return {
      s: { r: Math.max(0, Number(rowOnly[1]) - 1), c: used.s.c },
      e: { r: Math.max(0, Number(rowOnly[2]) - 1), c: used.e.c },
    };
  }
  try {
    return XLSX.utils.decode_range(raw);
  } catch {
    return null;
  }
});

const visibleRange = computed(() => {
  const used = sheetUsedRange(activeSheet.value);
  const evidence = citationRange.value;
  if (!evidence) {
    return {
      s: { r: used.s.r, c: used.s.c },
      e: { r: Math.min(used.e.r, used.s.r + 59), c: Math.min(used.e.c, used.s.c + 24) },
    };
  }
  return {
    s: { r: Math.max(0, evidence.s.r - 4), c: Math.max(0, evidence.s.c - 1) },
    e: { r: Math.min(Math.max(used.e.r, evidence.e.r), evidence.e.r + 6), c: Math.min(Math.max(used.e.c, evidence.e.c), evidence.e.c + 2) },
  };
});

const gridColumns = computed(() => {
  const XLSX = XLSXApi();
  if (!XLSX) return [];
  const columns = [];
  for (let column = visibleRange.value.s.c; column <= visibleRange.value.e.c; column += 1) {
    columns.push({ index: column, label: XLSX.utils.encode_col(column), width: columnWidth(activeSheet.value, column) });
  }
  return columns;
});

const isInside = (row, column, range) => Boolean(range && row >= range.s.r && row <= range.e.r && column >= range.s.c && column <= range.e.c);

const cellCssStyle = (cell) => {
  const style = cell?.s;
  if (!style || typeof style !== 'object') return {};
  const colorValue = (color) => (color?.rgb ? `#${String(color.rgb).slice(-6)}` : undefined);
  return {
    backgroundColor: colorValue(style.fill?.fgColor),
    color: colorValue(style.font?.color),
    fontWeight: style.font?.bold ? '700' : undefined,
    fontStyle: style.font?.italic ? 'italic' : undefined,
    textDecoration: style.font?.underline ? 'underline' : undefined,
    textAlign: style.alignment?.horizontal,
    verticalAlign: style.alignment?.vertical === 'center' ? 'middle' : style.alignment?.vertical,
    whiteSpace: style.alignment?.wrapText ? 'normal' : undefined,
  };
};

const activeSheetResources = computed(() =>
  sheetResources.value.filter((resource) => {
    return resource?.displayable === true && resource?.sheet_name === activeSheetName.value && (resource.resource_type === 'image' || String(resource.mime_type || '').startsWith('image/'));
  })
);

const resourcesAtCell = (row, column) =>
  activeSheetResources.value.filter((resource) => {
    const start = parseResourceCell(resource.from_cell);
    return start?.r === row && start?.c === column;
  });

const resourceImageStyle = (images) => {
  if (!images.length) return {};
  const XLSX = XLSXApi();
  const start = parseResourceCell(images[0].from_cell);
  const end = parseResourceCell(images[0].to_cell) || start;
  if (!XLSX || !start || !end) return {};
  let width = 0;
  let height = 0;
  for (let column = start.c; column <= end.c; column += 1) width += columnWidth(activeSheet.value, column);
  for (let row = start.r; row <= end.r; row += 1) height += rowHeight(activeSheet.value, row);
  return { width: `${Math.max(80, width) * zoom.value}px`, height: `${Math.max(60, height) * zoom.value}px` };
};

// 2026.10.23(woojin.jung) 수정 - 원본 셀 값과 답변 근거 범위 경계를 행·열 헤더가 있는 표로 변환
const gridRows = computed(() => {
  const XLSX = XLSXApi();
  const sheet = activeSheet.value;
  if (!XLSX || !sheet) return [];
  const rows = [];
  const evidence = citationRange.value;
  const merges = sheet['!merges'] || [];
  for (let row = visibleRange.value.s.r; row <= visibleRange.value.e.r; row += 1) {
    const cells = [];
    for (let column = visibleRange.value.s.c; column <= visibleRange.value.e.c; column += 1) {
      const merge = merges.find((range) => isInside(row, column, range));
      const clippedMerge = merge
        ? {
            s: { r: Math.max(merge.s.r, visibleRange.value.s.r), c: Math.max(merge.s.c, visibleRange.value.s.c) },
            e: { r: Math.min(merge.e.r, visibleRange.value.e.r), c: Math.min(merge.e.c, visibleRange.value.e.c) },
          }
        : null;
      const skip = Boolean(clippedMerge && (row !== clippedMerge.s.r || column !== clippedMerge.s.c));
      const sourceAddress = XLSX.utils.encode_cell(merge?.s || { r: row, c: column });
      const address = XLSX.utils.encode_cell({ r: row, c: column });
      const sourceCell = sheet[sourceAddress];
      const display = sourceCell ? XLSX.utils.format_cell(sourceCell) : '';
      const footprint = clippedMerge || { s: { r: row, c: column }, e: { r: row, c: column } };
      const highlighted = Boolean(evidence && footprint.e.r >= evidence.s.r && footprint.s.r <= evidence.e.r && footprint.e.c >= evidence.s.c && footprint.s.c <= evidence.e.c);
      const classes = {
        'answer-range': highlighted,
        'answer-top': highlighted && footprint.s.r <= evidence.s.r,
        'answer-bottom': highlighted && footprint.e.r >= evidence.e.r,
        'answer-left': highlighted && footprint.s.c <= evidence.s.c,
        'answer-right': highlighted && footprint.e.c >= evidence.e.c,
        selected: selectedAddress.value === address,
      };
      const images = skip ? [] : resourcesAtCell(row, column);
      cells.push({
        address,
        display,
        formula: sourceCell?.f ? `=${sourceCell.f}` : display,
        classes,
        style: cellCssStyle(sourceCell),
        skip,
        rowspan: clippedMerge && !skip ? clippedMerge.e.r - clippedMerge.s.r + 1 : 1,
        colspan: clippedMerge && !skip ? clippedMerge.e.c - clippedMerge.s.c + 1 : 1,
        images,
        imageStyle: resourceImageStyle(images),
        isFirstEvidence: highlighted && row === evidence.s.r && column === evidence.s.c,
      });
    }
    rows.push({ index: row, height: rowHeight(sheet, row), cells });
  }
  return rows;
});

const selectCell = (cell) => {
  selectedAddress.value = cell.address;
  selectedValue.value = cell.formula;
};

const resetSelection = () => {
  selectedAddress.value = citationRange.value ? `${XLSXApi().utils.encode_range(citationRange.value)}` : activeSheet.value?.['!ref'] || 'A1';
  selectedValue.value = activeSheetName.value === citation.value?.sheet_name ? [citation.value?.sheet_name, citation.value?.source_range].filter(Boolean).join('!') : activeSheetName.value;
};

const selectSheet = async (sheetName) => {
  activeSheetName.value = sheetName;
  resetSelection();
  await nextTick();
  if (gridWrap.value) {
    gridWrap.value.scrollTop = 0;
    gridWrap.value.scrollLeft = 0;
  }
};

// 2026.10.23(woojin.jung) 수정 - 인증된 원본 Excel과 삽입 이미지 메타데이터를 함께 조회하고 셀 스타일을 포함해 파싱
const loadWorkbook = async (targetDocumentId) => {
  const XLSX = XLSXApi();
  if (!XLSX) throw new Error('SheetJS를 불러오지 못했습니다. 페이지를 새로고침해 주세요.');
  const [response, resourceResponse] = await Promise.all([
    chatApi.spreadsheetDocumentFile(targetDocumentId),
    chatApi.documentSpreadsheetResources(targetDocumentId).catch((error) => {
      console.warn('Excel 삽입 이미지 메타데이터 조회 실패:', error);
      return null;
    }),
  ]);
  return {
    workbook: XLSX.read(response.data, { type: 'array', cellDates: true, cellStyles: true }),
    originalFileData: response.data,
    contentType: response.headers?.['content-type'] || '',
    resources: resourceResponse?.data?.resources || [],
  };
};

const loadCurrent = async () => {
  const version = ++loadVersion;
  loading.value = true;
  errorMessage.value = '';
  workbook.value = null;
  originalFileData.value = null;
  originalContentType.value = '';
  sheetResources.value = [];
  try {
    const loaded = await loadWorkbook(documentId.value);
    if (version !== loadVersion) return;
    workbook.value = loaded.workbook;
    originalFileData.value = loaded.originalFileData;
    originalContentType.value = loaded.contentType;
    sheetResources.value = loaded.resources;
    activeSheetName.value = loaded.workbook.SheetNames.includes(citation.value?.sheet_name) ? citation.value.sheet_name : loaded.workbook.SheetNames[0] || '';
    resetSelection();
  } catch (error) {
    if (version !== loadVersion) return;
    console.error('원본 Excel 조회 실패:', error);
    errorMessage.value = error.response?.status === 403 ? '원본 Excel 열람 권한이 없습니다.' : '원본 Excel을 불러올 수 없습니다.';
  } finally {
    if (version === loadVersion) loading.value = false;
  }
};

const open = async (targetCitation, targetDocumentId) => {
  citation.value = targetCitation;
  documentId.value = targetDocumentId;
  filename.value = targetCitation?.original_filename || targetCitation?.document_name || '원본 문서.xlsx';
  zoom.value = 1;
  isOpen.value = true;
  document.body.classList.add('sheet-viewer-open');
  await nextTick();
  closeButton.value?.focus();
  await loadCurrent();
};

const close = () => {
  isOpen.value = false;
  loadVersion += 1;
  document.body.classList.remove('sheet-viewer-open');
};

const reload = () => loadCurrent();

const excelMimeType = (targetFilename) => {
  const extension = String(targetFilename || '')
    .split('.')
    .pop()
    ?.toLowerCase();
  if (extension === 'xls') return 'application/vnd.ms-excel';
  if (extension === 'xlsm') return 'application/vnd.ms-excel.sheet.macroEnabled.12';
  return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
};

// 2026.10.23(woojin.jung) 수정 - 원본 이름과 그림·서식은 보존하고 외부 통합 문서 연결만 제거한 안전한 사본 다운로드
const downloadWorkbook = async (targetCitation, targetDocumentId) => {
  if (downloading.value) return;
  downloading.value = true;
  try {
    const targetFilename = targetCitation?.original_filename || targetCitation?.document_name || '원본 문서.xlsx';
    let fileData = documentId.value === targetDocumentId ? originalFileData.value : null;
    let contentType = documentId.value === targetDocumentId ? originalContentType.value : '';
    if (!fileData) {
      const response = await chatApi.spreadsheetDocumentFile(targetDocumentId);
      fileData = response.data;
      contentType = response.headers?.['content-type'] || '';
    }
    const safeFileData = await createSafeExcelCopy(fileData, targetFilename);
    const blob = new Blob([safeFileData], { type: contentType || excelMimeType(targetFilename) });
    const blobUrl = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = blobUrl;
    anchor.download = targetFilename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000);
  } catch (error) {
    console.error('원본 Excel 다운로드 실패:', error);
    const message =
      error.message === 'SAFE_COPY_UNSUPPORTED_FORMAT'
        ? '안전한 사본 다운로드는 XLSX·XLSM 형식만 지원합니다.'
        : error.response?.status === 403
          ? '원본 Excel 다운로드 권한이 없습니다.'
          : '안전한 Excel 사본을 생성할 수 없습니다.';
    emit('toast', message, 'error');
  } finally {
    downloading.value = false;
  }
};

const downloadCurrent = () => downloadWorkbook(citation.value, documentId.value);
const changeZoom = (amount) => {
  zoom.value = Math.min(1.4, Math.max(0.8, Number((zoom.value + amount).toFixed(1))));
};

const onKeydown = (event) => {
  if (isOpen.value && event.key === 'Escape') close();
};

defineExpose({ open, download: downloadWorkbook });
onMounted(() => document.addEventListener('keydown', onKeydown));
onBeforeUnmount(() => {
  loadVersion += 1;
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
  width: min(1060px, 96vw);
  height: min(810px, 92vh);
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
.sheet-tabs {
  display: flex;
  min-height: 48px;
  overflow-x: auto;
  border-bottom: 1px solid #e2e8f0;
}
.sheet-tab {
  position: relative;
  min-width: 145px;
  padding: 0 1.2rem;
  border: 0;
  border-right: 1px solid #e2e8f0;
  background: transparent;
  color: #64748b;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
}
.sheet-tab.active {
  color: #15803d;
}
.sheet-tab.active::after {
  content: '';
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 3px;
  background: #16a34a;
}
.sheet-toolbar {
  display: flex;
  min-height: 48px;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  border-bottom: 1px solid #dbe2ea;
  background: #f8fafc;
}
.sheet-address {
  min-width: 126px;
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 5px;
  background: #fff;
  color: #0f172a;
  font-size: 0.78rem;
  font-weight: 600;
}
.sheet-formula-label {
  color: #64748b;
  font-family: Georgia, serif;
  font-style: italic;
}
.sheet-formula {
  flex: 1;
  min-width: 0;
  padding: 6px 10px;
  overflow: hidden;
  border: 1px solid #dbe2ea;
  border-radius: 4px;
  background: #fff;
  color: #64748b;
  font-size: 0.78rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sheet-grid-wrap {
  flex: 1;
  min-height: 0;
  padding: 12px;
  overflow: auto;
  background: #eef2f7;
}
.sheet-grid {
  width: max-content;
  min-width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  table-layout: fixed;
  background: #fff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}
.sheet-grid .row-number-column {
  width: 42px;
}
.sheet-grid th,
.sheet-grid td {
  min-width: 0;
  padding: 5px 8px;
  overflow: hidden;
  border-right: 1px solid #dbe2ea;
  border-bottom: 1px solid #dbe2ea;
  color: #334155;
  font-size: var(--sheet-font-size);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sheet-grid thead th,
.sheet-grid .row-head {
  position: sticky;
  z-index: 6;
  min-width: 42px;
  width: 42px;
  background: #f1f5f9;
  color: #475569;
  font-weight: 500;
  text-align: center;
}
.sheet-grid thead th {
  top: 0;
  height: 31px;
}
.sheet-grid .row-head {
  left: 0;
}
.sheet-grid .corner {
  z-index: 7;
  left: 0;
}
.sheet-grid td {
  position: relative;
  cursor: cell;
}
.sheet-grid td:hover {
  outline: 1px solid #93c5fd;
  outline-offset: -1px;
}
.sheet-grid td.selected {
  outline: 2px solid #2563eb;
  outline-offset: -2px;
}
.sheet-grid td.answer-range {
  overflow: visible;
  background: #fefce8;
  border-color: #bbf7d0;
}
.sheet-grid td.answer-top {
  border-top: 2px solid #16a34a;
}
.sheet-grid td.answer-bottom {
  border-bottom: 2px solid #16a34a;
}
.sheet-grid td.answer-left {
  border-left: 2px solid #16a34a;
}
.sheet-grid td.answer-right {
  border-right: 2px solid #16a34a;
}
.evidence-label {
  position: absolute;
  z-index: 4;
  top: -35px;
  left: calc(100% + 10px);
  width: max-content;
  padding: 5px 9px;
  border-radius: 6px;
  background: #15803d;
  color: #fff;
  font-size: 0.7rem;
  font-weight: 600;
  box-shadow: 0 3px 8px rgba(21, 128, 61, 0.25);
  pointer-events: none;
}
/* 2026.10.23(woojin.jung) 수정 - 백엔드가 추출한 Excel 삽입 이미지를 원본 셀 범위 크기에 맞춰 시트 위에 배치 */
.sheet-cell-images {
  position: absolute;
  z-index: 3;
  top: 0;
  left: 0;
  display: flex;
  overflow: hidden;
  background: #fff;
  pointer-events: none;
}
.sheet-cell-images > * {
  flex: 1 1 0;
  min-width: 0;
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
.sheet-zoom-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}
.sheet-zoom-controls button {
  width: 32px;
  height: 32px;
  border: 1px solid #dbe2ea;
  border-radius: 5px;
  background: #fff;
  color: #475569;
  cursor: pointer;
}
.sheet-zoom-controls button:disabled {
  opacity: 0.4;
}
.sheet-zoom-controls span {
  width: 46px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
@media (max-width: 640px) {
  .sheet-viewer-overlay {
    padding: 8px;
  }
  .sheet-viewer {
    width: 100%;
    height: 96vh;
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
  .sheet-tab {
    min-width: 120px;
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
