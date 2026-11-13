<template>
  <!-- 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - 도면 처리 결과·검수 대화상자(바깥 클릭으로 닫지 않음, Esc 닫기, 포커스 가둠) -->
  <div v-if="target" class="dialog-overlay" @keydown="onKeydown">
    <div v-focus class="dialog-box drawing-dialog" role="dialog" aria-modal="true" aria-labelledby="drawingResultTitle" tabindex="-1" :inert="confirmOpen || viewerOpen">
      <div class="drawing-head">
        <div>
          <div id="drawingResultTitle" class="dialog-title"><i class="fa-solid fa-compass-drafting" style="color: #0f766e"></i>도면 처리 결과</div>
          <p v-if="result" class="drawing-sub">
            {{ result.product_model || '-' }} · {{ result.filename }} · v{{ result.version_no }}<template v-if="result.uploaded_by"> · 업로더 {{ result.uploaded_by }}</template>
          </p>
        </div>
        <button type="button" class="drawing-close" aria-label="도면 처리 결과 닫기" @click="$emit('close')"><i class="fa-solid fa-xmark"></i></button>
      </div>

      <p v-if="loading" class="drawing-state"><i class="fa-solid fa-spinner fa-spin"></i> 처리 결과를 불러오는 중입니다.</p>
      <p v-else-if="loadError" class="drawing-state error" role="alert">{{ loadError }}</p>

      <template v-else-if="result">
        <div v-if="missingLabels.length" class="drawing-banner warn" role="status">
          <i class="fa-solid fa-triangle-exclamation"></i>
          <span>표제란 필수 항목(<strong>{{ missingLabels.join('·') }}</strong>)을 찾지 못했습니다. 원본 도면을 확인한 뒤 검수 완료로 기록해 주세요. 값 수정은 지원하지 않습니다.</span>
        </div>
        <div v-else-if="reviewed" class="drawing-banner ok" role="status">
          <i class="fa-solid fa-circle-check"></i>
          <span>검수 완료 · {{ result.review.reviewer || '-' }} · {{ result.review.reviewed_at || '-' }}</span>
        </div>

        <div class="drawing-tabs" role="tablist">
          <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" class="drawing-tab" :class="{ active: activeTab === tab.key }" :aria-selected="activeTab === tab.key" @click="activeTab = tab.key">
            {{ tab.label }}
          </button>
        </div>

        <div class="drawing-body">
          <!-- 요약 -->
          <div v-if="activeTab === 'summary'" class="summary-grid">
            <div>
              <button v-if="previewImageId" type="button" class="thumb-main" aria-label="전체 도면 크게 보기" @click="openViewer(fullImageId || previewImageId, '전체 도면')">
                <AuthenticatedImage :resource-id="previewImageId" alt="전체 도면" />
              </button>
              <p v-else class="empty-note">도면 이미지를 만들지 못했습니다. 경고·정보 탭을 확인하세요.</p>
              <div v-if="cropList.length" class="thumb-row">
                <button v-for="crop in cropList" :key="crop.region" type="button" class="thumb-crop" @click="openViewer(crop.id, crop.label)">
                  <AuthenticatedImage :resource-id="crop.id" :alt="crop.label" />
                  <span>{{ crop.label }}</span>
                </button>
              </div>
            </div>
            <div>
              <h4 class="sec-title first">표제란</h4>
              <table class="kv">
                <tbody>
                  <tr v-for="row in titleRows" :key="row.label">
                    <th>{{ row.label }}</th>
                    <td :class="{ missing: row.missing, mono: row.mono }">{{ row.missing ? '미검출' : row.value || '-' }}</td>
                  </tr>
                </tbody>
              </table>
              <h4 class="sec-title">검색에 쓸 정보(다음 단계)</h4>
              <p class="drawing-hint">품번·품명·개정·재질·사양·도면 종류·부품표 품번 {{ bomPartCount }}개를 저장했습니다. 검수한 도면은 다음 단계에서 검색에 적용하면 챗봇 답변에서 볼 수 있습니다.</p>
            </div>
          </div>

          <!-- 부품표 -->
          <template v-else-if="activeTab === 'bom'">
            <template v-if="bomTable">
              <div class="tab-tools">
                <span class="drawing-hint">{{ bomTable.rows.length }}행</span>
                <button v-if="cropIds.bom" type="button" class="btn-text-link" @click="openViewer(cropIds.bom, '부품표')"><i class="fa-solid fa-magnifying-glass-plus"></i> 원본 영역 보기</button>
              </div>
              <div class="table-wrap">
                <table class="grid-table">
                  <thead>
                    <tr><th v-for="col in bomTable.columns" :key="col">{{ columnLabel(col) }}</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, i) in bomTable.rows" :key="i"><td v-for="col in bomTable.columns" :key="col" :class="{ mono: col === 'part_no' }">{{ row[col] || '' }}</td></tr>
                  </tbody>
                </table>
              </div>
            </template>
            <p v-else class="empty-note">부품표가 없는 도면(가공품)입니다.</p>
          </template>

          <!-- 개정이력 -->
          <template v-else-if="activeTab === 'revision'">
            <template v-if="revisionTable && revisionTable.rows.length">
              <div class="tab-tools">
                <span class="drawing-hint">{{ revisionTable.rows.length }}행</span>
                <button v-if="cropIds.revision" type="button" class="btn-text-link" @click="openViewer(cropIds.revision, '개정이력')"><i class="fa-solid fa-magnifying-glass-plus"></i> 원본 영역 보기</button>
              </div>
              <div class="table-wrap">
                <table class="grid-table">
                  <thead>
                    <tr><th v-for="col in revisionTable.columns" :key="col">{{ columnLabel(col, 'revision') }}</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, i) in revisionTable.rows" :key="i"><td v-for="col in revisionTable.columns" :key="col">{{ row[col] || '' }}</td></tr>
                  </tbody>
                </table>
              </div>
            </template>
            <p v-else class="empty-note">개정 이력이 비어 있습니다.</p>
          </template>

          <!-- 주기 -->
          <template v-else-if="activeTab === 'notes'">
            <h4 class="sec-title first">주기</h4>
            <ol v-if="result.notes.items?.length" class="note-list">
              <li v-for="(item, i) in result.notes.items" :key="i">{{ item }}</li>
            </ol>
            <p v-else class="empty-note">주기를 찾지 못했습니다.</p>
            <h4 class="sec-title">일반공차 규격</h4>
            <p class="drawing-text">{{ result.notes.general_tolerance || '-' }}</p>
            <template v-if="result.notes.spec_memos?.length">
              <h4 class="sec-title">규격 메모</h4>
              <p v-for="(memo, i) in result.notes.spec_memos" :key="i" class="drawing-text">{{ memo }}</p>
            </template>
            <h4 class="sec-title">치수 {{ result.dimension_count }}개</h4>
            <p class="drawing-text dims">{{ result.dimensions.map((d) => d.text).join(' · ') || '-' }}</p>
            <template v-if="result.misc_texts?.length">
              <h4 class="sec-title">기타 글자</h4>
              <p class="drawing-text">{{ result.misc_texts.join(' · ') }}</p>
            </template>
          </template>

          <!-- 경고·정보 -->
          <template v-else-if="activeTab === 'warnings'">
            <div v-for="group in warningGroups" :key="group.level" class="warn-group">
              <h4>
                <i :class="group.level === 'warn' ? 'fa-solid fa-triangle-exclamation warn-icon' : 'fa-solid fa-circle-info info-icon'"></i>
                {{ group.title }} {{ group.items.length }}
              </h4>
              <div v-for="(w, i) in group.items" :key="i" class="warn-item">
                <code>{{ w.code }}</code>
                <span>{{ w.message }}</span>
                <span class="warn-count">{{ w.count ?? '' }}</span>
              </div>
              <p v-if="!group.items.length" class="warn-empty">{{ group.empty }}</p>
            </div>
          </template>

          <!-- 처리 정보 -->
          <template v-else>
            <table class="kv">
              <tbody>
                <tr><th>원본 형식</th><td>{{ result.processing.source.format || '-' }} {{ result.processing.source.release || result.processing.source.acadver || '' }}</td></tr>
                <tr><th>변환기</th><td>{{ converterLabel }}</td></tr>
                <tr><th>표제란 방식</th><td>{{ result.title_block.method || '-' }}</td></tr>
                <tr><th>용지 · 축척</th><td>{{ result.sheet.size || '미판정' }} · {{ result.title_block.fields?.scale || '-' }}</td></tr>
                <tr><th>엔티티 · 글자</th><td>{{ result.processing.stats.entity_count ?? '-' }} · {{ result.processing.stats.text_count ?? '-' }}</td></tr>
                <tr><th>소요 시간</th><td>{{ timingLabel }}</td></tr>
                <tr><th>확인용 md</th><td class="mono">{{ result.processing.md_dir || '-' }}</td></tr>
                <tr><th>검색 데이터</th><td>저장하지 않음(검색 미적용)</td></tr>
              </tbody>
            </table>
          </template>
        </div>
      </template>

      <div class="dialog-actions">
        <button type="button" class="btn-search-disabled" disabled title="검수한 도면은 다음 단계에서 검색에 적용됩니다."><i class="fa-solid fa-magnifying-glass"></i> 검색 적용 <small>다음 단계</small></button>
        <span class="actions-gap"></span>
        <button
          v-if="result"
          type="button"
          :class="reviewed ? 'btn-cancel' : 'btn-review'"
          :disabled="!result.can_review || reviewing"
          :title="result.can_review ? '' : '업로드한 본인 또는 관리자만 현재 버전을 검수할 수 있습니다.'"
          @click="onReviewClick"
        >
          <i v-if="reviewing" class="fa-solid fa-spinner fa-spin"></i>
          <i v-else :class="reviewed ? 'fa-solid fa-rotate-left' : 'fa-solid fa-check'"></i>
          {{ reviewed ? '검수 취소' : '검수 완료' }}
        </button>
        <button type="button" class="btn-cancel" @click="$emit('close')">닫기</button>
      </div>
    </div>

    <!-- 필수 항목 누락 확인 -->
    <div v-if="confirmOpen" class="dialog-overlay nested" @keydown="onConfirmKeydown">
      <div v-focus class="dialog-box confirm-box" role="alertdialog" aria-modal="true" aria-labelledby="drawingConfirmTitle" tabindex="-1">
        <div id="drawingConfirmTitle" class="dialog-title"><i class="fa-solid fa-triangle-exclamation" style="color: #f97316"></i>필수 항목 확인</div>
        <p class="drawing-hint">
          필수 항목(<strong>{{ missingLabels.join('·') }}</strong>)이 비어 있습니다.<br />원본 도면을 확인했으면 검수 완료로 기록합니다. 비어 있는 값은 그대로 저장됩니다.
        </p>
        <div class="dialog-actions plain">
          <button type="button" class="btn-cancel" @click="confirmOpen = false">취소</button>
          <button type="button" class="btn-review" :disabled="reviewing" @click="submitReview(true)">원본 확인함 · 검수 완료</button>
        </div>
      </div>
    </div>

    <ImageViewer :open="viewerOpen" :images="viewerImages" :index="0" @close="viewerOpen = false" @toast="(m, t) => $emit('toast', m, t)" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { adminApi } from '../api/adminApi';
import { handleDialogKeydown } from '../utils/dialogKeydown';
import AuthenticatedImage from './AuthenticatedImage.vue';
import ImageViewer from './ImageViewer.vue';

const props = defineProps({
  // { documentId, versionNo }
  target: { type: Object, default: null },
});
const emit = defineEmits(['close', 'toast', 'reviewed']);
const vFocus = { mounted: (el) => el.focus() };

const TITLE_FIELDS = [
  ['part_no', '품번', true],
  ['part_name', '품명'],
  ['revision', '개정'],
  ['date', '날짜'],
  ['scale', '축척'],
  ['material', '재질'],
  ['material_group', '재질 그룹'],
  ['after_treatment', '후처리'],
  ['part_spec', 'PART SPEC'],
  ['drawn', '작성'],
  ['checked', '검토'],
  ['approved', '승인'],
];
const REQUIRED = { part_no: '품번', part_name: '품명', revision: '개정' };
const COLUMN_LABELS = {
  item_no: '번호', revision: 'REV', part_no: '품번', part_name: '품명', qty: '수량', material: '재질',
  material_group: '재질 그룹', part_spec: '사양', after_treatment: '후처리',
};
const REVISION_LABELS = { rev: '개정', description: '내용', date: '날짜', drawn: '작성', checked: '검토' };
const CROP_LABELS = { title_block: '표제란', bom: '부품표', revision: '개정이력', notes: '주기' };

const result = ref(null);
const loading = ref(false);
const loadError = ref('');
const activeTab = ref('summary');
const reviewing = ref(false);
const confirmOpen = ref(false);
const viewerOpen = ref(false);
const viewerImages = ref([]);

const errorText = (error) => {
  const detail = error.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return detail?.message || error.message || '요청 처리에 실패했습니다.';
};

const load = async () => {
  if (!props.target) return;
  loading.value = true;
  loadError.value = '';
  result.value = null;
  activeTab.value = 'summary';
  try {
    const response = await adminApi.drawingResult(props.target.documentId, props.target.versionNo);
    result.value = response.data;
  } catch (error) {
    loadError.value = errorText(error);
  } finally {
    loading.value = false;
  }
};
watch(() => props.target, load, { immediate: true });

const reviewed = computed(() => result.value?.review?.status === 'reviewed');
const fields = computed(() => result.value?.title_block?.fields || {});
const missingLabels = computed(() => (result.value?.summary?.missing_fields || []).map((key) => REQUIRED[key] || key));
const titleRows = computed(() =>
  TITLE_FIELDS.map(([key, label, mono]) => ({
    label,
    value: key === 'revision' && fields.value.rev_iter ? `${fields.value.revision} (개정 ${fields.value.rev_major} · 반복 ${fields.value.rev_iter})` : fields.value[key],
    missing: Boolean(REQUIRED[key]) && !fields.value[key],
    mono,
  })).concat([{ label: '도면 종류', value: result.value?.metadata?.drawing_kind === 'assembly' ? '조립도(부품표 있음)' : '가공품' }]),
);
const bomTable = computed(() => result.value?.tables?.find((t) => t.kind === 'bom') || null);
const revisionTable = computed(() => result.value?.tables?.find((t) => t.kind === 'revision') || null);
const bomPartCount = computed(() => result.value?.metadata?.bom_part_nos?.length || 0);
const images = computed(() => result.value?.images || {});
const previewImageId = computed(() => images.value.preview || images.value.full || '');
const fullImageId = computed(() => images.value.full || '');
const cropIds = computed(() => images.value.crops || {});
const cropList = computed(() =>
  Object.entries(cropIds.value).map(([region, id]) => ({ region, id, label: CROP_LABELS[region] || region })),
);
const warningGroups = computed(() => {
  const list = result.value?.warnings || [];
  return [
    { level: 'warn', title: '경고 — 확인 필요', items: list.filter((w) => w.level === 'warn'), empty: '확인이 필요한 항목이 없습니다.' },
    { level: 'info', title: '정보 — 자동 조치됨', items: list.filter((w) => w.level !== 'warn'), empty: '없음' },
  ];
});
const tabs = computed(() => {
  const warn = warningGroups.value[0].items.length;
  const info = warningGroups.value[1].items.length;
  return [
    { key: 'summary', label: '요약' },
    { key: 'bom', label: '부품표' },
    { key: 'revision', label: '개정이력' },
    { key: 'notes', label: '주기·치수' },
    { key: 'warnings', label: `경고·정보 ${warn}+${info}` },
    { key: 'processing', label: '처리 정보' },
  ];
});
const converterLabel = computed(() => {
  const conv = result.value?.processing?.source?.converter || {};
  if (!conv.name) return '변환 없음(DXF)';
  return [conv.name, conv.version, conv.sanitize_fixes ? `보정 ${conv.sanitize_fixes}건` : ''].filter(Boolean).join(' · ');
});
const timingLabel = computed(() => {
  const t = result.value?.processing?.timings || {};
  const sec = (ms) => (ms == null ? '-' : `${(ms / 1000).toFixed(1)} s`);
  return `변환 ${sec(t.convert_ms)} · 추출 ${sec(t.extract_ms)} · 이미지 ${sec(t.render_ms)}`;
});

const columnLabel = (col, kind) => (kind === 'revision' ? REVISION_LABELS[col] : COLUMN_LABELS[col]) || col;

const openViewer = (resourceId, title) => {
  if (!resourceId) return;
  viewerImages.value = [{ resource_id: resourceId, title, original_filename: result.value?.filename }];
  viewerOpen.value = true;
};

const submitReview = async (confirmMissing = false) => {
  if (!result.value || reviewing.value) return;
  reviewing.value = true;
  try {
    const { documentId, versionNo } = props.target;
    const response = reviewed.value
      ? await adminApi.cancelDrawingReview(documentId, versionNo)
      : await adminApi.reviewDrawing(documentId, versionNo, confirmMissing);
    result.value = { ...result.value, review: response.data.review };
    confirmOpen.value = false;
    emit('toast', reviewed.value ? '검수 완료로 기록했습니다.' : '검수를 취소했습니다.', 'success');
    emit('reviewed');
  } catch (error) {
    emit('toast', errorText(error), 'error');
  } finally {
    reviewing.value = false;
  }
};

const onReviewClick = () => {
  if (!reviewed.value && missingLabels.value.length) {
    confirmOpen.value = true;
    return;
  }
  submitReview(false);
};

const onKeydown = (event) => {
  if (confirmOpen.value || viewerOpen.value) return;
  handleDialogKeydown(event, () => emit('close'));
};
const onConfirmKeydown = (event) => handleDialogKeydown(event, () => (confirmOpen.value = false));
</script>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(15, 23, 42, 0.45);
}
.dialog-overlay.nested {
  z-index: 1010;
}
.dialog-box {
  display: flex;
  flex-direction: column;
  width: min(1040px, 100%);
  max-height: calc(100vh - 32px);
  background: white;
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.25);
}
.confirm-box {
  width: min(460px, 100%);
  padding: 1.4rem;
}
.drawing-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 1.2rem 1.4rem 0.6rem;
}
.dialog-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.02rem;
  font-weight: 700;
  color: #1e293b;
}
.drawing-sub {
  margin: 0.3rem 0 0;
  font-size: 0.8rem;
  color: #64748b;
}
.drawing-close {
  border: none;
  background: none;
  color: #94a3b8;
  font-size: 1.1rem;
  cursor: pointer;
}
.drawing-state {
  padding: 2rem 1.4rem;
  color: #64748b;
  font-size: 0.88rem;
}
.drawing-state.error {
  color: #dc2626;
}
.drawing-banner {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
  margin: 0 1.4rem 0.6rem;
  padding: 0.6rem 0.8rem;
  border-radius: 8px;
  font-size: 0.82rem;
  line-height: 1.5;
}
.drawing-banner.warn {
  background: #fff7ed;
  color: #9a3412;
  border: 1px solid #fed7aa;
}
.drawing-banner.ok {
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}
.drawing-tabs {
  display: flex;
  gap: 0.2rem;
  padding: 0 1.4rem;
  border-bottom: 1px solid #e2e8f0;
  overflow-x: auto;
}
.drawing-tab {
  padding: 0.6rem 0.8rem;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  color: #64748b;
  font-size: 0.84rem;
  white-space: nowrap;
  cursor: pointer;
}
.drawing-tab.active {
  color: #2563eb;
  border-bottom-color: #2563eb;
  font-weight: 700;
}
.drawing-body {
  flex: 1;
  padding: 1.1rem 1.4rem;
  overflow: auto;
}
.summary-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  gap: 1.25rem;
}
.thumb-main {
  display: block;
  width: 100%;
  padding: 0;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: white;
  cursor: zoom-in;
  overflow: hidden;
}
.thumb-main :deep(img) {
  display: block;
  width: 100%;
  height: auto;
}
.thumb-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.thumb-crop {
  padding: 4px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: white;
  text-align: left;
  cursor: zoom-in;
}
.thumb-crop :deep(img) {
  display: block;
  width: 100%;
  height: 70px;
  object-fit: contain;
}
.thumb-crop span {
  display: block;
  margin-top: 2px;
  font-size: 0.72rem;
  color: #64748b;
}
.sec-title {
  margin: 1rem 0 0.4rem;
  font-size: 0.82rem;
  font-weight: 700;
  color: #334155;
}
.sec-title.first {
  margin-top: 0;
}
.kv {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}
.kv th {
  width: 110px;
  padding: 0.38rem 0.5rem;
  border-bottom: 1px solid #f1f5f9;
  color: #64748b;
  font-weight: 500;
  text-align: left;
  vertical-align: top;
}
.kv td {
  padding: 0.38rem 0.5rem;
  border-bottom: 1px solid #f1f5f9;
  color: #1e293b;
  word-break: break-all;
}
.kv td.missing {
  color: #dc2626;
  font-weight: 600;
}
.mono {
  font-family: Consolas, monospace;
}
.drawing-hint,
.drawing-text {
  margin: 0;
  color: #64748b;
  font-size: 0.82rem;
  line-height: 1.55;
}
.drawing-text {
  color: #1e293b;
}
.drawing-text.dims {
  word-break: break-all;
}
.tab-tools {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.btn-text-link {
  border: none;
  background: none;
  color: #2563eb;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}
.table-wrap {
  overflow-x: auto;
}
.grid-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.grid-table th {
  padding: 0.45rem 0.55rem;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
  text-align: left;
  white-space: nowrap;
}
.grid-table td {
  padding: 0.45rem 0.55rem;
  border: 1px solid #e2e8f0;
}
.empty-note {
  margin: 0;
  padding: 1rem;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
  font-size: 0.84rem;
  text-align: center;
}
.note-list {
  margin: 0;
  padding-left: 1.2rem;
  font-size: 0.84rem;
  line-height: 1.8;
}
.warn-group {
  margin-bottom: 0.8rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}
.warn-group h4 {
  margin: 0;
  padding: 0.55rem 0.8rem;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  font-size: 0.82rem;
}
.warn-icon {
  color: #dc2626;
}
.info-icon {
  color: #2563eb;
}
.warn-item {
  display: grid;
  grid-template-columns: 170px 1fr 60px;
  gap: 0.75rem;
  padding: 0.55rem 0.8rem;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.8rem;
}
.warn-item:last-child {
  border-bottom: none;
}
.warn-item code {
  font-size: 0.74rem;
  color: #475569;
}
.warn-count {
  color: #64748b;
}
.warn-empty {
  margin: 0;
  padding: 0.55rem 0.8rem;
  color: #94a3b8;
  font-size: 0.8rem;
}
.dialog-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 0.9rem 1.4rem;
  border-top: 1px solid #e2e8f0;
}
.dialog-actions.plain {
  padding: 0.6rem 0 0;
  border-top: none;
}
.actions-gap {
  flex: 1;
}
.btn-cancel,
.btn-review,
.btn-search-disabled {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.55rem 1rem;
  border-radius: 8px;
  font-size: 0.84rem;
  cursor: pointer;
}
.btn-cancel {
  border: 1px solid #d1d5db;
  background: white;
  color: #374151;
}
.btn-review {
  border: none;
  background: #16a34a;
  color: white;
  font-weight: 600;
}
.btn-review:disabled,
.btn-cancel:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-search-disabled {
  border: 1px dashed #cbd5e1;
  background: #f8fafc;
  color: #94a3b8;
  cursor: not-allowed;
}
.btn-search-disabled small {
  font-size: 0.7rem;
}
@media (max-width: 768px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
  .warn-item {
    grid-template-columns: 1fr;
  }
}
</style>
