<!-- 2026.04.01(sooyeon.choi) 수정 - 멀티대화 주제 관리 기능 추가 -->
<template>
  <div class="admin-layout">
    <AdminSidebar :isOpen="sidebarOpen" activePage="collections" :isAdmin="isAdmin" :displayName="displayName" :navigationLocked="isSavingCollection" @close="sidebarOpen = false" @logout="logout" />

    <!-- Main -->
    <div class="admin-main">
      <!-- Header -->
      <header class="admin-header">
        <div class="header-left">
          <button class="btn-hamburger" @click="sidebarOpen = true">
            <i class="fa-solid fa-bars"></i>
          </button>
          <div class="header-text">
            <h1>대화 주제 설정</h1>
            <p>최대 5개의 대화 주제를 등록하여 문서군별로 분리 저장할 수 있습니다.</p>
          </div>
        </div>
        <div class="collections-badge">
          <i class="fa-solid fa-database"></i>
          {{ savedCollectionCount }} / 5 등록됨
        </div>
      </header>

      <!-- Content: 관리자·일반 사용자 동일 UI -->
      <div class="admin-content">
        <div class="card collection-card" v-for="(col, idx) in collections" :key="col.collection_id ?? col._tmpKey">
          <div class="card-title-row">
            <div class="card-title"><i class="fa-solid fa-layer-group"></i> 대화 주제 {{ idx + 1 }}</div>
            <div class="slot-meta">
              <span class="doc-count"> <i class="fa-solid fa-file-lines"></i> 문서 {{ col.document_count }}개 </span>
            </div>
          </div>
          <div class="slot-form compact-slot-form">
            <div class="form-row">
              <div class="form-group">
                <label>대화 주제</label>
                <input v-model="col._editName" type="text" placeholder="대화 주제 입력" :disabled="col._saving" />
              </div>
              <div class="form-group flex-2">
                <label>설명 <span class="label-hint">(선택)</span></label>
                <input v-model="col._editDescription" type="text" placeholder="대화 주제 설명 입력" :disabled="col._saving" />
              </div>
            </div>
            <div class="slot-actions compact-actions">
              <button class="btn-save icon-action" :disabled="col._saving || !col._editName.trim()" @click="saveCollection(col)" title="Save">
                <i v-if="!col._saving" class="fa-solid fa-floppy-disk"></i>
                <span v-else class="spinner"></span>
              </button>
              <button class="btn-delete" :disabled="isSavingCollection" @click="confirmDelete(col)"><i class="fa-solid fa-trash"></i> 삭제</button>
            </div>
          </div>
        </div>

        <div class="card add-card" v-if="savedCollectionCount < 5">
          <button class="btn-add" :disabled="isAdding" @click="addCollection"><i class="fa-solid fa-plus"></i> 새 대화 주제 추가</button>
        </div>
        <div class="card add-card disabled-card" v-else>
          <div class="max-notice">
            <i class="fa-solid fa-circle-info"></i>
            최대 5개까지 등록 가능합니다.
          </div>
        </div>

        <AppToast :message="alertMessage" :type="alertType" admin-position @close="alertMessage = ''" />
      </div>
    </div>

    <!-- Delete Confirm Dialog -->
    <!-- 2026.05.04(sooyeon.choi) 수정 - 삭제가 Qdrant 벡터 포함 완전 삭제로 변경됨에 따라 문구 업데이트 -->
    <div v-if="deleteTarget" class="dialog-overlay" @click.self="deleteTarget = null">
      <div class="dialog-box">
        <div class="dialog-title">
          <i class="fa-solid fa-triangle-exclamation" style="color: #ef4444"></i>
          대화 주제 삭제 확인
        </div>
        <p class="dialog-msg">
          "<strong>{{ deleteTarget.collection_name }}</strong
          >" 대화 주제를 삭제하시겠습니까?<br />
          <span class="dialog-hint">
            <i class="fa-solid fa-circle-exclamation" style="color: #ef4444"></i>
            업로드된 문서 {{ deleteTarget.document_count }}개가 모두 삭제됩니다.<br />
            삭제 후 복구할 수 없습니다.
          </span>
        </p>
        <div class="dialog-actions">
          <button class="btn-cancel" @click="deleteTarget = null">취소</button>
          <button class="btn-confirm-delete" :disabled="isSavingCollection" @click="doDelete">삭제</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
// 2026.04.01(sooyeon.choi) 수정 - 멀티대화 주제 관리 기능 추가
import { useRouter } from 'vue-router';
import AdminSidebar from '../components/AdminSidebar.vue';
import AppToast from '../components/AppToast.vue';
import PageHeader from '../components/PageHeader.vue';
import { useCollectionSettings } from '../composables/useCollectionSettings';

export default {
  components: { AdminSidebar, AppToast, PageHeader },
  setup() {
    const router = useRouter();
    return useCollectionSettings({ router });
  },
};
</script>

<style scoped>
/* 2026.04.01(sooyeon.choi) 수정 - 멀티대화 주제 관리 기능 추가 */
* {
  box-sizing: border-box;
}

.admin-layout {
  display: flex;
  height: 100dvh;
  background: #f1f5f9;
  overflow: hidden;
  font-family: 'Inter', 'Apple SD Gothic Neo', sans-serif;
}

/* ── Main ── */
.admin-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
.admin-header {
  background: white;
  border-bottom: 1px solid #e2e8f0;
  padding: 1.25rem 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  gap: 1rem;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}
.header-text {
  min-width: 0;
}
.btn-hamburger {
  display: none;
  background: none;
  border: none;
  color: #64748b;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  flex-shrink: 0;
}
.btn-hamburger:hover {
  background: #f1f5f9;
  color: #1e293b;
}
.admin-header h1 {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 0.2rem;
}
.admin-header p {
  font-size: 0.85rem;
  color: #64748b;
}
.collections-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #eff6ff;
  color: #2563eb;
  padding: 0.4rem 0.85rem;
  border-radius: 20px;
  font-size: 0.82rem;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.admin-content {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* ── Cards ── */
.card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 1rem;
}
.collection-card {
  padding: 0.85rem 1rem;
}
.card-title {
  font-size: 0.88rem;
  font-weight: 600;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.65rem;
  flex-wrap: wrap;
  gap: 0.5rem;
}

/* ── Slot Form ── */
.slot-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.compact-slot-form {
  flex-direction: row;
  align-items: end;
  gap: 0.75rem;
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 0.75rem;
  flex: 1;
  min-width: 0;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.form-group label {
  font-size: 0.76rem;
  font-weight: 500;
  color: #374151;
}
.label-hint {
  font-weight: 400;
  color: #9ca3af;
}
.form-group input {
  border: 1px solid #d1d5db;
  border-radius: 7px;
  padding: 0.48rem 0.65rem;
  font-size: 0.84rem;
  color: #374151;
  outline: none;
  transition: border-color 0.15s;
}
.form-group input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}
.form-group input:disabled {
  background: #f3f4f6;
  cursor: not-allowed;
}

.slot-actions {
  display: flex;
  gap: 0.5rem;
}
.compact-actions {
  align-items: center;
  flex-shrink: 0;
  padding-bottom: 0;
}
.btn-save {
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.55rem 1.25rem;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: background 0.15s;
}
.icon-action {
  min-width: 36px;
  width: 36px;
  height: 36px;
  padding: 0;
  justify-content: center;
  border-radius: 7px;
  overflow: hidden;
}
.icon-action .spinner {
  width: 14px;
  height: 14px;
}
.btn-save:hover:not(:disabled) {
  background: #1d4ed8;
}
.btn-save:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
.btn-delete {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
  border-radius: 8px;
  padding: 0.55rem 1.25rem;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s;
}
.btn-delete:hover:not(:disabled) {
  background: #fee2e2;
}
.btn-delete:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.doc-count {
  font-size: 0.76rem;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ── Add Card ── */
.add-card {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem;
}
.btn-add {
  background: #f8fafc;
  color: #2563eb;
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  padding: 0.75rem 1.5rem;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.15s;
  width: 100%;
  justify-content: center;
}
.btn-add:hover:not(:disabled) {
  border-color: #3b82f6;
  background: #eff6ff;
}
.btn-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.disabled-card {
  background: #f8fafc;
}
.max-notice {
  color: #64748b;
  font-size: 0.88rem;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── Delete Dialog ── */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
}
.dialog-box {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  width: 400px;
  max-width: 90vw;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}
.dialog-title {
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 1rem;
}
.dialog-msg {
  font-size: 0.9rem;
  color: #374151;
  line-height: 1.6;
  margin-bottom: 1.25rem;
}
.dialog-hint {
  font-size: 0.8rem;
  color: #94a3b8;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
.btn-cancel {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
  cursor: pointer;
}
.btn-cancel:hover {
  background: #e2e8f0;
}
.btn-confirm-delete {
  background: #ef4444;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
}
.btn-confirm-delete:hover:not(:disabled) {
  background: #dc2626;
}
.btn-confirm-delete:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── Spinner ── */
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.uploading-text {
  display: flex;
  align-items: center;
  gap: 8px;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.input-readonly {
  background: #f8fafc !important;
  color: #64748b;
  cursor: default;
}
.select-add {
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 0.6rem 0.75rem;
  font-size: 0.88rem;
  color: #374151;
  outline: none;
  width: 100%;
  transition: border-color 0.15s;
  background: white;
}
.select-add:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .btn-hamburger {
    display: flex;
  }
  .admin-header {
    padding: 1rem;
  }
  .admin-header p {
    display: none;
  }
  .admin-content {
    padding: 1rem;
  }
  .card {
    padding: 1rem;
  }
  .compact-slot-form {
    flex-direction: column;
    align-items: stretch;
  }
  .form-row {
    grid-template-columns: 1fr;
  }
  .compact-actions {
    justify-content: flex-end;
  }
}

/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
.dialog-box {
  max-width: calc(100vw - 32px);
  max-height: calc(100dvh - 32px);
  overflow-y: auto;
}
/* 2026.11.03(woojin.jung) 수정 - 태블릿 가로는 데스크톱, 세로는 모바일 레이아웃(사이드바 숨김) */
@media (max-width: 768px), (max-width: 1024px) and (orientation: portrait), (max-width: 1024px) and (max-height: 500px) {
  .btn-hamburger {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
  }
}
@media (max-width: 768px) {
  .icon-action {
    min-width: 40px;
    width: 40px;
    height: 40px;
  }
  .btn-delete {
    height: 40px;
  }
  .dialog-box {
    padding: 1.25rem;
  }
}
</style>
