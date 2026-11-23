<template>
  <div class="drawing-dialog-overlay" @keydown="onKeydown">
    <section ref="dialogRef" class="drawing-dialog" role="dialog" aria-modal="true" aria-labelledby="drawingResultTitle" tabindex="-1">
      <header class="drawing-dialog-head">
        <div>
          <h2 id="drawingResultTitle"><i class="fa-solid fa-compass-drafting"></i> 도면 처리 결과</h2>
          <p v-if="result">{{ result.product_model || document.product_model || '-' }} · {{ result.filename || document.filename }} · v{{ result.version_no ?? document.version_no ?? 1 }}</p>
        </div>
        <button class="icon-button" type="button" aria-label="도면 처리 결과 닫기" @click="close"><i class="fa-solid fa-xmark"></i></button>
      </header>

      <div v-if="loading" class="drawing-state"><i class="fa-solid fa-circle-notch fa-spin"></i> 처리 결과를 불러오는 중입니다.</div>
      <div v-else-if="loadError" class="drawing-state error"><i class="fa-solid fa-circle-exclamation"></i> {{ loadError }}</div>
      <template v-else-if="result">
        <div v-if="missingFields.length" class="drawing-banner warn">
          <i class="fa-solid fa-triangle-exclamation"></i>
          필수 항목 {{ missingFieldLabels.join(', ') }}을(를) 찾지 못했습니다. 원본 도면을 확인한 뒤 검수해 주세요.
        </div>
        <div v-else-if="reviewStatus === 'reviewed'" class="drawing-banner ok">
          <i class="fa-solid fa-circle-check"></i>
          검수 완료<template v-if="result.review?.reviewer"> · {{ result.review.reviewer }}</template><template v-if="result.review?.reviewed_at"> · {{ result.review.reviewed_at }}</template>
        </div>

        <nav class="drawing-tabs" role="tablist" aria-label="도면 처리 결과 항목">
          <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" :aria-selected="activeTab === tab.key" :class="{ active: activeTab === tab.key }" @click="activeTab = tab.key">
            {{ tab.label }}<span v-if="tab.count !== null" class="tab-count">{{ tab.count }}</span>
          </button>
        </nav>

        <div class="drawing-tab-body">
          <div v-if="activeTab === 'summary'" class="summary-grid">
            <div>
              <button v-if="mainImage" class="main-image" type="button" @click="openViewer(mainImage, '전체 도면')">
                <AuthenticatedImage :resource-id="mainImage" alt="도면 미리보기" />
              </button>
              <div v-else class="empty-note">도면 이미지를 만들지 못했습니다.</div>
              <div v-if="cropImages.length" class="crop-row">
                <button v-for="crop in cropImages" :key="crop.key" type="button" @click="openViewer(crop.resourceId, crop.label)">
                  <AuthenticatedImage :resource-id="crop.resourceId" :alt="crop.label" /><span>{{ crop.label }}</span>
                </button>
              </div>
            </div>
            <div>
              <h3>표제란</h3>
              <table class="kv-table"><tbody><tr v-for="field in titleFields" :key="field.key"><th>{{ field.label }}</th><td :class="{ missing: field.required && !field.value }">{{ displayValue(field.value) }}</td></tr></tbody></table>
              <h3>도면 정보</h3>
              <table class="kv-table"><tbody>
                <tr><th>도면 종류</th><td>{{ drawingKindLabel }}</td></tr>
                <tr><th>부품표 품번</th><td>{{ result.metadata?.bom_part_nos?.length ?? 0 }}개</td></tr>
                <tr><th>업로더</th><td>{{ result.uploaded_by || '-' }}</td></tr>
              </tbody></table>
            </div>
          </div>

          <ResultTable v-else-if="activeTab === 'bom'" :table="bomTable" empty-text="부품표가 없습니다. 가공품 도면일 수 있습니다." />
          <ResultTable v-else-if="activeTab === 'revision'" :table="revisionTable" empty-text="개정 이력이 없습니다." />

          <div v-else-if="activeTab === 'notes'" class="notes-pane">
            <h3>일반 주기</h3><ul v-if="noteItems.length" class="note-list"><li v-for="(item, index) in noteItems" :key="index">{{ displayValue(item) }}</li></ul><p v-else class="empty-note">추출된 주기가 없습니다.</p>
            <h3>일반 공차</h3><p class="drawing-text">{{ displayValue(result.notes?.general_tolerance) }}</p>
            <h3>사양 메모</h3><ul v-if="specMemos.length" class="note-list"><li v-for="(item, index) in specMemos" :key="index">{{ displayValue(item) }}</li></ul><p v-else class="empty-note">추출된 사양 메모가 없습니다.</p>
            <h3>치수 <small>{{ result.dimension_count ?? dimensions.length }}개</small></h3><div v-if="dimensions.length" class="text-chips"><span v-for="(item, index) in dimensions" :key="index">{{ displayValue(item?.text ?? item) }}</span></div><p v-else class="empty-note">추출된 치수가 없습니다.</p>
            <h3>기타 글자</h3><div v-if="miscTexts.length" class="text-chips"><span v-for="(item, index) in miscTexts" :key="index">{{ displayValue(item) }}</span></div><p v-else class="empty-note">기타 글자가 없습니다.</p>
          </div>

          <div v-else-if="activeTab === 'warnings'">
            <section class="warning-group"><h3>경고 {{ warningItems.length }}건</h3><div v-if="warningItems.length"><article v-for="(item, index) in warningItems" :key="`${item.code}-${index}`"><code>{{ item.code || 'WARN' }}</code><span>{{ item.message }}</span><b v-if="item.count != null">{{ item.count }}건</b></article></div><p v-else>사람이 확인할 경고가 없습니다.</p></section>
            <section class="warning-group info"><h3>정보 {{ infoItems.length }}건</h3><div v-if="infoItems.length"><article v-for="(item, index) in infoItems" :key="`${item.code}-${index}`"><code>{{ item.code || 'INFO' }}</code><span>{{ item.message }}</span><b v-if="item.count != null">{{ item.count }}건</b></article></div><p v-else>자동 처리 정보가 없습니다.</p></section>
          </div>

          <div v-else class="processing-pane">
            <table class="kv-table"><tbody>
              <tr><th>원본 형식</th><td>{{ result.processing?.source?.format || '-' }}</td></tr>
              <tr><th>CAD 버전</th><td>{{ result.processing?.source?.acadver || result.processing?.source?.release || '-' }}</td></tr>
              <tr><th>변환기</th><td>{{ converterText }}</td></tr>
              <tr><th>자동 보정</th><td>{{ result.processing?.source?.converter?.sanitize_fixes ?? 0 }}건</td></tr>
              <tr><th>표제란 추출</th><td>{{ result.title_block?.method || '-' }}</td></tr>
              <tr><th>용지</th><td>{{ result.sheet?.size || result.summary?.sheet_size || '-' }}</td></tr>
              <tr><th>엔티티 / 글자</th><td>{{ result.processing?.stats?.entity_count ?? '-' }} / {{ result.processing?.stats?.text_count ?? '-' }}</td></tr>
              <tr><th>변환 / 추출 / 렌더</th><td>{{ timingText }}</td></tr>
              <tr><th>처리 결과 경로</th><td class="mono">{{ result.processing?.md_dir || '-' }}</td></tr>
            </tbody></table>
          </div>
        </div>
      </template>

      <footer class="drawing-dialog-actions">
        <button v-if="result" class="search-disabled" type="button" disabled title="검수한 도면의 검색 적용은 다음 단계에서 지원됩니다."><i class="fa-solid fa-magnifying-glass"></i> 검색 적용 <small>다음 단계</small></button>
        <span></span>
        <button v-if="result" class="review-button" :class="{ cancel: reviewStatus === 'reviewed' }" type="button" :disabled="reviewing || !result.can_review" :title="reviewDisabledTitle" @click="requestReviewChange">
          <i v-if="reviewing" class="fa-solid fa-spinner fa-spin"></i> {{ reviewButtonLabel }}
        </button>
        <button class="close-button" type="button" @click="close">닫기</button>
      </footer>
    </section>

    <div v-if="confirmMissing" class="nested-overlay" @keydown.stop="onConfirmKeydown">
      <section ref="confirmRef" class="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="missingConfirmTitle" tabindex="-1">
        <h2 id="missingConfirmTitle"><i class="fa-solid fa-triangle-exclamation"></i> 필수 항목 확인</h2>
        <p>필수 항목 {{ missingFieldLabels.join(', ') }}을(를) 찾지 못했습니다. 원본 도면에서 확인했습니까?</p>
        <div><button type="button" class="close-button" @click="confirmMissing = false">취소</button><button type="button" class="review-button" :disabled="reviewing" @click="completeReview(true)">원본 확인함 · 검수 완료</button></div>
      </section>
    </div>

    <div v-if="viewer" class="nested-overlay image-overlay" @keydown.stop="onViewerKeydown">
      <section ref="viewerRef" class="image-viewer" role="dialog" aria-modal="true" aria-label="도면 이미지 확대" tabindex="-1">
        <header><strong>{{ viewer.label }}</strong><button type="button" aria-label="확대 이미지 닫기" @click="viewer = null"><i class="fa-solid fa-xmark"></i></button></header>
        <AuthenticatedImage :resource-id="viewer.resourceId" :alt="viewer.label" />
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue';
import { adminApi } from '../api/adminApi';
import { handleDialogKeydown } from '../utils/dialogKeydown';
import AuthenticatedImage from './AuthenticatedImage.vue';
import ResultTable from './DrawingResultTable.vue';

const props = defineProps({ document: { type: Object, required: true } });
const emit = defineEmits(['close', 'changed', 'toast']);
const dialogRef = ref(null); const confirmRef = ref(null); const viewerRef = ref(null);
const loading = ref(true); const loadError = ref(''); const result = ref(null); const activeTab = ref('summary');
const reviewing = ref(false); const confirmMissing = ref(false); const viewer = ref(null);
const apiError = (error, fallback) => { const detail = error.response?.data?.detail; return (typeof detail === 'string' ? detail : detail?.message) || error.message || fallback; };
const resourceId = (value) => typeof value === 'string' ? value : value?.resource_id || '';
const displayValue = (value) => value === null || value === undefined || value === '' ? '-' : Array.isArray(value) ? value.join(', ') : String(value);
const findTable = (kind) => (result.value?.tables || []).find((table) => table.kind === kind) || null;
const bomTable = computed(() => findTable('bom')); const revisionTable = computed(() => findTable('revision'));
const warningItems = computed(() => (result.value?.warnings || []).filter((item) => item.level === 'warn'));
const infoItems = computed(() => (result.value?.warnings || []).filter((item) => item.level === 'info'));
const noteItems = computed(() => result.value?.notes?.items || []); const specMemos = computed(() => result.value?.notes?.spec_memos || []);
const dimensions = computed(() => result.value?.dimensions || []); const miscTexts = computed(() => result.value?.misc_texts || []);
const missingFields = computed(() => result.value?.summary?.missing_fields || []);
const requiredLabels = { part_no: '품번', part_name: '품명', revision: '개정' };
const missingFieldLabels = computed(() => missingFields.value.map((field) => requiredLabels[field] || field));
const reviewStatus = computed(() => result.value?.review?.status || 'pending');
const reviewButtonLabel = computed(() => reviewing.value ? '처리 중...' : reviewStatus.value === 'reviewed' ? '검수 취소' : '검수 완료');
const reviewDisabledTitle = computed(() => result.value?.can_review ? '' : result.value?.is_current === false ? '현재 버전만 검수할 수 있습니다.' : '소속 부서의 운영관리자만 검수할 수 있습니다.');
const mainImage = computed(() => resourceId(result.value?.images?.preview || result.value?.images?.full));
const cropImages = computed(() => [['title_block', '표제란'], ['bom', '부품표'], ['revision', '개정이력']].map(([key, label]) => ({ key, label, resourceId: resourceId(result.value?.images?.crops?.[key]) })).filter((item) => item.resourceId));
const fieldDefinitions = [['part_no', '품번', true], ['part_name', '품명', true], ['revision', '개정', true], ['date', '날짜'], ['scale', '축척'], ['material', '재질'], ['material_group', '재질 그룹'], ['after_treatment', '후처리'], ['part_spec', 'PART SPEC'], ['drawn', '작성'], ['checked', '검토'], ['approved', '승인']];
const titleFields = computed(() => fieldDefinitions.map(([key, label, required = false]) => ({ key, label, required, value: result.value?.title_block?.fields?.[key] })));
const drawingKindLabel = computed(() => ({ assembly: '조립도', part: '부품도' }[result.value?.metadata?.drawing_kind] || result.value?.metadata?.drawing_kind || '-'));
const converterText = computed(() => { const value = result.value?.processing?.source?.converter; return value ? `${value.name || '-'} ${value.version || ''}${value.elapsed_ms != null ? ` · ${value.elapsed_ms} ms` : ''}`.trim() : '변환 없음(DXF)'; });
const timingText = computed(() => { const value = result.value?.processing?.timings || {}; return `${value.convert_ms ?? '-'} / ${value.extract_ms ?? '-'} / ${value.render_ms ?? '-'} ms`; });
const tabs = computed(() => [
  { key: 'summary', label: '요약', count: null }, { key: 'bom', label: '부품표', count: bomTable.value?.rows?.length ?? 0 },
  { key: 'revision', label: '개정이력', count: revisionTable.value?.rows?.length ?? 0 }, { key: 'notes', label: '주기·치수', count: noteItems.value.length + dimensions.value.length },
  { key: 'warnings', label: '경고·정보', count: warningItems.value.length + infoItems.value.length }, { key: 'processing', label: '처리 정보', count: null },
]);

const load = async () => { loading.value = true; loadError.value = ''; try { const response = await adminApi.drawingResult(props.document.document_id, props.document.version_no ?? 1); result.value = response.data; } catch (error) { loadError.value = apiError(error, '도면 처리 결과를 불러오지 못했습니다.'); } finally { loading.value = false; await nextTick(); dialogRef.value?.focus(); } };
const close = () => emit('close');
const onKeydown = (event) => { if (confirmMissing.value || viewer.value) return; handleDialogKeydown(event, close); };
const openViewer = (id, label) => { const full = resourceId(result.value?.images?.full) || id; viewer.value = { resourceId: label === '전체 도면' ? full : id, label }; nextTick(() => viewerRef.value?.focus()); };
const onViewerKeydown = (event) => handleDialogKeydown(event, () => { viewer.value = null; });
const onConfirmKeydown = (event) => handleDialogKeydown(event, () => { confirmMissing.value = false; });
const requestReviewChange = () => { if (reviewStatus.value === 'reviewed') cancelReview(); else if (missingFields.value.length) { confirmMissing.value = true; nextTick(() => confirmRef.value?.focus()); } else completeReview(false); };
const applyReview = (data) => { result.value.review = data.review || data; emit('changed'); };
const completeReview = async (confirm) => { reviewing.value = true; try { const response = await adminApi.completeDrawingReview(props.document.document_id, result.value.version_no ?? props.document.version_no ?? 1, confirm ? { confirm_missing: true } : {}); applyReview(response.data); confirmMissing.value = false; emit('toast', '도면 검수를 완료했습니다.', 'success'); } catch (error) { const detail = error.response?.data?.detail; if (error.response?.status === 409 && detail?.code === 'MISSING_FIELDS_CONFIRM_REQUIRED') { confirmMissing.value = true; await nextTick(); confirmRef.value?.focus(); } else emit('toast', apiError(error, '도면 검수를 완료하지 못했습니다.'), 'error'); } finally { reviewing.value = false; } };
const cancelReview = async () => { reviewing.value = true; try { const response = await adminApi.cancelDrawingReview(props.document.document_id, result.value.version_no ?? props.document.version_no ?? 1); applyReview(response.data); emit('toast', '도면 검수를 취소했습니다.', 'success'); } catch (error) { emit('toast', apiError(error, '도면 검수를 취소하지 못했습니다.'), 'error'); } finally { reviewing.value = false; } };
onMounted(load);
</script>

<style scoped>
.drawing-dialog-overlay,.nested-overlay{position:fixed;inset:0;z-index:80;display:flex;align-items:center;justify-content:center;padding:16px;background:rgba(15,23,42,.5)}
.drawing-dialog{display:flex;flex-direction:column;width:min(1080px,100%);max-height:calc(100dvh - 32px);overflow:hidden;border-radius:14px;background:#fff;box-shadow:0 24px 60px rgba(15,23,42,.3);outline:none}
.drawing-dialog-head{display:flex;align-items:flex-start;justify-content:space-between;padding:1.2rem 1.4rem .75rem}.drawing-dialog-head h2{margin:0;color:#1e293b;font-size:1.05rem}.drawing-dialog-head h2 i{margin-right:.45rem;color:#0f766e}.drawing-dialog-head p{margin:.35rem 0 0;color:#64748b;font-size:.8rem}.icon-button{border:0;background:none;color:#94a3b8;font-size:1.15rem}
.drawing-state{margin:1rem 1.4rem;padding:1rem;border-radius:8px;background:#f8fafc;color:#475569}.drawing-state i{margin-right:.4rem}.drawing-state.error{background:#fef2f2;color:#b91c1c}.drawing-banner{margin:0 1.4rem .65rem;padding:.65rem .8rem;border:1px solid;border-radius:8px;font-size:.82rem;line-height:1.5}.drawing-banner i{margin-right:.4rem}.drawing-banner.warn{border-color:#fed7aa;background:#fff7ed;color:#9a3412}.drawing-banner.ok{border-color:#bbf7d0;background:#f0fdf4;color:#166534}
.drawing-tabs{display:flex;overflow-x:auto;padding:0 1.4rem;border-bottom:1px solid #e2e8f0}.drawing-tabs button{display:flex;gap:.35rem;align-items:center;padding:.65rem .8rem;border:0;border-bottom:2px solid transparent;background:none;color:#64748b;white-space:nowrap}.drawing-tabs button.active{border-bottom-color:#2563eb;color:#2563eb;font-weight:700}.tab-count{min-width:1.25rem;padding:.05rem .35rem;border-radius:999px;background:#f1f5f9;font-size:.7rem}
.drawing-tab-body{flex:1;overflow:auto;padding:1.1rem 1.4rem}.summary-grid{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(300px,1fr);gap:1.25rem}.main-image{width:100%;height:360px;padding:0;overflow:hidden;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc;cursor:zoom-in}.crop-row{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;margin-top:.5rem}.crop-row button{height:100px;padding:4px;border:1px solid #e2e8f0;border-radius:8px;background:#fff;text-align:left}.crop-row .authenticated-image{height:70px}.crop-row span{display:block;margin-top:2px;color:#64748b;font-size:.72rem}h3{margin:1rem 0 .45rem;color:#334155;font-size:.84rem}h3:first-child{margin-top:0}.kv-table{width:100%;border-collapse:collapse;font-size:.82rem}.kv-table th{width:120px;padding:.4rem .5rem;border-bottom:1px solid #f1f5f9;color:#64748b;text-align:left;font-weight:500;vertical-align:top}.kv-table td{padding:.4rem .5rem;border-bottom:1px solid #f1f5f9;color:#1e293b}.kv-table td.missing{color:#dc2626;font-weight:700}.mono{font-family:Consolas,monospace;overflow-wrap:anywhere}.empty-note{padding:1rem;border:1px dashed #cbd5e1;border-radius:8px;background:#f8fafc;color:#64748b;text-align:center;font-size:.84rem}.note-list{margin:0;padding-left:1.2rem;color:#334155;line-height:1.8}.drawing-text{color:#334155}.text-chips{display:flex;flex-wrap:wrap;gap:.4rem}.text-chips span{padding:.25rem .5rem;border-radius:5px;background:#f1f5f9;color:#334155;font-size:.8rem}
.warning-group{margin-bottom:.85rem;overflow:hidden;border:1px solid #fed7aa;border-radius:10px}.warning-group h3{margin:0;padding:.6rem .8rem;background:#fff7ed;color:#9a3412}.warning-group article{display:grid;grid-template-columns:170px 1fr auto;gap:.75rem;padding:.6rem .8rem;border-top:1px solid #f1f5f9;font-size:.8rem}.warning-group code{color:#475569}.warning-group p{margin:0;padding:.7rem .8rem;color:#94a3b8;font-size:.8rem}.warning-group.info{border-color:#bfdbfe}.warning-group.info h3{background:#eff6ff;color:#1d4ed8}
.drawing-dialog-actions{display:flex;gap:.5rem;align-items:center;padding:.85rem 1.4rem;border-top:1px solid #e2e8f0}.drawing-dialog-actions>span{flex:1}.review-button,.close-button,.search-disabled{padding:.55rem 1rem;border-radius:8px;font-size:.84rem}.review-button{border:0;background:#16a34a;color:#fff;font-weight:600}.review-button.cancel{background:#fff7ed;color:#c2410c;border:1px solid #fed7aa}.review-button:disabled{opacity:.5}.close-button{border:1px solid #d1d5db;background:#fff;color:#374151}.search-disabled{border:1px dashed #cbd5e1;background:#f8fafc;color:#94a3b8}.search-disabled small{margin-left:.3rem}
.nested-overlay{z-index:90}.confirm-dialog{width:min(480px,100%);padding:1.4rem;border-radius:12px;background:#fff;outline:none}.confirm-dialog h2{margin:0;color:#1e293b;font-size:1rem}.confirm-dialog h2 i{color:#f97316}.confirm-dialog p{color:#475569;line-height:1.6}.confirm-dialog>div{display:flex;justify-content:flex-end;gap:.5rem}.image-overlay{background:rgba(2,6,23,.88)}.image-viewer{display:flex;flex-direction:column;width:min(1400px,100%);height:calc(100dvh - 32px);outline:none}.image-viewer header{display:flex;justify-content:space-between;padding:.6rem;color:#fff}.image-viewer header button{border:0;background:none;color:#fff;font-size:1.2rem}.image-viewer .authenticated-image{flex:1;border-radius:8px;background:#fff}
@media(max-width:800px){.summary-grid{grid-template-columns:1fr}.main-image{height:280px}.drawing-dialog-actions{flex-wrap:wrap}.search-disabled{display:none}.warning-group article{grid-template-columns:1fr}.crop-row{grid-template-columns:1fr}.crop-row button{height:120px}}
</style>
