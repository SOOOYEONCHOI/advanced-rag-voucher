<!-- 2026.04.01(sooyeon.choi) 수정 - 멀티대화 주제 관리 기능 추가 -->
<!-- 2026.11.12(woojin.jung) 수정 - 목록 + 상세(기본 정보 / 채팅 시작 화면 / 미리보기 탭) + 변경 시에만 나타나는 하단 저장 바로 개편 -->
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
      <div class="settings-body" :class="{ 'show-detail': mobileDetail }">
        <!-- 2026.11.12(woojin.jung) 추가 - 왼쪽: 대화 주제 목록 -->
        <nav class="topic-list" aria-label="대화 주제 목록">
          <div class="topic-list-title">
            <span>대화 주제</span><span>{{ savedCollectionCount }} / {{ maxCollections }}</span>
          </div>
          <button
            v-for="col in collections"
            :key="keyOf(col)"
            type="button"
            class="topic-item"
            :class="{ active: keyOf(col) === selectedKey, 'is-new': col._isNew }"
            :disabled="isSavingCollection"
            @click="selectCollection(col)"
          >
            <span class="topic-icon"><i class="fa-solid" :class="col._isNew ? 'fa-pen' : 'fa-layer-group'"></i></span>
            <span class="topic-text">
              <span class="topic-name">{{ col._draft.name.trim() || '새 대화 주제' }}</span>
              <span class="topic-meta">
                <template v-if="col._isNew">작성 중 · 저장 전</template>
                <template v-else>문서 {{ col.document_count }}개<template v-if="col._faqLoaded"> · 추천 질문 {{ col._saved.recommended.length }}개</template></template>
              </span>
            </span>
            <span v-if="!col._isNew && changesOf(col).any" class="unsaved-badge">저장 안 됨</span>
            <i class="fa-solid fa-chevron-right topic-chev"></i>
          </button>
          <div v-if="collections.length === 0" class="list-empty">등록된 대화 주제가 없습니다.</div>
          <button
            type="button"
            class="btn-add-topic"
            :disabled="savedCollectionCount >= maxCollections || collections.some((c) => c._isNew) || isSavingCollection"
            @click="addCollection"
          >
            <i class="fa-solid fa-plus"></i> 새 대화 주제
          </button>
          <div v-if="savedCollectionCount >= maxCollections" class="list-hint">최대 5개까지 등록할 수 있습니다.</div>
        </nav>

        <!-- 2026.11.12(woojin.jung) 추가 - 오른쪽: 선택한 대화 주제 상세 (선택이 바뀌면 다시 그려 스크롤 초기화) -->
        <section v-for="col in currentCollection ? [currentCollection] : []" :key="keyOf(col)" class="detail" :class="{ 'has-bar': currentChanges.any }">
          <div class="detail-head">
            <button type="button" class="btn-back" aria-label="목록으로" @click="mobileDetail = false"><i class="fa-solid fa-arrow-left"></i></button>
            <h2 class="detail-title" :class="{ placeholder: !col._draft.name.trim() }">{{ col._draft.name.trim() || '새 대화 주제' }}</h2>
            <span v-if="!col._isNew" class="detail-meta"><i class="fa-solid fa-file-lines"></i> 문서 {{ col.document_count }}개</span>
          </div>

          <div class="tabs" role="tablist">
            <button type="button" role="tab" class="tab" :class="{ active: activeTab === 'basic' }" :aria-selected="activeTab === 'basic'" @click="activeTab = 'basic'">
              기본 정보<span v-if="currentChanges.basic" class="dot" title="변경됨"></span>
            </button>
            <button type="button" role="tab" class="tab" :class="{ active: activeTab === 'faq' }" :aria-selected="activeTab === 'faq'" @click="activeTab = 'faq'">
              <i class="fa-regular fa-comment-dots"></i> 채팅 시작 화면<span v-if="currentChanges.faq" class="dot" title="변경됨"></span>
            </button>
            <button type="button" role="tab" class="tab" :class="{ active: activeTab === 'preview' }" :aria-selected="activeTab === 'preview'" @click="activeTab = 'preview'">
              <i class="fa-regular fa-eye"></i> 미리보기
            </button>
          </div>

          <div class="detail-body">
            <!-- 기본 정보 -->
            <template v-if="activeTab === 'basic'">
              <div class="basic-form">
                <p v-if="!col.can_update" class="readonly-note"><i class="fa-solid fa-lock"></i> 대화 주제를 만든 사용자나 관리자만 수정할 수 있습니다.</p>
                <div class="form-group" :class="{ invalid: col._touched && !col._draft.name.trim() }">
                  <label for="collectionName">대화 주제</label>
                  <input id="collectionName" v-model="col._draft.name" type="text" placeholder="대화 주제 입력" :disabled="isSavingCollection || !col.can_update" @blur="col._touched = true" />
                  <span v-if="col._touched && !col._draft.name.trim()" class="field-error">대화 주제 이름을 입력해 주세요.</span>
                </div>
                <div class="form-group">
                  <label for="collectionDesc">설명 <span class="label-hint">(선택)</span></label>
                  <input id="collectionDesc" v-model="col._draft.desc" type="text" placeholder="대화 주제 설명 입력" :disabled="isSavingCollection || !col.can_update" />
                </div>
              </div>
              <div v-if="!col._isNew && col.can_delete" class="danger-zone">
                <div>
                  <strong>대화 주제 삭제</strong>
                  <p>업로드된 문서 {{ col.document_count }}개와 채팅 시작 화면 질문이 함께 삭제되며 복구할 수 없습니다.</p>
                </div>
                <button type="button" class="btn-delete" :disabled="isSavingCollection" @click="confirmDelete(col)"><i class="fa-solid fa-trash"></i> 삭제</button>
              </div>
            </template>

            <!-- 채팅 시작 화면 질문: 추천 질문 등록(최대 5개) + 많이 찾는 질문 확인·숨기기 -->
            <template v-else-if="activeTab === 'faq'">
              <p v-if="!col.can_update" class="readonly-note"><i class="fa-solid fa-lock"></i> 대화 주제를 만든 사용자나 관리자만 시작 화면 질문을 관리할 수 있습니다.</p>
              <p v-else-if="!col._faqLoaded" class="readonly-note error"><i class="fa-solid fa-circle-exclamation"></i> 시작 화면 질문을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>
              <template v-else>
                <p class="faq-intro">
                  사용자가 새 대화를 시작할 때 보이는 질문입니다. 누르면 바로 질문이 전송됩니다.
                  <button type="button" class="link-btn" @click="activeTab = 'preview'">미리보기 <i class="fa-solid fa-arrow-right"></i></button>
                </p>
                <div class="faq-panel">
                  <div class="faq-box registered">
                    <div class="faq-box-head">
                      <i class="fa-solid fa-thumbtack"></i>
                      <strong>추천 질문</strong>
                      <span class="faq-count">{{ col._draft.recommended.length }} / {{ maxRecommendedQuestions }}</span>
                    </div>
                    <p class="faq-box-desc">직접 등록한 질문입니다. 채팅 시작 화면에 아래 순서대로 표시됩니다.</p>
                    <ol class="q-list">
                      <li v-for="(question, qIdx) in col._draft.recommended" :key="qIdx" class="q-row">
                        <span class="q-num">{{ qIdx + 1 }}</span>
                        <input v-model="col._draft.recommended[qIdx]" class="q-input" :maxlength="maxQuestionLength" :aria-label="`추천 질문 ${qIdx + 1}`" :disabled="isSavingCollection" />
                        <button type="button" class="q-btn move" :disabled="qIdx === 0 || isSavingCollection" title="위로" @click="moveRecommendedQuestion(col, qIdx, -1)">
                          <i class="fa-solid fa-arrow-up"></i>
                        </button>
                        <button type="button" class="q-btn move" :disabled="qIdx === col._draft.recommended.length - 1 || isSavingCollection" title="아래로" @click="moveRecommendedQuestion(col, qIdx, 1)">
                          <i class="fa-solid fa-arrow-down"></i>
                        </button>
                        <button type="button" class="q-btn danger" :disabled="isSavingCollection" title="삭제" @click="removeRecommendedQuestion(col, qIdx)">
                          <i class="fa-solid fa-trash"></i>
                        </button>
                      </li>
                      <li v-if="col._draft.recommended.length === 0" class="q-empty">등록된 추천 질문이 없습니다. 시작 화면에는 많이 찾는 질문만 표시됩니다.</li>
                    </ol>
                    <div v-if="col._draft.recommended.length < maxRecommendedQuestions" class="q-add">
                      <input
                        v-model="col._newQuestion"
                        class="q-input"
                        placeholder="예) 볼트 체결 토크 기준값은?"
                        :maxlength="maxQuestionLength"
                        :disabled="isSavingCollection"
                        @keyup.enter="addRecommendedQuestion(col)"
                      />
                      <button type="button" class="q-add-btn" :disabled="!col._newQuestion.trim() || isSavingCollection" @click="addRecommendedQuestion(col)">
                        <i class="fa-solid fa-plus"></i> 추가
                      </button>
                    </div>
                    <div v-else class="q-limit"><i class="fa-solid fa-circle-info"></i> 최대 {{ maxRecommendedQuestions }}개까지 등록할 수 있습니다.</div>
                  </div>

                  <div class="faq-box popular">
                    <div class="faq-box-head">
                      <i class="fa-solid fa-arrow-trend-up"></i>
                      <strong>많이 찾는 질문</strong>
                      <span class="faq-count">자동 · 최근 {{ col._popularDays }}일</span>
                    </div>
                    <p class="faq-box-desc">답변에 성공한 질의 로그를 비슷한 질문끼리 묶어 상위 5개를 표시합니다. ‘별로예요’ 평가를 받았거나 추천 질문과 겹치는 질문은 제외됩니다.</p>
                    <ol class="q-list">
                      <li v-for="(item, pIdx) in visiblePopular(col)" :key="item.question" class="pop-row">
                        <span class="pop-rank">{{ pIdx + 1 }}</span>
                        <span class="pop-q" :title="item.question">{{ item.question }}</span>
                        <span class="pop-cnt">{{ item.count }}회</span>
                        <button type="button" class="pop-hide" :disabled="isSavingCollection" title="시작 화면에 표시하지 않음" @click="hidePopularQuestion(col, item.question)">
                          <i class="fa-regular fa-eye-slash"></i> 숨기기
                        </button>
                      </li>
                      <li v-if="visiblePopular(col).length === 0" class="pop-empty">
                        {{ col._isNew ? '대화 주제를 만들고 질문이 쌓이면 자동으로 표시됩니다.' : '아직 집계된 질문이 없습니다. 질문이 쌓이면 자동으로 표시됩니다.' }}
                      </li>
                    </ol>
                    <template v-if="col._draft.hidden.length">
                      <div class="pop-sub">숨긴 질문 {{ col._draft.hidden.length }}개 · 다시 표시하면 저장 후 집계에 포함됩니다.</div>
                      <ol class="q-list">
                        <li v-for="question in col._draft.hidden" :key="question" class="pop-row hidden-q">
                          <span class="pop-rank">–</span>
                          <span class="pop-q" :title="question">{{ question }}</span>
                          <button type="button" class="pop-hide" :disabled="isSavingCollection" @click="unhidePopularQuestion(col, question)">
                            <i class="fa-regular fa-eye"></i> 다시 표시
                          </button>
                        </li>
                      </ol>
                    </template>
                  </div>
                </div>
              </template>
            </template>

            <!-- 미리보기: 사용자 채팅 시작 화면 (ChatView.vue 시작 화면과 같은 모양, 저장 전 편집 내용 반영) -->
            <template v-else>
              <p v-if="!col.can_update || !col._faqLoaded" class="readonly-note"><i class="fa-solid fa-circle-info"></i> 시작 화면 질문을 불러올 수 없어 미리보기를 표시할 수 없습니다.</p>
              <template v-else>
                <p class="preview-note">
                  <i class="fa-regular fa-eye"></i>
                  사용자 채팅 시작 화면입니다. <b v-if="currentChanges.faq">저장하지 않은 변경이 반영된 모습입니다.</b><template v-else>현재 저장된 상태입니다.</template>
                </p>
                <div class="preview-frame">
                  <div class="faq-welcome">
                    <div class="welcome-icon"><i class="fa-solid fa-robot"></i></div>
                    <h3>무엇을 도와드릴까요?</h3>
                    <p>
                      {{ col._draft.name.trim() || '새 대화 주제' }} 문서를 기반으로 답변합니다.
                      <template v-if="previewRecommended(col).length || visiblePopular(col).length"> 아래 질문을 눌러 바로 시작해 보세요.</template>
                    </p>
                    <div v-if="previewRecommended(col).length || visiblePopular(col).length" class="faq-columns" :class="{ single: !previewRecommended(col).length || !visiblePopular(col).length }">
                      <section v-if="previewRecommended(col).length" class="faq-group registered" aria-label="추천 질문">
                        <div class="faq-group-head"><i class="fa-solid fa-thumbtack"></i><strong>추천 질문</strong></div>
                        <div class="faq-list">
                          <div v-for="question in previewRecommended(col)" :key="question" class="faq-item">
                            <span class="faq-pin"><i class="fa-solid fa-circle"></i></span>
                            <span class="faq-q">{{ question }}</span>
                          </div>
                        </div>
                      </section>
                      <section v-if="visiblePopular(col).length" class="faq-group popular" aria-label="많이 찾는 질문">
                        <div class="faq-group-head"><i class="fa-solid fa-arrow-trend-up"></i><strong>많이 찾는 질문</strong><span>최근 {{ col._popularDays }}일</span></div>
                        <div class="faq-list">
                          <div v-for="(item, pIdx) in visiblePopular(col)" :key="item.question" class="faq-item">
                            <span class="faq-rank">{{ pIdx + 1 }}</span>
                            <span class="faq-q">{{ item.question }}</span>
                            <span class="faq-cnt">{{ item.count }}회</span>
                          </div>
                        </div>
                      </section>
                    </div>
                    <p v-else class="preview-empty">표시할 질문이 없어 안내 문구만 보입니다.</p>
                  </div>
                </div>
              </template>
            </template>
          </div>

          <!-- 하단 저장 바: 변경이 있을 때만 표시 -->
          <Transition name="save-bar">
            <div v-if="currentChanges.any" class="save-bar" role="region" aria-label="저장">
              <div class="save-bar-text">
                <i class="fa-solid fa-circle-exclamation"></i>
                <span>
                  {{ col._isNew ? '새 대화 주제를 아직 저장하지 않았습니다' : '저장하지 않은 변경이 있습니다' }}
                  <small v-if="!col._isNew">({{ [currentChanges.basic && '기본 정보', currentChanges.faq && '시작 화면 질문'].filter(Boolean).join(' · ') }})</small>
                </span>
              </div>
              <button type="button" class="btn-bar-cancel" :disabled="isSavingCollection" @click="discardChanges">{{ col._isNew ? '취소' : '되돌리기' }}</button>
              <button type="button" class="btn-save" :disabled="isSavingCollection || !col._draft.name.trim()" :title="col._draft.name.trim() ? '' : '대화 주제 이름을 입력해 주세요'" @click="saveCollection">
                <span v-if="isSavingCollection" class="spinner"></span>
                <i v-else class="fa-solid fa-floppy-disk"></i>
                {{ col._isNew ? '만들기' : '저장' }}
              </button>
            </div>
          </Transition>
        </section>
        <section v-if="!currentCollection" class="detail detail-empty">
          <i class="fa-solid fa-layer-group"></i>
          <p>대화 주제를 추가하면 여기에서 설정할 수 있습니다.</p>
        </section>

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

    <!-- 2026.11.12(woojin.jung) 추가 - 저장하지 않은 변경 확인 (다른 대화 주제 선택·메뉴 이동·로그아웃) -->
    <div v-if="unsavedDialog" class="dialog-overlay" @click.self="resolveUnsaved('keep')">
      <div class="dialog-box" role="dialog" aria-modal="true">
        <div class="dialog-title">
          <i class="fa-solid fa-circle-exclamation" style="color: #f59e0b"></i>
          저장하지 않은 변경이 있습니다
        </div>
        <p class="dialog-msg">
          "<strong>{{ currentCollection?._draft.name.trim() || '새 대화 주제' }}</strong>"의 변경 내용을 저장할까요?<br />
          <span class="dialog-hint">저장하지 않으면 변경 내용이 사라집니다.</span>
        </p>
        <div class="dialog-actions">
          <button class="btn-cancel btn-discard" @click="resolveUnsaved('discard')">저장 안 함</button>
          <button class="btn-cancel" @click="resolveUnsaved('keep')">계속 편집</button>
          <button class="btn-save" :disabled="isSavingCollection || !currentCollection?._draft.name.trim()" @click="resolveUnsaved('save')">저장 후 이동</button>
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
    const settings = useCollectionSettings({ router });
    // 2026.11.12(woojin.jung) 추가 - 미리보기에 표시할 추천 질문 (빈 칸 제외)
    const previewRecommended = (col) => col._draft.recommended.map((q) => q.trim()).filter(Boolean);
    return { ...settings, previewRecommended };
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

/* ── Form ── */
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

/* 2026.11.12(woojin.jung) 추가 - 목록 + 상세 레이아웃 */
.settings-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 1rem;
  padding: 1.25rem 2rem;
}
.topic-list {
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.topic-list-title {
  display: flex;
  justify-content: space-between;
  margin: 0 0.25rem 0.25rem;
  font-size: 0.74rem;
  font-weight: 600;
  color: #64748b;
}
.topic-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 0.75rem 0.85rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: white;
  color: #1e293b;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.topic-item:hover:not(:disabled) {
  border-color: #bfdbfe;
}
.topic-item:disabled {
  cursor: not-allowed;
}
.topic-item.active {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}
.topic-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 8px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  justify-content: center;
}
.topic-item.is-new .topic-icon {
  background: #f1f5f9;
  color: #64748b;
}
.topic-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.topic-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.86rem;
  font-weight: 600;
}
.topic-meta {
  font-size: 0.72rem;
  color: #94a3b8;
}
.unsaved-badge {
  flex-shrink: 0;
  padding: 1px 7px;
  border: 1px solid #fde68a;
  border-radius: 999px;
  background: #fffbeb;
  color: #b45309;
  font-size: 0.68rem;
}
.topic-chev {
  display: none;
  flex-shrink: 0;
  color: #cbd5e1;
  font-size: 0.72rem;
}
.list-empty,
.list-hint {
  font-size: 0.74rem;
  color: #94a3b8;
  text-align: center;
}
.list-empty {
  padding: 1rem 0.5rem;
}
.btn-add-topic {
  width: 100%;
  margin-top: 4px;
  padding: 0.7rem;
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  background: #f8fafc;
  color: #2563eb;
  font: inherit;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.btn-add-topic:hover:not(:disabled) {
  border-color: #3b82f6;
  background: #eff6ff;
}
.btn-add-topic:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}

.detail {
  position: relative;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: white;
}
.detail-empty {
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  color: #94a3b8;
  font-size: 0.85rem;
}
.detail-empty i {
  font-size: 1.5rem;
}
.detail-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 1rem 1.25rem 0;
}
.btn-back {
  display: none;
  padding: 4px 6px;
  border: none;
  border-radius: 6px;
  background: none;
  color: #64748b;
  font-size: 0.95rem;
  cursor: pointer;
}
.detail-title {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
}
.detail-title.placeholder {
  color: #94a3b8;
}
.detail-meta {
  flex-shrink: 0;
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.76rem;
  color: #64748b;
}
.tabs {
  display: flex;
  gap: 2px;
  padding: 0.75rem 1.25rem 0;
  border-bottom: 1px solid #e2e8f0;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}
.tab {
  margin-bottom: -1px;
  padding: 0.6rem 0.85rem;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  color: #64748b;
  font: inherit;
  font-size: 0.85rem;
  white-space: nowrap;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tab:hover {
  color: #1e293b;
}
.tab.active {
  border-bottom-color: #2563eb;
  color: #2563eb;
  font-weight: 600;
}
.tab .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f59e0b;
}
.detail-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 1.25rem;
}
.detail.has-bar .detail-body {
  padding-bottom: 5rem;
}

/* 기본 정보 탭 */
.basic-form {
  max-width: 640px;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.form-group.invalid input {
  border-color: #fca5a5;
}
.field-error {
  font-size: 0.74rem;
  color: #dc2626;
}
.readonly-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 0.75rem;
  font-size: 0.8rem;
  color: #64748b;
}
.readonly-note.error {
  color: #dc2626;
}
.danger-zone {
  max-width: 640px;
  margin-top: 2rem;
  padding: 0.9rem 1rem;
  border: 1px solid #fecaca;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 1rem;
}
.danger-zone strong {
  display: block;
  font-size: 0.84rem;
  color: #1e293b;
}
.danger-zone p {
  margin: 3px 0 0;
  font-size: 0.76rem;
  line-height: 1.5;
  color: #64748b;
}
.danger-zone .btn-delete {
  flex-shrink: 0;
  margin-left: auto;
}

/* 하단 저장 바 */
.save-bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1.25rem;
  background: #0f172a;
  color: #e2e8f0;
}
.save-bar-text {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.84rem;
}
.save-bar-text i {
  color: #fbbf24;
}
.save-bar-text small {
  font-size: 0.76rem;
  color: #94a3b8;
}
.btn-bar-cancel {
  padding: 0.5rem 1rem;
  border: 1px solid #475569;
  border-radius: 8px;
  background: none;
  color: #e2e8f0;
  font: inherit;
  font-size: 0.84rem;
  cursor: pointer;
}
.btn-bar-cancel:hover:not(:disabled) {
  background: #1e293b;
}
.btn-bar-cancel:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.save-bar-enter-active,
.save-bar-leave-active {
  transition: transform 0.2s ease;
}
.save-bar-enter-from,
.save-bar-leave-to {
  transform: translateY(100%);
}
.btn-discard {
  margin-right: auto;
  color: #dc2626;
}

/* 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면 질문 (추천 질문 등록 + 많이 찾는 질문 확인·숨기기) */
.faq-intro {
  margin: 0 0 0.9rem;
  font-size: 0.8rem;
  line-height: 1.55;
  color: #64748b;
}
.link-btn {
  padding: 0;
  border: none;
  background: none;
  color: #2563eb;
  font: inherit;
  cursor: pointer;
}
.faq-panel {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: 0.75rem;
}
.faq-box {
  min-width: 0;
  padding: 0.8rem;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #f8fafc;
}
.faq-box-head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 0.3rem;
}
.faq-box-head i {
  font-size: 0.8rem;
}
.faq-box.registered .faq-box-head i {
  color: #2563eb;
}
.faq-box.popular .faq-box-head i {
  color: #ea580c;
}
.faq-box-head strong {
  font-size: 0.82rem;
  color: #1e293b;
}
.faq-count {
  margin-left: auto;
  font-size: 0.74rem;
  color: #64748b;
}
.faq-box-desc {
  margin: 0 0 0.6rem;
  font-size: 0.74rem;
  line-height: 1.5;
  color: #64748b;
}
.q-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.q-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.q-num {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  border-radius: 6px;
  background: #e0e7ff;
  color: #3730a3;
  font-size: 0.72rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.q-input {
  flex: 1;
  min-width: 0;
  border: 1px solid #d1d5db;
  border-radius: 7px;
  padding: 0.42rem 0.6rem;
  background: white;
  font: inherit;
  font-size: 0.82rem;
  color: #374151;
  outline: none;
}
.q-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}
.q-btn {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: white;
  color: #64748b;
  font-size: 0.75rem;
  cursor: pointer;
}
.q-btn:hover:not(:disabled) {
  background: #f1f5f9;
  color: #1e293b;
}
.q-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.q-btn.danger:hover:not(:disabled) {
  background: #fef2f2;
  border-color: #fecaca;
  color: #dc2626;
}
.q-add {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.q-add .q-input {
  border-style: dashed;
}
.q-add-btn {
  flex-shrink: 0;
  padding: 0 0.8rem;
  border: 1px solid #bfdbfe;
  border-radius: 7px;
  background: #eff6ff;
  color: #2563eb;
  font: inherit;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}
.q-add-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.q-empty {
  padding: 0.55rem 0.2rem;
  font-size: 0.78rem;
  color: #94a3b8;
}
.q-limit {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 0.74rem;
  color: #64748b;
}
.pop-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0.42rem 0.55rem;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: white;
}
.pop-rank {
  width: 18px;
  flex-shrink: 0;
  text-align: center;
  font-size: 0.78rem;
  font-weight: 700;
  color: #ea580c;
}
.pop-q {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.82rem;
  color: #334155;
}
.pop-cnt {
  flex-shrink: 0;
  font-size: 0.72rem;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}
.pop-hide {
  flex-shrink: 0;
  padding: 3px 6px;
  border: none;
  border-radius: 5px;
  background: none;
  color: #94a3b8;
  font: inherit;
  font-size: 0.72rem;
  cursor: pointer;
}
.pop-hide:hover:not(:disabled) {
  background: #f1f5f9;
  color: #475569;
}
.pop-row.hidden-q {
  border-style: dashed;
  background: #f8fafc;
}
.pop-row.hidden-q .pop-q {
  color: #94a3b8;
  text-decoration: line-through;
}
.pop-sub {
  margin: 10px 0 6px;
  font-size: 0.72rem;
  color: #94a3b8;
}
.pop-empty {
  padding: 0.7rem;
  border: 1px dashed #e2e8f0;
  border-radius: 7px;
  background: white;
  text-align: center;
  font-size: 0.78rem;
  color: #94a3b8;
}

/* 2026.11.12(woojin.jung) 추가 - 미리보기 (ChatView.vue 시작 화면 스타일과 동일하게 유지) */
.preview-note {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 0.75rem;
  font-size: 0.76rem;
  color: #64748b;
}
.preview-frame {
  padding: 2rem 1.25rem;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
}
.faq-welcome {
  max-width: 820px;
  margin: 0 auto;
  text-align: center;
  color: #64748b;
}
.faq-welcome .welcome-icon {
  width: 52px;
  height: 52px;
  margin: 0 auto 0.9rem;
  border-radius: 14px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 1.4rem;
  display: flex;
  align-items: center;
  justify-content: center;
}
.faq-welcome h3 {
  margin: 0 0 0.4rem;
  font-size: 1.4rem;
  color: #1e293b;
}
.faq-welcome > p {
  margin: 0 0 1.5rem;
  font-size: 0.9rem;
}
.faq-welcome > p.preview-empty {
  margin: 0;
  font-size: 0.82rem;
  color: #94a3b8;
}
.faq-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  text-align: left;
}
.faq-columns.single {
  grid-template-columns: minmax(0, 420px);
  justify-content: center;
}
.faq-group {
  min-width: 0;
  padding: 0.85rem;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}
.faq-group-head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0 0.15rem 0.6rem;
}
.faq-group-head i {
  font-size: 0.82rem;
}
.faq-group.registered .faq-group-head i {
  color: #2563eb;
}
.faq-group.popular .faq-group-head i {
  color: #ea580c;
}
.faq-group-head strong {
  font-size: 0.88rem;
  color: #1e293b;
}
.faq-group-head span {
  margin-left: auto;
  font-size: 0.72rem;
  color: #94a3b8;
}
.faq-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.faq-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0.62rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #fff;
  color: #1e293b;
}
.faq-pin,
.faq-rank {
  width: 18px;
  flex-shrink: 0;
  text-align: center;
}
.faq-pin {
  font-size: 0.4rem;
  color: #93c5fd;
}
.faq-rank {
  font-size: 0.8rem;
  font-weight: 700;
  color: #ea580c;
}
.faq-q {
  flex: 1;
  min-width: 0;
  font-size: 0.86rem;
  line-height: 1.45;
}
.faq-cnt {
  flex-shrink: 0;
  font-size: 0.7rem;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 1100px) {
  .faq-panel {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 900px) {
  .settings-body {
    grid-template-columns: 220px minmax(0, 1fr);
    padding: 1rem;
  }
  .faq-columns {
    grid-template-columns: 1fr;
  }
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
  /* 2026.11.12(woojin.jung) 추가 - 모바일: 목록 화면 ↔ 상세 화면 전환, 순서 이동 버튼 숨김, 터치 영역 확대 */
  .settings-body {
    grid-template-columns: minmax(0, 1fr);
    padding: 1rem;
  }
  .settings-body.show-detail .topic-list,
  .settings-body:not(.show-detail) .detail {
    display: none;
  }
  .topic-chev,
  .btn-back {
    display: block;
  }
  .topic-item.active {
    border-color: #e2e8f0;
    box-shadow: none;
  }
  .detail-head {
    padding: 0.85rem 0.9rem 0;
  }
  .tabs {
    padding: 0.5rem 0.6rem 0;
  }
  .detail-body {
    padding: 1rem 0.9rem;
  }
  .q-btn.move {
    display: none;
  }
  .q-btn {
    width: 34px;
    height: 34px;
  }
  .danger-zone {
    flex-direction: column;
    align-items: stretch;
  }
  .danger-zone .btn-delete {
    margin-left: 0;
    justify-content: center;
  }
  .save-bar {
    padding: 0.7rem 0.9rem;
  }
  .save-bar-text small {
    display: none;
  }
  .preview-frame {
    padding: 1.25rem 0.75rem;
  }
  .dialog-actions {
    flex-wrap: wrap;
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
  .btn-delete {
    height: 40px;
  }
  .dialog-box {
    padding: 1.25rem;
  }
}
</style>
