<!-- 2026.07.22(sychoi) 추가 - RAG 평가 테스트셋 생성/검수 화면 (P4) -->
<template>
  <div class="admin-layout">
    <AdminSidebar :isOpen="sidebarOpen" activePage="eval-datasets" :isAdmin="isAdmin"
      :displayName="displayName" @close="sidebarOpen = false" @logout="logout" />

    <div class="admin-main">
      <header class="admin-header">
        <div class="header-left">
          <button class="btn-hamburger" @click="sidebarOpen = true"><i class="fa-solid fa-bars"></i></button>
          <div class="header-text">
            <h1>평가 데이터셋 <span class="admin-badge">관리자</span></h1>
            <p>지식베이스 기반 테스트 QA를 자동 생성하고, 검토·승인하여 골드데이터셋을 확정합니다.</p>
          </div>
        </div>
        <div class="header-actions">
          <button class="btn-primary" @click="openCreate"><i class="fa-solid fa-plus"></i> 테스트셋 생성</button>
        </div>
      </header>

      <main class="admin-content">
        <div v-if="loadError" class="alert error"><i class="fa-solid fa-circle-exclamation"></i> {{ loadError }}</div>

        <!-- 1. 데이터셋 목록 -->
        <section class="card dataset-list-card">
          <div class="card-title"><i class="fa-solid fa-database"></i> 데이터셋 목록
            <span v-if="datasets.length" class="count-hint">총 {{ datasets.length }}건</span>
            <button class="refresh-btn" :disabled="isLoading" title="새로고침" @click="loadDatasets">
              <i class="fa-solid fa-rotate-right" :class="{ 'fa-spin': isLoading }"></i>
            </button>
          </div>
          <p v-if="datasets.length && !selectedDataset" class="list-guide">
            <i class="fa-solid fa-circle-info"></i>
            위 목록에서 데이터셋 행을 클릭하면 QA 검토(승인·수정·반려)와 골드셋 버전 확정을 진행할 수 있습니다.
          </p>
          <!-- 2026.11.20(sooyeon.choi) 수정 - 합본 데이터셋: 확정 데이터셋 2개 이상 체크 → [합본 데이터셋 만들기] -->
          <div v-if="datasets.length && mergeEnabled && mergeSelection.length" class="merge-bar" aria-live="polite">
            <b>{{ mergeSelection.length }}개 선택</b>
            <span class="merge-sum">
              {{ mergeSelection.length >= 2
                ? mergeSelectedDatasets.map((d) => `${d.name} ${d.approved_count ?? 0}`).join(' + ') + ` = ${mergeItemTotal}문항`
                : '2개 이상 골라야 합칠 수 있습니다' }}
            </span>
            <span class="merge-spacer"></span>
            <button class="btn-secondary" @click="clearMergeSelection">선택 해제</button>
            <button class="btn-merge" :disabled="mergeSelection.length < 2" @click="openMergeModal">
              <i class="fa-solid fa-layer-group"></i> 합본 데이터셋 만들기
            </button>
          </div>
          <p v-else-if="datasets.length && mergeEnabled" class="merge-hint">
            <i class="fa-solid fa-layer-group"></i> 확정된 데이터셋 2개 이상을 체크하면 한 데이터셋(합본)으로 합쳐 한 번에 평가할 수 있습니다.
          </p>
          <div v-if="!datasets.length" class="empty-state">
            <i class="fa-regular fa-folder-open"></i>
            <p>생성된 데이터셋이 없습니다. "테스트셋 생성"으로 시작하세요.</p>
          </div>
          <div v-else class="dataset-table-scroll" role="region" aria-label="평가 데이터셋 목록" tabindex="0">
            <table class="data-table">
              <thead>
                <tr><th v-if="mergeEnabled" class="center" title="합본에 넣을 확정 데이터셋 선택">선택</th><th class="center">순번</th><th>이름</th><th>컬렉션</th><th class="center">상태</th><th class="center">QA (승인/전체)</th><th class="center">생성일</th><th class="center">최종 수정일</th><th class="center">다운로드</th><th class="center">삭제</th></tr>
              </thead>
              <tbody>
                <tr v-for="(d, index) in datasets" :key="d.dataset_id"
                    :class="{ selected: selectedDataset && selectedDataset.dataset_id === d.dataset_id }"
                    @click="selectDataset(d)">
                  <td v-if="mergeEnabled" class="center" @click.stop>
                    <input type="checkbox" :checked="isMergeSelected(d)" :disabled="!canMergeSelect(d)"
                           :title="isMerged(d) ? '합본은 다시 합칠 수 없습니다' : (canMergeSelect(d) ? '합본에 넣기' : '확정(골드셋)된 데이터셋만 합칠 수 있습니다')"
                           :aria-label="`${d.name} 합본 선택`" @change="toggleMergeSelect(d)" />
                  </td>
                  <td class="center">{{ datasets.length - index }}</td>
                  <td class="strong">{{ d.name }} <span v-if="isMerged(d)" class="merged-badge">합본</span></td>
                  <td>{{ collectionLabel(d) }}</td>
                  <td class="center"><span class="status-badge" :class="d.status">{{ statusLabel(d.status) }}</span></td>
                  <td class="center">{{ d.approved_count ?? 0 }} / {{ d.item_count ?? 0 }}</td>
                  <td class="center">{{ formatDate(d.created_at) }}</td>
                  <!-- 최종 수정일 (생성 진행/상태 변경 + QA 검수 시 갱신) -->
                  <td class="center">{{ formatDate(d.updated_at) }}</td>
                  <td class="center">
                    <!-- 2026.11.19(sooyeon.choi) 수정 - 다운로드를 하나로 통합(질의·정답 근거·검수 정보·요약).
                         승인 QA Excel 버튼은 내용이 겹쳐 숨김(API approved-items.xlsx는 유지) -->
                    <button class="btn-download-excel"
                            :disabled="(d.approved_count ?? 0) < 1 || downloadingDatasetId !== null"
                            :title="(d.approved_count ?? 0) < 1 ? '승인된 QA가 없습니다' : '데이터셋 다운로드(질의·정답 근거·검수 정보)'"
                            @click.stop="downloadTestsetExcel(d)">
                      <i class="fa-solid"
                         :class="downloadingDatasetId === d.dataset_id ? 'fa-spinner fa-spin' : 'fa-file-excel'"></i>
                    </button>
                  </td>
                  <td class="center">
                    <button class="btn-delete-doc" :disabled="d.status === 'generating'"
                            :title="d.status === 'generating' ? '생성 중에는 삭제할 수 없습니다' : '데이터셋 삭제'"
                            @click.stop="deleteDataset(d)">
                      <i class="fa-solid fa-trash"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <template v-if="selectedDataset">
          <!-- 생성 진행률 -->
          <section class="card" v-if="isGenerating">
            <div class="progress-head">
              <span>생성 중… {{ selectedDataset.progress_done }}/{{ selectedDataset.progress_total }} ({{ generateProgress }}%)</span>
            </div>
            <div class="progress-bar"><div class="progress-fill" :style="{ width: generateProgress + '%' }"></div></div>
          </section>

          <!-- 2. QA 검토 -->
          <section class="card" v-else>
            <div class="card-header">
              <div class="card-title"><i class="fa-solid fa-list-check"></i> QA 검토 — {{ selectedDataset.name }}</div>
              <div class="counts">
                승인 <b>{{ approvedCount }}</b> / {{ datasetItemCount }}
                <!-- 2026.11.19(sooyeon.choi) 수정 - '미검출' → '검색 확인 필요' -->
                <span v-if="undetectedCount" class="warn-inline">
                  · 검색 확인 필요 <b>{{ undetectedCount }}</b>
                </span>
              </div>
            </div>

            <div class="filter-row">
              <select v-model="statusFilter" @change="applyFilters">
                <option value="">전체 상태</option>
                <option value="pending">검토 대기</option>
                <option value="approved">승인</option>
                <option value="edited">수정됨</option>
                <option value="rejected">반려</option>
              </select>
              <select v-model="typeFilter" @change="applyFilters">
                <option value="">전체 유형</option>
                <option value="factual">사실형</option>
                <option value="procedural">절차형</option>
                <option value="comparative">비교형</option>
                <option value="multihop">멀티홉</option>
                <!-- 2026.11.19(sooyeon.choi) 추가 - 단일 출처 생성 문항 -->
                <option value="law">법령</option>
                <option value="general">일반</option>
              </select>
              <label class="chk" title="생성 직후 사전 검색에서 원본 근거가 상위 10위 밖이었던 문항(검수 참고용)">
                <input type="checkbox" v-model="undetectedOnly" @change="applyFilters" /> 검색 확인 필요만
              </label>
              <span class="spacer"></span>
              <button
                v-if="!selectedIsMerged"
                class="btn-secondary"
                :disabled="!displayQaItems.length || isSelectingAll"
                @click="toggleSelectAll"
              >
                <i class="fa-solid" :class="isSelectingAll ? 'fa-spinner fa-spin' : (isAllSelected ? 'fa-square-minus' : 'fa-square-check')"></i>
                {{ isSelectingAll ? '선택 중…' : (isAllSelected ? '전체 해제' : '전체 선택') }}
              </button>
              <template v-if="!selectedIsMerged">
                <button class="btn-secondary" :disabled="!selectedQaIds.length" @click="bulkApprove">
                  <i class="fa-solid fa-check-double"></i> 일괄 승인 ({{ selectedQaIds.length }})
                </button>
                <button class="btn-secondary danger" :disabled="!selectedQaIds.length" @click="bulkReject">일괄 반려</button>
              </template>
            </div>
            <!-- 2026.11.20(sooyeon.choi) 수정 - 합본은 읽기 전용(수정은 원본에서 → 확정 → 합본 다시 만들기) -->
            <div v-if="selectedIsMerged" class="merged-note">
              <i class="fa-solid fa-layer-group"></i>
              구성:
              <template v-for="(source, i) in mergedSources(selectedDataset)" :key="source.dataset_id">
                <b>{{ source.dataset_name }}</b> 확정 v{{ source.goldset_version }} ({{ source.item_count }}문항)<template v-if="i < mergedSources(selectedDataset).length - 1"> + </template>
              </template>
              <br />문항은 읽기 전용입니다. 고칠 문항이 있으면 원본에서 수정·확정한 뒤 합본을 다시 만들어 주세요.
            </div>

            <div v-if="!displayQaItems.length" class="empty-state">
              <p>{{ undetectedOnly ? '검색 확인이 필요한 항목이 없습니다.' : 'QA 항목이 없습니다.' }}</p>
            </div>
            <div v-else class="qa-list">
              <article v-for="item in displayQaItems" :key="item.qa_id" class="qa-item" :class="item.review_status">
                <div class="qa-row">
                  <input v-if="!selectedIsMerged" type="checkbox" :value="item.qa_id" v-model="selectedQaIds" />
                  <div class="qa-body" @click="toggleExpand(item)">
                    <div class="qa-meta">
                      <!-- 2026.11.20(sooyeon.choi) 수정 - 합본 문항의 질의ID·법령 -->
                      <span v-if="item.source_meta?.query_id" class="type-badge">{{ item.source_meta.query_id }}</span>
                      <span v-if="item.source_meta?.law_label" class="merged-badge">{{ item.source_meta.law_label }}</span>
                      <span class="type-badge">{{ typeLabel(item.question_type) }}</span>
                      <span class="status-badge" :class="item.review_status">{{ reviewLabel(item.review_status) }}</span>
                      <span v-if="item.self_valid_rank == null" class="warn-badge"
                            title="생성 직후 사전 검색에서 원본 근거가 상위 10위 밖이었던 문항(검수 참고용)">
                        <i class="fa-solid fa-triangle-exclamation"></i> 검색 확인 필요
                      </span>
                      <span v-else class="rank-badge">검색 순위 {{ item.self_valid_rank }}위</span>
                      <span v-if="item.expected_behavior && item.expected_behavior !== 'answer'" class="behavior-badge">
                        {{ behaviorLabel(item.expected_behavior) }}
                      </span>
                      <span v-for="t in item.tags_parsed" :key="t" class="tag">{{ tagLabel(t) }}</span>
                    </div>
                    <div class="qa-question">Q. {{ item.question }}</div>
                    <div class="qa-answer">A. {{ item.gold_answer }}</div>
                  </div>
                  <div class="qa-actions">
                    <template v-if="!selectedIsMerged">
                      <button class="icon-btn approve" title="승인" @click.stop="approveItem(item)"><i class="fa-solid fa-check"></i></button>
                      <button class="icon-btn edit" title="수정" @click.stop="startEdit(item)"><i class="fa-solid fa-pen"></i></button>
                      <button class="icon-btn reject" title="반려" @click.stop="rejectItem(item)"><i class="fa-solid fa-xmark"></i></button>
                    </template>
                    <!-- 2026.11.19(sooyeon.choi) 추가 - '검색 확인 필요' 문항만 같은 조항(섹션)으로 다시 생성 -->
                    <button v-if="canRegenerate(item)" class="icon-btn edit" :title="regenerateLabel(item)"
                            :disabled="regeneratingQaId !== null" @click.stop="regenerateItem(item)">
                      <i class="fa-solid" :class="regeneratingQaId === item.qa_id ? 'fa-spinner fa-spin' : 'fa-rotate'"></i>
                    </button>
                  </div>
                </div>
                <!-- 근거 원문 펼침 -->
                <div v-if="item.expanded" class="qa-source">
                  <div class="source-meta">
                    <i class="fa-solid fa-file-lines"></i>
                    {{ item.source_meta.original_filename || '문서 정보 없음' }}
                    <template v-if="item.source_meta.section_title"> · {{ item.source_meta.section_title }}</template>
                    <template v-if="item.source_meta.page_number"> · p.{{ item.source_meta.page_number }}</template>
                  </div>
                  <pre v-for="(text, i) in item.gold_chunk_texts_parsed" :key="i" class="chunk-text">{{ text }}</pre>
                  <p v-if="!item.gold_chunk_texts_parsed.length" class="muted">근거 청크 원문이 없습니다.</p>
                </div>
              </article>
            </div>

            <div class="pagination" v-if="qaTotalPages > 1">
              <button :disabled="qaPage <= 1" @click="goToPage(qaPage - 1)">이전</button>
              <span>{{ qaPage }} / {{ qaTotalPages }}</span>
              <button :disabled="qaPage >= qaTotalPages" @click="goToPage(qaPage + 1)">다음</button>
            </div>
          </section>

          <!-- 3. 골드셋 버전 -->
          <section class="card" v-if="!isGenerating">
            <div class="card-title"><i class="fa-solid fa-medal"></i> 골드셋 버전</div>
            <p v-if="selectedIsMerged" class="hint">합본은 만들 때 확정(v1)됩니다. 원본을 고쳤다면 합본을 다시 만들어 주세요.</p>
            <form v-else class="finalize-row" @submit.prevent="finalizeDataset">
              <input v-model="finalizeNote" placeholder="버전 메모 (예: 초기 30문항)" />
              <button type="submit" class="btn-primary" :disabled="!approvedCount">
                <i class="fa-solid fa-flag-checkered"></i> 승인 항목으로 골드셋 확정 ({{ approvedCount }}건)
              </button>
            </form>
            <table v-if="goldsets.length" class="data-table">
              <thead><tr><th class="center">버전</th><th class="center">항목 수</th><th>메모</th><th class="center">확정일</th></tr></thead>
              <tbody>
                <tr v-for="g in goldsets" :key="g.goldset_id">
                  <td class="center strong">v{{ g.version }}</td>
                  <td class="center">{{ g.item_count }}</td>
                  <td>{{ g.note || '-' }}</td>
                  <td class="center">{{ formatDate(g.created_at) }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="hint">확정된 골드셋이 없습니다. 승인 항목이 있으면 확정할 수 있습니다.</p>
          </section>
        </template>
      </main>
    </div>

    <!-- 테스트셋 자동 생성 모달 -->
    <div v-if="showCreateModal" class="modal-overlay" @pointerdown.self="showCreateModal = false">
      <div class="modal">
        <div class="modal-head"><h3><i class="fa-solid fa-wand-magic-sparkles"></i> 테스트셋 자동 생성</h3></div>
        <form @submit.prevent="submitCreateDataset">
          <div class="modal-body">
          <div class="form-row">
            <label>데이터셋 이름</label>
            <input v-model="createForm.name" placeholder="예: 산업안전법 QA v1" />
          </div>
          <div class="form-row">
            <label>대상 컬렉션</label>
            <select v-model="createForm.collection_id">
              <option :value="null" disabled>선택하세요</option>
              <!-- 관리자는 전체 사용자 컬렉션을 보므로 전역 유니크한 qdrant_name(ID_컬렉션명)으로 구분 -->
              <option v-for="c in collections" :key="c.collection_id" :value="c.collection_id">
                {{ c.qdrant_name || c.collection_name || `컬렉션 #${c.collection_id}` }}
              </option>
            </select>
          </div>
          <!-- 2026.11.19(sooyeon.choi) 추가 - 생성 방식. 단일 출처 = 질의 1건당 근거 청크 1개, 질문 유형 구분 없음 -->
          <div class="form-row">
            <label>생성 방식</label>
            <select v-model="createForm.generation_mode">
              <option value="typed">유형별 (사실·절차·비교·멀티홉)</option>
              <option value="law_article">법령 조항 (조항별 고르게)</option>
              <option value="single_section">일반 문서 (섹션별 고르게)</option>
            </select>
          </div>
          <div class="form-row">
            <label>생성 목표 건수 <span class="label-hint">5~200{{ createForm.generation_mode === 'law_article' ? ' · 법령별 60 권장' : '' }}</span></label>
            <input type="number" v-model="createForm.target_count" min="5" max="200" />
          </div>
          <template v-if="createForm.generation_mode === 'law_article'">
            <div class="form-row">
              <label>조항 직접 언급 비율 <span class="label-hint">% · 질문에 "제N조"를 넣는 비율</span></label>
              <input type="number" v-model="createForm.article_ref_ratio" min="0" max="100" />
            </div>
            <div class="form-row">
              <label class="chk"><input type="checkbox" v-model="createForm.include_annex" /> 별표 포함 <span class="label-hint">끄면 조문이 모자랄 때만 보충</span></label>
            </div>
          </template>
          <div class="form-row" v-if="createForm.generation_mode !== 'typed'">
            <label>질의ID 접두어 <span class="label-hint">예: 산안 → 산안-001 (비우면 Q)</span></label>
            <input v-model="createForm.query_id_prefix" maxlength="20" placeholder="Q" />
          </div>
          <div class="form-row">
            <label>생성 LLM</label>
            <select v-model="createForm.llm_backend">
              <option value="vllm">로컬 vLLM (무료)</option>
              <option value="openai">OpenAI</option>
            </select>
          </div>
          <!-- 2026.11.18(sooyeon.choi) 추가 - vLLM에 띄워진 모델 중 선택. 꺼진 모델은 선택 불가(데이터셋 생성 기간에만 켜는 모델 등) -->
          <div class="form-row" v-if="createForm.llm_backend === 'vllm'">
            <label>생성 모델</label>
            <select v-model="createForm.llm_model" :disabled="genModelsLoading">
              <option v-if="genModelsLoading" value="">불러오는 중...</option>
              <option
                v-for="m in genModels"
                :key="m.model"
                :value="m.model"
                :disabled="!m.available && !m.is_default"
              >{{ m.model }}{{ m.is_default ? ' (챗봇 기본)' : '' }}{{ m.available ? '' : ' (꺼짐)' }}</option>
            </select>
          </div>
          <!-- 2026.07.24(sychoi) 수정 - OpenAI 키는 최초 1회만 저장(관리자 계정 단위), 이후 재사용.
               ChatView처럼 서버에 암호화 저장되고 원문은 노출되지 않는다. -->
          <div class="form-row" v-if="createForm.llm_backend === 'openai'">
            <label>OpenAI API 키</label>
            <div v-if="hasOpenAIKey && !changingKey" class="key-saved">
              <span><i class="fa-solid fa-circle-check"></i> 저장된 키 사용 (재입력 불필요)</span>
              <button type="button" class="link-btn" @click="changingKey = true">키 변경</button>
            </div>
            <div v-else class="key-edit">
              <input type="password" v-model="keyInput" placeholder="sk-..." autocomplete="off" />
              <button type="button" class="btn-mini" :disabled="savingKey || !keyInput" @click="onSaveKey">
                {{ savingKey ? '저장 중…' : '키 저장' }}
              </button>
              <button v-if="hasOpenAIKey" type="button" class="link-btn" @click="changingKey = false">취소</button>
            </div>
            <span v-if="keyError" class="key-error">{{ keyError }}</span>
            <span v-else class="label-hint">키는 암호화되어 저장되며 이 계정의 평가 생성·실행에 재사용됩니다.</span>
          </div>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn-cancel" @click="showCreateModal = false">취소</button>
            <button type="submit" class="btn-primary" :disabled="!canCreateDataset">
              <i class="fa-solid fa-play"></i> 생성 시작
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- QA 수정 모달 (①축 기대동작·태그 포함) -->
    <div v-if="editingItem" class="modal-overlay" @pointerdown.self="cancelEdit">
      <div class="modal wide">
        <div class="modal-head"><h3><i class="fa-solid fa-pen"></i> QA 수정</h3></div>
        <div class="modal-body">
          <div class="form-row">
            <label>질문</label>
            <textarea v-model="editingItem.question" rows="3"></textarea>
          </div>
          <div class="form-row">
            <label>골드 답변(정답)</label>
            <textarea v-model="editingItem.gold_answer" rows="5"></textarea>
          </div>
          <div class="form-row">
            <label>기대 동작 <span class="label-hint">거절·가드레일 평가 분기 기준</span></label>
            <select v-model="editingItem.expected_behavior">
              <option v-for="o in EXPECTED_BEHAVIOR_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>검색 취약 태그 <span class="label-hint">세그먼트별 지표 집계에 사용</span></label>
            <div class="tag-picker">
              <label v-for="t in AVAILABLE_TAGS" :key="t.value" class="tag-chip"
                     :class="{ on: editingItem.tags.includes(t.value) }">
                <input type="checkbox" :checked="editingItem.tags.includes(t.value)" @change="toggleEditTag(t.value)" />
                {{ t.label }}
              </label>
            </div>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn-cancel" @click="cancelEdit">취소</button>
          <button class="btn-primary" @click="saveEdit">저장 (수정됨으로 표시)</button>
        </div>
      </div>
    </div>

    <!-- 2026.11.20(sooyeon.choi) 수정 - 합본 데이터셋 만들기 모달 -->
    <div v-if="showMergeModal" class="modal-overlay" @pointerdown.self="showMergeModal = false">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="merge-title">
        <div class="modal-head"><h3 id="merge-title"><i class="fa-solid fa-layer-group"></i> 합본 데이터셋 만들기</h3></div>
        <form @submit.prevent="submitMerge">
          <div class="modal-body">
          <div class="form-row">
            <label for="merge-name">합본 이름</label>
            <input id="merge-name" v-model="mergeName" maxlength="200" required />
          </div>
          <div class="form-row">
            <label>합칠 데이터셋 (고른 순서대로 이어 붙임)</label>
            <ol class="merge-list">
              <li v-for="d in mergeSelectedDatasets" :key="d.dataset_id">
                <b>{{ d.name }}</b> · 최신 확정본 · {{ d.collection_name }}
              </li>
            </ol>
          </div>
          <ul class="merge-rules">
            <li>질의ID는 원본 그대로 유지합니다(겹치면 만들지 않음).</li>
            <li>문항마다 원래 컬렉션에서 검색합니다. 지표 계산은 단독 평가와 같습니다(항목별 계산 → 전체 집계).</li>
            <li>만들면 바로 확정(v1)되어 평가 실행에서 고를 수 있습니다.</li>
            <li>원본을 고친 뒤에는 원본을 다시 확정하고 합본을 새로 만들어야 반영됩니다.</li>
          </ul>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn-cancel" :disabled="isMerging" @click="showMergeModal = false">취소</button>
            <button type="submit" class="btn-primary" :disabled="isMerging || !mergeName.trim()">
              <i class="fa-solid" :class="isMerging ? 'fa-spinner fa-spin' : 'fa-layer-group'"></i>
              {{ isMerging ? '만드는 중…' : '만들기' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 평가 데이터셋 삭제 확인 모달 -->
    <div v-if="deleteDatasetTarget" class="modal-overlay delete-dataset-overlay" @pointerdown.self="closeDeleteDatasetModal">
      <div class="modal confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-dataset-title">
        <div class="confirm-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <h3 id="delete-dataset-title">평가 데이터셋을 삭제할까요?</h3>
        <p>
          <strong>'{{ deleteDatasetTarget.name }}'</strong> 데이터셋과 확정된 골드셋,<br />
          관련 평가 실행 이력이 함께 삭제됩니다.<br />
          삭제 후에는 복구할 수 없습니다.
        </p>
        <div class="confirm-actions">
          <button class="btn-cancel" :disabled="isDeletingDataset" @click="closeDeleteDatasetModal">취소</button>
          <button class="btn-danger" :disabled="isDeletingDataset" @click="confirmDeleteDataset">
            <i class="fa-solid fa-trash"></i> {{ isDeletingDataset ? '삭제 중…' : '삭제' }}
          </button>
        </div>
      </div>
    </div>

    <AppToast :message="toast.visible ? toast.message : ''" :type="toast.type" admin-position
      @close="toast.visible = false" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import AdminSidebar from '../components/AdminSidebar.vue';
import AppToast from '../components/AppToast.vue';
import { useEvalDatasets } from '../composables/useEvalDatasets';
import { useEvalSettings } from '../composables/useEvalSettings';

const {
  isAdmin, displayName, sidebarOpen, isLoading, loadError, toast,
  datasets, selectedDataset, downloadingDatasetId, downloadingKind, isGenerating, generateProgress,
  displayQaItems, qaTotal, qaPage, qaTotalPages,
  statusFilter, typeFilter, undetectedOnly, undetectedCount,
  selectedQaIds, isAllSelected, isSelectingAll, toggleSelectAll, editingItem,
  approvedCount, datasetItemCount, showCreateModal, collections, createForm, goldsets, finalizeNote,
  genModels, genModelsLoading, loadGenModels,
  deleteDatasetTarget, isDeletingDataset,
  loadDatasets, loadCollections, selectDataset, downloadApprovedExcel, downloadTestsetExcel, applyFilters, goToPage, toggleExpand,
  createDataset, approveItem, rejectItem, bulkApprove, bulkReject,
  regeneratingQaId, canRegenerate, regenerateLabel, regenerateItem,
  startEdit, toggleEditTag, saveEdit, cancelEdit, finalizeDataset, deleteDataset,
  closeDeleteDatasetModal, confirmDeleteDataset, logout,
  statusLabel, typeLabel, reviewLabel, tagLabel, behaviorLabel, formatDate,
  EXPECTED_BEHAVIOR_OPTIONS, AVAILABLE_TAGS,
  // 2026.11.20(sooyeon.choi) 수정 - 합본 데이터셋
  mergeEnabled, mergeSelection, showMergeModal, mergeName, isMerging, mergeSelectedDatasets, mergeItemTotal,
  selectedIsMerged, isMerged, mergedSources, collectionLabel, canMergeSelect, isMergeSelected,
  toggleMergeSelect, clearMergeSelection, openMergeModal, submitMerge,
} = useEvalDatasets();

// 2026.07.24(sychoi) 추가 - 평가 전용 OpenAI 키 1회 저장/재사용
const { hasOpenAIKey, keyInput, savingKey, keyError, loadKeyStatus, saveKey } = useEvalSettings();
const changingKey = ref(false);
const onSaveKey = async () => { if (await saveKey()) changingKey.value = false; };
// 2026.11.18(sooyeon.choi) 수정 - vLLM은 모델 목록을 다 불러온 뒤에만 생성 가능
const canCreateDataset = computed(() => !isGenerating.value
  && (createForm.value.llm_backend !== 'openai' || hasOpenAIKey.value)
  && (createForm.value.llm_backend !== 'vllm' || !genModelsLoading.value));
const submitCreateDataset = () => {
  if (canCreateDataset.value) createDataset();
};

const openCreate = () => {
  showCreateModal.value = true;
  changingKey.value = false;
  loadCollections();
  loadKeyStatus();
  loadGenModels();
};

onMounted(loadDatasets);
</script>

<style scoped>
/* 헤더 고정 + 콘텐츠 영역만 스크롤 (기존 관리 화면과 동일 구조·여백) */
.admin-layout { display: flex; height: 100dvh; overflow: hidden; background: #f1f5f9; color: #0f172a;
  font-family: Inter, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; }
.admin-main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.admin-header { display: flex; justify-content: space-between; align-items: center;
  padding: 1.25rem 2rem; background: #fff; border-bottom: 1px solid #e2e8f0; flex-shrink: 0; gap: 1rem; }
.header-left { display: flex; align-items: center; gap: 0.75rem; }
.header-text h1 { font-size: 1.25rem; font-weight: 700; }
.header-text p { color: #64748b; font-size: 0.85rem; margin-top: 2px; }
.admin-badge { font-size: 0.65rem; background: #fef3c7; color: #b45309; padding: 2px 8px; border-radius: 10px; }
.btn-hamburger { display: none; background: none; border: none; font-size: 1.2rem; cursor: pointer; }
.admin-content { --evaluation-overview-card-height: clamp(390px, 45vh, 460px); flex: 1; padding: 1.5rem 2rem; overflow-y: auto; display: flex; flex-direction: column; gap: 1.25rem; }

.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 1.5rem; }
.card-title { font-weight: 700; font-size: 0.95rem; display: flex; align-items: center; gap: 8px; }
.card-title .count-hint { font-size: 0.8rem; font-weight: 400; color: #94a3b8; }
.card-title .refresh-btn { margin-left: auto; background: #fff; border: 1px solid #cbd5e1; border-radius: 6px;
  width: 30px; height: 30px; cursor: pointer; color: #475569; font-size: 0.8rem; flex-shrink: 0; }
.card-title .refresh-btn:hover:not(:disabled) { background: #f8fafc; color: #2563eb; }
.card-title .refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.card-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 0.9rem; }
.counts { font-size: 0.82rem; color: #64748b; }
.counts b { color: #0f172a; }
.warn-inline { color: #b45309; }
.muted { color: #94a3b8; }
.strong { font-weight: 600; }
.hint { color: #94a3b8; font-size: 0.82rem; }
/* 2026.11.20(sooyeon.choi) 수정 - 합본 데이터셋 */
.merge-bar { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 0.5rem 0.75rem; margin-bottom: 0.6rem; font-size: 0.82rem; color: #1e3a8a; }
.merge-sum { color: #475569; }
.merge-spacer { flex: 1; }
.merge-hint { color: #64748b; font-size: 0.78rem; margin: 0 0 0.5rem; }
.btn-merge { background: #7c3aed; border: 1px solid #7c3aed; color: #fff; border-radius: 6px; padding: 0.4rem 0.75rem; font-size: 0.78rem; cursor: pointer; display: inline-flex; gap: 5px; align-items: center; }
.btn-merge:disabled { opacity: 0.45; cursor: not-allowed; }
.merged-badge { display: inline-block; background: #f5f3ff; color: #7c3aed; border: 1px solid #ddd6fe; border-radius: 999px; padding: 0 0.5rem; font-size: 0.72rem; font-weight: 600; margin-left: 0.25rem; }
.merged-note { background: #f5f3ff; border: 1px dashed #a78bfa; color: #4c1d95; border-radius: 8px; padding: 0.6rem 0.8rem; margin: 0.6rem 0; font-size: 0.8rem; line-height: 1.6; }
.merge-list { margin: 0.2rem 0 0; padding-left: 1.2rem; font-size: 0.85rem; line-height: 1.7; color: #334155; }
.merge-rules { margin: 0.4rem 0 0; padding-left: 1.1rem; font-size: 0.78rem; line-height: 1.7; color: #64748b; }
.label-hint { font-weight: 400; color: #94a3b8; font-size: 0.72rem; margin-left: 4px; }
/* 2026.07.24(sychoi) 추가 - OpenAI 키 저장 UI */
.key-saved { display: flex; align-items: center; gap: 10px; font-size: 0.82rem; color: #15803d; }
.key-saved i { margin-right: 2px; }
.key-edit { display: flex; align-items: center; gap: 8px; }
.key-edit input { flex: 1; min-width: 0; }
.link-btn { background: none; border: none; color: #2563eb; font-size: 0.78rem; cursor: pointer; padding: 0; }
.key-error { color: #b91c1c; font-size: 0.75rem; }
.btn-mini { background: #fff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 0.4rem 0.7rem; font-size: 0.78rem; cursor: pointer; white-space: nowrap; }
.btn-mini:disabled { opacity: 0.5; cursor: not-allowed; }

/* 미선택 상태 안내 (데이터셋 목록 제목 바로 아래 한 줄) */
.list-guide { display: flex; align-items: center; gap: 6px; margin-top: 0.5rem;
  font-size: 0.82rem; color: #64748b; }
.list-guide i { color: #94a3b8; }
/* 안내 문구가 있을 때 아래 표와의 간격 확보 */
.list-guide + .dataset-table-scroll { margin-top: 1.7rem; }

.empty-state { text-align: center; color: #94a3b8; padding: 2rem 0; }
.empty-state i { font-size: 1.6rem; margin-bottom: 0.5rem; display: block; }

.data-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; margin-top: 0.9rem; }
.data-table th { text-align: left; color: #64748b; font-weight: 600; padding: 0.5rem 0.6rem; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }
.data-table td { padding: 0.55rem 0.6rem; border-bottom: 1px solid #f1f5f9; }
.data-table th.center, .data-table td.center { text-align: center; }
.data-table td.center .btn-delete-doc { margin: 0 auto; }
.data-table tbody tr { cursor: pointer; }
.data-table tbody tr:hover { background: #f8fafc; }
.data-table tbody tr.selected { background: #eff6ff; }
.dataset-list-card { height: var(--evaluation-overview-card-height); min-height: var(--evaluation-overview-card-height);
  box-sizing: border-box; display: flex; flex-direction: column; flex-shrink: 0; }
.dataset-table-scroll { flex: 1; min-height: 0; margin-top: 0.9rem;
  overflow: auto; border: 1px solid #e2e8f0; border-radius: 8px; }
.dataset-table-scroll:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }
.dataset-table-scroll .data-table { min-width: 900px; margin-top: 0; }
.dataset-table-scroll .data-table thead th { position: sticky; top: 0; z-index: 1; background: #fff; }

.filter-row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.9rem; }
.filter-row .spacer { flex: 1; }
.chk { font-size: 0.8rem; color: #475569; display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }

.qa-list { display: flex; flex-direction: column; gap: 0.6rem; }
.qa-item { border: 1px solid #e2e8f0; border-radius: 10px; padding: 0.85rem 1rem; }
.qa-item.approved { border-left: 3px solid #22c55e; }
.qa-item.rejected { border-left: 3px solid #ef4444; opacity: 0.7; }
.qa-item.edited { border-left: 3px solid #3b82f6; }
.qa-row { display: flex; gap: 0.75rem; align-items: flex-start; }
.qa-body { flex: 1; min-width: 0; cursor: pointer; }
.qa-meta { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; margin-bottom: 5px; }
.qa-question { font-weight: 600; font-size: 0.88rem; }
.qa-answer { font-size: 0.82rem; color: #475569; margin-top: 3px; }
.qa-actions { display: flex; gap: 2px; flex-shrink: 0; }
.qa-source { margin-top: 0.7rem; padding-top: 0.7rem; border-top: 1px dashed #e2e8f0; }
.source-meta { font-size: 0.76rem; color: #64748b; margin-bottom: 0.5rem; }
.chunk-text { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.6rem 0.7rem;
  font-size: 0.76rem; white-space: pre-wrap; word-break: break-word; margin-bottom: 0.4rem; max-height: 220px; overflow-y: auto; }

/* 배지는 좁아져도 세로로 쪼개지지 않도록 */
.qa-meta > span { white-space: nowrap; }
.type-badge { font-size: 0.7rem; background: #e0e7ff; color: #4338ca; padding: 2px 7px; border-radius: 8px; }
.status-badge { font-size: 0.7rem; padding: 2px 8px; border-radius: 10px; background: #e2e8f0; color: #475569; }
.status-badge.generating { background: #dbeafe; color: #1d4ed8; }
.status-badge.review, .status-badge.pending { background: #fef9c3; color: #a16207; }
.status-badge.finalized, .status-badge.approved, .status-badge.edited { background: #dcfce7; color: #15803d; }
.status-badge.failed, .status-badge.rejected { background: #fee2e2; color: #b91c1c; }
.warn-badge { font-size: 0.7rem; background: #fef3c7; color: #b45309; padding: 2px 7px; border-radius: 8px; }
.rank-badge { font-size: 0.7rem; background: #f1f5f9; color: #64748b; padding: 2px 7px; border-radius: 8px; }
.behavior-badge { font-size: 0.7rem; background: #fae8ff; color: #a21caf; padding: 2px 7px; border-radius: 8px; }
.tag { font-size: 0.68rem; background: #ecfeff; color: #0e7490; padding: 2px 6px; border-radius: 8px; }

.pagination { display: flex; justify-content: center; align-items: center; gap: 0.8rem; margin-top: 1rem; font-size: 0.82rem; }
.pagination button { background: #fff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 0.35rem 0.8rem; cursor: pointer; }
.pagination button:disabled { opacity: 0.45; cursor: not-allowed; }

.progress-head { display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem; margin-bottom: 0.6rem; }
.progress-bar { height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: #2563eb; transition: width 0.3s; }

.finalize-row { display: flex; gap: 0.5rem; margin-top: 0.9rem; }
.finalize-row input { flex: 1; }

.btn-primary { background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 0.55rem 1rem; font-size: 0.85rem; cursor: pointer; display: inline-flex; gap: 8px; align-items: center; white-space: nowrap; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: #fff; border: 1px solid #cbd5e1; color: #475569; border-radius: 6px; padding: 0.4rem 0.75rem; font-size: 0.78rem; cursor: pointer; display: inline-flex; gap: 5px; align-items: center; }
.btn-secondary.danger { color: #b91c1c; border-color: #fca5a5; }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-cancel { background: #fff; border: 1px solid #cbd5e1; color: #475569; border-radius: 8px; padding: 0.55rem 1.1rem; font-size: 0.85rem; cursor: pointer; }
/* 문서 관리(AdminView)의 .btn-delete-doc과 동일 스펙 */
.btn-delete-doc {
  background: none;
  border: 1px solid #fecaca;
  color: #dc2626;
  width: 30px;
  height: 30px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  transition: all 0.15s;
}
.btn-delete-doc:hover:not(:disabled) { background: #fef2f2; }
.btn-delete-doc:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-download-excel {
  background: none; border: 1px solid #bbf7d0; color: #15803d; width: 30px; height: 30px;
  border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center;
  margin: 0 auto; font-size: 0.8rem; transition: all 0.15s;
}
.btn-download-excel:hover:not(:disabled) { background: #f0fdf4; }
.btn-download-excel:disabled { opacity: 0.45; cursor: not-allowed; }
.icon-btn { background: none; border: 1px solid transparent; border-radius: 6px; width: 28px; height: 28px; cursor: pointer; color: #64748b; }
.icon-btn.approve:hover { color: #15803d; background: #dcfce7; }
.icon-btn.edit:hover { color: #1d4ed8; background: #dbeafe; }
.icon-btn.reject:hover { color: #b91c1c; background: #fee2e2; }

input, select, textarea { padding: 0.5rem 0.6rem; border: 1px solid #cbd5e1; border-radius: 8px;
  font-size: 0.85rem; box-sizing: border-box; font-family: inherit; }
input[type="checkbox"] { width: auto; padding: 0; border: none; flex-shrink: 0; margin-top: 3px; }
.filter-row select { min-width: 130px; }
.alert.error { background: #fef2f2; color: #b91c1c; padding: 0.7rem 1rem; border-radius: 8px; font-size: 0.85rem; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 60; padding: 1rem; }
.delete-dataset-overlay { left: 260px; align-items: flex-start; padding: clamp(96px, 18vh, 180px) 1rem 1rem; box-sizing: border-box; }
.modal { background: #fff; border-radius: 14px; width: min(440px, 92vw); box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18); max-height: 90vh; overflow-y: auto; }
.modal.wide { width: min(620px, 94vw); }
.confirm-modal { width: min(420px, 92vw); padding: 1.5rem; text-align: center; }
.confirm-icon { width: 48px; height: 48px; margin: 0 auto 0.9rem; border-radius: 50%; display: grid; place-items: center; background: #fee2e2; color: #dc2626; font-size: 1.2rem; }
.confirm-modal h3 { font-size: 1.05rem; font-weight: 700; color: #0f172a; }
.confirm-modal p { margin: 0.75rem 0 1.25rem; color: #64748b; font-size: 0.88rem; line-height: 1.65; }
.confirm-modal strong { color: #0f172a; }
.confirm-actions { display: flex; justify-content: flex-end; gap: 0.6rem; }
.btn-danger { background: #dc2626; color: #fff; border: none; border-radius: 8px; padding: 0.55rem 1rem; font-size: 0.85rem; cursor: pointer; }
.btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }
.modal-head { padding: 1.4rem 1.5rem 0.4rem; }
.modal-head h3 { font-size: 1.05rem; font-weight: 700; display: flex; align-items: center; gap: 9px; }
.modal-head h3 i { color: #2563eb; }
.modal-body { padding: 0.8rem 1.5rem 0.4rem; }
.modal-body .form-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 1rem; }
.modal-body .form-row label { font-size: 0.8rem; color: #475569; font-weight: 500; }
.modal-body input, .modal-body select, .modal-body textarea { width: 100%; padding: 0.6rem 0.7rem; border-radius: 10px; }
.modal-body input[type="checkbox"] { width: auto; }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; padding: 0.6rem 1.5rem 1.4rem; }
.tag-picker { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.tag-chip { font-size: 0.76rem; border: 1px solid #cbd5e1; border-radius: 14px; padding: 4px 11px; cursor: pointer; color: #64748b; }
.tag-chip.on { background: #ecfeff; border-color: #67e8f9; color: #0e7490; }
.tag-chip input { display: none; }

/* 2026.11.02(woojin.jung) 수정 - 반응형(태블릿/모바일) 대응 */
@media (max-width: 1024px) {
  .admin-header { padding: 1rem 1.5rem; }
  .admin-content { padding: 1.25rem 1.5rem; }
  .dataset-table-scroll .data-table td.center { white-space: nowrap; }
  .modal { width: min(440px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); }
  .modal.wide { width: min(620px, calc(100vw - 32px)); }
  .confirm-modal { width: min(420px, calc(100vw - 32px)); }
}
/* 2026.11.03(woojin.jung) 수정 - 태블릿 가로는 데스크톱, 세로는 모바일 레이아웃(사이드바 숨김) */
@media (max-width: 768px), (max-width: 1024px) and (orientation: portrait), (max-width: 1024px) and (max-height: 500px) {
  .btn-hamburger { display: grid; place-items: center; width: 40px; height: 40px; flex-shrink: 0; }
  .delete-dataset-overlay { left: 0; }
}
@media (max-width: 768px) {
  .admin-header { padding: 0.85rem 1rem; flex-wrap: wrap; }
  .header-left { min-width: 0; flex: 1 1 auto; }
  .header-text h1 { font-size: 1.1rem; }
  .header-text p { display: none; }
  .admin-content { padding: 1rem; gap: 1rem; }
  .card { padding: 1rem; }
  .delete-dataset-overlay { padding-top: 12vh; }
  .card-header { flex-wrap: wrap; gap: 0.4rem 1rem; }
  .card-header .card-title { min-width: 0; overflow-wrap: anywhere; }
  .filter-row select { flex: 1 1 130px; }
  .filter-row .spacer { flex-basis: 100%; height: 0; }
  .qa-row { flex-wrap: wrap; }
  .qa-actions { width: 100%; justify-content: flex-end; }
  .icon-btn { width: 40px; height: 40px; }
  .finalize-row { flex-wrap: wrap; }
  .finalize-row input { flex: 1 1 100%; }
  .finalize-row .btn-primary { flex: 1 1 100%; justify-content: center; white-space: normal; }
  .modal-head { padding: 1.1rem 1rem 0.3rem; }
  .modal-body { padding: 0.6rem 1rem 0.3rem; }
  .modal-actions { padding: 0.6rem 1rem 1rem; }
  .key-edit { flex-wrap: wrap; }
}
@media (max-width: 480px) {
  .header-actions .btn-primary { padding: 0.55rem 0.75rem; }
  .filter-row .btn-secondary { flex: 1 1 auto; justify-content: center; min-height: 36px; }
}
</style>
