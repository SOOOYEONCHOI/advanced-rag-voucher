<template>
  <div class="admin-layout">
    <AdminSidebar :isOpen="sidebarOpen" activePage="documents" :isAdmin="isAdmin" :displayName="displayName" :navigationLocked="isUploading" @close="sidebarOpen = false" @logout="logout" />

    <!-- Main -->
    <div class="admin-main">
      <!-- Header -->
      <header class="admin-header">
        <div class="header-left">
          <button class="btn-hamburger" @click="sidebarOpen = true">
            <i class="fa-solid fa-bars"></i>
          </button>
          <div class="header-text">
            <h1>문서 관리</h1>
            <p>문서를 업로드하면 파싱 → 청킹 → 임베딩 → Vector DB 저장까지 자동으로 처리됩니다.</p>
          </div>
        </div>
        <div class="collections-badge" v-if="registeredCollections.length > 0">
          <i class="fa-solid fa-database"></i>
          대화 주제 {{ registeredCollections.length }}개
        </div>
      </header>

      <!-- Content -->
      <div class="admin-content">
        <!-- Upload Card -->
        <div class="card upload-card">
          <div class="card-title"><i class="fa-solid fa-cloud-arrow-up"></i> 문서 업로드</div>

          <!-- Drop Zone -->
          <div
            class="drop-zone"
            :class="{ dragging: isDragging, 'has-file': uploadItems.length, disabled: isUploading }"
            :aria-disabled="isUploading"
            @dragover.prevent="onDragOver"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="onDrop"
            @click="openFilePicker"
          >
            <!-- 2026.08.27(sooyeon.choi) 수정 - OOXML Excel 4종만 허용하고 .xls 제외 -->
            <!-- 2026.10.16(sooyeon.choi) 추가 - 서버가 엑셀 전용 처리기(backend)를 쓰면 .xls도 선택 가능(acceptedExtensions) -->
            <input ref="fileInput" type="file" multiple style="display: none" :disabled="isUploading" :accept="acceptedExtensions" @change="onFileChange" />
            <div class="drop-placeholder">
              <i class="fa-solid fa-file-circle-plus drop-icon"></i>
              <p>파일을 드래그하거나 클릭하여 선택 · 최대 10개</p>
              <span>PDF · DOCX · PPTX · XLSX · 이미지</span>
            </div>
          </div>
          <p v-if="selectionMessage" class="form-error" role="alert">{{ selectionMessage }}</p>
          <div v-if="uploadItems.length" class="batch-selection">
            <span>선택 {{ uploadItems.length }}/10개 · 총 {{ formatFileSize(totalFileSize) }}</span>
            <!-- 2026.10.02(woojin.jung) 수정 - 보조 동작 버튼을 경고색이 아닌 텍스트 버튼으로 변경 -->
            <button class="btn-text" :disabled="isUploading || pendingItems.length > 0" @click="clearFile"><i class="fa-solid fa-trash-can"></i> 목록 비우기</button>
          </div>

          <!-- Form -->
          <div class="upload-form">
            <div class="form-row">
              <!-- 2026.04.01(sooyeon.choi) 수정 - 멀티대화 주제 관리 기능 추가 -->
              <div class="form-group">
                <label>대화 주제</label>
                <select v-model="form.collectionName" :disabled="isUploading || registeredCollections.length === 0">
                  <option value="" disabled>대화 주제를 선택하세요</option>
                  <option v-for="col in registeredCollections" :key="col.qdrant_name || col.collection_name" :value="col.qdrant_name || col.collection_name">{{ col.collection_name }}</option>
                </select>
                <div v-if="registeredCollections.length === 0" class="no-collection-hint"><i style="margin-right: 3px" class="fa-solid fa-circle-info"></i> 먼저 대화 주제를 등록해주세요</div>
              </div>
              <div class="form-group">
                <label>문서 유형 <span class="required">*</span></label>
                <select v-model="form.documentType" :disabled="isUploading">
                  <option v-for="option in documentTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
                <div v-if="documentTypeCompatibilityError" class="form-error">{{ documentTypeCompatibilityError }}</div>
                <div v-else class="form-hint">{{ selectedDocumentTypeDescription }}</div>
              </div>
              <!-- 2026.10.19(sooyeon.choi) 수정 - 공통 제품 모델 입력 제거: 아래 처리 현황의 파일별 모델명 입력으로 전환 -->
              <div class="form-group">
                <label>파서 선택</label>
                <!-- 2026.10.16(sooyeon.choi) 추가 - 선택 파일이 모두 엑셀 전용 처리기 대상이면 파서 선택 비활성 + 안내 -->
                <select v-model="form.parserType" :disabled="isUploading || allExcelIngestFiles">
                  <option value="docling">Docling API (PDF·DOCX·PPTX·이미지)</option>
                  <option value="pdfplumber">pdfplumber (PDF 전용, 빠름)</option>
                </select>
                <div v-if="hasExcelIngestFile" class="form-hint"><i class="fa-solid fa-circle-info"></i> 엑셀은 전용 처리기로 처리됩니다(문서 유형·파서 선택과 관계없음).</div>
              </div>
              <!-- <div class="form-group">
                <label>청크 크기 <span class="label-hint">(비우면 자동)</span></label>
                <input v-model.number="form.chunkSize" type="number" :disabled="isUploading" min="100" max="4000" />
              </div> -->
            </div>

            <!-- 2026.10.02(woojin.jung) 수정 - 업로드 버튼이 처리 상태 표시로 바뀌지 않도록 전송 중/처리 중 문구 분리 -->
            <button class="btn-upload" :disabled="!canUpload" @click="uploadDocument">
              <span v-if="isSubmitting" class="uploading-text"> <span class="spinner"></span> 파일 전송 중... </span>
              <span v-else-if="isUploading"> <i class="fa-solid fa-hourglass-half"></i> 처리가 끝나면 추가 업로드할 수 있습니다 </span>
              <span v-else> <i class="fa-solid fa-rocket"></i> {{ submissionItems.length ? `${submissionItems.length}개 업로드 시작` : '업로드할 파일을 선택하세요' }} </span>
            </button>
            <!-- 2026.10.19(sooyeon.choi) 추가 - 파일별 모델명 오류가 있으면 전송 차단 안내 -->
            <p v-if="hasModelError && !isUploading" class="form-error model-submit-error" role="alert">파일별 모델명을 확인하세요.</p>
          </div>

          <!-- 2026.10.02(woojin.jung) 수정 - 업로드 진행 현황 UI 개선(요약 통합·분할 진행 막대·단계 인디케이터·안내 문구 정리) -->
          <section v-if="uploadItems.length" class="batch-progress">
            <div class="batch-progress-header" aria-live="polite">
              <h2 class="batch-progress-title">처리 현황</h2>
              <span class="batch-progress-count"
                ><strong>{{ summary.total }}개 중 {{ summary.completed }}개 완료</strong></span
              >
              <span v-for="chip in summaryChips" :key="chip.key" class="summary-chip" :class="chip.key">{{ chip.label }} {{ chip.count }}</span>
              <div v-if="pendingItems.length" class="batch-monitor">
                <button v-if="isMonitoring" class="btn-text" :disabled="isSubmitting" title="자동 확인을 중지해도 서버의 문서 처리는 계속됩니다." @click="stopMonitoring">
                  <i class="fa-solid fa-pause"></i> 자동 확인 중지
                </button>
                <button v-else class="btn-text" :disabled="isSubmitting" @click="startMonitoring"><i class="fa-solid fa-rotate-right"></i> 자동 확인 재개</button>
              </div>
            </div>
            <div class="upload-progress-track overall-progress" role="progressbar" aria-label="전체 완료 문서 수" :aria-valuenow="summary.completed" :aria-valuemax="summary.total" aria-valuemin="0">
              <span v-for="segment in progressSegments" :key="segment.key" :class="segment.key" :style="{ width: `${segment.width}%` }"></span>
            </div>
            <p v-if="hasLongWait" class="batch-notice">30분 이상 대기 중인 문서가 있습니다. 대기 시간에는 앞선 문서의 처리 시간이 포함됩니다.</p>
            <p v-if="authBlocked" class="batch-notice error" role="alert">인증이 만료되었습니다. 다시 로그인한 뒤 진행하세요. 이미 접수된 문서는 서버에서 계속 처리됩니다.</p>
            <p v-if="pendingItems.length" class="batch-notice">
              <i class="fa-solid fa-circle-info"></i> 처리 중 새로고침하면 이 목록은 사라지지만, 서버 처리는 계속되며 완료 문서는 아래 문서 목록에 표시됩니다.
            </p>

            <ul class="upload-file-list">
              <!-- 2026.10.20(woojin.jung) 수정 - 행마다 반복되던 안내를 목록 머리글 한 곳으로 모음 -->
              <li class="upload-file-head">
                <span>파일</span>
                <!-- 2026.10.21(woojin.jung) 수정 - 브라우저 기본 title 툴팁 → 프로젝트 카드 스타일 도움말 팝오버(hover·키보드 포커스) -->
                <span class="upload-file-head-name">
                  모델명
                  <span class="help-pop">
                    <button type="button" class="help-pop-trigger" aria-label="모델명 안내" aria-describedby="modelNameHelp">
                      <i class="fa-regular fa-circle-question"></i>
                    </button>
                    <span id="modelNameHelp" class="help-pop-card" role="tooltip">
                      <span class="help-pop-title"><i class="fa-solid fa-tag"></i> 모델명이란?</span>
                      <span class="help-pop-desc">문서 목록과 버전 이력에서 이 문서를 가리키는 이름입니다.</span>
                      <span class="help-pop-list">
                        <span><i class="fa-solid fa-wand-magic-sparkles"></i> 파일명에서 자동으로 채워집니다</span>
                        <span><i class="fa-solid fa-code-branch"></i> 최신본을 바꿔도 그대로 유지됩니다</span>
                        <span><i class="fa-solid fa-pen"></i> 업로드 후에도 목록에서 수정할 수 있습니다</span>
                      </span>
                    </span>
                  </span>
                </span>
                <span>상태</span>
              </li>
              <li v-for="item in uploadItems" :key="item.clientId" class="upload-file" :class="item.status">
                <div class="upload-file-main">
                  <div class="upload-file-name">
                    <i class="fa-regular fa-file-lines"></i>
                    <strong :title="item.filename">{{ item.filename }}</strong>
                    <span class="upload-file-size">{{ formatFileSize(item.size) }}</span>
                  </div>
                  <!-- 2026.10.19(sooyeon.choi) 추가 - 파일별 모델명 입력(파일명 기본값, 전송 시작 후 잠금, UI-12) -->
                  <!-- 2026.10.20(woojin.jung) 수정 - 수정 가능할 때만 입력창, 전송 후에는 확정된 이름을 텍스트로 표시. 바꾼 이름은 파일명으로 되돌리기 제공 -->
                  <div class="upload-file-model">
                    <div v-if="canEditModel(item)" class="model-input-wrap">
                      <input
                        v-model="item.productModel"
                        type="text"
                        class="model-input"
                        :class="{ invalid: modelError(item), resettable: isModelNameEdited(item) }"
                        :aria-label="`${item.filename} 모델명`"
                        :aria-invalid="Boolean(modelError(item))"
                        :title="item.productModel"
                        placeholder="모델명 입력"
                      />
                      <button
                        v-if="isModelNameEdited(item)"
                        type="button"
                        class="btn-model-reset"
                        title="파일명으로 되돌리기"
                        :aria-label="`${item.filename} 모델명을 파일명으로 되돌리기`"
                        @click="resetModelName(item)"
                      >
                        <i class="fa-solid fa-rotate-left"></i>
                      </button>
                    </div>
                    <span v-else class="model-locked" :title="item.productModel"><span class="model-locked-label">모델명</span>{{ item.productModel || '-' }}</span>
                    <p v-if="modelError(item)" class="model-error" aria-live="polite">{{ modelError(item) }}</p>
                  </div>
                  <div class="upload-file-status">
                    <span class="upload-state" :class="item.status"
                      ><i v-if="progressAnimated(item)" class="fa-solid fa-spinner fa-spin upload-state-spinner" aria-hidden="true"></i>{{ uploadStateLabel(item) }}</span
                    >
                    <ol v-if="['running', 'failed', 'completed'].includes(item.status)" class="upload-steps" :aria-label="`${item.filename} 처리 단계`">
                      <li v-for="(step, index) in uploadSteps" :key="step.key" :class="uploadStepState(item, index)" :title="step.label"></li>
                    </ol>
                    <span class="upload-step-label">{{ uploadStatusLabel(item) }}</span>
                  </div>
                  <div v-if="hasRowActions" class="upload-file-actions">
                    <button
                      v-if="['selected', 'rejected'].includes(item.status)"
                      class="btn-text"
                      :disabled="isUploading"
                      :aria-label="`${item.filename} 선택 해제`"
                      @click="removeFile(item.clientId)"
                    >
                      <i class="fa-solid fa-xmark"></i> 제외
                    </button>
                    <button v-else-if="item.status === 'failed'" class="btn-text danger" :disabled="isSubmitting || item.retrying" @click="retryIngestJob(item)">
                      <i class="fa-solid fa-rotate-right"></i> {{ item.retrying ? '재시도 접수 중...' : '재시도' }}
                    </button>
                  </div>
                </div>
                <p v-if="validationError(item)" class="upload-file-message error">{{ validationError(item) }}</p>
                <p v-if="item.error" class="upload-file-message error">{{ item.error }}</p>
                <p v-if="item.monitorError" class="upload-file-message error">상태 확인 실패: {{ item.monitorError }}</p>
                <p v-if="item.status === 'submission_unknown'" class="upload-file-message">중복 업로드를 피하려면 아래 문서 목록에서 접수 여부를 확인한 뒤 다시 선택하세요.</p>
                <details v-if="item.result" class="batch-result">
                  <summary>처리 결과 · {{ item.result.total_pages ?? '-' }}페이지 · {{ item.result.chunk_count ?? '-' }}개 청크</summary>
                  <dl>
                    <dt>문서 유형</dt>
                    <dd>{{ docTypeLabel(item.result.doc_type) }} · {{ docTypeSourceLabel(item.result.doc_type_source) }}</dd>
                    <dt>대화 주제</dt>
                    <dd>{{ item.result.collection_name }}</dd>
                    <dt>Document ID</dt>
                    <dd>{{ item.result.document_id }}</dd>
                  </dl>
                </details>
              </li>
            </ul>
          </section>
        </div>

        <!-- Error Card -->
        <div v-if="uploadError" class="card error-card">
          <div class="card-title">
            <i class="fa-solid fa-circle-exclamation" style="color: #ef4444"></i>
            처리 실패
          </div>
          <p class="error-msg">{{ uploadError }}</p>
          <button class="btn-retry" @click="uploadError = null">닫기</button>
        </div>

        <AppToast :message="alertMessage" :type="alertType" admin-position @close="alertMessage = ''" />

        <!-- Documents Table -->
        <div class="card table-card">
          <!-- 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원 진행·완료·실패 상태 줄(목업 #pageStatus) -->
          <div v-if="pageStatus" class="page-status" :class="pageStatus.type" role="status">
            <i v-if="pageStatus.type === 'info'" class="fa-solid fa-spinner fa-spin"></i>
            <span>{{ pageStatus.text }}</span>
            <button class="page-status-close" aria-label="상태 안내 닫기" @click="pageStatus = null"><i class="fa-solid fa-xmark"></i></button>
          </div>
          <div class="card-title-row">
            <div class="card-title"><i class="fa-solid fa-list"></i> 업로드된 문서</div>
            <div class="table-filters">
              <select v-model="filterCollection" @change="loadDocuments">
                <option value="">전체 대화 주제</option>
                <option v-for="col in collectionsForFilter" :key="col.qdrant_name" :value="col.qdrant_name">{{ col.collection_name }}</option>
              </select>
              <button class="btn-refresh" @click="loadDocuments" title="새로고침">
                <i class="fa-solid fa-rotate-right"></i>
              </button>
            </div>
          </div>

          <div v-if="documents.length === 0" class="empty-table">
            <i class="fa-regular fa-folder-open"></i>
            <p>업로드된 문서가 없습니다.</p>
          </div>

          <div v-else class="table-scroll" :style="filenameColumnStyle" @mousedown="startFilenameResizeFromHeader">
            <table class="doc-table">
              <!-- 2026.10.19(sooyeon.choi) 수정 - 선두 모델명, 파일명(최신본), 현재 버전·최근 변경일 컬럼 추가(업로드 시각 → 최근 변경일) -->
              <!-- 2026.10.20(woojin.jung) 수정 - 모델명(굵게)·파일명(링크)을 한 셀 두 줄로 합쳐 관계를 드러냄 -->
              <colgroup>
                <col class="col-filename" />
                <col class="col-doc-type" />
                <col class="col-pages" />
                <col class="col-topic" />
                <col class="col-user" />
                <col class="col-parser" />
                <col class="col-version" />
                <col class="col-upload-time" />
                <col class="col-actions" />
              </colgroup>
              <thead>
                <tr>
                  <th class="th-filename">모델명 · 파일(최신본)</th>
                  <th>문서 유형</th>
                  <th>총 페이지</th>
                  <!-- <th>청크 수</th> -->
                  <th>대화주제</th>
                  <th>업로더</th>
                  <th>파서</th>
                  <th>현재 버전</th>
                  <th>최근 변경일</th>
                  <th>작업</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="doc in documents" :key="doc.document_id">
                  <!-- 2026.10.19(sooyeon.choi) 추가 - 모델명 표시·연필 아이콘 인라인 수정(저장/취소, Enter 저장·Esc 취소) -->
                  <!-- 2026.10.20(woojin.jung) 수정 - 모델명 클릭·연필로 수정(본인 문서만 연필 노출), 저장/취소는 아이콘 버튼 -->
                  <td class="td-filename">
                    <div v-if="editingModelId === doc.document_id" class="model-cell editing">
                      <input
                        v-model="editingModelValue"
                        v-focus
                        type="text"
                        class="model-input"
                        :class="{ invalid: modelEditError }"
                        aria-label="모델명"
                        placeholder="모델명 입력"
                        :aria-invalid="Boolean(modelEditError)"
                        :disabled="savingModelId === doc.document_id"
                        @keydown.enter.prevent="saveModelEdit(doc)"
                        @keydown.esc.prevent="cancelModelEdit"
                      />
                      <button class="btn-model-icon save" :disabled="savingModelId === doc.document_id" title="저장 (Enter)" aria-label="모델명 저장" @click="saveModelEdit(doc)">
                        <i :class="savingModelId === doc.document_id ? 'fa-solid fa-spinner fa-spin' : 'fa-solid fa-check'"></i>
                      </button>
                      <button class="btn-model-icon" :disabled="savingModelId === doc.document_id" title="취소 (Esc)" aria-label="모델명 수정 취소" @click="cancelModelEdit">
                        <i class="fa-solid fa-xmark"></i>
                      </button>
                      <p v-if="modelEditError" class="model-error" aria-live="polite">{{ modelEditError }}</p>
                    </div>
                    <div v-else class="model-cell">
                      <button
                        v-if="doc.can_edit"
                        class="model-name editable"
                        :disabled="Boolean(savingModelId)"
                        :title="`${doc.product_model || '-'} — 클릭하여 모델명 수정`"
                        @click="startModelEdit(doc)"
                      >
                        <span class="model-name-text">{{ doc.product_model || '-' }}</span>
                        <i class="fa-solid fa-pen" aria-hidden="true"></i>
                      </button>
                      <strong v-else class="model-name" :title="doc.product_model">{{ doc.product_model || '-' }}</strong>
                    </div>
                    <div class="filename-cell-content">
                      <i class="fa-regular fa-file-lines"></i>
                      <button class="filename-link" :disabled="openingDocId === doc.document_id" :title="`${doc.filename} — 원본 열기`" @click="openOriginalDocument(doc)">
                        <span class="filename-text">{{ doc.filename }}</span>
                        <i v-if="openingDocId === doc.document_id" class="fa-solid fa-spinner fa-spin"></i>
                      </button>
                    </div>
                  </td>
                  <td>
                    <span class="badge" :class="doc.doc_type">
                      {{ docTypeLabel(doc.doc_type) }}
                    </span>
                  </td>
                  <td>{{ doc.total_pages ?? '-' }}</td>
                  <!-- <td class="td-chunks">{{ doc.chunk_count ?? '-' }}</td> -->
                  <td>
                    {{ collectionTopicLabel(doc.collection_name) }}
                  </td>
                  <td>
                    {{ doc.uploaded_by || '-' }}
                  </td>
                  <td>{{ doc.parser_type }}</td>
                  <!-- 2026.10.19(sooyeon.choi) 추가 - 현재 버전(시스템 version_no)·최근 변경일(등록·모델명 수정 시각, KST) -->
                  <td>
                    <span class="version-badge">v{{ doc.version_no ?? 1 }}</span>
                    <!-- 2026.10.19(sooyeon.choi) 추가 - 최신본 변경 처리 중 표시(처리 중에는 현재 버전으로 검색·답변) -->
                    <span v-if="isVersionPending(doc)" class="version-pending" :title="`v${pendingVersionNo(doc)} 처리 중 — 완료 전까지 현재 버전으로 검색됩니다.`">
                      <i class="fa-solid fa-spinner fa-spin"></i> v{{ pendingVersionNo(doc) }}
                    </span>
                    <!-- 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원 처리 중 표시(완료 전까지 현재 버전으로 검색·답변) -->
                    <span v-else-if="restorePendingOf(doc)" class="version-pending" :title="`v${restorePendingOf(doc)} 복원 처리 중 — 완료 전까지 현재 버전으로 검색됩니다.`">
                      <i class="fa-solid fa-spinner fa-spin"></i> v{{ restorePendingOf(doc) }} 복원
                    </span>
                  </td>
                  <td class="td-time">{{ formatTime(doc.updated_at || doc.upload_timestamp) }}</td>
                  <!-- 2026.04.02(sooyeon.choi) - 문서 삭제 기능 추가 -->
                  <!-- 2026.10.19(sooyeon.choi) 수정 - [최신본 변경]·[버전 이력] 추가, 기존 삭제 버튼·권한 유지(처리 중에는 삭제 불가) -->
                  <td>
                    <div class="document-actions">
                      <!-- 2026.11.06(sooyeon.choi) 수정 - 복원 처리 중에도 최신본 변경·삭제 잠금(isDocumentBusy) -->
                      <button
                        v-if="versionReplaceEnabled"
                        class="btn-doc-action btn-latest-version"
                        :disabled="!doc.can_edit || isDocumentBusy(doc)"
                        :title="
                          !doc.can_edit ? '본인이 업로드한 문서만 최신본을 변경할 수 있습니다.' : isDocumentBusy(doc) ? '이 문서의 변경 작업을 처리 중입니다.' : '새 파일을 이 문서의 다음 버전으로 등록'
                        "
                        @click="openReplaceDialog(doc)"
                      >
                        <i class="fa-solid fa-arrow-up-from-bracket"></i><span>최신본 변경</span>
                      </button>
                      <button class="btn-doc-action btn-version-history" title="버전 이력" @click="openVersionHistory(doc)"><i class="fa-solid fa-clock-rotate-left"></i><span>버전 이력</span></button>
                      <button
                        class="btn-delete-doc"
                        :disabled="!doc.can_delete || deletingId === doc.document_id || isDocumentBusy(doc)"
                        @click="confirmDeleteDoc(doc)"
                        :title="!doc.can_delete ? '본인이 업로드한 문서만 개별 삭제할 수 있습니다.' : isDocumentBusy(doc) ? '변경 작업을 처리 중인 문서는 삭제할 수 없습니다.' : '문서 삭제'"
                      >
                        <i v-if="deletingId === doc.document_id" class="fa-solid fa-spinner fa-spin"></i>
                        <i v-else class="fa-solid fa-trash"></i>
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
    <!-- 2026.04.02(sooyeon.choi) - 문서 삭제 기능 추가 -->
    <div v-if="deleteDocTarget" class="dialog-overlay" @click.self="deleteDocTarget = null">
      <div class="dialog-box">
        <div class="dialog-title">
          <i class="fa-solid fa-triangle-exclamation" style="color: #ef4444"></i>
          문서 삭제 확인
        </div>
        <p class="dialog-msg">
          "<strong>{{ deleteDocTarget.filename }}</strong
          >" 문서를 삭제하시겠습니까?<br />
          <span class="dialog-hint">벡터 데이터와 업로드 이력이 모두 삭제됩니다.</span>
        </p>
        <div class="dialog-actions">
          <button class="btn-cancel" @click="deleteDocTarget = null">취소</button>
          <button class="btn-confirm-delete" @click="doDeleteDoc">삭제</button>
        </div>
      </div>
    </div>

    <!-- 2026.10.19(sooyeon.choi) 추가 - 최신본 변경 대화상자: 처리 완료 후 다음 버전으로 적용 -->
    <div v-if="replaceTarget" class="dialog-overlay" @click.self="closeReplaceDialog">
      <div class="dialog-box version-dialog" role="dialog" aria-modal="true" aria-labelledby="replaceDialogTitle">
        <div id="replaceDialogTitle" class="dialog-title"><i class="fa-solid fa-arrow-up-from-bracket" style="color: #2563eb"></i>최신본 변경</div>
        <p class="version-dialog-name">
          <strong>{{ replaceTarget.product_model || '-' }}</strong>
          <span>{{ replaceTarget.filename }} · 현재 v{{ replaceTarget.version_no ?? 1 }}</span>
        </p>
        <p class="dialog-hint">새 파일 처리가 완료되면 기존 문서의 다음 버전으로 적용됩니다. 처리 중에는 현재 버전으로 검색·답변하며, 실패하면 현재 버전을 그대로 유지합니다.</p>
        <label class="replacement-file" :class="{ disabled: replaceSubmitting }">
          <span class="replacement-file-button"><i class="fa-solid fa-file-circle-plus"></i> 새 파일 선택</span>
          <input type="file" :accept="acceptedExtensions" :disabled="replaceSubmitting" @change="onReplaceFileChange" />
          <strong class="replacement-file-name">{{ replaceFile ? replaceFile.name : '파일을 선택하세요' }}</strong>
        </label>
        <p v-if="replaceError" class="model-error" role="alert">{{ replaceError }}</p>
        <div class="dialog-actions">
          <button class="btn-cancel" :disabled="replaceSubmitting" @click="closeReplaceDialog">취소</button>
          <button class="btn-activate-version" :disabled="!replaceFile || replaceSubmitting" @click="submitReplace">
            <i v-if="replaceSubmitting" class="fa-solid fa-spinner fa-spin"></i>
            업로드 및 최신본 변경
          </button>
        </div>
      </div>
    </div>

    <!-- 2026.10.19(sooyeon.choi) 추가 - 버전 이력 대화상자 -->
    <!-- 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원(목업 v0.2): 버전 단일 선택 → 하단 [선택 버전 복원] → 확인창. 행 선택은 서버 요청 없음, 적용 이력 펼치기 -->
    <div v-if="historyTarget" class="dialog-overlay" @click.self="!restoreDialog.stage && closeVersionHistory()">
      <div
        v-focus
        class="dialog-box version-dialog version-history-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="historyDialogTitle"
        tabindex="-1"
        :inert="Boolean(restoreDialog.stage)"
        @keydown.esc="!restoreDialog.stage && closeVersionHistory()"
      >
        <div class="history-head">
          <div id="historyDialogTitle" class="dialog-title"><i class="fa-solid fa-clock-rotate-left" style="color: #2563eb"></i>버전 이력</div>
          <button class="history-close" aria-label="버전 이력 닫기" @click="closeVersionHistory">×</button>
        </div>
        <p class="version-dialog-name">
          <strong
            >{{ historyData?.product_model || historyTarget.product_model || '-' }}<span v-if="historyData?.collection_display_name" class="history-topic">
              · {{ historyData.collection_display_name }}</span
            ></strong
          >
          <span>{{ historyData?.current_original_filename || historyTarget.filename }}</span>
        </p>
        <p class="history-notice">{{ historyNotice }}</p>
        <div class="history-section-title">
          <span>{{ restoreSupported ? '버전 선택' : '버전 목록' }}</span>
          <span v-if="historyData" class="history-count">최신순 · 총 {{ historyData.total_versions ?? historyItems.length }}개 버전</span>
        </div>
        <div class="version-history-list" aria-live="polite">
          <p v-if="historyLoading" class="version-history-empty"><i class="fa-solid fa-spinner fa-spin"></i> 버전 이력을 불러오는 중입니다.</p>
          <div v-else-if="historyError" class="history-load-error" role="alert">
            <span>버전 이력을 불러오지 못했습니다. {{ historyError }}</span>
            <button class="btn-cancel" @click="reloadVersionHistory">다시 불러오기</button>
          </div>
          <p v-else-if="!historyItems.length" class="version-history-empty">버전 이력이 없습니다.</p>
          <template v-else>
            <article
              v-for="item in historyItems"
              :key="item.version_no"
              class="version-history-item"
              :class="[item.status, { selected: selectedVersionNo === item.version_no }]"
              :aria-label="`v${item.version_no} 버전`"
            >
              <button type="button" class="version-option" :disabled="!canSelectVersion(item)" :aria-pressed="selectedVersionNo === item.version_no" @click="selectVersion(item)">
                <span v-if="restoreSupported" class="version-radio" aria-hidden="true"><i v-if="item.is_active" class="fa-solid fa-check"></i></span>
                <span class="version-info">
                  <span class="version-history-head">
                    <strong>v{{ item.version_no }}</strong>
                    <span v-if="selectedVersionNo === item.version_no" class="version-status selected">복원 대상 선택됨</span>
                    <span v-else class="version-status" :class="item.status">{{ item.is_active ? '현재 적용 중' : versionStatusLabel(item.status) }}</span>
                    <span v-if="item.is_active" class="version-in-use">· 검색·답변 사용 중</span>
                  </span>
                  <span class="version-history-file" :title="item.original_filename">{{ item.original_filename || '-' }}</span>
                  <small>
                    {{ item.created_at || '-' }} 등록<template v-if="item.uploaded_by_name || item.uploaded_by"> · {{ item.uploaded_by_name || item.uploaded_by }}</template
                    ><template v-if="item.total_pages != null"> · {{ item.total_pages }}페이지</template
                    ><template v-if="item.chunk_count != null"> · {{ item.chunk_count }}청크</template
                    ><template v-if="item.file_size"> · {{ formatFileSize(item.file_size) }}</template>
                  </small>
                </span>
                <i v-if="canSelectVersion(item)" class="fa-solid fa-chevron-right version-chevron" aria-hidden="true"></i>
              </button>
              <p v-if="item.error" class="model-error version-reason">{{ item.error }}</p>
              <p v-else-if="versionBlockReason(item)" class="version-reason"><i class="fa-solid fa-circle-info"></i> {{ versionBlockReason(item) }}</p>
            </article>
          </template>
        </div>
        <p v-if="restoreSupported && historyItems.length" class="history-help"><i class="fa-solid fa-circle-info"></i> 이전 버전을 선택한 후 하단의 복원 버튼을 눌러주세요.</p>
        <details v-if="restoreSupported" class="activation-log" @toggle="onActivationsToggle">
          <summary>적용 이력 보기 <i class="fa-solid fa-chevron-down"></i></summary>
          <p v-if="activations.error" class="model-error" role="alert">{{ activations.error }}</p>
          <p v-else-if="activations.loaded && !activations.items.length" class="activation-empty">적용 이력이 없습니다.</p>
          <p v-for="a in activations.items" :key="a.activation_id">{{ activationText(a) }}</p>
          <p v-if="activations.loading" class="activation-empty"><i class="fa-solid fa-spinner fa-spin"></i> 불러오는 중...</p>
          <button v-else-if="activations.next != null" class="btn-text" @click="loadMoreActivations">더 보기</button>
        </details>
        <div class="dialog-actions history-foot">
          <div v-if="restoreSupported" class="selection-summary" aria-live="polite">
            <template v-if="selectionValid"
              ><strong>v{{ historyData.current_version_no }} → v{{ selectedVersionNo }}</strong> 복원 예정 · 확인 단계가 한 번 더 표시됩니다.</template
            >
            <template v-else>복원할 이전 버전을 선택하세요.</template>
          </div>
          <div class="footer-actions">
            <button class="btn-cancel" @click="closeVersionHistory">닫기</button>
            <button v-if="restoreSupported" class="btn-activate-version" :disabled="!selectionValid" @click="openRestoreConfirm">
              <i class="fa-solid fa-rotate-left"></i> 선택 버전 복원
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원 확인·진행·완료·실패 대화상자(목업 v0.2 #restoreOverlay) -->
    <div v-if="restoreDialog.stage" class="dialog-overlay restore-overlay" @click.self="onRestoreEscape">
      <div v-focus class="dialog-box version-dialog restore-dialog" role="dialog" aria-modal="true" aria-labelledby="restoreDialogTitle" tabindex="-1" @keydown.esc="onRestoreEscape">
        <div id="restoreDialogTitle" class="dialog-title">{{ restoreTitle }}</div>
        <p class="restore-model">{{ restoreDialog.productModel || '-' }}</p>

        <template v-if="restoreDialog.stage === 'confirm'">
          <p>선택한 버전으로 문서를 복원하시겠습니까?</p>
          <div class="restore-comparison">
            <div class="compare-box">
              <span class="compare-label">현재 적용</span>
              <strong>v{{ restoreDialog.fromVersionNo }}</strong>
              <span class="compare-file">{{ restoreDialog.fromFilename || '-' }}</span>
            </div>
            <span class="compare-arrow" aria-hidden="true">→</span>
            <div class="compare-box target">
              <span class="compare-label">복원할 버전</span>
              <strong>v{{ restoreDialog.targetVersionNo }}</strong>
              <span class="compare-file">{{ restoreDialog.targetFilename || '-' }}</span>
            </div>
          </div>
          <p class="restore-note">검색·답변과 사진·출처가 v{{ restoreDialog.targetVersionNo }} 내용으로 변경됩니다.</p>
          <p class="restore-checklist">
            ✓ 보관된 검색 데이터를 그대로 사용합니다.<br />✓ 복원 전후 버전 이력이 모두 유지됩니다.<br />✓ 완료 전에는 현재 v{{ restoreDialog.fromVersionNo }}으로 서비스합니다.
          </p>
          <p v-if="restoreDialog.nextVersionNo" class="restore-small">복원 후 새 파일을 등록하면 v{{ restoreDialog.nextVersionNo }}로 추가됩니다.</p>
          <p v-if="restoreDialog.submitError" class="model-error" role="alert">{{ restoreDialog.submitError }}</p>
          <div class="dialog-actions">
            <button class="btn-cancel" :disabled="restoreSubmitting" @click="cancelRestoreConfirm">취소</button>
            <button class="btn-activate-version" :disabled="restoreSubmitting" @click="submitRestore">
              <i v-if="restoreSubmitting" class="fa-solid fa-spinner fa-spin"></i> 이 버전으로 복원
            </button>
          </div>
        </template>

        <template v-else-if="restoreDialog.stage === 'progress'">
          <p class="restore-note">완료 전까지 현재 v{{ restoreDialog.fromVersionNo }}으로 검색·답변합니다.</p>
          <div class="restore-progress" role="status">
            <p v-for="(state, index) in restoreStepStates(restoreDialog.step)" :key="index" class="restore-step" :class="state">
              <i v-if="state === 'on'" class="fa-solid fa-spinner fa-spin"></i>
              <span v-else>{{ state === 'done' ? '✓' : '○' }}</span>
              {{ restoreStepLabel(index, state) }}
            </p>
          </div>
          <p v-if="restoreDialog.checking" class="restore-small">상태 확인 중... 연결이 회복되면 자동으로 이어서 확인합니다.</p>
          <p class="restore-small">창을 닫아도 처리는 계속됩니다. 버전 이력에서 결과를 확인할 수 있습니다.</p>
          <div class="dialog-actions">
            <button class="btn-cancel" @click="backgroundRestore">닫고 계속하기</button>
          </div>
        </template>

        <template v-else-if="restoreDialog.stage === 'success'">
          <p class="restore-note success" role="status">✓ 현재 적용 버전이 v{{ restoreDialog.result?.current_version_no ?? restoreDialog.targetVersionNo }}으로 변경되었습니다.</p>
          <div class="restore-progress">
            <strong>{{ restoreDialog.result?.original_filename || restoreDialog.targetFilename }}</strong>
            <p class="restore-small">
              <template v-if="restoreDialog.result?.total_pages != null">{{ restoreDialog.result.total_pages }}페이지 · </template
              ><template v-if="restoreDialog.result?.chunk_count != null">{{ restoreDialog.result.chunk_count }}개 청크<br /></template>
              선택한 버전의 문서·검색·사진·출처가 적용되었습니다.
            </p>
          </div>
          <p class="restore-small">실행자: {{ restoreDialog.result?.activated_by_name || restoreDialog.result?.activated_by || '-' }} · 복원 내역은 적용 이력에 기록되었습니다.</p>
          <div class="dialog-actions">
            <button class="btn-activate-version" @click="closeRestoreResult">버전 이력 확인</button>
          </div>
        </template>

        <template v-else>
          <p class="restore-note error" role="alert">{{ restoreDialog.error }}</p>
          <p class="restore-keep">
            현재 적용 버전은 <strong>v{{ restoreDialog.currentVersionNo }}</strong>으로 유지됩니다.
          </p>
          <p class="restore-small">잠시 후 다시 시도하세요. 반복되면 관리자에게 문의하세요.</p>
          <div class="dialog-actions">
            <button class="btn-cancel" @click="closeRestoreResult">버전 이력으로</button>
            <button class="btn-activate-version" @click="retryRestore">다시 시도</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script>
import { useRouter } from 'vue-router';
import AdminSidebar from '../components/AdminSidebar.vue';
import AppToast from '../components/AppToast.vue';
import { useAdminDocuments } from '../composables/useAdminDocuments';

export default {
  components: { AdminSidebar, AppToast },
  // 2026.10.19(sooyeon.choi) 추가 - 모델명 수정 입력창이 열리면 바로 입력할 수 있게 포커스
  directives: { focus: { mounted: (el) => el.focus() } },
  setup() {
    const router = useRouter();
    return useAdminDocuments({ router });
  },
};
</script>

<style scoped>
/* 2026.10.02(woojin.jung) 수정 - 업로드 진행 현황 UI 개선(요약 칩·분할 진행 막대·파일 목록·단계 인디케이터) */
.batch-selection {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 1rem;
  font-size: 0.875rem;
  color: #475569;
}
.batch-progress {
  margin-top: 1.5rem;
  padding-top: 1.25rem;
  border-top: 1px solid #e2e8f0;
  font-size: 0.875rem;
}
.batch-progress-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.batch-progress-title {
  margin: 0 0.25rem 0 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
}
.batch-progress-count {
  color: #1e293b;
}
.summary-chip {
  border-radius: 999px;
  padding: 0.15rem 0.6rem;
  font-size: 0.78rem;
  background: #f1f5f9;
  color: #475569;
}
.summary-chip.running {
  background: #dbeafe;
  color: #2563eb;
}
.summary-chip.failed,
.summary-chip.unknown {
  background: #fee2e2;
  color: #dc2626;
}
.batch-monitor {
  margin-left: auto;
}
.batch-notice {
  margin: 0.6rem 0 0;
  color: #64748b;
  font-size: 0.78rem;
  line-height: 1.5;
}
.batch-notice i {
  margin-right: 0.25rem;
}
.batch-notice.error {
  color: #dc2626;
}
.btn-text {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: none;
  background: none;
  padding: 0.3rem 0.5rem;
  border-radius: 6px;
  color: #475569;
  font-size: 0.8rem;
  cursor: pointer;
  white-space: nowrap;
}
.btn-text:hover:not(:disabled) {
  background: #f1f5f9;
  color: #1e293b;
}
.btn-text.danger {
  color: #dc2626;
}
.btn-text.danger:hover:not(:disabled) {
  background: #fef2f2;
  color: #b91c1c;
}
.btn-text:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.upload-progress-track {
  display: flex;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}
.upload-progress-track span {
  height: 100%;
  transition: width 0.4s ease;
}
.upload-progress-track span.completed {
  background-color: #22c55e;
}
.upload-progress-track span.failed {
  background-color: #ef4444;
}
.upload-progress-track span.running {
  background-color: #3b82f6;
}
.upload-file-list {
  list-style: none;
  margin: 1rem 0 0;
  padding: 0;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}
.upload-file {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e2e8f0;
}
.upload-file:last-child {
  border-bottom: none;
}
.upload-file.failed,
.upload-file.rejected,
.upload-file.submission_unknown {
  background: #fffafa;
}
/* 2026.10.19(sooyeon.choi) 수정 - 파일명 | 모델명 입력 | 상태 | 작업 */
.upload-file-main {
  display: grid;
  /* 2026.10.20(woojin.jung) 수정 - 머리글과 열을 맞추도록 작업 열 최소 폭 고정 */
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.1fr) minmax(4.5rem, auto);
  align-items: center;
  gap: 1rem;
}
/* 2026.10.20(woojin.jung) 추가 - 처리 현황 목록 머리글(파일 | 모델명 | 상태) */
.upload-file-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.1fr) minmax(4.5rem, auto);
  gap: 1rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 10px 10px 0 0;
  color: #64748b;
  font-size: 0.75rem;
  font-weight: 600;
}
/* 2026.10.21(woojin.jung) 수정 - 모델명 도움말 팝오버(흰 카드·부드러운 그림자). 아래 행 입력칸을 가리지 않도록 아이콘 위쪽에 표시 */
.upload-file-head-name {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.help-pop {
  position: relative;
  display: inline-flex;
}
.help-pop-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: #94a3b8;
  font-size: 0.8rem;
  cursor: help;
  transition: color 0.15s, background-color 0.15s;
}
.help-pop:hover .help-pop-trigger,
.help-pop-trigger:focus-visible {
  background: #eff6ff;
  color: #2563eb;
  outline: none;
}
.help-pop-card {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 50%;
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  width: 270px;
  padding: 0.85rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 12px 28px -8px rgba(15, 23, 42, 0.18), 0 2px 6px rgba(15, 23, 42, 0.06);
  color: #475569;
  font-size: 0.78rem;
  font-weight: 400;
  line-height: 1.5;
  text-align: left;
  white-space: normal;
  opacity: 0;
  visibility: hidden;
  transform: translate(-50%, -4px);
  transition: opacity 0.15s ease, transform 0.15s ease, visibility 0.15s;
  pointer-events: none;
}
/* 카드 아래쪽 꼬리(아이콘을 가리킴) */
.help-pop-card::before {
  content: '';
  position: absolute;
  bottom: -6px;
  left: 50%;
  width: 10px;
  height: 10px;
  border-right: 1px solid #e2e8f0;
  border-bottom: 1px solid #e2e8f0;
  background: #fff;
  transform: translateX(-50%) rotate(45deg);
}
.help-pop:hover .help-pop-card,
.help-pop:focus-within .help-pop-card {
  opacity: 1;
  visibility: visible;
  transform: translate(-50%, 0);
}
.help-pop-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: #1e293b;
  font-size: 0.82rem;
  font-weight: 600;
}
.help-pop-title i {
  color: #2563eb;
  font-size: 0.75rem;
}
.help-pop-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding-top: 0.55rem;
  border-top: 1px solid #f1f5f9;
}
.help-pop-list span {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #334155;
}
.help-pop-list i {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 0.65rem;
}
@media (prefers-reduced-motion: reduce) {
  .help-pop-card {
    transition: none;
  }
}
.upload-file-name {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  color: #1e293b;
}
.upload-file-name i {
  color: #94a3b8;
}
.upload-file-name strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.upload-file-size {
  flex-shrink: 0;
  color: #94a3b8;
  font-size: 0.78rem;
}
.upload-file-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.6rem;
  min-width: 0;
}
.upload-file-actions {
  display: flex;
  justify-content: flex-end;
}
.upload-state {
  display: inline-flex;
  align-items: center;
  border-radius: 20px;
  padding: 0.2rem 0.6rem;
  font-size: 0.78rem;
  font-weight: 600;
  background: #f1f5f9;
  color: #475569;
  white-space: nowrap;
}
.upload-state-spinner {
  margin-right: 0.35rem;
}
.upload-state.running,
.upload-state.uploading {
  background: #dbeafe;
  color: #2563eb;
}
.upload-state.completed {
  background: #dcfce7;
  color: #15803d;
}
.upload-state.failed,
.upload-state.rejected,
.upload-state.submission_unknown {
  background: #fee2e2;
  color: #dc2626;
}
.upload-steps {
  display: flex;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.upload-steps li {
  width: 18px;
  height: 6px;
  border-radius: 999px;
  background: #e2e8f0;
}
.upload-steps li.done {
  background: #22c55e;
}
.upload-steps li.active {
  background: #3b82f6;
}
.upload-steps li.error {
  background: #ef4444;
}
.upload-step-label {
  color: #64748b;
  font-size: 0.78rem;
}
.upload-file-message {
  margin: 0.4rem 0 0 1.5rem;
  color: #64748b;
  font-size: 0.78rem;
  line-height: 1.5;
}
.upload-file-message.error {
  color: #dc2626;
}
.batch-result {
  margin-left: 1.5rem;
  font-size: 0.8125rem;
  color: #475569;
}
.batch-result summary {
  cursor: pointer;
  margin-top: 0.5rem;
}
.batch-result dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
}
.batch-result dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}
/* 2026.10.19(sooyeon.choi) 추가 - 파일별 모델명 입력·목록 모델명 셀(기존 입력·버튼 스타일 기준) */
.upload-file-model {
  min-width: 0;
}
.model-input {
  width: 100%;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.4rem 0.6rem;
  font: inherit;
  font-size: 0.82rem;
  color: #374151;
  outline: none;
  transition: border-color 0.15s;
}
.model-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}
.model-input:disabled {
  background: #f3f4f6;
  color: #475569;
  cursor: not-allowed;
}
.model-input.invalid {
  border-color: #ef4444;
}
/* 2026.10.20(woojin.jung) 추가 - 파일명으로 되돌리기 버튼·전송 후 확정 이름 표시 */
.model-input-wrap {
  position: relative;
}
.model-input.resettable {
  padding-right: 2rem;
}
.btn-model-reset {
  position: absolute;
  top: 50%;
  right: 4px;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #64748b;
  font-size: 0.75rem;
  cursor: pointer;
}
.btn-model-reset:hover {
  background: #eff6ff;
  color: #2563eb;
}
.model-locked {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.82rem;
  color: #334155;
}
.model-locked-label {
  display: none;
  margin-right: 0.4rem;
  color: #94a3b8;
  font-size: 0.75rem;
}
.model-error {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  line-height: 1.4;
  white-space: normal;
}
.model-error {
  color: #dc2626;
}
.model-submit-error {
  min-height: 0;
  margin: -0.5rem 0 0;
}
@media (prefers-reduced-motion: reduce) {
  .upload-state-spinner {
    animation: none !important;
  }
  .upload-progress-track span {
    transition: none;
  }
}
@media (max-width: 768px) {
  .upload-file-main {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  /* 2026.10.19(sooyeon.choi) 수정 - 좁은 화면: 모델명 입력 2행, 상태 3행 */
  .upload-file-model {
    grid-column: 1 / -1;
    grid-row: 2;
  }
  .upload-file-status {
    grid-column: 1 / -1;
    grid-row: 3;
  }
  /* 2026.10.20(woojin.jung) 추가 - 좁은 화면은 머리글 대신 확정 이름 앞에 라벨 표시 */
  .upload-file-head {
    display: none;
  }
  .model-locked-label {
    display: inline;
  }
  .batch-monitor {
    margin-left: 0;
  }
}

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
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* ── Cards ── */
.card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 1.5rem;
}
.card-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 1.25rem;
}

/* ── Drop Zone ── */
.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  padding: 2rem;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #f8fafc;
  margin-bottom: 1.25rem;
  min-height: 120px;
}
.drop-zone:hover,
.drop-zone.dragging {
  border-color: #3b82f6;
  background: #eff6ff;
}
.drop-zone.has-file {
  border-color: #22c55e;
  background: #f0fdf4;
  border-style: solid;
}
.drop-zone.disabled {
  cursor: not-allowed;
  opacity: 0.7;
  pointer-events: none;
}
.drop-placeholder {
  text-align: center;
  color: #94a3b8;
}
.drop-icon {
  font-size: 2rem;
  margin-bottom: 0.5rem;
  color: #cbd5e1;
}
.drop-placeholder p {
  font-size: 0.9rem;
  margin-bottom: 0.25rem;
  color: #64748b;
}
.drop-placeholder span {
  font-size: 0.78rem;
  color: #94a3b8;
}
/* ── Form ── */
.upload-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.form-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.form-group label {
  font-size: 0.82rem;
  font-weight: 500;
  color: #374151;
}
.required {
  color: #ef4444;
}
.label-hint {
  font-weight: 400;
  color: #9ca3af;
}
.form-group input,
.form-group select {
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 0.6rem 0.75rem;
  font-size: 0.88rem;
  color: #374151;
  outline: none;
  transition: border-color 0.15s;
}
.form-group input:focus,
.form-group select:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}
.form-group input:disabled,
.form-group select:disabled {
  background: #f3f4f6;
  cursor: not-allowed;
}
.form-hint {
  min-height: 2.4em;
  color: #64748b;
  font-size: 0.78rem;
  line-height: 1.4;
}
.form-error {
  min-height: 2.4em;
  color: #dc2626;
  font-size: 0.78rem;
  line-height: 1.4;
}

/* 2026.04.01(sooyeon.choi) 수정 - 멀티대화 주제 관리 기능 추가 */
.no-collection-hint {
  font-size: 0.78rem;
  color: #f59e0b;
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 2px;
}

.btn-upload {
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.8rem 1.5rem;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: background 0.15s;
  align-self: flex-start;
}
.btn-upload:hover:not(:disabled) {
  background: #1d4ed8;
}
.btn-upload:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
.uploading-text {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* ── Spinner ── */
.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ── Error Card ── */
.error-card {
  border-color: #fecaca;
  background: #fef2f2;
}
.error-msg {
  font-size: 0.88rem;
  color: #dc2626;
  margin: 0.5rem 0 1rem;
}
.btn-retry {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
  padding: 0.4rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.82rem;
}
.btn-retry:hover {
  background: #fee2e2;
}

/* ── Table Card ── */
.card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.table-filters {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.table-filters select {
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0.35rem 0.6rem;
  font-size: 0.82rem;
  color: #374151;
  outline: none;
}
.btn-refresh {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #64748b;
  width: 30px;
  height: 30px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
}
.btn-refresh:hover {
  background: #eff6ff;
  color: #2563eb;
}

.empty-table {
  text-align: center;
  padding: 2.5rem;
  color: #94a3b8;
}
.empty-table i {
  font-size: 2rem;
  margin-bottom: 0.5rem;
  display: block;
}
.empty-table p {
  font-size: 0.88rem;
}

.table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.doc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
  /* 2026.10.19(sooyeon.choi) 수정 - 모델명(220)·현재 버전(110)·작업(280) 컬럼 추가분 반영 */
  /* 2026.10.20(woojin.jung) 수정 - 모델명 컬럼을 파일명 컬럼에 합쳐 220px 제외 */
  min-width: calc(var(--filename-column-width, 340px) + 1080px);
  table-layout: fixed;
}
.col-version {
  width: 110px;
}
.col-filename {
  width: var(--filename-column-width, 340px);
}
.col-doc-type {
  width: 110px;
}
.col-pages {
  width: 86px;
}
.col-topic {
  width: 170px;
}
.col-user {
  width: 110px;
}
.col-parser {
  width: 100px;
}
.col-upload-time {
  width: 170px;
}
/* 2026.10.19(sooyeon.choi) 수정 - [최신본 변경]·[버전 이력]·삭제 3개 버튼 */
.col-actions {
  width: 280px;
}
.doc-table th {
  background: #f8fafc;
  padding: 0.6rem 0.75rem;
  text-align: left;
  font-weight: 600;
  color: #374151;
  border-bottom: 1px solid #e5e7eb;
  white-space: nowrap;
}
/* 2026.10.19(sooyeon.choi) 수정 - 리사이즈 손잡이를 첫 컬럼이 아닌 파일명 헤더(th-filename)에 둔다 */
.doc-table th.th-filename {
  position: relative;
  cursor: col-resize;
  user-select: none;
  padding-right: 1.6rem;
}
.doc-table th.th-filename::after {
  content: '\2194';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 18px;
  border-right: 2px solid #cbd5e1;
  color: #94a3b8;
  font-size: 0.75rem;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.9;
}
.doc-table th.th-filename:hover::after {
  border-right-color: #2563eb;
  color: #2563eb;
  opacity: 1;
}
.doc-table td {
  padding: 0.7rem 0.75rem;
  border-bottom: 1px solid #f1f5f9;
  color: #374151;
  vertical-align: middle;
}
.doc-table tr:last-child td {
  border-bottom: none;
}
.doc-table tr:hover td {
  background: #f8fafc;
}
/* 2026.10.19(sooyeon.choi) 추가 - 목록 모델명 셀·연필 버튼·버전 배지 */
.model-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
/* 2026.10.20(woojin.jung) 수정 - 모델명(1행)·파일명 링크(2행) 한 셀 구성, 이름 클릭으로 수정 */
.td-filename .filename-cell-content {
  margin-top: 2px;
  font-size: 0.78rem;
  color: #94a3b8;
}
.model-cell.editing {
  flex-wrap: wrap;
}
.model-cell.editing .model-input {
  flex: 1;
  min-width: 0;
  width: auto;
}
.model-cell .model-error {
  flex-basis: 100%;
}
.model-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: #1e293b;
}
.model-name.editable {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  margin: -2px -6px;
  padding: 2px 6px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  font: inherit;
  font-weight: 600;
  text-align: left;
  cursor: text;
}
.model-name-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-name.editable i {
  flex-shrink: 0;
  color: #94a3b8;
  font-size: 0.7rem;
}
.model-name.editable:hover:not(:disabled),
.model-name.editable:focus-visible {
  border-color: #cbd5e1;
  background: #fff;
}
.model-name.editable:hover:not(:disabled) i {
  color: #2563eb;
}
.model-name.editable:disabled {
  cursor: default;
}
.btn-model-icon {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.78rem;
  cursor: pointer;
}
.btn-model-icon:hover:not(:disabled) {
  background: #e2e8f0;
}
.btn-model-icon.save {
  border-color: #2563eb;
  background: #2563eb;
  color: #fff;
}
.btn-model-icon.save:hover:not(:disabled) {
  background: #1d4ed8;
}
.btn-model-icon:disabled {
  opacity: 0.6;
  cursor: wait;
}
.version-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.75rem;
  font-weight: 600;
}
/* 2026.10.19(sooyeon.choi) 추가 - 작업 버튼·처리 중 표시·최신본 변경/버전 이력 대화상자(기존 버튼·대화상자 스타일 기준) */
.version-pending {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 4px;
  padding: 2px 6px;
  border-radius: 10px;
  background: #dbeafe;
  color: #2563eb;
  font-size: 0.72rem;
  font-weight: 600;
}
.document-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.btn-doc-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 34px;
  padding: 0 0.65rem;
  border: 1px solid transparent;
  border-radius: 6px;
  background: #fff;
  font-size: 0.78rem;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}
/* 2026.10.19(sooyeon.choi) 수정 - 최신본 변경은 연한 파란 배경으로 주요 작업 구분(버전 이력=흰 배경 회색) */
.btn-latest-version {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #2563eb;
}
.btn-latest-version:hover:not(:disabled) {
  background: #dbeafe;
  border-color: #93c5fd;
}
.btn-version-history {
  border-color: #e2e8f0;
  color: #475569;
}
.btn-version-history:hover:not(:disabled) {
  background: #f1f5f9;
  border-color: #cbd5e1;
  color: #1e293b;
}
.btn-doc-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.dialog-box.version-dialog {
  width: 520px;
}
.version-dialog-name {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 0.5rem;
  font-size: 0.88rem;
  color: #1e293b;
  overflow-wrap: anywhere;
}
.version-dialog-name span {
  font-size: 0.8rem;
  color: #64748b;
}
.version-dialog .dialog-hint {
  display: block;
  margin-bottom: 1rem;
  line-height: 1.5;
}
.replacement-file {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  padding: 0.75rem;
  margin-bottom: 0.75rem;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  cursor: pointer;
}
.replacement-file.disabled {
  cursor: not-allowed;
  opacity: 0.7;
}
.replacement-file input {
  display: none;
}
.replacement-file-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0.35rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  color: #374151;
  font-size: 0.82rem;
}
.replacement-file-name {
  min-width: 0;
  font-size: 0.82rem;
  font-weight: 500;
  color: #475569;
  overflow-wrap: anywhere;
}
.btn-activate-version {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
}
.btn-activate-version:hover:not(:disabled) {
  background: #1d4ed8;
}
.btn-activate-version:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
.version-history-list {
  max-height: 50vh;
  overflow-y: auto;
  margin-bottom: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.version-history-empty {
  padding: 1rem;
  font-size: 0.85rem;
  color: #64748b;
  text-align: center;
}
.version-history-item {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.8rem;
  color: #475569;
}
.version-history-item:last-child {
  border-bottom: none;
}
.version-history-item.active {
  background: #f0f9ff;
}
.version-history-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin-bottom: 4px;
  color: #1e293b;
}
.version-history-file {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.version-history-item p {
  margin: 0 0 2px;
}
.version-history-item small {
  color: #94a3b8;
}
.version-status {
  flex-shrink: 0;
  padding: 1px 8px;
  border-radius: 10px;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.72rem;
  font-weight: 600;
}
.version-status.active {
  background: #dcfce7;
  color: #15803d;
}
.version-status.building,
.version-status.ready {
  background: #dbeafe;
  color: #2563eb;
}
.version-status.failed {
  background: #fee2e2;
  color: #dc2626;
}
/* 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원(목업 v0.2): 버전 선택 행·하단 선택 요약·적용 이력·복원 확인/진행/결과 대화상자 */
.page-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 0.82rem;
}
.page-status.success {
  background: #ecfdf5;
  color: #047857;
}
.page-status.error {
  background: #fef2f2;
  color: #b91c1c;
}
.page-status span {
  flex: 1;
  min-width: 0;
}
.page-status-close {
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  opacity: 0.7;
}
.dialog-box.version-history-dialog {
  width: 760px;
  max-width: calc(100vw - 2rem);
  max-height: calc(100dvh - 2rem);
  overflow-y: auto;
}
.dialog-box.restore-dialog {
  width: 530px;
  max-width: calc(100vw - 2rem);
  max-height: calc(100dvh - 2rem);
  overflow-y: auto;
}
.dialog-box:focus {
  outline: none;
}
.history-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}
.history-close {
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 1.4rem;
  line-height: 1;
  cursor: pointer;
}
.history-topic {
  font-weight: 400;
  color: #64748b;
}
.history-notice {
  margin: 0.25rem 0 1rem;
  padding: 0.75rem 0.95rem;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 0.82rem;
  line-height: 1.5;
}
.history-section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: #334155;
}
.history-count {
  font-weight: 400;
  color: #64748b;
  font-size: 0.78rem;
}
.history-load-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 0.82rem;
}
.version-history-item.selected {
  background: #eff6ff;
}
.version-option {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.version-option:disabled {
  cursor: default;
}
.version-option:focus-visible {
  outline: 3px solid #93c5fd;
  outline-offset: 3px;
  border-radius: 6px;
}
.version-radio {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border: 2px solid #cbd5e1;
  border-radius: 50%;
  color: #64748b;
  font-size: 0.6rem;
}
.version-history-item.selected .version-radio {
  border: 5px solid #2563eb;
}
.version-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.version-in-use {
  color: #64748b;
  font-size: 0.75rem;
}
.version-chevron {
  color: #94a3b8;
  font-size: 0.75rem;
}
.version-status.selected {
  background: #dbeafe;
  color: #2563eb;
}
.version-reason {
  margin: 0.4rem 0 0 calc(18px + 0.75rem) !important;
  color: #b45309;
  font-size: 0.78rem;
}
.history-help {
  margin: -0.5rem 0 0.75rem;
  color: #64748b;
  font-size: 0.78rem;
}
.activation-log {
  margin-bottom: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid #e2e8f0;
  font-size: 0.78rem;
  color: #64748b;
}
.activation-log summary {
  cursor: pointer;
  font-weight: 600;
  color: #334155;
}
.activation-log summary i {
  font-size: 0.6rem;
}
.activation-log p {
  margin: 0.35rem 0 0;
}
.activation-empty {
  color: #94a3b8;
}
.history-foot {
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}
.selection-summary {
  flex: 1;
  min-width: 0;
  color: #475569;
  font-size: 0.82rem;
}
.footer-actions {
  display: flex;
  gap: 0.5rem;
  margin-left: auto;
}
.restore-model {
  margin: 0.15rem 0 1rem;
  color: #64748b;
  font-size: 0.8rem;
}
.restore-comparison {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 1rem;
  margin: 1.1rem 0;
}
.compare-box {
  display: flex;
  flex-direction: column;
  padding: 0.9rem;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  min-width: 0;
}
.compare-box.target {
  border-color: #93c5fd;
  background: #eff6ff;
}
.compare-box strong {
  font-size: 1.5rem;
  margin: 2px 0;
}
.compare-label {
  font-size: 0.75rem;
  color: #64748b;
}
.compare-box.target .compare-label {
  color: #2563eb;
}
.compare-file {
  font-size: 0.75rem;
  color: #64748b;
  overflow-wrap: anywhere;
}
.compare-arrow {
  color: #64748b;
}
.restore-note {
  padding: 0.75rem 0.95rem;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 0.82rem;
}
.restore-note.success {
  background: #ecfdf5;
  color: #047857;
}
.restore-note.error {
  background: #fef2f2;
  color: #b91c1c;
}
.restore-checklist {
  margin: 0.9rem 0;
  color: #475569;
  font-size: 0.8rem;
  line-height: 2;
}
.restore-small {
  margin: 0.5rem 0;
  color: #64748b;
  font-size: 0.78rem;
}
.restore-keep {
  margin: 1rem 0;
  font-size: 0.88rem;
}
.restore-progress {
  margin: 1rem 0;
  padding: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
}
.restore-step {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0;
  color: #64748b;
  font-size: 0.85rem;
}
.restore-step.on {
  color: #2563eb;
  font-weight: 600;
}
.restore-step.done {
  color: #047857;
}
@media (max-width: 600px) {
  .restore-comparison {
    gap: 0.5rem;
  }
  .history-foot .footer-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
@media (prefers-reduced-motion: reduce) {
  .restore-step .fa-spin,
  .page-status .fa-spin {
    animation: none;
  }
}
.td-filename {
  width: var(--filename-column-width, 340px);
  max-width: var(--filename-column-width, 340px);
}
.filename-cell-content {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.filename-cell-content > i {
  flex-shrink: 0;
}
.filename-link {
  min-width: 0;
  border: none;
  background: transparent;
  color: #2563eb;
  padding: 0;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  text-align: left;
  font: inherit;
}
.filename-link:hover .filename-text {
  text-decoration: underline;
}
.filename-link:disabled {
  color: #94a3b8;
  cursor: wait;
}
.td-filename .filename-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  /* 핵심 속성: flex 안에서 자식이 가질 수 있는 최소 너비를 해제하여 */
  /* 부모인 max-width: 220px 안에서만 늘어나고 줄어들게 만듭니다. */
  min-width: 0;
}
.td-chunks {
  font-weight: 600;
  color: #2563eb;
}
.td-time {
  font-size: 0.78rem;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.doc-table th:last-child,
.doc-table td:last-child {
  text-align: center;
  white-space: nowrap;
}
.doc-table th:last-child {
  padding-left: 0.5rem;
  padding-right: 0.5rem;
}
.doc-table td:last-child {
  padding-left: 0.5rem;
  padding-right: 0.5rem;
}
.doc-table td:last-child .btn-delete-doc {
  margin: 0 auto;
}
code {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.8rem;
  color: #475569;
}

/* ── Badges ── */
.badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 500;
}
.badge.law {
  background: #fef3c7;
  color: #92400e;
}
.badge.manual {
  background: #ede9fe;
  color: #5b21b6;
}
.badge.general {
  background: #f0f9ff;
  color: #075985;
}
.badge.spreadsheet {
  background: #dcfce7;
  color: #166534;
}

/* ── Responsive ── */
@media (max-width: 1024px) {
  .form-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .admin-content {
    padding: 1.25rem;
  }
}

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
}

@media (max-width: 480px) {
  .form-row {
    grid-template-columns: 1fr;
  }
  .btn-upload {
    width: 100%;
  }
  .collections-badge {
    display: none;
  }
}

/* 2026.04.02(sooyeon.choi) - 문서 삭제 기능 추가 */
.btn-delete-doc {
  background: none;
  border: 1px solid #fecaca;
  color: #dc2626;

  width: 34px;
  height: 34px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  transition: all 0.15s;
}
.btn-delete-doc:hover:not(:disabled) {
  background: #fef2f2;
  border-color: #fca5a5;
}
.btn-delete-doc:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

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
.btn-confirm-delete:hover {
  background: #dc2626;
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
  .btn-refresh {
    width: 40px;
    height: 40px;
  }
  .dialog-box {
    padding: 1.25rem;
  }
  .version-history-list {
    max-height: 40dvh;
  }
}
</style>
