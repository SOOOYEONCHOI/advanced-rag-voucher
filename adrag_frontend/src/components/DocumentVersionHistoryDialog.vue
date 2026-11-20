<!-- 2026.11.09(woojin.jung) 추가 - 버전 이력(B·C·F)·이전 버전 복원(D·E) 대화상자. 08_이전버전복원_목업_가이드 화면 기준 -->
<template>
  <!-- B 버전 이력 -->
  <div v-if="r.historyDoc" class="overlay history-overlay" @keydown="onKeydown($event, 'history')">
    <section ref="historyDialogEl" class="dialog" role="dialog" aria-modal="true" aria-labelledby="vrHistoryTitle" tabindex="-1">
      <header class="dialog-head">
        <div class="topline">
          <h2 id="vrHistoryTitle"><i class="fa-solid fa-clock-rotate-left title-icon"></i>버전 이력</h2>
          <button ref="historyCloseEl" type="button" class="close" aria-label="버전 이력 닫기" @click="r.closeHistory()">×</button>
        </div>
        <p class="subtitle">
          <strong>{{ h?.product_model ?? r.historyDoc.product_model ?? '-' }}</strong>
          <span v-if="h?.collection_display_name" class="muted topic"> · {{ h.collection_display_name }}</span>
          <br />
          <span class="muted">{{ h?.current_original_filename ?? r.historyDoc.filename }}</span>
        </p>
      </header>

      <div class="dialog-body">
        <div class="note" :class="{ warn: r.historyNotice }">{{ r.historyNoticeText }}</div>
        <div class="history-section-title">
          <span>버전 선택</span>
          <span v-if="h" class="history-count">최신순 · 총 {{ h.total_versions }}개 버전</span>
        </div>
        <div ref="versionsEl" class="versions" aria-live="polite">
          <p v-if="r.historyState === 'loading'" class="muted list-message"><span class="spinner"></span>버전 이력을 불러오는 중입니다.</p>
          <div v-else-if="r.historyState === 'error'" class="note error" role="alert">
            버전 이력을 불러오지 못했습니다. <button type="button" @click="r.loadHistory()">다시 불러오기</button>
          </div>
          <p v-else-if="!versions.length" class="muted list-message">버전 이력이 없습니다.</p>
          <template v-else>
            <article v-for="v in versions" :key="v.version_no" class="version" :class="{ active: v.is_active, selected: isSelected(v) }" :aria-label="`v${v.version_no} 버전`">
              <button
                type="button"
                class="version-option"
                :data-select-version="v.version_no"
                :disabled="!r.isSelectable(v)"
                :aria-pressed="String(isSelected(v))"
                @click="r.selectVersion(v)"
              >
                <span class="version-radio" aria-hidden="true"><i v-if="v.is_active" class="fa-solid fa-check"></i></span>
                <span class="version-info">
                  <span class="version-top">
                    <strong>v{{ v.version_no }}</strong>
                    <span class="badge" :class="badgeClass(v)">{{ badgeLabel(v) }}</span>
                    <span v-if="v.is_active" class="small muted">· 검색·답변 사용 중</span>
                  </span>
                  <span class="version-filename">{{ v.original_filename || '-' }}</span>
                  <span class="version-details">{{ versionDetails(v) }}</span>
                </span>
                <i v-if="r.isSelectable(v)" class="fa-solid fa-chevron-right chevron"></i>
              </button>
              <p v-if="!v.is_active && v.restore_block_reason" class="version-reason"><i class="fa-solid fa-circle-info"></i> {{ v.restore_block_reason }}</p>
            </article>
          </template>
        </div>
        <p v-if="h?.restore_supported !== false" class="history-help"><i class="fa-solid fa-circle-info"></i> 적용할 버전을 선택한 후 하단의 [선택 버전 적용] 버튼을 눌러주세요.</p>

        <!-- F 적용 이력 -->
        <section class="timeline">
          <details :open="r.activations.open" @toggle="r.toggleActivations($event.target.open)">
            <summary>적용 이력 보기 <i class="fa-solid fa-chevron-down summary-icon"></i></summary>
            <div class="activation-log">
              <p v-if="act.loading && !act.items.length"><span class="spinner"></span>적용 이력을 불러오는 중입니다.</p>
              <p v-else-if="act.error && !act.items.length" class="log-error" role="alert">
                {{ act.error }} <button type="button" class="link-button" @click="r.loadActivations({ force: true })">다시 불러오기</button>
              </p>
              <p v-else-if="act.loaded && !act.items.length">적용 이력이 없습니다.</p>
              <template v-else>
                <p v-for="a in act.items" :key="a.activation_id">{{ activationText(a) }}</p>
                <p v-if="act.error" class="log-error" role="alert">{{ act.error }}</p>
                <button v-if="act.next != null" type="button" class="more-button" :disabled="act.loading" @click="r.loadActivations({ more: true })">
                  <span v-if="act.loading" class="spinner"></span>더 보기
                </button>
              </template>
            </div>
          </details>
        </section>
      </div>

      <footer class="dialog-foot">
        <div class="selection-summary" aria-live="polite">
          <template v-if="selected"><strong>v{{ h.current_version_no }} → v{{ selected.version_no }}</strong> 적용 예정 · 확인 단계가 한 번 더 표시됩니다.</template>
          <template v-else>적용할 버전을 선택하세요.</template>
        </div>
        <div class="footer-actions">
          <button type="button" @click="r.closeHistory()">닫기</button>
          <button v-if="h?.restore_supported !== false" type="button" class="restore-selected" :disabled="!selected" @click="r.openRestoreConfirm()">
            <i class="fa-solid fa-arrow-right-arrow-left"></i> 선택 버전 적용
          </button>
        </div>
      </footer>
    </section>
  </div>

  <!-- D 복원 확인 · E 진행/결과 -->
  <div v-if="d" class="overlay restore-overlay" @keydown="onKeydown($event, 'restore')">
    <section ref="restoreDialogEl" class="dialog confirm" role="dialog" aria-modal="true" aria-labelledby="vrRestoreTitle" tabindex="-1">
      <header class="dialog-head">
        <h2 id="vrRestoreTitle">{{ restoreTitle }}</h2>
        <p class="muted small model-line">{{ d.productModel }}</p>
      </header>

      <div class="dialog-body">
        <template v-if="d.stage === 'confirm'">
          <p>선택한 버전을 문서에 적용하시겠습니까?</p>
          <div class="comparison">
            <div class="compare-box">
              <span class="muted small">현재 적용</span>
              <strong>v{{ d.current }}</strong>
              <span class="filename">{{ d.currentFilename }}</span>
            </div>
            <span class="muted">→</span>
            <div class="compare-box target">
              <span class="small target-label">적용할 버전</span>
              <strong>v{{ d.target }}</strong>
              <span class="filename">{{ d.targetFilename }}</span>
            </div>
          </div>
          <div class="note">검색·답변과 사진·출처가 v{{ d.target }} 내용으로 변경됩니다.</div>
          <div class="checklist small">
            ✓ 보관된 검색 데이터를 그대로 사용합니다.<br />✓ 적용 전후 버전 이력이 모두 유지됩니다.<br />✓ 완료 전에는 현재 v{{ d.current }}{{ josaRo(d.current) }} 서비스합니다.
          </div>
          <p class="muted small">적용 후 새 파일을 등록하면 v{{ d.nextVersionNo }}{{ josaRo(d.nextVersionNo) }} 추가됩니다.</p>
          <div v-if="d.error" class="note error confirm-error" role="alert">{{ d.error }}</div>
        </template>

        <template v-else-if="d.stage === 'progress'">
          <div class="note">완료 전까지 현재 v{{ d.from }}{{ josaRo(d.from) }} 검색·답변합니다.</div>
          <div class="progress" role="status">
            <p v-for="(line, index) in progressLines" :key="index" class="step" :class="{ on: line.state === 'on' }">
              <template v-if="line.state === 'done'">✓ {{ line.text }}</template>
              <template v-else-if="line.state === 'on'"><span class="spinner"></span>{{ line.text }}</template>
              <template v-else>○ {{ line.text }}</template>
            </p>
          </div>
          <p v-if="d.pollFailed" class="muted small poll-warning">연결이 불안정해 처리 상태를 다시 확인하고 있습니다.</p>
          <p class="muted small">창을 닫아도 처리는 계속됩니다. 버전 이력에서 결과를 확인할 수 있습니다.</p>
        </template>

        <template v-else-if="d.stage === 'success'">
          <div class="note success" role="status">✓ 현재 적용 버전이 v{{ result.current_version_no }}{{ josaRo(result.current_version_no) }} 변경되었습니다.</div>
          <div class="progress">
            <strong>{{ result.original_filename }}</strong>
            <p class="muted small result-meta">
              {{ result.total_pages ?? '-' }}페이지 · {{ result.chunk_count ?? '-' }}개 청크<br />선택한 버전의 문서·검색·사진·출처가 적용되었습니다.
            </p>
          </div>
          <p class="muted small">실행자: {{ result.activated_by_name ?? result.activated_by ?? '-' }} · 이 내역은 적용 이력에 기록되었습니다.</p>
        </template>

        <template v-else>
          <div class="note error" role="alert">{{ d.error }}</div>
          <p class="kept-version">
            현재 적용 버전은 <strong>v{{ d.keptVersionNo }}</strong>{{ josaRo(d.keptVersionNo) }} 유지됩니다.
          </p>
          <p class="muted small">잠시 후 다시 시도하세요. 반복되면 관리자에게 문의하세요.</p>
        </template>
      </div>

      <footer class="dialog-foot">
        <template v-if="d.stage === 'confirm'">
          <button type="button" :disabled="d.submitting" @click="r.closeRestoreDialog()">취소</button>
          <button type="button" class="primary" :disabled="d.submitting" @click="r.submitRestore()">
            <span v-if="d.submitting" class="spinner on-primary"></span>이 버전으로 적용
          </button>
        </template>
        <button v-else-if="d.stage === 'progress'" type="button" @click="r.continueInBackground()">닫고 계속하기</button>
        <button v-else-if="d.stage === 'success'" type="button" class="primary" @click="r.completeRestore()">버전 이력 확인</button>
        <template v-else>
          <button type="button" @click="r.closeRestoreDialog()">버전 이력으로</button>
          <button type="button" class="primary" @click="r.retryRestore()">다시 시도</button>
        </template>
      </footer>
    </section>
  </div>
</template>

<script>
import { computed, nextTick, ref, watch } from 'vue';
import { activationText, formatMegabytes, josaRo, restoreStepLines, versionStatusLabel } from '../composables/useDocumentVersionRestore';

const RESTORE_TITLES = {
  confirm: '버전 적용',
  progress: '선택한 버전을 적용하고 있습니다',
  success: '선택한 버전을 적용했습니다',
  failure: '버전을 적용하지 못했습니다',
};

export default {
  name: 'DocumentVersionHistoryDialog',
  props: {
    // useDocumentVersionRestore 반환값을 reactive로 감싼 객체
    restore: { type: Object, required: true },
  },
  setup(props) {
    const r = props.restore;
    const historyDialogEl = ref(null);
    const historyCloseEl = ref(null);
    const restoreDialogEl = ref(null);
    const versionsEl = ref(null);
    let historyReturnFocus = null;

    const h = computed(() => r.history);
    const d = computed(() => r.restoreDialog);
    const act = computed(() => r.activations);
    const versions = computed(() => (r.historyState === 'ready' ? r.history?.versions || [] : []));
    const selected = computed(() => r.selectedVersion);
    const result = computed(() => r.restoreDialog?.result || {});
    const restoreTitle = computed(() => RESTORE_TITLES[r.restoreDialog?.stage] || '');

    const progressLines = computed(() => {
      const dialog = r.restoreDialog;
      if (!dialog) return [];
      const texts = ['적용 요청 접수', `v${dialog.target}의 검색 데이터와 원본 확인 중`, dialog.step === 'activate' ? '적용 버전 전환 중' : '적용 버전 전환 대기'];
      return restoreStepLines(dialog.step).map((state, index) => ({ state, text: texts[index] }));
    });

    const isSelected = (v) => r.isSelectable(v) && r.selectedVersionNo === v.version_no;
    const badgeClass = (v) => (v.is_active ? 'green' : isSelected(v) ? 'blue' : v.status === 'failed' ? 'red' : '');
    const badgeLabel = (v) => (v.is_active ? '현재 적용 중' : isSelected(v) ? '적용 대상 선택됨' : versionStatusLabel(v.status));
    const versionDetails = (v) => [
      v.created_at ? `${v.created_at} 등록` : null,
      v.total_pages != null ? `${v.total_pages}페이지` : null,
      v.chunk_count != null ? `${v.chunk_count}청크` : null,
      formatMegabytes(v.file_size),
    ].filter(Boolean).join(' · ');

    // 포커스: 이력을 열면 대화상자로, 닫으면 연 버튼으로 되돌린다
    watch(() => r.historyDoc, async (doc, previous) => {
      if (doc && !previous) {
        historyReturnFocus = document.activeElement;
        await nextTick();
        historyDialogEl.value?.focus();
      } else if (!doc && previous) {
        if (historyReturnFocus?.isConnected) historyReturnFocus.focus();
        historyReturnFocus = null;
      }
    });

    // 복원 창 단계가 바뀌면 창으로, 닫히면 대상 버전 행(선택 불가면 닫기 버튼)으로
    watch(() => [r.restoreDialog, r.restoreDialog?.stage], async ([dialog], [previous]) => {
      await nextTick();
      if (dialog) {
        restoreDialogEl.value?.focus();
      } else if (previous && r.historyDoc) {
        const btn = versionsEl.value?.querySelector(`[data-select-version="${previous.target}"]`);
        (btn && !btn.disabled ? btn : historyCloseEl.value)?.focus();
      }
    });

    const onKeydown = (event, which) => {
      // 복원 창이 열려 있으면 이력 창은 키 입력을 받지 않는다
      if (which === 'history' && r.restoreDialog) return;
      const dialogEl = which === 'restore' ? restoreDialogEl.value : historyDialogEl.value;
      if (event.key === 'Escape') {
        event.stopPropagation();
        if (which === 'history') r.closeHistory();
        else if (r.restoreDialog?.stage === 'progress') r.continueInBackground();
        else r.closeRestoreDialog();
        return;
      }
      if (event.key !== 'Tab' || !dialogEl) return;
      const items = [...dialogEl.querySelectorAll('button:not(:disabled), a[href], select, summary')];
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogEl)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialogEl.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };

    return {
      r, h, d, act, versions, selected, result, restoreTitle, progressLines,
      historyDialogEl, historyCloseEl, restoreDialogEl, versionsEl,
      isSelected, badgeClass, badgeLabel, versionDetails, onKeydown,
      activationText, josaRo,
    };
  },
};
</script>

<style scoped>
/* 08_이전버전복원_목업_가이드 #historyOverlay·#restoreOverlay 최종 규격 */
.overlay {
  position: fixed;
  inset: 0;
  background: #0f172a80;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 200;
  color: #1e293b;
  font-family: Inter, 'Apple SD Gothic Neo', sans-serif;
  font-size: 14px;
  line-height: 1.6;
}
.restore-overlay {
  z-index: 210;
}
.overlay *,
.overlay *::before,
.overlay *::after {
  box-sizing: border-box;
}
h2,
p {
  margin: 0;
}
button {
  font-family: inherit;
  font-size: inherit;
  cursor: pointer;
  border: 1px solid #cbd5e1;
  background: white;
  color: #475569;
  border-radius: 7px;
  padding: 8px 13px;
}
button:hover:enabled {
  background: #f8fafc;
}
button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}
button:focus-visible,
summary:focus-visible {
  outline: 3px solid #93c5fd;
  outline-offset: 3px;
}
.primary {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}
.primary:hover:enabled {
  background: #1d4ed8;
}
.muted {
  color: #64748b;
}
.small {
  font-size: 12px;
}
.badge {
  display: inline-flex;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  background: #f1f5f9;
  color: #64748b;
}
.badge.blue {
  background: #eff6ff;
  color: #2563eb;
}
.badge.green {
  background: #ecfdf5;
  color: #047857;
}
.badge.red {
  background: #fef2f2;
  color: #b91c1c;
}
.note {
  padding: 12px 15px;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 13px;
}
.note.warn {
  background: #fffbeb;
  color: #92400e;
}
.note.error {
  background: #fef2f2;
  color: #b91c1c;
}
.note.success {
  background: #ecfdf5;
  color: #047857;
}
.topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.dialog {
  width: 520px;
  max-width: 100%;
  max-height: calc(100dvh - 40px);
  background: white;
  border-radius: 12px;
  box-shadow: 0 24px 70px #0f172a40;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.dialog:focus {
  outline: none;
}
.dialog h2 {
  font-size: 17.6px;
  font-weight: 700;
}
.dialog-body {
  overflow: auto;
}
.dialog-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  background: #fff;
}
.close {
  font-size: 22px;
  border: 0;
  padding: 0 7px;
  background: transparent;
  color: #64748b;
}
.spinner {
  display: inline-block;
  width: 13px;
  height: 13px;
  border: 2px solid #bfdbfe;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  vertical-align: -2px;
  margin-right: 7px;
}
.spinner.on-primary {
  border-color: #ffffff80;
  border-top-color: white;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ── B 버전 이력 ── */
.history-overlay .dialog {
  width: 720px;
  max-width: calc(100vw - 24px);
}
.history-overlay .dialog-head {
  padding: 24px 28px 16px;
  border-bottom: 1px solid #e2e8f0;
}
.history-overlay .dialog-body {
  padding: 20px 28px;
}
.history-overlay .dialog-foot {
  padding: 16px 28px;
  border-top: 1px solid #e2e8f0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.title-icon {
  color: #2563eb;
  margin-right: 7px;
}
.subtitle {
  margin-top: 9px;
  font-size: 14px;
  line-height: 1.6;
}
.subtitle .topic {
  font-size: 12px;
}
/* 이력 창 안내는 배경 없이 회색 문구(경고·오류는 글자색으로만 구분) */
.history-overlay .note {
  background: transparent;
  color: #64748b;
  padding: 0;
  font-size: 12.8px;
  line-height: 1.5;
}
.history-overlay .note.warn {
  color: #b45309;
}
.history-overlay .note.error {
  color: #b91c1c;
}
.history-overlay .note.error button {
  margin-left: 6px;
  padding: 4px 10px;
  font-size: 12px;
}
.history-section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 19px;
  font-size: 13px;
  font-weight: 650;
  color: #334155;
}
.history-count {
  font-size: 12px;
  font-weight: 400;
  color: #64748b;
}
.versions {
  margin-top: 14px;
  display: grid;
  gap: 9px;
}
.list-message {
  padding: 18px;
}
.version {
  padding: 0;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.version.active {
  background: #f8fafc;
  border-color: #cbd5e1;
}
.version.selected {
  background: #eff6ff;
  border: 2px solid #2563eb;
}
.version-option {
  width: 100%;
  border: 0;
  background: transparent;
  border-radius: 9px;
  padding: 15px 17px;
  display: flex;
  gap: 14px;
  text-align: left;
  align-items: center;
  color: #334155;
  cursor: pointer;
}
.version-option:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}
.version-option:hover:not(:disabled) {
  background: #f8fbff;
}
.version.selected .version-option:hover {
  background: transparent;
}
.version-radio {
  width: 19px;
  height: 19px;
  border: 2px solid #cbd5e1;
  border-radius: 50%;
  flex-shrink: 0;
  display: grid;
  place-items: center;
}
.version-radio i {
  font-size: 10px;
  color: #64748b;
}
.version.selected .version-radio {
  border-color: #2563eb;
}
.version.selected .version-radio::after {
  content: '';
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #2563eb;
}
.version-info {
  flex: 1;
  min-width: 0;
}
.version-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.version-top strong {
  font-size: 15px;
  color: #0f172a;
}
.version-filename {
  display: block;
  margin-top: 5px;
  font-size: 13px;
  color: #334155;
  overflow-wrap: anywhere;
}
.version-details {
  display: block;
  margin-top: 5px;
  font-size: 12px;
  color: #64748b;
}
.chevron {
  color: #94a3b8;
  font-size: 12px;
}
.version-reason {
  padding: 0 17px 12px 50px;
  color: #b45309;
  font-size: 12px;
}
.history-help {
  margin-top: 10px;
  color: #64748b;
  font-size: 12px;
}
.selection-summary {
  flex: 1;
  min-width: 0;
  color: #64748b;
  font-size: 12px;
}
.selection-summary strong {
  color: #1e293b;
}
.footer-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.restore-selected {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
  font-weight: 600;
}
.restore-selected:hover:not(:disabled) {
  background: #1d4ed8;
}
.restore-selected:disabled {
  background: #e2e8f0;
  color: #94a3b8;
  border-color: #e2e8f0;
  opacity: 1;
}

/* ── F 적용 이력 ── */
.timeline {
  margin-top: 18px;
  border-top: 1px solid #e2e8f0;
  padding-top: 14px;
}
.timeline summary {
  cursor: pointer;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
}
.timeline details[open] summary {
  margin-bottom: 8px;
}
.summary-icon {
  font-size: 10px;
}
.activation-log p {
  color: #64748b;
  font-size: 11.5px;
  padding: 4px 0;
}
.activation-log .log-error {
  color: #b91c1c;
}
.link-button {
  border: 0;
  padding: 0 4px;
  background: transparent;
  color: #2563eb;
  font-size: 11.5px;
  text-decoration: underline;
}
.more-button {
  margin-top: 6px;
  padding: 5px 12px;
  font-size: 12px;
}

/* ── D·E 복원 확인/진행/결과 ── */
.restore-overlay .dialog {
  width: 580px;
}
.restore-overlay .dialog-head {
  padding: 24px 26px 16px;
  border-bottom: 1px solid #e2e8f0;
}
.restore-overlay .dialog-body {
  padding: 22px 26px;
}
.restore-overlay .dialog-foot {
  padding: 16px 26px;
  border-top: 1px solid #e2e8f0;
}
.model-line {
  margin-top: 5px;
}
.comparison {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 10px;
  margin: 20px 0;
}
.compare-box {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  padding: 12px;
}
.compare-box span {
  display: block;
}
.compare-box.target {
  border-color: #93c5fd;
  background: #eff6ff;
}
.target-label {
  color: #2563eb;
}
.compare-box strong {
  display: block;
  font-size: 23px;
  margin: 3px 0;
}
.compare-box .filename {
  font-size: 12px;
  color: #64748b;
  overflow-wrap: anywhere;
}
.checklist {
  margin: 14px 0;
  color: #475569;
  line-height: 1.8;
}
.confirm-error {
  margin-top: 14px;
}
.progress {
  margin: 20px 0;
  padding: 18px;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
}
.step {
  padding: 7px 0;
  color: #64748b;
}
.step.on {
  color: #2563eb;
  font-weight: 600;
}
.poll-warning {
  margin-bottom: 6px;
  color: #b45309;
}
.result-meta {
  margin-top: 8px;
}
.kept-version {
  margin: 18px 0;
}

@media (max-width: 600px) {
  .overlay {
    padding: 10px;
  }
  .dialog {
    max-height: calc(100dvh - 20px);
  }
  .topline {
    gap: 8px;
  }
  .subtitle {
    font-size: 12px;
  }
  .history-overlay .dialog-head {
    padding: 18px 18px 14px;
  }
  .history-overlay .dialog-body {
    padding: 16px 18px;
  }
  .history-overlay .dialog-foot {
    padding: 14px 18px;
    flex-direction: column;
    align-items: stretch;
  }
  .footer-actions {
    width: 100%;
  }
  .footer-actions button {
    flex: 1;
  }
  .version-option {
    padding: 13px 12px;
    gap: 10px;
  }
  .version-reason {
    padding-left: 42px;
  }
  .version-details {
    line-height: 1.6;
  }
  .restore-overlay .dialog-head,
  .restore-overlay .dialog-body,
  .restore-overlay .dialog-foot {
    padding: 16px;
  }
  .comparison {
    grid-template-columns: 1fr;
    gap: 8px;
  }
  .comparison > span {
    text-align: center;
    transform: rotate(90deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation: none;
  }
}
</style>
